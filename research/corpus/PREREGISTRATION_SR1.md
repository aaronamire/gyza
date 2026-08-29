# SR-1 — decomposition structure and outcome. PREREGISTRATION

**Committed before any association between structure and outcome was computed.**
Print this file's hash and confirm it predates `sr1_result.json`.

## 0. What I already knew when writing this — declared, because it bounds the claim

Known: n, the substantive FAIL base rate (0.117), per-repo rates (scikit-learn
0.074, pydantic 0.207), the depth distribution (median 5, mean 8.0, max 100),
and the review-residue fraction (0.306).

**Not known, and not computed until this file is committed:** the
conservation-preservation partition, its size, and **any** association between
any structural property and outcome. Every hypothesis below is about that
unseen relation.

## 1. The objective, REPLACED

The original SR-1 metric — *fraction of subtasks PROOF/SPEC-carried* — is
**unmeasurable on this substrate, and the reason is definitional rather than
practical.** PROOF-carriage requires a verifier that RECOMPUTES the property.
CI running a test suite is a finite sample over inputs, so **every** CI-derived
subtask is TEST-carried by definition. A corpus whose verdicts come from CI can
never contain a PROOF-carried subtask, for the same reason a thermometer cannot
report colour. The metric was written for Gyza's own claim vocabulary and does
not transfer.

Replaced objective, on this corpus:

- **PRIMARY** — outcome rate of the decomposition: `outcome_substantive`
  (CI PASS over CODE-SUBSTANTIVE checks only, per `check_taxonomy.py`).
- **SECONDARY** — **depth** (`n_subtasks`). Depth is the exponent in every
  chain-survival argument, so at equal outcome a shallower decomposition is
  preferred.
- **TERTIARY** — fraction of decompositions that are **conservation-preserving**,
  the only mechanically checkable structural property available here.

## 2. Definitions, fixed now

**Conservation-preserving.** A decomposition is CONSERVING iff its subtasks'
file sets are pairwise disjoint — every touched file is written by exactly one
subtask:

```
sum_i |files(subtask_i)|  ==  |union_i files(subtask_i)|
```

This is the partition/map/filter shape: work is split, not revisited. A
REVISITING decomposition writes some file in ≥2 subtasks, meaning a later
subtask edits or undoes an earlier one.

Commits with an empty file list (merges, empty commits) are **excluded from the
disjointness computation but counted in depth**, and a record whose subtasks all
have empty file lists is `UNDEFINED` and dropped from H1/H3 — not defaulted to
either class.

**Depth** = `n_subtasks`, the count of commits in the reference decomposition.

**Usable population** = the 179 records with `outcome_substantive in {PASS,
FAIL}`. The 2 records whose substantive outcome is `NONE` are excluded; an
absent verdict is not a passing one.

## 3. THE FEASIBILITY CEILING — computed before the thresholds, per standing rule #4

n = 179, FAIL events = 21, base rate p = 0.1173. Two-proportion test,
alpha 0.05 two-sided, power 0.80:

| group split | minimum DETECTABLE absolute difference |
|---|---|
| 50 / 50 | **0.167** |
| 30 / 70 | 0.190 |
| 20 / 80 | 0.226 |
| 10 / 90 | 0.319 |

**Consequences, binding:**

1. **The best case detects only a 0.167 absolute difference** — against a base
   rate of 0.117 that means the worse arm must reach ≈0.28. SR-1 is powered for
   **large effects only**. No threshold below 0.167 may be preregistered,
   because no split could reach it.
2. **A null is UNDERPOWERED-NULL, not evidence of no effect**, and must be
   reported under that name. This is stated now so it cannot be softened later.
3. **At most 2 predictors** in any logistic model (21 events, 10-EPV rule;
   2 predictors gives EPV 10.5). The two are fixed here as **depth** and
   **n_files** (size). No others may be added after seeing data.

## 4. Hypotheses, decision rules, and point predictions

**H1 (PRIMARY).** CONSERVING decompositions have a lower substantive FAIL rate
than REVISITING ones.

- *Decision rule:* SUPPORTED iff `FAIL(REVISITING) − FAIL(CONSERVING) ≥ 0.167`
  **and** a two-sided Fisher exact test gives p < 0.05. REFUTED iff the
  difference is ≤ −0.167 with p < 0.05. Otherwise **UNDERPOWERED-NULL**.
- *Point prediction:* SUPPORTED, difference ≈ 0.10 — **which is below my own
  detectability floor.** I therefore predict the honest outcome is
  UNDERPOWERED-NULL, and I am recording that I expect my primary hypothesis to
  be unresolvable at this n rather than discovering it afterwards.

**H2 (SECONDARY).** Depth is positively associated with substantive FAIL,
controlling for size.

- *Decision rule:* SUPPORTED iff the logistic coefficient on `log2(depth)` is
  positive with p < 0.05 in a model containing `log2(depth)` and
  `log10(1+n_files)` only. REFUTED iff negative with p < 0.05. Otherwise NULL.
- *Point prediction:* SUPPORTED, positive coefficient. Deeper decompositions
  accumulate more review cycles, and each cycle is another chance for CI to go
  red.
- **CONFOUND, stated in advance:** depth is not randomly assigned. A harder goal
  produces both more commits and more failures, so a positive coefficient is
  **consistent with difficulty, not evidence of causation by depth.** `n_files`
  is a weak difficulty proxy and does not remove this. No causal claim will be
  made from H2 under any result.

**H3 (TERTIARY).** What fraction of real decompositions are conservation-
preserving?

- *Descriptive; no decision rule.* Point prediction: **0.20–0.35**. Most PRs
  revisit files across commits because review comments arrive after the first
  push.

## 5. Counter-metrics — reported beside every headline, per standing rule #3

1. **Both arms' base rates and n**, never a difference alone.
2. **Per-repo breakdown** for every result. The two repos differ 2.8× in
   substantive FAIL rate, so any pooled effect must be checked for Simpson
   reversal; a pooled result that reverses within both repos is reported as
   confounded by repo.
3. **The share of CONSERVING records that are also short.** If conservation
   correlates with depth, H1 and H2 are the same finding twice.
4. **Depth distribution per arm**, since a difference in outcome could be a
   difference in size wearing a structural name.

## 6. What would make this route VOID

- If the CONSERVING arm has n < 15, H1 is not evaluated and is reported
  NOT-EVALUABLE rather than null.
- If `commit_files.json` is missing for > 10% of subtasks, the partition is
  unreliable and H1/H3 are void.
- Any exact 0 or 1 in a headline is diagnosed before reporting.

## 7. Analysis plan, fixed

One pass. Fisher exact for H1; statsmodels-free logistic via Newton–Raphson for
H2 with Wald p-values; descriptive fraction for H3. No tuning after seeing
results; implementation-bug fixes only, disclosed. Verdict comparisons go
through `gyza.canon.values_equal`.
