// Package capability implements the cryptographic primitives behind
// Gyza's Tier-3 proof-of-capability sybil resistance.
//
// Three actors:
//
//   Applicant  — a node seeking Tier-3 standing.
//   Validator  — an existing Tier-3 node willing to issue challenges.
//   Verifier   — anyone reading the DHT who needs to check whether a
//                claimed Tier-3 advertiser actually holds a valid cert.
//
// Three primitives:
//
//   IssueChallenge   — a Validator builds and signs a Challenge.
//   VerifyResponse   — a Validator checks a ChallengeResponse and
//                      returns a CoSignature on the AttestationBody.
//   AssembleAndVerify — anyone collects ≥ MinCoSignatures cosigs into
//                       an AttestationCert, or verifies one.
//
// Why this is in a tight package: all three primitives operate on
// deterministic-marshal of the *Body proto messages. Keeping the
// canonical-bytes function in one file makes "this is the bytes that
// got signed" unambiguous; cross-language reproduction (Go validator
// signs bytes; Python applicant is ALSO Tier-3 and might verify the
// cosig) just needs Marshal{Deterministic:true}.
//
// What's NOT in this package:
//
//   * The libp2p stream protocol that ferries Challenge / Response /
//     CoSignature between nodes. Lives in Session 7 once the global
//     cluster formation flow needs it.
//   * The Python eval suite that actually executes tasks. Lives in
//     gyza/capability_eval.py once the demo is built.
//   * The Tier-3 enforcement on PublishAgent. Stubbed for Phase 4 —
//     today any node may publish ANY tier; sybil resistance is a
//     verification-time concern at the read side.
package capability

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	pb "gyza/netd/internal/grpc/proto"

	"github.com/zeebo/blake3"
	"google.golang.org/protobuf/proto"
)

// MinCoSignatures is the threshold for a valid AttestationCert. Below
// this, AssembleAttestation refuses to construct a cert and
// VerifyAttestation rejects one. Tied to the spec's "2 of 3" rule.
const MinCoSignatures = 2

// DefaultChallengeTTL is the maximum window between Challenge issue
// and Response submission. Short enough that an offline applicant
// can't accumulate a stockpile of pre-signed challenges; long enough
// that real eval-task execution (which can take 60s+) fits.
const DefaultChallengeTTL = 5 * time.Minute

// DefaultAttestationTTL bounds how long an AttestationCert is
// considered valid by the verifier. After expiry, a Tier-3 node must
// re-attest. 30 days mirrors the spec.
const DefaultAttestationTTL = 30 * 24 * time.Hour

// NonceSize is the byte length of the per-Challenge nonce. 32 bytes
// = 256 bits of unpredictability, which is overkill for replay
// detection but cheap.
const NonceSize = 32

// IssuedTier is the tier value an attestation cert grants. Hard-coded
// to 3 because that's the only tier that requires proof of capability;
// tiers 0–2 are bootstrap tiers that don't need this protocol.
const IssuedTier = 3

// ChallengeManager is the per-node primitive surface. It only needs
// Ed25519 signing access (provided by `signer`) and a clock (provided
// by `now`, defaulting to time.Now).
//
// One instance per node is enough; ChallengeManager is stateless apart
// from the signer.
type ChallengeManager struct {
	pubkeyHex string
	signer    func(message []byte) []byte
	now       func() time.Time
}

// Signer interface lets the daemon plug in identity.Identity without
// importing it (avoids a needless dependency cycle if test fixtures
// want to inject a stub).
type Signer interface {
	SignBytes(b []byte) []byte
}

// NewChallengeManager returns a ChallengeManager bound to the given
// signer. pubkeyHex is the Ed25519 hex of the signer's public key —
// stamped into Challenge.body.challenger_pubkey and ditto for cosigs.
func NewChallengeManager(pubkeyHex string, signer Signer) *ChallengeManager {
	return &ChallengeManager{
		pubkeyHex: pubkeyHex,
		signer:    signer.SignBytes,
		now:       time.Now,
	}
}

// SetClock overrides the time source. Used by TestExpiredChallenge to
// fast-forward.
func (m *ChallengeManager) SetClock(now func() time.Time) {
	m.now = now
}

// =============================================================================
// IssueChallenge — Validator side
// =============================================================================

