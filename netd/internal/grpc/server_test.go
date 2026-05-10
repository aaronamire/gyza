package grpcsrv

import (
	"context"
	"crypto/ed25519"
	cryptorand "crypto/rand"
	"encoding/hex"
	"net"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	protomarshal "google.golang.org/protobuf/proto"

	libp2p "github.com/libp2p/go-libp2p"
	libp2pcrypto "github.com/libp2p/go-libp2p/core/crypto"
	libp2phost "github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	libp2pquic "github.com/libp2p/go-libp2p/p2p/transport/quic"

	"github.com/zeebo/blake3"

	"gyza/netd/internal/capability"
	"gyza/netd/internal/capability_stream"
	pb "gyza/netd/internal/grpc/proto"
	"gyza/netd/internal/identity"
)

// makeTestIdentity writes a 32-byte master seed to a temp file with mode
// 0600 and loads an Identity from it. This exercises the same on-disk
// path the daemon uses, so the test catches mode-permission regressions.
func makeTestIdentity(t *testing.T) (*identity.Identity, string) {
	t.Helper()
	dir := t.TempDir()
	keyPath := filepath.Join(dir, "compositor.key")
	seed := make([]byte, 32)
	for i := range seed {
		seed[i] = byte(i + 1) // any deterministic 32 bytes
	}
	if err := os.WriteFile(keyPath, seed, 0o600); err != nil {
		t.Fatalf("write key: %v", err)
	}
	id, err := identity.LoadIdentity(keyPath)
	if err != nil {
		t.Fatalf("load identity: %v", err)
	}
	return id, keyPath
}

// dialUnixGRPC opens a gRPC client over a Unix socket. The default
// resolver doesn't speak unix; we plug a custom dialer.
func dialUnixGRPC(t *testing.T, socketPath string) *grpc.ClientConn {
	t.Helper()
	conn, err := grpc.NewClient(
		"unix:"+socketPath,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		t.Fatalf("grpc.NewClient: %v", err)
	}
	return conn
}

// TestGRPCServerStartStop — the Session-1 exit gate. Daemon starts,
// accepts a gRPC connection, returns NodeInfo with a non-empty PeerID
// matching the loaded identity, and stops cleanly without leaving the
// socket file behind.
func TestGRPCServerStartStop(t *testing.T) {
	id, _ := makeTestIdentity(t)
	socketPath := filepath.Join(t.TempDir(), "netd.sock")

	srv, err := StartGRPCServer(socketPath, NewNetdServer(id, nil, nil, nil, nil, nil, nil, nil), nil)
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	t.Cleanup(srv.Stop)

	conn := dialUnixGRPC(t, socketPath)
	defer conn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	client := pb.NewNodeServiceClient(conn)
	info, err := client.GetNodeInfo(ctx, &pb.Empty{})
	if err != nil {
		t.Fatalf("GetNodeInfo: %v", err)
	}
	if info.PeerId == "" {
		t.Errorf("PeerId is empty")
	}
	if info.CompositorPubkey != id.PubKeyHex {
		t.Errorf("CompositorPubkey = %q, want %q", info.CompositorPubkey, id.PubKeyHex)
	}
	if info.GyzaVersion == "" {
		t.Errorf("GyzaVersion is empty")
	}

	// Status should also work — uptime ≥ 0 is the only invariant in Session 1.
	st, err := client.GetStatus(ctx, &pb.Empty{})
	if err != nil {
		t.Fatalf("GetStatus: %v", err)
	}
	if st.UptimeSeconds < 0 {
		t.Errorf("UptimeSeconds = %d, must be >= 0", st.UptimeSeconds)
	}

	srv.Stop()
	if _, err := os.Stat(socketPath); !os.IsNotExist(err) {
		t.Errorf("socket file %q still exists after Stop (err=%v)", socketPath, err)
	}
}

