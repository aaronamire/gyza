# Findings — Phase 4 ablations (FREE, cache-only)

Decision first, then 4b–4e. **NOT a Route 2 rescue** (terminal decision stands).
Zero new generations — everything below is recomputed from the existing cache.
Implied revisions to `FINDINGS_CHANNEL_A.md` / `FINDINGS_SYNTHESIS.md` are given as
a DIFF at the end, **not applied**.

## 4a DECISION — A-LIVE SURVIVES (with a corrected, deployable headline)

The preregistered worry was that A1's advantage was carried by **T1** (the
irrelevant-value probe, which is oracle-informed — it varies the very quantity the
NoOp error incorporates). **Refuted.** The **content-agnostic, deployable**
detector {T2, T3, T4} — the transforms an auditor can apply *without* knowing which
quantity is irrelevant or whether the answer is homogeneous — is *stronger* than
the full set:

| detector (surface/NoOp) | J [CI] | FPR | perm p | vs re-matched SC (paired diff) |
|---|---|---|---|---|
| A1 full {T1..T5} | 0.815 [0.750, 0.876] | 0.185 | 0.0 | +0.369 [0.158, 0.571] |
| A1 no-T1 {T2,T3,T4,T5} | 0.874 [0.818, 0.927] | 0.126 | 0.0 | +0.492 [0.280, 0.692] |
| **A1 deployable {T2,T3,T4}** | **0.941 [0.898, 0.978]** | **0.059** | 0.0 | **+0.602 [0.400, 0.797]** |

The deployable J clears 0.30 with CI excluding 0, beats the cost-matched
self-consistency baseline (re-matched: SC uses the FIRST K′ resamples where K′ = the
reduced transform count for the item), and the permutation p = 0. **A-LIVE
survives; the corrected deployable headline is J ≈ 0.94.**

**Per-transform decomposition (surface, n=160, 25 wrong):**

| transform | relation | J | TPR | FPR |
|---|---|---|---|---|
| T2 rephrase | invariance | **1.000** | 1.00 | 0.000 |
| T1 irrelevant-value | invariance | 0.882 | 1.00 | 0.119 |
| T4 reorder | invariance | 0.628 | 0.68 | 0.052 |
| T3 rename | invariance | 0.141 | 0.20 | 0.059 |
| T5 scale k=3 | equivariance | 0.002 | 0.12 | 0.119 |

**Honest caveat (load-bearing):** the deployable set is **carried by T2 (rephrase),
J=1.0**. T2's perfect separation likely reflects that the rephrase de-emphasises
the NoOp clause, so the model solves the rephrased item correctly while it failed
the original — a genuine oracle-free inconsistency, but one whose power depends on
the rephrase being an *easier* phrasing, not on pure surface-keying. T3 (rename) is
weak (J=0.14) and T5 (scale) is dead (J=0.002, and a FPR contributor). So the
deployable headline rests on rephrase + reorder; whether an arbitrary rephrase
generalises is exactly what Phase 5 tests.

## 4b Compounding curves — challenge count IS a tunable security parameter (for {T2,T3,T4})

Average over ≥200 random size-K subsets per item (seed 1), surface items:

| K | {T2,T3,T4} P(fire\|wrong) | P(fire\|correct) | gap | full-set P(fire\|correct) |
|---|---|---|---|---|
| 1 | 0.617 | 0.038 | 0.580 | 0.072 |
| 2 | 0.899 | 0.057 | 0.843 | 0.108 |
| 3 | 1.000 | 0.059 | **0.941** | 0.134 |
| 4 | — | — | — | 0.160 |
| 5 | — | — | — | 0.185 |

For **{T2,T3,T4}** the wrong-curve rises steeply (0.62 → 1.0) while the correct-curve
stays **flat** (0.038 → 0.059) — so more challenges buy real security at ~no
false-positive cost; the gap is maximised at **K=3 (0.94)**. For the **full set**,
the correct-curve *rises* with K (0.072 → 0.185) because T1/T5 keep adding false
convictions. This independently confirms {T2,T3,T4} as the right set and T1/T5 as
FPR sources.

## 4c LR / precision (the right summary for a bonded market)

| detector (surface) | TPR | FPR | **LR = TPR/FPR** | precision | base rate wrong |
|---|---|---|---|---|---|
| A1 full | 1.00 | 0.185 | 5.4 | 0.50 | 0.156 |
| A1 deployable {T2,T3,T4} | 1.00 | 0.059 | 16.9 | 0.76 | 0.156 |
| **A2 inversion** | 0.55 | **0.015** | **36.8** | **0.86** | 0.156 |

**Slashing vs flagging.** A violation only proves the two answers *disagree*, not
which is wrong — so a botched transform-solve on a *correct* original convicts an
honest defender; this makes A1's FPR structural. **A2 inversion** (FPR 0.015, LR
36.8) is the only detector with a false-conviction rate low enough to plausibly
support **slashing**. A1 deployable (FPR 0.059) and especially A1 full (FPR 0.185)
are **flag-for-review**, not slash — the honest-defender false-conviction cost is
too high.

