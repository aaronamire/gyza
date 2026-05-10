package capability_stream_test

// End-to-end tests for /gyza/capability-challenge/1.0.0 over real
// libp2p hosts on loopback. No mocks — the whole point of this layer
// is the protocol exchange.
//
// What's covered here:
//
//	TestSuccessfulAttestationRoundTrip — happy path: applicant produces
//	  a valid response, validator verifies, returns CoSignature.
//	TestValidatorRejectsBadResponse    — applicant sends a malformed
//	  response (forged ICP signature); validator returns a structured
//	  rejection on the wire.
//	TestApplicantRejectsForgedChallenge — validator's challenge has a
//	  bad signature; applicant aborts BEFORE running the eval.
//	TestEvalRunnerError                 — eval callback returns an
//	  error; applicant returns the error and validator sees a clean
//	  stream close.
//	TestSelfRequestRejected             — RequestAttestation against
//	  own peer.ID is refused at the API level.

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"testing"
	"time"

	"gyza/netd/internal/capability"
	"gyza/netd/internal/capability_stream"
	pb "gyza/netd/internal/grpc/proto"

	"github.com/zeebo/blake3"
	libp2p "github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	libp2pquic "github.com/libp2p/go-libp2p/p2p/transport/quic"
	"google.golang.org/protobuf/proto"
)

// =============================================================================
// Test scaffolding — minimal libp2p host + capability.Signer wired to
// the SAME Ed25519 key. The protocol's correctness depends on this
// binding: the libp2p PeerID is derived from the Ed25519 key, and the
// validator extracts that pubkey from the stream's RemotePeer to use
// as the applicant_pubkey when issuing challenges.
// =============================================================================

type ed25519Signer struct {
	priv ed25519.PrivateKey
	pub  ed25519.PublicKey
}

func (s *ed25519Signer) SignBytes(b []byte) []byte {
	return ed25519.Sign(s.priv, b)
}

func (s *ed25519Signer) PubkeyHex() string {
	return hex.EncodeToString(s.pub)
}

// newPeerWithSigner builds a libp2p host whose Ed25519 identity key is
// also exposed as a capability.Signer (and as raw ed25519 for synthetic
// ICP envelope signing in tests).
func newPeerWithSigner(t *testing.T) (host.Host, *ed25519Signer, func()) {
	t.Helper()
	priv, pub, err := crypto.GenerateEd25519Key(rand.Reader)
	if err != nil {
		t.Fatalf("genkey: %v", err)
	}
	rawPriv, err := priv.Raw()
	if err != nil {
		t.Fatalf("priv.Raw: %v", err)
	}
	rawPub, err := pub.Raw()
	if err != nil {
		t.Fatalf("pub.Raw: %v", err)
	}
	signer := &ed25519Signer{
		priv: ed25519.PrivateKey(rawPriv),
		pub:  ed25519.PublicKey(rawPub),
	}
	h, err := libp2p.New(
		libp2p.Identity(priv),
		libp2p.ListenAddrStrings("/ip4/127.0.0.1/udp/0/quic-v1"),
		libp2p.Transport(libp2pquic.NewTransport),
	)
	if err != nil {
		t.Fatalf("libp2p.New: %v", err)
	}
	return h, signer, func() { _ = h.Close() }
}

func connect(t *testing.T, ctx context.Context, a, b host.Host) {
	t.Helper()
	if err := a.Connect(ctx, peer.AddrInfo{ID: b.ID(), Addrs: b.Addrs()}); err != nil {
		t.Fatalf("connect: %v", err)
	}
}

