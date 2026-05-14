// Package bootstrap resolves the set of bootstrap peers a gyza-netd
// daemon should connect to on startup.
//
// Two sources, merged with the DNS-anchored set taking precedence:
//
//  1. DNS TXT records at _dnsaddr.<domain> (e.g., _dnsaddr.gyza.network).
//     Each TXT record is "dnsaddr=<multiaddr>" where <multiaddr> is a
//     concrete /ip4/.../udp/.../quic-v1/p2p/<peer-id> string. This is
//     the dnsaddr convention used by libp2p / IPFS bootstrap.
//
//     DNS allows rotation: we can change the set of bootstrap nodes
//     without rebuilding the daemon binary. New nodes appear on the
//     next daemon restart (or sooner if we add periodic re-resolution).
//
//  2. FallbackPeers — a hardcoded compile-time list of peer multiaddrs.
//     Used when DNS fails (transient outage, hostile resolver) and as
//     belt-and-braces if all DNS records are wiped maliciously.
//     Each entry pubkey-pins the peer via /p2p/<peer-id>; an attacker
//     hijacking the IP cannot impersonate the peer without its key.
//
// Failure mode: if BOTH sources are empty, Resolve returns []. The
// caller (daemon main) treats that as "no bootstrap configured" — the
// node still runs as a DHT island until it learns peers via mDNS or
// direct connect.
//
// The DNS resolver is injected via a Resolver interface so tests can
// substitute a fake. Default uses net.DefaultResolver.
package bootstrap

import (
	"context"
	"fmt"
	"net"
	"strings"
	"time"

	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/multiformats/go-multiaddr"
)

const (
	// DefaultDomain is the production DNS domain. Override via
	// --bootstrap-domain on the daemon command line, or set
	// GYZA_BOOTSTRAP_DOMAIN in the environment for tests.
	DefaultDomain = "gyza.network"

	// dnsTimeout caps a single TXT lookup. We don't want a slow
	// resolver to delay daemon startup; the fallback set picks up
	// the slack.
	dnsTimeout = 5 * time.Second

	// txtPrefix is what every dnsaddr TXT record starts with.
	txtPrefix = "dnsaddr="
)

// FallbackPeers — production bootstrap peer multiaddrs baked into the
// daemon binary at release time. Each entry pubkey-pins the peer via
// the trailing /p2p/<peer-id>.
//
// Update flow: when bootstrap nodes rotate, regenerate this list from
// the current _dnsaddr.gyza.network TXT records and tag a new daemon
// release. Until then, the DNS set is authoritative; this list catches
// the edge case where DNS itself is unreachable.
//
// Empty during pre-bootstrap-node phase. The daemon logs a warning
// if Resolve falls back to this empty set and the operator hasn't
// passed --bootstrap explicitly.
var FallbackPeers = []string{
	// EU — Frankfurt (Vultr).
	"/ip4/45.77.55.27/udp/7749/quic-v1/p2p/12D3KooWCfGdkEXZvgPMCfGD3K8xhdxpMHvbWJhUknEs4zRNHAAp",
	// US — New Jersey (Vultr).
	"/ip4/155.138.217.81/udp/7749/quic-v1/p2p/12D3KooWSwDNtty5Vgps452oKeVyUyn7tHyFnCks31xTwgYMPq8W",
	// AP — Singapore (Vultr).
	"/ip4/45.76.150.156/udp/7749/quic-v1/p2p/12D3KooWM8Jeu6p68dtavDHR7YSZGpBUN8cN26oPmRA8Fb1EYYjG",
}

// Resolver is the subset of net.Resolver we depend on. Tests inject
// a fake implementation.
type Resolver interface {
	LookupTXT(ctx context.Context, name string) ([]string, error)
}

// defaultResolver lazily wraps the Go stdlib resolver.
type defaultResolver struct{}

func (defaultResolver) LookupTXT(ctx context.Context, name string) ([]string, error) {
	return net.DefaultResolver.LookupTXT(ctx, name)
}

// DefaultResolver returns the production resolver.
func DefaultResolver() Resolver { return defaultResolver{} }

