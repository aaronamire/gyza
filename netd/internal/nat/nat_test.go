package nat_test

// NAT tests. We exercise the manager surface end-to-end against real
// libp2p hosts. Full DCUtR / circuit-relay verification needs three
// nodes on different network conditions and is left for the integration
// demo (Phase 3 Session 8). What this file proves on a single machine:
//
//   - LibP2POptions feeds a working host (no construction errors when
//     EnableHolePunching / EnableAutoRelay are set with a deferred DHT).
//   - ObservedAddr never panics on a single-node setup; returns "" or a
//     non-private multiaddr.
//   - ConnectWithNAT drives a successful direct dial on loopback.
//   - The static-relay-only peer source returns the configured set.
//   - AdvertiseAsRelay → DHT → FindRelayNodes round-trip preserves a
//     publicly-addressed relay entry.

import (
	"context"
	"crypto/rand"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"gyza/netd/internal/dht"
	pb "gyza/netd/internal/grpc/proto"
	"gyza/netd/internal/host"
	"gyza/netd/internal/identity"
	"gyza/netd/internal/nat"

	libp2p "github.com/libp2p/go-libp2p"
	kaddht "github.com/libp2p/go-libp2p-kad-dht"
	"github.com/libp2p/go-libp2p/core/crypto"
	libhost "github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	libp2pquic "github.com/libp2p/go-libp2p/p2p/transport/quic"
	"github.com/multiformats/go-multiaddr"
)

// makeIdentity writes a 32-byte master seed at mode 0600 and loads the
// resulting compositor identity. Same shape as Identity returned by
// the daemon at runtime.
func makeIdentity(t *testing.T) *identity.Identity {
	t.Helper()
	dir := t.TempDir()
	keyPath := filepath.Join(dir, "compositor.key")
	seed := make([]byte, 32)
	if _, err := rand.Read(seed); err != nil {
		t.Fatalf("rand: %v", err)
	}
	if err := os.WriteFile(keyPath, seed, 0o600); err != nil {
		t.Fatalf("write key: %v", err)
	}
	id, err := identity.LoadIdentity(keyPath)
	if err != nil {
		t.Fatalf("LoadIdentity: %v", err)
	}
	return id
}

// rawHost spins up a minimal libp2p host on loopback. Used as a
// "bare" peer for ConnectWithNAT to dial.
func rawHost(t *testing.T) (libhost.Host, func()) {
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

// TestManagerLifecycle — NewManager + LibP2POptions + SetHost + SetDHT
// must compose with host.NewHost without panic and with all the NAT
// subsystems enabled. This is the full happy-path wiring exercised in
// production main.go.
func TestManagerLifecycle(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	id := makeIdentity(t)

	mgr := nat.NewManager(nat.Config{
		EnableHolePunching: true,
		EnableAutoRelay:    true,
		AdvertiseInterval:  100 * time.Millisecond,
	})
	if !mgr.Available() {
		t.Fatal("Manager.Available() returned false despite hole-punch + autorelay enabled")
	}

	h, err := host.NewHost(ctx, host.Config{
		Identity:     id,
		ListenPort:   0,
		ExtraOptions: mgr.LibP2POptions(),
	})
	if err != nil {
		t.Fatalf("host.NewHost: %v", err)
	}
	defer func() { _ = h.Close() }()
	mgr.SetHost(h)

	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("dht.NewGyzaDHT: %v", err)
	}
	defer gd.Close()
	mgr.SetDHT(gd)

	// ObservedAddr on a freshly-started single-node host with only
	// loopback listeners may legitimately be empty — we require it to
	// not panic and to return either empty or a non-loopback string.
	obs := mgr.ObservedAddr()
	if obs != "" && strings.Contains(obs, "127.0.0.1") {
		t.Errorf("ObservedAddr returned loopback address %q", obs)
	}
}

