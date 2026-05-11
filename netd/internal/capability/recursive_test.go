package capability_test

// Unit tests for RecursiveVerifier (Session 16, A2). Uses a
// dictionary-backed stub fetcher so we can exercise recursion / cycle
// detection / depth bound / cache behavior without spinning up a DHT.
// Real cosig math is produced via ed25519 directly — same shape as
// production.

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"gyza/netd/internal/capability"
	pb "gyza/netd/internal/grpc/proto"

	"google.golang.org/protobuf/proto"
)

// recSigner is the test-local Ed25519 signer used to mint certs with
// real signatures. Mirrors capability_test.go's edSigner but exported
// names since this is in the external test package.
type recSigner struct {
	priv ed25519.PrivateKey
	pub  ed25519.PublicKey
}

func newRecSigner(t *testing.T) *recSigner {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("ed25519.GenerateKey: %v", err)
	}
	return &recSigner{priv: priv, pub: pub}
}

func (s *recSigner) hex() string { return hex.EncodeToString(s.pub) }

// buildRecCert constructs a real-signature attestation cert for
// `applicant`, cosigned by `validators`. The body's IssuedAtNs +
// ExpiresAtNs default to "fresh and valid for 48h" so the cert
// passes capability.VerifyAttestation's freshness check.
func buildRecCert(
	t *testing.T,
	applicant *recSigner,
	validators ...*recSigner,
) *pb.AttestationCert {
	t.Helper()
	body := &pb.AttestationBody{
		ApplicantPubkey:  applicant.hex(),
		IssuedAtNs:       time.Now().UnixNano(),
		ExpiresAtNs:      time.Now().Add(48 * time.Hour).UnixNano(),
		TierGranted:      int32(capability.IssuedTier),
		ChallengeTaskIds: []string{"t1", "t2"},
	}
	bodyBytes, err := proto.MarshalOptions{Deterministic: true}.Marshal(body)
	if err != nil {
		t.Fatalf("marshal body: %v", err)
	}
	cosigs := make([]*pb.CoSignature, 0, len(validators))
	for _, v := range validators {
		cosigs = append(cosigs, &pb.CoSignature{
			ValidatorPubkey: v.hex(),
			Signature:       ed25519.Sign(v.priv, bodyBytes),
			SignedAtNs:      time.Now().UnixNano(),
		})
	}
	return &pb.AttestationCert{Body: body, CoSignatures: cosigs}
}

// recFetcher is a test-only RecursiveCertFetcher backed by an
// in-memory dictionary keyed by pubkey. Tracks call counts so cycle/
// cache tests can assert on fetch frequency.
type recFetcher struct {
	mu    sync.Mutex
	certs map[string]*pb.AttestationCert
	errs  map[string]error
	count atomic.Int32
}

func newRecFetcher() *recFetcher {
	return &recFetcher{
		certs: make(map[string]*pb.AttestationCert),
		errs:  make(map[string]error),
	}
}

func (f *recFetcher) put(pubkey string, cert *pb.AttestationCert) {
	f.mu.Lock()
	f.certs[pubkey] = cert
	f.mu.Unlock()
}

func (f *recFetcher) putErr(pubkey string, err error) {
	f.mu.Lock()
	f.errs[pubkey] = err
	f.mu.Unlock()
}

func (f *recFetcher) fetch(_ context.Context, pubkey string) (*pb.AttestationCert, error) {
	f.count.Add(1)
	f.mu.Lock()
	defer f.mu.Unlock()
	if err, ok := f.errs[pubkey]; ok {
		return nil, err
	}
	return f.certs[pubkey], nil
}

