# There is a silent-loss window after a partition heals, and the mechanism that names it is inert on the plane that needs it

**Found 2026-08-23** while calibrating instruments for Arena 1, before any
preregistered run. Reported now because it is an **existence proof**, not a
statistical claim: one clean reproduction with its own negative control is
sufficient, and it changes what §3.7 of the DICE technical volume may claim.

## Setup

Two real `gyza-netd` daemons on loopback, QUIC transport. **Three isolation
requirements, all load-bearing:**

- `mdns=False` — mDNS re-discovers a disconnected loopback peer in
  milliseconds, so the partition would be cosmetic.
- `isolated=True` — otherwise the daemons dial the public `gyza.network`
  bootstrap peers and could reconnect *through them*. Same species as the mDNS
  trap, different mechanism, and not previously written down.
- `dht_mode="server"` — `ModeAuto` stays in Client mode forever on loopback and
  the failure is silent.

Partition = `disconnect_peer`. **Truth predicate is the peer count reaching 0 on
BOTH sides**, not the absence of a connection event.

## The measurement

Steady-state gossip delivery of a work item, A → B: **0.055–0.058 s**.
While partitioned, delivery **fails** (negative control: the cut is real).

After `connect_peer` returns `success=True`:

| item | posted | arrived on B? |
|---|---|---|
| **EARLY** | 0.00 s after `connect_peer` returned success | **NO** — not at 20 s, not at 30 s |
| **LATE** | ~20 s after, same link, same topic | **YES** |

**LATE arriving is what makes EARLY's absence a loss rather than a delay.** The
link is healthy; the earlier delta is simply gone. Gossipsub does not retry, and
the blackboard's CRDT converges over *deltas received* — a delta that was never
delivered is never re-sent, so the two replicas stay divergent indefinitely.

**`connect_peer` succeeding does not mean the gossip plane is ready.** Between
those two moments, writes are accepted locally, published into a mesh that has
not re-GRAFTed, and silently dropped.

## The part that matters

**Gyza already knows about this hazard.** `NetworkBlackboard.wait_for_sync`
documents it almost exactly:

> *"After a network partition heals, the rejoining node still has a stale local
> SQLite even though the transport reports `connected`. Local-only signals can
> lie … Until that holds, this node MUST NOT accept new claims."*

That is the correct analysis. But its first line is:

```python
if not self._cluster_mode or self._raft is None:
    return True
```

**It is a RAFT-plane mechanism.** On the gossip plane — `_cluster_mode` is
`False` and `_raft` is `None` for a gossip-attached blackboard, verified
directly — `wait_for_sync()` returns **True immediately, having checked
nothing.**

So a caller who does the right thing, and asks whether it has caught up before
accepting work, is told **yes** on the one plane where the answer is unfounded.
This is worse than an absent mechanism: an absent one fails visibly at the call
site. **The reassuring direction is the one that does not get questioned.**

## What this does and does not establish

- **Establishes:** a reproducible window after heal in which gossip-plane writes
  are permanently lost; and that `wait_for_sync` does not cover that plane.
- **Does not establish:** how wide the window is as a distribution, how it
  scales past two nodes, or whether asymmetric and flapping partitions behave
  the same. Those are Arena 1's preregistered run.
- **n = 2 nodes, loopback, one scenario.** The existence claim is safe; no rate
  or distribution is claimed here.

## Two candidate remedies, not equivalent

1. **A gossip-plane readiness predicate** that `wait_for_sync` consults —
   mesh-formed rather than peer-connected — so the honest answer is available.
   Does not repair a loss that already happened.
2. **Anti-entropy**: a periodic digest exchange so an undelivered delta is
   eventually reconciled. This is the only one that makes convergence a
   *property* rather than an assumption about delivery, and it is what the
   architectural principle (append-only, derived-not-stored) would prescribe:
   convergence should be a fold over state, not a consequence of every message
   arriving.

**(1) is cheap and makes the system honest; (2) is what makes it correct.**
Neither is done here — the level and the design are user decisions.

## Method note

The first version of this measurement reported **TIMEOUT in 5/5 trials** and I
was one step from writing "the gossip plane does not recover from a partition."
That was false — it recovers in under 2 s — and it was my harness posting into
the unformed mesh every trial. What caught it was instrumenting the heal instead
of reporting the clean number: **five identical TIMEOUTs is exactly the kind of
result standing rule #2 exists for.** The real finding was hiding inside the
false one.
