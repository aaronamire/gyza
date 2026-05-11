package dht

// Verify-on-fetch for AgentAdvertisement.attestation_tier.
//
// AgentAdvertisement carries a self-reported attestation_tier integer.
// Without an extra check, any node can advertise tier=3 and a query
// with min_tier=3 will return the lie. The point of Tier-3 (CLAUDE.md
// §6 #21) is sybil-resistance: a node is Tier-3 iff at least
// MinCoSignatures distinct Tier-3 validators have signed an
// AttestationCert about it, and that cert is fetchable from the DHT
// at /gyza/attestations/{compositor_pubkey}. This file turns the
// self-reported field into a verified one at FindAgents time.
//
// Performance constraints — FindAgents is on the hot path. So:
//
//   * positive cache (5 min default) per compositor_pubkey amortizes
//     repeated queries that hit the same agent;
//   * negative cache (30 s default) bounds the per-second DHT load
//     that a stable Sybil-without-cert imposes;
//   * single-flight per pubkey: two concurrent FindAgents queries for
//     the same Tier-3 compositor share one DHT fetch rather than fan
//     out twice;
//   * global semaphore (16 in-flight default): the verifier never
//     allows more than N concurrent fetches, so a worst-case bucket
//     full of tier-3 ads can't pin the daemon's IO budget;
//   * per-fetch timeout (250 ms default): a slow validator-side DHT
//     dial doesn't stall the consumer's routing decision. Beyond
//     the timeout, the ad is treated as unverified for this call but
//     the failure is NOT cached (transient — let the next caller
//     retry).
//
// Freshness — VerifyAttestation already rejects certs where
// now >= expires_at_ns. We tighten that to "now >= expires_at_ns -
// expirySlack" (1h default) so a cert that "verified now" is still
// a useful answer 5 minutes from now. Without the slack, an ad
// fetched 1 ms before its cert expires would route a request that
// arrives after the cert is dead.

import (
	"context"
	"sync"
	"time"

	pb "gyza/netd/internal/grpc/proto"

	"gyza/netd/internal/capability"
)

// AttestationVerifier is the contract FindAgents calls when minTier
// >= IssuedTier. Implementations decide what fetched-and-valid means;
// the default does DHT-fetch + capability.VerifyAttestation +
// freshness-with-slack. Tests can substitute a stub (e.g. always-true)
// via GyzaDHT.SetAttestationVerifier.
type AttestationVerifier interface {
	Verify(ctx context.Context, compositorPubkey string) bool
}

// CertFetcher is the dependency-injected fetch shape. Matches
// GyzaDHT.FetchAttestation's signature so wiring is trivial. Pulled out
// so tests can stub fetches without spinning up real libp2p.
type CertFetcher func(ctx context.Context, applicantPubkeyHex string) (*pb.AttestationCert, error)

// Defaults for the verifier knobs. Exposed as constants for tests that
// want to assert against them rather than hardcoding magic numbers.
const (
	DefaultVerifierPosTTL       = 5 * time.Minute
	DefaultVerifierNegTTL       = 30 * time.Second
	DefaultVerifierFetchTimeout = 250 * time.Millisecond
	DefaultVerifierExpirySlack  = 1 * time.Hour
	DefaultVerifierMaxInflight  = 16
)

// VerifierConfig tunes the defaults. Zero values fall back to the
// DefaultVerifier* constants — callers only set what they want to
// override.
type VerifierConfig struct {
	PosTTL       time.Duration
	NegTTL       time.Duration
	FetchTimeout time.Duration
	ExpirySlack  time.Duration
	MaxInflight  int
	// Now overrides time.Now for tests that need to fast-forward
	// without monkey-patching the global clock. Nil → time.Now.
	Now func() time.Time
}

// NewDHTAttestationVerifier constructs the default DHT-backed verifier.
// fetch is typically GyzaDHT.FetchAttestation; cfg's zero fields fall
// back to package defaults.
func NewDHTAttestationVerifier(fetch CertFetcher, cfg VerifierConfig) *DHTAttestationVerifier {
	if cfg.PosTTL <= 0 {
		cfg.PosTTL = DefaultVerifierPosTTL
	}
	if cfg.NegTTL <= 0 {
		cfg.NegTTL = DefaultVerifierNegTTL
	}
	if cfg.FetchTimeout <= 0 {
		cfg.FetchTimeout = DefaultVerifierFetchTimeout
	}
	if cfg.ExpirySlack <= 0 {
		cfg.ExpirySlack = DefaultVerifierExpirySlack
	}
	if cfg.MaxInflight <= 0 {
		cfg.MaxInflight = DefaultVerifierMaxInflight
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}
	return &DHTAttestationVerifier{
		fetch:        fetch,
		posTTL:       cfg.PosTTL,
		negTTL:       cfg.NegTTL,
		fetchTimeout: cfg.FetchTimeout,
		expirySlack:  cfg.ExpirySlack,
		now:          cfg.Now,
		sem:          make(chan struct{}, cfg.MaxInflight),
		cache:        make(map[string]verifierEntry),
		inflight:     make(map[string]*inflightCall),
	}
}

type verifierEntry struct {
	valid     bool
	expiresAt time.Time // when this cache entry expires (NOT cert.expires_at_ns)
}

// inflightCall is the single-flight handoff. Concurrent callers for
// the same pubkey wait on done and read the cached result afterward.
type inflightCall struct {
	done chan struct{}
}