// TestRecursive_BootstrapAcceptedDirectly — the simplest case: the
// cert's cosigners are in the trusted bootstrap set. No fetches.
func TestRecursive_BootstrapAcceptedDirectly(t *testing.T) {
	applicant := newRecSigner(t)
	v1 := newRecSigner(t)
	v2 := newRecSigner(t)

	bootstrap := map[string]struct{}{
		v1.hex(): {},
		v2.hex(): {},
	}
	f := newRecFetcher()
	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)

	cert := buildRecCert(t, applicant, v1, v2)
	n, err := rv.Verify(context.Background(), cert)
	if err != nil {
		t.Fatalf("Verify rejected bootstrap-cosigned cert: %v", err)
	}
	if n != 2 {
		t.Errorf("expected 2 Tier-3 cosigs, got %d", n)
	}
	if got := f.count.Load(); got != 0 {
		t.Errorf("expected 0 fetches (bootstrap-only path), got %d", got)
	}
}

// TestRecursive_OneHopChainTerminatesAtBootstrap — applicant cert is
// cosigned by v1, v2; v1+v2 each have their own cert cosigned by
// bootstrap members. Two levels of recursion; both terminate cleanly.
func TestRecursive_OneHopChainTerminatesAtBootstrap(t *testing.T) {
	applicant := newRecSigner(t)
	v1 := newRecSigner(t)
	v2 := newRecSigner(t)
	bs1 := newRecSigner(t)
	bs2 := newRecSigner(t)

	bootstrap := map[string]struct{}{
		bs1.hex(): {},
		bs2.hex(): {},
	}
	f := newRecFetcher()
	// v1's cert: cosigned by bootstrap.
	f.put(v1.hex(), buildRecCert(t, v1, bs1, bs2))
	// v2's cert: cosigned by bootstrap.
	f.put(v2.hex(), buildRecCert(t, v2, bs1, bs2))

	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)

	cert := buildRecCert(t, applicant, v1, v2)
	n, err := rv.Verify(context.Background(), cert)
	if err != nil {
		t.Fatalf("Verify rejected one-hop chain: %v", err)
	}
	if n != 2 {
		t.Errorf("expected 2 Tier-3 cosigs, got %d", n)
	}
	// Exactly 2 fetches: one for v1's cert, one for v2's. Bootstrap
	// hits don't fetch.
	if got := f.count.Load(); got != 2 {
		t.Errorf("expected 2 fetches (one per non-bootstrap cosig), got %d", got)
	}
}

// TestRecursive_RejectsNonTier3Validator — applicant's cert is
// cosigned by v1 (Tier-3 via bootstrap chain) AND vbad (not Tier-3:
// no cert in DHT). Quorum is 2; only 1 valid → reject.
func TestRecursive_RejectsNonTier3Validator(t *testing.T) {
	applicant := newRecSigner(t)
	v1 := newRecSigner(t)
	vbad := newRecSigner(t)
	bs1 := newRecSigner(t)
	bs2 := newRecSigner(t)

	bootstrap := map[string]struct{}{bs1.hex(): {}, bs2.hex(): {}}
	f := newRecFetcher()
	f.put(v1.hex(), buildRecCert(t, v1, bs1, bs2))
	// vbad: no cert published; FetchCert returns nil.

	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)

	cert := buildRecCert(t, applicant, v1, vbad)
	n, err := rv.Verify(context.Background(), cert)
	if err == nil {
		t.Fatalf("Verify accepted a cert with non-Tier-3 cosigner; want rejection")
	}
	if n != 1 {
		t.Errorf("expected 1 Tier-3-verified cosig, got %d", n)
	}
}

