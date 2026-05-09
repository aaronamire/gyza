// Package grpcsrv implements the gRPC server side of the gyza-netd
// daemon. It exposes five services over a Unix-domain socket:
//
//	NodeService      — local identity & status
//	DiscoveryService — DHT-backed agent advertisement / search
//	PeerService      — direct peer connections
//	MessageService   — arbitrary peer messaging
//	DHTService       — raw DHT put/get/delete
//
// Sessions 1 and 2 are wired (NodeService, DiscoveryService).
// Sessions 3 and 4 fill in PeerService / MessageService /
// GossipService. The not-yet-wired methods return Unimplemented with
// an explicit "lands in Session N" message so a Python caller hitting
// one early gets a clear error.
package grpcsrv

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"sync/atomic"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"gyza/netd/internal/capability"
	"gyza/netd/internal/dht"
	"gyza/netd/internal/gossip"
	"gyza/netd/internal/identity"
	"gyza/netd/internal/message"
	"gyza/netd/internal/nat"

	libp2phost "github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/multiformats/go-multiaddr"

	pb "gyza/netd/internal/grpc/proto"
)

// GyzaVersion is reported by NodeService.GetNodeInfo. Bumped per
// release; gates compatibility checks once federation is real.
const GyzaVersion = "phase3-session5"

// defaultConnectTimeout bounds PeerService.Connect when the caller
// doesn't override. Long enough for a relay-mediated DCUtR upgrade,
// short enough that a stuck connection doesn't pin a gRPC handler
// indefinitely.
const defaultConnectTimeout = 30 * time.Second

// NetdServer holds the runtime state shared across all five services.
//
// Why not split per-service: the same identity, host, DHT, and gossip
// objects are reused in every service. Keeping them on one struct
// avoids hand-wired plumbing through dependency-injection ceremony.
//
// host and dht are nullable so unit tests can construct a NetdServer
// without spinning up libp2p. NodeService.GetNodeInfo degrades
// gracefully (returns identity-only fields) when host == nil.
type NetdServer struct {
	pb.UnimplementedNodeServiceServer
	pb.UnimplementedDiscoveryServiceServer
	pb.UnimplementedPeerServiceServer
	pb.UnimplementedMessageServiceServer
	pb.UnimplementedDHTServiceServer
	pb.UnimplementedGossipServiceServer
	pb.UnimplementedCapabilityServiceServer

	identity   *identity.Identity
	host       libp2phost.Host
	dht        *dht.GyzaDHT
	natMgr     *nat.Manager
	gossip     *gossip.Manager
	capability *capability.ChallengeManager
	msg        *message.Manager
	startNs    int64
}

// NewNetdServer constructs the shared server state. host, gdht, natMgr,
// gossipMgr, and capMgr may be nil — the server still answers
// GetNodeInfo with whatever identity info is available, so unit tests
// can exercise the serve/stop path without libp2p in the loop.
func NewNetdServer(
	id *identity.Identity,
	h libp2phost.Host,
	gdht *dht.GyzaDHT,
	natMgr *nat.Manager,
	gossipMgr *gossip.Manager,
	capMgr *capability.ChallengeManager,
	msgMgr *message.Manager,
) *NetdServer {
	return &NetdServer{
		identity:   id,
		host:       h,
		dht:        gdht,
		natMgr:     natMgr,
		gossip:     gossipMgr,
		capability: capMgr,
		msg:        msgMgr,
		startNs:    time.Now().UnixNano(),
	}
}

// =============================================================================
// NodeService
// =============================================================================

// GetNodeInfo returns the daemon's libp2p PeerID, compositor pubkey
// (hex), listen multiaddrs, and version. PeerID falls back to the
// identity-derived value if the libp2p host hasn't been started.
func (s *NetdServer) GetNodeInfo(_ context.Context, _ *pb.Empty) (*pb.NodeInfo, error) {
	if s.identity == nil {
		return nil, status.Error(codes.FailedPrecondition, "no identity loaded")
	}
	peerID := s.identity.PeerID.String()
	listen := []string{}
	if s.host != nil {
		peerID = s.host.ID().String()
		for _, a := range s.host.Addrs() {
			listen = append(listen, a.String())
		}
	}
	return &pb.NodeInfo{
		PeerId:           peerID,
		CompositorPubkey: s.identity.PubKeyHex,
		ListenAddrs:      listen,
		GyzaVersion:      GyzaVersion,
	}, nil
}

