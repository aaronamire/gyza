// Package capability_stream implements the libp2p stream protocol that
// carries proof-of-capability Challenge / ChallengeResponse /
// VerifyResponseResult between an applicant daemon and a validator
// daemon.
//
// Why a stream protocol vs. gRPC: gRPC over Unix sockets is
// IN-DAEMON only; cross-daemon traffic must ride libp2p so it gets the
// same NAT traversal and Noise authentication as the rest of the
// global federation. The capability flow is point-to-point and short
// (3 frames each direction), so a dedicated stream protocol — not
// gossipsub, not pubsub — is the right shape.
//
// Wire format on the stream:
//
//	→  Validator → Applicant : Challenge          (deterministic-marshaled proto)
//	←  Applicant → Validator : ChallengeResponse  (deterministic-marshaled proto)
//	→  Validator → Applicant : VerifyResponseResult (proto)
//
// Each frame is [uvarint_len][marshaled_proto_bytes]. The stream is
// closed by the validator after writing the final outcome frame.
//
// Validator initiates the protocol: as soon as the applicant opens the
// stream, the validator extracts the applicant's compositor pubkey
// from the libp2p RemotePeer (Noise-authenticated, so the binding is
// load-bearing) and issues a Challenge with a fresh nonce. This
// avoids a kickoff frame from the applicant and keeps the protocol at
// 3 frames total.
//
// Why deterministic protobuf marshal: the cosignature in the final
// outcome is signed over a SEPARATE canonical bytes routine (the
// AttestationBody, in capability.VerifyResponse). The wire frames
// themselves don't need to be byte-stable across implementations —
// they just need to round-trip cleanly. We use deterministic marshal
// anyway so a future protobuf-aware proxy can compare frames without
// re-marshaling.
//
// What's NOT in this package:
//
//   - The Python integration. The applicant-side ``RequestAttestation``
//     takes an ``EvalRunner`` callback the daemon wires to a Python
//     gRPC method that runs the eval suite. That wiring lives in
//     `gyza/network/...` and `netd/internal/grpc/server.go` (next
//     session).
//   - DHT-driven validator selection. ``RequestAttestation`` takes a
//     concrete peer ID; selecting which peers to ask is the orchestrator
//     layer's concern.
//   - Cert assembly + DHT publication. Both already exist
//     (`capability.AssembleAttestation`, `CapabilityService.PublishAttestation`);
//     this package returns one cosignature per call, the orchestrator
//     collects ≥ MinCoSignatures and assembles.
package capability_stream

import (
	"bufio"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"sync/atomic"
	"time"

	"gyza/netd/internal/capability"
	pb "gyza/netd/internal/grpc/proto"

	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/core/protocol"
	"google.golang.org/protobuf/proto"
)

// ProtocolID is the libp2p stream protocol identifier. Bumping it is a
// hard fork — old daemons won't understand the new dialect.
const ProtocolID protocol.ID = "/gyza/capability-challenge/1.0.0"

// MaxFrameLen bounds a single uvarint-length-prefixed frame. The
// Challenge is small (a few hundred bytes); ChallengeResponse can grow
// linearly in task_ids × ICP envelope size. 4 MiB matches the
// per-frame cap used by /gyza/message/1.0.0 and is a safe upper bound
// for ~50 tasks even with large outputs.
const MaxFrameLen = 4 * 1024 * 1024

// StreamTimeout bounds the entire validator-side handler AND the
// applicant-side initiator. Long enough for real-LLM eval execution
// (a 60s mock-eval suite plus margin) but capped so a slow or
// malicious peer can't pin the host's goroutines forever.
const StreamTimeout = 120 * time.Second

// Manager owns the validator-side stream handler. One per daemon.
// Construct via NewManager; Close on shutdown to release the protocol
// handler. Concurrent stream handling is goroutine-per-stream by
// libp2p's default behavior.
type Manager struct {
	host      host.Host
	capMgr    *capability.ChallengeManager
	taskIDs   []string
	verifyOut capability.TaskOutputVerifier
	ttl       time.Duration
	logf      func(string, ...any)

	closed atomic.Bool
}

// Config bundles the Manager's wiring inputs. ``TaskIDs`` is the list
// of canonical eval task IDs this validator will demand from
// applicants; the applicant-side eval runner is responsible for
// matching them. ``VerifyOut`` is the per-task output verifier — pass
// ``nil`` for permissive mode (the default while the cross-language
// Python bridge is still being built).
type Config struct {
	CapabilityManager *capability.ChallengeManager
	TaskIDs           []string
	VerifyOut         capability.TaskOutputVerifier
	ChallengeTTL      time.Duration
	Logf              func(string, ...any)
}

