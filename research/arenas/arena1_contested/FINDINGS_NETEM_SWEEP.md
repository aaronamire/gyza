# The post-heal silent-loss window, swept over RTT

**Run 2026-08-29** against `PREREGISTRATION_NETEM.md`
(sha256 `1b667ed63785b3aa86cba64297505d47b228e1c0b4a45947be1af8e1ed13fe8d`,
written 10:50:02, before any harness code existed).

**Two earlier documents from this same session — `APPARATUS_NETEM.md` and
`FINDING_MESH_FORMATION.md` — were WRONG and have been deleted.** They
concluded, in turn, that netem breaks QUIC and that gossip mesh formation
fails at WAN latency. Neither is true. What was failing was the harness, and
the record of how it looked like a system failure is kept in §4 because the
species recurs.

## 1. Results

Apparatus: two `gyza-netd` daemons, one in a network namespace, joined by a
veth pair with netem on both ends. RTT verified by ping immediately before and
after every delivery measurement. Probes at 100 ms spacing for 10 s after
heal, 30 s settle, then a census of which arrived.

| netem delay | RTT | n | boundary (median) | range | steady delivery |
|---|---|---|---|---|---|
| 0 ms | 0 ms | 4 | 0.50 s | 0.10–0.50 | 26 ms |
| 40 ms | 80 ms | 3 | 0.90 s | 0.40–0.90 | 60 ms |
| 100 ms | 200 ms | 3 | 0.90 s | 0.80–1.00 | 109 ms |
| 140 ms | 280 ms | 3 | 1.30 s | 1.20–1.30 | 154 ms |
| 250 ms | 500 ms | 4 | 2.10 s | 1.60–2.10 | 268 ms |

**17 runs, 0 inversions at any RTT.** Steady-state delivery tracks one-way
delay across the whole range (26 -> 268 ms), which is the standing evidence
that the instrument measured what it claimed to.

### The window has a two-term structure

Least squares over all 17 runs:

```
boundary(s) = 0.400 + 3.098 x RTT(s)        R^2 = 0.907
```

- **A 400 ms floor**, independent of RTT.
- **A cost of ~3.1 round trips.**

The coefficient is the part worth keeping, because it is not merely a fit: **a
small integer number of round trips is what a GRAFT/PRUNE negotiation costs.**
The window is therefore not one phenomenon but two -- a fixed heartbeat-and-
processing floor, plus a mesh handshake that pays real latency. That
decomposition is what N1 was reaching for, and it is now quantified rather
than asserted.

**It also predicts where the two terms trade places.** They are equal at
RTT = 129 ms; below that the floor dominates and the window is roughly
constant, above it the handshake dominates and the window grows linearly. All
three real legs of the planned deployment sit at or above that crossover.

### Point predictions for the WAN run

Drawn from the fit, and committed here BEFORE any hardware exists:

| leg | RTT | predicted boundary |
|---|---|---|
| New York - Amsterdam | 80 ms | **0.65 s** |
| New York - Sydney | 200 ms | **1.02 s** |
| Amsterdam - Sydney | 280 ms | **1.27 s** |

**Arena 1 no longer reports three unanchored numbers; it tests three
predictions.** If the measured WAN coefficient departs materially from ~3
round trips, the netem model does not transfer and that is itself the finding.

## 2. Verdicts against the preregistered predictions

- **N0 — RTT/delay = 2.0 ± 10%. HOLDS.** Measured 2.000, spread 0.001, on both
  loopback and veth. The x-axis was never in doubt.
- **N1 — heal is heartbeat-dominated, TTR(500 ms) − TTR(0) < 2.0 s. HOLDS**, at
  **+1.60 s** on medians. **Reported with a caveat**: the RTT≈0 baseline is
  unstable (0.10–0.50 s), and taking its low end puts the difference at exactly
  2.00 s, on the bar. N1 survives but is not comfortable, and the WAN run
  should treat 2.0 s as a live threshold rather than a settled one.
- **N2 — the window exists at every RTT. HOLDS.** The offset-0 probe was lost
  in **6/6** runs where it was checked, and no run delivered it.
- **N3 — the arrival pattern is monotone. HOLDS, cleanly.** Zero inversions in
  **17 runs across five RTTs**. **The loss is a window with a sharp edge, not a decaying
  probability.** This is the verdict that matters for design: a sharp edge
  means a readiness predicate can in principle close it, where a decaying
  probability would leave anti-entropy as the only sound remedy.
- **N5 — width(500 ms) < 3 × width(≈0). FALSIFIED**, at 4.2× on medians.
  This was flagged in advance as the weakest prediction, and it was. **The fit
  explains why it had to fail**: at 500 ms the handshake term (1.55 s) is
  nearly 4x the floor (0.40 s), so any ratio bound anchored at RTT≈0 is
  measuring the floor against the handshake. The prediction was malformed
  rather than merely wrong — a ratio was the wrong statistic for a quantity
  with a non-zero intercept.
- **C3 confirmed by direct comparison.** The control reports heal TTR as
  **2.08–2.09 s** using probes at 2 s intervals; this sweep, probing at 100 ms,
  finds delivery restored by **0.10–0.50 s** at the same RTT. Same event, 20x
  finer instrument, a 4–20x smaller number. **`PREREGISTRATION.md` ceiling C3
  predicted exactly this and was right: 2.08 s is the probe interval, not a
  system property, and must not be quoted as one.**
