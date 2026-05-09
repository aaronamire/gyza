// Package nat owns NAT traversal for gyza-netd.
//
// Three mechanisms, in priority order:
//
//  1. Direct dial (IPv4/IPv6 + UPnP/NAT-PMP, configured by host.NewHost).
//  2. DCUtR hole-punching — coordinated simultaneous-open through a
//     relay node, upgrading a relay-mediated connection to direct.
//     Wired by libp2p.EnableHolePunching.
//  3. Circuit relay (libp2p circuitv2) — fallback when both peers are
//     behind symmetric NATs that DCUtR can't traverse. Wired by
//     libp2p.EnableAutoRelayWithPeerSource on the client side and
//     libp2p.EnableRelayService on the (opt-in) relay side.
//
// One idiomatic deviation from the Phase 3 Session 3 spec: those
// mechanisms must be configured at libp2p.New() time, not bolted on
// afterward. The Manager therefore exposes LibP2POptions() returning
// the option set that host.NewHost folds in. After the host is built
// and the DHT is up, the caller injects the DHT via SetDHT so the
// AutoRelay peer source can populate from /gyza/relays.
//
// What ConnectWithNAT looks like in practice: just host.Connect with a
// timeout. libp2p's hole-punch service intercepts dials whose only
// known addresses are circuit-relay multiaddrs, drives DCUtR, and
// upgrades to a direct connection if it succeeds. The "try direct →
// DCUtR → relay" staged-dial logic the Phase 3 spec describes is the
// libp2p internal behavior; reimplementing it on top would duplicate
// machinery that already exists.
package nat

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"gyza/netd/internal/dht"
	pb "gyza/netd/internal/grpc/proto"

	libp2p "github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	basichost "github.com/libp2p/go-libp2p/p2p/host/basic"
	"github.com/multiformats/go-multiaddr"
	manet "github.com/multiformats/go-multiaddr/net"
)

// Config governs which NAT subsystems are enabled. Plain-Go pattern: a
// zero-value Config disables everything (useful in unit tests that
// construct hosts without NAT noise).
type Config struct {
	// EnableHolePunching switches on DCUtR. Practically always true for
	// real deployments; left configurable so tests don't pay the
	// startup cost.
	EnableHolePunching bool

	// EnableAutoRelay turns on the AutoRelay subsystem so this host can
	// reserve circuit-relay slots when it can't be reached directly.
	// Without this, NATed nodes are unreachable from the internet.
	EnableAutoRelay bool

	// EnableRelayService advertises this node as a circuit relay (i.e.
	// other NATed nodes can use *us* as their relay). Resource-intensive;
	// strict opt-in via configuration.
	EnableRelayService bool

	// StaticRelays seed the AutoRelay peer source even before the DHT
	// has discovered any. Useful for the Phase 3 demo (each side
	// hardcodes the other's relay) and for production deployments
	// against Gyza-owned bootstrap relays.
	StaticRelays []peer.AddrInfo

	// AdvertiseInterval — how often AdvertiseAsRelay re-publishes the
	// /gyza/relays record. 0 disables the advertise loop.
	AdvertiseInterval time.Duration

	// RelayStaleAfter is the freshness window applied when reading the
	// relay list from the DHT. Entries older than now-RelayStaleAfter
	// are filtered out. Default: 2 × AdvertiseInterval.
	RelayStaleAfter time.Duration
}

// Manager wraps a NAT-enabled libp2p host and the DHT-backed relay
// directory. Construct via NewManager — never the zero value, since
// the relay peer source has internal state.
type Manager struct {
	cfg Config

	// peerSource captures *self so its closure-state pointer stays
	// fresh as the host and DHT come online.
	peerSource *relayPeerSource

	mu   sync.RWMutex
	host host.Host
	dht  *dht.GyzaDHT

	advertiseStop chan struct{}
}