// GetStatus reports the daemon's runtime stats. Routing-table size and
// connected-peer counts come from libp2p when the host is wired; NAT
// fields come from the nat.Manager.
func (s *NetdServer) GetStatus(_ context.Context, _ *pb.Empty) (*pb.NodeStatus, error) {
	uptimeSec := (time.Now().UnixNano() - s.startNs) / int64(time.Second)
	st := &pb.NodeStatus{UptimeSeconds: uptimeSec}
	if s.host != nil {
		st.ConnectedPeers = int32(len(s.host.Network().Peers()))
	}
	if s.dht != nil {
		st.DhtRoutingTableSize = int32(s.dht.RoutingTableSize())
	}
	if s.natMgr != nil {
		st.NatTraversalAvailable = s.natMgr.Available()
		st.ObservedAddr = s.natMgr.ObservedAddr()
	}
	return st, nil
}

// =============================================================================
// All other services — explicit Session-1 stubs.
//
// We override the embedded UnimplementedXxxServer's auto-Unimplemented
// answers with status.Error(Unimplemented, "land in session N") so the
// failure mode is a *deliberate* gRPC-Unimplemented with a useful
// message, not an accidental "method not found". Same effect, better
// debuggability when a Python caller hits one prematurely.
// =============================================================================

const (
	notReadySession2 = "wired in Phase 3 Session 2"
	notReadySession3 = "wired in Phase 3 Session 3"
	notReadySession4 = "wired in Phase 3 Session 4"
)

// DiscoveryService

// PublishAgent advertises the agent on the DHT. The bucket id is
// recomputed server-side from the embedding regardless of any value
// the client supplied — the client doesn't get to lie about LSH.
func (s *NetdServer) PublishAgent(ctx context.Context, ad *pb.AgentAdvertisement) (*pb.PublishResult, error) {
	if s.dht == nil {
		return nil, status.Error(codes.Unavailable, "DHT not initialized")
	}
	if ad == nil {
		return nil, status.Error(codes.InvalidArgument, "advertisement is nil")
	}
	dhtKey, err := s.dht.PublishAgent(ctx, ad)
	if err != nil {
		return &pb.PublishResult{Success: false, Error: err.Error()}, nil
	}
	return &pb.PublishResult{Success: true, DhtKey: dhtKey}, nil
}

// FindAgents streams up to k matching advertisements ordered by
// cosine similarity, descending. The stream closes when results are
// exhausted; an empty result yields an immediate close.
func (s *NetdServer) FindAgents(q *pb.AgentQuery, stream pb.DiscoveryService_FindAgentsServer) error {
	if s.dht == nil {
		return status.Error(codes.Unavailable, "DHT not initialized")
	}
	if q == nil {
		return status.Error(codes.InvalidArgument, "query is nil")
	}
	emb, err := dht.DecodeF32LEAvailable(q.QueryEmbedding)
	if err != nil {
		return status.Error(codes.InvalidArgument, err.Error())
	}
	if len(emb) != dht.EmbeddingDim {
		return status.Errorf(codes.InvalidArgument,
			"query_embedding has %d dims, want %d", len(emb), dht.EmbeddingDim)
	}
	results, err := s.dht.FindAgents(stream.Context(), emb, int(q.K), q.MinTier, q.MinReputation)
	if err != nil {
		return status.Error(codes.Internal, err.Error())
	}
	for _, ad := range results {
		if err := stream.Send(ad); err != nil {
			return err
		}
	}
	return nil
}