- **N4 (boundary vs TTR)** was not separately measured: the harness derives the
  boundary from first-arrival, so the two are the same quantity here. Recorded
  as not tested rather than as confirmed.

**The window grows with RTT and becomes MORE deterministic in relative terms.**
At RTT≈0 the boundary ranged 0.10–0.50 s — a 5x spread; at 500 ms it ranged
1.60–2.10 s, a 1.3x spread. Consistent with the two-term model: the floor is
the noisy component and the handshake term is not, so the measurement gets
cleaner exactly where the handshake dominates.

## 3. What this does and does not license

- **Does:** the silent-loss window survives every RTT tested up to 500 ms, has
  a sharp edge, and widens sub-linearly enough that N1's heartbeat account
  holds while N5's tighter bound does not.
- **Does NOT:** say anything about real WAN. This is netem. Route flap, BGP
  reconvergence and bursty jitter are absent by construction, and
  `PREREGISTRATION.md` remains the commitment for the hardware run.
- **Does NOT** measure the window under load. All 11 runs used an idle board
  with no agents. Arena 1 runs 500. If GRAFT competes with agent traffic the
  window could widen; **this is a floor, not an operating value.**

**The point predictions the WAN run should now test**, drawn from the curve:
80 ms → ~0.9 s, 200 ms → ~0.8 s, 280 ms → ~1.3 s. Arena 1 no longer reports
three unanchored numbers; it tests three predictions.

## 4. Three false trails, and what each cost

Recorded because all three are documented species that bit anyway.

**(a) Leaked daemons — a real bug, and NOT the contamination I first claimed.**
`NetdClient.start_daemon` returns a `Popen`; `close()` shuts only the gRPC
channel. Both harnesses discard the handle, leaking two daemons per run; **24
were found alive** on this host. `partition_experiment.py:42` has the same
defect.

> **The first version of this section asserted that the leak "polluted every
> later run" and put `FINDINGS_PARTITION_CONTROL.md`'s numbers in doubt. That
> was wrong, and it was asserted without being checked.** Leaked daemons boot
> with `isolated=True` and `mdns=False`, so they can never auto-connect to a
> later pair — they are inert islands, not gossip participants. And
> `partition_experiment.py` uses FIXED ports 7870/7871, so a leaked daemon
> makes a re-run fail loudly on bind rather than succeed with bad data.
> **Verified by re-running the control on a clean host: every value reproduces
> — 20/20 mirrored, 100% duplication, 0/20 agreement, TTR 2.09 s against the
> recorded 2.08 s.** The leak wastes ~36 MB per orphan and nothing else.
>
> The 0.90 s vs 0.10 s boundary difference I originally attributed to the leak
> is ordinary variance: the RTT≈0 boundary ranges 0.10–0.50 s across four
> clean runs. **I reached for a contaminating mechanism before checking
> whether the spread was simply the spread.**

**(b) The instrument was blamed for the system.** With the intent bug (c) live,
gossip delivery failed at every RTT ≥ 10 ms. That produced two confident and
false write-ups. What eventually broke it was a control that **bypassed the
suspect layer**: `send_message` over the same QUIC connection, which delivered
4 B / 2 KB / 16 KB in 44 / 42 / 49 ms at 80 ms RTT — proving the transport was
fine and the fault lay above it. **A comparison that changes two things at once
(direct vs gossip, 4 B vs 2 KB) is not a control**; the size confound had to be
removed before the result meant anything.

**(c) The actual bug — an intent published once into an unformed mesh.**
`work_items` holds a foreign key to the intent row. The harness posted the
intent immediately after `attach_gossip`. At RTT≈0 the mesh was ready and it
landed; at higher RTT it was published before GRAFT completed and **lost
forever, because gossip does not retry.** Every subsequent work item then
failed its foreign key on the receiving board. Re-posting the intent until it
lands fixes it completely: **80 ms → delivered in 2.6 s, 280 ms → 2.7 s.**

> **This is a real system observation, not only a harness bug.** A lost intent
> delta silently poisons every work item under that lineage on the receiving
> node, and the failure surfaces as `FOREIGN KEY constraint failed` in a log
> nobody reads rather than as a delivery error. The delta *arrives* and is
> rejected at insert. **In production that is indistinguishable from a
> partition**, and it is the same hazard `HEAL_WINDOW.md` names, one level
> down: a dropped delta whose absence is never reconciled.

**The species is identical in all three, and it is the one this program keeps
writing down:** the reassuring reading — my instrument is broken, the system is
fine — is the one that does not get questioned. Here it was false twice in a
row, and both times the correction came from instrumenting rather than from
reasoning harder about the same black box.

## 5. Method note on the preregistration itself

**N0 held perfectly and was not enough.** It calibrated the independent
variable and said nothing about whether the apparatus preserved the dependent
one. The delay was applied to three decimal places while delivery was
identically zero. A calibration that checks only the axis being swept is half
a calibration, and the missing half — a steady-state delivery control at every
RTT before any partition — is what a future preregistration should require.
