// Package message provides point-to-point peer messaging on top of
// libp2p streams.
//
// Different from gossip: gossip is publish-subscribe (every peer in
// a topic sees every message). MessageService is one-to-one — a
// payer-earner ledger settlement, a project invite, a private RPC
// reply. Bilateral and confidential. We use a libp2p stream protocol
// rather than pubsub because pubsub broadcasts to the whole topic
// mesh, and most application messages don't want that exposure.
//
// Wire format on the stream:
//
//	[type_len:varint][type_bytes][payload_len:varint][payload_bytes]
//
// One message per stream. Stream is closed by the sender after the
// payload write; receiver detects EOF and dispatches.
//
// Self-loop suppression: the manager drops messages whose libp2p
// `from` field matches the local PeerID. Pubsub manager has the same
// guard for the same reason — it makes the application contract
// simpler.
//
// Signing: NOT done at this layer. libp2p's stream transport
// (Noise + QUIC) authenticates the peer at connection time, so the
// receiver knows who sent each stream. Application-layer payloads
// (ledger entries, attestation responses) carry their own
// signatures over canonical content. We don't double-sign envelopes
// here because there's no archive/forward path — every message goes
// directly from sender to receiver via Noise.
package message

import (
	"bufio"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"sync"
	"sync/atomic"
	"time"

	pb "gyza/netd/internal/grpc/proto"

	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/core/protocol"
)

// ProtocolID is the libp2p stream-protocol identifier. Bumping it is
// a hard fork — old daemons won't speak the new dialect.
const ProtocolID protocol.ID = "/gyza/message/1.0.0"

// SubscriberBufferSize bounds per-subscriber backpressure. A slow
// subscriber drops messages past this point; same engineering choice
// as gossip — one stuck consumer must not stall the entire pipeline.
const SubscriberBufferSize = 256

// MaxTypeLen is a sanity cap on message-type strings to bound the
// per-stream allocation. Application message types are short.
const MaxTypeLen = 256

// MaxPayloadLen bounds a single payload. Bigger payloads should use
// content-addressed artifact transfer, not direct messages.
const MaxPayloadLen = 4 * 1024 * 1024

// SendTimeout limits the time spent on a single Send call (open
// stream + handshake + write + close). A peer that's slow to
// respond shouldn't pin the gRPC handler forever.
const SendTimeout = 10 * time.Second

// Manager owns the stream-protocol handler and the per-RPC subscriber
// fan-out. One per daemon. Construct via NewManager; Close on
// shutdown to release the protocol handler.
type Manager struct {
	host host.Host
	logf func(string, ...any)

	mu     sync.RWMutex
	subs   map[uint64]*subscriberHandle
	subSeq atomic.Uint64

	closed atomic.Bool
}

type subscriberHandle struct {
	id     uint64
	ch     chan *pb.IncomingMessage
	filter map[string]struct{} // empty == receive all message types
}

// NewManager registers the libp2p stream handler and returns a
// Manager. The handler dispatches incoming messages to every
// subscriber whose filter matches.
func NewManager(h host.Host, logf func(string, ...any)) *Manager {
	if logf == nil {
		logf = func(string, ...any) {}
	}
	m := &Manager{
		host: h,
		logf: logf,
		subs: make(map[uint64]*subscriberHandle),
	}
	h.SetStreamHandler(ProtocolID, m.handleIncoming)
	return m
}

// Close removes the stream handler and closes every subscriber's
// channel. Idempotent. Subsequent Send calls fail with a clear
// "manager closed" error.
func (m *Manager) Close() error {
	if !m.closed.CompareAndSwap(false, true) {
		return nil
	}
	m.host.RemoveStreamHandler(ProtocolID)
	m.mu.Lock()
	subs := m.subs
	m.subs = nil
	m.mu.Unlock()
	for _, s := range subs {
		close(s.ch)
	}
	return nil
}

// =============================================================================
// Send
// =============================================================================

