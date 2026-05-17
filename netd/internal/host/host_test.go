package host

import (
	"context"
	"testing"
	"time"

	libp2p "github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
)

// newTestHost spins up a bare libp2p host on a loopback QUIC port.
// No identity / DHT / NAT — just enough to exercise dial behavior.
func newTestHost(t *testing.T) host.Host {
	t.Helper()
	h, err := libp2p.New(
		libp2p.ListenAddrStrings("/ip4/127.0.0.1/udp/0/quic-v1"),
	)
	if err != nil {
		t.Fatalf("libp2p.New: %v", err)
	}
	t.Cleanup(func() { _ = h.Close() })
	return h
}

// p2pAddr returns h's first listen multiaddr with /p2p/<id> appended —
// the form RebootstrapOnce / ConnectBootstrap parse.
func p2pAddr(t *testing.T, h host.Host) string {
	t.Helper()
	addrs := h.Addrs()
	if len(addrs) == 0 {
		t.Fatalf("host %s has no listen addrs", h.ID())
	}
	return addrs[0].String() + "/p2p/" + h.ID().String()
}

// waitConnected polls until h's connectedness to id matches `want`,
// or the deadline elapses.
func waitConnected(
	t *testing.T, h host.Host, id peer.ID,
	want network.Connectedness, deadline time.Duration,
) bool {
	t.Helper()
	stop := time.Now().Add(deadline)
	for time.Now().Before(stop) {
		if h.Network().Connectedness(id) == want {
			return true
		}
		time.Sleep(20 * time.Millisecond)
	}
	return false
}

// ----------------------------------------------------------------------

func TestRebootstrapOnceConnectsAndIsIdempotent(t *testing.T) {
	ctx := context.Background()
	h1, h2 := newTestHost(t), newTestHost(t)

	// First call dials h2.
	n := RebootstrapOnce(ctx, h1, []string{p2pAddr(t, h2)}, t.Logf)
	if n != 1 {
		t.Fatalf("first RebootstrapOnce dialed %d, want 1", n)
	}
	if h1.Network().Connectedness(h2.ID()) != network.Connected {
		t.Fatalf("h1 not connected to h2 after RebootstrapOnce")
	}

	// Second call must be a no-op — already connected, dialed count 0.
	n = RebootstrapOnce(ctx, h1, []string{p2pAddr(t, h2)}, t.Logf)
	if n != 0 {
		t.Fatalf("second RebootstrapOnce dialed %d, want 0 (idempotent)", n)
	}
}

func TestRebootstrapOnceSkipsSelf(t *testing.T) {
	ctx := context.Background()
	h1 := newTestHost(t)
	// Our own multiaddr can legitimately appear in a resolved set
	// (a bootstrap node re-bootstrapping reads its own dnsaddr).
	n := RebootstrapOnce(ctx, h1, []string{p2pAddr(t, h1)}, t.Logf)
	if n != 0 {
		t.Fatalf("RebootstrapOnce dialed self %d times, want 0", n)
	}
}

func TestRebootstrapOnceToleratesGarbage(t *testing.T) {
	ctx := context.Background()
	h1, h2 := newTestHost(t), newTestHost(t)
	// A malformed entry alongside a good one must not abort the loop.
	addrs := []string{
		"not-a-multiaddr",
		"/ip4/127.0.0.1/udp/1/quic-v1", // valid multiaddr, no /p2p/
		p2pAddr(t, h2),
	}
	n := RebootstrapOnce(ctx, h1, addrs, t.Logf)
	if n != 1 {
		t.Fatalf("RebootstrapOnce dialed %d, want 1 (good entry survives garbage)", n)
	}
}

// TestStartBootstrapLoopRecoversLostPeer is the property that matters:
// a daemon that loses every bootstrap connection must get back on the
// mesh on its own. We connect, forcibly drop the connection, and
// assert the loop re-dials without any further intervention.
func TestStartBootstrapLoopRecoversLostPeer(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	h1, h2 := newTestHost(t), newTestHost(t)
	resolve := func() []string { return []string{p2pAddr(t, h2)} }

	StartBootstrapLoop(ctx, h1, resolve, 80*time.Millisecond, t.Logf)

	// Initial connect by the loop.
	if !waitConnected(t, h1, h2.ID(), network.Connected, 3*time.Second) {
		t.Fatalf("loop did not establish the initial connection")
	}

	// Forcibly drop it — simulates a bootstrap node restart / NAT churn.
	if err := h1.Network().ClosePeer(h2.ID()); err != nil {
		t.Fatalf("ClosePeer: %v", err)
	}
	if !waitConnected(t, h1, h2.ID(), network.NotConnected, 1*time.Second) {
		t.Fatalf("connection did not drop after ClosePeer")
	}

	// The loop must re-dial on a subsequent tick — with NO further
	// calls from the test. This is the recovery guarantee.
	if !waitConnected(t, h1, h2.ID(), network.Connected, 3*time.Second) {
		t.Fatalf("loop did not recover the lost peer — daemon would be a " +
			"permanent DHT island")
	}
}

func TestStartBootstrapLoopDisabledWhenIntervalNonPositive(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	h1, h2 := newTestHost(t), newTestHost(t)
	// interval <= 0 must be a hard no-op (tests / single-shot daemons).
	StartBootstrapLoop(ctx, h1, func() []string { return []string{p2pAddr(t, h2)} },
		0, t.Logf)
	time.Sleep(300 * time.Millisecond)
	if h1.Network().Connectedness(h2.ID()) == network.Connected {
		t.Fatalf("loop ran despite interval<=0")
	}
}

func TestStartBootstrapLoopStopsOnContextCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	h1, h2 := newTestHost(t), newTestHost(t)
	StartBootstrapLoop(ctx, h1, func() []string { return []string{p2pAddr(t, h2)} },
		50*time.Millisecond, t.Logf)
	if !waitConnected(t, h1, h2.ID(), network.Connected, 3*time.Second) {
		t.Fatalf("loop did not connect before cancel")
	}
	cancel()
	// After cancel, drop the peer; the loop must NOT bring it back.
	_ = h1.Network().ClosePeer(h2.ID())
	time.Sleep(400 * time.Millisecond)
	if h1.Network().Connectedness(h2.ID()) == network.Connected {
		t.Fatalf("loop kept running after context cancel")
	}
}