// UnpublishAgent removes the agent from local state and re-publishes
// affected buckets. Signature verification is intentionally weak in
// Session 2 — the unpublish request authorizes only against the
// compositor that originally published the agent. Strict cross-node
// authorization lands in Session 5 (proof-of-capability).
func (s *NetdServer) UnpublishAgent(ctx context.Context, req *pb.UnpublishRequest) (*pb.Empty, error) {
	if s.dht == nil {
		return nil, status.Error(codes.Unavailable, "DHT not initialized")
	}
	if req == nil || req.AgentPubkey == "" {
		return nil, status.Error(codes.InvalidArgument, "agent_pubkey required")
	}
	if err := s.dht.UnpublishAgent(ctx, req.AgentPubkey); err != nil {
		return nil, status.Error(codes.Internal, err.Error())
	}
	return &pb.Empty{}, nil
}

// =============================================================================
// PeerService
// =============================================================================

// Connect dials the peer at the given multiaddr. NAT traversal is
// transparent: libp2p's hole-punch service auto-upgrades from a
// circuit-relay-mediated dial to a direct connection when DCUtR is
// configured. Caller can pin an expected_pubkey to refuse connections
// to peers whose PeerID doesn't match the configured identity.
func (s *NetdServer) Connect(ctx context.Context, req *pb.ConnectRequest) (*pb.ConnectResult, error) {
	if s.host == nil {
		return nil, status.Error(codes.Unavailable, "host not initialized")
	}
	if req == nil || req.Multiaddr == "" {
		return nil, status.Error(codes.InvalidArgument, "multiaddr required")
	}
	ma, err := multiaddr.NewMultiaddr(req.Multiaddr)
	if err != nil {
		return &pb.ConnectResult{Success: false, Error: fmt.Sprintf("bad multiaddr: %v", err)}, nil
	}
	target, err := peer.AddrInfoFromP2pAddr(ma)
	if err != nil {
		return &pb.ConnectResult{Success: false, Error: fmt.Sprintf("bad addrinfo: %v", err)}, nil
	}
	// Optional identity guard: reject if the multiaddr's encoded peer
	// ID doesn't correspond to the expected pubkey hex. We accept both
	// "matches" (compositor pubkey hex) and "no expected_pubkey" cases.
	if req.ExpectedPubkey != "" {
		if !peerIDMatchesPubkeyHex(target.ID, req.ExpectedPubkey) {
			return &pb.ConnectResult{
				Success: false,
				Error:   fmt.Sprintf("peer id %s does not match expected pubkey", target.ID),
			}, nil
		}
	}

	connectFn := s.host.Connect
	if s.natMgr != nil {
		connectFn = func(ctx context.Context, p peer.AddrInfo) error {
			return s.natMgr.ConnectWithNAT(ctx, p, defaultConnectTimeout)
		}
	}
	if err := connectFn(ctx, *target); err != nil {
		return &pb.ConnectResult{Success: false, Error: err.Error()}, nil
	}
	return &pb.ConnectResult{
		Success:        true,
		PeerId:         target.ID.String(),
		VerifiedPubkey: req.ExpectedPubkey,
	}, nil
}

// Disconnect closes all open connections to the peer. Best-effort: if
// the peer is already disconnected, returns success.
func (s *NetdServer) Disconnect(_ context.Context, req *pb.DisconnectRequest) (*pb.Empty, error) {
	if s.host == nil {
		return nil, status.Error(codes.Unavailable, "host not initialized")
	}
	if req == nil || req.PeerId == "" {
		return nil, status.Error(codes.InvalidArgument, "peer_id required")
	}
	pid, err := peer.Decode(req.PeerId)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "bad peer_id: %v", err)
	}
	if err := s.host.Network().ClosePeer(pid); err != nil {
		return nil, status.Errorf(codes.Internal, "close peer: %v", err)
	}
	return &pb.Empty{}, nil
}

// ListPeers returns the currently connected peers with whatever info
// we can populate without an extra round-trip. multiaddr is the first
// observed connection's remote address; compositor_pubkey is empty in
// Session 3 (filled in Session 5 via attestation cert lookup).
func (s *NetdServer) ListPeers(_ context.Context, _ *pb.Empty) (*pb.PeerList, error) {
	out := &pb.PeerList{}
	if s.host == nil {
		return out, nil
	}
	for _, pid := range s.host.Network().Peers() {
		out.Peers = append(out.Peers, s.peerInfoFor(pid))
	}
	return out, nil
}