// TestSocketPermissions — the socket must be chmod 0600 on the way up.
// Anyone with shell access shouldn't be able to walk through someone
// else's gyza-netd. The whole reason we're using a Unix socket vs TCP
// loopback is the OS-enforced perm check; if mode regresses, the
// check is silently bypassed and the test catches that.
func TestSocketPermissions(t *testing.T) {
	id, _ := makeTestIdentity(t)
	socketPath := filepath.Join(t.TempDir(), "netd.sock")
	srv, err := StartGRPCServer(socketPath, NewNetdServer(id, nil, nil, nil, nil, nil, nil, nil), nil)
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	t.Cleanup(srv.Stop)

	info, err := os.Stat(socketPath)
	if err != nil {
		t.Fatalf("stat socket: %v", err)
	}
	if info.Mode()&os.ModeSocket == 0 {
		t.Fatalf("expected socket file, got mode %v", info.Mode())
	}
	if perm := info.Mode().Perm(); perm != 0o600 {
		t.Errorf("socket perm = %#o, want 0600", perm)
	}
}

// TestGracefulShutdown — SIGTERM-equivalent (Stop) cleans up the socket
// file. We don't actually send SIGTERM — we exercise the Stop() path,
// which is what the signal handler invokes.
func TestGracefulShutdown(t *testing.T) {
	id, _ := makeTestIdentity(t)
	socketPath := filepath.Join(t.TempDir(), "netd.sock")
	srv, err := StartGRPCServer(socketPath, NewNetdServer(id, nil, nil, nil, nil, nil, nil, nil), nil)
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	srv.Stop()
	srv.Stop() // idempotency

	if _, err := os.Stat(socketPath); !os.IsNotExist(err) {
		t.Errorf("socket file still exists after shutdown")
	}
}

// TestRefusesNonSocketAtPath — if there's a regular file at the socket
// path, the server must NOT clobber it. A misconfigured user setting
// --socket-path to e.g. ~/important.txt should fail loud, not delete.
func TestRefusesNonSocketAtPath(t *testing.T) {
	id, _ := makeTestIdentity(t)
	dir := t.TempDir()
	regular := filepath.Join(dir, "not-a-socket")
	if err := os.WriteFile(regular, []byte("important data"), 0o600); err != nil {
		t.Fatalf("setup: %v", err)
	}
	_, err := StartGRPCServer(regular, NewNetdServer(id, nil, nil, nil, nil, nil, nil, nil), nil)
	if err == nil {
		t.Fatalf("expected error when path holds a regular file, got nil")
	}
	// And the file must still exist.
	if _, err := os.Stat(regular); err != nil {
		t.Fatalf("regular file vanished: %v", err)
	}
}

// TestStaleSocketIsReplaced — a stale socket file (from a crashed prior
// daemon) must not block startup; the server unlinks and rebinds.
func TestStaleSocketIsReplaced(t *testing.T) {
	id, _ := makeTestIdentity(t)
	socketPath := filepath.Join(t.TempDir(), "netd.sock")

	// Create a stale socket by binding+closing. Bind leaves the inode behind.
	addr, err := net.ResolveUnixAddr("unix", socketPath)
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	l, err := net.ListenUnix("unix", addr)
	if err != nil {
		t.Fatalf("pre-listen: %v", err)
	}
	// Close without unlinking. Use SyscallConn to forcibly NOT unlink —
	// the simple l.Close() in net does unlink. We mimic crash by Detach.
	rawC, _ := l.SyscallConn()
	_ = rawC.Control(func(fd uintptr) {
		_ = syscall.Close(int(fd))
	})

	if _, err := os.Stat(socketPath); err != nil {
		// Some platforms unlink on Close even via syscall; if so, simply
		// touch a fake socket and skip the strict version of the test.
		t.Skipf("could not produce stale socket: %v", err)
	}

	srv, err := StartGRPCServer(socketPath, NewNetdServer(id, nil, nil, nil, nil, nil, nil, nil), nil)
	if err != nil {
		t.Fatalf("start with stale socket: %v", err)
	}
	t.Cleanup(srv.Stop)
}

