package dht_test

// Two-host DHT integration test. Spins up two real libp2p hosts on
// loopback, connects them, runs a GyzaDHT on each, and verifies that
// an advertisement published by host A is discoverable by host B.
//
// Why a separate _test package: keeps the libp2p mocknet/swarm
// dependencies out of the production package's import surface, and
// lets us exercise GyzaDHT through its public API.

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"fmt"
	"strings"
	"testing"
	"time"

	libp2p "github.com/libp2p/go-libp2p"
	kaddht "github.com/libp2p/go-libp2p-kad-dht"
	"github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	libp2pquic "github.com/libp2p/go-libp2p/p2p/transport/quic"

	"gyza/netd/internal/dht"
	pb "gyza/netd/internal/grpc/proto"
)

// buildHost spins up a libp2p host on a random loopback QUIC port with
// a fresh Ed25519 keypair. Returns host plus a teardown.
func buildHost(t *testing.T) (host.Host, func()) {
	t.Helper()
	priv, _, err := crypto.GenerateEd25519Key(rand.Reader)
	if err != nil {
		t.Fatalf("genkey: %v", err)
	}
	h, err := libp2p.New(
		libp2p.Identity(priv),
		libp2p.ListenAddrStrings("/ip4/127.0.0.1/udp/0/quic-v1"),
		libp2p.Transport(libp2pquic.NewTransport),
	)
	if err != nil {
		t.Fatalf("libp2p.New: %v", err)
	}
	return h, func() { _ = h.Close() }
}

// connect joins two hosts so they can route DHT queries through each other.
func connect(t *testing.T, ctx context.Context, a, b host.Host) {
	t.Helper()
	bInfo := peer.AddrInfo{ID: b.ID(), Addrs: b.Addrs()}
	if err := a.Connect(ctx, bInfo); err != nil {
		t.Fatalf("connect %s -> %s: %v", a.ID(), b.ID(), err)
	}
}

// fakeEmbedding produces a unit-norm float32[384] biased toward a
// caller-provided seed direction. Lets the test build advertisements
// with predictable LSH bucketing without needing real text embeddings.
func fakeEmbedding(seed int64) []float32 {
	v := make([]float32, dht.EmbeddingDim)
	x := uint64(seed) | 1
	var sumSq float64
	for i := range v {
		// xorshift64 — deterministic and good enough.
		x ^= x << 13
		x ^= x >> 7
		x ^= x << 17
		// Map the low 32 bits to [-1, 1].
		f := float32(int32(x))/float32(1<<31) - 0.5
		v[i] = f
		sumSq += float64(f) * float64(f)
	}
	// L2-normalize so two embeddings produced from the same seed
	// land at the same bucket regardless of magnitude.
	if sumSq > 0 {
		n := float32(1.0 / sqrt(sumSq))
		for i := range v {
			v[i] *= n
		}
	}
	return v
}

func sqrt(x float64) float64 {
	z := x
	for i := 0; i < 16; i++ {
		z = 0.5 * (z + x/z)
	}
	return z
}

func makeAd(t *testing.T, agentSeed int64, tier int32, reputation float64) *pb.AgentAdvertisement {
	t.Helper()
	pub, _, _ := ed25519.GenerateKey(nil)
	emb := fakeEmbedding(agentSeed)
	return &pb.AgentAdvertisement{
		AgentPubkey:             fmt.Sprintf("%x", pub),
		CompositorPubkey:        fmt.Sprintf("%x", pub),
		CapabilityManifestHash:  "fake-manifest-hash",
		SpecializationEmbedding: dht.EncodeF32LE(emb),
		AttestationTier:         tier,
		ReputationScore:         reputation,
		ComputeCreditBalance:    0,
		LastSeen:                time.Now().UnixNano(),
		TtlSeconds:              3600,
		GyzaVersion:             "test",
	}
}

