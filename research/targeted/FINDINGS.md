# R-T — the targeted asymmetric adversary: findings

**Preregistration:** `PREREGISTRATION.md`, committed `b329bc0` as the only file
in this directory, BLAKE3
`d4b4954a0e225b8348514e50feae1f2ae730ebadfd60d3c1a6afcf50d69d2cda`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic.

**Verdict: `COVERAGE-IS-THE-INVARIANT`.** The attack R-D named as the sharpest
open threat **does not work at all**. A different property of placement, which
this route did not hypothesise, **halves k\*** — and the quantity governing
breach turns out to be exact, identical across five structurally different
adversaries, and **not the one R-B published**.

---

## 1. The 2×2: sparing does nothing, evenness halves k\*

| arm | spares target? | even? | k\* | k\*/clusters | clusters covered |
|---|---|---|---|---|---|
| CONCENTRATE | no (7 in it) | no | 109 | 1.70 | **55** |
| **RANDOM** (control) | no | no | **103** | 1.61 | **55** |
| SPARE | **yes** | no | **105** | 1.67 | **55** |
| EVEN_ALL | no | **yes** | **55** | 0.86 | **55** |
| SPARE_EVEN | yes | yes | **55** | 0.87 | **55** |

**Deliberately sparing the target's cluster makes the attack slightly WORSE**
(103 → 105). **Placing defectors evenly nearly halves k\*** (103 → 55, 1.87×).

R-D's prescription — *"an attacker must maximise asymmetry, not damage"* — is
**wrong as stated**. The adversary cannot create asymmetry at all (§3). What it
can do is stop wasting defectors.

**The preregistered arms varied two factors at once**, and could not attribute
between them. `EVEN_ALL` was added after the k = 103 mechanism check to complete
the 2×2. It is **not preregistered**, is a decomposition control rather than a
hypothesis test, and no decision rule reads it.

## 2. The invariant: 55 clusters covered, in every arm, exactly

`k*/clusters` ranges over 0.86 → 1.70, a factor of two. **`clusters_covered` is
55 in all five arms.** Per seed, at k\*−1 and k\*:

| arm | k | per-seed coverage | violations per seed |
|---|---|---|---|
| RANDOM | 102 | [53, 48, **54**] | [0, 0, **0**] |
| RANDOM | 103 | [53, 49, **55**] | [0, 0, **11**] |
| EVEN_ALL | 54 | [54, 54, 54] | [0, 0, 0] |
| EVEN_ALL | 55 | [55, 55, 55] | [5, 5, 5] |

**Coverage predicts breach seed-by-seed, not merely in aggregate.** In the
random arms, the two seeds at coverage 53 and 49 do not breach; the single seed
that reaches 55 does, with 11 violations. Coverage 54 never breaches in any arm;
55 always does.

> **A breach requires ≥ 55 of 64 clusters (85.9%) to contain at least one
> defector. The number of defectors is irrelevant except as a means to that
> coverage.**

## 3. Why: the adversary cannot move the numerator

`max` is **14.001 in every arm, every k, every seed** — including CONCENTRATE,
which places seven defectors inside the target's own cluster. The numerator is
inert. Breach is achieved entirely by shrinking the denominator, and the
denominator is **linear in coverage**:

| coverage | 48 | 49 | 53 | 54 | 55 |
|---|---|---|---|---|---|
| total | 29.505 | 28.550 | 24.740 | 23.994 | **23.039** |

Slope ≈ **−0.955 per cluster covered**. Breach requires
`total < max/κ = 14.001/0.60 = 23.335`, which falls between coverage 54 and 55 —
**exactly where every arm flips.** Solving the line gives `c ≥ 54.69`, so
`c = 55`, matching all five arms case by case.

**This is R-E's result arriving from the other side.** R-E found a ratio bound
is blind to how much value exists. R-T finds that a ratio bound is breached
*only* through that same quantity. The denominator is the extensive quantity the
ratio does not bound, and it is the only thing an adversary here can touch.

## 4. What this does to R-B's published invariant

R-B's headline is *"the governing quantity is defectors per cluster, not
defectors total"*, at ≈1.61. That number is **an artifact of random placement** —
it is what a Poisson process costs to reach 55-cluster coverage, since random
placement wastes defectors by doubling them into clusters already covered.

**The governing quantity is neither defectors total nor defectors per cluster.
It is the fraction of clusters containing at least one defector**, and it is
0.859 in every arm. R-B's *direction* stands (topology bounds damage; k\* rises
with depth); the quantity it named does not. Indexed as CORRECTIONS 28.

The safety consequence is that **R-B's k\* = 103 is loose by 1.87×.** The
honest tolerance figure for this environment is **55**, not 103.

## 5. Predictions, scored — three refuted

| | prediction | outcome |
|---|---|---|
| **P-T0** | RANDOM reproduces k\* = 103 | **CONFIRMED exactly** |
| **P-T1** | TARGETING-HELPS: k\*(SPARE_EVEN) < 103 | **CONFIRMED (55) — but for a mechanism I did not predict.** The sparing I hypothesised contributes nothing; SPARE alone measures 105 |
| **P-T2** | k\*(SPARE_EVEN) ∈ [85, 102] | **REFUTED — 55, low by 35%.** My +1.07% numerator argument was arithmetically right and second-order; the coverage effect I never considered is ~2× larger |
| **P-T3** | TARGETING-BREAKS refuted (k\* > 52) — *the route's bet* | **CONFIRMED at 55, by three defectors.** Preregistered, but the margin is thin enough that it should be read as "no clean 2× break", not as a comfortable safety result |
| **P-T4** | ASYMMETRY-ORDERS monotone | **REFUTED** — SPARE (105) exceeds RANDOM (103); the ordering is non-monotone at exactly the step the route was built to test |
| **P-T5** | k\*(SPARE_EVEN) < k\*(SPARE) | **CONFIRMED** — 55 vs 105 |

**MECHANISM-RUNS** passed: SPARE arms place 0 defectors in cluster 0 and
CONCENTRATE places 7, measured rather than assumed. **Honest refusal is 0.0000
in every arm** — no honest principal was ever blocked, so none of these k\*
values is bought with a throughput cost.

## 6. What this route cannot establish

1. **The coverage threshold is one environment's number.** 55/64 = 0.859 was
   measured at d = 3, f = 8, δ = 0, ε = 1. Whether the *fraction* is stable
   across depth, fan-out and margin is untested and is the obvious next
   question — R-B's 1.61 looked stable across d = 2 and d = 3 too, and it was
   an artifact.
2. **The linear coverage→total relation is fitted over five points from one
   sweep**, and is used to explain the threshold, not to predict a new one.
   Standing discipline treats a closed form as an optimisation validated case
   by case; it agreed with all five arms here and that is the whole evidence.
3. **The adversary is given the target's identity for free**, and it turns out
   not to matter — which weakens the realism objection but also means this route
   never tested target *discovery*.
4. **One aggregate.** The ratio only, and §3 shows that for this environment the
   ratio is breached through its denominator. An extensive bound would be
   breached far earlier and is priced separately (R-E §2.1).
5. **Placement only.** Modes and regimes are R-B's; a defector that games a
   check rather than ignoring it remains untested (R-B §7.1).
6. **Nothing about correctness.** Consequence only.
