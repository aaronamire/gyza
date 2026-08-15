# Correction — E1's `PARTITIONED_READ` column is degenerate

**`FINDINGS.md` stands unedited**, per the practice this corpus already follows
(`FINDINGS_BOX_SCALING` §5 → `FINDINGS_ROUND3_DISTANCE` §4c). This document
carries the correction; `research/CORRECTIONS.md` indexes it.

Written the same day as the finding it corrects, found by asking whether a
monotone decay to zero — the shape I wanted — was real.

---

## 1. What was claimed

`FINDINGS.md` §1 and §2.2: *"`PARTITIONED_READ` strictly dominates it at every
M ≥ 4 and **improves** with scale,"* reporting 0.000 for M ≥ 8 (n=1) and a clean
monotone decay 0.850 → 0.525 → 0.000 (n=4).

## 2. What is actually true

**The zeros are a floating-point boundary artifact, and the decay is not a
scaling trend.**

`PARTITIONED_READ` re-reads current state on every admission and sheds each
principal to exactly `L·(1+1e-9)`. `L` is *defined* as the floor at which
concentration equals κ. So the discipline drives the system **to exactly the
bound and holds it there**:

| M | final concentration | − κ |
|---|---|---|
| 64 | 0.6000000055980319 | **+5.6e-09** |
| 128 | 0.599999999519995 | **−4.8e-10** |
| 512 | 0.5999999995199679 | **−4.8e-10** |

The check was `> κ + 1e-9`. M = 64 lands *above* that hair; M ≥ 128 lands
*below* it. **The difference between "0% violations" and "98% violations" is
1e-8 of concentration.**

### Tolerance sensitivity — the decisive test

Violation rate at M = 64, n = 4, 100 rounds, varying only the check's tolerance:

| tolerance | naive | reserved | **partitioned** |
|---|---|---|---|
| 0 | 1.0000 | 0.9800 | **0.8100** |
| 1e-12 | 1.0000 | 0.9800 | **0.8100** |
| 1e-09 | 1.0000 | 0.9800 | **0.8100** |
| 1e-06 | 1.0000 | 0.9800 | **0.0000** |
| 1e-03 | 1.0000 | 0.9800 | **0.0000** |

`naive` and `reserved` are **flat across nine orders of magnitude.** `partitioned`
flips between 1e-9 and 1e-6.

### And it is slower, not safer

At the tolerance as published, partitioned's rate *grows with rounds* wherever it
is not boundary-pinned — the 40-round figures understate it roughly twofold:

| M | 40 rounds | 200 | 1000 |
|---|---|---|---|
| 16 | 0.800 | 0.960 | **0.992** |
| 64 | 0.525 | 0.905 | **0.981** |

## 3. What survives

**The E1 verdict `RESERVATION-DEAD-ABOVE-M=3` is unaffected and is robust.** It
rests on `reserved ≈ naive` for M ≥ 4, and both arms are tolerance-insensitive
across the whole sweep. Nothing in §2.3's mechanism, §2.6, or the E2 results
depends on the partitioned column.

**What does not survive** is the reading I was one step from building a route
on: that re-reading current state is a mechanism whose adequacy *improves* at
planetary scale. It does not. It sits exactly on the bound at every scale.

## 4. The general lesson, which is worth more than the correction

> **A guard that admits optimally — right up to the bound — leaves zero margin,
> so its measured violation rate is decided by numerical tolerance rather than by
> the guard. Optimal admission is maximally brittle.**

Every real deployment carries jitter orders of magnitude above 1e-9: gossip
delay, clock skew, rounding in credit units, partial views. A guard tuned to
admit exactly to the bound is not merely unsafe under that jitter — it is
**unmeasurable**, because its violation rate is a property of the arithmetic
rather than of the design.

This is the **fifth** instance of the float-boundary species in this program and
the second time I have misdiagnosed it as something structural: first as a "seed
effect" (`research/arena/FINDINGS.md` §4), now as a scaling trend. Both times the
misreading was the flattering one.

**It also names the next question.** The useful quantity is not whether an
aggregate bound holds, but the **margin δ** it must leave below the bound to
survive staleness ε — and what throughput that margin costs, as a function of M.
An aggregate guard has to be run strictly inside its bound, and how far inside is
measurable.
