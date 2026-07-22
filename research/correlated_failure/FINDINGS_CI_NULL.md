# Findings — conditional-independence null (the real H2 test)

Reanalysis of the cached OpenRouter code battery. No new generations. The
question: is the published "universal blind spot" (within ≈ cross ≈ 13× the
permutation null) a genuine shared blind spot, or an artifact of a small
per-problem wrong-answer space?

## Headline — Case A: the convergence is problem-structural

**Mean cross-family excess over the leave-pair-out population baseline =
−0.024, 95% CI [−0.052, +0.001] — includes 0.** A cross-family pair, on
the problems where both are wrong, agrees *no more often than two random
other wrong models do*. Within-family excess = +0.026 [−0.013, +0.065] —
also includes 0.

> **Case A fires:** both excess CIs include 0 ⇒ the convergence is entirely
> explained by the population's per-problem wrong-answer structure. Family
> is irrelevant either way. The "universal blind spot" must be restated as
> a **constrained wrong-answer space**.

The permutation null (0.044) was the *wrong* null. It only asks whether the
wrong-answer distribution is non-degenerate *across problems* (it is — so
convergence sits ~13× above it). It does **not** ask whether a specific
pair correlates *beyond the per-problem structure*. Against the right null,
it does not.

## Reproduce-first gate (unchanged codebench metric, from cache)

| | mean | 95% CI | null | pairs |
|---|---|---|---|---|
| within | 0.6027 | [0.563, 0.643] | 0.044 | 2 |
| cross | 0.5602 | [0.533, 0.586] | 0.044 | 13 |

R = 1.076. Matches the published numbers exactly (±0.000). 6 in-band models
{llama-3.1-70b, gemma-2-27b, gemma-3-27b, mistral-2501, mistral-3.2, phi-4}.

## Layer 1 — observed vs the population baseline

The baseline (P two *other* wrong models agree, leave-pair-out) is
**0.584 [0.577, 0.591]** for cross pairs and **0.576 [0.575, 0.578]** for
within — i.e. essentially equal to the observed convergence. Observed minus
baseline is the excess above:

| variant | within excess (CI) | cross excess (CI) | reads as |
|---|---|---|---|
| **R1 in-band ref (primary)** | +0.026 [−0.013, +0.065] | **−0.024 [−0.052, +0.001]** | both ~0 → Case A |
| R2 all-9 ref (weak-inclusive) | +0.364 [+0.326, +0.401] | +0.319 [+0.292, +0.343] | positive, but see note |
| R3 distinct_wrong ≥ 3 (12 probs) | −0.068 [−0.205, +0.070] | +0.004 [−0.079, +0.088] | both ~0 |
| ERR-sensitivity (exclude all-ERR) | +0.001 [−0.069, +0.071] | −0.000 [−0.021, +0.020] | both ~0 |

**Per pair, the biggest cross pairs converge *below* baseline:**
llama-3.1×mistral-2501 −0.131, llama-3.1×phi-4 −0.121, llama-3.1×mistral-3.2
−0.054. No cross pair's excess is convincingly positive.

**R2 note (the wider-pool caveat, as predicted).** Adding the three
band-excluded models back (llama-3.3 0.08, mistral-3.1 0.18, qwen 0.12 pass
rates) drops the baseline to ~0.24, because those weak models fail
*diversely* — they do not pile onto the same wrong answers. So the in-band
pairs' 0.56–0.60 sits far above a *capability-heterogeneous* baseline. That
excess is a **capability-homogeneity effect, not a family effect**: within
(+0.364) ≈ cross (+0.319), so family is still irrelevant even here. R2 is
the biased-high direction the pre-analysis flagged (weak-model junk in the
reference); R1 (capability-matched reference) is the clean test and shows
excess ≈ 0.

**R3 note.** Restricting to the 12 problems with ≥3 distinct wrong answers
(a genuinely non-tiny space) collapses observed convergence from 0.56 to
~0.17 and leaves excess ≈ 0 — the convergence was carried by tiny-space
problems, and even on rich-space problems pairs do not correlate beyond
baseline.

### Within-reference caveat (stated plainly)

Only 2 same-family models per family clear the band, so the leave-pair-out
reference for a **within** pair is composed *entirely of other families*.
Within-excess is therefore a within-vs-cross-family contrast, **not**
family-neutral. A positive within-excess would have hinted that family adds
correlation; it is +0.026 and its CI includes 0, so it does not. This is
exactly why R2 (wider pool) and Layer 2 (pair-independent) matter — and both
agree with R1.

## Layer 2 — how concentrated is the wrong-answer space itself

Pair-independent. Over all in-band models wrong on a problem:

| statistic | median | IQR | n |
|---|---|---|---|
| Simpson agreement (P two wrong models agree) | **0.60** | [0.20, 1.00] | 34 |
| distinct wrong signatures | **1.0** | [0, 2] | 50 |
| effective # wrong answers (1/Σpᵢ²) | 1.43 | [1.0, 2.78] | 50 |
| # models wrong (m) | 5.0 | [0, 6] | 50 |

The median problem has **a single distinct wrong answer** shared by all
wrong models, and the median Simpson agreement is 0.60 — far above the
≳0.4 threshold at which convergence is "space-driven." Excluding all-ERR
signatures still leaves median Simpson 0.43. The wrong-answer space on these
MBPP problems, for capable-but-wrong models, is *tiny*: when they fail, they
fail into the same one or two behaviors, regardless of family.

The 90 highest-weight agreements are all-`ERR` (both programs raise the
identical exceptions on the same problems). These are counted as shared
behavior in the primary (codebench defines "behavior" to include
exceptions), which is why there is **no artifact-#4 contamination**: zero of
the agreements are TIMEOUT/IMPORTERR "no program ran" collisions. Excluding
all-ERR too (ERR-sensitivity) drops observed to 0.36 but leaves the excess
at 0 — the Case-A conclusion does not depend on the ERR choice.

## What this does and does not change about the universal-blind-spot claim

**Does NOT change (the decision survives):** family diversity does not
decorrelate failure. Within ≈ cross excess ≈ 0 across every variant; mixing
families buys nothing. For Gyza, diversity remains an unreliable defense and
the settlement-primary + external-resolution backstop is still the load-
bearing mechanism. If anything this is *stronger*: the failure correlation
is not even family-shaped — it is problem-shaped.

**DOES change (the mechanism, and the words):** the convergence is **not**
evidence of a *shared cognitive blind spot* across model families. It is a
**constrained wrong-answer space**: on these problems the set of wrong
behaviors a capable model can emit is so small that any two wrong models —
same family or not — land on the same wrong answer at the base rate. The
"~13× above null" framing overstates the phenomenon by using a null that
cannot see per-problem pair-specificity. The honest headline is "constrained
wrong-answer space," not "shared cognition."

## Honesty

Layer 1 answers exactly one question: *does pair/family identity add
correlation beyond problem structure?* Answer: no (excess ≈ 0). Neither
layer can separate "genuine universal shared cognition" from "intrinsically
small wrong-answer space" — Layer 2 only **bounds** the latter (and finds it
large: median 1 distinct wrong answer). What we can say cleanly is that
whatever convergence exists is problem-structural and family-invariant; what
we cannot say is that it reflects shared reasoning. N = 50 problems, seed 1;
full per-pair and per-problem tables in `ci_null_result.json`.

---

## Implied edit to FINDINGS.md (diff — do NOT overwrite)

The result does not overturn the H2 decision but reframes the mechanism.
The minimal honest edit to the FINDINGS.md headline block:

```diff
@@ FINDINGS.md — DECISIVE RESULT section @@
-## DECISIVE RESULT (wider menu, capable models) — H2 FALSIFIED: universal blind spot
+## DECISIVE RESULT (wider menu, capable models) — H2 FALSIFIED: family-invariant failure
+
+> **Mechanism corrected (conditional-independence null, FINDINGS_CI_NULL.md).**
+> Against the *right* null — the leave-pair-out per-problem wrong-answer
+> distribution — cross-family excess is −0.024 [−0.052, +0.001] and
+> within-family excess is +0.026 [−0.013, +0.065]: both include 0 (Case A).
+> The convergence is **problem-structural**, not a shared cognitive blind
+> spot. Median distinct wrong answers per problem = 1 (Simpson 0.60). Read
+> "universal blind spot" below as **constrained wrong-answer space**: the
+> family-invariance of failure stands; the "shared cognition" reading does
+> not. The ~13× permutation null cannot see pair-specificity and overstates
+> the effect.
@@ within ≈ cross line @@
-- Pre-registered decision rule: *0.8 ≤ R ≤ 1.2 and both > null ⇒ H2
-  FALSIFIED, universal blind spot.* R = 1.08, both ~13× null ⇒
-  **H2 is FALSIFIED. The blind spot is UNIVERSAL.** Mixing families does
-  **not** decorrelate failure on the confound-free test.
+- Pre-registered decision rule: *0.8 ≤ R ≤ 1.2 and both > null ⇒ H2
+  FALSIFIED.* R = 1.08 ⇒ **H2 is FALSIFIED: mixing families does not
+  decorrelate failure.** But the correct null (conditional-independence,
+  not permutation) shows the shared failure is a **constrained wrong-answer
+  space**, not a shared blind spot — family-invariant because it is
+  problem-driven. Diversity still cannot help; the reason is the small
+  answer space, and only external resolution breaks it.
```