// TestRecursive_CycleRejected — vA's cert is cosigned by vB and
// bootstrap; vB's cert is cosigned by vA and bootstrap. Without
// cycle detection vA would recurse into vB which recurses into vA
// (infinite loop OR mutual-validation acceptance). With cycle
// detection, vA's branch sees vA-already-in-path → reject.
func TestRecursive_CycleRejected(t *testing.T) {
	applicant := newRecSigner(t)
	vA := newRecSigner(t)
	vB := newRecSigner(t)
	bs := newRecSigner(t)
	// We need 2 cosigs minimum per cert. Use bs + vB for vA, and
	// bs + vA for vB. Then top-level cert is cosigned by vA + vB.
	bsAlt := newRecSigner(t)

	bootstrap := map[string]struct{}{bs.hex(): {}, bsAlt.hex(): {}}
	f := newRecFetcher()
	// vA's cert: cosigned by bs (bootstrap) + vB (recursive into vB).
	f.put(vA.hex(), buildRecCert(t, vA, bs, vB))
	// vB's cert: cosigned by bs (bootstrap) + vA (cycle back to vA).
	f.put(vB.hex(), buildRecCert(t, vB, bs, vA))

	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)
	cert := buildRecCert(t, applicant, vA, vB)

	// Cycle detection: when verifying vA, we recurse into vA's cert,
	// which tries to verify vB (depth=1, seen={vA}). vB's cert tries
	// to verify vA — but vA is in `seen`, so it's rejected. vB's
	// cert thus has only 1 Tier-3 cosig (bs) which is below quorum,
	// so vB is rejected. vA's cert now has only 1 Tier-3 cosig (bs),
	// below quorum → vA rejected. Top-level cert thus has 0 Tier-3
	// cosigners → reject.
	//
	// Without cycle detection, the recursion would either loop
	// forever or accept the mutual-attestation farm.
	n, err := rv.Verify(context.Background(), cert)
	if err == nil {
		t.Fatalf("Verify accepted a mutual-attestation cycle; want rejection (got n=%d)", n)
	}
}

// TestRecursive_DepthBound — a chain longer than MaxDepth must
// terminate in rejection rather than burn unbounded fetches.
func TestRecursive_DepthBound(t *testing.T) {
	applicant := newRecSigner(t)
	bs := newRecSigner(t)
	bsAlt := newRecSigner(t)

	// Build a chain: v1 → v2 → v3 → v4 → v5 → v6 → bootstrap.
	// 6 hops needed to reach bootstrap; MaxDepth=3 will reject at v4.
	vs := make([]*recSigner, 6)
	for i := range vs {
		vs[i] = newRecSigner(t)
	}

	bootstrap := map[string]struct{}{bs.hex(): {}, bsAlt.hex(): {}}
	f := newRecFetcher()
	// Each v_i's cert is cosigned by bs (bootstrap) + v_{i+1} (chain).
	// v_last is cosigned by bs (bootstrap) + bs (bootstrap)... no
	// that's a dup. Use bs + bsAlt.
	for i := 0; i < len(vs)-1; i++ {
		f.put(vs[i].hex(), buildRecCert(t, vs[i], bs, vs[i+1]))
	}
	f.put(vs[len(vs)-1].hex(), buildRecCert(t, vs[len(vs)-1], bs, bsAlt))

	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)
	rv.MaxDepth = 3

	// Top-level cert cosigned by v0 + bsAlt. v0 chain is 6 deep;
	// MaxDepth=3 means we accept v0 only if its chain reaches
	// bootstrap within 3 fetches. v0 → v1 → v2 → v3 (depth=3, no
	// more recursion). v3's cosigners: bs (bootstrap) + v4 (depth
	// exhausted → reject v4). So v3 has 1 Tier-3 cosig (below
	// quorum), v3 rejected, propagating up.
	cert := buildRecCert(t, applicant, vs[0], bsAlt)

	_, err := rv.Verify(context.Background(), cert)
	if err == nil {
		t.Errorf("Verify accepted a chain longer than MaxDepth; want rejection")
	}

	// Sanity: with MaxDepth=10 the same chain should verify.
	rv.MaxDepth = 10
	// Reset the cache so the depth-3-rejected branches re-evaluate.
	rv2 := capability.NewRecursiveVerifier(bootstrap, f.fetch)
	rv2.MaxDepth = 10
	if _, err := rv2.Verify(context.Background(), cert); err != nil {
		t.Errorf("Verify rejected a chain within MaxDepth=10: %v", err)
	}
}

