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


---

# FIXED 2026-08-23 — both defects, measured before and after

The negative scaling had **two independent causes, and they interact**, so
neither could be fixed alone: bounding the fetch makes the herd *worse*,
because fewer candidates means more agents converging on the same row.

| | 1 | 2 | 4 | 8 | 16 agents |
|---|---:|---:|---:|---:|---:|
| homogeneous claims/s **before** | 24 | 22 | 12 | 7 | **4** |
| homogeneous claims/s **after** | 151 | 244 | 247 | 204 | **175** |
| win rate **before** | 100% | 50.4% | 27.9% | 19.9% | **11.4%** |
| win rate **after** | 100% | 99.2% | 98.2% | 95.5% | **91.1%** |
| heterogeneous claims/s **before** | 24 | 52 | 57 | 53 | 49 |
| heterogeneous claims/s **after** | 145 | 207 | 212 | 180 | **141** |

**44x at 16 agents in the pathological case**, ~4x across the benign case, and
the queue now DRAINS: every run claims all 1500 items, where before a 16-agent
fleet managed 69. **Zero double-claims at every N, before and after** — the
correctness property was never the problem and is not disturbed by the fix.

**D1 — a strict argmax over a deterministically ordered list.**
`_score_items` took the maximum-similarity item with `>`, so ties kept
`items[0]`, and `get_unclaimed` orders identically for everyone. Whenever
scores tie — normal for homogeneous work, eventual for agents whose
specializations converge — every agent wants the same row. The win rate then
falls as **1/N almost exactly**, which is the algebraic signature of N agents
contending for one item and is what identified the mechanism.

Fixed by breaking **ties** at random within `SELECTION_TIE_EPSILON`. Randomising
only among ties rather than sampling the top-K is deliberate: where a genuine
best exists it is still returned, so the change costs nothing in the case it is
not needed. It decorrelates agents; it does not weaken selection. Pinned by a
negative control (`test_a_UNIQUE_best_is_still_returned`).

**D2 — an unbounded fetch.** `get_unclaimed` had no `LIMIT`, so every agent on
every poll materialised the entire unclaimed backlog, each row carrying a
384-float embedding, and scored all of them: O(agents x backlog) per interval,
worsening as the backlog grows. This, not lock contention, capped the benign
arm at ~55 claims/s **at a 99% win rate** — the agents were not fighting, they
were each re-reading the whole board. Fixed with an optional `limit`
(`POLL_CANDIDATES = 128` from the runner; `None` stays unbounded so no existing
caller changes).

## A confound in the counter-metric, recorded rather than reported as a result

Mean similarity of claimed items appears to fall (0.069 -> 0.003 at N=1), which
reads as a match-quality regression bought with throughput. **It is not
comparable.** Before the fix a single agent claimed 363 of 1500 items in the
window, so the mean covers only its BEST matches; after, it drains all 1500 and
the mean includes every poor match. The denominators differ by up to 20x.

This is artifact #17's species — two numbers with the same units, the same
plausible ordering, and different populations. A sound comparison would fix the
number of claims (e.g. mean similarity over the first 100) and has not been run,
so **no claim about match quality is made in either direction.**

**A genuine risk does remain, separately:** bounding candidates by REWARD order
does not preserve embedding diversity, so a well-matched item can sit outside
the top 128. The principled fix is similarity-aware fetching through the LSH
index that already exists (`gyza/demand.py`), which would bound the fetch
*and* preserve match quality. Not done; scoped, not hand-waved.

## What this does and does not change

It makes the **work queue** scale. It does **not** make Gyza coordinate: no
agent creates work, `parent_id` is still never written, and the decomposer
still raises. Sections 1-3 above stand unchanged. **This was the prerequisite,
not the feature** — there was no point generating more work for a queue that
got slower as agents were added.

---

# CORRECTION 2026-08-23 (later the same day): the plateau was the TEST HOST

The post-fix table above shows throughput peaking at 4 agents and declining
(151 / 244 / 247 / 204 / 175 for 1..16). I read that as a per-node
architectural ceiling — one SQLite blackboard being a single-writer resource —
and went on to test whether PARTITIONING recovers scaling. It appeared not to:
independent blackboards, no gossip, no coordination, and aggregate throughput
was flat to declining (285 / 280 / 268 / 214 for 1/2/4/8 partitions).

**That conclusion is void, and the reason is standing rule #4.**

> **This host has FOUR cores** (i5-7200U), and the poll path is **99%
> CPU-bound at ~0.1 ms per poll**. One agent per core saturates it. The
> 8-partition run put **32 processes on 4 cores** — 8x oversubscribed, load
> average 9.52 — so it measured context-switching on a 2016 laptop, not any
> property of Gyza.

I computed the feasibility ceiling of the system under test and not of the
apparatus, which is exactly the failure rule #4 was written for and exactly
how it has failed the previous five times.

## The measurement that survives

Re-run with total processes **≤ nproc**, on a settled machine:

| partitions | agents | claims/s | vs 1 partition |
|---:|---:|---:|---:|
| 1 | 1 | 173 | 1.00x |
| 2 | 2 | 299 | **1.73x** |
| 4 | 4 | 318 | 1.84x |

**Partitioning scales near-linearly while cores are available.** 1 -> 2 gives
1.73x against a ceiling of 2.00x; 2 -> 4 adds almost nothing, because the
fourth core is absorbing the parent process and the OS.

## What may and may not be claimed

- **May:** the per-agent poll path costs ~0.1 ms and is CPU-bound;
  partitioning recovers near-linear aggregate throughput at 2 partitions;
  per-core throughput is roughly 80-170 claims/s depending on contention.
- **May NOT:** anything about scaling beyond ~4 concurrent agents. **It is not
  merely untested, it is untestable on this hardware** — the apparatus
  saturates below the interesting region.

## What survives from the original result, and why

**The 44x contention fix stands.** That was a before/after comparison at
IDENTICAL agent counts on the same host, so the apparatus was constant and
divides out. The defect was algebraic — a claim win rate falling as 1/N, the
signature of N agents contending for one row — and it is gone.

What did NOT survive was the *absolute interpretation*: "the queue plateaus at
~250 claims/s regardless of agent count" is a statement about a 4-core laptop.

## Consequence for the program

This converts a stated assumption into a measured requirement. The technical
plan's risk **R5 — compute for large-agent experiments** was an assertion that
large-N work needs infrastructure not currently held. It is now a measurement:
**the scalability question cannot be answered on this machine at all**, because
the interesting region begins above the core count. A thousand-agent claim
requires hardware before it requires code.
