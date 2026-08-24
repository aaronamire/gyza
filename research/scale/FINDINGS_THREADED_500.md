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