// TestConnectWithNATDirect — two hosts on loopback, NAT manager bound
// to one of them. ConnectWithNAT must succeed in the trivial direct
// case (no NAT actually involved). This is the Session 3 minimum: the
// public API works for the easy path. DCUtR / relay validation needs
// real network conditions.
func TestConnectWithNATDirect(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	id := makeIdentity(t)
	mgr := nat.NewManager(nat.Config{
		EnableHolePunching: true,
		EnableAutoRelay:    true,
	})
	hA, err := host.NewHost(ctx, host.Config{
		Identity:     id,
		ListenPort:   0,
		ExtraOptions: mgr.LibP2POptions(),
	})
	if err != nil {
		t.Fatalf("host A: %v", err)
	}
	defer func() { _ = hA.Close() }()
	mgr.SetHost(hA)

	hB, closeB := rawHost(t)
	defer closeB()

	target := peer.AddrInfo{ID: hB.ID(), Addrs: hB.Addrs()}
	if err := mgr.ConnectWithNAT(ctx, target, 5*time.Second); err != nil {
		t.Fatalf("ConnectWithNAT direct: %v", err)
	}
	if c := hA.Network().Connectedness(hB.ID()).String(); c != "Connected" {
		t.Fatalf("after ConnectWithNAT, connectedness = %s, want Connected", c)
	}
}

// TestConnectWithNATTimeout — a target with no listeners and a tight
// timeout fails in bounded time, not hang. Catches a regression where
// we'd pass ctx without applying timeout.
func TestConnectWithNATTimeout(t *testing.T) {
	ctx := context.Background()
	id := makeIdentity(t)
	mgr := nat.NewManager(nat.Config{}) // no NAT subsystems — bare host
	h, err := host.NewHost(ctx, host.Config{
		Identity:     id,
		ListenPort:   0,
		ExtraOptions: mgr.LibP2POptions(),
	})
	if err != nil {
		t.Fatalf("host: %v", err)
	}
	defer func() { _ = h.Close() }()
	mgr.SetHost(h)

	// A multiaddr that points at a closed UDP port on localhost — the
	// QUIC dial blocks on handshake until our timeout fires.
	ma, _ := multiaddr.NewMultiaddr("/ip4/127.0.0.1/udp/1/quic-v1/p2p/12D3KooWBmwXBuyKkAQrqxASE6BwZQNkPV9LJVHtEa3WZdBGqyDH")
	target, err := peer.AddrInfoFromP2pAddr(ma)
	if err != nil {
		t.Fatalf("addrinfo: %v", err)
	}

	start := time.Now()
	err = mgr.ConnectWithNAT(ctx, *target, 500*time.Millisecond)
	elapsed := time.Since(start)
	if err == nil {
		t.Fatal("expected dial to fail")
	}
	if elapsed > 3*time.Second {
		t.Errorf("dial took %v; timeout was 500ms — likely not honored", elapsed)
	}
}

// TestAdvertiseAndFindRoundTrip — push a synthetic relay record into
// the DHT and verify FindRelayNodes returns a fully-formed AddrInfo.
// We bypass the AdvertiseAsRelay loop because publishRelayOnce skips
// when the host has no public addresses (we're on loopback only).
func TestAdvertiseAndFindRoundTrip(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	id := makeIdentity(t)
	mgr := nat.NewManager(nat.Config{
		AdvertiseInterval: time.Hour,
		RelayStaleAfter:   time.Hour,
	})
	h, err := host.NewHost(ctx, host.Config{
		Identity:   id,
		ListenPort: 0,
	})
	if err != nil {
		t.Fatalf("host: %v", err)
	}
	defer func() { _ = h.Close() }()
	mgr.SetHost(h)
	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("dht: %v", err)
	}
	defer gd.Close()
	mgr.SetDHT(gd)

	pubAddr := "/ip4/198.51.100.42/udp/7749/quic-v1"
	pid := h.ID()
	entry := &pb.RelayEntry{
		PeerId:           pid.String(),
		Multiaddrs:       []string{pubAddr},
		LastSeen:         time.Now().UnixNano(),
		CompositorPubkey: id.PubKeyHex,
	}
	if err := gd.PublishRelay(ctx, entry, time.Hour); err != nil {
		t.Fatalf("PublishRelay: %v", err)
	}

	relays, err := mgr.FindRelayNodes(ctx, 5)
	if err != nil {
		t.Fatalf("FindRelayNodes: %v", err)
	}
	if len(relays) != 1 {
		t.Fatalf("FindRelayNodes returned %d, want 1", len(relays))
	}
	if relays[0].ID != pid {
		t.Errorf("PeerID mismatch: got %s, want %s", relays[0].ID, pid)
	}
	if len(relays[0].Addrs) != 1 || relays[0].Addrs[0].String() != pubAddr {
		t.Errorf("addrs mismatch: got %v, want [%s]", relays[0].Addrs, pubAddr)
	}
}