// GetPeerInfo returns the same per-peer view as ListPeers but for one
// specific peer id.
func (s *NetdServer) GetPeerInfo(_ context.Context, req *pb.PeerInfoRequest) (*pb.PeerInfo, error) {
	if s.host == nil {
		return nil, status.Error(codes.Unavailable, "host not initialized")
	}
	if req == nil || req.PeerId == "" {
		return nil, status.Error(codes.InvalidArgument, "peer_id required")
	}
	pid, err := peer.Decode(req.PeerId)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "bad peer_id: %v", err)
	}
	if s.host.Network().Connectedness(pid) != network.Connected {
		return nil, status.Error(codes.NotFound, "peer not connected")
	}
	return s.peerInfoFor(pid), nil
}

// peerInfoFor builds a PeerInfo proto from libp2p network state. Stats
// fields (messages_sent, messages_received, attestation_tier) are zero
// in Session 3 — they get populated in Session 4 (gossip) and Session 5
// (attestation), respectively. Connection time is approximated as
// "earliest connection of the open conns" so the value is stable across
// individual stream open/close events.
//
// Session 8: compositor_pubkey is now extracted from the libp2p PeerID.
// Ed25519 PeerIDs embed the public key in the multihash, so we can
// recover it deterministically without round-tripping to the peer.
// Without this, PeerRegistry on the Python side has no way to resolve
// inbound peers' compositor pubkey — settlement silently skips every
// remote-creator entry because the registry returns None.
func (s *NetdServer) peerInfoFor(pid peer.ID) *pb.PeerInfo {
	info := &pb.PeerInfo{PeerId: pid.String()}
	if pub, err := pid.ExtractPublicKey(); err == nil && pub != nil {
		if raw, err := pub.Raw(); err == nil && len(raw) == 32 {
			info.CompositorPubkey = fmt.Sprintf("%x", raw)
		}
	}
	if s.host == nil {
		return info
	}
	conns := s.host.Network().ConnsToPeer(pid)
	if len(conns) > 0 {
		info.Multiaddr = conns[0].RemoteMultiaddr().String()
		info.LastSeen = time.Now().UnixNano()
		earliest := conns[0].Stat().Opened
		for _, c := range conns[1:] {
			if t := c.Stat().Opened; !t.IsZero() && (earliest.IsZero() || t.Before(earliest)) {
				earliest = t
			}
		}
		if !earliest.IsZero() {
			info.ConnectedAt = earliest.UnixNano()
		}
	}
	return info
}

// peerIDMatchesPubkeyHex returns true if the libp2p PeerID was derived
// from an Ed25519 public key whose 32-byte representation hex-encodes
// to the same string as the expected pubkey. This is how Python-side
// compositor pubkeys (32-byte Ed25519, hex) map to libp2p PeerIDs.
func peerIDMatchesPubkeyHex(pid peer.ID, expectedHex string) bool {
	if expectedHex == "" {
		return true
	}
	pub, err := pid.ExtractPublicKey()
	if err != nil || pub == nil {
		return false
	}
	raw, err := pub.Raw()
	if err != nil {
		return false
	}
	if len(raw) != 32 {
		return false
	}
	return fmt.Sprintf("%x", raw) == expectedHex
}

// =============================================================================
// GossipService — cross-cluster blackboard delta sync.
// =============================================================================

func (s *NetdServer) JoinProject(ctx context.Context, req *pb.JoinProjectRequest) (*pb.JoinProjectResult, error) {
	if s.gossip == nil {
		return nil, status.Error(codes.Unavailable, "gossip not initialized")
	}
	if req == nil || req.ProjectId == "" {
		return nil, status.Error(codes.InvalidArgument, "project_id required")
	}
	mesh, err := s.gossip.JoinProject(ctx, req.ProjectId)
	if err != nil {
		return &pb.JoinProjectResult{Success: false, Error: err.Error()}, nil
	}
	return &pb.JoinProjectResult{
		Success:   true,
		Topic:     gossip.TopicForProject(req.ProjectId),
		MeshPeers: int32(mesh),
	}, nil
}

