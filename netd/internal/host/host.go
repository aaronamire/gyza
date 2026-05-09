// Package host wraps libp2p host construction with Gyza's chosen
// transport stack: QUIC over UDP for the wire, Noise for AEAD security
// using the compositor Ed25519 key as identity, Yamux as the stream
// multiplexer. NAT port mapping (UPnP / NAT-PMP) is enabled
// opportunistically; the full NAT story (DCUtR, autorelay) lives in
// internal/nat and is wired in Session 3.
package host

import (
	"context"
	"fmt"

	"gyza/netd/internal/identity"

	libp2p "github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/p2p/muxer/yamux"
	"github.com/libp2p/go-libp2p/p2p/security/noise"
	libp2pquic "github.com/libp2p/go-libp2p/p2p/transport/quic"
	"github.com/multiformats/go-multiaddr"
)

// Config holds the parameters NewHost consumes. Caller is responsible
// for tilde-expanding any user paths before constructing this.
type Config struct {
	Identity       *identity.Identity
	ListenPort     int
	BootstrapPeers []string // multiaddr strings; may be empty

	// ExtraOptions are appended after the base option set. Used by the
	// NAT manager to wire EnableHolePunching, EnableAutoRelayWithPeerSource,
	// and EnableRelayService, which must be configured at host
	// construction (not bolted on afterwards). Callers that don't need
	// them leave this nil.
	ExtraOptions []libp2p.Option
}

// NewHost spins up a libp2p host bound to the configured QUIC port on
// both IPv4 and IPv6. The compositor key from cfg.Identity drives both
// the Ed25519 PeerID and the Noise handshake — same key, two layers.
//
// Returned host is ready to listen and dial; the caller is expected to
// call host.Close() on shutdown to release the listening sockets.
func NewHost(_ context.Context, cfg Config) (host.Host, error) {
	if cfg.Identity == nil {
		return nil, fmt.Errorf("host: identity is required")
	}
	if cfg.ListenPort < 0 || cfg.ListenPort > 65535 {
		return nil, fmt.Errorf("host: invalid listen port %d", cfg.ListenPort)
	}

	v4 := fmt.Sprintf("/ip4/0.0.0.0/udp/%d/quic-v1", cfg.ListenPort)
	v6 := fmt.Sprintf("/ip6/::/udp/%d/quic-v1", cfg.ListenPort)

	opts := []libp2p.Option{
		libp2p.Identity(cfg.Identity.PrivKey),
		libp2p.ListenAddrStrings(v4, v6),
		libp2p.Security(noise.ID, noise.New),
		libp2p.Muxer("/yamux/1.0.0", yamux.DefaultTransport),
		libp2p.Transport(libp2pquic.NewTransport),
		// UPnP / NAT-PMP — best-effort. Gives us an external port on
		// home routers; corporate firewalls fall through to DCUtR / relay
		// configured via cfg.ExtraOptions.
		libp2p.NATPortMap(),
	}
	opts = append(opts, cfg.ExtraOptions...)

	h, err := libp2p.New(opts...)
	if err != nil {
		return nil, fmt.Errorf("libp2p.New: %w", err)
	}
	return h, nil
}

// ConnectBootstrap dials each bootstrap multiaddr in parallel. Returns
// the count of successful connections. Failures are non-fatal — a node
// that can reach even one bootstrap peer can subsequently expand its
// routing table via DHT lookup.
func ConnectBootstrap(
	ctx context.Context, h host.Host, addrs []string,
	logf func(string, ...any),
) int {
	if logf == nil {
		logf = func(string, ...any) {}
	}
	var ok int
	for _, s := range addrs {
		ma, err := multiaddr.NewMultiaddr(s)
		if err != nil {
			logf("[bootstrap] bad multiaddr %q: %v", s, err)
			continue
		}
		info, err := peer.AddrInfoFromP2pAddr(ma)
		if err != nil {
			logf("[bootstrap] addr-info %q: %v", s, err)
			continue
		}
		if err := h.Connect(ctx, *info); err != nil {
			logf("[bootstrap] connect %s: %v", info.ID, err)
			continue
		}
		ok++
		logf("[bootstrap] connected to %s", info.ID)
	}
	return ok
}

// AddrStrings returns the host's current listen multiaddrs as strings,
// ready for inclusion in NodeInfo.
func AddrStrings(h host.Host) []string {
	addrs := h.Addrs()
	out := make([]string, 0, len(addrs))
	for _, a := range addrs {
		out = append(out, a.String())
	}
	return out
}

// DefaultBootstrapPeers — sentinel values used when no --bootstrap is
// passed. Phase 3 Sessions 1-7 default to none (the demos either
// connect peers directly or expect the user to point at a private
// dev bootstrap). Production deployment of Phase 3 will populate
// this with Gyza-controlled bootstrap nodes whose keys are pinned.
//
// Note: the IPFS bootstrap nodes mentioned in the original Phase-3
// spec WILL NOT work here — we use ProtocolPrefix("/gyza/1.0") in the
// DHT, which means our Kademlia traffic is on a different protocol ID
// than IPFS, and IPFS nodes will not respond to our kademlia queries.
// Riding the IPFS DHT would require dropping the prefix, which would
// also leak Gyza records into the public DHT. Not a tradeoff worth
// making for "easier dev".
var DefaultBootstrapPeers = []string{}