// IssueChallenge builds and signs a Challenge for the given applicant.
// taskIDs may be supplied by the caller (for deterministic tests) or
// left empty — the manager refuses empty challenge sets so the caller
// always sees the "no tasks specified" failure mode loudly.
//
// nonce is generated with crypto/rand. Caller doesn't need to provide
// one; supplying nonce externally would let callers accidentally
// re-use a nonce, which is exactly what replay protection prevents.
func (m *ChallengeManager) IssueChallenge(
	applicantPubkeyHex string,
	taskIDs []string,
	ttl time.Duration,
) (*pb.Challenge, error) {
	if applicantPubkeyHex == "" {
		return nil, errors.New("applicant_pubkey required")
	}
	if _, err := hex.DecodeString(applicantPubkeyHex); err != nil {
		return nil, fmt.Errorf("applicant_pubkey not hex: %w", err)
	}
	if len(taskIDs) == 0 {
		return nil, errors.New("at least one task_id required")
	}
	if ttl <= 0 {
		ttl = DefaultChallengeTTL
	}

	nonce := make([]byte, NonceSize)
	if _, err := rand.Read(nonce); err != nil {
		return nil, fmt.Errorf("nonce: %w", err)
	}

	now := m.now()
	body := &pb.ChallengeBody{
		ChallengerPubkey: m.pubkeyHex,
		ApplicantPubkey:  applicantPubkeyHex,
		TaskIds:          append([]string{}, taskIDs...), // defensive copy
		Nonce:            nonce,
		IssuedAtNs:       now.UnixNano(),
		ExpiresAtNs:      now.Add(ttl).UnixNano(),
	}
	bodyBytes, err := canonicalMarshal(body)
	if err != nil {
		return nil, fmt.Errorf("marshal body: %w", err)
	}
	sig := m.signer(bodyBytes)
	return &pb.Challenge{
		Body:                body,
		ChallengerSignature: sig,
	}, nil
}

// VerifyChallenge checks a Challenge's signature and freshness. Used
// by an applicant before executing the embedded tasks — a malformed
// or expired challenge from a misbehaving validator should be ignored
// before any work is wasted on it.
func (m *ChallengeManager) VerifyChallenge(c *pb.Challenge) error {
	if c == nil || c.Body == nil {
		return errors.New("nil challenge")
	}
	if len(c.ChallengerSignature) != ed25519.SignatureSize {
		return errors.New("invalid signature length")
	}
	pub, err := decodePubkey(c.Body.ChallengerPubkey)
	if err != nil {
		return fmt.Errorf("challenger pubkey: %w", err)
	}
	bodyBytes, err := canonicalMarshal(c.Body)
	if err != nil {
		return fmt.Errorf("marshal body: %w", err)
	}
	if !ed25519.Verify(pub, bodyBytes, c.ChallengerSignature) {
		return errors.New("signature mismatch")
	}
	now := m.now().UnixNano()
	if now < c.Body.IssuedAtNs {
		return errors.New("challenge issued in the future")
	}
	if now >= c.Body.ExpiresAtNs {
		return errors.New("challenge expired")
	}
	if len(c.Body.Nonce) != NonceSize {
		return errors.New("invalid nonce length")
	}
	return nil
}

// =============================================================================
// VerifyResponse — Validator side, returns a CoSignature on success
// =============================================================================

// TaskOutputVerifier is the per-task pluggable check. The verifier
// returns nil if the output_json is acceptable for the task_id, or an
// error explaining the rejection. Phase 3 leaves the implementation
// to callers (test stubs use a permissive verifier; the real eval
// suite plugs in deterministic checks per task).
//
// Even with a permissive output verifier, the ICP envelope signature
// must still match the applicant pubkey — without that, a free-rider
// could just send empty bytes and pass.
type TaskOutputVerifier func(taskID string, outputJSON []byte) error

