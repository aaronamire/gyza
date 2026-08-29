# Preregistration — AR-2: is a claim semantic intrinsically, or as stated?

**Committed before any AR-2 result.** Discovery route. O1.

## The question, sharpened by AR-1

AR-1 found that Gyza's chains contain **no** correctness claim at any depth —
the semantic types are the payload, never links. So the prior question is:

> Can a correctness claim be **in** a chain at all? Equivalently: decompose a
> semantic claim type into a mechanically-checkable **envelope** and a semantic
> **core**, and ask **how much real failure mass the envelope absorbs**.

If the envelope absorbs most failures, semantic-ness is substantially an
artifact of how the claim was *stated*, and respecifying the vocabulary helps.
If it absorbs almost none, semantic-ness is **intrinsic** and O1's ceiling is
structural.

## The fence check

This does **not** build a correctness verifier. The envelope is explicitly *not*
claimed to establish correctness; the measurement is **how much of the real
failure mass is mechanically detectable**, with the false-positive rate reported
beside it. It is not R14 restated: R14 asked whether **models** can author
specs, on **synthetic mutants**. This asks what a **human-authored, type-level**
envelope absorbs on **real model failures** with external ground truth.

## THE BINDING CONSTRAINT — one envelope per CLAIM TYPE, not per instance

C11's cost model is affordable only because specs are authored **once per claim
type**. So the envelope may use **nothing problem-specific**. One envelope
covers all 196 artifacts of type `execution_output_content`. An envelope that
encoded per-problem expectations would be measuring a cost model nobody can pay.

## Method

Substrate: the corpus's 196 (model, problem) artifacts, ground truth **re-executed
from MBPP's asserts** (external; `selection_routes/mbpp_truth.json`).

Three envelopes, all human-authored, all type-level:

| id | check | role |
|---|---|---|
| **TYPE-ONLY** | output exists and the program does not raise | FLOOR |
| **STRUCTURAL** | floor + deterministic across repeat calls + output type consistent across inputs + non-degenerate (not constant across differing inputs) | the candidate |
| **ORACLE** | matches the MBPP reference solution's output | CEILING — **not a cheap check**; computing it requires solving the problem, which is the competence bound |

## Metrics — never one without the other

1. **TPR** — fraction of genuinely-failing artifacts the envelope rejects.
2. **FPR** — fraction of genuinely-correct artifacts it rejects. **An envelope
   that rejects everything scores TPR 1.0**; the FPR is what stops that reading.
3. Position of STRUCTURAL between the TYPE-ONLY floor and the ORACLE ceiling.

## Feasibility ceiling, before thresholds

- Requires both classes present: **≥ 30 failing and ≥ 30 correct artifacts**. If
  either is short, the route reports NOT-MEASURABLE.
- The ORACLE ceiling is expected to be TPR 1.0 / FPR 0.0 **by construction** —
  DEFINITIONAL, and reported as the ceiling, never as a result.

## Decision rule

- **ENVELOPE-ABSORBS** — STRUCTURAL TPR ≥ 0.50 **and** FPR ≤ 0.10. Semantic-ness
  is substantially a statement artifact; respecification is a real lever for O1.
- **ENVELOPE-FAILS** — STRUCTURAL TPR < 0.20 **or** FPR > 0.30. Semantic-ness is
  intrinsic at the granularity C11 can pay for.
- **INTERMEDIATE** — anything else. Report the numbers; claim neither.

## Point predictions, with a prior

- **P1** — STRUCTURAL TPR is **low** (< 0.25). A type-level envelope cannot
  encode what any particular problem's answer should look like, and that is
  precisely the information that separates right from wrong.
- **P2** — STRUCTURAL FPR is **non-zero**: some correct programs are
  legitimately constant or type-varying across inputs, so the non-degeneracy
  and type-consistency checks will misfire.
- **P3** — the ORACLE ceiling is 1.0/0.0 and is definitional.

**Prior: 65% ENVELOPE-FAILS / 25% INTERMEDIATE / 10% ENVELOPE-ABSORBS.**

**What would falsify P1:** STRUCTURAL TPR ≥ 0.50 at FPR ≤ 0.10 — a type-level
envelope catching half of real failures without punishing correct work.

## Terminal condition

Ends when TPR and FPR are measured for all three envelopes over the full 196.
**No envelope tuning after seeing the numbers** — that would convert this into a
search for an envelope that fits the data, which measures my authorship.

## What this cannot establish

One benchmark (MBPP), short functions, one claim type, one author's envelope.
A *better* envelope may exist; this measures what one careful type-level
envelope achieves, not what the best possible one would. It cannot show that no
envelope works — only what this one does, at the granularity that is affordable.
