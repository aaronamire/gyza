# ADR-0007: Kademlia DHT under `/gyza/1.0` protocol prefix

**Status:** Accepted (Phase 3). Migration to provider-records
acknowledged as Phase 4 cleanup; superset replacement in vNext
(ADR-0015 layer 4).

## Context

Phase 3 needed cross-cluster discovery. Agents publish capability
advertisements; consumers find them by capability match. The libp2p
ecosystem has a mature Kademlia DHT implementation
(`go-libp2p-kad-dht`) with standard get/put semantics.

A separate question was whether to ride the public IPFS DHT or
segregate into a Gyza-only DHT. Public IPFS DHT would give
"discoverability" but mixes Gyza records with public IPFS records
(security boundary issues, name collisions, validators not
understanding our record types).

## Decision

- Use libp2p's Kademlia DHT under a dedicated Gyza protocol prefix:
  `/gyza/1.0`.
- Three record-type namespaces:
  - `/gyza/agents/{lsh_bucket_hex}` — AgentBucket records
  - `/gyza/attestations/{compositor_pubkey_hex}` — AttestationCert
    records (Session 14)
  - `/gyza/relays` — singleton RelayList for AutoRelay
- `gyzaValidator` (in `netd/internal/dht/dht.go`) implements
  libp2p's `record.Validator` interface. Dispatches by key prefix.
  Application-level signature verification happens at `FindAgents`
  read time, NOT at the validator (the validator runs on every
  storing peer in the network and doesn't have the trust registry).
- LWW (last-write-wins) on `last_updated_ns` for record selection
  on multi-value lookups.

## Consequences

**Intended:**
- Mature implementation. No need to write a DHT.
- Gyza records segregated from public IPFS — no namespace collisions.
- Network can run alongside an IPFS daemon on the same host
  without record interference.

**Accepted costs:**
- Public IPFS bootstrap peers don't serve `/gyza/1.0` queries.
  Gyza needs its own bootstrap peers (CLAUDE.md §6 B1; deployment
  blocker; user-owned).
- Bucket merge under concurrent publishers loses data (LWW on the
  whole bucket value). Phase 4 should migrate to provider records
  (each peer advertises themselves; consumers fetch from listed
  providers). Acknowledged in CLAUDE.md §3 trip-wires.
- Kademlia is not optimized for high-write churn. Agent
  advertisements republish every TTL/2 (default 30 min) which is
  fine for steady-state but inefficient. vNext (ADR-0015 layer 4)
  picks a custom DHT variant.
- DHT-level record TTL is a libp2p constant, not bounded by
  application-level TTL fields. Session 16's PublishAttestation
  floor + validator-side rejection mitigate; vNext fully replaces.

## Alternatives considered

- **Ride public IPFS DHT.** Rejected: record-validator collisions;
  IPFS bootstrap peers would route us into unrelated traffic;
  security boundary issues.
- **Custom DHT from scratch.** Rejected: years of effort; libp2p
  kad-dht is good enough at Phase 3 scope.
- **Centralized registry server.** Rejected: defeats decentralization
  goals; single point of failure.

## References

- `netd/internal/dht/dht.go` — GyzaDHT + validator
- `netd/cmd/gyza-netd/main.go` — DHT initialization with mode flag
- ADR-0013 (verify-on-fetch consumes attestation records)
- ADR-0014 (recursive Tier-3 verification uses DHT)
- ADR-0015 (vNext layer 4 — custom DHT variant for high-write)
- CLAUDE.md §6 B1 (deployment blocker: no default bootstrap peers)