// waitForRoutingTable polls until the DHT routing table on `a` knows
// about `bID` (or timeout). Bootstrap and Connect are async — Provide
// won't see the partner peer immediately.
func waitForRoutingTable(t *testing.T, ctx context.Context, gd *dht.GyzaDHT, expectedSize int, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if gd.RoutingTableSize() >= expectedSize {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("routing table did not reach size %d within %v (got %d)",
		expectedSize, timeout, gd.RoutingTableSize())
}

// TestPublishAndFindLocal — single-host smoke test. Local cache is
// populated by Publish, FindAgents returns it without any network.
// Catches regressions in the LSH path / cosine ordering / dedupe
// before the harder two-host test catches DHT routing.
func TestPublishAndFindLocal(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	h, closeH := buildHost(t)
	defer closeH()

	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}
	defer gd.Close()

	ad := makeAd(t, 12345, 1, 0.5)
	if _, err := gd.PublishAgent(ctx, ad); err != nil {
		t.Fatalf("publish: %v", err)
	}

	queryEmb := fakeEmbedding(12345) // same seed → same bucket
	results, err := gd.FindAgents(ctx, queryEmb, 5, 0, 0)
	if err != nil {
		t.Fatalf("find: %v", err)
	}
	if len(results) == 0 {
		t.Fatalf("expected ≥1 local match, got 0")
	}
	if results[0].AgentPubkey != ad.AgentPubkey {
		t.Errorf("want %q, got %q", ad.AgentPubkey, results[0].AgentPubkey)
	}
}

// TestFindFiltersByTier — agents below min_tier are excluded.
func TestFindFiltersByTier(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	h, closeH := buildHost(t)
	defer closeH()
	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}
	defer gd.Close()

	low := makeAd(t, 1, 1, 0.5)
	high := makeAd(t, 1, 3, 0.5) // same embedding seed → same bucket
	if _, err := gd.PublishAgent(ctx, low); err != nil {
		t.Fatalf("publish low: %v", err)
	}
	if _, err := gd.PublishAgent(ctx, high); err != nil {
		t.Fatalf("publish high: %v", err)
	}

	q := fakeEmbedding(1)
	results, err := gd.FindAgents(ctx, q, 10, 3, 0)
	if err != nil {
		t.Fatalf("find: %v", err)
	}
	for _, r := range results {
		if r.AttestationTier < 3 {
			t.Errorf("got tier-%d agent in min_tier=3 query", r.AttestationTier)
		}
	}
}

// TestRepublishLoopBumpsLastSeen — start the republish loop with a
// short interval, wait for two ticks, and verify the local ad's
// last_seen timestamp has advanced. This is the freshness invariant
// the loop exists to maintain: without it, DHT records expire and the
// node disappears from FindAgents results until something else triggers
// a Publish.
func TestRepublishLoopBumpsLastSeen(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	h, closeH := buildHost(t)
	defer closeH()

	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}
	defer gd.Close()

	ad := makeAd(t, 7777, 1, 0.5)
	if _, err := gd.PublishAgent(ctx, ad); err != nil {
		t.Fatalf("publish: %v", err)
	}

	// Snapshot the as-published last_seen.
	before := gd.LocalAgents()
	if len(before) != 1 {
		t.Fatalf("expected 1 local ad, got %d", len(before))
	}
	beforeLastSeen := before[0].LastSeen

	// Loop tick = 30ms; deadline = 250ms gives ~8 ticks worth of headroom
	// even on a slow CI runner.
	gd.StartRepublishLoop(ctx, 30*time.Millisecond)

	deadline := time.Now().Add(250 * time.Millisecond)
	for time.Now().Before(deadline) {
		if gd.RepublishCount() >= 2 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if got := gd.RepublishCount(); got < 2 {
		t.Fatalf("RepublishCount = %d, want ≥ 2 after 250ms", got)
	}

	after := gd.LocalAgents()
	if len(after) != 1 {
		t.Fatalf("expected 1 local ad after republish, got %d", len(after))
	}
	if after[0].LastSeen <= beforeLastSeen {
		t.Errorf("LastSeen did not advance: before=%d after=%d", beforeLastSeen, after[0].LastSeen)
	}
}