// makeApplicantResponse builds a ChallengeResponse whose ICP envelopes
// and ApplicantSignature all verify under the applicant's Ed25519
// signing key. Mirrors the helper in capability_test.go — synthetic
// payload bytes, real crypto.
func makeApplicantResponse(
	t *testing.T,
	challenge *pb.Challenge,
	applicant *ed25519Signer,
	completedAt time.Time,
) *pb.ChallengeResponse {
	t.Helper()
	results := make([]*pb.TaskResult, 0, len(challenge.Body.TaskIds))
	for _, taskID := range challenge.Body.TaskIds {
		payload := []byte("synthetic-icp-payload:" + taskID)
		digest := blake3.Sum256(payload)
		sig := ed25519.Sign(applicant.priv, digest[:])
		results = append(results, &pb.TaskResult{
			TaskId:            taskID,
			OutputJson:        []byte(`{"result":"ok"}`),
			IcpPayloadBytes:   payload,
			IcpSignatureHex:   hex.EncodeToString(sig),
			IcpAgentPubkeyHex: applicant.PubkeyHex(),
			DurationMs:        100,
		})
	}
	body := &pb.ResponseBody{
		ApplicantPubkey:  applicant.PubkeyHex(),
		ChallengerPubkey: challenge.Body.ChallengerPubkey,
		Nonce:            append([]byte{}, challenge.Body.Nonce...),
		TaskResults:      results,
		CompletedAtNs:    completedAt.UnixNano(),
	}
	bodyBytes, err := proto.MarshalOptions{Deterministic: true}.Marshal(body)
	if err != nil {
		t.Fatalf("marshal body: %v", err)
	}
	return &pb.ChallengeResponse{
		Body:               body,
		ApplicantSignature: ed25519.Sign(applicant.priv, bodyBytes),
	}
}

// =============================================================================
// Tests
// =============================================================================

func TestSuccessfulAttestationRoundTrip(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	validatorHost, validatorSigner, closeV := newPeerWithSigner(t)
	defer closeV()
	applicantHost, applicantSigner, closeA := newPeerWithSigner(t)
	defer closeA()

	validatorCapMgr := capability.NewChallengeManager(validatorSigner.PubkeyHex(), validatorSigner)
	validatorMgr, err := capability_stream.NewManager(validatorHost, capability_stream.Config{
		CapabilityManager: validatorCapMgr,
		TaskIDs:           []string{"count_py_files", "list_extensions", "echo_nonce"},
		Logf:              t.Logf,
	})
	if err != nil {
		t.Fatalf("validator NewManager: %v", err)
	}
	defer validatorMgr.Close()

	// Applicant-side Manager — only used for its RequestAttestation method.
	// Applicant doesn't need its own ChallengeManager for this flow, but
	// the constructor requires one (it could in principle act as a
	// validator too if anyone dialed it). Use the applicant's key so
	// the constructor's invariants are satisfied.
	applicantCapMgr := capability.NewChallengeManager(applicantSigner.PubkeyHex(), applicantSigner)
	applicantMgr, err := capability_stream.NewManager(applicantHost, capability_stream.Config{
		CapabilityManager: applicantCapMgr,
		TaskIDs:           []string{"count_py_files"},  // never used by applicant role
		Logf:              t.Logf,
	})
	if err != nil {
		t.Fatalf("applicant NewManager: %v", err)
	}
	defer applicantMgr.Close()

	connect(t, ctx, applicantHost, validatorHost)

	runEval := func(challenge *pb.Challenge) (*pb.ChallengeResponse, error) {
		return makeApplicantResponse(t, challenge, applicantSigner, time.Now()), nil
	}

	cosig, err := applicantMgr.RequestAttestation(ctx, validatorHost.ID(), runEval)
	if err != nil {
		t.Fatalf("RequestAttestation: %v", err)
	}
	if cosig == nil {
		t.Fatal("expected non-nil cosignature")
	}
	if cosig.ValidatorPubkey != validatorSigner.PubkeyHex() {
		t.Errorf(
			"cosig.ValidatorPubkey = %q, want %q",
			cosig.ValidatorPubkey, validatorSigner.PubkeyHex(),
		)
	}
	if len(cosig.Signature) != ed25519.SignatureSize {
		t.Errorf("cosig signature length = %d, want %d",
			len(cosig.Signature), ed25519.SignatureSize)
	}
	if cosig.SignedAtNs == 0 {
		t.Errorf("cosig.SignedAtNs not set")
	}
}

