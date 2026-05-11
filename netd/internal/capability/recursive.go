package capability

// Recursive Tier-3 verification — Session 16 (#21f follow-up A2).
//
// VerifyAttestation today accepts a cert if ≥ MinCoSignatures distinct
// validators have valid Ed25519 signatures over the canonical body.
// It does NOT check that the signing validators are themselves Tier-3
// attested. A Sybil that controls N pubkeys can issue cosigs that
// pass VerifyAttestation — the attack is "I created N fresh keys and
// had them sign each other's certs."
//
// The defense is to bottom out validator trust at a manually-pinned
// "trusted bootstrap set" of pubkeys known to be Tier-3 out of band
// (Foundation-blessed initial validators), and recursively verify
// that any non-bootstrap signer has its own valid Tier-3 cert whose
// cosigners are in turn either bootstrap members or recursively
// verifiable. Three guards:
//
//   - Trusted bootstrap set is the base case (terminates recursion)
//   - Cycle detection: if pubkey appears in the current verification
//     path, don't accept it (prevents A→B→A mutual-validation farms)
//   - Depth bound: hard cap on recursion (prevents pathological cases
//     where a malicious peer constructs arbitrarily-deep cert chains)
//
// Performance: each non-bootstrap pubkey costs one DHT fetch. A
// positive cache amortizes repeated lookups within one
// RecursiveVerifier instance. Negatives are NOT cached — they can be
// transient (fetch failure, momentary cycle in another branch), and
// sticky-negatives would hide validators that legitimately become
// Tier-3 later.
//
// Integration with Session 15's verify-on-fetch is left to a follow-up
// session — this file is the pure logic. The find_agents hot path
// can swap from VerifyAttestation to RecursiveVerifier.Verify once
// the Foundation bootstrap set is configured.

import (
	"context"
	"crypto/ed25519"
	"errors"
	"fmt"
	"sync"
	"time"

	pb "gyza/netd/internal/grpc/proto"
)

// DefaultRecursiveMaxDepth bounds how many levels of validator-of-
// validator chains the recursive verifier will walk. At depth N the
// verifier has done N cert fetches in the current chain. 5 is generous
// for any plausible network topology (Tier-3 validators don't form
// 6-deep chains in practice) while protecting against pathological
// chains crafted by a malicious peer.
const DefaultRecursiveMaxDepth = 5

// RecursiveCertFetcher fetches the AttestationCert for a given pubkey.
// Typically the daemon's dht.GyzaDHT.FetchAttestation. Pulled out as a
// dependency so tests can stub without spinning up libp2p, and so the
// capability package doesn't have to depend on the dht package.
type RecursiveCertFetcher func(ctx context.Context, pubkey string) (*pb.AttestationCert, error)

// RecursiveVerifier verifies that an AttestationCert is well-formed,
// cryptographically valid, AND that ≥ MinCoSignatures of its
// cosigners are themselves Tier-3 attested (either in the trusted
// bootstrap set or recursively verifiable).
type RecursiveVerifier struct {
	// TrustedBootstrap is the set of pubkeys (hex) accepted as Tier-3
	// without recursion. Required to be non-empty; an empty set
	// causes every cert to be rejected (no base case for recursion).
	TrustedBootstrap map[string]struct{}

	// MaxDepth caps recursion depth. depth=0 examines the user-supplied
	// cert; each cosig recursion increments. depth=MaxDepth is the
	// hardest level we'll walk before declaring the validator
	// non-Tier-3. 0 means "only trusted bootstrap counts; no
	// recursion." Use DefaultRecursiveMaxDepth for sane production
	// behavior.
	MaxDepth int

	// FetchCert retrieves the cert for a pubkey from the DHT (or
	// equivalent). Errors and nil results are treated as
	// "non-Tier-3," NOT cached as negatives — the caller can retry.
	FetchCert RecursiveCertFetcher

	// Now is the clock for freshness checks; defaults to time.Now.
	// Override for tests that fast-forward.
	Now func() time.Time

	mu    sync.Mutex
	cache map[string]bool // pubkey → verified-Tier-3 (positive cache only)
}

// NewRecursiveVerifier constructs a RecursiveVerifier with sane
// defaults. trustedBootstrap is required (non-empty); fetch is
// required.
func NewRecursiveVerifier(
	trustedBootstrap map[string]struct{},
	fetch RecursiveCertFetcher,
) *RecursiveVerifier {
	tb := make(map[string]struct{}, len(trustedBootstrap))
	for k := range trustedBootstrap {
		tb[k] = struct{}{}
	}
	return &RecursiveVerifier{
		TrustedBootstrap: tb,
		MaxDepth:         DefaultRecursiveMaxDepth,
		FetchCert:        fetch,
		Now:              time.Now,
		cache:            make(map[string]bool),
	}
}