// Send opens a new stream to the target peer, writes a single
// (message_type, payload) frame, and closes. Returns the byte count
// written or an error.
//
// The stream is short-lived by design: each call open-write-close.
// libp2p multiplexes streams over the existing peer connection, so
// this is cheap.
func (m *Manager) Send(
	ctx context.Context,
	target peer.ID,
	messageType string,
	payload []byte,
) error {
	if m.closed.Load() {
		return errors.New("message manager closed")
	}
	if target == m.host.ID() {
		return errors.New("refusing to send message to self")
	}
	if err := validateFrame(messageType, payload); err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, SendTimeout)
	defer cancel()

	stream, err := m.host.NewStream(ctx, target, ProtocolID)
	if err != nil {
		return fmt.Errorf("open stream to %s: %w", target, err)
	}
	defer func() { _ = stream.Close() }()

	if err := writeFrame(stream, messageType, payload); err != nil {
		_ = stream.Reset()
		return fmt.Errorf("write frame: %w", err)
	}
	return nil
}

// Broadcast sends to every currently-connected peer except those in
// `exclude`. Best-effort: per-peer Send failures are logged and
// counted, not propagated. Returns the count of successful deliveries.
//
// For cross-cluster fan-out, prefer the gossip layer — it's
// mesh-routed and bandwidth-efficient. Broadcast here is for the
// occasional "tell every peer in my one-hop neighborhood" case
// (project invite to known peers, etc.).
func (m *Manager) Broadcast(
	ctx context.Context,
	messageType string,
	payload []byte,
	exclude []peer.ID,
) int {
	if m.closed.Load() {
		return 0
	}
	excludeSet := make(map[peer.ID]struct{}, len(exclude))
	for _, p := range exclude {
		excludeSet[p] = struct{}{}
	}
	excludeSet[m.host.ID()] = struct{}{}

	delivered := 0
	for _, p := range m.host.Network().Peers() {
		if _, skip := excludeSet[p]; skip {
			continue
		}
		if err := m.Send(ctx, p, messageType, payload); err != nil {
			m.logf("[message] broadcast to %s failed: %v", p, err)
			continue
		}
		delivered++
	}
	return delivered
}

// =============================================================================
// Subscribe
// =============================================================================

// Subscribe registers a fan-out slot. Returns a channel that receives
// every incoming message whose type matches the filter (or all
// messages if filter is empty). The returned cancel func unregisters
// and closes the channel. Caller MUST call cancel.
//
// gRPC SubscribeMessages handlers wrap this — one Manager call per
// open RPC stream.
func (m *Manager) Subscribe(messageTypes []string) (<-chan *pb.IncomingMessage, func()) {
	id := m.subSeq.Add(1)
	filter := make(map[string]struct{}, len(messageTypes))
	for _, t := range messageTypes {
		filter[t] = struct{}{}
	}
	h := &subscriberHandle{
		id:     id,
		ch:     make(chan *pb.IncomingMessage, SubscriberBufferSize),
		filter: filter,
	}
	m.mu.Lock()
	if m.subs != nil {
		m.subs[id] = h
	}
	m.mu.Unlock()
	cancel := func() {
		m.mu.Lock()
		if m.subs != nil {
			if _, ok := m.subs[id]; ok {
				delete(m.subs, id)
				close(h.ch)
			}
		}
		m.mu.Unlock()
	}
	return h.ch, cancel
}

// =============================================================================
// stream handler
// =============================================================================