// TestRecursive_EmptyBootstrapRejected — a verifier with no
// trusted bootstrap can't terminate recursion → must reject all
// certs (no base case).
func TestRecursive_EmptyBootstrapRejected(t *testing.T) {
	applicant := newRecSigner(t)
	v1 := newRecSigner(t)
	v2 := newRecSigner(t)

	f := newRecFetcher()
	rv := capability.NewRecursiveVerifier(map[string]struct{}{}, f.fetch)

	cert := buildRecCert(t, applicant, v1, v2)
	_, err := rv.Verify(context.Background(), cert)
	if err == nil {
		t.Errorf("Verify accepted cert with empty bootstrap; want rejection")
	}
}

// TestRecursive_WrongPubkeyOnFetchedCert — a malicious peer could
// substitute someone else's Tier-3 cert in response to a fetch for
// a non-Tier-3 pubkey. Verifier must reject if the fetched cert's
// ApplicantPubkey doesn't match the queried pubkey.
func TestRecursive_WrongPubkeyOnFetchedCert(t *testing.T) {
	applicant := newRecSigner(t)
	v1 := newRecSigner(t)
	v2 := newRecSigner(t)
	bs := newRecSigner(t)
	bsAlt := newRecSigner(t)
	imposter := newRecSigner(t)

	bootstrap := map[string]struct{}{bs.hex(): {}, bsAlt.hex(): {}}
	f := newRecFetcher()
	// Fetch for v1 returns a cert for `imposter`, not v1. Verifier
	// must reject this substitution.
	f.put(v1.hex(), buildRecCert(t, imposter, bs, bsAlt))
	f.put(v2.hex(), buildRecCert(t, v2, bs, bsAlt))

	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)
	cert := buildRecCert(t, applicant, v1, v2)
	n, err := rv.Verify(context.Background(), cert)
	if err == nil {
		t.Errorf("Verify accepted a substitution attack; want rejection (got n=%d)", n)
	}
}

// TestRecursive_PositiveCacheReuse — within one verifier instance,
// a non-bootstrap validator is fetched once even if it appears in
// multiple cosig walks. Cache hit on second appearance.
func TestRecursive_PositiveCacheReuse(t *testing.T) {
	applicant1 := newRecSigner(t)
	applicant2 := newRecSigner(t)
	v1 := newRecSigner(t)
	bs := newRecSigner(t)
	bsAlt := newRecSigner(t)

	bootstrap := map[string]struct{}{bs.hex(): {}, bsAlt.hex(): {}}
	f := newRecFetcher()
	f.put(v1.hex(), buildRecCert(t, v1, bs, bsAlt))

	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)

	// Cert 1 cosigned by v1 + bs. Cert 2 cosigned by v1 + bsAlt.
	cert1 := buildRecCert(t, applicant1, v1, bs)
	cert2 := buildRecCert(t, applicant2, v1, bsAlt)

	if _, err := rv.Verify(context.Background(), cert1); err != nil {
		t.Fatalf("Verify cert1: %v", err)
	}
	beforeCount := f.count.Load()
	if _, err := rv.Verify(context.Background(), cert2); err != nil {
		t.Fatalf("Verify cert2: %v", err)
	}
	afterCount := f.count.Load()
	if afterCount > beforeCount {
		t.Errorf("expected cache hit on v1 (no second fetch); got %d additional fetches",
			afterCount-beforeCount)
	}
	if rv.CacheLen() != 1 {
		t.Errorf("expected cache size 1 (v1 only), got %d", rv.CacheLen())
	}
}