func (s *NetdServer) LeaveProject(_ context.Context, req *pb.LeaveProjectRequest) (*pb.Empty, error) {
	if s.gossip == nil {
		return nil, status.Error(codes.Unavailable, "gossip not initialized")
	}
	if req == nil || req.ProjectId == "" {
		return nil, status.Error(codes.InvalidArgument, "project_id required")
	}
	if err := s.gossip.LeaveProject(req.ProjectId); err != nil {
		return nil, status.Errorf(codes.Internal, "leave: %v", err)
	}
	return &pb.Empty{}, nil
}

func (s *NetdServer) PublishDelta(ctx context.Context, req *pb.PublishDeltaRequest) (*pb.PublishDeltaResult, error) {
	if s.gossip == nil {
		return nil, status.Error(codes.Unavailable, "gossip not initialized")
	}
	if req == nil || req.Delta == nil {
		return nil, status.Error(codes.InvalidArgument, "delta required")
	}
	seq, err := s.gossip.PublishDelta(ctx, req.Delta)
	if err != nil {
		return &pb.PublishDeltaResult{Success: false, Error: err.Error()}, nil
	}
	return &pb.PublishDeltaResult{Success: true, SenderSeq: seq}, nil
}

func (s *NetdServer) ListProjects(_ context.Context, _ *pb.Empty) (*pb.ProjectList, error) {
	if s.gossip == nil {
		return &pb.ProjectList{}, nil
	}
	return &pb.ProjectList{ProjectIds: s.gossip.ListProjects()}, nil
}

// SubscribeDeltas is server-streaming. Each RPC call gets its own
// subscription slot in the gossip fan-out. The stream stays open until
// the client cancels or the daemon shuts down.
//
// We register the subscription before sending any deltas, so a client
// that calls JoinProject + immediately Subscribe doesn't miss the
// first delta. Caveat: if a delta arrives before the gRPC handler
// starts iterating its channel, it sits in the channel buffer — not
// lost.
func (s *NetdServer) SubscribeDeltas(req *pb.SubscribeDeltasRequest, stream pb.GossipService_SubscribeDeltasServer) error {
	if s.gossip == nil {
		return status.Error(codes.Unavailable, "gossip not initialized")
	}
	var filter []string
	if req != nil {
		filter = req.ProjectIds
	}
	ch, cancel := s.gossip.Subscribe(filter)
	defer cancel()

	ctx := stream.Context()
	for {
		select {
		case <-ctx.Done():
			return nil
		case d, ok := <-ch:
			if !ok {
				// Manager closed (daemon shutdown). End stream cleanly.
				return nil
			}
			if err := stream.Send(d); err != nil {
				return err
			}
		}
	}
}

// =============================================================================
// CapabilityService — sybil resistance / Tier-3 attestation
// =============================================================================

// IssueChallenge — server side of "I'm a Tier-3 validator; here's a
// challenge you must solve". The applicant_pubkey identifies who's
// being challenged; task_ids may override the daemon's default
// canonical eval suite (test override only — production callers
// should leave it empty).
func (s *NetdServer) IssueChallenge(_ context.Context, req *pb.IssueChallengeRequest) (*pb.Challenge, error) {
	if s.capability == nil {
		return nil, status.Error(codes.Unavailable, "capability not initialized")
	}
	if req == nil || req.ApplicantPubkey == "" {
		return nil, status.Error(codes.InvalidArgument, "applicant_pubkey required")
	}
	taskIDs := req.TaskIds
	if len(taskIDs) == 0 {
		// Phase 3 minimum: a fixed default set so the server-side
		// always produces a valid challenge. The Python eval suite
		// (Session 8) will replace this with a randomly-sampled
		// canonical subset.
		taskIDs = defaultEvalTaskIDs()
	}
	ttl := time.Duration(req.TtlSeconds) * time.Second
	challenge, err := s.capability.IssueChallenge(req.ApplicantPubkey, taskIDs, ttl)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "issue challenge: %v", err)
	}
	return challenge, nil
}