// handleIncoming reads one frame off the stream, builds the
// IncomingMessage proto, and fans out to subscribers.
func (m *Manager) handleIncoming(stream network.Stream) {
	defer func() { _ = stream.Close() }()

	sender := stream.Conn().RemotePeer()
	if sender == m.host.ID() {
		// Shouldn't happen on real libp2p — same-host stream is a
		// configuration error. Defend anyway.
		return
	}

	messageType, payload, err := readFrame(stream)
	if err != nil {
		m.logf("[message] read from %s failed: %v", sender, err)
		return
	}

	// Sender pubkey: extract from the libp2p PeerID. For our system,
	// PeerID is derived from the compositor Ed25519 key, so this is
	// equivalent to "compositor pubkey hex".
	senderPubkeyHex := ""
	if pub, err := sender.ExtractPublicKey(); err == nil && pub != nil {
		if raw, err := pub.Raw(); err == nil {
			senderPubkeyHex = fmt.Sprintf("%x", raw)
		}
	}

	msg := &pb.IncomingMessage{
		SenderPeerId: sender.String(),
		SenderPubkey: senderPubkeyHex,
		MessageType:  messageType,
		Payload:      payload,
		TimestampNs:  time.Now().UnixNano(),
	}
	m.fanOut(msg)
}

func (m *Manager) fanOut(msg *pb.IncomingMessage) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, s := range m.subs {
		if len(s.filter) > 0 {
			if _, ok := s.filter[msg.MessageType]; !ok {
				continue
			}
		}
		select {
		case s.ch <- msg:
		default:
			m.logf("[message] subscriber %d full; dropped %s from %s",
				s.id, msg.MessageType, msg.SenderPeerId)
		}
	}
}

// =============================================================================
// frame encoding
// =============================================================================

func validateFrame(messageType string, payload []byte) error {
	if messageType == "" {
		return errors.New("message_type required")
	}
	if len(messageType) > MaxTypeLen {
		return fmt.Errorf("message_type too long (%d > %d)", len(messageType), MaxTypeLen)
	}
	if len(payload) > MaxPayloadLen {
		return fmt.Errorf("payload too large (%d > %d)", len(payload), MaxPayloadLen)
	}
	return nil
}

// writeFrame writes [type_len:uvarint][type][payload_len:uvarint][payload].
// Buffered so we don't issue tiny syscalls; flushed before return.
func writeFrame(w io.Writer, messageType string, payload []byte) error {
	bw := bufio.NewWriter(w)
	if err := writeUvarint(bw, uint64(len(messageType))); err != nil {
		return err
	}
	if _, err := bw.WriteString(messageType); err != nil {
		return err
	}
	if err := writeUvarint(bw, uint64(len(payload))); err != nil {
		return err
	}
	if _, err := bw.Write(payload); err != nil {
		return err
	}
	return bw.Flush()
}

// readFrame reverses writeFrame, with hard caps so a misbehaving
// peer can't allocate gigabytes via a forged length prefix.
func readFrame(r io.Reader) (string, []byte, error) {
	br := bufio.NewReader(r)
	typeLen, err := binary.ReadUvarint(br)
	if err != nil {
		return "", nil, fmt.Errorf("read type_len: %w", err)
	}
	if typeLen > MaxTypeLen {
		return "", nil, fmt.Errorf("type_len %d exceeds %d", typeLen, MaxTypeLen)
	}
	typeBuf := make([]byte, typeLen)
	if _, err := io.ReadFull(br, typeBuf); err != nil {
		return "", nil, fmt.Errorf("read type: %w", err)
	}
	payloadLen, err := binary.ReadUvarint(br)
	if err != nil {
		return "", nil, fmt.Errorf("read payload_len: %w", err)
	}
	if payloadLen > MaxPayloadLen {
		return "", nil, fmt.Errorf("payload_len %d exceeds %d", payloadLen, MaxPayloadLen)
	}
	payload := make([]byte, payloadLen)
	if _, err := io.ReadFull(br, payload); err != nil {
		return "", nil, fmt.Errorf("read payload: %w", err)
	}
	return string(typeBuf), payload, nil
}

func writeUvarint(w io.Writer, v uint64) error {
	var buf [binary.MaxVarintLen64]byte
	n := binary.PutUvarint(buf[:], v)
	_, err := w.Write(buf[:n])
	return err
}
