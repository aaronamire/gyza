package capability_test

// The five Phase 3 Session 5 spec tests. All operate in-process — no
// libp2p, no DHT, no gRPC. They cover only the cryptographic surface,
// which is the irreducible core: if these tests fail, the entire
// sybil-resistance scheme is broken.
//
//	TestChallengeIssuanceAndVerification — happy path, full round-trip.
//	TestReplayAttackPrevented            — same response submitted under
//	                                       a different challenge fails.
//	TestExpiredChallenge                 — clock-shifted past the window.
//	TestInvalidICPEnvelope               — corrupted ICP signature.
//	TestAttestationCert                  — 2 of 3 valid; 1 of 3 rejected.

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"testing"
	"time"

	"gyza/netd/internal/capability"
	pb "gyza/netd/internal/grpc/proto"

	"github.com/zeebo/blake3"
	"google.golang.org/protobuf/proto"
)

// edSigner is a minimal capability.Signer implementation that wraps a
// raw Ed25519 private key. We use it instead of identity.Identity to
// keep the test free of file-IO setup and 0600-mode requirements.
type edSigner struct {
	priv ed25519.PrivateKey
	pub  ed25519.PublicKey
}

func newSigner(t *testing.T) *edSigner {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("ed25519.GenerateKey: %v", err)
	}
	return &edSigner{priv: priv, pub: pub}
}

func (s *edSigner) SignBytes(b []byte) []byte {
	return ed25519.Sign(s.priv, b)
}

func (s *edSigner) PubkeyHex() string {
	return hex.EncodeToString(s.pub)
}

// makeApplicantResponse builds a ChallengeResponse for the given
// challenge as if the applicant had run every requested task and
// signed each output. ICP envelopes are synthesized: a 200-byte
// "payload" stand-in plus a real ed25519 signature, so the
// challenger's verifyTaskResult crypto path runs exactly as it would
// in production.
func makeApplicantResponse(
	t *testing.T,
	challenge *pb.Challenge,
	applicantSigner *edSigner,
	completedAt time.Time,
) *pb.ChallengeResponse {
	t.Helper()
	results := make([]*pb.TaskResult, 0, len(challenge.Body.TaskIds))
	for _, taskID := range challenge.Body.TaskIds {
		// Synthetic ICP payload — opaque bytes, but real crypto.
		// In production this is the canonical-JSON of the ICP
		// envelope minus the signature field; for the test the
		// content doesn't matter as long as the signature/digest
		// pair is genuine.
		payload := []byte("synthetic-icp-payload:" + taskID)
		digest := blake3.Sum256(payload)
		sig := ed25519.Sign(applicantSigner.priv, digest[:])
		results = append(results, &pb.TaskResult{
			TaskId:            taskID,
			OutputJson:        []byte(`{"result":"ok"}`),
			IcpPayloadBytes:   payload,
			IcpSignatureHex:   hex.EncodeToString(sig),
			IcpAgentPubkeyHex: applicantSigner.PubkeyHex(),
			DurationMs:        100,
		})
	}
	body := &pb.ResponseBody{
		ApplicantPubkey:  applicantSigner.PubkeyHex(),
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
		ApplicantSignature: ed25519.Sign(applicantSigner.priv, bodyBytes),
	}
}

// TestChallengeIssuanceAndVerification — the happy path. Validator
// issues a challenge; applicant builds the obvious response; validator
// returns a CoSignature.
func TestChallengeIssuanceAndVerification(t *testing.T) {
	validator := newSigner(t)
	applicant := newSigner(t)
	mgr := capability.NewChallengeManager(validator.PubkeyHex(), validator)

	taskIDs := []string{"file_list_001", "file_read_001", "search_001"}
	challenge, err := mgr.IssueChallenge(applicant.PubkeyHex(), taskIDs, 5*time.Minute)
	if err != nil {
		t.Fatalf("IssueChallenge: %v", err)
	}

	// Applicant verifies the challenge before bothering to execute.
	applicantMgr := capability.NewChallengeManager(applicant.PubkeyHex(), applicant)
	if err := applicantMgr.VerifyChallenge(challenge); err != nil {
		t.Fatalf("VerifyChallenge (applicant side): %v", err)
	}

	// Applicant builds and signs the response.
	response := makeApplicantResponse(t, challenge, applicant, time.Now())

	// Validator runs VerifyResponse and gets a CoSignature.
	cosig, err := mgr.VerifyResponse(challenge, response, nil)
	if err != nil {
		t.Fatalf("VerifyResponse: %v", err)
	}
	if cosig.ValidatorPubkey != validator.PubkeyHex() {
		t.Errorf("cosig validator = %s, want %s", cosig.ValidatorPubkey, validator.PubkeyHex())
	}
	if len(cosig.Signature) != ed25519.SignatureSize {
		t.Errorf("cosig signature length = %d, want %d",
			len(cosig.Signature), ed25519.SignatureSize)
	}
}

