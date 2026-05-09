package discovery

import (
	"context"
	"crypto/rand"
	"sync"
	"testing"
	"time"

	libp2p "github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	libp2pquic "github.com/libp2p/go-libp2p/p2p/transport/quic"
)

// makeHost spins up a libp2p host on a random loopback QUIC port. We
// don't reuse internal/host because that pulls in the identity package
// (and its 0600 mode check on a temp file), which we don't need here.
func makeHost(t *testing.T) (host.Host, func()) {
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

// TestNotifeeIgnoresSelf — the discovery loop must not treat its own
// announce as a peer; if it did, every node would log a noisy "connect
// to self" failure on startup.
func TestNotifeeIgnoresSelf(t *testing.T) {
	h, cleanup := makeHost(t)
	defer cleanup()

	logged := 0
	n := &connectNotifee{
		ctx:  context.Background(),
		host: h,
		logf: func(string, ...any) { logged++ },
	}
	n.HandlePeerFound(peer.AddrInfo{ID: h.ID(), Addrs: h.Addrs()})

	if got := n.peersFound.Load(); got != 0 {
		t.Errorf("self-announce incremented peersFound to %d (want 0)", got)
	}
	if logged != 0 {
		t.Errorf("self-announce logged %d times (want 0)", logged)
	}
}

// TestNotifeeDialsDiscoveredPeer — when mDNS surfaces a real peer, the
// notifee must Connect to them. We exercise this without real mDNS by
// hand-injecting an AddrInfo that we know hostB is listening on.
func TestNotifeeDialsDiscoveredPeer(t *testing.T) {
	hA, cleanupA := makeHost(t)
	defer cleanupA()
	hB, cleanupB := makeHost(t)
	defer cleanupB()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	var mu sync.Mutex
	var lines []string
	logf := func(format string, args ...any) {
		mu.Lock()
		defer mu.Unlock()
		_ = format
		_ = args
		lines = append(lines, format)
	}

	n := &connectNotifee{ctx: ctx, host: hA, logf: logf}
	n.HandlePeerFound(peer.AddrInfo{ID: hB.ID(), Addrs: hB.Addrs()})

	// HandlePeerFound dials in a goroutine; poll for connection rather
	// than sleeping a fixed duration.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if hA.Network().Connectedness(hB.ID()).String() == "Connected" {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if c := hA.Network().Connectedness(hB.ID()).String(); c != "Connected" {
		t.Fatalf("hostA never connected to hostB after mDNS-style dial (state=%s)", c)
	}

	if got := n.peersFound.Load(); got != 1 {
		t.Errorf("peersFound = %d, want 1", got)
	}
}

// TestServiceLifecycle — the public API: NewMDNSDiscovery starts a real
// mDNS service, Close releases it, double-Close is a no-op. We don't
// assert that two NewMDNSDiscovery instances actually find each other
// because LAN multicast availability varies wildly across CI sandboxes.
func TestServiceLifecycle(t *testing.T) {
	h, cleanup := makeHost(t)
	defer cleanup()

	d, err := NewMDNSDiscovery(context.Background(), h, nil)
	if err != nil {
		t.Fatalf("NewMDNSDiscovery: %v", err)
	}
	if got := d.PeersFound(); got != 0 {
		t.Errorf("fresh discovery has PeersFound=%d, want 0", got)
	}
	if err := d.Close(); err != nil {
		t.Errorf("first Close: %v", err)
	}
	// Second Close should be tolerant. The libp2p mdns Close may return
	// an error on the second call ("already closed"); we accept either
	// nil or an error so long as it doesn't panic.
	_ = d.Close()
}

// TestNilDiscoveryClose — Close on a nil receiver must not panic; the
// gRPC server's nullable-discovery code path relies on this.
func TestNilDiscoveryClose(t *testing.T) {
	var d *MDNSDiscovery
	if err := d.Close(); err != nil {
		t.Errorf("nil Close returned %v, want nil", err)
	}
	if got := d.PeersFound(); got != 0 {
		t.Errorf("nil PeersFound = %d, want 0", got)
	}
}