// NewManager registers the stream handler on ``h`` and returns a
// Manager. ``cfg.TaskIDs`` MUST be non-empty — the protocol refuses
// to issue a challenge with zero tasks (matches capability.IssueChallenge).
func NewManager(h host.Host, cfg Config) (*Manager, error) {
	if cfg.CapabilityManager == nil {
		return nil, errors.New("Config.CapabilityManager is required")
	}
	if len(cfg.TaskIDs) == 0 {
		return nil, errors.New("Config.TaskIDs must be non-empty")
	}
	if cfg.ChallengeTTL <= 0 {
		cfg.ChallengeTTL = capability.DefaultChallengeTTL
	}
	logf := cfg.Logf
	if logf == nil {
		logf = func(string, ...any) {}
	}
	m := &Manager{
		host:      h,
		capMgr:    cfg.CapabilityManager,
		taskIDs:   append([]string{}, cfg.TaskIDs...),
		verifyOut: cfg.VerifyOut,
		ttl:       cfg.ChallengeTTL,
		logf:      logf,
	}
	h.SetStreamHandler(ProtocolID, m.handleIncoming)
	return m, nil
}

// Close removes the stream handler. Idempotent. After Close,
// RequestAttestation calls return an error and incoming streams are
// not handled.
func (m *Manager) Close() error {
	if !m.closed.CompareAndSwap(false, true) {
		return nil
	}
	m.host.RemoveStreamHandler(ProtocolID)
	return nil
}

// =============================================================================
// Validator-side stream handler
// =============================================================================

// handleIncoming runs the validator side of the protocol. Each step
// has a clearly-named failure mode — we log + close on any error,
// never panicking, never writing a partial frame.
func (m *Manager) handleIncoming(stream network.Stream) {
	defer func() { _ = stream.Close() }()

	// Wall-clock cap for the whole exchange — keeps a slow applicant
	// from pinning the goroutine.
	if err := stream.SetDeadline(time.Now().Add(StreamTimeout)); err != nil {
		m.logf("[capability_stream] set deadline: %v", err)
		return
	}

	remotePeer := stream.Conn().RemotePeer()
	if remotePeer == m.host.ID() {
		// Self-loop — never legitimate.
		return
	}

	applicantPubkey, err := extractPubkeyHex(remotePeer)
	if err != nil {
		m.logf("[capability_stream] extract %s pubkey: %v", remotePeer, err)
		return
	}

	// 1. Issue Challenge.
	challenge, err := m.capMgr.IssueChallenge(applicantPubkey, m.taskIDs, m.ttl)
	if err != nil {
		m.logf("[capability_stream] IssueChallenge for %s: %v", remotePeer, err)
		return
	}
	if err := writeFrame(stream, challenge); err != nil {
		m.logf("[capability_stream] write challenge to %s: %v", remotePeer, err)
		_ = stream.Reset()
		return
	}

	// 2. Read ChallengeResponse.
	response := &pb.ChallengeResponse{}
	if err := readFrame(stream, response); err != nil {
		m.logf("[capability_stream] read response from %s: %v", remotePeer, err)
		return
	}

	// 3. Verify + co-sign.
	cosig, err := m.capMgr.VerifyResponse(challenge, response, m.verifyOut)
	outcome := &pb.VerifyResponseResult{}
	if err != nil {
		// Reject: surface the reason on the wire so the applicant
		// can diagnose. We do NOT include the validator's pubkey on
		// the rejection branch — preserves privacy of which validator
		// rejected (the applicant already knows from peer ID anyway,
		// but we keep proto fields populated only when needed).
		outcome.Success = false
		outcome.Error = err.Error()
		m.logf("[capability_stream] reject from %s: %v", remotePeer, err)
	} else {
		outcome.Success = true
		outcome.CoSignature = cosig
	}
	if werr := writeFrame(stream, outcome); werr != nil {
		m.logf("[capability_stream] write outcome to %s: %v", remotePeer, werr)
		_ = stream.Reset()
		return
	}
}

// =============================================================================
// Applicant-side initiator
// =============================================================================

// EvalRunner is the callback the applicant-side initiator invokes to
// produce a ChallengeResponse from a received Challenge. In production
// the daemon wires this to a Python gRPC stream that runs the eval
// suite; in tests the callback can synthesize a response directly.
//
// Returning a non-nil error aborts the attestation BEFORE we send a
// response; the validator's stream just sees a dropped connection.
// (We considered surfacing a structured error frame, but the validator
// never asked for the eval, so there's nothing actionable on its end.)
type EvalRunner func(challenge *pb.Challenge) (*pb.ChallengeResponse, error)

