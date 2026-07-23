# Findings — Phase 5 external validity (A2 inversion on natural MATH errors)

Decision first, then the table, then honest limits. **NOT a Route 2 rescue**
(terminal decision stands). Tests whether the surviving primitive detects
**natural** errors, not just the 80 hand-built fixtures with a designed attractor.

## DECISION — the primitive GENERALIZES (attenuated, model-dependent)

A2 inversion — ask a model to re-check its own cached answer to a competition-math
problem (VALID/INVALID), no oracle — detects **natural** MATH errors above chance:

| | pooled MATH (natural) | fixture family (designed) |
|---|---|---|
| n (evaluable) | 215 (of 226; 11 unparsed verdicts = 5%) | 160 |
| base rate wrong | 0.191 | 0.156 |
| TPR | 0.415 | 0.545 |
| **FPR** | **0.040** | 0.015 |
| **LR = TPR/FPR** | **10.3** | 36.8 |
| precision | 0.708 | 0.857 |
| **J [CI]** | **0.374 [0.231, 0.535]** | 0.531 |
| permutation p | **0.0** | 0.0 |

J excludes 0, permutation p = 0, LR = 10.3 and precision = 0.71 — the primitive
**holds up on natural errors**, so it is not a designed-trap artifact. It is
**attenuated** vs the fixtures (LR 10.3 vs 36.8, J 0.37 vs 0.53): natural
competition-math errors are somewhat harder to self-catch than deliberately
constructed comprehension traps, as expected.

## Model dependence (the load-bearing caveat)

| model | n | wrong | TPR | FPR | LR | J |
|---|---|---|---|---|---|---|
| **llama-3.1-70b** | ~58 | — | — | 0.021 | **20.6** | 0.408 |
| gemma-2-27b | ~62 | — | — | 0.150 | 3.9 | 0.433 |
| **mistral-small-3.2** | ~40 | — | — | 0.000 | — | **0.000** |
| **phi-4** | ~55 | — | — | 0.000 | — | **0.000** |

The generalization is **carried by llama (LR 20.6, FPR 0.021)** and gemma (higher
FPR 0.15). **mistral-small and phi-4 have J = 0 — they never flag their own
answers as INVALID**, so self-inversion is useless for them. This mirrors the
fixture finding (phi-4 A1 J=0): A2 inversion works only for a model that will
actually *reconsider* under challenge; an overconfident model that rubber-stamps
its own output is undetectable by self-inversion. So the primitive is real and
general, but its power is a **property of the defender model**, not a universal
guarantee — a cross-model challenger (a *different* model doing the inversion)
would be needed to cover self-validating models, which this phase did not test.

## What was NOT run, and why (honest exclusion)

**Metamorphic {T2,T3,T4} was excluded on MATH.** Competition-math problems are not
templated, so a rephrase/rename/reorder cannot have its declared relation
(invariance) verified with certainty without re-solving — and guessing the
relation would silently corrupt the experiment. Per the strict rule, these were
excluded, not guessed. So external validity is established for **A2 inversion
only**; the metamorphic detector's generalization beyond templated fixtures
remains untested (and its fixture-family power was itself carried by a rephrase
whose clarity may not transfer — see FINDINGS_ABLATION.md 4a).

## What it means

A2 inversion — the program's slashing-grade primitive (fixture LR 36.8) — is a
**genuinely general** oracle-free error signal, not a fixture artifact: on natural
competition-math errors it retains LR 10.3, FPR 0.040, and a significant J (perm
p=0). It is publishable as a general result **with two bounds**: (1) it is
attenuated on natural vs designed errors, and (2) it only works for models that
will reconsider their own answer — self-validating models (mistral, phi-4 here)
are immune, which argues for a **cross-model** inversion challenger in any bonded
deployment. This strengthens the synthesis: the oracle-free consistency/inversion
primitive is real and general but bounded, and belongs **layered with** ground-
truth resolution, not replacing it.
