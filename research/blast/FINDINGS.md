# R-B (blast radius) — findings

**Preregistration:** `PREREGISTRATION.md`, committed `16533ed` as the only file
in this directory, BLAKE3
`d9d118b896ad991b8fbf8b1485d8b8dee377b7d63b6af69cf19c6ebce679a732`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic.

**Verdict: `BLAST-RADIUS-IS-ONE-CLUSTER`.** A2's "one defector breaks the
federation" becomes **"≈1.6 defectors per cluster,"** and cluster size is a
design parameter.

---

## 1. The result

Every topology runs at **its own δ\*** from R-H1, so `k = 0` is safe by
construction and k\* is well-defined everywhere (§4).

| mode | regime | d | clusters | δ | **k\*** | **k\* / clusters** |
|---|---|---|---|---|---|---|
| SHED | UNILATERAL | 1 | 1 | 0.295 | **2** | 2.00 |
| SHED | UNILATERAL | 2 | 23 | 0 | **37** | **1.61** |
| SHED | UNILATERAL | 3 | 64 | 0 | **103** | **1.61** |
| SHED | SUPERVISED | 1–3 | — | — | *never breaches* | — |
| SKEW | UNILATERAL | 1 | 1 | 0.295 | 23 | 23.0 |
| SKEW | UNILATERAL | 2, 3 | — | 0 | *never breaches* | — |

> **k\* rises 2 → 37 → 103 while k\*/clusters is flat at ≈1.6.** The governing
> quantity is **defectors per cluster**, not defectors total. A federation of
> 512 principals in 64 clusters tolerates 51× more defectors than the same 512
> flat.

**Blast radius measured directly:** at d=3, a defector's own cluster is driven
to **4.4e-05** of genesis while clusters without one retain **0.0074** — the same
value they retain at k = 0. Damage does not cross a cluster boundary, and the
ratio between them is **170×**.

*(The first table of this run displayed the dirty figure as "0.0000". It is not
zero; that was four-decimal rounding, caught by a test asserting an absolute
threshold. Per standing rule #2 a clean zero is a suspected artifact until
shown definitional — here it was neither, just a display width, and the claim is
a differential rather than an absolute in any case.)*

## 2. Hoarding — the derivation predicted the measurement to three figures

A2's most alarming result was that hoarding **breaches and pays 3086×**. In a
tree a hoarder can capture only *its own cluster's* commons:

| d | clusters | **derived** payoff | **measured** payoff | breaches? |
|---|---|---|---|---|
| 1 | 1 | 3086 | **3086.00** | yes (120 rounds) |
| 2 | 23 | 152 | **151.91** | yes (111 rounds) |
| 3 | 64 | 62 | **61.88** | **NO — 0 violations** |

> **At depth 3 the rational attack stops working.** A hoarder capturing
> everything it can reach cannot move global concentration past κ, because the
> most it can reach is 48 units of cluster pool instead of 3072 of federation
> pool.

This is the sharpest reversal in the containment line. A2 concluded *"the
profitable defection is also the effective one"* — under hierarchy it is
profitable and **ineffective**.

## 3. Supervision defeats shedding entirely — and the result is DEFINITIONAL

Under SUPERVISED, no k in [1, M−1] breaches, at any depth. Flat federation has
no supervised case at all: there is nothing above a principal.

**But this is not an empirical win, and reporting it as one would be wrong.**
An honest leaf proposes `want = believed − L`, landing exactly on the floor; a
SHED defector proposes `want = believed − 0`. The supervisor's check is
`believed − want ≥ L`. **The check tests precisely the quantity the defector
violates, so it separates them by construction.**

That is why `honest_refusal` measures **0.0000 everywhere** — supervision
appears free because it is not doing discriminating work, only rejecting a
proposal that is definitionally out of bounds.

> **The untested and realistic case is a defector that GAMES the check rather
> than ignoring it** — shedding to just above the floor every round, or
> misreporting its own value. Nothing here measures that, and the supervised
> column should not be read as evidence about it.

