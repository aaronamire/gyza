package dht_test

// A NODE THAT NEVER PROMOTES TO SERVER MUST SAY SO.
//
// ModeAuto starts every node as a DHT client and promotes it only when AutoNAT
// confirms inbound reachability. Behind NAT — which is the common case for a
// fleet of agent runners — promotion may never happen. Clients query the
// routing layer without answering queries, so the whole DHT rests on whatever
// nodes are publicly reachable, and nothing anywhere reports that.
//
// The daemon's only signal was a startup line printing the --dht-mode FLAG,
// i.e. what the operator asked for. kaddht.IpfsDHT.Mode() is no better: it
// returns the ModeOpt the DHT was constructed with, so an auto node reports
// "auto" whether or not it promoted. Both describe the request, not the state.

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"

	kaddht "github.com/libp2p/go-libp2p-kad-dht"
	"github.com/libp2p/go-libp2p/core/protocol"

	"gyza/netd/internal/dht"
)

// ServingMode reads the runtime mode by looking for the DHT's server stream
// handler on the host. That protocol ID is RECONSTRUCTED from the prefix
// because kad-dht does not export it — a claim about a dependency's internals,
// so it is checked against a real server-mode host rather than trusted.
func TestServerProtocolIDMatchesWhatTheHostRegisters(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	h, closeH := buildHost(t)
	defer closeH()

	if _, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer); err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}

	var got []string
	for _, p := range h.Mux().Protocols() {
		got = append(got, string(p))
		if p == dht.ServerProtocolID {
			return
		}
	}
	t.Fatalf("ServerProtocolID %q is registered by no handler on a server-mode "+
		"host, so ServingMode would report every node as a client. kad-dht "+
		"likely changed how it derives the protocol from the prefix. "+
		"Registered: %s", dht.ServerProtocolID, strings.Join(got, " "))
}

// The prefix must reach kaddht, not just be declared: a constant that the
// constructor does not pass is a segregation claim with no mechanism.
func TestProtocolPrefixIsActuallyApplied(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	h, closeH := buildHost(t)
	defer closeH()

	if _, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer); err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}
	for _, p := range h.Mux().Protocols() {
		if p == protocol.ID("/ipfs/kad/1.0.0") {
			t.Fatal("registered the PUBLIC IPFS DHT protocol: the /gyza/1.0 " +
				"prefix did not take effect and this node would answer " +
				"queries on the public DHT")
		}
	}
}

// The two modes are distinguishable. Without this, ServingMode could return a
// constant and every other assertion here would still pass.
func TestServingModeDistinguishesServerFromClient(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	hs, closeS := buildHost(t)
	defer closeS()
	srv, err := dht.NewGyzaDHT(ctx, hs, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("server dht: %v", err)
	}

	hc, closeC := buildHost(t)
	defer closeC()
	cli, err := dht.NewGyzaDHT(ctx, hc, kaddht.ModeClient)
	if err != nil {
		t.Fatalf("client dht: %v", err)
	}

	if got := srv.ServingMode(); got != "server" {
		t.Errorf("ModeServer node reports ServingMode()=%q, want \"server\"", got)
	}
	if got := cli.ServingMode(); got != "client" {
		t.Errorf("ModeClient node reports ServingMode()=%q, want \"client\"", got)
	}
}

// The warning fires for a node that asked for auto and stayed a client. This
// is the whole point of the watch: silence is what the defect looked like.
func TestWatchPromotionWarnsWhenAutoNodeStaysClient(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	h, closeH := buildHost(t)
	defer closeH()

	// ModeClient stands in for an auto node that never got promoted: from the
	// host's point of view the two are the same state, which is exactly why
	// the runtime mode had to be read off the host rather than the config.
	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeClient)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}

	var mu sync.Mutex
	var lines []string
	logf := func(format string, _ ...any) {
		mu.Lock()
		defer mu.Unlock()
		lines = append(lines, strings.ToLower(format))
	}

	watchCtx, stop := context.WithCancel(ctx)
	defer stop()
	gd.WatchPromotion(watchCtx, "auto", 10*time.Millisecond, 20*time.Millisecond, logf)

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		mu.Lock()
		var warned bool
		for _, l := range lines {
			if strings.Contains(l, "warning") && strings.Contains(l, "client-mode") {
				warned = true
			}
		}
		mu.Unlock()
		if warned {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	mu.Lock()
	defer mu.Unlock()
	t.Fatalf("no free-rider warning after grace elapsed; logged: %v", lines)
}

// ... and does NOT fire for a node the operator deliberately ran as a client.
// A warning that fires on a correct configuration gets muted, and then it is
// not there for the case it was written for.
func TestWatchPromotionSilentWhenClientWasRequested(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	h, closeH := buildHost(t)
	defer closeH()

	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeClient)
	if err != nil {
		t.Fatalf("NewGyzaDHT: %v", err)
	}

	var mu sync.Mutex
	var lines []string
	logf := func(format string, _ ...any) {
		mu.Lock()
		defer mu.Unlock()
		lines = append(lines, strings.ToLower(format))
	}

	watchCtx, stop := context.WithCancel(ctx)
	defer stop()
	gd.WatchPromotion(watchCtx, "client", 10*time.Millisecond, 20*time.Millisecond, logf)
	time.Sleep(500 * time.Millisecond)

	mu.Lock()
	defer mu.Unlock()
	for _, l := range lines {
		if strings.Contains(l, "warning") {
			t.Fatalf("warned about an explicitly-requested client: %q", l)
		}
	}
}
