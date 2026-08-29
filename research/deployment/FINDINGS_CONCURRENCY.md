# Deployment topology — what actually binds, and what I got wrong measuring it

**Engineering measurement, not a preregistered route.** Data:
`concurrency.json`, produced by `measure_concurrency.py`.

---

## 0. The headline, and it corrects my own framing

> **Claim contention costs 0.33% of an action. The blackboard does not bind
> until roughly 300 cores on ONE host. The sandbox binds at 3.3 actions/s per
> core and binds everywhere.**

I measured the contended claim path first, found aggregate throughput falling
from 13,080 claims/s at one runner to 982 at thirty-two, and called it
**anti-scaling**. The number is real. The framing was the AG-3 error again:
*reporting a cost without the counterfactual.* At 32 runners a claim costs 1.02
ms against a 305 ms sandbox — it is under one percent of the work it gates.

**A guard's throughput cost is not evidence that it is doing anything, and a
bottleneck's degradation curve is not evidence that it is the bottleneck.**

## 1. What was measured

N threads sharing ONE blackboard, racing for a shared pool. The pool is shared
rather than partitioned on purpose: partitioning would measure N independent
writers and call the result contention.

| runners | items | wall | claims/s | p50 | p99 | double-claims | unclaimed |
|---|---|---|---|---|---|---|---|
| 1 | 25 | 0.00s | 13,080 | 0.032 ms | 0.123 ms | **0** | **0** |
| 2 | 50 | 0.01s | 3,419 | 0.034 ms | 8.649 ms | **0** | **0** |
| 4 | 100 | 0.02s | 4,452 | 0.021 ms | 1.296 ms | **0** | **0** |
| 8 | 200 | 0.09s | 2,224 | 0.020 ms | 1.186 ms | **0** | **0** |
| 16 | 400 | 0.18s | 2,178 | 0.019 ms | 1.372 ms | **0** | **0** |
| 32 | 800 | 0.81s | 982 | 0.019 ms | 18.283 ms | **0** | **0** |

**Correctness holds perfectly at every N.** Zero double-claims, zero items
lost, in a workload built to produce them. `BEGIN IMMEDIATE` does its job.

The degradation is close to `1/N`, which is what a serialized writer lock
predicts: total attempts are `items x N` at every cell — the harness and the
production pattern agree on this, because `_run_loop` polls `get_unclaimed` and
claims the highest-scoring item, so N runners mostly contend for the SAME item
and produce `1` winner and `N-1` losers per item.

## 2. A fix I built, measured, and reverted

96.9% of writer-lock acquisitions at N=32 are losing claims, and a losing claim
took the full `BEGIN IMMEDIATE` path to discover it. The obvious optimisation is
a read-only pre-check outside the transaction, declining early without the write
lock — sound, because the authoritative test stays inside the transaction and a
pre-check can only decline, never admit.

**It made things worse and was reverted.**

| | N=1 | N=32 |
|---|---|---|
| baseline | 13,080 /s | 982 /s |
| with pre-check | 8,266 /s | 410 /s |

An extra read per attempt costs more than the lock it avoids — a 41% regression
on the UNCONTENDED path, where there is nothing to avoid. Recorded rather than
deleted: the hypothesis was reasonable, the measurement refuted it, and the
next person to have the same idea should find this instead of rediscovering it.

## 3. Where the fleet actually binds

| | rate | binds at |
|---|---|---|
| bubblewrap sandbox | 3.3 actions/s **per core** | always |
| blackboard claims | ~982 claims/s **per host** | ~300 cores |

**Per host: `throughput ≈ 3.3 x cores` actions/s.** Coordination is free at any
host size anyone will build.

That reframes the deployment question entirely. It is not *"can the substrate
coordinate N agents"* — it can, with room to spare. It is **"how many cores do
you want to buy"**, and the answer follows from the action rate you need:

| target | cores | notes |
|---|---|---|
| 100 actions/s | 31 | one large machine |
| 1,000 actions/s | 304 | a small cluster; blackboard now co-binding per host |
| 26,000 actions/day | **0.3** | the planetary program's own figure — a fraction of one core |

**The planetary bound is not a throughput problem.** `N <= H*A/[(1-p)(1-c)]`
caps the fleet at ~26,000 actions/day for reasons that have nothing to do with
CPU, and 26,000 actions/day is one third of one core. Buying hardware does not
move it.

## 4. What is genuinely missing

Not throughput. These:

1. **`AgentSupervisor` has ZERO production constructors** and no `NON_ADOPTED`
   marker. It is the component that spawns agents in response to demand — the
   mechanism a multi-agent deployment would run on — and nothing constructs it.
   `tests/test_declared_is_wired.py` did not catch it because its census is
   scoped to a hardcoded list of `gyza.containment.*` modules; `gyza/supervisor.py`
   is outside its remit. **Instance #10 of the species, in the deployment path.**
2. **One process, N threads.** `AgentRunner.start()` spawns a daemon thread.
   That is fine — the sandbox is a subprocess, so the GIL is released during the
   305 ms that dominates — but it means one crashed process takes the whole
   node's roster with it. There is no supervision across processes and no
   restart policy.
3. **No host-level sharding.** One blackboard per host is measured and adequate;
   what is absent is any statement of how work is partitioned ACROSS hosts. The
   gossip layer replicates deltas, so today every host sees every item.
4. **No backpressure.** Nothing throttles a runner when the blackboard slows.
   At 300+ cores per host that would start to matter.

## 5. What this does not establish

- Mock executor throughout. Mixing in the 305 ms sandbox would make every cell
  sandbox-bound and measure that constant instead of the coordination it is
  meant to isolate. §3 composes them rather than hiding the choice.
- One host. Cross-host contention is gossip-mediated and unmeasured.
- Threads, not processes. Process-level claim exclusion is verified separately
  and mutation-checked (`tests/test_claim_across_processes.py`), but the
  THROUGHPUT numbers here are thread-level.
- 32 runners is the largest cell. 300 cores is an extrapolation from the
  crossover, not a measurement at that size.