// VerifyResponse runs every check and returns a CoSignature on
// success. The cosignature signs the AttestationBody the applicant
// will eventually assemble — so multiple validators independently
// produce signatures over the SAME canonical body bytes, and any
// verifier downstream just runs ed25519.Verify per cosig.
//
// Step order matters: cheap checks first, ed25519 verify last (it's
// the most expensive op).
func (m *ChallengeManager) VerifyResponse(
	challenge *pb.Challenge,
	response *pb.ChallengeResponse,
	verifyOutput TaskOutputVerifier,
) (*pb.CoSignature, error) {
	if challenge == nil || challenge.Body == nil {
		return nil, errors.New("nil challenge")
	}
	if response == nil || response.Body == nil {
		return nil, errors.New("nil response")
	}

	body := response.Body
	cb := challenge.Body

	// Bind: response must claim the same applicant the challenge
	// targeted, and echo the challenger.
	if body.ApplicantPubkey != cb.ApplicantPubkey {
		return nil, errors.New("applicant pubkey mismatch")
	}
	if body.ChallengerPubkey != cb.ChallengerPubkey {
		return nil, errors.New("challenger pubkey mismatch")
	}

	// Replay check — nonce must echo the challenge's nonce. Catches
	// the "applicant submits an old response signed by a different
	// challenger's nonce" attack and the "applicant re-submits the
	// same response twice" idempotency case (caller's job to
	// dedupe by nonce server-side; here we just validate the bind).
	if !bytesEqual(body.Nonce, cb.Nonce) {
		return nil, errors.New("nonce mismatch")
	}

	// Freshness — even a valid signature on a stale response must be
	// rejected. We check completed_at_ns falls within the challenge
	// window.
	if body.CompletedAtNs < cb.IssuedAtNs {
		return nil, errors.New("response completed before challenge issued")
	}
	if body.CompletedAtNs > cb.ExpiresAtNs {
		return nil, errors.New("response completed after challenge expired")
	}

	// Task results: every task_id from the challenge must have a
	// matching TaskResult, and each ICP envelope's embedded signature
	// must verify under its declared agent pubkey.
	//
	// Note on agent vs applicant identity: gyza separates the
	// COMPOSITOR (durable, libp2p PeerID, signs the response body) from
	// the AGENT (ephemeral, runner-bound, signs ICP envelopes). The
	// validator does NOT require ``IcpAgentPubkeyHex == applicantPubkey``
	// — that's a flat-key model the in-process Go test path happens to
	// use, but the cross-network protocol's design intent (per
	// CLAUDE.md §11) is "agent issued by compositor", verified via the
	// capability manifest in a follow-up. For now: confirm the agent
	// did sign these bytes (cryptographic proof of compute), and trust
	// that the response's compositor-bound signature ties the bundle
	// to the applicant.
	resultByID := make(map[string]*pb.TaskResult, len(body.TaskResults))
	for _, r := range body.TaskResults {
		resultByID[r.TaskId] = r
	}
	for _, tid := range cb.TaskIds {
		r, ok := resultByID[tid]
		if !ok {
			return nil, fmt.Errorf("missing task result %s", tid)
		}
		if err := verifyTaskResult(r); err != nil {
			return nil, fmt.Errorf("task %s: %w", tid, err)
		}
		if verifyOutput != nil {
			if err := verifyOutput(tid, r.OutputJson); err != nil {
				return nil, fmt.Errorf("task %s output: %w", tid, err)
			}
		}
	}

	// Applicant signature over response body — proves the response is
	// from the claimed applicant.
	if len(response.ApplicantSignature) != ed25519.SignatureSize {
		return nil, errors.New("invalid applicant signature length")
	}
	applPub, err := decodePubkey(body.ApplicantPubkey)
	if err != nil {
		return nil, fmt.Errorf("applicant pubkey: %w", err)
	}
	bodyBytes, err := canonicalMarshal(body)
	if err != nil {
		return nil, fmt.Errorf("marshal response body: %w", err)
	}
	if !ed25519.Verify(applPub, bodyBytes, response.ApplicantSignature) {
		return nil, errors.New("applicant signature mismatch")
	}

	// All gates passed — issue a CoSignature on the AttestationBody.
	now := m.now()
	attestBody := &pb.AttestationBody{
		ApplicantPubkey:    body.ApplicantPubkey,
		IssuedAtNs:         now.UnixNano(),
		ExpiresAtNs:        now.Add(DefaultAttestationTTL).UnixNano(),
		TierGranted:        IssuedTier,
		ChallengeTaskIds:   append([]string{}, cb.TaskIds...),
	}
	abBytes, err := canonicalMarshal(attestBody)
	if err != nil {
		return nil, fmt.Errorf("marshal attestation body: %w", err)
	}
	sig := m.signer(abBytes)
	return &pb.CoSignature{
		ValidatorPubkey: m.pubkeyHex,
		Signature:       sig,
		SignedAtNs:      now.UnixNano(),
	}, nil
}

// verifyTaskResult runs the cross-language ICP-envelope check. Returns
// nil iff the embedded signature verifies under the claimed agent
// pubkey. Does NOT verify "agent issued by applicant compositor" —
// that lives at the manifest layer and is a documented follow-up
// (CLAUDE.md §11). We don't try to understand the JSON content —
// the eval suite's own verify function (passed via TaskOutputVerifier)
// handles task-specific output checks.
func verifyTaskResult(r *pb.TaskResult) error {
	if r == nil {
		return errors.New("nil task result")
	}
	pub, err := decodePubkey(r.IcpAgentPubkeyHex)
	if err != nil {
		return fmt.Errorf("ICP agent pubkey decode: %w", err)
	}
	sig, err := hex.DecodeString(r.IcpSignatureHex)
	if err != nil {
		return fmt.Errorf("ICP signature hex: %w", err)
	}
	if len(sig) != ed25519.SignatureSize {
		return fmt.Errorf("ICP signature length %d, want %d",
			len(sig), ed25519.SignatureSize)
	}
	if len(r.IcpPayloadBytes) == 0 {
		return errors.New("empty ICP payload")
	}
	// Python signs blake3(payload_bytes).digest() — we recompute that
	// digest and ed25519.Verify against it. Cross-language match is
	// guaranteed because both sides use the canonical JSON Python
	// already emitted (we never re-encode here).
	digest := blake3.Sum256(r.IcpPayloadBytes)
	if !ed25519.Verify(pub, digest[:], sig) {
		return errors.New("ICP envelope signature mismatch")
	}
	return nil
}

