# Coordination-plane scaling ceiling — measured 2026-08-20

> ## ⚠ CORRECTED SAME DAY — THIS FILE FIRST MEASURED THE WRONG THING
>
> §1–§3 measure the **read** path and concluded "500k is ~2.5× over". Two
> further measurements moved the ceiling by three orders of magnitude:
>
> | path | throughput | scales with processes? |
> |---|---|---|
> | blackboard **reads** | 209,000 /s | yes (2.2×) |
> | blackboard **writes** | **~11,000 /s** | **no — degrades** |
> | **bubblewrap sandbox** | **3.3 actions/s/core** | per-core only |
>
> **The sandbox is the binding constraint — 305 ms per action, 3,362× the
> write path.** An agent doing real sandboxed work costs four orders of
> magnitude more than one polling. Reporting the read ceiling as *the*
> ceiling was measuring the cheapest path and calling it the system.
>
> See §6, which is the finding that actually answers the question.

**Not a projection.** Single-machine measurement of the blackboard poll path,
which is what every `AgentRunner` executes once per `poll_interval_s` (default
1.0s). Answers SOW Task 1.2 — *"establish the current scaling ceiling and
characterise what breaks first"* — ahead of the program rather than inside it.

## 1. Per-runner resource cost

Constructed 200 real `AgentRunner`s (identity, episodic memory, specialization
tracker, LSH index, mock executor) against one shared blackboard.

| runners | RSS added | per runner |
|---|---|---|
| 25 | 99.6 MB | 3.99 MB |
| 50 | 108.5 MB | 2.17 MB |
| 100 | 126.5 MB | 1.27 MB |
| 200 | 162.4 MB | 0.81 MB |

**The marginal cost is 0.36 MB per runner** — identical across every interval
(25→50, 50→100, 100→200). The falling per-runner average is fixed overhead
amortizing; **0.36 MB is the number to extrapolate with, not 0.81.** Reporting
the average would have overstated the cost by 2.25×.

Marginal construction cost: **~3.2 ms per runner**.

## 2. THE BINDING CONSTRAINT IS THE GIL, NOT SQLITE

Blackboard poll throughput, identical workload, empty board:

| concurrent readers | **threads** | **processes** |
|---|---|---|
| 1 | 116,656 /s | 93,059 /s |
| 4 | 32,368 /s | 189,178 /s |
| 16 | 23,053 /s | **208,701 /s** |
| 64 | 22,752 /s | 178,796 /s |

**Threading does not merely fail to scale — it scales NEGATIVELY.** Total
throughput falls 5× from one thread to sixteen. Processes scale 2.2× and
plateau near 200k/s.

> **SQLite in WAL mode is not the bottleneck. Python's GIL is.** A threaded
> deployment caps at **~23,000 polls/sec regardless of core count**; a
> multi-process deployment reaches **~200,000/sec against the same file.**

This was measured because negative scaling is a suspicious result and the
distinction is architecturally decisive: a GIL bound is fixed by process
topology, a storage bound is not.

## 3. What this means for deployment size

At `poll_interval_s = 1.0`, each runner costs one poll per second.

| target | RAM (0.36 MB/ea) | polls/s needed | verdict |
|---|---|---|---|
| **500 agents** | 0.18 GB | 500 | **comfortable — 400× under the process ceiling** |
| 5,000 | 1.8 GB | 5,000 | comfortable, multi-process |
| 50,000 | 18 GB | 50,000 | feasible, multi-process, one blackboard |
| **500,000** | **180 GB** | **500,000** | **~2.5× over the ceiling of one blackboard; needs ≥3 shards** |

**Three constraints, in the order they bite:**

1. **Threading model.** Above ~23k runners a single process cannot poll fast
   enough no matter the hardware. Multi-process is mandatory, not an
   optimisation.
2. **Blackboard sharding.** One blackboard tops out near 200k polls/s. 500k
   runners need at least three, and the coordination semantics of sharding are
   **not yet designed**.
3. **File descriptors and inodes.** Each runner opens **two** SQLite files
   (episodic memory, specialization). 500k runners = **1,000,000 files**.
   This is a real limit before RAM is.

RAM is the *least* binding constraint — 180 GB is purchasable. The architecture
is not.

## 4. Honest scope of this measurement

