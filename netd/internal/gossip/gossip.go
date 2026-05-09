// Package gossip implements cross-cluster blackboard delta sync over
// libp2p gossipsub.
//
// Topology
//
// Each project has its own gossipsub topic:
//
//	/gyza/project/{project_id}/blackboard
//
// All cluster members of a project subscribe to that topic. Deltas are
// pushed to the topic and fan out through the gossipsub mesh to every
// subscriber within seconds (single-hop fan-out for small meshes; bounded
// hops for larger ones).
//
// Two layers of message authentication
//
// libp2p pubsub envelope: signed by the sender's libp2p host key (which
// in this system equals the compositor key — same Ed25519). Verified
// transparently by every receiver via WithStrictSignatureVerification,
// so spoofed sender PeerIDs are dropped at the wire layer before we
// see them.
//
// App-layer Ed25519 signature on the delta payload itself: BLAKE3
// hash of the protobuf-serialized delta with app_signature zeroed,
// signed by the compositor private key. Survives forwarding through
// relays / archives that strip the libp2p envelope, and is the durable
// proof "this delta was issued by compositor X" the application layer
// trusts for CRDT merging.
//
// Dedup
//
// Each delta carries a per-(sender, project) monotonically increasing
// sender_seq. Receivers drop any delta whose seq is ≤ the highest seq
// previously seen from that sender for that project. This eliminates
// duplicates from gossipsub mesh redelivery and from naive replays of
// old messages.
//
// Self-loop suppression: pubsub delivers our own published messages
// back to us. The receive loop drops messages where msg.GetFrom() ==
// our own PeerID, so the application doesn't have to filter.
//
// Subscriber fan-out
//
// One internal subscriber goroutine per joined topic feeds a slice of
// per-client channels held under the manager's mutex. PublishDelta
// stamps the sender fields and signs server-side; SubscribeDeltas (the
// gRPC server-streaming RPC) takes a slot in the fan-out and drops out
// when its context is cancelled.
package gossip

import (
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	pb "gyza/netd/internal/grpc/proto"
	"gyza/netd/internal/identity"

	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	pubsub "github.com/libp2p/go-libp2p-pubsub"
	"github.com/zeebo/blake3"
	"google.golang.org/protobuf/proto"
)

// TopicForProject returns the canonical gossipsub topic name for a
// given project_id. Bumping this format string is a hard fork — old
// nodes won't see new ones.
func TopicForProject(projectID string) string {
	return "/gyza/project/" + projectID + "/blackboard"
}

// ValidateProjectID rejects strings that would corrupt the topic
// naming scheme. We allow alphanumerics, dash, underscore, and dot —
// the conventional UUIDv4 / slugify alphabet — and cap at 128 chars.
//
// Why so strict: the project_id is interpolated raw into the topic
// path. A project_id containing "/" would split the topic into
// unexpected segments and route messages somewhere else; a NUL would
// be silently truncated in some libp2p layers. Refusing them is
// cheaper than auditing every layer downstream.
func ValidateProjectID(projectID string) error {
	if projectID == "" {
		return errors.New("project_id required")
	}
	if len(projectID) > 128 {
		return fmt.Errorf("project_id too long (%d > 128)", len(projectID))
	}
	for i, r := range projectID {
		switch {
		case r >= 'a' && r <= 'z':
		case r >= 'A' && r <= 'Z':
		case r >= '0' && r <= '9':
		case r == '-' || r == '_' || r == '.':
		default:
			return fmt.Errorf(
				"project_id contains invalid character %q at offset %d "+
					"(allowed: a-z A-Z 0-9 - _ .)", r, i,
			)
		}
	}
	return nil
}

// SubscriberBufferSize is the per-subscriber channel buffer. A slow
// subscriber loses deltas past this point (we drop, not block — one
// stuck subscriber must not stall the entire fan-out).
const SubscriberBufferSize = 256

// Manager owns one gossipsub instance per node and a set of joined
// project topics. Constructed once at daemon start; multiple gRPC
// callers (Python clients) share it through the GossipService surface.
type Manager struct {
	host     host.Host
	identity *identity.Identity
	ps       *pubsub.PubSub
	logf     func(string, ...any)

	mu       sync.RWMutex
	topics   map[string]*topicState        // project_id → topic state
	subs     map[uint64]*subscriberHandle  // subscriber_id → handle
	subSeq   atomic.Uint64                  // next subscriber id

	publishSeq map[string]int64 // project_id → next sender_seq
	pubSeqMu   sync.Mutex
}