// VerifyResponse — server side of "verify this applicant's response
// and give me a CoSignature on the AttestationBody if it passes".
// Returns the cosignature inside VerifyResponseResult; an unsuccessful
// verification returns success=false + error string (no cosig).
func (s *NetdServer) VerifyResponse(_ context.Context, req *pb.VerifyResponseRequest) (*pb.VerifyResponseResult, error) {
	if s.capability == nil {
		return nil, status.Error(codes.Unavailable, "capability not initialized")
	}
	if req == nil || req.Challenge == nil || req.Response == nil {
		return nil, status.Error(codes.InvalidArgument, "challenge and response required")
	}
	cosig, err := s.capability.VerifyResponse(req.Challenge, req.Response, nil)
	if err != nil {
		return &pb.VerifyResponseResult{Success: false, Error: err.Error()}, nil
	}
	return &pb.VerifyResponseResult{Success: true, CoSignature: cosig}, nil
}

// PublishAttestation — server side of "publish the assembled
// AttestationCert to the DHT under /gyza/attestations/{pubkey}".
// Self-verifies before publishing so we can't accidentally pollute
// the DHT with a malformed cert.
func (s *NetdServer) PublishAttestation(ctx context.Context, cert *pb.AttestationCert) (*pb.PublishAttestationResult, error) {
	if s.dht == nil {
		return nil, status.Error(codes.Unavailable, "DHT not initialized")
	}
	if cert == nil || cert.Body == nil {
		return nil, status.Error(codes.InvalidArgument, "cert/body required")
	}
	if _, err := capability.VerifyAttestation(cert, time.Now); err != nil {
		return &pb.PublishAttestationResult{
			Success: false,
			Error:   "self-verify: " + err.Error(),
		}, nil
	}
	key, err := s.dht.PublishAttestation(ctx, cert)
	if err != nil {
		return &pb.PublishAttestationResult{Success: false, Error: err.Error()}, nil
	}
	return &pb.PublishAttestationResult{Success: true, DhtKey: key}, nil
}

// FetchAttestation — server side of "give me the cert for this pubkey".
// NotFound is conveyed by an empty cert (body=nil) rather than an
// error code, so callers can distinguish "no cert" from "DHT failure"
// uniformly.
func (s *NetdServer) FetchAttestation(ctx context.Context, req *pb.FetchAttestationRequest) (*pb.AttestationCert, error) {
	if s.dht == nil {
		return nil, status.Error(codes.Unavailable, "DHT not initialized")
	}
	if req == nil || req.ApplicantPubkey == "" {
		return nil, status.Error(codes.InvalidArgument, "applicant_pubkey required")
	}
	cert, err := s.dht.FetchAttestation(ctx, req.ApplicantPubkey)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "fetch: %v", err)
	}
	if cert == nil {
		return &pb.AttestationCert{}, nil
	}
	return cert, nil
}

// VerifyAttestation — server side of "tell me if this cert is valid".
// Pure function — no I/O. Useful for clients that have a cert in
// hand and want a single trusted check rather than reimplementing
// all the cosig math themselves.
func (s *NetdServer) VerifyAttestation(_ context.Context, cert *pb.AttestationCert) (*pb.VerifyAttestationResult, error) {
	if cert == nil || cert.Body == nil {
		return &pb.VerifyAttestationResult{Valid: false, Reason: "nil cert/body"}, nil
	}
	n, err := capability.VerifyAttestation(cert, time.Now)
	if err != nil {
		return &pb.VerifyAttestationResult{
			Valid:       false,
			CosigCount:  int32(n),
			Reason:      err.Error(),
		}, nil
	}
	return &pb.VerifyAttestationResult{Valid: true, CosigCount: int32(n)}, nil
}