// TestReplayAttackPrevented — submitting a response with a stale
// nonce against a freshly-issued challenge must fail. The nonce is
// the binding between Challenge and Response; pollute it and the
// bind breaks.
func TestReplayAttackPrevented(t *testing.T) {
	validator := newSigner(t)
	applicant := newSigner(t)
	mgr := capability.NewChallengeManager(validator.PubkeyHex(), validator)

	c1, err := mgr.IssueChallenge(applicant.PubkeyHex(), []string{"t1"}, time.Minute)
	if err != nil {
		t.Fatalf("issue 1: %v", err)
	}
	c2, err := mgr.IssueChallenge(applicant.PubkeyHex(), []string{"t1"}, time.Minute)
	if err != nil {
		t.Fatalf("issue 2: %v", err)
	}
	// Sanity: nonces differ.
	if string(c1.Body.Nonce) == string(c2.Body.Nonce) {
		t.Fatalf("two challenges generated identical nonces — RNG broken?")
	}

	// Applicant builds a response to c1, then tries to submit it
	// against c2 (the replay). VerifyResponse(c2, response_to_c1)
	// must fail on nonce mismatch.
	response := makeApplicantResponse(t, c1, applicant, time.Now())
	if _, err := mgr.VerifyResponse(c2, response, nil); err == nil {
		t.Fatal("VerifyResponse accepted a response with a stale nonce")
	}
}

// TestExpiredChallenge — a response submitted after the challenge's
// expires_at_ns is rejected, even if every signature is otherwise
// valid.
func TestExpiredChallenge(t *testing.T) {
	validator := newSigner(t)
	applicant := newSigner(t)
	mgr := capability.NewChallengeManager(validator.PubkeyHex(), validator)

	now := time.Unix(1_700_000_000, 0)
	mgr.SetClock(func() time.Time { return now })

	challenge, err := mgr.IssueChallenge(applicant.PubkeyHex(), []string{"t1"}, time.Minute)
	if err != nil {
		t.Fatalf("issue: %v", err)
	}

	// Applicant takes 2 minutes to "execute" — well past the
	// 1-minute window.
	completedAt := now.Add(2 * time.Minute)
	response := makeApplicantResponse(t, challenge, applicant, completedAt)

	// Move the validator's clock forward so the challenge has
	// expired by the time it sees the response.
	mgr.SetClock(func() time.Time { return now.Add(2 * time.Minute) })

	if _, err := mgr.VerifyResponse(challenge, response, nil); err == nil {
		t.Fatal("VerifyResponse accepted a response after challenge expiry")
	}

	// Also confirm: applicant-side VerifyChallenge would also reject.
	applMgr := capability.NewChallengeManager(applicant.PubkeyHex(), applicant)
	applMgr.SetClock(func() time.Time { return now.Add(2 * time.Minute) })
	if err := applMgr.VerifyChallenge(challenge); err == nil {
		t.Fatal("VerifyChallenge accepted an already-expired challenge")
	}
}

// TestInvalidICPEnvelope — the ICP signature in one of the task
// results is corrupted. VerifyResponse must reject the whole response.
func TestInvalidICPEnvelope(t *testing.T) {
	validator := newSigner(t)
	applicant := newSigner(t)
	mgr := capability.NewChallengeManager(validator.PubkeyHex(), validator)

	challenge, err := mgr.IssueChallenge(applicant.PubkeyHex(), []string{"t1", "t2"}, time.Minute)
	if err != nil {
		t.Fatalf("issue: %v", err)
	}
	response := makeApplicantResponse(t, challenge, applicant, time.Now())

	// Flip a bit in the second task's signature. The applicant
	// signature over the response body is still valid, so this
	// isolates the ICP-envelope check.
	sigBytes, err := hex.DecodeString(response.Body.TaskResults[1].IcpSignatureHex)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	sigBytes[0] ^= 0x01
	response.Body.TaskResults[1].IcpSignatureHex = hex.EncodeToString(sigBytes)

	// Re-sign the body since we mutated it (otherwise the response
	// body signature would also fail and we'd hit a different error
	// than the one the test is targeting).
	bodyBytes, err := proto.MarshalOptions{Deterministic: true}.Marshal(response.Body)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	response.ApplicantSignature = ed25519.Sign(applicant.priv, bodyBytes)

	if _, err := mgr.VerifyResponse(challenge, response, nil); err == nil {
		t.Fatal("VerifyResponse accepted a response with a corrupt ICP envelope")
	}
}