// TestRecursive_TransientFetchErrorNotCached — fetch errors must
// NOT be cached as negatives, so a flaky DHT doesn't sticky-hide an
// honest validator.
func TestRecursive_TransientFetchErrorNotCached(t *testing.T) {
	applicant := newRecSigner(t)
	v1 := newRecSigner(t)
	v2 := newRecSigner(t)
	bs := newRecSigner(t)
	bsAlt := newRecSigner(t)

	bootstrap := map[string]struct{}{bs.hex(): {}, bsAlt.hex(): {}}
	f := newRecFetcher()
	f.putErr(v1.hex(), errors.New("simulated DHT error"))
	f.put(v2.hex(), buildRecCert(t, v2, bs, bsAlt))

	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)
	cert := buildRecCert(t, applicant, v1, v2)

	// First verify: v1 fetch errors → 1 valid Tier-3 (v2) → reject.
	if _, err := rv.Verify(context.Background(), cert); err == nil {
		t.Fatalf("Verify accepted cert with transient v1 error; want rejection")
	}
	firstCount := f.count.Load()

	// Second verify: v1 should be re-fetched (transient not cached).
	if _, err := rv.Verify(context.Background(), cert); err == nil {
		t.Fatalf("Verify accepted on second try; want rejection")
	}
	secondCount := f.count.Load()
	if secondCount <= firstCount {
		t.Errorf("expected v1 to be re-fetched on retry (transient not cached); "+
			"first=%d, second=%d", firstCount, secondCount)
	}
}

// TestRecursive_StandardVerifyAttestationFailuresPropagate — make
// sure the recursive verifier doesn't accept certs that standard
// VerifyAttestation would reject (expired, wrong tier, bad sigs).
func TestRecursive_StandardVerifyAttestationFailuresPropagate(t *testing.T) {
	applicant := newRecSigner(t)
	v1 := newRecSigner(t)
	v2 := newRecSigner(t)
	bootstrap := map[string]struct{}{v1.hex(): {}, v2.hex(): {}}
	f := newRecFetcher()
	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)

	// Expired cert.
	body := &pb.AttestationBody{
		ApplicantPubkey:  applicant.hex(),
		IssuedAtNs:       time.Now().Add(-48 * time.Hour).UnixNano(),
		ExpiresAtNs:      time.Now().Add(-24 * time.Hour).UnixNano(),
		TierGranted:      int32(capability.IssuedTier),
		ChallengeTaskIds: []string{"t1"},
	}
	bodyBytes, _ := proto.MarshalOptions{Deterministic: true}.Marshal(body)
	mkCosig := func(v *recSigner) *pb.CoSignature {
		return &pb.CoSignature{
			ValidatorPubkey: v.hex(),
			Signature:       ed25519.Sign(v.priv, bodyBytes),
			SignedAtNs:      time.Now().UnixNano(),
		}
	}
	expired := &pb.AttestationCert{
		Body:         body,
		CoSignatures: []*pb.CoSignature{mkCosig(v1), mkCosig(v2)},
	}
	if _, err := rv.Verify(context.Background(), expired); err == nil {
		t.Errorf("Verify accepted an expired cert; want rejection")
	}

	// Wrong tier.
	body.IssuedAtNs = time.Now().UnixNano()
	body.ExpiresAtNs = time.Now().Add(24 * time.Hour).UnixNano()
	body.TierGranted = 99
	bodyBytes, _ = proto.MarshalOptions{Deterministic: true}.Marshal(body)
	wrongTier := &pb.AttestationCert{
		Body: body,
		CoSignatures: []*pb.CoSignature{
			{ValidatorPubkey: v1.hex(), Signature: ed25519.Sign(v1.priv, bodyBytes), SignedAtNs: time.Now().UnixNano()},
			{ValidatorPubkey: v2.hex(), Signature: ed25519.Sign(v2.priv, bodyBytes), SignedAtNs: time.Now().UnixNano()},
		},
	}
	if _, err := rv.Verify(context.Background(), wrongTier); err == nil {
		t.Errorf("Verify accepted a wrong-tier cert; want rejection")
	}
}

// TestRecursive_NilCertRejected — defensive.
func TestRecursive_NilCertRejected(t *testing.T) {
	bs := newRecSigner(t)
	bsAlt := newRecSigner(t)
	bootstrap := map[string]struct{}{bs.hex(): {}, bsAlt.hex(): {}}
	f := newRecFetcher()
	rv := capability.NewRecursiveVerifier(bootstrap, f.fetch)
	if _, err := rv.Verify(context.Background(), nil); err == nil {
		t.Errorf("Verify accepted nil cert")
	}
}