// =============================================================================
// AssembleAttestation / VerifyAttestation
// =============================================================================

// AssembleAttestation collects CoSignatures into an AttestationCert.
// All cosigs must sign the same AttestationBody (caller's
// responsibility to provide a consistent body — typically the body
// from the first cosig, since validators echo back identical bodies).
//
// Returns an error if fewer than MinCoSignatures cosigs are supplied
// (otherwise we'd ship a cert that won't verify, which would be
// confusing).
func AssembleAttestation(
	body *pb.AttestationBody,
	cosigs []*pb.CoSignature,
) (*pb.AttestationCert, error) {
	if body == nil {
		return nil, errors.New("nil attestation body")
	}
	if len(cosigs) < MinCoSignatures {
		return nil, fmt.Errorf(
			"need ≥%d cosignatures, got %d", MinCoSignatures, len(cosigs),
		)
	}
	out := &pb.AttestationCert{
		Body:         body,
		CoSignatures: append([]*pb.CoSignature{}, cosigs...),
	}
	if _, err := VerifyAttestation(out, time.Now); err != nil {
		return nil, fmt.Errorf("assembled cert fails self-verify: %w", err)
	}
	return out, nil
}

// VerifyAttestation checks an attestation cert for:
//
//	* freshness (now within [issued_at, expires_at])
//	* tier_granted == IssuedTier (we don't accept attestations that
//	  claim to grant some other tier — that's not a thing)
//	* ≥ MinCoSignatures distinct validators
//	* every cosignature is a valid Ed25519 over the canonical body
//
// `now` is a callable so tests can fast-forward without monkey-
// patching the global clock. Pass time.Now in production.
func VerifyAttestation(
	cert *pb.AttestationCert,
	now func() time.Time,
) (int, error) {
	if cert == nil || cert.Body == nil {
		return 0, errors.New("nil cert")
	}
	body := cert.Body
	if body.TierGranted != IssuedTier {
		return 0, fmt.Errorf("tier %d != %d", body.TierGranted, IssuedTier)
	}
	t := now().UnixNano()
	if t < body.IssuedAtNs {
		return 0, errors.New("cert issued in the future")
	}
	if t >= body.ExpiresAtNs {
		return 0, errors.New("cert expired")
	}
	bodyBytes, err := canonicalMarshal(body)
	if err != nil {
		return 0, fmt.Errorf("marshal body: %w", err)
	}

	seen := make(map[string]struct{}, len(cert.CoSignatures))
	valid := 0
	for _, cs := range cert.CoSignatures {
		if cs == nil {
			continue
		}
		if _, dup := seen[cs.ValidatorPubkey]; dup {
			// Two signatures from the same validator count as one;
			// otherwise an attacker who controls one Tier-3 key
			// could trivially mint a "self-attested" cert.
			continue
		}
		pub, err := decodePubkey(cs.ValidatorPubkey)
		if err != nil {
			continue
		}
		if len(cs.Signature) != ed25519.SignatureSize {
			continue
		}
		if !ed25519.Verify(pub, bodyBytes, cs.Signature) {
			continue
		}
		seen[cs.ValidatorPubkey] = struct{}{}
		valid++
	}
	if valid < MinCoSignatures {
		return valid, fmt.Errorf(
			"only %d valid cosignatures, need ≥%d", valid, MinCoSignatures,
		)
	}
	return valid, nil
}

// =============================================================================
// helpers
// =============================================================================

// canonicalMarshal is the single canonical-bytes routine for ALL signing
// and verification in this package. Deterministic-protobuf marshal
// keeps Go-Go reproduction stable and gives us a clear contract for
// future Python signers (Python's protobuf library has its own
// deterministic marshal flag that produces identical bytes).
func canonicalMarshal(m proto.Message) ([]byte, error) {
	return proto.MarshalOptions{Deterministic: true}.Marshal(m)
}

func decodePubkey(hexStr string) (ed25519.PublicKey, error) {
	b, err := hex.DecodeString(hexStr)
	if err != nil {
		return nil, err
	}
	if len(b) != ed25519.PublicKeySize {
		return nil, fmt.Errorf("pubkey length %d, want %d", len(b), ed25519.PublicKeySize)
	}
	return ed25519.PublicKey(b), nil
}

func bytesEqual(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