// TestRelayPublishAndFind — single-host smoke test for the relay record
// path: PublishRelay writes a RelayList to /gyza/relays; FindRelays
// reads it back. Catches regressions in the validator (which now has to
// dispatch by key prefix between AgentBucket and RelayList) and in the
// merge LWW logic.
func TestRelayPublishAndFind(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	h, closeH := buildHost(t)
	defer closeH()
	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}
	defer gd.Close()

	entry := &pb.RelayEntry{
		PeerId:           "12D3KooWFakeRelay001",
		Multiaddrs:       []string{"/ip4/198.51.100.7/udp/7749/quic-v1"},
		LastSeen:         time.Now().UnixNano(),
		CompositorPubkey: "deadbeef",
	}
	if err := gd.PublishRelay(ctx, entry, time.Hour); err != nil {
		t.Fatalf("PublishRelay: %v", err)
	}
	relays, err := gd.FindRelays(ctx, 5, time.Hour)
	if err != nil {
		t.Fatalf("FindRelays: %v", err)
	}
	if len(relays) != 1 {
		t.Fatalf("FindRelays returned %d entries, want 1", len(relays))
	}
	if relays[0].PeerId != entry.PeerId {
		t.Errorf("PeerId = %q, want %q", relays[0].PeerId, entry.PeerId)
	}

	// Re-publish under same peer_id with newer LastSeen — LWW should
	// replace, not append.
	updated := &pb.RelayEntry{
		PeerId:     entry.PeerId,
		Multiaddrs: []string{"/ip4/198.51.100.7/udp/7800/quic-v1"},
		LastSeen:   entry.LastSeen + int64(time.Second),
	}
	if err := gd.PublishRelay(ctx, updated, time.Hour); err != nil {
		t.Fatalf("re-publish: %v", err)
	}
	relays, err = gd.FindRelays(ctx, 5, time.Hour)
	if err != nil {
		t.Fatalf("FindRelays: %v", err)
	}
	if len(relays) != 1 {
		t.Fatalf("after LWW upsert, got %d entries, want 1", len(relays))
	}
	if relays[0].Multiaddrs[0] != updated.Multiaddrs[0] {
		t.Errorf("expected newer multiaddr %q, got %q",
			updated.Multiaddrs[0], relays[0].Multiaddrs[0])
	}
}

// TestRelayStalenessPruning — entries older than staleAfter are dropped
// on FindRelays. This is the freshness invariant: a relay that died
// 2 days ago shouldn't keep showing up just because its DHT record
// hasn't expired yet.
func TestRelayStalenessPruning(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	h, closeH := buildHost(t)
	defer closeH()
	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}
	defer gd.Close()

	// Old entry — pretend it was published an hour ago.
	old := &pb.RelayEntry{
		PeerId:   "12D3KooWFakeOld",
		LastSeen: time.Now().Add(-time.Hour).UnixNano(),
	}
	if err := gd.PublishRelay(ctx, old, 0); err != nil {
		t.Fatalf("publish old: %v", err)
	}
	// Filter with 5min freshness window — old entry should be hidden.
	out, err := gd.FindRelays(ctx, 10, 5*time.Minute)
	if err != nil {
		t.Fatalf("find: %v", err)
	}
	if len(out) != 0 {
		t.Errorf("stale entry not pruned: %+v", out)
	}
	// Same call without staleness filter returns it.
	out, err = gd.FindRelays(ctx, 10, 0)
	if err != nil {
		t.Fatalf("find no-filter: %v", err)
	}
	if len(out) != 1 {
		t.Errorf("no-filter find returned %d, want 1", len(out))
	}
}

// TestAttestationPublishAndFetch — round-trip an AttestationCert
// through the DHT. Validates that the validator dispatches
// AttestationCert records correctly (i.e. doesn't try to parse them
// as AgentBucket or RelayList).
func TestAttestationPublishAndFetch(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	h, closeH := buildHost(t)
	defer closeH()
	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}
	defer gd.Close()

	applicantPubkey := "deadbeef" + strings.Repeat("00", 28)
	body := &pb.AttestationBody{
		ApplicantPubkey:  applicantPubkey,
		IssuedAtNs:       time.Now().UnixNano(),
		ExpiresAtNs:      time.Now().Add(24 * time.Hour).UnixNano(),
		TierGranted:      3,
		ChallengeTaskIds: []string{"t1", "t2"},
	}
	cert := &pb.AttestationCert{
		Body: body,
		CoSignatures: []*pb.CoSignature{
			{ValidatorPubkey: strings.Repeat("aa", 32), Signature: make([]byte, 64), SignedAtNs: time.Now().UnixNano()},
			{ValidatorPubkey: strings.Repeat("bb", 32), Signature: make([]byte, 64), SignedAtNs: time.Now().UnixNano()},
		},
	}

	key, err := gd.PublishAttestation(ctx, cert)
	if err != nil {
		t.Fatalf("PublishAttestation: %v", err)
	}
	if key != "/gyza/attestations/"+body.ApplicantPubkey {
		t.Errorf("unexpected key %q", key)
	}

	got, err := gd.FetchAttestation(ctx, body.ApplicantPubkey)
	if err != nil {
		t.Fatalf("FetchAttestation: %v", err)
	}
	if got == nil {
		t.Fatalf("expected cert, got nil")
	}
	if got.Body.ApplicantPubkey != body.ApplicantPubkey {
		t.Errorf("body pubkey = %q, want %q", got.Body.ApplicantPubkey, body.ApplicantPubkey)
	}
	if len(got.CoSignatures) != 2 {
		t.Errorf("cosignatures = %d, want 2", len(got.CoSignatures))
	}
}

