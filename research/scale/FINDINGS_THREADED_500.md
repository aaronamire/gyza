# 500 threaded agents on four cores — it works, and throughput is flat

**Measured 2026-08-25**, `research/scale/threaded_scale.py`. Every action is a
real bubblewrap execution of `/usr/bin/uname -a`; agents are THREADS in one
process; all of them contend for one blackboard. **Cost: $0.**

| agents | signed | failed | wall s | **act/s** | RSS MB | MB/agent | mean queue |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 20 | 0 | 22.2 | 0.90 | 965 | 9.0 | 0.4 s |
| 50 | 100 | 0 | 34.5 | 2.90 | 1006 | 0.20 | 10.7 s |
| 100 | 200 | 0 | 66.4 | 3.01 | 1060 | 0.06 | 23.0 s |
| 250 | 467 | 0 | 144.0 | 3.24 | 1282 | 0.17 | 51.8 s |
| 500 | 602 | 15 | 202.5 | 2.97 | 1513 | 0.15 | **85.0 s** |

## What is established

**500 agents run.** They exist as threads in one process, poll a shared
blackboard, claim under mutual exclusion, execute real sandboxed actions and
sign envelopes. Nothing crashed, and the roster did not share a fate.

**The memory model holds.** Marginal cost is **0.15–0.20 MB per agent**, against
0.36 MB predicted by `FINDINGS_COORDINATION_CEILING.md` and 0.27 MB measured
in-process this session. 500 agents cost ~1.5 GB total, of which ~950 MB is
one-time process baseline (imports + the embedder's 88 MB).

**Threads were the right topology, and it was measured before it was chosen.**
Subprocess-bound work scales **29.89x at 32 threads**; CPU-bound work scales
**0.66x**. The GIL is released across the bwrap call. As processes, 500 agents
would have cost ~69 GB; as threads, 1.5 GB.

## What is refuted — including a projection made earlier the same day

**Throughput is FLAT at ~3 actions/sec from 50 agents upward** (2.90, 3.01,
3.24, 2.97). Adding agents adds **zero** throughput. It is `admission limit /
service time` and nothing else, so 500 agents on four cores is 500 agents
mostly queueing: **mean admission wait 85 seconds.**

**A projection made hours before this run was wrong by ~4x.** It read: "500
agents x 20 actions = 10,000 sandboxed actions = 3,050 core-seconds = ~13
minutes", from the research's 305 ms per sandboxed action. **Measured service
time is ~2.6 s**, so the same work is ~55 minutes. The 305 ms figure is real
but applies to a LIGHT factory; see below.

That is the third extrapolation error of this kind in a week — a 4-core laptop
reported as an architectural ceiling, 9.6 MB/runner that was 0.27, and now 13
minutes that is 55. **The pattern is arithmetic over a constant measured in a
different regime, and the remedy is the ladder rather than the multiplication.**

## Why an action costs 2.6 s and not 305 ms

`make_sandboxed_executor` spawns a fresh interpreter inside bwrap and re-imports
the factory's module **on every call**. Its docstring estimates ~150–300 ms.
Measured here:

```
bare interpreter          0.034 s
+ import gyza.runner      0.514 s      <- the factory's module
+ import numpy only       0.202 s
+ import subprocess only  0.032 s
```

The factory is `gyza.runner:make_command_executor`, and `gyza.runner` pulls in
numpy, blake3 and cryptography — **0.48 s of pure import per action**, amplified
by running eight concurrently on four cores.

**`make_command_executor` needs only `subprocess`.** Hosting it in a module that
imports nothing heavy would cut the import component ~16x. Not done here: it
touches the most safety-critical file in the tree and deserves its own change
with its own regression run. It is the single highest-leverage optimisation
available for throughput, and it costs no hardware.

## Two defects found, one fixed

**`ArtifactStore.store` raced under threads — FIXED.** The temp name carried
only `os.getpid()`, with a comment stating that was enough "so two processes
writing the same content at once don't trip over each other's tmp file". True,
and it does not cover THREADS: they share a pid, so two agents storing
identical bytes built the same temp path and one `os.replace`d it out from under
the other. Invisible while every agent was its own process; reproduced at 50
threaded agents. A documented invariant whose named mechanism does not cover the
case is an assumption. Now unique per write, with cleanup on failure.

**A sandbox granted 256 MB cannot execute at all — NOT fixed, recorded.** With
`max_memory_mb=256` every action failed with `OpenBLAS error: Memory allocation
still failed after 10 retries`. The RLIMIT_AS is below what a numpy-importing
sandbox needs to start, and **the error names OpenBLAS rather than the grant**,
so an operator would debug the wrong thing. 512 MB works. There is a real
minimum grant for the current executor and nothing states or checks it.

**15 `database is locked` at 500 agents**, 0 below that. SQLite write contention
is the next limit above ~250 threaded agents on one blackboard, and it is the
partitioning argument stated as a measurement.

## What this means for scale

Cores are the only throughput lever. At ~0.75 actions/sec/core measured here,
500 agents at one action/sec each would need **~667 cores** — far beyond any
hobby budget, and that number is honest where "13 minutes" was not.

**But a bounded-action demonstration is already done, for free.** 500 agents,
1,000 real sandboxed actions, 602 signed envelopes, in 202 seconds on a 2016
laptop. What more hardware buys is *rate*, and what more MACHINES buy —
separately and more interestingly — is *distribution*, which is the only way to
get real WAN latency into a DDIL measurement.

---

# The light-factory fix: 2.6x throughput, no hardware (2026-08-25)

The finding above named the highest-leverage optimisation available and scoped
it rather than doing it. Done now. `make_mock_executor`,
`make_command_executor` and `make_planning_executor` moved from
`gyza/runner.py` to a new top-level `gyza/executors.py` that imports nothing
beyond the standard library.

**Top-level rather than under `gyza/sandbox/`, and the placement was measured:**

```
bare interpreter      0.034 s
import gyza          0.039 s      <- package root is cheap
import gyza.sandbox   0.207 s      <- would have cost 5x more
import gyza.runner    0.506 s      <- what every action used to pay
import gyza.executors 0.048 s      <- 10.5x cheaper
```

## Result

| agents | act/s before | act/s after | wall s before | wall s after |
|---:|---:|---:|---:|---:|
| 10 | 0.90 | **1.37** | 22.2 | 14.6 |
| 50 | 2.90 | **6.96** | 34.5 | 14.4 |
| 100 | 3.01 | **7.33** | 66.4 | 26.9 |
| 250 | 3.24 | **7.37** | 144.0 | 59.2 |
| 500 | 2.97 | **7.79** | 202.5 | **82.9** |

**Service time 2.6 s -> 1.03 s.** Mean admission wait at 500 agents 85 s -> 33 s.
`database is locked` failures at 500: 15 -> 7. Memory is unchanged (0.15 MB per
agent), because nothing about the agent changed — only what its sandbox pays to
start.

**Throughput is still FLAT above 50 agents** (6.96, 7.33, 7.37, 7.79). The fix
raised the ceiling; it did not remove it. The ceiling is
`admission limit / service time` and the only lever on it is cores.

`tests/test_executor_import_cost.py` pins this four ways, including a check
that no `gyza.runner:` qualname survives in any sandbox call site — a cheap
module nothing points at saves nothing.

## Ceilings, separated — because "maximum agents" is two different questions

**Agents that EXIST and coordinate — RAM-bound.** Baseline ~950 MB per process
(imports plus the embedder's 88 MB) plus **0.15 MB per agent**. On this box's
2.6 GB of available RAM the arithmetic gives several thousand. **Measured to
500; anything beyond that is arithmetic, and arithmetic of exactly this kind
has been wrong three times this week.** The next real limit is visible in the
data rather than predicted: `database is locked` appears at 500 and not at 250,
so SQLite write contention on one blackboard binds before RAM does.

**Agents doing USEFUL WORK — core-bound, and unaffected by agent count.**
~7.8 actions/sec on four cores, which is ~1.95 actions/sec per core. 500 agents
share that, so each one gets 0.016 actions/sec. Adding agents past ~16 buys
queueing and nothing else.

**Those two numbers answer different questions and must not be quoted as one.**
"500 agents coordinating with signed provenance" is true and measured. "500
agents working at scale" is not.

---

# Where the single-board wall is (2026-08-25)

The section above said the single-board ceiling was "probably ~1,000-2,000" and
that finding it means running the ladder further rather than multiplying.
Ran it. One action per agent, so agent COUNT is the variable:

| agents | signed | failed | act/s | RSS MB |
|---:|---:|---:|---:|---:|
| 500 | 231 | **0** | 9.88 | 487 |
| 750 | 298 | **0** | 9.45 | 789 |
| 1000 | 347 | **154** | 6.55 | 1025 |
| 1500 | 340 | **538** | 6.18 | 1331 |

**Clean to 750. First failures at 1000. Wall at 1500**, where failures exceed
successes and the ladder stops by design — past that it would measure the OOM
killer rather than Gyza.

**Every failure is `database is locked`.** Not memory: RSS at the wall is
1.3 GB against ~2.6 GB available, and it grew smoothly. **SQLite write
contention on one blackboard is what binds**, exactly as the 500-agent run
predicted from its 15 stray failures, and it is the partitioning argument
arriving as a measurement rather than an assertion.

**Throughput held at ~9.5 act/s through 750 and degraded to ~6 past the wall** —
failing writes cost time and produce nothing.

> **Single-board operating range: up to ~750 agents. The scaling lever above
> that is a second blackboard, not a bigger machine.**

Partitioning was already measured to scale near-linearly (1.73x at two
partitions), so the architecture's answer to this wall is the one it already
had.

## Methodology note: three attempts to call a Go test failure "mine"

While this ran, the Go suite reported `TestRequestAttestationHappyPath`
failing, then `TestSenderSeqDedupRejects` — a different test each run, which is
the signature of load rather than code. Resolving it took three wrong turns
worth recording:

1. **The suites were run concurrently with a 1500-thread ladder**, violating a
   standing rule. Mine.
2. **"Passes in isolation" was tested as isolation from other TESTS, not from
   LOAD.** The box was still at load 4-7.
3. **Waiting for load < 0.5 was unreachable**: two six-day-old editor processes
   put this machine's BASELINE at ~2.4 on four cores. A quiet machine was never
   available, which is why CLAUDE.md's "passes in isolation" could not be
   reproduced today.

The decisive test was none of those. **`go list -deps ./internal/gossip` shows
zero dependency on `internal/bootstrap`**, the only package changed — so the
change cannot reach that test at all. A dependency fact settled in one command
what three timing experiments could not.

---

# Gap 1 closed: `RunnerThreadRoster` (2026-08-25)

`gyza/roster.py` — a FIXED ROSTER of agents as threads in one process, the
threaded sibling of `RunnerProcessSupervisor`. **Not** an adoption of
`AgentSupervisor`: that spawns on DEMAND, and `supervisor.py` correctly calls
demand-driven spawning "an OPTIMISATION over a fixed roster". A fixed roster is
what a deployment needs first.

## The objection, answered exactly as far as it is true

`supervisor.py` declines a threaded roster because *"threads share a fate — one
unhandled exception in one runner takes the whole roster."* Half right:

- **A Python exception does NOT cross threads.** `AgentRunner.start()` already
  runs its loop in its own daemon thread, so an unhandled error kills that
  thread alone. What was missing was anything to NOTICE — a dead daemon thread
  leaves no trace. The roster watches liveness and restarts. Tested by killing
  one agent's loop and asserting the other three keep signing.
- **A PROCESS-LEVEL fault genuinely is shared.** OOM, a segfault in a C
  extension, `os._exit` — all 500 die together, and nothing here changes that.
  **That is the price of the 130x memory saving and it is documented rather
  than engineered around.**

An unbuildable agent is isolated too: a corrupt state file marks that slot
`gave_up` and the other three run. One bad agent must not prevent 499 good ones.

The stall rule is copied from the process supervisor rather than reinvented,
because a negative control caught the distinction there: **idle is healthy, and
so is declining.** The signal is ATTEMPTING — holding a claim and finishing
nothing. `test_an_IDLE_roster_is_never_restarted` re-pins it here.

## Measured

**250 agents, 500 items, 500/500 signed, 0 restarts, 0 gave-up.** 614 MB RSS.

**Memory per agent is 2.24 MB running, against 0.27 MB constructed — and the
8x is SQLite, not a leak.** `PRAGMA cache_size` defaults to 2 MB **per
connection**, and `Blackboard._conn` is thread-local, so 250 threads carry ~500
MB of page cache; that is the whole gap. Each agent also opens its own episodic
and specialization databases. **At 500 agents this is ~1.1 GB of page cache**,
which an 8 GB node absorbs easily and which `PRAGMA cache_size` can lower if a
smaller node is ever used.

**A cold fleet pays for the embedder, and threads make it worse before better.**
The first action per agent measured **18.2 s**, and two agents took 18.2 s
*each* because both threads hit the cold SentenceTransformer load together;
warm actions are 43–260 ms. Real, and not what a roster test is about, so the
tests pin `GYZA_EMBEDDER=stub` in a MODULE-scoped fixture — not `conftest.py`,
because the suite must still exercise the real embedder somewhere.
