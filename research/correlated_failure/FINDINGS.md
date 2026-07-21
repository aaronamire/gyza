# Findings — the correlated-failure project

Write-up after the decisive run, per the pre-registration. Includes the
nulls and the ways the experiment was *not* able to reach its stated
decision. No new methodology thread follows this.

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
