# Arena 1 — netem RTT sweep, preregistration

**A SEPARATE experiment from `PREREGISTRATION.md`, which is unchanged and
remains the commitment for the WAN run.** This one is committed before any
sweep data exists and before the harness is written.

**What it is.** The WAN preregistration's P3 and P4 are both claims about
*RTT dependence* — that heal time and the silent-loss window are governed by
gossipsub's heartbeat rather than by distance. That is a claim about a
mechanism, and a mechanism claim can be tested by *varying RTT* without
crossing an ocean. `tc netem` injects delay at the qdisc layer, so RTT becomes
a swept independent variable instead of three fixed samples.

**What it is NOT.** netem produces *controlled* latency. It does not reproduce
route flap, BGP reconvergence, MTU discovery, or the bursty jitter of a real
transpacific path. **This sweep cannot replace the WAN run and does not try
to.** Its purpose is to make the WAN run cheaper and sharper: it produces a
curve, from which a POINT PREDICTION is drawn for each of the three real legs,
so the WAN run tests a prediction instead of reporting three unanchored
numbers.

---

## 0. Order of operations, and why it matters

1. This document is committed. Its hash predates every result artifact.
2. The harness is written.
3. The calibration (§2) runs. **If calibration fails, the sweep does not run.**
4. The sweep runs.
5. Point predictions for 80 / 200 / 280 ms are derived from the curve and
   appended to this file **as a dated addendum, not an edit**.
6. The WAN run tests those predictions.

## 1. Apparatus

- Two `gyza-netd` daemons on loopback, QUIC, `mdns=False`, `isolated=True`,
  `dht_mode="server"` — the three isolation requirements from
  `HEAL_WINDOW.md`, all load-bearing.
- `tc qdisc ... root netem delay D` on `lo`, applied for the whole run and
  removed in a `finally`.
- Control-plane calls to netd go over a **Unix socket**, which does not
  traverse `lo`'s qdisc. Only the QUIC data plane is delayed. This is the
  property that makes the measurement meaningful rather than an artifact of a
  slowed harness.
- Swept delays **D ∈ {0, 40, 100, 140, 250} ms**, chosen so the resulting RTTs
  bracket the three real legs: NY–AMS ~80, NY–SYD ~200, AMS–SYD ~280, plus one
  extrapolation point beyond any of them.
- **n = 3 repeats per delay**, fresh daemons and fresh ports every run.

## 2. Calibration — an instrument check with its own falsifier

**On loopback a packet traverses the `lo` egress qdisc once per direction, so
`delay D` should yield RTT ≈ 2D.** This is a claim about the apparatus and is
therefore measured, not assumed.

> **N0 — measured RTT / D = 2.0 ± 10% at every non-zero D.**
> **Falsified if the ratio is outside [1.8, 2.2], or if it is not constant
> across D.** A ratio near 1.0 would mean the qdisc is traversed once per
> round trip and every RTT label in this document is off by a factor of two.
>
> **If N0 is falsified the sweep does not run** until the mapping is
> understood. Reporting a curve against a mis-stated x-axis is the artifact
> this program has recorded most often.

Baseline (no netem) is measured in the same step: 0.069 ms on this host.

## 3. Predictions

> **N1 — heal time is heartbeat-dominated, not RTT-dominated.**
> **Predicted: TTR(RTT=500 ms) − TTR(RTT≈0) < 2.0 s.**
> Rationale: gossipsub's heartbeat is 1 s and re-meshing costs a small number
> of GRAFT/PRUNE rounds; even three rounds at 250 ms one-way adds ~0.75 s on
> top of a heartbeat floor. **Falsified if that difference is ≥ 2.0 s**, which
> would mean distance rather than the heartbeat governs re-meshing — and would
> also falsify the WAN preregistration's P3 before a single instance is
> created.

> **N2 — the silent-loss window exists at every RTT, including RTT ≈ 0.**
> **Falsified if an item posted at offset 0 after `connect_peer` returns
> success arrives, at any tested RTT.** This is the `HEAL_WINDOW.md` existence
> claim, re-tested under a swept variable rather than assumed to generalise.

> **N3 — the arrival pattern is MONOTONE in offset.** Every probe before the
> boundary is lost; every probe after it arrives.
> **Falsified if any probe at offset t arrives while a probe at offset t' > t
> is lost**, beyond a single adjacent inversion. Non-monotonicity would mean
> mesh readiness is not a step function and "the window" is the wrong noun —
> the quantity would then be a loss *probability* decaying with offset, which
> is a different object and a more serious finding.

> **N4 — window width and TTR measure the same event.**
> **Predicted |boundary − TTR| < 300 ms at every RTT.**
> Rationale: both should be set by GRAFT completion. **Falsified if they
> differ by more than 1 s at any RTT**, which would mean first-delivery and
> end-of-loss are governed by different mechanisms and the WAN run must
> measure both separately.

> **N5 — window width grows sub-linearly in RTT.**
> **Predicted: width(500 ms) < 3 × width(≈0).** Weakest prediction here and
> flagged as such, in the manner of the WAN preregistration's P6: the
> mechanism is understood well enough to give a direction, not a value.

## 4. Feasibility ceilings — computed for BOTH sides

Standing rule #4 has failed six times in this program, most recently by
checking the ceiling of the system under test and not of the apparatus. Both
are computed here.

- **C1 — window resolution is the probe spacing.** Probes at **100 ms**;
  predicted window 1–5 s gives 10–50 resolution elements across it. Adequate.
  A window below 200 ms would be at the instrument floor and must be reported
  as such rather than as a value.
- **C2 — probe train must outlast the window.** Train runs to **10 s**, i.e.
  2× the top of the predicted 1–5 s range. If the boundary is not observed
  inside the train the run reports NO-BOUNDARY, never a censored number.
- **C3 — probe spacing vs. one-way delay.** At D = 250 ms, probes are spaced
  closer than one one-way delay, so several are in flight at once. Gossip
  publishes are independent and do not require a round trip, so this is sound
  — but it is the assumption most likely to be wrong here, and N3's
  monotonicity check is what would expose it.
- **C4 — settle time.** 30 s after the train, ≥ 60× the largest RTT. A probe
  counted as lost has had two orders of magnitude more time than delivery
  needs.
- **C5 — pacing floor.** The WAN preregistration measured 7% gossip burst loss
  in a tight loop and 0% at 5 ms. Probes at 100 ms are 20× that floor, so
  burst loss cannot be mistaken for window loss.
- **C6 — total runtime.** 5 delays × 3 repeats × ~70 s ≈ **18 minutes**. Cost
  $0.

## 5. What each outcome changes

- **N1 confirmed** → P3 is de-risked before any instance is created, and the
  WAN run's job narrows to confirming the curve at three points.
- **N1 falsified** → P3 is falsified on free hardware, the DICE §3.7
  concession stands, and the WAN run's design changes before money is spent.
  **This is the outcome with the highest value per dollar.**
- **N3 falsified** → "the window" is not a window but a decaying loss
  probability. `HEAL_WINDOW.md`'s existence claim survives; its framing does
  not, and anti-entropy becomes the only sound remedy rather than the better
  of two.
- **N0 falsified** → the sweep does not run. Recorded as an apparatus finding.

## 6. What this sweep will NOT claim

Anything about real WAN behaviour. Anything about duplication rates (P1/P2 are
the WAN run's, and P1 predicts RTT-independence there anyway). Anything about
throughput. That netem latency and geographic latency are the same thing —
**they are not, and the WAN run exists because they are not.**
