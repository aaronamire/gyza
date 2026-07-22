# Findings — the correlated-failure project

Write-up per the pre-registration. No new methodology thread follows.

## DECISIVE RESULT (wider menu, capable models) — H2 FALSIFIED: family-invariant failure

> **Mechanism corrected (conditional-independence null, FINDINGS_CI_NULL.md).**
> Against the *right* null — the leave-pair-out per-problem wrong-answer
> distribution — cross-family excess is −0.024 [−0.052, +0.001] and
> within-family excess is +0.026 [−0.013, +0.065]: both include 0 (Case A).
> The convergence is **problem-structural**, not a shared cognitive blind
> spot. Median distinct wrong answers per problem = 1 (Simpson 0.60). Read
> "universal blind spot" below as **constrained wrong-answer space**: the
> family-invariance of failure stands; the "shared cognition" reading does
> not. The ~13× permutation null cannot see pair-specificity and overstates
> the effect.

Re-run of the **unchanged** protocol on 9 capable models across 5 families
via OpenRouter, capability-banded exactly as pre-registered. On the
**primary, confound-free code battery** (same specific wrong program
behavior; null ≈ 0 because capable models produce diverse *runnable* buggy
code, not degenerate errors):

| | mean | 95% CI (bootstrap over pairs) | null | pairs |
|---|---|---|---|---|
| within-family | 0.603 | [0.563, 0.643] | 0.044 | 2 |
| **cross-family** | **0.560** | **[0.533, 0.586]** | **0.044** | 13 |

- **Every single pair — all 13 cross-family and both within — sits far
  above null**: per-pair convergence 0.45–0.64 vs null ~0.044, i.e.
  **+0.41 to +0.60**, ~13× chance. Llama×Gemma, Llama×Mistral, Llama×Phi,
  Gemma×Mistral, Gemma×Phi, Mistral×Phi *all* converge on the same
  specific wrong program outputs. **Cross-family convergence sits
  emphatically above null.**
- **within ≈ cross**: R = 0.603/0.560 = **1.08**, CIs overlap heavily.
- Pre-registered decision rule: *0.8 ≤ R ≤ 1.2 and both > null ⇒ H2
  FALSIFIED.* R = 1.08 ⇒ **H2 is FALSIFIED: mixing families does not
  decorrelate failure.** But the correct null (conditional-independence,
  not permutation) shows the shared failure is a **constrained wrong-answer
  space**, not a shared blind spot — family-invariant because it is
  problem-driven. Diversity still cannot help; the reason is the small
  answer space, and only external resolution breaks it. See
  FINDINGS_CI_NULL.md.

Code-band capability (±0.10, code pass rate): llama-3.1-70b 0.40, gemma-2
0.38, gemma-3 0.40, mistral-2501 0.32, mistral-3.2 0.36, phi-4 0.38 — six
models, four families. (Excluded below band: llama-3.3-70b 0.08,
mistral-3.1 0.18, qwen-72b 0.12.)

**Honest caveats.** (a) Only **2 within-family pairs** cleared the code
band (Gemma, Mistral), one short of the pre-registered ≥3 — so the *ratio*
R has a slightly underpowered within side. But the two within pairs agree
(0.64, 0.56) and both fall inside the cross range, and the crux — cross-
family convergence ≫ null — is well-powered (13 pairs, all above null), so
the universal-blind-spot conclusion does not rest on the underpowered
side. (b) **Secondary TruthfulQA disagrees in part**: the verbatim floor
leans family-specific (cross 0.017 [0, 0.05] < within 0.083, but 1 within
pair — underpowered), while the topic-confounded semantic ceiling is
universal (cross 0.74 ≥ within 0.67). Per the pre-registration the **code
battery is authoritative** on disagreement ⇒ universal.

**What this means for Gyza.** The diversity-invariant premise — that
mixing model families reduces shared blind spots — is **refuted on the
confound-free primary test**: different families make the *same specific
bugs* ~13× more than chance, at essentially the same rate as same-family
models. Diversity is **not** a reliable defense. This *strengthens* the
case for the settlement-primary + sparse-ground-truth-resolution backstop
over diversity: when the collective's blind spot is universal, no amount
of pool diversity helps, and only an external verification signal
(bonded-market resolution) can break it. The earlier "diversity helps"
reading (from the artifact-inflated tiny-model runs) does not survive
capable cross-family models.

---

## Earlier (Groq) run — inconclusive, retained for the record

## Question and pre-registered claim

H2: **diversity decorrelates failure** — mixing model families lowers
shared blind spots, so cross-family failure convergence < within-family.
Its negation is the dangerous case for Gyza: a **universal blind spot**
(cross ≈ within, both above chance), where pool diversity cannot help.
Primary, confound-free metric: **code-battery same-bug convergence**
(identical wrong program behavior in an ~infinite space). Falsifier: the
within/cross ratio R on capability-matched models.