// TestAttestationCert — assembling a cert from cosignatures.
//
//	* 2 valid cosignatures → cert verifies.
//	* 1 valid cosignature → AssembleAttestation refuses to construct,
//	  and a hand-built cert with one cosig fails VerifyAttestation.
//	* a duplicated cosignature (same validator twice) counts as one,
//	  not two — defends against a single Tier-3 node minting a
//	  "self-attested" cert.
//	* an expired cert fails verification.
func TestAttestationCert(t *testing.T) {
	applicant := newSigner(t)
	v1 := newSigner(t)
	v2 := newSigner(t)
	v3 := newSigner(t)

	body := &pb.AttestationBody{
		ApplicantPubkey:  applicant.PubkeyHex(),
		IssuedAtNs:       time.Now().UnixNano(),
		ExpiresAtNs:      time.Now().Add(24 * time.Hour).UnixNano(),
		TierGranted:      capability.IssuedTier,
		ChallengeTaskIds: []string{"t1", "t2", "t3"},
	}
	bodyBytes, err := proto.MarshalOptions{Deterministic: true}.Marshal(body)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}

	cosig := func(s *edSigner) *pb.CoSignature {
		return &pb.CoSignature{
			ValidatorPubkey: s.PubkeyHex(),
			Signature:       ed25519.Sign(s.priv, bodyBytes),
			SignedAtNs:      time.Now().UnixNano(),
		}
	}

	// Happy: 2 of 3 sign → cert assembles and verifies.
	cert, err := capability.AssembleAttestation(body, []*pb.CoSignature{cosig(v1), cosig(v2)})
	if err != nil {
		t.Fatalf("AssembleAttestation 2/3: %v", err)
	}
	if n, err := capability.VerifyAttestation(cert, time.Now); err != nil {
		t.Errorf("VerifyAttestation 2/3 failed: %v (n=%d)", err, n)
	}

	// 3 of 3 also fine.
	cert3, err := capability.AssembleAttestation(body,
		[]*pb.CoSignature{cosig(v1), cosig(v2), cosig(v3)})
	if err != nil {
		t.Fatalf("AssembleAttestation 3/3: %v", err)
	}
	if n, err := capability.VerifyAttestation(cert3, time.Now); err != nil {
		t.Errorf("VerifyAttestation 3/3 failed: %v (n=%d)", err, n)
	}

	// 1 of 3: AssembleAttestation refuses.
	if _, err := capability.AssembleAttestation(body, []*pb.CoSignature{cosig(v1)}); err == nil {
		t.Error("AssembleAttestation accepted only 1 cosignature")
	}

	// Duplicate-validator forgery: same v1 cosig twice. VerifyAttestation
	// must count it as 1, not 2.
	dupCert := &pb.AttestationCert{
		Body:         body,
		CoSignatures: []*pb.CoSignature{cosig(v1), cosig(v1)},
	}
	if _, err := capability.VerifyAttestation(dupCert, time.Now); err == nil {
		t.Error("VerifyAttestation accepted duplicate-validator cosigs")
	}

	// Expired cert.
	staleBody := &pb.AttestationBody{
		ApplicantPubkey:  applicant.PubkeyHex(),
		IssuedAtNs:       time.Now().Add(-48 * time.Hour).UnixNano(),
		ExpiresAtNs:      time.Now().Add(-24 * time.Hour).UnixNano(),
		TierGranted:      capability.IssuedTier,
		ChallengeTaskIds: []string{"t1"},
	}
	staleBodyBytes, _ := proto.MarshalOptions{Deterministic: true}.Marshal(staleBody)
	staleCosig := func(s *edSigner) *pb.CoSignature {
		return &pb.CoSignature{
			ValidatorPubkey: s.PubkeyHex(),
			Signature:       ed25519.Sign(s.priv, staleBodyBytes),
			SignedAtNs:      time.Now().Add(-25 * time.Hour).UnixNano(),
		}
	}
	staleCert := &pb.AttestationCert{
		Body:         staleBody,
		CoSignatures: []*pb.CoSignature{staleCosig(v1), staleCosig(v2)},
	}
	if _, err := capability.VerifyAttestation(staleCert, time.Now); err == nil {
		t.Error("VerifyAttestation accepted an expired cert")
	}

	// Tampered body: changing tier_granted invalidates all cosigs.
	tampered := &pb.AttestationCert{
		Body: &pb.AttestationBody{
			ApplicantPubkey:  body.ApplicantPubkey,
			IssuedAtNs:       body.IssuedAtNs,
			ExpiresAtNs:      body.ExpiresAtNs,
			TierGranted:      99, // ← tampered
			ChallengeTaskIds: body.ChallengeTaskIds,
		},
		CoSignatures: cert.CoSignatures, // signatures from the original body
	}
	if _, err := capability.VerifyAttestation(tampered, time.Now); err == nil {
		t.Error("VerifyAttestation accepted a tampered body")
	}
}