// NewManager constructs a Manager and pre-builds the relay peer source.
// Returns the manager and the libp2p.Option list to fold into
// host.NewHost. Wire ordering (which the caller must respect):
//
//	mgr := nat.NewManager(cfg)
//	h := host.NewHost(host.Config{ ExtraOptions: mgr.LibP2POptions() ... })
//	mgr.SetHost(h)
//	dht := dht.NewGyzaDHT(ctx, h, ...)
//	mgr.SetDHT(dht)
//
// Skipping any of these leaves the relay machinery half-wired: AutoRelay
// without a host has no reservations to manage; without a DHT it falls
// back to StaticRelays only.
func NewManager(cfg Config) *Manager {
	if cfg.RelayStaleAfter == 0 && cfg.AdvertiseInterval > 0 {
		cfg.RelayStaleAfter = 2 * cfg.AdvertiseInterval
	}
	m := &Manager{
		cfg:           cfg,
		peerSource:    &relayPeerSource{static: cfg.StaticRelays},
		advertiseStop: make(chan struct{}),
	}
	return m
}

// LibP2POptions returns the libp2p options the host must be constructed
// with. Order matters: host construction merges these after the base
// options, and EnableAutoRelayWithPeerSource needs to see the peer
// source closure rebuild every host start.
func (m *Manager) LibP2POptions() []libp2p.Option {
	var opts []libp2p.Option
	if m.cfg.EnableHolePunching {
		opts = append(opts, libp2p.EnableHolePunching())
	}
	if m.cfg.EnableAutoRelay {
		opts = append(opts, libp2p.EnableAutoRelayWithPeerSource(m.peerSource.Source))
	}
	if m.cfg.EnableRelayService {
		opts = append(opts, libp2p.EnableRelayService())
	}
	return opts
}

// SetHost binds the constructed libp2p host to this manager. Idempotent;
// later calls overwrite the previous host (useful in tests, no-op in
// production where host is built exactly once).
func (m *Manager) SetHost(h host.Host) {
	m.mu.Lock()
	m.host = h
	m.mu.Unlock()
}

// SetDHT injects the GyzaDHT after it's been initialized. Until this is
// called, the relay peer source returns only StaticRelays.
func (m *Manager) SetDHT(d *dht.GyzaDHT) {
	m.mu.Lock()
	m.dht = d
	m.mu.Unlock()
	m.peerSource.SetSource(d, m.cfg.RelayStaleAfter)
}

// PeerSource returns the relay peer-source function. AutoRelay calls
// this internally; we expose it both so tests can drive it directly
// and so external callers (e.g. a CLI "list known relays" command)
// can read the same view AutoRelay sees.
func (m *Manager) PeerSource() func(ctx context.Context, num int) <-chan peer.AddrInfo {
	return m.peerSource.Source
}

// Host returns the bound host (or nil if SetHost hasn't been called).
func (m *Manager) Host() host.Host {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.host
}

// Available reports whether NAT traversal subsystems are enabled in
// this manager's configuration. Surfaced via NodeStatus.
func (m *Manager) Available() bool {
	return m.cfg.EnableHolePunching || m.cfg.EnableAutoRelay || m.cfg.EnableRelayService
}

// ObservedAddr returns the daemon's externally observable multiaddr,
// learned via libp2p's identify exchange and AutoNAT confirmation.
//
// Selection order:
//  1. Confirmed-reachable address (AutoNAT verified).
//  2. Any non-loopback, non-private address from AllAddrs.
//  3. Empty string if nothing public is known yet (newly started node
//     with no peer connections).
//
// Type-asserts the host to *basichost.BasicHost; libp2p's host.Host
// interface doesn't expose ConfirmedAddrs publicly, but every host
// constructed by libp2p.New is a *basichost.BasicHost.
func (m *Manager) ObservedAddr() string {
	h := m.Host()
	if h == nil {
		return ""
	}
	if bh, ok := h.(*basichost.BasicHost); ok {
		reachable, _, _ := bh.ConfirmedAddrs()
		for _, a := range reachable {
			if isPublicAddr(a) {
				return a.String()
			}
		}
		// Fall back to AllAddrs (includes observed but not yet confirmed).
		for _, a := range bh.AllAddrs() {
			if isPublicAddr(a) {
				return a.String()
			}
		}
	}
	// Last resort: the first non-loopback address. Test environments
	// often only have loopback, in which case we return empty.
	for _, a := range h.Addrs() {
		if isPublicAddr(a) {
			return a.String()
		}
	}
	return ""
}

