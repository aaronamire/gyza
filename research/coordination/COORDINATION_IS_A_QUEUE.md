# The coordination layer is a work queue, and it negative-scales

**Measured 2026-08-23.** Two questions, asked of the actual tree rather than of
the design documents: do agents *coordinate*, and does it *scale*?

## 1. No agent ever creates work

By AST census over `gyza/` (not grep — grep has misreported this codebase
before), `WorkItem` is constructed in exactly three non-deserializer places:

| site | `parent_id` |
|---|---|
| `gyza/capability_eval.py:534` | `None` |
| `gyza/cli.py:365` | `None` |
| `gyza/cli.py:2477` | `None` |

The other three constructions (`blackboard.py:162`,
`network_blackboard.py:541`, `raft.py:69`) are row-to-object reconstruction.
**`AgentRunner` calls `post_work_item` zero times.**

So **`parent_id` — the work-DAG edge — is never populated by anything.** The
field exists in the schema, is indexed, is replicated over gossip, is carried in
the protobuf, and is deserialized on the way back. Nothing writes a non-`None`
value. The dependency structure is fully plumbed and entirely unused.

**Work enters the system only from a human, through the CLI.**

## 2. The components that would decompose are unimplemented and unadopted

The codebase states this itself and should be credited for it:

- `gyza/coordination/orchestrator.py`: *"K-2 (decomposer) is now SPLIT … its
  IMPLEMENTATION still raises, for a reason that has nothing to do with
  strategy: nothing assigns a `claim_type` to a natural task."*
- The same class carries `NON_ADOPTED`: *"IT SCHEDULES OVER A STAGED EXECUTION
  MODEL THAT IS ITSELF NOT ADOPTED … gyza's production path executes an action
  and signs it, with no staging/promotion step."*
- `Orchestrator` and `SubcontractCoordinator` are **constructed nowhere** in
  `gyza/`.
- `economy/subcontract.py` and `economy/delegation.py` never reference
  `WorkItem` or the blackboard: **delegation grants AUTHORITY, it does not
  dispatch WORK.** These are different mechanisms and only one of them exists
  end to end.

## 3. What therefore exists

A **blackboard/stigmergic** coordination model, which is a legitimate paradigm
and is implemented correctly:

- a shared queue of work items,
- atomic claiming with mutual exclusion,
- claim leases with reaping, so a dead agent's work returns,
- specialization/LSH selection so heterogeneous agents self-select,
- gossip replication of the board across nodes,
- capability attenuation, proven monotone, along delegation edges.

**What does not exist:** decomposition, dependency ordering ("B after A"),
agent-to-agent handoff, negotiation, or bidding. Agents do not coordinate with
each other; they independently self-select from a pile a human filled.

## 4. It negative-scales

Processes, not threads (the fleet is one OS process per agent). 2,000 items, a
20 s window, one SQLite blackboard:

| agents | claimed | double-claims | claims/sec |
|---:|---:|---:|---:|
| 1 | 2000 | **0** | 216 |
| 2 | 2000 | **0** | 217 |
| 4 | 2000 | **0** | 116 |
| 8 | 965 | **0** | 46 |
| 16 | 415 | **0** | 19 |

**Correctness is perfect — zero double-claims at every N**, under genuine
process contention. That is the mechanism working exactly as designed.

**Throughput is 11× WORSE at 16 agents than at 1.** Adding agents does not add
capacity; past N = 2 it removes it, and at N ≥ 8 the fleet cannot drain the
queue at all. Two mechanisms, independent:

1. **Thundering herd.** `get_unclaimed` returns a deterministically ordered list
   (`ORDER BY reward DESC, created_at_ns ASC`), so every agent's "best item" is
   the same item. N−1 agents lose each race and immediately retry.
2. **Reap-on-every-poll.** `_run_loop` calls `reclaim_expired_claims()` before
   every poll, from every agent, every interval.

   > **CORRECTION 2026-08-23, same day.** This entry originally said "a WRITE …
   > whether or not anything is expired." **That is false.**
   > `reclaim_expired_claims` (`blackboard.py`) is already read-first: it
   > `SELECT`s expired rows and `UPDATE`s only the rows returned, so an empty
   > result performs **no write**. The steady-state cost is a *read* per poll
   > per agent — O(agents) index scans, concurrent under WAL — and it becomes a
   > write only when a lease has genuinely expired.
   >
   > I asserted a write path without reading the function. The measured
   > negative scaling in the table above is unaffected and reproduces; what was
   > wrong was my attribution of *why*. Mechanism (1) is therefore the
   > candidate that survives, and which mechanism dominates is now an open
   > question to be settled by profiling rather than by assertion.

**Scope of this measurement, stated:** all items carried identical embeddings,
so specialization could not diversify selection. This is therefore the
HOMOGENEOUS-WORK worst case. Heterogeneous work would spread selection and
reduce mechanism (1) — but not (2), and "many agents against a large pile of
similar tasks" is precisely the planetary case, so the worst case is the
relevant one rather than a pathological one.

## 5. Why this matters more than it looks

`N ≤ H·A/[(1−p)(1−c)]` is blocked at `A ≈ 1` on the review side because absence
is undetectable (`research/evidence_bundle/`). **This is a second, independent
path to the same wall, on the authoring side:** if a human must author every
work item, human effort scales linearly with task count and `A ≤ 1` by
construction, no matter how good review sampling ever gets.

**Planetary scale requires agents to generate work for each other. Nothing in
the production path does.** That is not a tuning problem or a wiring gap — the
decomposer raises, and the model it would schedule over is not adopted.
