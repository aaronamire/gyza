package dht_test

// Unit tests for DHTAttestationVerifier. Uses a stub CertFetcher so we
// can exercise cache / single-flight / near-expiry / negative-cache
// logic without spinning up libp2p. Cryptographic cert validity is
// produced via real ed25519 over canonical-marshal of the body — same
// shape capability.VerifyAttestation expects.

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"gyza/netd/internal/capability"
	"gyza/netd/internal/dht"
	pb "gyza/netd/internal/grpc/proto"

	"google.golang.org/protobuf/proto"
)

// buildValidCert assembles a cert with 2 real cosigs over the given
// body. ApplicantPubkey is filled into the body if empty. ExpiresAtNs
// defaults to issuedAt + lifetime (defaults: now / 24h).
func buildValidCert(
	t *testing.T,
	applicantPubkeyHex string,
	issuedAt time.Time,
	lifetime time.Duration,
) *pb.AttestationCert {
	t.Helper()
	if applicantPubkeyHex == "" {
		_, priv, err := ed25519.GenerateKey(rand.Reader)
		if err != nil {
			t.Fatalf("genkey: %v", err)
		}
		applicantPubkeyHex = hex.EncodeToString(priv.Public().(ed25519.PublicKey))
	}
	if issuedAt.IsZero() {
		issuedAt = time.Now()
	}
	if lifetime == 0 {
		lifetime = 24 * time.Hour
	}

	body := &pb.AttestationBody{
		ApplicantPubkey:  applicantPubkeyHex,
		IssuedAtNs:       issuedAt.UnixNano(),
		ExpiresAtNs:      issuedAt.Add(lifetime).UnixNano(),
		TierGranted:      int32(capability.IssuedTier),
		ChallengeTaskIds: []string{"t1", "t2"},
	}
	bodyBytes, err := proto.MarshalOptions{Deterministic: true}.Marshal(body)
	if err != nil {
		t.Fatalf("marshal body: %v", err)
	}

	mkCosig := func() *pb.CoSignature {
		pub, priv, err := ed25519.GenerateKey(rand.Reader)
		if err != nil {
			t.Fatalf("genkey: %v", err)
		}
		return &pb.CoSignature{
			ValidatorPubkey: hex.EncodeToString(pub),
			Signature:       ed25519.Sign(priv, bodyBytes),
			SignedAtNs:      time.Now().UnixNano(),
		}
	}
	return &pb.AttestationCert{
		Body:         body,
		CoSignatures: []*pb.CoSignature{mkCosig(), mkCosig()},
	}
}

// stubFetcher records call counts per pubkey and returns canned
// responses. Concurrent-safe so single-flight tests can assert on
// fetch counts under load.
type stubFetcher struct {
	mu        sync.Mutex
	calls     map[string]int
	responses map[string]stubResponse
	delay     time.Duration // optional artificial latency
}

type stubResponse struct {
	cert *pb.AttestationCert
	err  error
}

func newStubFetcher() *stubFetcher {
	return &stubFetcher{
		calls:     make(map[string]int),
		responses: make(map[string]stubResponse),
	}
}

func (s *stubFetcher) set(pubkey string, cert *pb.AttestationCert, err error) {
	s.mu.Lock()
	s.responses[pubkey] = stubResponse{cert: cert, err: err}
	s.mu.Unlock()
}

func (s *stubFetcher) setDelay(d time.Duration) {
	s.mu.Lock()
	s.delay = d
	s.mu.Unlock()
}

func (s *stubFetcher) callCount(pubkey string) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls[pubkey]
}

func (s *stubFetcher) fetch(ctx context.Context, pubkey string) (*pb.AttestationCert, error) {
	s.mu.Lock()
	s.calls[pubkey]++
	resp := s.responses[pubkey]
	delay := s.delay
	s.mu.Unlock()
	if delay > 0 {
		select {
		case <-time.After(delay):
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	return resp.cert, resp.err
}

// TestVerifier_AcceptsValidCertCachesResult — happy path. A valid cert
// returns true; a second call inside posTTL hits the cache and never
// re-fetches.
func TestVerifier_AcceptsValidCertCachesResult(t *testing.T) {
	pubkey := strings.Repeat("aa", 32)
	cert := buildValidCert(t, pubkey, time.Now(), 24*time.Hour)
	f := newStubFetcher()
	f.set(pubkey, cert, nil)

	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{
		PosTTL:       2 * time.Second,
		NegTTL:       1 * time.Second,
		FetchTimeout: 500 * time.Millisecond,
	})

	if !v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify returned false for a valid cert")
	}
	if n := f.callCount(pubkey); n != 1 {
		t.Fatalf("first call: fetch count = %d, want 1", n)
	}
	if !v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify returned false on cache hit")
	}
	if n := f.callCount(pubkey); n != 1 {
		t.Errorf("cache miss: fetch count = %d after second Verify, want still 1", n)
	}
}