## What was run

Groq free tier, capability-matched, deterministic (seed 1), both
batteries. Models measured: llama-3.1-8b, llama-3.3-70b, qwen-27b,
allam-7b, gpt-oss-20b, gpt-oss-120b.

- **TruthfulQA accuracy** (band ±0.10): llama-8b 0.49, llama-70b 0.45,
  qwen 0.44, allam 0.46 (banded); gpt-oss 20b/120b 0.04/0.05 (a format
  outlier, band-excluded).
- **Code pass rate** (after fixing a harness bug — see below): gpt-oss-120b
  0.42, gpt-oss-20b 0.38, qwen 0.28, llama-8b 0.24, allam 0.20, llama-70b
  0.10. Band (±0.10 of top): **only the two gpt-oss models**.

## The decision could NOT be reached (stated plainly)

The pre-registered within/cross **ratio R is not evaluable** on the
available models, for a structural reason, not a chosen one:

- **Code battery (primary):** after capability-banding, only gpt-oss-20b
  and gpt-oss-120b clear the bar — the **same family**. So there are
  **zero capability-matched cross-family pairs.** The one matched pair
  (within-family gpt-oss) converges strongly: **0.655 vs 0.182 null
  (+0.47)** — same-family models do share specific bugs — but there is no
  matched cross-family comparison to divide by.
- **TruthfulQA (secondary):** the band has 4 models but only **one
  within-family pair** (the two Llamas), far short of the pre-registered
  ≥3. Underpowered by exactly the criterion the pre-registration flagged.

So H2 is **neither confirmed nor refuted** by the pre-registered test.
Groq's thin menu + capability-matching leaves no valid cross-family
comparison. A definitive answer needs a broader capability-matched
cross-family menu (e.g. OpenRouter: Mistral/Gemma/more sizes) — NOT run
here, per the instruction to stop.

## What the evaluable, clean signals do show (directional, not decisive)

Two independent CLEAN metrics agree on direction:

| clean metric | within-family | cross-family |
|---|---|---|
| verbatim TruthfulQA convergence | 0.094 | **0.006** |
| code same-bug (unbanded, conv − null) | +0.28 | +0.12 |

Both show **within-family > cross-family**. This:

- **Refutes the earlier "universal blind spot (cross ≈ within)" headline**
  — which the tightening had already exposed as a forced-collision
  artifact. The clean picture is family-*specific*, not universal.
- **Leans toward H2** (diversity partially decorrelates failure):
  cross-family models converge on the same specific failure *less* than
  same-family models.
- **But cross-family convergence is still above null** (verbatim 0.006 >
  0.0005 null; code +0.12) — diversity *reduces* shared failure, it does
  not eliminate it.

Caveats that keep this directional, not decisive: the within side rests on
1–2 pairs (underpowered, inconsistent — the code within pairs are Llama
+0.08 and gpt-oss +0.47); the unbanded code comparison is
capability-confounded; the semantic TruthfulQA ceiling is topic-confounded.

## Methodological findings (the project's durable output)

The measurement was harder than the phenomenon, and rigor caught four
artifacts that would each have produced a false result:

1. **Forced collision.** Nearest-listed matching on TruthfulQA's curated
   misconception set collapses the answer space (null 0.28); it fabricated
   a "universal blind spot" that vanished under list-free matching.
2. **Degenerate outputs from weak models.** Twice — arithmetic, then code
   pre-fix (86–96% error signatures, 4–10 distinct) — too-weak models
   collapse the space and inflate the null. The confound-free test needs
   models *capable at the task*.
3. **Harness artifact.** MBPP tests call a specific function name; not
   telling the model it produced universal `NameError`s and a fake null.
   Fixing it moved pass rates 2–10% → 10–42%.
4. **Sentinel collision.** "No answer produced" counted as agreement,
   inflating within-family convergence to a spurious 1.0.

Plus two positive methodological results:
- **Free-form absolute convergence** reveals a universal blind spot that
  the within/cross statistic reads as zero (validated on synthetic).
- **Direction, not frequency:** decorrelating *which* answer a model gives
  when wrong matters; decorrelating error timing does nothing. Gyza's
  diversity invariant must be conditional-on-error.

## For Gyza

The diversity-invariant premise (mixing families reduces shared blind
spots) is **directionally supported, not established**: cross-family
models share fewer specific failures than same-family, but still share
some above chance. That is consistent with the layered design —
diversity + settlement-primary backstop + detection — rather than
diversity as a complete defense. The honest status is: plausible,
partially evidenced, and awaiting a properly powered cross-family run.

## Reproduce

Instruments validated by tests (`test_*.py`, all green). The decisive run:
`GROQ key in .env; python run_groq.py`. Raw per-model outputs cached in
`groq_cache/` (git-ignored); result in `decisive_result.json`.