// defaultEvalTaskIDs is the Phase 3 stub set — a fixed list of three
// task IDs. Session 8 will swap this for a random sample drawn from
// the canonical eval suite published to the DHT.
func defaultEvalTaskIDs() []string {
	return []string{"file_list_001", "file_read_001", "search_001"}
}

// =============================================================================
// MessageService — point-to-point peer messaging via libp2p streams.
// =============================================================================

// Send opens a stream to the target peer and writes one (type, payload)
// frame. Returns success=true with no fields populated on a clean
// write; success=false + error on transport / framing failures.
func (s *NetdServer) Send(ctx context.Context, req *pb.SendRequest) (*pb.SendResult, error) {
	if s.msg == nil {
		return nil, status.Error(codes.Unavailable, "message service not initialized")
	}
	if req == nil || req.PeerId == "" {
		return nil, status.Error(codes.InvalidArgument, "peer_id required")
	}
	if req.MessageType == "" {
		return nil, status.Error(codes.InvalidArgument, "message_type required")
	}
	pid, err := peer.Decode(req.PeerId)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "bad peer_id: %v", err)
	}
	if err := s.msg.Send(ctx, pid, req.MessageType, req.Payload); err != nil {
		return &pb.SendResult{Success: false, Error: err.Error()}, nil
	}
	return &pb.SendResult{Success: true}, nil
}

// Broadcast sends to every currently-connected peer except the
// excluded set. Returns the count of successful per-peer Send calls.
func (s *NetdServer) Broadcast(ctx context.Context, req *pb.BroadcastRequest) (*pb.BroadcastResult, error) {
	if s.msg == nil {
		return nil, status.Error(codes.Unavailable, "message service not initialized")
	}
	if req == nil || req.MessageType == "" {
		return nil, status.Error(codes.InvalidArgument, "message_type required")
	}
	excludePeers := make([]peer.ID, 0, len(req.ExcludePeerIds))
	for _, s := range req.ExcludePeerIds {
		if pid, err := peer.Decode(s); err == nil {
			excludePeers = append(excludePeers, pid)
		}
	}
	delivered := s.msg.Broadcast(ctx, req.MessageType, req.Payload, excludePeers)
	return &pb.BroadcastResult{DeliveredCount: int32(delivered)}, nil
}

// Subscribe is server-streaming. Each call gets a fan-out slot;
// caller closes by cancelling its context (gRPC-side stream
// cancellation propagates here as ctx.Done).
func (s *NetdServer) Subscribe(req *pb.SubscribeRequest, stream pb.MessageService_SubscribeServer) error {
	if s.msg == nil {
		return status.Error(codes.Unavailable, "message service not initialized")
	}
	var filter []string
	if req != nil {
		filter = req.MessageTypes
	}
	ch, cancel := s.msg.Subscribe(filter)
	defer cancel()

	ctx := stream.Context()
	for {
		select {
		case <-ctx.Done():
			return nil
		case incoming, ok := <-ch:
			if !ok {
				return nil
			}
			if err := stream.Send(incoming); err != nil {
				return err
			}
		}
	}
}

// DHTService

func (s *NetdServer) Put(context.Context, *pb.DHTRecord) (*pb.DHTResult, error) {
	return nil, status.Error(codes.Unimplemented, notReadySession2)
}
func (s *NetdServer) Get(context.Context, *pb.DHTKey) (*pb.DHTRecord, error) {
	return nil, status.Error(codes.Unimplemented, notReadySession2)
}
func (s *NetdServer) Delete(context.Context, *pb.DHTKey) (*pb.DHTResult, error) {
	return nil, status.Error(codes.Unimplemented, notReadySession2)
}

// =============================================================================
// Server lifecycle
// =============================================================================

// Server is the gRPC server handle returned by StartGRPCServer. Owns
// the *grpc.Server, the listening Unix socket, and the socket file path
// (so Stop can clean it up).
type Server struct {
	grpc       *grpc.Server
	socketPath string
	listening  net.Listener
	stopped    atomic.Bool
}

