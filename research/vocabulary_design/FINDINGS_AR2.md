# Findings — AR-2: is a claim semantic intrinsically, or as stated?

Per `PREREGISTRATION_AR2.md` (`c30ab6c`), committed before any result. 196 real
artifacts, ground truth **re-executed from MBPP's asserts** (external).
Deterministic, zero model calls.

## DECISION: **ENVELOPE-ABSORBS fires as preregistered — and the decomposition says it should not be believed**

| envelope | TPR | FPR | role |
|---|---|---|---|
| TYPE-ONLY | 0.4017 | 0.0000 | FLOOR |
| **STRUCTURAL** | **0.5128** | **0.0000** | the candidate |
| ORACLE | 1.0000 | 0.0000 | CEILING (**DEFINITIONAL** — requires solving) |

The rule as written fires **ENVELOPE-ABSORBS** (TPR ≥ 0.50 and FPR ≤ 0.10).
**I am reporting it, and I do not believe the interpretation it licenses.** The
rule is not rewritten.

## The mixture (#14) — what the headline is actually made of

| | |
|---|---|
| failing artifacts | 117 |
| of those, **did not run at all** (crash / no output) | **47 (40.2%)** |
| of those, **ran and produced output** | 70 |
| **STRUCTURAL's marginal TPR among the 70 that RAN** | **0.1857** |
| marginal FPR among the 79 correct that ran | 0.0000 |

**78% of the headline is "the program crashed."** That is an execution failure
any runtime already surfaces — it is not a semantic claim respecified into a
mechanical one. Strip it out and the envelope catches **18.6%** of genuine wrong
answers, which is inside the preregistered **ENVELOPE-FAILS** band (< 0.20).

So the two readings disagree, and the decision-relevant one is the marginal:
the question was whether *respecifying a semantic claim* absorbs failure mass,
and crashes were never the semantic part.

## P1 was refuted on the headline and confirmed on the quantity that matters

P1 predicted STRUCTURAL TPR < 0.25. The headline is 0.5128 — **refuted**. The
marginal is 0.1857 — **confirmed**. Recorded both ways rather than picking the
flattering one, and the preregistration is what makes that possible: it fixed
the threshold before the number existed.

## The answer to the question

> **Semantic-ness is intrinsic at the granularity C11 can pay for.**

A type-level envelope cannot encode what a *particular* problem's answer should
look like, and that is exactly the information separating right from wrong. It
can check that the program ran, that it is deterministic, that its output type
is consistent, and that it is not constant — and having checked all of that, it
still admits **81.4%** of genuinely wrong answers.

Respecification is **not a strong lever for O1**. The 4-of-18 semantic fraction
does not shrink by restating the claims at a granularity anyone can afford.

## Diagnosed clean numbers

- **ORACLE 1.0000 / 0.0000** — DEFINITIONAL. It compares against the reference,
  so it separates perfectly by construction. It is the ceiling, never a result,
  and it is **not a cheap check**: computing it requires solving the problem.
- **FPR 0.0000 across all three** — for TYPE-ONLY this is definitional (a
  correct program passed the asserts, so it ran). For STRUCTURAL it is
  **measured**: 0 of 79 correct programs were rejected by the determinism,
  type-consistency or non-degeneracy checks. P2 predicted non-zero FPR here and
  was **wrong** — correct MBPP solutions are uniformly deterministic,
  type-stable and non-constant across the three test inputs.

## Disclosed correction — artifact #15's species, for the third time

The first run gave the **ORACLE an FPR of 0.0633**, which is impossible by
construction. Cause: the oracle compared **`repr` strings** while MBPP's asserts
compare **values**, so `1` vs `1.0` and dict key-order differences read as
mismatches. Fixed by comparing values in-process. **No envelope was tuned** —
the fix was to a ceiling that was mis-measuring itself, and it moved the ceiling
to its definitional 1.0/0.0 without touching TYPE-ONLY or STRUCTURAL, whose
numbers are unchanged between runs.

That this species recurred a third time, in a session that had just written the
rule down, is the honest note: the rule ("canonicalize before comparing") is
easy to state and evidently easy to not apply.

## Honest limits

One benchmark (MBPP), short functions, one claim type
(`execution_output_content`), one author's envelope. **A better envelope may
exist**; this measures what one careful type-level envelope achieves, not the
best possible. It cannot show that no envelope works. It also inherits MBPP's
own weakening: "correct" means passing three asserts, itself a finite-sample
verdict.

The 40.2% crash rate is a property of this capability tier and is not general —
at a higher tier, failures would shift from crashes toward wrong answers, and
the headline would fall toward the marginal.
