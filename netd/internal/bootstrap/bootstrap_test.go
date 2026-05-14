package bootstrap

import (
	"context"
	"errors"
	"sort"
	"testing"
)

// fakeResolver implements Resolver for tests.
type fakeResolver struct {
	records map[string][]string
	err     error
}

func (f *fakeResolver) LookupTXT(_ context.Context, name string) ([]string, error) {
	if f.err != nil {
		return nil, f.err
	}
	return f.records[name], nil
}

// Two real-looking but synthetic bootstrap multiaddrs. Peer IDs are
// from the libp2p test corpus and stable across runs; addresses are
// non-routable so the tests can't accidentally hit the network.
const (
	testMA1 = "/ip4/192.0.2.10/udp/7749/quic-v1/p2p/QmRELayv4r1Y1Q3HpY9DKuUPdJ8YjW1eqgmGz9XJZW5L93"
	testMA2 = "/ip4/198.51.100.20/udp/7749/quic-v1/p2p/QmYJZcvX9F9CSPDjV3GqLDeshmnZJp8sZi2ZWLXnQrTbDh"
	testMA3 = "/ip4/203.0.113.30/udp/7749/quic-v1/p2p/QmZmJ5dV9wT94zWcGE3vAbX5RXp4kdwG3oN8HHQBxKWZ1Z"
)

// helper: parse the multiaddr and assert it's valid; tests fail early
// if the constants ever break.
func mustParse(t *testing.T, s string) {
	t.Helper()
	if _, err := parseMultiaddrToAddrInfo(s); err != nil {
		t.Fatalf("test constant %q didn't parse: %v", s, err)
	}
}

func TestParseTXTRecords_HappyPath(t *testing.T) {
	mustParse(t, testMA1)
	mustParse(t, testMA2)

	txts := []string{
		"dnsaddr=" + testMA1,
		"dnsaddr=" + testMA2,
	}
	got := parseTXTRecords(txts)
	if len(got) != 2 {
		t.Fatalf("expected 2 peers, got %d", len(got))
	}
}

func TestParseTXTRecords_SkipsMalformed(t *testing.T) {
	mustParse(t, testMA1)

	txts := []string{
		"dnsaddr=" + testMA1,
		"dnsaddr=not-a-multiaddr",
		"dnsaddr=", // empty value
		"no-prefix-here",
		"v=spf1 -all", // unrelated TXT record
		"dnsaddr=/ip4/badformat",
	}
	got := parseTXTRecords(txts)
	if len(got) != 1 {
		t.Fatalf("expected 1 valid peer, got %d", len(got))
	}
}

func TestParseTXTRecords_HandlesWhitespace(t *testing.T) {
	mustParse(t, testMA1)

	txts := []string{
		"  dnsaddr=" + testMA1 + "  ",
		"dnsaddr=   " + testMA2,
	}
	got := parseTXTRecords(txts)
	if len(got) != 2 {
		t.Fatalf("expected 2 peers after whitespace trim, got %d", len(got))
	}
}

func TestResolve_DNSOnly(t *testing.T) {
	orig := FallbackPeers
	FallbackPeers = nil
	defer func() { FallbackPeers = orig }()
	r := &fakeResolver{
		records: map[string][]string{
			"_dnsaddr.example.test": {
				"dnsaddr=" + testMA1,
				"dnsaddr=" + testMA2,
			},
		},
	}
	got := Resolve(context.Background(), r, "example.test", nil)
	if len(got) != 2 {
		t.Fatalf("expected 2 DNS peers, got %d", len(got))
	}
}

func TestResolve_FallbackOnly(t *testing.T) {
	// Temporarily inject a fallback.
	orig := FallbackPeers
	FallbackPeers = []string{testMA1}
	defer func() { FallbackPeers = orig }()

	r := &fakeResolver{records: map[string][]string{}} // empty
	got := Resolve(context.Background(), r, "example.test", nil)
	if len(got) != 1 {
		t.Fatalf("expected 1 fallback peer, got %d", len(got))
	}
}

func TestResolve_DNSFailsFallsBackToHardcoded(t *testing.T) {
	orig := FallbackPeers
	FallbackPeers = []string{testMA1}
	defer func() { FallbackPeers = orig }()

	r := &fakeResolver{err: errors.New("SERVFAIL")}

	var logged []string
	logf := func(format string, args ...any) {
		logged = append(logged, format)
	}

	got := Resolve(context.Background(), r, "example.test", logf)
	if len(got) != 1 {
		t.Fatalf("expected 1 fallback peer when DNS errors, got %d", len(got))
	}
	if len(logged) == 0 {
		t.Fatalf("expected at least one log line for DNS failure")
	}
	// Verify the log mentions DNS failure (sloppy substring match — we
	// don't want to over-specify the message).
	foundDNSFailure := false
	for _, line := range logged {
		if contains(line, "DNS resolution") {
			foundDNSFailure = true
		}
	}
	if !foundDNSFailure {
		t.Fatalf("expected DNS failure log; got %v", logged)
	}
}