// StartGRPCServer creates a Unix-socket listener at socketPath, mounts
// every Gyza service onto a new *grpc.Server, and starts Serve on a
// goroutine. Returns once the listener is bound — by the time this
// function returns, a client can dial socketPath.
//
// Pre-existing socket files at that path are removed (after a sanity
// check that they ARE socket files — refuse to clobber a regular file).
//
// Permissions: the socket is chmod'd to 0600 immediately after bind.
// The whole point of using a Unix socket is to keep this control
// channel local-only; the mode is part of that contract.
func StartGRPCServer(socketPath string, server *NetdServer, logf func(string, ...any)) (*Server, error) {
	if logf == nil {
		logf = func(string, ...any) {}
	}

	socketPath, err := expandUser(socketPath)
	if err != nil {
		return nil, fmt.Errorf("expand socket path: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(socketPath), 0o700); err != nil {
		return nil, fmt.Errorf("create socket dir: %w", err)
	}

	// Refuse to clobber a pre-existing non-socket file. A stale socket
	// from a crashed daemon is fine — that's exactly the case Unlink
	// is for. A regular file at that path is a configuration mistake.
	if info, err := os.Stat(socketPath); err == nil {
		if info.Mode()&os.ModeSocket == 0 {
			return nil, fmt.Errorf(
				"refusing to remove non-socket at %q (mode %v)", socketPath, info.Mode(),
			)
		}
		if err := os.Remove(socketPath); err != nil {
			return nil, fmt.Errorf("remove stale socket: %w", err)
		}
	}

	lis, err := net.Listen("unix", socketPath)
	if err != nil {
		return nil, fmt.Errorf("listen unix: %w", err)
	}
	if err := os.Chmod(socketPath, 0o600); err != nil {
		_ = lis.Close()
		_ = os.Remove(socketPath)
		return nil, fmt.Errorf("chmod socket: %w", err)
	}

	gs := grpc.NewServer()
	pb.RegisterNodeServiceServer(gs, server)
	pb.RegisterDiscoveryServiceServer(gs, server)
	pb.RegisterPeerServiceServer(gs, server)
	pb.RegisterMessageServiceServer(gs, server)
	pb.RegisterDHTServiceServer(gs, server)
	pb.RegisterGossipServiceServer(gs, server)
	pb.RegisterCapabilityServiceServer(gs, server)

	logf("[grpc] listening on %s", socketPath)

	out := &Server{
		grpc:       gs,
		socketPath: socketPath,
		listening:  lis,
	}
	go func() {
		if err := gs.Serve(lis); err != nil && !errors.Is(err, net.ErrClosed) && !out.stopped.Load() {
			logf("[grpc] serve error: %v", err)
		}
	}()
	return out, nil
}

// stopGracePeriod bounds GracefulStop. If a handler (especially a
// long-lived streaming RPC, like Session 4's Subscribe) refuses to
// return, we fall back to a hard Stop so the daemon process can exit
// in response to SIGTERM. Without this backstop, the systemd / docker
// stop sequence can wedge.
const stopGracePeriod = 5 * time.Second

// Stop terminates the gRPC server and removes the socket file. Tries
// graceful first (lets in-flight unary calls finish), falls back to
// hard Stop after stopGracePeriod. Idempotent.
func (s *Server) Stop() {
	if !s.stopped.CompareAndSwap(false, true) {
		return
	}
	done := make(chan struct{})
	go func() {
		s.grpc.GracefulStop()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(stopGracePeriod):
		s.grpc.Stop() // hard stop — kills active streams.
	}
	_ = os.Remove(s.socketPath)
}

// SocketPath returns the actual filesystem path the server is listening
// on (after ~ expansion).
func (s *Server) SocketPath() string { return s.socketPath }

// expandUser performs ~ → $HOME expansion. Doesn't pull in
// shell-style globbing — keep it simple.
func expandUser(p string) (string, error) {
	if len(p) == 0 || p[0] != '~' {
		return p, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	if p == "~" {
		return home, nil
	}
	if len(p) > 1 && p[1] == '/' {
		return filepath.Join(home, p[2:]), nil
	}
	return p, nil // "~user" forms not supported
}
