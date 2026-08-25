# A partition causes 100% duplicate execution, and convergence does not undo it

**Measured 2026-08-25 on loopback**, two real `gyza-netd` daemons, gossip-attached
`NetworkBlackboard` on each, a `RunnerThreadRoster` of 4 agents on each.
`research/arenas/arena1_contested/partition_experiment.py`. **Cost: $0.**

This is the **zero-latency CONTROL** for the WAN deployment. It is not the
experiment; it is the baseline the experiment is compared against, and it
already answers the soundness question.

## Result

```
work mirrored to B          20/20 in 0.00s
PARTITION: peers 0 both sides = True
during partition:  A signed 20/20,  B signed 20/20
  SAME item, BOTH sides, DIFFERENT envelopes:  20  (100%)
HEAL: first cross-node delivery after          2.08s
after heal: boards AGREE on 0/20; 20 still hold DIFFERENT envelopes
```

## What it means

**`try_claim` is atomic LOCALLY and only then publishes.** Within a node,
mutual exclusion is absolute — 0 double-claims measured at every agent count up
to 750. **Across a partition there is no gossip, so neither side can learn of
the other's claims, and both execute everything they can see.**

**Last-writer-wins converges the BOARD and not the WORK.** After heal the two
boards still disagree on all 20 items, because each holds the envelope its own
agent signed. LWW picks a winner for the row; **both actions already ran and
both envelopes exist and verify.** Convergence is not compensation.

**For idempotent work this is waste. For an IRREVERSIBLE action it is a
correctness failure** — the same intent produced two real-world effects while
the board records one, which is precisely the H7 hazard
(`research/IRREVERSIBILITY.md`). The harm model measures irreversible actions
per agent; nothing measures the same action performed twice by two partitions.

## Scope, stated so 100% is not misread

**The design forces the worst case deliberately**: mirror all work first, cut,
then start both rosters simultaneously from an identical view of unclaimed
items. That is an upper bound on duplication, not an average. Work posted on one
side only during a partition cannot duplicate, and work already claimed before
the cut does not either. **What 100% establishes is that nothing in the
architecture prevents it** — the rate in any real deployment is a function of
how much mirrored-but-unclaimed work exists when the link drops.

## Second finding: gossip loses deltas under BURST, and never recovers them

The first run of this harness mirrored only **17/20 items in 30 s**, where an
earlier run mirrored 12/12 in 0.20 s. Isolating posting interval:

| post interval | posted | delivered | loss |
|---:|---:|---:|---:|
| **0 ms** (tight loop) | 30 | 28 | **7%** |
| 5 ms | 30 | 30 | 0% |
| 25 ms | 30 | 30 | 0% |
| 100 ms | 30 | 30 | 0% |

**It is a burst property and 5 ms of spacing eliminates it on loopback.** The
losses are never recovered, because the CRDT converges over deltas *received*
and nothing re-requests a delta that never arrived.

**This is the same root cause as the heal window** (`HEAL_WINDOW.md`), reached
from a second, independent direction: there, deltas published into a not-yet-
formed mesh were lost; here, deltas published faster than the mesh absorbs them
are lost. **One remedy covers both — anti-entropy: a periodic digest exchange
that makes convergence a property of state rather than a consequence of every
message arriving.**

It is also a harness constraint: **the experiment must pace its posts**, or it
measures its own burst loss and calls it partition behaviour.

## What this changes about the WAN run

The control is now known, so the WAN experiment has a real question rather than
a vague one:

- **Duplication under partition: 100% on loopback, worst case.** WAN cannot
  exceed it, so the WAN measurement is about the REALISTIC rate under the three
  cut shapes — not about whether the effect exists.
- **Heal TTR: 2.08 s at ~0.05 ms RTT.** Gossipsub's heartbeat is 1 s, so the WAN
  figure should be heartbeat-dominated rather than RTT-dominated. That is a
  falsifiable prediction: if TTR at 280 ms RTT is far above ~3 s, something
  other than the heartbeat governs re-meshing.
- **Burst threshold: 5 ms on loopback.** Unknown on WAN, and it bounds how fast
  a distributed fleet may post work at all.