// Verify checks that the cert is well-formed, cryptographically
// valid, AND ≥ MinCoSignatures of its cosigners are themselves
// Tier-3 attested. Returns (count_of_tier3_cosigners, error).
//
// Failure modes:
//   - nil cert → error
//   - tier mismatch / future-issued / expired → error
//   - body marshal failure → error
//   - too few Tier-3-verified cosignatures → error with count
//
// Cosigs that fail Ed25519 verification, are from validators not
// recursively verifiable, or are duplicates by validator_pubkey
// don't count toward the Tier-3 quorum.
func (r *RecursiveVerifier) Verify(ctx context.Context, cert *pb.AttestationCert) (int, error) {
	if r.TrustedBootstrap == nil || len(r.TrustedBootstrap) == 0 {
		return 0, errors.New("recursive verify: TrustedBootstrap is empty (no base case)")
	}
	if r.FetchCert == nil {
		return 0, errors.New("recursive verify: FetchCert is nil")
	}
	now := r.Now
	if now == nil {
		now = time.Now
	}
	return r.verifyInner(ctx, cert, make(map[string]struct{}), 0)
}

// verifyInner runs the cert-level checks AND the per-cosig Tier-3
// recursive validation. `seen` is the cycle-detection path; `depth`
// is how many recursive fetches we've done in the current chain.
func (r *RecursiveVerifier) verifyInner(
	ctx context.Context,
	cert *pb.AttestationCert,
	seen map[string]struct{},
	depth int,
) (int, error) {
	if cert == nil || cert.Body == nil {
		return 0, errors.New("nil cert")
	}
	body := cert.Body
	if body.TierGranted != IssuedTier {
		return 0, fmt.Errorf("tier %d != %d", body.TierGranted, IssuedTier)
	}
	t := r.Now().UnixNano()
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

	sigSeen := make(map[string]struct{}, len(cert.CoSignatures))
	tier3Valid := 0
	for _, cs := range cert.CoSignatures {
		if cs == nil {
			continue
		}
		if _, dup := sigSeen[cs.ValidatorPubkey]; dup {
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
		sigSeen[cs.ValidatorPubkey] = struct{}{}

		// Standard VerifyAttestation would stop here. Recursive
		// verifier additionally requires the signer itself be
		// Tier-3.
		if r.isTier3(ctx, cs.ValidatorPubkey, seen, depth) {
			tier3Valid++
		}
	}
	if tier3Valid < MinCoSignatures {
		return tier3Valid, fmt.Errorf(
			"only %d Tier-3-verified cosignatures, need ≥%d",
			tier3Valid, MinCoSignatures,
		)
	}
	return tier3Valid, nil
}

// isTier3 returns true iff pubkey is either in the trusted bootstrap
// set or has a recursively-verifiable Tier-3 cert. Carries cycle
// detection (seen) and depth bound (depth).
func (r *RecursiveVerifier) isTier3(
	ctx context.Context,
	pubkey string,
	seen map[string]struct{},
	depth int,
) bool {
	// Base case 1: trusted bootstrap.
	if _, ok := r.TrustedBootstrap[pubkey]; ok {
		return true
	}

	// Cycle detection: pubkey already in current recursion path.
	// Without this, two non-bootstrap validators that cosign each
	// other's certs would form a mutually-validating clique that
	// no bootstrap member ever vouched for.
	if _, inPath := seen[pubkey]; inPath {
		return false
	}

	// Depth bound: at depth >= MaxDepth we refuse to recurse deeper.
	// depth counts fetches done in this chain so far; calling isTier3
	// here would imply doing fetch #(depth+1) which exceeds MaxDepth.
	if depth >= r.MaxDepth {
		return false
	}

	// Positive cache.
	r.mu.Lock()
	if cached, ok := r.cache[pubkey]; ok {
		r.mu.Unlock()
		return cached
	}
	r.mu.Unlock()

	// Fetch the validator's own cert.
	cert, err := r.FetchCert(ctx, pubkey)
	if err != nil || cert == nil || cert.Body == nil {
		// Don't cache — transient. Caller can retry.
		return false
	}

	// The fetched cert MUST attest to the SAME pubkey we're trying
	// to verify. Otherwise a malicious DHT peer could substitute
	// someone else's cert (a Tier-3 one) in response to a fetch for
	// a non-Tier-3 pubkey.
	if cert.Body.ApplicantPubkey != pubkey {
		return false
	}

	// Recurse. New seen set: copy + add the pubkey we're examining.
	newSeen := make(map[string]struct{}, len(seen)+1)
	for k := range seen {
		newSeen[k] = struct{}{}
	}
	newSeen[pubkey] = struct{}{}

	_, err = r.verifyInner(ctx, cert, newSeen, depth+1)
	result := err == nil

	// Cache positives only. A definitive negative for a malformed
	// cert is stable, but a "cosigs not yet Tier-3" negative for
	// this query may be transient (the cosigs might be verifiable
	// next minute when their certs republish). Caching negatives
	// would sticky-hide them. The cost: every non-Tier-3 pubkey
	// gets re-fetched on each top-level Verify, but that's bounded
	// by the cosig count of the top-level cert (≤ a few per call).
	if result {
		r.mu.Lock()
		r.cache[pubkey] = true
		r.mu.Unlock()
	}
	return result
}

// CacheLen reports the size of the positive cache. For tests + diagnostics.
func (r *RecursiveVerifier) CacheLen() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.cache)
}