## 4d The two-stage gate (SC-stability × A1) — clean ACCEPT + ESCALATE, but CONVICT still needs A2

Cross-tab, surface items, deployable A1:

| cell | n | wrong | P(wrong) |
|---|---|---|---|
| SC-stable & A1 fires (**CONVICT**) | 21 | 15 | 0.714 |
| SC-stable & A1 quiet (**ACCEPT**) | 121 | **0** | **0.000** |
| SC-unstable & A1 fires (**ESCALATE**) | 12 | 10 | 0.833 |
| SC-unstable & A1 quiet (**ESCALATE**) | 6 | 0 | 0.000 |

**Three-way rule:** CONVICT if SC-stable & A1{T2,T3,T4} fires; ACCEPT if SC-stable &
A1 quiet; ESCALATE (→ Route 1 ground truth) if SC-unstable. **ACCEPT is clean** (121
items, **zero** errors) and **ESCALATE** isolates 18 uninformative claims. But the
**CONVICT cell precision is 0.714** (6 false convictions of 21) and FPR-within-
SC-stable is 0.047 — better than raw A1 (0.185) but still not slashing-grade. So the
gate is valuable for triage (perfect accept, explicit escalate) but **A2 inversion
remains the slashing primitive**, not gated-A1.

## 4e Channel B re-analysis

**LR per condition:** ASSIGNED-vs-TRUE **8.26** (violation 0.471 / 0.057), HELD-vs-TRUE
**1.25** (0.690 / 0.552). A protocol that convicts honest defenders at 0.552
(B-TRUE on hard/held items) **cannot support a bonded market in that regime**;
ASSIGNED LR 8.3 (deter strategic fraud) is deployable, HELD LR 1.25 (cannot separate
sincere error) is not.

**Per-round cumulative violation:**

| condition | after 1 | 2 | 3 |
|---|---|---|---|
| B-TRUE (hard/held items) | 0.138 | 0.552 | 0.552 |
| B-HELD | 0.517 | 0.759 | 0.862 |
| B-ASSIGNED | 0.400 | 0.521 | 0.557 |
| **B-TRUE (solvable items)** | **0.000** | **0.057** | **0.057** |

Defending truth on **solvable** items stays **flat and near-zero** across rounds,
while B-ASSIGNED climbs to 0.56 — so the ASSIGNED−TRUE gap **grows with challenge
count**: challenge count is a tunable *deterrent* for strategic fraud. On **hard**
items the B-TRUE baseline itself climbs to 0.55, so the held gap does **not** open up
with rounds — the sincere-error case stays indistinguishable.

**Maintainability gate:** does SC-instability predict B-TRUE (held) violation? No —
P(B-TRUE viol | SC-unstable) 0.46 vs | SC-stable 0.625, diff −0.16 [−0.52, 0.21] (CI
includes 0, wrong sign, n=29). **No ground-truth-free ex-ante gate for Channel B via
SC-instability.**

**Selection artifact (limitation, not a discovery):** B-HELD items were selected
*because* the model failed on them natively, so "defend the truth" there is "defend a
truth you do not understand" — the sincere-error null is **partly definitional**.

## Implied DIFF to FINDINGS_CHANNEL_A.md (NOT applied)

```diff
@@ DECISION @@
- On surface-keyed (NoOp) items the metamorphic detector A1 has J = 0.815 [0.748, 0.879]
+ On surface-keyed (NoOp) items the DEPLOYABLE content-agnostic detector A1{T2,T3,T4}
+ has J = 0.941 [0.898, 0.978], FPR 0.059, and beats re-matched self-consistency
+ +0.602 [0.400, 0.797]. (The full {T1..T5} set is J=0.815 but T1 is oracle-informed
+ and T5 dead; the ablation shows the content-agnostic subset is STRONGER, refuting the
+ worry that T1 carried the result. Caveat: the deployable set is carried by T2 rephrase,
+ J=1.0, whose power may partly reflect rephrase-clarity — tested in Phase 5.)
@@ deployability @@
+ For a bonded market use the LR: A2 inversion LR=36.8 (FPR 0.015) is slashing-grade;
+ A1 deployable LR=16.9 is flag-grade; challenge count is a tunable security parameter
+ ({T2,T3,T4} wrong-curve rises to 1.0 while the correct-curve stays flat at ~0.06).
```

## Implied DIFF to FINDINGS_SYNTHESIS.md (NOT applied)

```diff
@@ cost per challenge / mechanism design @@
+ A two-stage gate (SC-stability × A1{T2,T3,T4}) yields a clean ACCEPT (121 items, 0
+ errors) and an explicit ESCALATE→Route-1 class (SC-unstable). For slashing use A2
+ inversion (LR 36.8, FPR 0.015); A1 for flagging. Challenge count is a tunable
+ deterrent in BOTH channels (A: wrong-curve→1.0, correct flat; B: ASSIGNED−TRUE gap
+ grows with rounds while solvable-item TRUE stays ~0.06).
```