// RequestAttestation runs the applicant-side protocol against ``target``.
// Returns the validator's cosignature on success, or an error on
// rejection / network failure.
//
// ``runEval`` MUST produce a ChallengeResponse whose ApplicantSignature
// is over deterministic-marshal(body) using the applicant's compositor
// signing key. The libp2p layer doesn't sign anything itself; the
// signature must already be on the proto by the time it's handed back.
func (m *Manager) RequestAttestation(
	ctx context.Context,
	target peer.ID,
	runEval EvalRunner,
) (*pb.CoSignature, error) {
	if m.closed.Load() {
		return nil, errors.New("capability_stream manager closed")
	}
	if target == m.host.ID() {
		return nil, errors.New("refusing to request attestation from self")
	}
	if runEval == nil {
		return nil, errors.New("runEval callback required")
	}

	ctx, cancel := context.WithTimeout(ctx, StreamTimeout)
	defer cancel()

	stream, err := m.host.NewStream(ctx, target, ProtocolID)
	if err != nil {
		return nil, fmt.Errorf("open stream to %s: %w", target, err)
	}
	defer func() { _ = stream.Close() }()
	if err := stream.SetDeadline(time.Now().Add(StreamTimeout)); err != nil {
		return nil, fmt.Errorf("set deadline: %w", err)
	}

	// 1. Read Challenge.
	challenge := &pb.Challenge{}
	if err := readFrame(stream, challenge); err != nil {
		return nil, fmt.Errorf("read challenge: %w", err)
	}

	// 2. Sanity-verify the challenge BEFORE running the eval. A
	// malformed challenge from a spoofing peer (the libp2p Noise
	// guarantee binds the peer_id, but a subsequent payload could
	// still be junk) shouldn't burn applicant CPU.
	if err := m.capMgr.VerifyChallenge(challenge); err != nil {
		return nil, fmt.Errorf("invalid challenge: %w", err)
	}

	// 3. Run eval (blocking — this is the slow step).
	response, err := runEval(challenge)
	if err != nil {
		// Don't write a response frame; just close. The validator's
		// read times out cleanly.
		return nil, fmt.Errorf("eval: %w", err)
	}
	if response == nil {
		return nil, errors.New("eval returned nil response")
	}

	// 4. Write ChallengeResponse.
	if err := writeFrame(stream, response); err != nil {
		_ = stream.Reset()
		return nil, fmt.Errorf("write response: %w", err)
	}

	// 5. Read VerifyResponseResult.
	outcome := &pb.VerifyResponseResult{}
	if err := readFrame(stream, outcome); err != nil {
		return nil, fmt.Errorf("read outcome: %w", err)
	}
	if !outcome.Success {
		return nil, fmt.Errorf("validator rejected: %s", outcome.Error)
	}
	if outcome.CoSignature == nil {
		return nil, errors.New("validator returned success with nil cosignature")
	}
	return outcome.CoSignature, nil
}

// =============================================================================
// Frame encoding — uvarint length prefix, then deterministic-marshaled
// protobuf bytes. Mirrors /gyza/message/1.0.0's framing but with one
// frame per call (no message_type field — the protocol order is
// fixed, so framing is unambiguous).
// =============================================================================

func writeFrame(w io.Writer, m proto.Message) error {
	body, err := proto.MarshalOptions{Deterministic: true}.Marshal(m)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}
	if len(body) > MaxFrameLen {
		return fmt.Errorf("frame too large (%d > %d)", len(body), MaxFrameLen)
	}
	bw := bufio.NewWriter(w)
	if err := writeUvarint(bw, uint64(len(body))); err != nil {
		return err
	}
	if _, err := bw.Write(body); err != nil {
		return err
	}
	return bw.Flush()
}

// readFrame reads one length-prefixed frame and unmarshals into ``m``.
// We bufio-wrap so the uvarint read doesn't issue a syscall per byte.
//
// Stateful note: the bufio.Reader holds onto bytes read past the
// uvarint+payload. That's harmless here because each direction of the
// stream carries exactly one frame — there's nothing else to read.
func readFrame(r io.Reader, m proto.Message) error {
	br := bufio.NewReader(r)
	n, err := binary.ReadUvarint(br)
	if err != nil {
		return fmt.Errorf("read length: %w", err)
	}
	if n > MaxFrameLen {
		return fmt.Errorf("frame length %d exceeds %d", n, MaxFrameLen)
	}
	buf := make([]byte, n)
	if _, err := io.ReadFull(br, buf); err != nil {
		return fmt.Errorf("read body: %w", err)
	}
	if err := proto.Unmarshal(buf, m); err != nil {
		return fmt.Errorf("unmarshal: %w", err)
	}
	return nil
}

func writeUvarint(w io.Writer, v uint64) error {
	var buf [binary.MaxVarintLen64]byte
	n := binary.PutUvarint(buf[:], v)
	_, err := w.Write(buf[:n])
	return err
}

// extractPubkeyHex pulls the Ed25519 hex-encoded compositor pubkey out
// of a libp2p PeerID. PeerIDs in our network are derived from the
// compositor key via libp2p's identity scheme, so this is the inverse
// of "construct PeerID from compositor pubkey." Mirrors
// message.go's senderPubkeyHex extraction.
func extractPubkeyHex(p peer.ID) (string, error) {
	pub, err := p.ExtractPublicKey()
	if err != nil {
		return "", fmt.Errorf("extract pubkey: %w", err)
	}
	if pub == nil {
		return "", errors.New("nil pubkey")
	}
	raw, err := pub.Raw()
	if err != nil {
		return "", fmt.Errorf("pubkey raw: %w", err)
	}
	return fmt.Sprintf("%x", raw), nil
}