// ConnectWithNAT dials a peer using whatever traversal mechanism is
// available. Direct → DCUtR upgrade-from-relay → circuit relay are all
// driven by libp2p; this method simply applies a timeout.
func (m *Manager) ConnectWithNAT(
	ctx context.Context,
	target peer.AddrInfo,
	timeout time.Duration,
) error {
	h := m.Host()
	if h == nil {
		return errors.New("nat: no host bound")
	}
	if timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	return h.Connect(ctx, target)
}

// AdvertiseAsRelay starts the periodic /gyza/relays publish loop for
// this node. Caller is expected to have set EnableRelayService=true
// and confirmed the node is publicly reachable (via ObservedAddr()).
//
// The loop terminates on context cancel or StopAdvertising; it does
// best-effort republish even when DHT puts fail (single-peer nets,
// transient routing errors), so the local view at least stays warm
// even when no peer can read it.
func (m *Manager) AdvertiseAsRelay(
	ctx context.Context,
	compositorPubkeyHex string,
	logf func(string, ...any),
) {
	if logf == nil {
		logf = func(string, ...any) {}
	}
	if m.cfg.AdvertiseInterval <= 0 {
		logf("[nat] AdvertiseAsRelay called with non-positive interval; skipping")
		return
	}
	go func() {
		// Burst once on startup so peers see us before the first tick.
		m.publishRelayOnce(ctx, compositorPubkeyHex, logf)
		ticker := time.NewTicker(m.cfg.AdvertiseInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-m.advertiseStop:
				return
			case <-ticker.C:
				m.publishRelayOnce(ctx, compositorPubkeyHex, logf)
			}
		}
	}()
}

// StopAdvertising signals the advertise goroutine to exit. Idempotent.
func (m *Manager) StopAdvertising() {
	select {
	case <-m.advertiseStop:
		// already closed
	default:
		close(m.advertiseStop)
	}
}

func (m *Manager) publishRelayOnce(ctx context.Context, compositorPubkey string, logf func(string, ...any)) {
	m.mu.RLock()
	h := m.host
	d := m.dht
	m.mu.RUnlock()
	if h == nil || d == nil {
		return
	}
	addrs := []string{}
	for _, a := range h.Addrs() {
		if isPublicAddr(a) {
			addrs = append(addrs, a.String())
		}
	}
	if len(addrs) == 0 {
		// No public addresses yet — pointless to advertise as relay
		// because nobody can reach us anyway. Try again next tick;
		// observed addresses get added once peers identify with us.
		return
	}
	entry := &pb.RelayEntry{
		PeerId:           h.ID().String(),
		Multiaddrs:       addrs,
		LastSeen:         time.Now().UnixNano(),
		CompositorPubkey: compositorPubkey,
	}
	stale := m.cfg.RelayStaleAfter
	if stale <= 0 {
		stale = 2 * m.cfg.AdvertiseInterval
	}
	if err := d.PublishRelay(ctx, entry, stale); err != nil {
		logf("[nat] PublishRelay: %v", err)
		return
	}
	logf("[nat] advertised as relay (%d addrs)", len(addrs))
}

// FindRelayNodes returns up to `num` known relay AddrInfos, drawing
// from the DHT-stored /gyza/relays list. Static relays from
// cfg.StaticRelays are NOT included here (they're already plumbed
// through the AutoRelay peer source); this method is for callers that
// want the current crowd-sourced relay list directly.
func (m *Manager) FindRelayNodes(ctx context.Context, num int) ([]peer.AddrInfo, error) {
	m.mu.RLock()
	d := m.dht
	stale := m.cfg.RelayStaleAfter
	m.mu.RUnlock()
	if d == nil {
		return nil, nil
	}
	entries, err := d.FindRelays(ctx, num, stale)
	if err != nil {
		return nil, err
	}
	out := make([]peer.AddrInfo, 0, len(entries))
	for _, e := range entries {
		ai, ok := relayEntryToAddrInfo(e)
		if !ok {
			continue
		}
		out = append(out, ai)
	}
	return out, nil
}