// topicState bundles the per-topic primitives plus dedup state. The
// receive goroutine for a topic owns the lastSeen map; the manager
// only reads it under the topicState's own lock when listing peers.
type topicState struct {
	projectID string
	topic     *pubsub.Topic
	sub       *pubsub.Subscription
	cancel    context.CancelFunc

	dedupMu  sync.Mutex
	lastSeen map[string]int64 // sender_pubkey → highest seq applied
}

// subscriberHandle is one open SubscribeDeltas stream's slot in the
// fan-out. The channel buffer size and the projectFilter set are
// captured at subscription time.
type subscriberHandle struct {
	id              uint64
	ch              chan *pb.BlackboardDelta
	projectFilter   map[string]struct{} // empty == all joined projects
}

// NewManager constructs a gossipsub instance and a Manager wrapping it.
// One per daemon. Caller must Close() it on shutdown.
func NewManager(
	ctx context.Context,
	h host.Host,
	id *identity.Identity,
	logf func(string, ...any),
) (*Manager, error) {
	if h == nil {
		return nil, errors.New("gossip: host required")
	}
	if id == nil {
		return nil, errors.New("gossip: identity required")
	}
	if logf == nil {
		logf = func(string, ...any) {}
	}

	// Defaults are fine for Phase 3: gossipsub mesh of degree D=6,
	// validation workers, signing on. Strict signature verification
	// drops messages whose libp2p envelope signature doesn't match
	// the claimed sender — which is the only authentication layer
	// gossipsub offers natively.
	ps, err := pubsub.NewGossipSub(ctx, h,
		pubsub.WithMessageSigning(true),
		pubsub.WithStrictSignatureVerification(true),
	)
	if err != nil {
		return nil, fmt.Errorf("gossipsub init: %w", err)
	}
	return &Manager{
		host:       h,
		identity:   id,
		ps:         ps,
		logf:       logf,
		topics:     make(map[string]*topicState),
		subs:       make(map[uint64]*subscriberHandle),
		publishSeq: make(map[string]int64),
	}, nil
}

// JoinProject subscribes to a project's gossip topic. Idempotent: a
// second join returns the same topic without errors. Returns the live
// mesh-peer count for the topic at join time (often 0 if no other
// peer is yet connected; gossipsub fills the mesh asynchronously).
func (m *Manager) JoinProject(ctx context.Context, projectID string) (int, error) {
	if err := ValidateProjectID(projectID); err != nil {
		return 0, err
	}
	m.mu.Lock()
	if st, ok := m.topics[projectID]; ok {
		m.mu.Unlock()
		return len(st.topic.ListPeers()), nil
	}

	topicName := TopicForProject(projectID)
	topic, err := m.ps.Join(topicName)
	if err != nil {
		m.mu.Unlock()
		return 0, fmt.Errorf("pubsub.Join %s: %w", topicName, err)
	}
	sub, err := topic.Subscribe()
	if err != nil {
		_ = topic.Close()
		m.mu.Unlock()
		return 0, fmt.Errorf("topic.Subscribe %s: %w", topicName, err)
	}

	subCtx, cancel := context.WithCancel(context.Background())
	st := &topicState{
		projectID: projectID,
		topic:     topic,
		sub:       sub,
		cancel:    cancel,
		lastSeen:  make(map[string]int64),
	}
	m.topics[projectID] = st
	m.mu.Unlock()

	go m.receiveLoop(subCtx, st)
	m.logf("[gossip] joined project %s", projectID)
	return len(topic.ListPeers()), nil
}

// LeaveProject unsubscribes and tears down the topic. Idempotent.
func (m *Manager) LeaveProject(projectID string) error {
	m.mu.Lock()
	st, ok := m.topics[projectID]
	if !ok {
		m.mu.Unlock()
		return nil
	}
	delete(m.topics, projectID)
	m.mu.Unlock()

	st.cancel()
	st.sub.Cancel()
	if err := st.topic.Close(); err != nil {
		return fmt.Errorf("topic.Close: %w", err)
	}
	m.logf("[gossip] left project %s", projectID)
	return nil
}

// ListProjects returns the project_ids the daemon is currently
// subscribed to. Order is unspecified.
func (m *Manager) ListProjects() []string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]string, 0, len(m.topics))
	for p := range m.topics {
		out = append(out, p)
	}
	return out
}