func TestResolve_DedupAcrossDNSAndFallback(t *testing.T) {
	orig := FallbackPeers
	FallbackPeers = []string{testMA1} // same as DNS record
	defer func() { FallbackPeers = orig }()

	r := &fakeResolver{
		records: map[string][]string{
			"_dnsaddr.example.test": {"dnsaddr=" + testMA1},
		},
	}
	got := Resolve(context.Background(), r, "example.test", nil)
	if len(got) != 1 {
		t.Fatalf("expected dedup to 1 peer, got %d", len(got))
	}
}

func TestResolve_EmptyDomain_OnlyFallback(t *testing.T) {
	orig := FallbackPeers
	FallbackPeers = []string{testMA1}
	defer func() { FallbackPeers = orig }()

	// DNS resolver should not be consulted when domain is "".
	r := &fakeResolver{err: errors.New("should not be called")}
	got := Resolve(context.Background(), r, "", nil)
	if len(got) != 1 {
		t.Fatalf("expected 1 fallback peer with empty domain, got %d", len(got))
	}
}

func TestResolve_NoSourcesYieldsEmpty(t *testing.T) {
	orig := FallbackPeers
	FallbackPeers = nil
	defer func() { FallbackPeers = orig }()

	r := &fakeResolver{records: map[string][]string{}}
	var logged []string
	logf := func(format string, args ...any) {
		logged = append(logged, format)
	}

	got := Resolve(context.Background(), r, "example.test", logf)
	if len(got) != 0 {
		t.Fatalf("expected 0 peers, got %d", len(got))
	}
	// We expect a "no peers resolved" log line.
	foundEmpty := false
	for _, line := range logged {
		if contains(line, "no peers resolved") {
			foundEmpty = true
		}
	}
	if !foundEmpty {
		t.Fatalf("expected empty-resolution log line; got %v", logged)
	}
}

func TestResolveWithExtras_MergesUserSupplied(t *testing.T) {
	orig := FallbackPeers
	FallbackPeers = nil
	defer func() { FallbackPeers = orig }()

	r := &fakeResolver{
		records: map[string][]string{
			"_dnsaddr.example.test": {"dnsaddr=" + testMA1},
		},
	}
	got := ResolveWithExtras(
		context.Background(),
		r, "example.test",
		[]string{testMA2},
		nil,
	)
	if len(got) != 2 {
		t.Fatalf("expected DNS + extras = 2 peers, got %d", len(got))
	}
}

func TestResolveWithExtras_DropsBadExtras(t *testing.T) {
	orig := FallbackPeers
	FallbackPeers = nil
	defer func() { FallbackPeers = orig }()

	r := &fakeResolver{records: map[string][]string{}}
	got := ResolveWithExtras(
		context.Background(),
		r, "example.test",
		[]string{"not-a-multiaddr", testMA1, "/ip4/nope"},
		nil,
	)
	if len(got) != 1 {
		t.Fatalf("expected 1 valid extra peer, got %d", len(got))
	}
}

func TestAsMultiaddrStrings_Roundtrip(t *testing.T) {
	orig := FallbackPeers
	FallbackPeers = nil
	defer func() { FallbackPeers = orig }()
	r := &fakeResolver{
		records: map[string][]string{
			"_dnsaddr.example.test": {
				"dnsaddr=" + testMA1,
				"dnsaddr=" + testMA2,
				"dnsaddr=" + testMA3,
			},
		},
	}
	peers := Resolve(context.Background(), r, "example.test", nil)
	strs := AsMultiaddrStrings(peers)
	if len(strs) != 3 {
		t.Fatalf("expected 3 multiaddr strings, got %d: %v", len(strs), strs)
	}
	// Sorted for deterministic comparison; order out of Resolve is
	// map-iteration order.
	sort.Strings(strs)
	want := []string{testMA1, testMA2, testMA3}
	sort.Strings(want)
	for i := range strs {
		if strs[i] != want[i] {
			t.Errorf("strs[%d] = %q, want %q", i, strs[i], want[i])
		}
	}
}

// contains is a tiny substring helper.
func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