func TestValidatorRejectsBadResponse(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	validatorHost, validatorSigner, closeV := newPeerWithSigner(t)
	defer closeV()
	applicantHost, applicantSigner, closeA := newPeerWithSigner(t)
	defer closeA()

	validatorMgr, err := capability_stream.NewManager(
		validatorHost,
		capability_stream.Config{
			CapabilityManager: capability.NewChallengeManager(
				validatorSigner.PubkeyHex(), validatorSigner,
			),
			TaskIDs: []string{"count_py_files"},
			Logf:    t.Logf,
		},
	)
	if err != nil {
		t.Fatalf("validator NewManager: %v", err)
	}
	defer validatorMgr.Close()

	applicantMgr, err := capability_stream.NewManager(
		applicantHost,
		capability_stream.Config{
			CapabilityManager: capability.NewChallengeManager(
				applicantSigner.PubkeyHex(), applicantSigner,
			),
			TaskIDs: []string{"count_py_files"},
			Logf:    t.Logf,
		},
	)
	if err != nil {
		t.Fatalf("applicant NewManager: %v", err)
	}
	defer applicantMgr.Close()

	connect(t, ctx, applicantHost, validatorHost)

	runEval := func(challenge *pb.Challenge) (*pb.ChallengeResponse, error) {
		response := makeApplicantResponse(t, challenge, applicantSigner, time.Now())
		// Tamper: corrupt the ICP signature on the first task. The
		// validator's verifyTaskResult catches this.
		response.Body.TaskResults[0].IcpSignatureHex = hex.EncodeToString(
			make([]byte, ed25519.SignatureSize),
		)
		return response, nil
	}

	_, err = applicantMgr.RequestAttestation(ctx, validatorHost.ID(), runEval)
	if err == nil {
		t.Fatal("expected RequestAttestation to fail; got nil error")
	}
	// The validator's structured rejection arrives as a "validator
	// rejected: ..." error from the applicant side.
	if !contains(err.Error(), "validator rejected") {
		t.Errorf("expected 'validator rejected' in error; got: %v", err)
	}
}

func TestApplicantRejectsForgedChallenge(t *testing.T) {
	// Construct a stand-in validator whose Manager uses a DIFFERENT
	// signer than what gets stamped into the challenge. The validator's
	// own ChallengeManager DOES sign correctly, so this test relies on
	// post-issuance tampering. We do that by intercepting via a custom
	// stream handler instead of NewManager — keeping the actual
	// Manager.handleIncoming as the canonical path, and only this
	// test going off-script.
	//
	// Approach: register a handler that issues a challenge but
	// overwrites ChallengerSignature with garbage before sending.
	// The applicant must reject before running the eval.

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	validatorHost, validatorSigner, closeV := newPeerWithSigner(t)
	defer closeV()
	applicantHost, applicantSigner, closeA := newPeerWithSigner(t)
	defer closeA()

	// Build a Manager so the protocol handler is registered, then
	// OVERWRITE the handler with one that forges signatures. We do
	// this rather than crafting raw streams so the test exercises
	// the same libp2p plumbing as the real flow.
	capMgr := capability.NewChallengeManager(validatorSigner.PubkeyHex(), validatorSigner)
	mgr, err := capability_stream.NewManager(validatorHost, capability_stream.Config{
		CapabilityManager: capMgr,
		TaskIDs:           []string{"count_py_files"},
		Logf:              t.Logf,
	})
	if err != nil {
		t.Fatalf("NewManager: %v", err)
	}
	defer mgr.Close()
	validatorHost.SetStreamHandler(
		capability_stream.ProtocolID,
		makeForgedChallengeHandler(t, capMgr),
	)

	applicantMgr, err := capability_stream.NewManager(applicantHost, capability_stream.Config{
		CapabilityManager: capability.NewChallengeManager(
			applicantSigner.PubkeyHex(), applicantSigner,
		),
		TaskIDs: []string{"count_py_files"},
		Logf:    t.Logf,
	})
	if err != nil {
		t.Fatalf("applicant NewManager: %v", err)
	}
	defer applicantMgr.Close()

	connect(t, ctx, applicantHost, validatorHost)

	runEvalCalls := 0
	runEval := func(challenge *pb.Challenge) (*pb.ChallengeResponse, error) {
		runEvalCalls++
		return makeApplicantResponse(t, challenge, applicantSigner, time.Now()), nil
	}

	_, err = applicantMgr.RequestAttestation(ctx, validatorHost.ID(), runEval)
	if err == nil {
		t.Fatal("expected RequestAttestation to fail; got nil error")
	}
	if !contains(err.Error(), "invalid challenge") {
		t.Errorf("expected 'invalid challenge' in error; got: %v", err)
	}
	// Critical: applicant must NOT have run the eval — that's the
	// whole point of the early-reject.
	if runEvalCalls != 0 {
		t.Errorf("eval ran %d times; expected 0 (applicant must reject before eval)",
			runEvalCalls)
	}
}

