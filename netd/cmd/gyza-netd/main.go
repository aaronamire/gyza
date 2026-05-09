// Command gyza-netd is the long-running Gyza network daemon.
//
// One process per Gyza node. Owns the libp2p host, the Kademlia DHT,
// NAT traversal, and the cross-cluster gossip topics. Exposes a gRPC
// API over a Unix socket so the Python Gyza stack can issue control
// commands without speaking libp2p directly.
//
// Lifecycle:
//
//	parse flags
//	load identity from --key-path           (Session 1)
//	init libp2p host + DHT                  (Session 2)
//	init NAT traversal                      (Session 3)
//	init gossipsub                          (Session 4)
//	register all five gRPC services
//	start Unix-socket listener at --socket-path
//	wait for SIGINT/SIGTERM
//	on signal: close DHT, close host, stop gRPC, remove socket, exit 0
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"gyza/netd/internal/capability"
	"gyza/netd/internal/dht"
	"gyza/netd/internal/discovery"
	"gyza/netd/internal/gossip"
	grpcsrv "gyza/netd/internal/grpc"
	"gyza/netd/internal/host"
	"gyza/netd/internal/identity"
	"gyza/netd/internal/message"
	"gyza/netd/internal/nat"

	kaddht "github.com/libp2p/go-libp2p-kad-dht"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/multiformats/go-multiaddr"
)

// stringSliceFlag accepts a comma-separated --bootstrap value.
type stringSliceFlag []string

func (s *stringSliceFlag) String() string { return strings.Join(*s, ",") }
func (s *stringSliceFlag) Set(v string) error {
	if v == "" {
		return nil
	}
	for _, part := range strings.Split(v, ",") {
		p := strings.TrimSpace(part)
		if p != "" {
			*s = append(*s, p)
		}
	}
	return nil
}