// TestProposedAttestationBodyAggregatesAcrossValidators — load-bearing
// for #21d. Two validators called separately produce DIFFERENT bodies
// (different IssuedAtNs) without an applicant-proposed body, and
// their cosignatures cannot aggregate. With the applicant-proposed
// body path, both validators sign identical canonical bytes and the
// quorum verifies cleanly.
func TestProposedAttestationBodyAggregatesAcrossValidators(t *testing.T) {
	applicant := newSigner(t)
	v1 := newSigner(t)
	v2 := newSigner(t)

	mgrV1 := capability.NewChallengeManager(v1.PubkeyHex(), v1)
	mgrV2 := capability.NewChallengeManager(v2.PubkeyHex(), v2)

	taskIDs := []string{"alpha", "beta"}

	// Without proposed body: each validator authors its own. Force
	// observable timestamp drift by sleeping between the two issues.
	c1, err := mgrV1.IssueChallenge(applicant.PubkeyHex(), taskIDs, 0)
	if err != nil {
		t.Fatalf("v1 IssueChallenge: %v", err)
	}
	r1 := makeApplicantResponse(t, c1, applicant, time.Now())

	c2, err := mgrV2.IssueChallenge(applicant.PubkeyHex(), taskIDs, 0)
	if err != nil {
		t.Fatalf("v2 IssueChallenge: %v", err)
	}
	r2 := makeApplicantResponse(t, c2, applicant, time.Now())

	// First, the WITHOUT-proposal path: confirm cosigs don't aggregate.
	cosig1NoProposal, err := mgrV1.VerifyResponse(c1, r1, nil)
	if err != nil {
		t.Fatalf("v1 VerifyResponse no-proposal: %v", err)
	}
	cosig2NoProposal, err := mgrV2.VerifyResponse(c2, r2, nil)
	if err != nil {
		t.Fatalf("v2 VerifyResponse no-proposal: %v", err)
	}
	// Both validators authored their OWN body. Pick v1's-shaped body
	// for AssembleAttestation; v2's cosig won't verify against it.
	v1Body := &pb.AttestationBody{
		ApplicantPubkey:  applicant.PubkeyHex(),
		IssuedAtNs:       cosig1NoProposal.SignedAtNs,
		ExpiresAtNs:      cosig1NoProposal.SignedAtNs + int64(capability.DefaultAttestationTTL),
		TierGranted:      capability.IssuedTier,
		ChallengeTaskIds: taskIDs,
	}
	if _, err := capability.AssembleAttestation(v1Body, []*pb.CoSignature{
		cosig1NoProposal, cosig2NoProposal,
	}); err == nil {
		t.Fatal(
			"AssembleAttestation accepted divergent-body cosigs — that's the " +
				"bug this fix addresses; the test that proves it should fail " +
				"means the fix isn't applied",
		)
	}

	// Now: the WITH-proposal path. Applicant authors one body and
	// includes it in BOTH responses.
	now := time.Now()
	proposedBody := &pb.AttestationBody{
		ApplicantPubkey:  applicant.PubkeyHex(),
		IssuedAtNs:       now.UnixNano(),
		ExpiresAtNs:      now.Add(30 * 24 * time.Hour).UnixNano(),
		TierGranted:      capability.IssuedTier,
		ChallengeTaskIds: taskIDs,
	}
	r1WithBody := makeApplicantResponse(t, c1, applicant, now)
	r1WithBody.ProposedAttestationBody = proposedBody
	r2WithBody := makeApplicantResponse(t, c2, applicant, now)
	r2WithBody.ProposedAttestationBody = proposedBody

	cosig1, err := mgrV1.VerifyResponse(c1, r1WithBody, nil)
	if err != nil {
		t.Fatalf("v1 VerifyResponse with-proposal: %v", err)
	}
	cosig2, err := mgrV2.VerifyResponse(c2, r2WithBody, nil)
	if err != nil {
		t.Fatalf("v2 VerifyResponse with-proposal: %v", err)
	}
	cert, err := capability.AssembleAttestation(
		proposedBody, []*pb.CoSignature{cosig1, cosig2},
	)
	if err != nil {
		t.Fatalf("AssembleAttestation with shared proposed body: %v", err)
	}
	if n, err := capability.VerifyAttestation(cert, time.Now); err != nil {
		t.Errorf("VerifyAttestation 2-of-2 with proposed body: %v (n=%d)", err, n)
	}
}