- **Coordination plane only.** No libp2p, DHT, gossip or settlement is in the
  loop. Real deployment adds network cost, so these are an **upper bound on
  capacity**, not a prediction.
- **Empty board.** A populated blackboard makes `get_unclaimed` do more work;
  the ceiling falls from here, it does not rise.
- **One machine.** Multi-machine changes the sharding question qualitatively.
- **Polling only.** Claim/complete/sign are write paths and are not measured
  here. Writes contend where reads do not.

## 5. The honest answer to "is the substrate ready?"

**500 agents doing real work: yes.** Two orders of magnitude of headroom on
every measured axis. Nothing in this data suggests strain.

**500,000 AgentRunners: no — and now for stated reasons rather than an
absence of evidence.** The blockers are a threaded poll loop, an unsharded
blackboard, and a two-files-per-runner storage layout. None is fundamental;
all three are architectural work that has not been done.

The value of this file is that "designed, not demonstrated" becomes "measured
at 23k threaded / 200k multi-process, binding constraint identified" — which is
a statement a reviewer can check, and a starting point rather than a promise.


## 6. THE REAL CEILING — writes and the sandbox

### Write path (`post_work_item`), the path reads do not contend on

| processes | writes/s total | per process |
|---|---|---|
| 1 | 14,072 | 14,072 |
| 4 | 12,311 | 3,077 |
| 16 | 10,656 | 666 |

**Writes do not scale with processes — they degrade.** SQLite serializes
writers; adding concurrency subtracts throughput. Every agent action performs
several writes (claim, envelope, artifact, completion, episode), so node-wide
action throughput from storage alone is roughly **2,000–3,000 actions/sec**.

### Sandbox (bubblewrap), per action

**Median 305.6 ms** (n=12, min 290, max 323). **One core sustains 3.3 sandboxed
actions per second.**

> **This dominates everything else by 3,362×.** Coordination throughput is
> irrelevant next to it for any agent doing real work.

### What that means, decomposed by agent kind

The distinction matters and collapsing it produces nonsense:

| population | per-action cost | ceiling |
|---|---|---|
| **Mock runners (poll only)** | ~1 read | ~209k/s multi-process; 23k threaded |
| **Real agents (sandboxed)** | **305 ms + ~5 writes** | **3.3 actions/s/core** |

- **500 real agents, one action per 10 s** → 50 actions/s → **~15 cores of
  sandbox alone.** Feasible on one large machine.
- **500 real agents, one action per second** → 500 actions/s → **~150 cores.**
- **500,000 runners doing sandboxed work** → one action each is **42 core-hours**.
  Not feasible in any configuration measured here.
- **500,000 MOCK runners** → polling only, bounded by reads; feasible with
  sharding and multi-process, *provided they do no sandboxed work.*

## 7. What is STILL NOT MEASURED — and must not be assumed

Everything above is one machine, empty board, coordination and sandbox only.
**Not measured:**

- **libp2p / DHT / gossip at scale.** The mesh plane is entirely absent from
  these numbers. `CLAUDE.md` records gossipsub mesh re-formation at 10–15 s on
  two loopback nodes; behaviour at hundreds is unknown.
- **Settlement throughput.**
- **Multi-machine anything.**
- **Populated board.** Every measurement used an empty blackboard;
  `get_unclaimed` does more work with real items, so the read ceiling falls.
- **Episodic memory at corpus scale.** `memory.py:15` — the SQLite backend does
  brute-force cosine search, "slow above ~50k episodes", and retrieval sits on
  the execution hot path.
- **Inference API rate limits.** For *real* agents this is likely the true
  binding constraint and it is external to the substrate entirely.

## 8. So: is the substrate ready?

**For 500 real agents: nothing measured breaks, but it is sandbox-bound and
needs roughly 15 cores at a 10-second action cadence.** That is a deployment
question, not a research one.

**For 500,000 runners doing real work: no**, by four orders of magnitude on the
sandbox path.

**"Fully ready" is the wrong frame, and the honest answer is no** for reasons
independent of throughput: `can_claim_containment` reports **FALSE**; DDIL is
demonstrated on a clean cut only; **no external party has verified a bundle**;
and H3 has no attestation source so it counts every send. Those gate a
*deployment claim* regardless of how many agents the machine can hold.