// =============================================================================
// RequestAttestation — bridge between gRPC and the libp2p
// /gyza/capability-challenge/1.0.0 stream protocol. The test spins up
// two real libp2p hosts (validator + applicant), mounts the applicant
// host's capability_stream.Manager inside a NetdServer, and drives the
// flow over a Unix-socket gRPC client. End-to-end including real
// crypto and a real libp2p connection.
// =============================================================================

// reqAttPair packages the moving parts of an attestation test:
// validator + applicant libp2p hosts, applicant's NetdServer + gRPC
// client, and the applicant signer used to forge valid responses
// in-test.
type reqAttPair struct {
	ctx          context.Context
	cancel       context.CancelFunc
	validatorH   libp2phost.Host
	validatorSig *capStreamTestSigner
	applicantH   libp2phost.Host
	applicantSig *capStreamTestSigner
	srv          *Server
	conn         *grpc.ClientConn
	taskIDs      []string
}

func (p *reqAttPair) close(t *testing.T) {
	t.Helper()
	if p.conn != nil {
		_ = p.conn.Close()
	}
	if p.srv != nil {
		p.srv.Stop()
	}
	if p.validatorH != nil {
		_ = p.validatorH.Close()
	}
	if p.applicantH != nil {
		_ = p.applicantH.Close()
	}
	p.cancel()
}

// newReqAttPair constructs the full bridge test rig. Returns the
// caller-controllable parts; gRPC client connection is ready to use
// for stream calls.
func newReqAttPair(t *testing.T, taskIDs []string) *reqAttPair {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)

	validatorH, validatorSig, _ := newCapStreamPeerWithSigner(t)
	applicantH, applicantSig, _ := newCapStreamPeerWithSigner(t)

	validatorCapMgr := capability.NewChallengeManager(validatorSig.PubkeyHex(), validatorSig)
	_, err := capability_stream.NewManager(validatorH, capability_stream.Config{
		CapabilityManager: validatorCapMgr,
		TaskIDs:           taskIDs,
		Logf:              t.Logf,
	})
	if err != nil {
		t.Fatalf("validator NewManager: %v", err)
	}

	applicantCapMgr := capability.NewChallengeManager(applicantSig.PubkeyHex(), applicantSig)
	applicantStreamMgr, err := capability_stream.NewManager(applicantH, capability_stream.Config{
		CapabilityManager: applicantCapMgr,
		TaskIDs:           taskIDs,
		Logf:              t.Logf,
	})
	if err != nil {
		t.Fatalf("applicant NewManager: %v", err)
	}

	if err := applicantH.Connect(ctx, peer.AddrInfo{
		ID: validatorH.ID(), Addrs: validatorH.Addrs(),
	}); err != nil {
		t.Fatalf("connect: %v", err)
	}

	id, _ := makeTestIdentity(t)
	socketPath := filepath.Join(t.TempDir(), "netd.sock")
	srv, err := StartGRPCServer(socketPath, NewNetdServer(
		id, applicantH, nil, nil, nil, applicantCapMgr, applicantStreamMgr, nil,
	), nil)
	if err != nil {
		t.Fatalf("start grpc: %v", err)
	}
	conn := dialUnixGRPC(t, socketPath)

	return &reqAttPair{
		ctx: ctx, cancel: cancel,
		validatorH: validatorH, validatorSig: validatorSig,
		applicantH: applicantH, applicantSig: applicantSig,
		srv: srv, conn: conn, taskIDs: taskIDs,
	}
}

