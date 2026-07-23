# Findings — Channel A (consistency mechanisms)

Decision first, then the dissociation table, then TPR/FPR/firing rate, then
honest limits. **NOT a Route 2 rescue:** the Route 2 terminal decision
(UNFALSIFIABLE-IN-PRACTICE) stands. Channel A is a *different* trust source —
single-agent consistency under transformation — needing no independence.

## DECISION — A-LIVE (with a corrected dissociation)

On surface-keyed (NoOp) items the metamorphic detector A1 has **J = 0.815
[0.748, 0.879]** (permutation p = 0.0), and it **beats the cost-matched
self-consistency baseline by +0.367 [0.164, 0.566]** (paired, over items). All
three preregistered A-LIVE conditions are met. This is the **first positive
result in the whole program** — and unlike Route 2 it does not depend on error
independence; it depends only on a true answer being invariant under a
transformation that a surface-keyed error is not.

**But the preregistered dissociation was wrong in an instructive way.** I
predicted concept-keyed J ≈ 0 (undetectable). It is **0.544 [0.208, 0.849]** —
concept errors *are* detectable. The real, clean dissociation is not
detectable-vs-undetectable; it is **where metamorphic testing beats cheap
resampling**:

| stratum | A1 J | self-consistency J | **A1 − SC (paired, over items)** |
|---|---|---|---|
| **surface (NoOp)** | 0.815 | 0.448 | **+0.367 [0.164, 0.566]** ✓ excludes 0 |
| concept (classic) | 0.544 | 0.520 | **+0.024 [−0.342, 0.391]** ✗ includes 0 |
| substitution | 0.013 | — | (dead; 9 errors) |

So: **metamorphic transformation's ADVANTAGE over cost-matched self-consistency
is surface-specific.** Surface-keyed errors are *resample-stable* (the model
gives the same attractor at temp 0.7) but *transform-unstable* — only
transformation catches them (SC TPR 0.56 vs A1 TPR 1.0 on NoOp). Concept errors
are unstable under *both*, so transformation adds nothing there. This is a
sharper claim than the one predicted, and it is exactly the mechanism that
motivated the channel (round 3: CODE executes a comprehension error faithfully;
transformation perturbs the surface the error latched onto).

## TPR / FPR / firing rate (reported for every mechanism — a high TPR alone is worthless)

**A1 metamorphic** (n=314, 44 wrong):

| stratum | n | wrong | TPR | FPR | firing | J [CI] | p | precision |
|---|---|---|---|---|---|---|---|---|
| ALL | 314 | 44 | 0.75 | 0.156 | 0.239 | 0.594 [0.451, 0.729] | 0.0 | 0.44 |
| **surface (NoOp)** | 160 | 25 | **1.00** | **0.185** | 0.313 | **0.815 [0.748, 0.879]** | 0.0 | 0.50 |
| concept (classic) | 74 | 10 | 0.70 | 0.156 | 0.230 | 0.544 [0.208, 0.849] | 0.0007 | 0.41 |
| substitution | 80 | 9 | 0.11 | 0.099 | 0.100 | 0.013 [−0.154, 0.277] | 0.63 | 0.13 |

**A2 inversion** (ask the model to re-check its own answer): surface J = **0.531
[0.326, 0.743]**, FPR = **0.015**, precision = **0.857**, firing 0.089 — a clean,
low-false-positive second positive; concept J = 0.168 [−0.048, 0.468] (includes
0). Re-reading the original statement catches ~half of surface errors with almost
no false alarms.

**A4 entailment net** (NoOp): J = 0.025 [−0.030, 0.122], firing 0.019 — **DEAD**
(models answer the start/removed/remaining triple consistently even when the
final answer is wrong; parse rate aside, no signal).

**A3 trace–conclusion (JUDGE-DEPENDENT, reported separately, never pooled):**
n_wrong = 1 with a usable trace-conclusion → J = 0, no signal / underpowered.

## Model dependence (the power limitation, made concrete)

| model | n | wrong | A1 TPR | A1 FPR | A1 J | note |
|---|---|---|---|---|---|---|
| gemma-2-27b | 80 | **28** | 0.93 | 0.327 | 0.602 | the workhorse; carries the result |
| llama-3.1-70b | 79 | 2 | 1.00 | 0.130 | 0.870 | high J but only 2 errors — underpowered |
| mistral-small-3.2 | 76 | 6 | 0.83 | 0.214 | 0.619 | few errors |
| **phi-4** | 79 | 8 | **0.00** | 0.00 | **0.00** | its errors are NOT surface-detectable |

The result rests on **gemma-2** (28 of 44 total errors; the only well-powered
cell). **phi-4 is a clean counterexample**: it makes 8 errors and the detector
catches *none* of them (J=0) — phi's errors are not surface-keyed, so metamorphic
testing is blind to them, exactly as the mechanism predicts. So "consistency
detects error" is really "**consistency detects surface-keyed error**," and
whether a model's errors are surface-keyed is model- and item-dependent.

## Honest limits

- **FPR is non-trivial.** A1 on NoOp fires on 18.5% of *correct* answers (gemma
  32.7%). Part of this is genuine instability, part is **transform-induced
  error** — the model can mis-solve a *correct* item's transformed variant
  (e.g. an arithmetic slip under T5 scaling), which the detector counts as a
  violation. Metamorphic testing conflates "original was wrong" with "the
  transformed solve was wrong." **A2 inversion avoids this** (FPR 0.015) and is
  the more deployable detector.
- **Gemma-carried.** Non-gemma cells are underpowered (2–8 errors). The pooled
  numbers should not be read as model-general; phi-4 shows the detector can be
  fully blind to a model's error class.
- **Substitution dead** (9 errors, J≈0) — when capable models err on numeric
  substitution it is not surface-keyed.
- **Corrected prediction.** Concept-keyed errors are detectable (J=0.54), not
  ≈0 as predicted; what is surface-specific is A1's *advantage over
  self-consistency*, not detection per se.
- Not a claim about independence, ensembles, or agreement — a single agent
  auditing its own claim under transformation.

## What it means

Channel A is **live**: an oracle-free, single-agent consistency check catches
surface-keyed (comprehension-type) errors that cheap resampling misses, and a
self-inversion check catches them with very low false-positive rate. This is a
real trust primitive for the class of error round 3 showed execution cannot
catch. It is bounded: it detects surface-keyed error specifically, its
false-positive rate is non-trivial for the transform-solve variant, and the
evidence is carried by the one error-prone model. Whether this composes into a
bonded, judge-free fraud-proof is taken up in `FINDINGS_SYNTHESIS.md` after
Channel B.