func main() {
	var (
		socketPath = flag.String(
			"socket-path", "~/.gyza/netd.sock",
			"Unix socket the gRPC server listens on")
		listenPort = flag.Int(
			"listen-port", 7749,
			"QUIC listen port for libp2p")
		keyPath = flag.String(
			"key-path", "~/.gyza/compositor.key",
			"path to the 32-byte compositor master seed")
		logLevel = flag.String(
			"log-level", "info",
			"log level: debug | info | warn | error")
		mdnsEnabled = flag.Bool(
			"mdns", true,
			"enable mDNS LAN auto-discovery (Phase 3 Session 2)")
		republishInterval = flag.Duration(
			"republish-interval", 30*time.Minute,
			"how often to re-publish local agent ads to the DHT; ≤0 disables")
		holePunch = flag.Bool(
			"holepunch", true,
			"enable DCUtR hole-punching (Phase 3 Session 3)")
		autoRelay = flag.Bool(
			"autorelay", true,
			"enable AutoRelay client (use circuit relays as a fallback when NATed)")
		enableRelaySvc = flag.Bool(
			"enable-relay-service", false,
			"opt in to running a circuit-relay v2 service for other peers (resource intensive; recommended only for nodes with public IP and high uptime)")
		relayAdvertiseInterval = flag.Duration(
			"relay-advertise-interval", 30*time.Minute,
			"how often to re-advertise this node's relay availability to /gyza/relays; only used when --enable-relay-service is set")
		bootstrap   stringSliceFlag
		staticRelay stringSliceFlag
	)
	flag.Var(&bootstrap, "bootstrap",
		"bootstrap peer multiaddrs (comma-separated; defaults to public IPFS bootstrap until Phase 3 productionizes Gyza-owned ones)")
	flag.Var(&staticRelay, "static-relay",
		"hardcoded relay peer multiaddrs (comma-separated). Surfaces immediately to AutoRelay before the DHT discovers any.")
	flag.Parse()

	logger := newLogger(*logLevel)
	logger.Info("gyza-netd starting (Phase 3 Session 5)")
	logger.Info("    socket-path     = %s", *socketPath)
	logger.Info("    listen-port     = %d", *listenPort)
	logger.Info("    key-path        = %s", *keyPath)
	logger.Info("    bootstrap       = %d entries", len(bootstrap))
	logger.Info("    static-relay    = %d entries", len(staticRelay))
	logger.Info("    hole-punching   = %t", *holePunch)
	logger.Info("    auto-relay      = %t", *autoRelay)
	logger.Info("    relay-service   = %t", *enableRelaySvc)

	resolvedKey, err := expandUser(*keyPath)
	if err != nil {
		logger.Fatal("expand key path: %v", err)
	}
	id, err := identity.LoadIdentity(resolvedKey)
	if err != nil {
		logger.Fatal("load identity: %v", err)
	}
	logger.Info("[identity] peer_id=%s", id.PeerID.String())
	logger.Info("[identity] compositor_pubkey=%s", id.PubKeyHex)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Resolve --static-relay multiaddrs into peer.AddrInfos before host
	// construction — AutoRelay needs them at the moment libp2p.New runs.
	// Bad entries are logged and skipped rather than fatal: we'd rather
	// boot with a partial relay set than refuse to start.
	staticRelayPeers := parseRelayMultiaddrs(staticRelay, logger)

	// NAT manager: configures DCUtR + AutoRelay options that must be
	// passed to libp2p.New(). After the host is up we'll bind it back.
	natMgr := nat.NewManager(nat.Config{
		EnableHolePunching: *holePunch,
		EnableAutoRelay:    *autoRelay,
		EnableRelayService: *enableRelaySvc,
		StaticRelays:       staticRelayPeers,
		AdvertiseInterval:  *relayAdvertiseInterval,
	})

	// Real libp2p host with QUIC + Noise + Yamux + UPnP/NAT-PMP, plus
	// DCUtR hole-punching and AutoRelay client when configured. The
	// NAT-related libp2p options come from natMgr.LibP2POptions().
	h, err := host.NewHost(ctx, host.Config{
		Identity:       id,
		ListenPort:     *listenPort,
		BootstrapPeers: bootstrap,
		ExtraOptions:   natMgr.LibP2POptions(),
	})
	if err != nil {
		logger.Fatal("[host] init: %v", err)
	}
	natMgr.SetHost(h)
	logger.Info("[host] peer_id=%s", h.ID())
	for _, a := range host.AddrStrings(h) {
		logger.Info("[host] listen %s/p2p/%s", a, h.ID())
	}
	if natMgr.Available() {
		logger.Info("[nat] hole-punching=%t auto-relay=%t relay-service=%t",
			*holePunch, *autoRelay, *enableRelaySvc)
	}

	// Connect to bootstrap peers (if any). Failures here are non-fatal:
	// the daemon is still usable for direct-connect peers and as an
	// inert DHT node; Session 3's DCUtR can also seed the routing
	// table from observed addresses later.
	if len(bootstrap) > 0 {
		ok := host.ConnectBootstrap(ctx, h, bootstrap, logger.Info)
		logger.Info("[host] bootstrap: connected to %d/%d peers", ok, len(bootstrap))
	}

	// Kademlia DHT with /gyza/1.0 protocol prefix — segregated from
	// public IPFS, even when riding the same wire transport.
	gdht, err := dht.NewGyzaDHT(ctx, h, kaddht.ModeAuto)
	if err != nil {
		logger.Fatal("[dht] init: %v", err)
	}
	logger.Info("[dht] initialized (mode=auto, prefix=/gyza/1.0)")
	natMgr.SetDHT(gdht)

	// If the operator opted in to running a circuit relay, advertise
	// our reachability under /gyza/relays so other nodes can find us.
	// publishRelayOnce is a no-op if the host has no public addresses.
	if *enableRelaySvc {
		natMgr.AdvertiseAsRelay(ctx, id.PubKeyHex, logger.Info)
		logger.Info("[nat] relay advertise loop running every %s",
			*relayAdvertiseInterval)
	}

	// Periodic re-publication of every local agent so DHT records don't
	// expire under their TTL. interval ≤ 0 disables.
	gdht.StartRepublishLoop(ctx, *republishInterval)
	if *republishInterval > 0 {
		logger.Info("[dht] republish loop running every %s", *republishInterval)
	}

	// Cross-cluster blackboard gossip. Always-on: until JoinProject is
	// called over gRPC, the manager has zero topics and zero overhead.
	gossipMgr, err := gossip.NewManager(ctx, h, id, logger.Info)
	if err != nil {
		logger.Fatal("[gossip] init: %v", err)
	}
	logger.Info("[gossip] gossipsub initialized")

	// Capability / sybil-resistance manager. Stateless cryptographic
	// surface backed by the compositor identity; no init cost.
	capMgr := capability.NewChallengeManager(id.PubKeyHex, id)
	logger.Info("[capability] challenge manager ready")

	// Point-to-point message manager. Registers a libp2p stream
	// handler at /gyza/message/1.0.0 immediately; subscriber fan-out
	// routes incoming messages to gRPC SubscribeMessages callers.
	msgMgr := message.NewManager(h, logger.Info)
	logger.Info("[message] stream protocol %s registered", message.ProtocolID)

	// Optional mDNS LAN auto-discovery — peers on the same broadcast
	// domain find and connect to each other without configured bootstrap
	// multiaddrs. Failure to start (no multicast, restricted sandbox) is
	// logged but not fatal: the daemon still works for direct-connect
	// and DHT-via-bootstrap deployments.
	var mdnsSvc *discovery.MDNSDiscovery
	if *mdnsEnabled {
		mdnsSvc, err = discovery.NewMDNSDiscovery(ctx, h, logger.Info)
		if err != nil {
			logger.Info("[mdns] disabled: %v", err)
			mdnsSvc = nil
		}
	}

	server := grpcsrv.NewNetdServer(id, h, gdht, natMgr, gossipMgr, capMgr, msgMgr)
	srv, err := grpcsrv.StartGRPCServer(*socketPath, server, func(format string, args ...any) {
		logger.Info(format, args...)
	})
	if err != nil {
		_ = gdht.Close()
		_ = h.Close()
		logger.Fatal("start grpc server: %v", err)
	}

	sigC := make(chan os.Signal, 1)
	signal.Notify(sigC, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigC
	logger.Info("[main] received %s; shutting down", sig)

	// Tear-down order: gRPC first (stops accepting new requests, so no
	// new SubscribeDeltas streams open), then mDNS, then NAT advertise
	// loop, then gossip (closes subscriber channels — in-flight Send
	// calls fail cleanly), then DHT, then host. Cancelling ctx wakes
	// blocked DHT ops, republish-loop ticks, relay-advertise ticks,
	// and gossip receive loops.
	srv.Stop()
	cancel()
	natMgr.StopAdvertising()
	_ = msgMgr.Close()
	_ = mdnsSvc.Close()
	_ = gossipMgr.Close()
	_ = gdht.Close()
	_ = h.Close()

	logger.Info("[main] clean exit")
}

// ---------------------------------------------------------------------------
// Tiny logger — the daemon only needs leveled prefixed lines, not a full
// logging package. Avoids pulling in zap/logrus for what is, in Session 1,
// six lines of output total.
// ---------------------------------------------------------------------------

type logger struct {
	debug bool
}

func newLogger(level string) *logger {
	return &logger{debug: strings.EqualFold(level, "debug")}
}

func (l *logger) Info(format string, args ...any) {
	log.Printf("INFO  "+format, args...)
}

func (l *logger) Debug(format string, args ...any) {
	if !l.debug {
		return
	}
	log.Printf("DEBUG "+format, args...)
}

func (l *logger) Fatal(format string, args ...any) {
	log.Printf("FATAL "+format, args...)
	os.Exit(1)
}

// parseRelayMultiaddrs decodes --static-relay multiaddr strings into
// peer.AddrInfo values. Bad entries are logged and dropped — boot
// continues with the remaining good ones.
func parseRelayMultiaddrs(addrs []string, logger *logger) []peer.AddrInfo {
	out := make([]peer.AddrInfo, 0, len(addrs))
	for _, s := range addrs {
		ma, err := multiaddr.NewMultiaddr(s)
		if err != nil {
			logger.Info("[nat] skipping bad static-relay multiaddr %q: %v", s, err)
			continue
		}
		ai, err := peer.AddrInfoFromP2pAddr(ma)
		if err != nil {
			logger.Info("[nat] static-relay %q: %v", s, err)
			continue
		}
		out = append(out, *ai)
	}
	return out
}

func expandUser(p string) (string, error) {
	if len(p) == 0 || p[0] != '~' {
		return p, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	if p == "~" {
		return home, nil
	}
	if len(p) > 1 && p[1] == '/' {
		return home + p[1:], nil
	}
	return p, fmt.Errorf("unsupported ~ form: %q", p)
}