// TestRequestAttestationHappyPath — the load-bearing happy path:
// Python sends start, daemon ferries Challenge over libp2p, Python
// builds + sends ChallengeResponse, daemon ferries ChallengeResponse
// over libp2p and reads the validator's outcome, daemon emits Outcome
// frame with success=true and a CoSignature.
func TestRequestAttestationHappyPath(t *testing.T) {
	pair := newReqAttPair(t, []string{"count_py_files", "echo_nonce"})
	defer pair.close(t)

	client := pb.NewCapabilityServiceClient(pair.conn)
	stream, err := client.RequestAttestation(pair.ctx)
	if err != nil {
		t.Fatalf("open stream: %v", err)
	}

	// 1. Send start.
	if err := stream.Send(&pb.AttestationApplicantFrame{
		Body: &pb.AttestationApplicantFrame_Start{
			Start: &pb.AttestationStartRequest{
				TargetPeerId: pair.validatorH.ID().String(),
			},
		},
	}); err != nil {
		t.Fatalf("send start: %v", err)
	}

	// 2. Recv Challenge.
	frame, err := stream.Recv()
	if err != nil {
		t.Fatalf("recv challenge: %v", err)
	}
	challenge := frame.GetChallenge()
	if challenge == nil {
		t.Fatalf("expected challenge frame, got: %+v", frame)
	}
	if challenge.Body == nil {
		t.Fatal("challenge body nil")
	}
	if got, want := challenge.Body.ApplicantPubkey, pair.applicantSig.PubkeyHex(); got != want {
		t.Errorf("challenge applicant_pubkey = %q, want %q", got, want)
	}

	// 3. Build a valid ChallengeResponse and send it.
	resp := makeApplicantResponseInTest(t, challenge, pair.applicantSig, time.Now())
	if err := stream.Send(&pb.AttestationApplicantFrame{
		Body: &pb.AttestationApplicantFrame_Response{Response: resp},
	}); err != nil {
		t.Fatalf("send response: %v", err)
	}

	// 4. Recv outcome.
	frame, err = stream.Recv()
	if err != nil {
		t.Fatalf("recv outcome: %v", err)
	}
	outcome := frame.GetOutcome()
	if outcome == nil {
		t.Fatalf("expected outcome frame, got: %+v", frame)
	}
	if !outcome.Success {
		t.Fatalf("outcome.Success = false, error = %q", outcome.Error)
	}
	if outcome.CoSignature == nil {
		t.Fatal("outcome cosignature nil despite success")
	}
	if outcome.CoSignature.ValidatorPubkey != pair.validatorSig.PubkeyHex() {
		t.Errorf(
			"cosig validator = %q, want %q",
			outcome.CoSignature.ValidatorPubkey, pair.validatorSig.PubkeyHex(),
		)
	}

	// Stream is closed by the daemon after sending the outcome — a
	// follow-up Recv should yield io.EOF.
	if _, err := stream.Recv(); err == nil {
		t.Error("expected EOF after outcome, got nil")
	}
}

// TestRequestAttestationFirstFrameMustBeStart — protocol-level
// guardrail: the bridge rejects Python clients that try to skip the
// start frame and jump straight to a response. Surfaced as an
// InvalidArgument gRPC status.
func TestRequestAttestationFirstFrameMustBeStart(t *testing.T) {
	pair := newReqAttPair(t, []string{"count_py_files"})
	defer pair.close(t)

	client := pb.NewCapabilityServiceClient(pair.conn)
	stream, err := client.RequestAttestation(pair.ctx)
	if err != nil {
		t.Fatalf("open stream: %v", err)
	}

	// Send a response frame (with empty body) as the first frame.
	if err := stream.Send(&pb.AttestationApplicantFrame{
		Body: &pb.AttestationApplicantFrame_Response{
			Response: &pb.ChallengeResponse{},
		},
	}); err != nil {
		t.Fatalf("send response: %v", err)
	}
	// CloseSend so the server's Recv returns whatever it has.
	if err := stream.CloseSend(); err != nil {
		t.Fatalf("close send: %v", err)
	}

	_, err = stream.Recv()
	if err == nil {
		t.Fatal("expected error from server, got nil")
	}
	if !strings.Contains(err.Error(), "first frame") {
		t.Errorf("expected 'first frame' error, got: %v", err)
	}
}