// TestProposedAttestationBodyPlausibilityChecks — every plausibility
// rule is enforced. One subtest per check; each builds an otherwise-
// valid response with one field tampered to violate the rule, then
// asserts VerifyResponse rejects with a recognizable error message.
func TestProposedAttestationBodyPlausibilityChecks(t *testing.T) {
	applicant := newSigner(t)
	imposter := newSigner(t)
	v := newSigner(t)
	mgr := capability.NewChallengeManager(v.PubkeyHex(), v)
	taskIDs := []string{"alpha", "beta"}
	now := time.Now()

	makeValidProposal := func() *pb.AttestationBody {
		return &pb.AttestationBody{
			ApplicantPubkey:  applicant.PubkeyHex(),
			IssuedAtNs:       now.UnixNano(),
			ExpiresAtNs:      now.Add(30 * 24 * time.Hour).UnixNano(),
			TierGranted:      capability.IssuedTier,
			ChallengeTaskIds: taskIDs,
		}
	}

	cases := []struct {
		name      string
		mutate    func(*pb.AttestationBody)
		errSubstr string
	}{
		{
			name: "applicant_pubkey_mismatch",
			mutate: func(b *pb.AttestationBody) {
				b.ApplicantPubkey = imposter.PubkeyHex()
			},
			errSubstr: "applicant_pubkey mismatch",
		},
		{
			name:      "wrong_tier",
			mutate:    func(b *pb.AttestationBody) { b.TierGranted = 2 },
			errSubstr: "tier_granted",
		},
		{
			name: "issued_at_far_past",
			mutate: func(b *pb.AttestationBody) {
				b.IssuedAtNs = now.Add(-2 * time.Hour).UnixNano()
			},
			errSubstr: "clock skew",
		},
		{
			name: "issued_at_far_future",
			mutate: func(b *pb.AttestationBody) {
				b.IssuedAtNs = now.Add(2 * time.Hour).UnixNano()
				b.ExpiresAtNs = b.IssuedAtNs + int64(30*24*time.Hour)
			},
			errSubstr: "clock skew",
		},
		{
			name: "lifetime_too_long",
			mutate: func(b *pb.AttestationBody) {
				b.ExpiresAtNs = b.IssuedAtNs + int64(180*24*time.Hour)
			},
			errSubstr: "lifetime",
		},
		{
			name: "expires_before_issued",
			mutate: func(b *pb.AttestationBody) {
				b.ExpiresAtNs = b.IssuedAtNs - 1
			},
			errSubstr: "expires_at_ns must be after",
		},
		{
			name: "task_ids_mismatch",
			mutate: func(b *pb.AttestationBody) {
				b.ChallengeTaskIds = []string{"alpha", "different"}
			},
			errSubstr: "challenge_task_ids mismatch",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c, err := mgr.IssueChallenge(applicant.PubkeyHex(), taskIDs, 0)
			if err != nil {
				t.Fatalf("IssueChallenge: %v", err)
			}
			// Build the response AFTER the challenge issues — otherwise
			// completed_at_ns lands before issued_at_ns and an earlier
			// check rejects before plausibility runs.
			r := makeApplicantResponse(t, c, applicant, time.Now())
			body := makeValidProposal()
			tc.mutate(body)
			r.ProposedAttestationBody = body

			_, err = mgr.VerifyResponse(c, r, nil)
			if err == nil {
				t.Fatalf("VerifyResponse accepted bad proposal (%s)", tc.name)
			}
			if !contains(err.Error(), tc.errSubstr) {
				t.Errorf(
					"error %q does not contain %q",
					err.Error(), tc.errSubstr,
				)
			}
		})
	}
}

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
