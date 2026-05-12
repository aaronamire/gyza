# ADR-0001: Python + Go split with gRPC bridge

**Status:** Accepted (Phase 3 / Session 1 of Phase 3).
Superseded *in vNext* by Rust core (see ADR-0015).

## Context

Phase 1 was pure Python — runner, blackboard, ICP envelopes,
identity, memory, drift, demand, supervisor. Phase 2 added LAN
clustering via Raft (Python `pysyncobj`). Phase 3 needed
cross-internet federation: Kademlia DHT, gossipsub, NAT traversal
(DCUtR + circuit relay), libp2p streams.

The libp2p ecosystem is mature in Go (`go-libp2p`, `go-libp2p-kad-dht`,
gossipsub) and immature in Python (`py-libp2p` is incomplete and
unmaintained). Re-implementing NAT traversal, DHT, and gossipsub
in Python from scratch was infeasible at Phase 3's scope.

## Decision

Split the codebase along its natural seam:

- **Python (`gyza/`)** owns: execution, identity, ICP, ledger,
  memory, blackboard, capability eval, sandboxing, reputation.
  ML-adjacent code where Python's ecosystem wins.
- **Go (`netd/`)** owns: all libp2p concerns. DHT, gossipsub, NAT
  traversal, stream protocols. Compiled as `gyza-netd` daemon.
- **gRPC over a Unix socket** is the inter-language interface.
  Python is the client; Go daemon is the server.
- The daemon process is long-lived. Python clients connect on
  demand.

## Consequences

**Intended:**
- Each language used for what it's best at.
- Mature libp2p stack via Go without rewriting.
- Clean separation of concerns: network plumbing (Go) vs. agent
  execution (Python).

**Accepted costs:**
- gRPC boundary is a performance cliff. Every cross-language call
  marshals through Unix-socket bytes.
- Two codebases, two build systems, two CI streams (when CI lands).
- Type system mismatch: Python's dynamic types vs. Go's static
  types. Glued by hand-written `from_proto` / `to_proto` shims in
  `gyza/network/netd_client.py`.
- Cross-language canonicalization is load-bearing (see ADR-0010,
  ADR-0012). When Python and Go must agree on signing-input bytes,
  the conventions are easy to get wrong.
- Deployment requires running a Go daemon alongside Python.

## Alternatives considered

- **Pure Python with py-libp2p.** Rejected: ecosystem too immature
  in Phase 3 timeframe.
- **Pure Go everywhere.** Rejected: Python's ML ecosystem (sentence-
  transformers, LanceDB, runner-side eval) was load-bearing for
  Phase 1–2. Rewriting in Go would have delayed Phase 3 by months.
- **Rust everywhere.** Considered but rejected at Phase 3 scope —
  Rust libp2p was acceptable but Rust ML tooling was less mature
  than Python's. Becomes the right choice at vNext (ADR-0015).

## References

- `gyza/network/netd_client.py` — gRPC client surface
- `netd/internal/grpc/server.go` — gRPC server surface
- `netd/internal/grpc/proto/netd.proto` — wire interface
- CLAUDE.md §1 (architecture overview)
- ADR-0015 (vNext supersedes this with Rust core; v1 keeps the
  split during the migration window)