// TestAttestationFetchMissing — a fetch for an unattested pubkey
// returns (nil, nil) rather than an error. Application code uses
// this to distinguish "no cert" from "DHT failure".
func TestAttestationFetchMissing(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	h, closeH := buildHost(t)
	defer closeH()
	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}
	defer gd.Close()
	cert, err := gd.FetchAttestation(ctx, strings.Repeat("00", 32))
	if err != nil {
		t.Fatalf("FetchAttestation: %v", err)
	}
	if cert != nil {
		t.Errorf("expected nil cert for unattested pubkey, got %+v", cert)
	}
}

// TestRepublishLoopDisabledWhenIntervalZero — interval ≤ 0 means
// "don't run the loop at all". Catches a regression where a config
// path that disables auto-republish accidentally still spawns the
// goroutine.
func TestRepublishLoopDisabledWhenIntervalZero(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	h, closeH := buildHost(t)
	defer closeH()
	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}
	defer gd.Close()

	gd.StartRepublishLoop(ctx, 0)
	gd.StartRepublishLoop(ctx, -1)
	time.Sleep(100 * time.Millisecond)
	if got := gd.RepublishCount(); got != 0 {
		t.Errorf("RepublishCount = %d with disabled loop, want 0", got)
	}
}

// TestPublishAndFindAcrossHosts — the real Phase 3 contract. Host A
// publishes; host B (different process, different routing table)
// finds via DHT. We run them in-process for speed, but they go through
// real libp2p, real Kademlia, real /gyza/1.0 protocol, and a real
// AgentBucket validator round-trip.
func TestPublishAndFindAcrossHosts(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	hA, closeA := buildHost(t)
	defer closeA()
	hB, closeB := buildHost(t)
	defer closeB()

	connect(t, ctx, hA, hB)

	dA, err := dht.NewGyzaDHT(ctx, hA, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("dht A: %v", err)
	}
	defer dA.Close()
	dB, err := dht.NewGyzaDHT(ctx, hB, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("dht B: %v", err)
	}
	defer dB.Close()

	// Both DHTs must know about the other peer before Publish/Get
	// can route. Bootstrap is async — give it a moment.
	waitForRoutingTable(t, ctx, dA, 1, 5*time.Second)
	waitForRoutingTable(t, ctx, dB, 1, 5*time.Second)

	ad := makeAd(t, 9876, 2, 0.7)
	if _, err := dA.PublishAgent(ctx, ad); err != nil {
		t.Fatalf("publish on A: %v", err)
	}

	// Query the same embedding via host B's DHT. Because B does not
	// have ad in its `local` cache, success here is a real DHT lookup.
	queryEmb := fakeEmbedding(9876)
	var results []*pb.AgentAdvertisement
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		results, err = dB.FindAgents(ctx, queryEmb, 5, 0, 0)
		if err == nil && len(results) > 0 {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if err != nil {
		t.Fatalf("find on B: %v", err)
	}
	if len(results) == 0 {
		t.Fatalf("host B did not see host A's published advertisement via DHT")
	}
	if results[0].AgentPubkey != ad.AgentPubkey {
		t.Errorf("want %q, got %q", ad.AgentPubkey, results[0].AgentPubkey)
	}
}
