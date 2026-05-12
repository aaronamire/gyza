# ADR-0006: Blackboard as coordination substrate

**Status:** Accepted (Phase 1). Replaced by distributed-log +
differential-dataflow in vNext (ADR-0015 layer 5).

## Context

Phase 1 needed a coordination primitive for agents to post work
items, claim each other's work, and record completions. A
blackboard pattern (Hearsay-II lineage, 1970s AI) fit naturally:
agents poll a shared store; the store coordinates access; no
explicit message-passing required.

The blackboard is implemented as a SQLite database with WAL,
indexed by work_item_id and intent_id. Phase 2 extended it to
support Raft replication for LAN clusters; Phase 3 added gossipsub
deltas for cross-cluster sync.

## Decision

- The **blackboard** is the per-node coordination substrate.
- Tables: `intents`, `work_items`, `claims`, `completions`,
  `icp_envelopes`, plus settlement-specific tables.
- SQLite with WAL — concurrent reads + serialized writes.
- Agents poll the blackboard at `poll_interval_s` cadence (default
  0.1s for tests, 1.0s for production).
- Claim is a single UNIQUE row keyed by work_item_id; the SQL
  engine arbitrates races atomically.

## Consequences

**Intended:**
- Simple, well-understood pattern.
- SQLite gives durability, concurrent reads, atomic claims.
- Poll loop is cheap; agents back off when no work is found.

**Accepted costs:**
- Polling has latency floor proportional to `poll_interval_s`.
  Sub-100ms responsiveness (Phase 6 robotics) needs a push-based
  model.
- Blackboards become **hotspots at scale.** Empirically works at
  10⁰–10³ concurrent participants; at 10⁴–10⁵ becomes a bottleneck;
  at 10⁶+ collapses.
- Causality is implicit (timestamps + claim-uniqueness) rather than
  modeled as a primitive. Race conditions around claim-vs-complete
  required defensive handling in the runner.
- WAL gives concurrent reads, but writes still serialize via
  SQLite's writer lock. Long transactions back up.
- vNext (ADR-0015 layer 5) replaces with distributed logs over
  differential dataflow — biggest architectural divergence from v1.

## Alternatives considered

- **Actor model (Erlang / Akka style).** Better for distributed
  state but requires per-actor message handling logic. More code
  per agent.
- **Distributed log (Kafka style).** Better at scale; needs more
  infrastructure (broker). vNext picks this.
- **No blackboard (direct peer-to-peer dispatch).** Rejected:
  requires every node to know about every work item; doesn't
  scale.

## References

- `gyza/blackboard.py` — SQLite-backed blackboard
- `gyza/network/network_blackboard.py` — Raft + gossip integration
- `gyza/runner.py::_run_loop` — claim/execute/complete cycle
- ADR-0015 (vNext layer 5 — distributed logs replace blackboard)
- CLAUDE.md §7 (architectural critique — blackboard hotspots)