// Resolve returns the merged set of bootstrap peer.AddrInfos to dial.
//
// Steps:
//  1. Look up _dnsaddr.<domain> TXT records and parse each "dnsaddr=..."
//     entry into a peer.AddrInfo.
//  2. Parse each FallbackPeers entry.
//  3. Dedup by peer.ID, unioning the multiaddrs for any peer that
//     appears in both sources.
//
// `domain` may be empty — in which case step 1 is skipped. `logf` may
// be nil (silent).
//
// `r` is the DNS resolver. Pass DefaultResolver() in production. Tests
// inject a fake.
//
// The function never returns an error; DNS failures + parse failures
// are logged and the caller proceeds with whatever survives.
func Resolve(
	ctx context.Context,
	r Resolver,
	domain string,
	logf func(string, ...any),
) []peer.AddrInfo {
	if logf == nil {
		logf = func(string, ...any) {}
	}
	if r == nil {
		r = DefaultResolver()
	}

	// peer.ID -> AddrInfo accumulator. We union Addrs for duplicates.
	merged := make(map[peer.ID]peer.AddrInfo)

	add := func(ai *peer.AddrInfo) {
		if existing, ok := merged[ai.ID]; ok {
			// Union the address sets, skipping duplicates by string form.
			seen := make(map[string]struct{}, len(existing.Addrs))
			for _, a := range existing.Addrs {
				seen[a.String()] = struct{}{}
			}
			for _, a := range ai.Addrs {
				if _, dup := seen[a.String()]; dup {
					continue
				}
				existing.Addrs = append(existing.Addrs, a)
				seen[a.String()] = struct{}{}
			}
			merged[ai.ID] = existing
			return
		}
		merged[ai.ID] = *ai
	}

	// 1. DNS-anchored peers.
	if domain != "" {
		dnsAddrs, err := resolveDNS(ctx, r, domain)
		if err != nil {
			logf("[bootstrap] DNS resolution of _dnsaddr.%s failed: %v "+
				"(falling back to compiled-in peers)", domain, err)
		} else {
			for i := range dnsAddrs {
				add(&dnsAddrs[i])
			}
			logf("[bootstrap] DNS resolved %d peer(s) from _dnsaddr.%s",
				len(dnsAddrs), domain)
		}
	}

	// 2. Hardcoded fallback set.
	for _, s := range FallbackPeers {
		ai, err := parseMultiaddrToAddrInfo(s)
		if err != nil {
			logf("[bootstrap] bad fallback multiaddr %q: %v", s, err)
			continue
		}
		add(ai)
	}

	if len(merged) == 0 {
		logf("[bootstrap] no peers resolved (DNS empty + FallbackPeers empty)")
	}

	out := make([]peer.AddrInfo, 0, len(merged))
	for _, ai := range merged {
		out = append(out, ai)
	}
	return out
}

// ResolveWithExtras is like Resolve but also accepts user-supplied
// multiaddr strings (from --bootstrap). User-supplied entries are
// merged in alongside DNS + fallback, with the same dedup rules.
func ResolveWithExtras(
	ctx context.Context,
	r Resolver,
	domain string,
	extras []string,
	logf func(string, ...any),
) []peer.AddrInfo {
	if logf == nil {
		logf = func(string, ...any) {}
	}
	base := Resolve(ctx, r, domain, logf)

	merged := make(map[peer.ID]peer.AddrInfo, len(base)+len(extras))
	for i := range base {
		merged[base[i].ID] = base[i]
	}

	for _, s := range extras {
		ai, err := parseMultiaddrToAddrInfo(s)
		if err != nil {
			logf("[bootstrap] bad --bootstrap entry %q: %v", s, err)
			continue
		}
		if existing, ok := merged[ai.ID]; ok {
			seen := make(map[string]struct{}, len(existing.Addrs))
			for _, a := range existing.Addrs {
				seen[a.String()] = struct{}{}
			}
			for _, a := range ai.Addrs {
				if _, dup := seen[a.String()]; dup {
					continue
				}
				existing.Addrs = append(existing.Addrs, a)
				seen[a.String()] = struct{}{}
			}
			merged[ai.ID] = existing
		} else {
			merged[ai.ID] = *ai
		}
	}

	out := make([]peer.AddrInfo, 0, len(merged))
	for _, ai := range merged {
		out = append(out, ai)
	}
	return out
}

// resolveDNS does one TXT lookup and parses any dnsaddr= entries.
// Returns the parsed peers; unparseable entries are silently dropped
// (logged by Resolve's caller if needed).
func resolveDNS(ctx context.Context, r Resolver, domain string) ([]peer.AddrInfo, error) {
	ctx, cancel := context.WithTimeout(ctx, dnsTimeout)
	defer cancel()

	target := "_dnsaddr." + domain
	txts, err := r.LookupTXT(ctx, target)
	if err != nil {
		return nil, fmt.Errorf("LookupTXT %s: %w", target, err)
	}
	return parseTXTRecords(txts), nil
}

// parseTXTRecords is pure: takes TXT strings, returns the parsed
// peer.AddrInfo subset. Entries without the dnsaddr= prefix or with
// invalid multiaddrs are skipped silently. Separated out so it's
// unit-testable without a DNS round-trip.
func parseTXTRecords(txts []string) []peer.AddrInfo {
	out := make([]peer.AddrInfo, 0, len(txts))
	for _, txt := range txts {
		txt = strings.TrimSpace(txt)
		if !strings.HasPrefix(txt, txtPrefix) {
			continue
		}
		s := strings.TrimSpace(txt[len(txtPrefix):])
		if s == "" {
			continue
		}
		ai, err := parseMultiaddrToAddrInfo(s)
		if err != nil {
			continue
		}
		out = append(out, *ai)
	}
	return out
}

// parseMultiaddrToAddrInfo wraps the libp2p two-step.
func parseMultiaddrToAddrInfo(s string) (*peer.AddrInfo, error) {
	ma, err := multiaddr.NewMultiaddr(s)
	if err != nil {
		return nil, fmt.Errorf("parse multiaddr %q: %w", s, err)
	}
	return peer.AddrInfoFromP2pAddr(ma)
}

// AsMultiaddrStrings flattens a set of AddrInfos into the
// /<addr>/p2p/<id> string form ConnectBootstrap expects.
func AsMultiaddrStrings(peers []peer.AddrInfo) []string {
	var out []string
	for _, ai := range peers {
		for _, a := range ai.Addrs {
			out = append(out, a.String()+"/p2p/"+ai.ID.String())
		}
	}
	return out
}