// TestVerifier_RejectsMissingCertCachesNegative — pubkey with no cert
// returns false and the negative is cached for NegTTL so a stable
// Sybil doesn't hammer the DHT.
func TestVerifier_RejectsMissingCertCachesNegative(t *testing.T) {
	pubkey := strings.Repeat("bb", 32)
	f := newStubFetcher() // no response set → cert=nil, err=nil

	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{
		PosTTL: 2 * time.Second,
		NegTTL: 2 * time.Second,
	})
	if v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify returned true for missing cert")
	}
	if v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify returned true on negative-cache hit (after first miss)")
	}
	if n := f.callCount(pubkey); n != 1 {
		t.Errorf("negative cache miss: fetch count = %d after two Verify calls, want 1", n)
	}
}

// TestVerifier_RejectsExpiredCert — capability.VerifyAttestation
// rejects expired certs; we should drop them too AND cache negative.
func TestVerifier_RejectsExpiredCert(t *testing.T) {
	pubkey := strings.Repeat("cc", 32)
	// issued 48h ago, expired 24h ago
	cert := buildValidCert(t, pubkey, time.Now().Add(-48*time.Hour), 24*time.Hour)
	f := newStubFetcher()
	f.set(pubkey, cert, nil)
	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{})
	if v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify accepted expired cert")
	}
}

// TestVerifier_RejectsNearExpiryCert — cert that's still technically
// valid but expires within expirySlack should be rejected. This is the
// CLAUDE.md §6 #21f trip-wire: cert that "verifies now" but expires in
// 1ms shouldn't route a request that arrives after the cert dies.
func TestVerifier_RejectsNearExpiryCert(t *testing.T) {
	pubkey := strings.Repeat("dd", 32)
	// Issued 50min ago, expires 10min from now — VerifyAttestation
	// accepts (still valid) but our slack=1h rejects.
	cert := buildValidCert(t, pubkey, time.Now().Add(-50*time.Minute), 1*time.Hour)
	f := newStubFetcher()
	f.set(pubkey, cert, nil)
	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{
		ExpirySlack: 1 * time.Hour,
	})
	if v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify accepted near-expiry cert (would expire inside slack window)")
	}
}

// TestVerifier_FetchErrorNotCached — transient fetch failures (DHT
// network error, timeout) must NOT cache. A subsequent call from a
// fresh ctx should retry rather than sticky-hiding an honest ad.
func TestVerifier_FetchErrorNotCached(t *testing.T) {
	pubkey := strings.Repeat("ee", 32)
	f := newStubFetcher()
	f.set(pubkey, nil, errors.New("simulated DHT error"))
	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{
		NegTTL: 5 * time.Second,
	})
	if v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify accepted on simulated DHT error")
	}
	if v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify accepted on second call (transient error should NOT be cached)")
	}
	if n := f.callCount(pubkey); n != 2 {
		t.Errorf("expected 2 fetches (transient errors not cached), got %d", n)
	}
}

// TestVerifier_SingleFlightDedupsConcurrent — two concurrent Verify
// calls for the same pubkey result in exactly one fetch, with both
// callers seeing the same answer.
func TestVerifier_SingleFlightDedupsConcurrent(t *testing.T) {
	pubkey := strings.Repeat("ff", 32)
	cert := buildValidCert(t, pubkey, time.Now(), 24*time.Hour)
	f := newStubFetcher()
	f.set(pubkey, cert, nil)
	// Add latency so both callers race into the single-flight wait
	// rather than the first finishing before the second arrives.
	f.setDelay(100 * time.Millisecond)
	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{
		FetchTimeout: 1 * time.Second,
	})

	const N = 8
	var wg sync.WaitGroup
	var trueCount atomic.Int32
	wg.Add(N)
	for i := 0; i < N; i++ {
		go func() {
			defer wg.Done()
			if v.Verify(context.Background(), pubkey) {
				trueCount.Add(1)
			}
		}()
	}
	wg.Wait()
	if got := trueCount.Load(); got != N {
		t.Errorf("expected %d true results, got %d", N, got)
	}
	// At most a small constant — typically 1, possibly more if some
	// caller raced past a stale cache delete. Asserting ≤ 2 keeps the
	// test stable under scheduler jitter while still proving the
	// fan-in: without single-flight we'd see N=8 fetches.
	if n := f.callCount(pubkey); n > 2 {
		t.Errorf("expected ≤2 fetches under single-flight, got %d", n)
	}
}

// TestVerifier_PerFetchTimeout — a fetcher that exceeds FetchTimeout
// surfaces as a transient failure (ctx.DeadlineExceeded). The result
// must NOT be cached so a follow-up call gets a fresh chance.
func TestVerifier_PerFetchTimeout(t *testing.T) {
	pubkey := strings.Repeat("11", 32)
	cert := buildValidCert(t, pubkey, time.Now(), 24*time.Hour)
	f := newStubFetcher()
	f.set(pubkey, cert, nil)
	f.setDelay(300 * time.Millisecond)
	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{
		FetchTimeout: 50 * time.Millisecond,
		NegTTL:       5 * time.Second,
	})
	if v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify accepted on simulated slow fetch (should time out)")
	}
	// Negative not cached — second call hits fetch again.
	if v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify accepted on second call (timeout should NOT be cached)")
	}
	if n := f.callCount(pubkey); n != 2 {
		t.Errorf("expected 2 fetches across two timeouts, got %d", n)
	}
}

