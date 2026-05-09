// Package discovery provides LAN peer discovery via mDNS for gyza-netd.
//
// mDNS broadcasts a service tag over UDP multicast on the local network;
// any other gyza-netd on the same LAN sees the broadcast, picks up the
// peer's PeerID + multiaddrs, and triggers HandlePeerFound on its
// notifee. We respond by Connect()-ing the peer through the libp2p host,
// which in turn adds them to the Kademlia routing table — so a freshly
// started node on the same LAN ends up DHT-connected without the user
// configuring any bootstrap multiaddr.
//
// Why a Gyza-specific service tag: libp2p's mDNS uses the tag as the
// service-name component of the rendezvous query. Two unrelated libp2p
// apps on the same LAN with different tags ignore each other. Using
// "gyza-mdns-v1" keeps Gyza off random apps' rendezvous queries and
// vice-versa.
//
// Failure modes that are silently OK:
//   - No multicast on the network: mDNS service simply finds nothing.
//   - Peer found but Connect fails (firewalled, NAT timeout): we log and
//     skip; the peer will be retried on the next mDNS announce cycle.
//   - Discovering ourselves: we ignore self.ID() in HandlePeerFound.
package discovery

import (
	"context"
	"sync/atomic"

	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/p2p/discovery/mdns"
)

// ServiceName is the mDNS rendezvous tag broadcast by every gyza-netd.
// Bumping this string is a hard fork of LAN auto-discovery — old nodes
// won't see new ones and vice-versa. Keep it stable across Phase 3.
const ServiceName = "gyza-mdns-v1"

// MDNSDiscovery wires libp2p's mDNS service to a peer-connecting notifee.
// The whole package surface is one constructor, one Close, and one stat
// counter (peers-found) for the gRPC observability surface.
type MDNSDiscovery struct {
	svc      mdns.Service
	notifee  *connectNotifee
}

// connectNotifee handles each HandlePeerFound by dialing the discovered
// peer through the libp2p host. We don't block the mDNS goroutine on the
// dial — Connect can take a few seconds and we don't want to drop
// subsequent announces while one is in flight.
type connectNotifee struct {
	ctx        context.Context
	host       host.Host
	logf       func(string, ...any)
	peersFound atomic.Uint64
}

// HandlePeerFound is called by libp2p's mDNS implementation for every
// peer announce we observe. We filter self and dial the rest.
func (n *connectNotifee) HandlePeerFound(pi peer.AddrInfo) {
	if pi.ID == n.host.ID() {
		return
	}
	n.peersFound.Add(1)
	n.logf("[mdns] discovered peer %s (%d addrs)", pi.ID, len(pi.Addrs))

	// Off the mDNS goroutine — Connect can block for several seconds on
	// QUIC handshake / NAT timeout. Don't starve subsequent announces.
	go func() {
		if err := n.host.Connect(n.ctx, pi); err != nil {
			n.logf("[mdns] connect %s failed: %v", pi.ID, err)
			return
		}
		n.logf("[mdns] connected to %s", pi.ID)
	}()
}

// NewMDNSDiscovery constructs and starts the mDNS service. Returns the
// discovery handle; caller is expected to Close() it on shutdown so the
// multicast socket is released.
//
// logf may be nil (a no-op logger is substituted).
func NewMDNSDiscovery(ctx context.Context, h host.Host, logf func(string, ...any)) (*MDNSDiscovery, error) {
	if logf == nil {
		logf = func(string, ...any) {}
	}
	n := &connectNotifee{
		ctx:  ctx,
		host: h,
		logf: logf,
	}
	svc := mdns.NewMdnsService(h, ServiceName, n)
	if err := svc.Start(); err != nil {
		return nil, err
	}
	logf("[mdns] service started (tag=%q)", ServiceName)
	return &MDNSDiscovery{svc: svc, notifee: n}, nil
}

// PeersFound returns the running tally of unique mDNS announces handled.
// This is a simple counter — duplicates from re-announces are counted
// each time. Surfaced primarily for diagnostics in NodeStatus.
func (d *MDNSDiscovery) PeersFound() uint64 {
	if d == nil {
		return 0
	}
	return d.notifee.peersFound.Load()
}

// Close tears down the mDNS service. Idempotent: safe to call after a
// failed Start or twice. Returns the underlying Close error if any.
func (d *MDNSDiscovery) Close() error {
	if d == nil || d.svc == nil {
		return nil
	}
	return d.svc.Close()
}