// TestRequestAttestationInvalidPeerID — bridge validates the
// target_peer_id BEFORE opening any libp2p stream. Bad peer IDs are
// surfaced as InvalidArgument.
func TestRequestAttestationInvalidPeerID(t *testing.T) {
	pair := newReqAttPair(t, []string{"count_py_files"})
	defer pair.close(t)

	client := pb.NewCapabilityServiceClient(pair.conn)
	stream, err := client.RequestAttestation(pair.ctx)
	if err != nil {
		t.Fatalf("open stream: %v", err)
	}

	if err := stream.Send(&pb.AttestationApplicantFrame{
		Body: &pb.AttestationApplicantFrame_Start{
			Start: &pb.AttestationStartRequest{
				TargetPeerId: "this is not a valid peer id",
			},
		},
	}); err != nil {
		t.Fatalf("send start: %v", err)
	}

	_, err = stream.Recv()
	if err == nil {
		t.Fatal("expected error from server, got nil")
	}
	if !strings.Contains(err.Error(), "invalid target_peer_id") {
		t.Errorf("expected 'invalid target_peer_id' error, got: %v", err)
	}
}

// TestRequestAttestationCapStreamUnavailable — when the server is
// constructed without a capStreamMgr (test/early-init configuration),
// RequestAttestation returns Unavailable rather than crashing.
func TestRequestAttestationCapStreamUnavailable(t *testing.T) {
	id, _ := makeTestIdentity(t)
	socketPath := filepath.Join(t.TempDir(), "netd.sock")
	srv, err := StartGRPCServer(socketPath, NewNetdServer(id, nil, nil, nil, nil, nil, nil, nil), nil)
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	t.Cleanup(srv.Stop)

	conn := dialUnixGRPC(t, socketPath)
	defer conn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	client := pb.NewCapabilityServiceClient(conn)
	stream, err := client.RequestAttestation(ctx)
	if err != nil {
		t.Fatalf("open stream: %v", err)
	}
	if _, err := stream.Recv(); err == nil {
		t.Fatal("expected Unavailable, got nil")
	} else if !strings.Contains(err.Error(), "Unavailable") &&
		!strings.Contains(err.Error(), "not initialized") {
		t.Errorf("expected Unavailable error, got: %v", err)
	}
}

// =============================================================================
// Test helpers — minimal libp2p host + signer mirror of
// capability_stream/capability_stream_test.go's helpers. Duplicated
// here because that test's helpers live in package capability_stream_test
// and Go won't let us cross the package boundary for test-only code.
// =============================================================================

type capStreamTestSigner struct {
	priv ed25519.PrivateKey
	pub  ed25519.PublicKey
}

func (s *capStreamTestSigner) SignBytes(b []byte) []byte {
	return ed25519.Sign(s.priv, b)
}

func (s *capStreamTestSigner) PubkeyHex() string {
	return hex.EncodeToString(s.pub)
}

func newCapStreamPeerWithSigner(t *testing.T) (libp2phost.Host, *capStreamTestSigner, func()) {
	t.Helper()
	priv, pub, err := libp2pcrypto.GenerateEd25519Key(cryptorand.Reader)
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
	signer := &capStreamTestSigner{
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

// makeApplicantResponseInTest forges a valid ChallengeResponse over a
// real Ed25519 key. Each TaskResult uses synthetic ICP payload bytes
// (no Python in the loop), but the per-task signature and the body
// signature both verify under the applicant signer — same crypto
// path as the real applicant.
func makeApplicantResponseInTest(
	t *testing.T,
	challenge *pb.Challenge,
	applicant *capStreamTestSigner,
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
	bodyBytes, err := protomarshal.MarshalOptions{Deterministic: true}.Marshal(body)
	if err != nil {
		t.Fatalf("marshal body: %v", err)
	}
	return &pb.ChallengeResponse{
		Body:               body,
		ApplicantSignature: ed25519.Sign(applicant.priv, bodyBytes),
	}
}

// Tiny smoke test that ed25519 signing through the loaded identity
// matches a direct ed25519.Sign over the same key bytes — defensive
// check that the BLAKE3-derived seed maps to a valid Ed25519 key.
func TestIdentitySigningRoundtrip(t *testing.T) {
	id, _ := makeTestIdentity(t)

	msg := []byte("the rain in spain falls mainly on the plain")
	sig := id.SignBytes(msg)

	pub := ed25519.PublicKey(id.RawPubKey)
	if !ed25519.Verify(pub, msg, sig) {
		t.Fatal("signature failed to verify with derived public key")
	}
}