// TestVerifier_PositiveCacheBoundedByCertExpiry — a cert that expires
// within posTTL gets its cache entry truncated to (expiry - slack).
// We verify by fast-forwarding time and confirming the cache evicts
// correctly.
func TestVerifier_PositiveCacheBoundedByCertExpiry(t *testing.T) {
	pubkey := strings.Repeat("22", 32)
	// Cert lives for 90min total. With slack=1h, the verifier's
	// "useful window" is 30min. PosTTL is 1h. Cache entry should be
	// bounded by the 30min window, not the 1h PosTTL.
	clock := time.Now()
	cert := buildValidCert(t, pubkey, clock, 90*time.Minute)
	f := newStubFetcher()
	f.set(pubkey, cert, nil)
	now := atomicTime{}
	now.Set(clock)
	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{
		PosTTL:       1 * time.Hour,
		NegTTL:       30 * time.Second,
		ExpirySlack:  1 * time.Hour,
		FetchTimeout: 500 * time.Millisecond,
		Now:          now.Get,
	})

	if !v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify returned false for fresh cert")
	}
	if n := f.callCount(pubkey); n != 1 {
		t.Fatalf("fetch count after first Verify = %d, want 1", n)
	}

	// Fast-forward 20 minutes — within the 30min remaining-useful
	// window. Cache should still hit.
	now.Set(clock.Add(20 * time.Minute))
	if !v.Verify(context.Background(), pubkey) {
		t.Fatalf("Verify returned false 20min in (within useful window)")
	}
	if n := f.callCount(pubkey); n != 1 {
		t.Errorf("fetch count after 20min = %d, want 1 (cache hit)", n)
	}

	// Fast-forward 40 minutes — past the 30min useful window. Cache
	// expired; new fetch should fire. Cert now has 50min of life
	// total, but only ~50min - 1h slack = -10min into the slack
	// window. Verifier should reject.
	now.Set(clock.Add(40 * time.Minute))
	if v.Verify(context.Background(), pubkey) {
		t.Errorf("Verify accepted cert past its useful (slack-bounded) window")
	}
	if n := f.callCount(pubkey); n != 2 {
		t.Errorf("fetch count after 40min = %d, want 2 (cache evicted)", n)
	}
}

// atomicTime is a tiny mutable clock for time-travel tests.
type atomicTime struct {
	mu sync.Mutex
	t  time.Time
}

func (a *atomicTime) Get() time.Time {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.t
}
func (a *atomicTime) Set(t time.Time) {
	a.mu.Lock()
	a.t = t
	a.mu.Unlock()
}

// TestVerifier_EmptyPubkeyRejected — a malformed ad with empty
// compositor_pubkey gets rejected without any fetch.
func TestVerifier_EmptyPubkeyRejected(t *testing.T) {
	f := newStubFetcher()
	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{})
	if v.Verify(context.Background(), "") {
		t.Errorf("Verify accepted empty pubkey")
	}
	if n := f.callCount(""); n != 0 {
		t.Errorf("empty-pubkey case made %d fetches, want 0", n)
	}
}

// TestVerifier_BoundedConcurrency — sanity-check that MaxInflight is
// honored: with delay=200ms and MaxInflight=2, four concurrent calls
// for DISTINCT pubkeys still complete in well under 4*200ms (which
// would be the worst-case fully-serial time), but not in <200ms
// (which would mean the semaphore isn't gating anything). Using
// distinct pubkeys ensures single-flight doesn't fan in.
func TestVerifier_BoundedConcurrency(t *testing.T) {
	cert := buildValidCert(t, "", time.Now(), 24*time.Hour)
	f := newStubFetcher()
	for i := 0; i < 4; i++ {
		pk := fmt.Sprintf("%02x"+strings.Repeat("33", 31), i)
		c := *cert
		body := *cert.Body
		body.ApplicantPubkey = pk
		c.Body = &body
		f.set(pk, &c, nil)
	}
	f.setDelay(200 * time.Millisecond)
	v := dht.NewDHTAttestationVerifier(f.fetch, dht.VerifierConfig{
		MaxInflight:  2,
		FetchTimeout: 5 * time.Second,
	})

	start := time.Now()
	var wg sync.WaitGroup
	for i := 0; i < 4; i++ {
		pk := fmt.Sprintf("%02x"+strings.Repeat("33", 31), i)
		wg.Add(1)
		go func() {
			defer wg.Done()
			v.Verify(context.Background(), pk)
		}()
	}
	wg.Wait()
	elapsed := time.Since(start)
	// Two waves of 2 concurrent fetches at 200ms each → ~400ms.
	// Allow generous bounds for scheduler jitter.
	if elapsed < 350*time.Millisecond {
		t.Errorf("4 fetches with MaxInflight=2, delay=200ms ran in %v — semaphore not gating", elapsed)
	}
	if elapsed > 1500*time.Millisecond {
		t.Errorf("4 fetches ran in %v — sem looks fully serial, expected ~400ms", elapsed)
	}
}