## 4. A design defect the controls caught, and the rule it broke

The preregistration asserted *"k\* ≥ 1 by construction, so a ratio is
well-defined here — unlike E1-HOLDS, whose baseline came out exactly 0.000."*

**That was wrong for the same reason E1-HOLDS was.** At δ = 0 the flat topology
already breaches with **zero** defectors (it is R-H1's flat result), so
k\*(d=1) = 0 and `k*(d=3)/k*(d=1)` divides by zero. I had explicitly checked for
this failure mode and still walked into it, one route later.

**The fix is also the better experiment:** run each topology at **its own δ\***,
so every arm starts safe and k\* measures *"how many defectors does the margin
this topology needs buy you"* — which is the question worth asking anyway.

**And a measure that measured nothing.** `clusters_damaged` was "clusters below
half of genesis" and read **64/64 at k = 0** — the honest adversarial population
already halves every cluster, so the metric was saturated by the baseline. It is
now a **differential**: value remaining in clusters *with* a defector versus
*without*.

## 5. Predictions, scored

| | prediction | outcome |
|---|---|---|
| **P-B0** | k=0 reproduces R-H1 | **CONFIRMED**, definitional as flagged |
| **P-B1** | BLAST-CONFINED: k\*(d=3) ≥ 8 × k\*(d=1) | **CONFIRMED** (103 ≥ 16). The point estimate of ~64 was **low by 61%** — I assumed 1 defector per cluster; it is 1.61 |
| **P-B2** | hoarder concentration 0.3014 → 0.0061 | **CONFIRMED to three figures**: payoff 3086 → 61.88, and hoarding stops breaching entirely at d=3 |
| **P-B3** | compartmentalisation dominates supervision | **REFUTED** — supervision defeats every shed defector at every depth. But §3: definitionally, so the refutation is weaker than it looks |
| **P-B4** | k\*/clusters roughly constant | **CONFIRMED** — 2.00, 1.61, 1.61 |
| **P-B5** | honest_refusal > 5% under supervision | **REFUTED** — exactly 0.0000, and definitionally so (§3) |

Two confirmed, two refuted, one confirmed-with-a-bad-point-estimate, one
definitional. **P-B2 is the one that matters**: a derivation fixed before the
run predicted 3086 / 152 / 62 and measurement returned 3086.00 / 151.91 / 61.88.

## 6. What this changes

**A2's verdict is narrowed, not overturned.** A cross-principal aggregate bound
is still a compliance assumption — defectors still break it. What changes is the
**price**: flat, 2 defectors out of 512; at depth 3, 103. And the invariant is
**≈1.6 defectors per cluster**, so *cluster size is the security parameter.*

For the planetary question this is the first result that makes defection a
**budgetable** risk rather than an unbounded one. Combined with R-H1 (fan-in
511 → 7) the same structural choice buys both tractability and blast-radius
containment.

**For the substrate:** B6's action-rate `CapabilitySpec` dimension should be
scoped **per cluster**, and A2's instruction to "enforce the ceiling before the
floor" is now *conditional on topology* — at depth 3 the ceiling attack cannot
breach at all, so the floor is what remains to enforce.

## 7. What this route cannot establish

1. **A defector that games the check** rather than ignoring it (§3). This is
   now the most important untested case, and the supervised column says nothing
   about it.
2. **No collusion.** Defectors are scattered across clusters by construction. An
   adversary that concentrates every defector in one cluster is a different and
   stronger threat — and given that k\*/clusters is the invariant, concentrating
   them is exactly the right attack to try next.
3. **No detection or ejection**, so every k\* is a lower bound on real tolerance.
4. **Fixed clusters.** Churn remains unaddressed; a defector that can *move*
   between clusters defeats compartmentalisation by definition.
5. **Nothing about correctness.** Consequence only; the competence bound
   remains terminal.