// =============================================================================
// relay peer source for libp2p AutoRelay
// =============================================================================

// relayPeerSource is the closure-with-state that AutoRelay calls to
// get relay candidates. We keep static relays separate from DHT-found
// ones so the static set is always available even before the DHT
// finishes bootstrapping.
type relayPeerSource struct {
	mu     sync.RWMutex
	static []peer.AddrInfo
	d      *dht.GyzaDHT
	stale  time.Duration
}

// SetSource is called once the DHT is initialized so subsequent
// AutoRelay queries pick up dynamic relays.
func (s *relayPeerSource) SetSource(d *dht.GyzaDHT, stale time.Duration) {
	s.mu.Lock()
	s.d = d
	s.stale = stale
	s.mu.Unlock()
}

// Source is the autorelay.PeerSource callback. Sends static relays
// first (always available), then any from the DHT, until num is
// reached or the channel is closed.
//
// AutoRelay reads from this channel until it has enough candidates or
// it closes; the producer must close the channel.
func (s *relayPeerSource) Source(ctx context.Context, num int) <-chan peer.AddrInfo {
	out := make(chan peer.AddrInfo, num)
	go func() {
		defer close(out)
		s.mu.RLock()
		static := s.static
		d := s.d
		stale := s.stale
		s.mu.RUnlock()

		sent := 0
		for _, p := range static {
			select {
			case out <- p:
				sent++
				if sent >= num {
					return
				}
			case <-ctx.Done():
				return
			}
		}
		if d == nil {
			return
		}
		entries, err := d.FindRelays(ctx, num-sent, stale)
		if err != nil {
			return
		}
		for _, e := range entries {
			ai, ok := relayEntryToAddrInfo(e)
			if !ok {
				continue
			}
			select {
			case out <- ai:
				sent++
				if sent >= num {
					return
				}
			case <-ctx.Done():
				return
			}
		}
	}()
	return out
}

// =============================================================================
// helpers
// =============================================================================

func relayEntryToAddrInfo(e *pb.RelayEntry) (peer.AddrInfo, bool) {
	if e == nil || e.PeerId == "" {
		return peer.AddrInfo{}, false
	}
	pid, err := peer.Decode(e.PeerId)
	if err != nil {
		return peer.AddrInfo{}, false
	}
	addrs := make([]multiaddr.Multiaddr, 0, len(e.Multiaddrs))
	for _, s := range e.Multiaddrs {
		a, err := multiaddr.NewMultiaddr(s)
		if err != nil {
			continue
		}
		addrs = append(addrs, a)
	}
	if len(addrs) == 0 {
		return peer.AddrInfo{}, false
	}
	return peer.AddrInfo{ID: pid, Addrs: addrs}, true
}

// isPublicAddr returns true for IPv4/IPv6 multiaddrs that look
// internet-reachable. Conservative: rejects loopback, link-local,
// and RFC1918 / RFC4193 private ranges. We use multiaddr-net's
// IsThinWaist + IsPublicAddr where available for correctness across
// IP versions.
func isPublicAddr(a multiaddr.Multiaddr) bool {
	if !manet.IsThinWaist(a) {
		// Not an IP-based multiaddr (e.g. /p2p-circuit). Excluded by
		// definition: relay loops aren't useful.
		return false
	}
	if manet.IsIPLoopback(a) {
		return false
	}
	if manet.IsIPUnspecified(a) {
		return false
	}
	if manet.IsPrivateAddr(a) {
		return false
	}
	return manet.IsPublicAddr(a)
}

// observedFromString lets test code synthesize an AddrInfo. Not part of
// the production code path.
func ObservedFromString(s string) (peer.AddrInfo, error) {
	a, err := multiaddr.NewMultiaddr(s)
	if err != nil {
		return peer.AddrInfo{}, err
	}
	ai, err := peer.AddrInfoFromP2pAddr(a)
	if err != nil {
		return peer.AddrInfo{}, fmt.Errorf("addrinfo from %s: %w", s, err)
	}
	return *ai, nil
}
