# R-T — the targeted asymmetric adversary: findings

**Preregistration:** `PREREGISTRATION.md`, committed `b329bc0` as the only file
in this directory, BLAKE3
`d4b4954a0e225b8348514e50feae1f2ae730ebadfd60d3c1a6afcf50d69d2cda`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic.

**Verdict: `THE-DENOMINATOR-IS-THE-ONLY-LEVER`.** The attack R-D named as the
sharpest open threat **does not work at all**. A different property of placement,
which this route did not hypothesise, **halves k\***. And the quantity governing
breach is **extensive** — total remaining value — which is precisely the quantity
a ratio bound does not measure.

> **This section was first published as `COVERAGE-IS-THE-INVARIANT` and that was
> wrong.** Cluster coverage is exact across five arms at d = 3 and is
> **falsified at d = 2** (§2.1). It is a topology-specific proxy, not the
> invariant — the same species of error this route's own CORRECTIONS 28 names.
> Corrected in the commit after, from a check the route's §6.1 called for.

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

## 2. At d = 3: 55 clusters covered, in every arm, exactly

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

> **At d = 3, a breach requires ≥ 55 of 64 clusters (85.9%) to contain at least
> one defector.** Exact across five arms — and, as §2.1 shows, true of this
> topology rather than of the mechanism.

### 2.1 Coverage is a PROXY, and d = 2 falsifies it

§6.1 warned that 55/64 was one topology's number and that R-B's 1.61 had looked
stable across two topologies before turning out to be an artifact. Running d = 2
(f = 23, 23 clusters):

| d | arm | k\* | k\*/clusters | covered | coverage |
|---|---|---|---|---|---|
| 2 | RANDOM | 37 | 1.61 | 21 | 0.913 |
| 2 | EVEN_ALL | **25** | 1.09 | **23** | **1.000** |
| 3 | RANDOM | 103 | 1.61 | 55 | 0.859 |
| 3 | EVEN_ALL | 55 | 0.86 | 55 | 0.859 |

**Coverage is not invariant: 0.859 at d = 3, 0.913 and 1.000 at d = 2.** The
1.000 is a **saturated metric** — 25 defectors over 23 clusters — and a measure
pinned at its maximum reports the maximum, not the treatment. That is the third
occurrence of the species in this program (R-B's `clusters_damaged` 64/64, R-D's
`clusters_below_half` 64/64).

The decisive pair is one row apart:

| d | arm | k | covered | total | breach |
|---|---|---|---|---|---|
| 2 | EVEN_ALL | 24 | **23 (full)** | 23.598 | **no** |
| 2 | EVEN_ALL | 25 | **23 (full)** | 23.252 | **yes** |

**Identical coverage, opposite verdicts.** Coverage cannot be the governing
quantity. With f = 23 a single defector destroys a smaller *fraction* of its
cluster than at f = 8, so full coverage is necessary and not sufficient.

## 3. Why: the adversary cannot move the numerator

`max` is **14.001 in every arm, every k, every seed** — including CONCENTRATE,
which places seven defectors inside the target's own cluster. The numerator is
inert. Breach is achieved entirely by shrinking the denominator, and **at
d = 3** the denominator is linear in coverage:

| coverage | 48 | 49 | 53 | 54 | 55 |
|---|---|---|---|---|---|
| total | 29.505 | 28.550 | 24.740 | 23.994 | **23.039** |

Slope ≈ **−0.955 per cluster covered**. Breach requires
`total < max/κ = 14.001/0.60 = 23.335`, which falls between coverage 54 and 55 —
**exactly where every arm flips.** Solving the line gives `c ≥ 54.69`, so
`c = 55`, matching all five arms case by case.

### 3.1 The invariant that DOES hold, at both depths

`total < max/κ` predicts breach in **8 of 8 rows across both depths and both
arms**, with no exceptions:

| d | arm | k | max | total | max/κ | breach |
|---|---|---|---|---|---|---|
| 2 | RANDOM | 36 → 37 | 14.000 | 24.713 → **23.004** | 23.334 | no → **yes** |
| 2 | EVEN_ALL | 24 → 25 | 14.003 | 23.598 → **23.252** | 23.339 | no → **yes** |
| 3 | RANDOM | 102 → 103 | 14.001 | 23.785 → **22.831** | 23.335 | no → **yes** |
| 3 | EVEN_ALL | 54 → 55 | 14.001 | 23.994 → **23.039** | 23.335 | no → **yes** |

**The relation `max/total > κ ⟺ total < max/κ` is an identity, and stating it is
not the finding.** The finding is that **`max` is inert** — 14.000 to 14.003
across every arm, every k, and both depths — so the identity's right-hand side is
a *constant*, and breach is governed by `total` alone.

> **The only lever an adversary has against this ratio bound is the extensive
> quantity in its denominator. Coverage, defectors-per-cluster and defector
> count are all proxies for how much total value gets destroyed, and each is
> exact only in the topology it was measured in.**

**This is R-E's result arriving from the other side.** R-E found a ratio bound is
blind to how much value exists. R-T finds a ratio bound is breached *only*
through that same quantity. **The bound is defeated through precisely the thing
it does not measure** — which is an argument for declaring the extensive bound
alongside it, and R-E §2.1 prices that at zero for a 2% floor.

## 4. What this does to R-B's published invariant

R-B's headline is *"the governing quantity is defectors per cluster, not
defectors total"*, at ≈1.61. That number is **an artifact of random placement** —
it is what a Poisson process costs to reach 55-cluster coverage, since random
placement wastes defectors by doubling them into clusters already covered.

**The governing quantity is neither defectors total nor defectors per cluster** —
and, per §2.1, it is **not cluster coverage either**, which is what this document
first claimed. It is **total remaining value**, and all three of those are
topology-specific proxies for it. R-B's *direction* stands (topology bounds
damage; k\* rises with depth); the quantity it named does not. Indexed as
CORRECTIONS 28, with my own overclaim as CORRECTIONS 29.

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

1. **RESOLVED, AGAINST THIS DOCUMENT'S FIRST CLAIM.** This limitation read
   *"whether the fraction is stable across depth is untested… R-B's 1.61 looked
   stable across two topologies too, and it was an artifact."* Running d = 2
   falsified it within the hour (§2.1). The limitation was correctly identified
   and the claim was published anyway; **writing the caveat is not a substitute
   for running the check.**
2. **The linear coverage→total relation is d = 3 only** (§3), and §2.1 shows
   the coefficient must change with fan-out since a defector in a 23-leaf
   cluster destroys a smaller fraction than one in an 8-leaf cluster. It
   explains the d = 3 threshold; it does not predict d = 2's.
3. **`total < max/κ` is an identity, not a discovery.** Its content is entirely
   that `max` is inert in this environment, measured over 8 rows and two
   depths. An environment where an adversary CAN raise the numerator — by
   acquisition, merger, or a HOARD defector that becomes the max — is not
   covered, and R-B's HOARD mode is exactly that case, untested here.
4. **The adversary is given the target's identity for free**, and it turns out
   not to matter — which weakens the realism objection but also means this route
   never tested target *discovery*.
5. **One aggregate.** The ratio only, and §3 shows that for this environment the
   ratio is breached through its denominator. An extensive bound would be
   breached far earlier and is priced separately (R-E §2.1).
6. **Placement only.** Modes and regimes are R-B's; a defector that games a
   check rather than ignoring it remains untested (R-B §7.1).
7. **Nothing about correctness.** Consequence only.
