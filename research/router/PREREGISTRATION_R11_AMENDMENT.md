# Amendment 1 to PREREGISTRATION_R11.md — the NO-ANSWER label

**Committed BEFORE any prediction call is issued.** Pre-generation, pre-data.
No R11 confidence has been elicited at the time of this commit. It amends a
**label-definition defect in my own implementation**, not a decision rule. No
decision rule, threshold, prompt, stratum, or point prediction changes.

## What was wrong

`PREREGISTRATION_R11.md` §1 says `canonicalizer_v2.equal` is three-valued and that
**UNRESOLVED items are EXCLUDED, never imputed.** That is correct for what it
describes. My first implementation of `data.math_outcomes` then wrote:

```python
lab.append(None if not got else canonicalizer_v2.equal(got, it["ref_raw"]))
```

which folds **two structurally different events** into the same `None`:

1. **UNRESOLVED** — the model produced an answer, and the canonicalizer could not
   decide it against the reference. Genuinely undecidable; exclusion is right.
2. **NO-ANSWER** — `extract_boxed` found no `\boxed{...}` at all. The model produced
   **no final answer**. This is a **failure**, not an undecidable.

Excluding (2) excludes precisely the cases where the model did not deliver, which
selects the positive class.

## How it was caught

GATE 0b, by the standing rule *diagnose any exact 0 or 1 before reporting*.
`mistralai/mistral-small-3.2-24b-instruct` reported **40 solved / 40 used = exactly
1.000**, with 40 of 80 items dropped. Decomposing the `None`s:

| model | empty raw | **NO-ANSWER** | reached canonicalizer | **UNRESOLVED** | T | F |
|---|---|---|---|---|---|---|
| google/gemma-2-27b-it | 0 | **16** | 64 | 3 | 43 | 18 |
| meta-llama/llama-3.1-70b-instruct | 0 | **19** | 61 | 3 | 52 | 6 |
| microsoft/phi-4 | 0 | **20** | 60 | 1 | 55 | 4 |
| mistralai/mistral-small-3.2-24b-instruct | 0 | **39** | 41 | 1 | 40 | 0 |

The `None`s were **overwhelmingly NO-ANSWER** (16/19/20/39), not undecidability
(3/3/1/1). Genuine canonicalizer undecidability is rare, as Phase 8's hand validation
(27/27, zero false merges) would predict.

## Why NO-ANSWER is truncation, and therefore a failure

No-`\boxed` completions are systematically **longer** than boxed ones, and terminate
mid-expression:

| model | NO-ANSWER median chars | boxed median chars |
|---|---|---|
| meta-llama/llama-3.1-70b-instruct | **1820** | 963 |
| microsoft/phi-4 | **1023** | 1192 |
| mistralai/mistral-small-3.2-24b-instruct | **2852** | 2327 |
| google/gemma-2-27b-it | 562 | 743 |

A sampled mistral tail ends `... \[ 10` — cut mid-expression. The COT ran past the
cached run's generation cap and never reached its answer. (gemma is the exception —
its NO-ANSWERs are *short*, so they are format misses rather than truncation. Both
resolve the same way.)

## The correction

```
NO-ANSWER (extract_boxed == "")            -> label FALSE   (a failure)
UNRESOLVED (equal(...) is None, both set)  -> label None    (EXCLUDED, never imputed)
```

The claim the router predicts is *"would M produce the correct final answer?"*. A
model that was cut off did not produce a correct final answer. Labelling it FALSE is
the honest reading of the outcome; excluding it is the artifact.

This matches `route2_experiment`'s own convention, which emits the sentinel
`IMPORTERR:NOANSWER` for a missing `\boxed` rather than treating it as a
non-observation.

## Disclosed consequence and residual limit

- The MATH exclusion rate falls from 19–40 per model to **1–3 per model**.
- **Disclosed:** a NO-ANSWER is partly a **harness artifact** (the cached run's token
  cap), not purely a competence failure. The router is therefore predicting, in part,
  *"will this model ramble past the cap"*. That is a legitimate difficulty signal —
  harder problems produce longer chains — but it is **cap-dependent**, and any MATH
  result carries this caveat. It is reported in FINDINGS_R11, not buried here.
- **The population-difficulty null is affected identically for every model**, so the
  paired delta — the headline — is not biased by this choice in either direction.
- MBPP is untouched: its labels never route through `extract_boxed`.

## Artifact ledger

This is **artifact #10** of the program, and the fourth caught by the
diagnose-any-exact-zero-or-one rule.

- **What it would have falsely shown:** MATH base rates of 0.705 / 0.897 / 0.932 /
  **1.000** — a roster of mid-tier open-weight models apparently near-ceiling on MATH,
  against a program-wide capability tier of pass 0.32–0.40. Every downstream AUROC
  would have been computed on a positive-class-selected sample, and mistral would have
  had **zero negatives**, making its AUROC undefined or degenerate.
- **What caught it:** the standing rule that an exact 1.000 is a suspected artifact
  until diagnosed.