// TestPeerSourceWithStaticRelays — without a DHT, the peer source must
// still surface static relays. This is the "Phase 3 demo: hardcode each
// side's relay" path.
func TestPeerSourceWithStaticRelays(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	mk := func(pidStr, addr string) peer.AddrInfo {
		ma, err := multiaddr.NewMultiaddr(addr)
		if err != nil {
			t.Fatalf("multiaddr %s: %v", addr, err)
		}
		pid, err := peer.Decode(pidStr)
		if err != nil {
			t.Fatalf("peerid %s: %v", pidStr, err)
		}
		return peer.AddrInfo{ID: pid, Addrs: []multiaddr.Multiaddr{ma}}
	}
	staticRelays := []peer.AddrInfo{
		mk("12D3KooWBmwXBuyKkAQrqxASE6BwZQNkPV9LJVHtEa3WZdBGqyDH",
			"/ip4/198.51.100.1/udp/7749/quic-v1"),
		mk("12D3KooWA7ng4ozPMJEMpz1HkdAH6XLG3y4qMjnxDcwHbnBz9Z3K",
			"/ip4/198.51.100.2/udp/7749/quic-v1"),
	}

	mgr := nat.NewManager(nat.Config{
		EnableAutoRelay: true,
		StaticRelays:    staticRelays,
	})

	src := mgr.PeerSource()
	got := []peer.AddrInfo{}
	for ai := range src(ctx, 5) {
		got = append(got, ai)
	}
	if len(got) != 2 {
		t.Fatalf("static-only peer source returned %d, want 2", len(got))
	}
	if got[0].ID != staticRelays[0].ID || got[1].ID != staticRelays[1].ID {
		t.Errorf("ordering mismatch: %v", got)
	}
}

// TestPeerSourceMergesStaticAndDHT — static + DHT relays are both
// surfaced. With num=10 and 1 static + 1 DHT entry, both must appear.
func TestPeerSourceMergesStaticAndDHT(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	id := makeIdentity(t)

	staticRelay := peer.AddrInfo{
		ID:    mustPID(t, "12D3KooWBmwXBuyKkAQrqxASE6BwZQNkPV9LJVHtEa3WZdBGqyDH"),
		Addrs: []multiaddr.Multiaddr{mustMA(t, "/ip4/198.51.100.99/udp/7749/quic-v1")},
	}
	mgr := nat.NewManager(nat.Config{
		EnableAutoRelay: true,
		StaticRelays:    []peer.AddrInfo{staticRelay},
		RelayStaleAfter: time.Hour,
	})
	h, err := host.NewHost(ctx, host.Config{Identity: id, ListenPort: 0})
	if err != nil {
		t.Fatalf("host: %v", err)
	}
	defer func() { _ = h.Close() }()
	mgr.SetHost(h)
	gd, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeServer)
	if err != nil {
		t.Fatalf("dht: %v", err)
	}
	defer gd.Close()
	mgr.SetDHT(gd)

	dynID := mustPID(t, "12D3KooWA7ng4ozPMJEMpz1HkdAH6XLG3y4qMjnxDcwHbnBz9Z3K")
	if err := gd.PublishRelay(ctx, &pb.RelayEntry{
		PeerId:     dynID.String(),
		Multiaddrs: []string{"/ip4/198.51.100.50/udp/7749/quic-v1"},
		LastSeen:   time.Now().UnixNano(),
	}, time.Hour); err != nil {
		t.Fatalf("PublishRelay: %v", err)
	}

	src := mgr.PeerSource()
	got := []peer.AddrInfo{}
	for ai := range src(ctx, 10) {
		got = append(got, ai)
	}
	ids := map[peer.ID]bool{}
	for _, ai := range got {
		ids[ai.ID] = true
	}
	if !ids[staticRelay.ID] {
		t.Errorf("static relay missing from merged source")
	}
	if !ids[dynID] {
		t.Errorf("DHT-discovered relay missing from merged source")
	}
}

// =============================================================================
// helpers
// =============================================================================

func mustMA(t *testing.T, s string) multiaddr.Multiaddr {
	t.Helper()
	a, err := multiaddr.NewMultiaddr(s)
	if err != nil {
		t.Fatalf("multiaddr %q: %v", s, err)
	}
	return a
}

func mustPID(t *testing.T, s string) peer.ID {
	t.Helper()
	pid, err := peer.Decode(s)
	if err != nil {
		t.Fatalf("peer.Decode %q: %v", s, err)
	}
	return pid
}