// DHTAttestationVerifier is the production implementation. Exported so
// callers wiring custom config (e.g., longer caching in load tests)
// can build it directly; the daemon constructs the default via
// GyzaDHT's internal wiring.
type DHTAttestationVerifier struct {
	fetch        CertFetcher
	posTTL       time.Duration
	negTTL       time.Duration
	fetchTimeout time.Duration
	expirySlack  time.Duration
	now          func() time.Time

	// Bounded concurrency. A nil-bodied channel send blocks until a
	// slot is released. If the caller's ctx is canceled while waiting,
	// Verify returns false WITHOUT caching — the next call retries.
	sem chan struct{}

	mu       sync.Mutex
	cache    map[string]verifierEntry
	inflight map[string]*inflightCall
}

// Verify is the contract method. Returns true iff:
//   - cache has a valid entry that hasn't expired, OR
//   - a fetch within fetchTimeout returned a cert that passes
//     capability.VerifyAttestation AND has expires_at_ns - expirySlack
//     > now.
//
// Returns false on missing cert, invalid cert, near-expiry cert, fetch
// timeout, fetch error, or semaphore-exhausted ctx cancel. The first
// three are cached as negatives; the latter three are NOT cached so a
// transient failure doesn't sticky-hide an honest ad.
func (v *DHTAttestationVerifier) Verify(ctx context.Context, pubkey string) bool {
	if pubkey == "" {
		return false
	}

	// Cache check first — common case after warm-up. We hold the lock
	// briefly to read+evict the entry; the actual fetch happens
	// outside the lock so a slow DHT call can't block other callers.
	now := v.now()
	v.mu.Lock()
	if e, ok := v.cache[pubkey]; ok {
		if now.Before(e.expiresAt) {
			v.mu.Unlock()
			return e.valid
		}
		delete(v.cache, pubkey)
	}
	// Single-flight: if another goroutine is fetching this pubkey,
	// wait on its completion channel and re-read the cache.
	if call, ok := v.inflight[pubkey]; ok {
		v.mu.Unlock()
		select {
		case <-call.done:
		case <-ctx.Done():
			return false
		}
		// The fetcher populated the cache (positive or negative);
		// take a fresh snapshot.
		v.mu.Lock()
		e, ok := v.cache[pubkey]
		v.mu.Unlock()
		if !ok {
			// Fetcher hit a transient error and didn't cache.
			// Don't fan out a second fetch from this caller — the
			// next routing call will retry on a fresh ctx.
			return false
		}
		return e.valid
	}
	// We're the fetcher. Register in-flight before unlocking so
	// concurrent callers from this point on join our wait.
	call := &inflightCall{done: make(chan struct{})}
	v.inflight[pubkey] = call
	v.mu.Unlock()

	// Always tear down the in-flight registration so subsequent
	// callers go through fresh.
	defer func() {
		v.mu.Lock()
		delete(v.inflight, pubkey)
		v.mu.Unlock()
		close(call.done)
	}()

	// Bounded concurrency. The send blocks if the semaphore is full;
	// a canceled ctx aborts the wait. We hold the slot for the WHOLE
	// fetch (sem release happens after FetchAttestation returns).
	select {
	case v.sem <- struct{}{}:
		defer func() { <-v.sem }()
	case <-ctx.Done():
		return false
	}

	// Per-fetch deadline. Capped at the smaller of caller-ctx and
	// fetchTimeout. A short loopback DHT fetch takes ~10–100ms; over
	// the internet it can run to 500ms. 250ms is the routing-budget
	// sweet spot for the LAN/loopback case.
	fctx, cancel := context.WithTimeout(ctx, v.fetchTimeout)
	defer cancel()

	cert, err := v.fetch(fctx, pubkey)
	if err != nil {
		// Transient — don't cache. Next caller retries on a fresh ctx.
		return false
	}
	if cert == nil || cert.Body == nil {
		// Definitive: no cert exists for this compositor. Cache
		// negative for negTTL so a stable Sybil doesn't hammer DHT.
		v.cacheSet(pubkey, false, v.negTTL)
		return false
	}

	// Cryptographic verification. capability.VerifyAttestation is a
	// pure function; passing v.now lets tests fast-forward freshness.
	if _, err := capability.VerifyAttestation(cert, v.now); err != nil {
		v.cacheSet(pubkey, false, v.negTTL)
		return false
	}

	// Near-expiry check. CLAUDE.md §6 #21f trip-wire: a cert that
	// verifies "now" but expires in 1ms shouldn't be trusted for
	// the routing horizon. Slack window says: cert must be valid
	// for at least expirySlack into the future.
	deadline := time.Unix(0, cert.Body.ExpiresAtNs)
	if !now.Add(v.expirySlack).Before(deadline) {
		v.cacheSet(pubkey, false, v.negTTL)
		return false
	}

	// Bound positive cache by both posTTL and the cert's own
	// remaining lifetime minus slack — so a cert that'd expire
	// within posTTL is cached only until expires_at - slack.
	posTTL := v.posTTL
	remaining := deadline.Sub(now) - v.expirySlack
	if remaining < posTTL {
		posTTL = remaining
	}
	v.cacheSet(pubkey, true, posTTL)
	return true
}

func (v *DHTAttestationVerifier) cacheSet(pubkey string, valid bool, ttl time.Duration) {
	if ttl <= 0 {
		return
	}
	v.mu.Lock()
	v.cache[pubkey] = verifierEntry{valid: valid, expiresAt: v.now().Add(ttl)}
	v.mu.Unlock()
}

// cacheLen is for tests that want to assert on cache size without
// touching the unexported field.
func (v *DHTAttestationVerifier) cacheLen() int {
	v.mu.Lock()
	defer v.mu.Unlock()
	return len(v.cache)
}