func TestEvalRunnerError(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	validatorHost, validatorSigner, closeV := newPeerWithSigner(t)
	defer closeV()
	applicantHost, applicantSigner, closeA := newPeerWithSigner(t)
	defer closeA()

	validatorMgr, err := capability_stream.NewManager(validatorHost, capability_stream.Config{
		CapabilityManager: capability.NewChallengeManager(
			validatorSigner.PubkeyHex(), validatorSigner,
		),
		TaskIDs: []string{"count_py_files"},
		Logf:    t.Logf,
	})
	if err != nil {
		t.Fatalf("validator NewManager: %v", err)
	}
	defer validatorMgr.Close()

	applicantMgr, err := capability_stream.NewManager(applicantHost, capability_stream.Config{
		CapabilityManager: capability.NewChallengeManager(
			applicantSigner.PubkeyHex(), applicantSigner,
		),
		TaskIDs: []string{"count_py_files"},
		Logf:    t.Logf,
	})
	if err != nil {
		t.Fatalf("applicant NewManager: %v", err)
	}
	defer applicantMgr.Close()

	connect(t, ctx, applicantHost, validatorHost)

	wantErr := errors.New("simulated python eval failure")
	runEval := func(_ *pb.Challenge) (*pb.ChallengeResponse, error) {
		return nil, wantErr
	}
	_, err = applicantMgr.RequestAttestation(ctx, validatorHost.ID(), runEval)
	if err == nil {
		t.Fatal("expected RequestAttestation to fail; got nil error")
	}
	if !contains(err.Error(), "simulated python eval failure") {
		t.Errorf("expected eval error to surface; got: %v", err)
	}
}

func TestSelfRequestRejected(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	h, signer, closeH := newPeerWithSigner(t)
	defer closeH()

	mgr, err := capability_stream.NewManager(h, capability_stream.Config{
		CapabilityManager: capability.NewChallengeManager(signer.PubkeyHex(), signer),
		TaskIDs:           []string{"count_py_files"},
	})
	if err != nil {
		t.Fatalf("NewManager: %v", err)
	}
	defer mgr.Close()

	_, err = mgr.RequestAttestation(ctx, h.ID(), func(*pb.Challenge) (*pb.ChallengeResponse, error) {
		t.Fatal("eval should not be invoked for self-request")
		return nil, nil
	})
	if err == nil {
		t.Fatal("expected self-request to fail")
	}
	if !contains(err.Error(), "self") {
		t.Errorf("expected 'self' in error; got: %v", err)
	}
}

// =============================================================================
// helpers
// =============================================================================

func contains(s, sub string) bool {
	return len(sub) == 0 || (len(s) >= len(sub) && indexOf(s, sub) >= 0)
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}

// makeForgedChallengeHandler returns a libp2p StreamHandler that
// issues a real challenge from ``capMgr`` but corrupts the
// ChallengerSignature before writing it. The applicant's
// VerifyChallenge MUST reject.
func makeForgedChallengeHandler(
	t *testing.T,
	capMgr *capability.ChallengeManager,
) network.StreamHandler {
	return func(s network.Stream) {
		defer func() { _ = s.Close() }()

		applicantPubkey := "00112233445566778899aabbccddeeff" +
			"00112233445566778899aabbccddeeff"
		challenge, err := capMgr.IssueChallenge(
			applicantPubkey,
			[]string{"count_py_files"},
			time.Minute,
		)
		if err != nil {
			t.Logf("forged-handler IssueChallenge: %v", err)
			return
		}
		challenge.ChallengerSignature = make([]byte, ed25519.SignatureSize)

		body, err := proto.MarshalOptions{Deterministic: true}.Marshal(challenge)
		if err != nil {
			t.Logf("marshal forged challenge: %v", err)
			return
		}
		var lenBuf [10]byte
		n := putUvarint(lenBuf[:], uint64(len(body)))
		if _, err := s.Write(lenBuf[:n]); err != nil {
			return
		}
		if _, err := s.Write(body); err != nil {
			return
		}
	}
}

// putUvarint mirrors binary.PutUvarint without importing
// encoding/binary in this file. Caller-supplied buf must be ≥ 10 bytes.
func putUvarint(buf []byte, v uint64) int {
	i := 0
	for v >= 0x80 {
		buf[i] = byte(v) | 0x80
		v >>= 7
		i++
	}
	buf[i] = byte(v)
	return i + 1
}