// MeshPeers reports how many peers gossipsub currently has in this
// project's mesh. Useful for diagnostics; "0" right after joining is
// normal — the mesh fills as identify exchanges complete.
func (m *Manager) MeshPeers(projectID string) int {
	m.mu.RLock()
	st, ok := m.topics[projectID]
	m.mu.RUnlock()
	if !ok {
		return 0
	}
	return len(st.topic.ListPeers())
}

// PublishDelta stamps the delta's identity / seq / timestamp / app
// signature server-side, then publishes it on the project's topic.
// Returns the assigned sender_seq.
//
// Mutation of the input: PublishDelta overwrites sender_compositor_pubkey,
// sender_seq, timestamp_ns, and app_signature on `d`. Caller's other
// fields (project_id, payload) are preserved.
func (m *Manager) PublishDelta(ctx context.Context, d *pb.BlackboardDelta) (int64, error) {
	if d == nil {
		return 0, errors.New("nil delta")
	}
	if err := ValidateProjectID(d.ProjectId); err != nil {
		return 0, fmt.Errorf("delta.project_id: %w", err)
	}
	m.mu.RLock()
	st, ok := m.topics[d.ProjectId]
	m.mu.RUnlock()
	if !ok {
		return 0, fmt.Errorf("not joined to project %s", d.ProjectId)
	}

	d.SenderCompositorPubkey = m.identity.PubKeyHex
	d.SenderSeq = m.nextSeq(d.ProjectId)
	d.TimestampNs = time.Now().UnixNano()
	d.AppSignature = nil

	// Sign over the wire-format bytes with app_signature zeroed.
	// Deterministic marshal is REQUIRED here: a non-deterministic
	// encoding would produce different bytes on the verify side
	// (re-marshal of the same struct with sig zeroed) than on the
	// sign side, and verification would fail. The default
	// proto.Marshal happens to be stable within one binary today,
	// but isn't promised across protobuf library versions — making
	// it explicit guards against a future bump silently breaking
	// the signing contract.
	det := proto.MarshalOptions{Deterministic: true}
	preSig, err := det.Marshal(d)
	if err != nil {
		return 0, fmt.Errorf("marshal pre-sig: %w", err)
	}
	digest := blake3.Sum256(preSig)
	sig := m.identity.SignBytes(digest[:])
	d.AppSignature = sig

	final, err := det.Marshal(d)
	if err != nil {
		return 0, fmt.Errorf("marshal final: %w", err)
	}

	if err := st.topic.Publish(ctx, final); err != nil {
		return 0, fmt.Errorf("publish: %w", err)
	}
	return d.SenderSeq, nil
}

// nextSeq increments and returns the per-project send sequence number.
// Compatible with the spec's "vector clock" semantic when there's only
// one entry per (sender, project) — which there always is in this
// design (one daemon == one compositor).
func (m *Manager) nextSeq(projectID string) int64 {
	m.pubSeqMu.Lock()
	defer m.pubSeqMu.Unlock()
	m.publishSeq[projectID]++
	return m.publishSeq[projectID]
}

// Subscribe registers a fan-out slot. Returns a buffered channel that
// receives every delta from any of the projects in projectFilter
// (empty filter == every project the daemon is joined to). The
// returned cancel func unregisters and closes the channel; callers
// MUST call it (typical pattern: defer cancel()).
//
// The channel is closed by Close() on shutdown so the gRPC handler
// can detect the manager going away.
func (m *Manager) Subscribe(
	projectFilter []string,
) (<-chan *pb.BlackboardDelta, func()) {
	id := m.subSeq.Add(1)
	filter := make(map[string]struct{}, len(projectFilter))
	for _, p := range projectFilter {
		filter[p] = struct{}{}
	}
	h := &subscriberHandle{
		id:            id,
		ch:            make(chan *pb.BlackboardDelta, SubscriberBufferSize),
		projectFilter: filter,
	}
	m.mu.Lock()
	m.subs[id] = h
	m.mu.Unlock()
	cancel := func() {
		m.mu.Lock()
		if _, ok := m.subs[id]; ok {
			delete(m.subs, id)
			close(h.ch)
		}
		m.mu.Unlock()
	}
	return h.ch, cancel
}

