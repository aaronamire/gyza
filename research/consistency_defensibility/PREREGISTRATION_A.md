# Pre-registration — Channel A (consistency mechanisms)

Committed BEFORE any Phase 2 generation. Git history is the timestamp. Not
edited after data is seen.

**NOT a Route 2 rescue.** The Route 2 terminal decision
(UNFALSIFIABLE-IN-PRACTICE) stands. Channel A tests a structurally different
trust source — single-agent **consistency** (does a claim survive
semantics-preserving transformation?) — which needs no independence between
agents.

## Claim under test

A true answer is invariant under a semantics-preserving transformation and
scales predictably under an equivariant one; a **surface-keyed** error is not.
Detecting an inconsistency proves ≥1 claim is false with **no oracle**. The
audited claim is each model's cached **round-3 COT answer** to the item as given;
transformations are the audit.

## Item + transform set

- Items: `route3_attractor/items.json` (sha256[:16] = e0d9fedd108aff4f), 80,
  all with machine-verified true answers.
- Transforms: `transforms.json` (**sha256[:16] = b8166ff456fa61cf**), **288
  transforms, all 288 machine-verified** (2c): invariance → transformed_true ==
  item true; equivariance_k3 → == 3× true. Per relation: T2 80, T3 67, T5 61,
  T1 40, T4 40. Declared: invariance 227, equivariance_k3 61. Transforms are
  REGENERATED from each item's recovered numeric structure (not string edits),
  so the declared relation holds by construction. Exclusions: none.

## Roster + method

meta-llama/llama-3.1-70b-instruct, google/gemma-2-27b-it,
mistralai/mistral-small-3.2-24b-instruct, microsoft/phi-4. COT, temp 0 (sampling
arm temp 0.7). **Power limitation, stated up front:** llama-COT escaped 21/22
round-3 attractor items, so it carries almost no surface-keyed error; detection
power rests mainly on **gemma-2**. Per-model results reported; no pooling over a
model with nothing to detect.

## The four mechanisms

- **A1 METAMORPHIC** — solve each transformed item; violation = the model's
  transformed answer contradicts the declared relation to its ORIGINAL answer
  (T1 irrelevant-value / T2 rephrase / T3 rename / T4 reorder = invariance; T5
  scale k=3 = equivariance). Oracle-free. Detector fires iff ≥1 transform
  violates; graded = fraction violated.
- **A2 INVERSION** — give the model the original statement + its own candidate
  answer; it returns VALID/INVALID. Fires iff INVALID.
- **A3 TRACE–CONCLUSION COHERENCE** — a second model (gemma-2) sees ONLY the
  first model's reasoning trace and states the entailed conclusion; fires iff ≠
  the stated final answer. **JUDGE-DEPENDENT — reported separately, never pooled
  with A1/A2/A4.**
- **A4 ENTAILMENT NET** (NoOp) — ask the (start, removed, remaining) triple;
  fires iff remaining ≠ start − removed (mechanical constraint).

A non-answer on either side of any relation is EXCLUDED (never a violation,
never agreement).

## The cost-matched baseline (the crux, 2e)

**SELF-CONSISTENCY:** resample the SAME unmodified item K times at temp 0.7,
K = the number of transforms applied to that item (EXACT cost match). Fires iff
the K samples are not unanimous under canonical equivalence. Any claimed A1
advantage must be over THIS, reported as the paired J difference (A1 − SC) with
a bootstrap CI over items.

## Metrics (per mechanism, per category, pooled)

Ground truth (wrong = original COT answer ≠ true) is for EVALUATION only, never
used by a detector. Report **all three** of TPR = P(fire | wrong),
FPR = P(fire | correct), firing rate = P(fire) — a detector that always fires has
TPR=1 and is worthless. Primary summary: **Youden J = TPR − FPR**, bootstrap CI
over ITEMS. Also: graded-score AUC, PERMUTATION NULL over items (3000×, empirical
p — J compared against this, never 0 alone), precision, and the wrongness base
rate.

## The predicted dissociation (the real hypothesis, 2g)

- **SURFACE-KEYED (ii_noop)**: the error latches onto an irrelevant surface
  feature → tracks the feature → invariance violated → **DETECTABLE** (predict
  high J).
- **CONCEPT-KEYED (i_classic)**: a stable memorized misconception is a belief,
  invariant to rephrasing exactly as truth is → **UNDETECTABLE** (predict J ≈ 0).

J reported separately for the two classes. **The dissociation is the headline; a
pooled J alone is NOT reported as the headline.**

## Decision rule (2h)

- **A-LIVE**: on surface-keyed items, J > 0.30 with CI excluding 0 AND
  perm-null p < 0.05 AND J exceeds the cost-matched self-consistency baseline
  (paired-diff CI excludes 0).
- **A-WEAK**: J > 0 with CI excluding 0 but ≤ 0.30, or not clearly above
  self-consistency.
- **A-DEAD**: J CI includes 0 on surface-keyed items.
Concept-keyed J reported alongside in every case.

## Point predictions (stated now)

A1 J on NoOp ≈ 0.4–0.7; A1 J on classic ≈ 0–0.15; self-consistency J on NoOp
≈ 0–0.15 (systematic errors are resample-stable); A2 inversion J ≈ 0.2–0.5;
A4 J ≈ 0.2–0.4; A3 judge-dependent and likely noisy. Prior: **45% A-LIVE /
35% A-WEAK / 20% A-DEAD.** Report which fired. Any single item/model driving a
cell → report that cell inconclusive.

## Determinism

SEED = 1. Greedy temp 0 except the self-consistency sampling arm (temp 0.7,
per-sample seeds). Every generation cached; no call repeated.