// receiveLoop is the per-topic goroutine. Reads messages from the
// libp2p subscription, drops self-loops + stale-seq replays, verifies
// the app-layer signature, and dispatches to subscribers via the
// fan-out under the manager's lock.
func (m *Manager) receiveLoop(ctx context.Context, st *topicState) {
	for {
		msg, err := st.sub.Next(ctx)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return
			}
			m.logf("[gossip] %s receive error: %v", st.projectID, err)
			return
		}
		// Self-loop suppression: gossipsub delivers our own messages
		// back to us. We don't want to push them to subscribers — the
		// publishing path on the same daemon already informed local
		// state.
		if msg.GetFrom() == m.host.ID() {
			continue
		}

		d := &pb.BlackboardDelta{}
		if err := proto.Unmarshal(msg.Data, d); err != nil {
			m.logf("[gossip] %s unmarshal: %v", st.projectID, err)
			continue
		}
		if d.ProjectId != st.projectID {
			// Topic mismatch — sender packed the wrong project_id.
			// Drop; we can't trust them about anything else either.
			continue
		}
		if !m.verifyAppSignature(d) {
			m.logf("[gossip] %s rejected: bad app signature from %s",
				st.projectID, abbrev(d.SenderCompositorPubkey))
			continue
		}
		if !m.checkAndUpdateSeq(st, d) {
			continue // duplicate / stale
		}
		m.fanOut(d)
	}
}

// verifyAppSignature recomputes the BLAKE3 digest over the delta with
// app_signature zeroed and verifies the Ed25519 signature against the
// claimed sender pubkey. Returns false on any failure.
//
// MUST use the same MarshalOptions as PublishDelta — see the Deterministic
// comment there for why.
func (m *Manager) verifyAppSignature(d *pb.BlackboardDelta) bool {
	if len(d.AppSignature) != ed25519.SignatureSize {
		return false
	}
	pubBytes, err := hex.DecodeString(d.SenderCompositorPubkey)
	if err != nil || len(pubBytes) != ed25519.PublicKeySize {
		return false
	}
	sig := d.AppSignature
	d.AppSignature = nil
	preSig, err := proto.MarshalOptions{Deterministic: true}.Marshal(d)
	d.AppSignature = sig // restore — caller may want to keep the signed bytes around
	if err != nil {
		return false
	}
	digest := blake3.Sum256(preSig)
	return ed25519.Verify(ed25519.PublicKey(pubBytes), digest[:], sig)
}

// checkAndUpdateSeq dedupes by (sender, seq). Returns true iff this
// delta is newer than anything previously seen from the same sender
// on this topic.
func (m *Manager) checkAndUpdateSeq(st *topicState, d *pb.BlackboardDelta) bool {
	st.dedupMu.Lock()
	defer st.dedupMu.Unlock()
	last := st.lastSeen[d.SenderCompositorPubkey]
	if d.SenderSeq <= last {
		return false
	}
	st.lastSeen[d.SenderCompositorPubkey] = d.SenderSeq
	return true
}

// fanOut sends the delta to every matching subscriber. Slow subscribers
// (channel full) drop the delta — they'll need to anti-entropy back
// into sync via the application's own catch-up path. This is by design:
// one stuck subscriber must not stall the entire pipeline.
func (m *Manager) fanOut(d *pb.BlackboardDelta) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, s := range m.subs {
		if len(s.projectFilter) > 0 {
			if _, ok := s.projectFilter[d.ProjectId]; !ok {
				continue
			}
		}
		select {
		case s.ch <- d:
		default:
			// Channel full — log once per dropped delta. Loudly: a
			// dropped delta is a correctness gap the application has
			// to compensate for.
			m.logf("[gossip] subscriber %d full; dropped delta seq=%d from %s",
				s.id, d.SenderSeq, abbrev(d.SenderCompositorPubkey))
		}
	}
}

// Close tears down every subscription and topic. Idempotent.
func (m *Manager) Close() error {
	m.mu.Lock()
	subs := m.subs
	m.subs = nil
	topics := m.topics
	m.topics = nil
	m.mu.Unlock()

	for _, h := range subs {
		close(h.ch)
	}
	for _, st := range topics {
		st.cancel()
		st.sub.Cancel()
		_ = st.topic.Close()
	}
	return nil
}

// abbrev shortens a hex pubkey for log lines.
func abbrev(s string) string {
	if len(s) > 16 {
		return s[:16] + "…"
	}
	return s
}

// ExtractSenderID returns the libp2p PeerID of the original publisher
// of a pubsub message. Wrapper helps tests that want to assert on
// sender authenticity post-validation.
func ExtractSenderID(msg *pubsub.Message) peer.ID {
	if msg == nil {
		return ""
	}
	return msg.GetFrom()
}
