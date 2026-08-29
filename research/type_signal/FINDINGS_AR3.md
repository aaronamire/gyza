# Findings — AR-3: is there a non-text signal for claim-type assignment?

Per `PREREGISTRATION_AR3.md` (`c2fafc4`), committed before any result.
Deterministic, zero model calls.

## DECISION: **NO-SIGNAL**

| | n | unique determination |
|---|---|---|
| **OVERALL** | 12 | **0.5833** |
| TOUCH-differing | 10 | **0.7000** |
| ASSERTION-differing | 2 | **0.0000** (DEFINITIONAL) |

**Ambiguity rate: 0.4167** — the counter-metric, and it is what stops 0.5833
reading as "mostly works". Two collisions account for all of it:

```
ICPEnvelope  ->  envelope_signature, envelope_chain, envelope_dag
program      ->  execution_output_content, unit_test_execution
```

**SIGNAL-PARTIAL did not fire** because TOUCH-differing came in at **0.70**,
below its 0.75 bar. The single reason is P1's collision: three registered claim
types are all *about an ICPEnvelope*, so an object-derived signal cannot say
which claim is being made about it.

## Predictions scored

| # | prediction | outcome |
|---|---|---|
| P1 | SHAPE collides within the envelope family | ✓ **confirmed** — and it alone drags TOUCH from 1.0 to 0.70 |
| P2 | ASSERTION-differing resolves at chance, and the value is DEFINITIONAL | ✓ **confirmed** — exactly 0.0000 |
| **P3** | **SIGNAL-PARTIAL fires** | ✗ **REFUTED** — NO-SIGNAL fires |

P3 failed because **P1 was right harder than I allowed for.** I expected the
envelope collision and still assumed TOUCH-differing types would clear 0.75. One
collision among twelve types was enough to miss the bar.

## The 0.0000, diagnosed

**DEFINITIONAL, and predicted as such before data.** `unit_test_execution` and
`execution_output_content` are claims about a **byte-identical object**. No
function of the object can separate them, because the distinction is not in the
object — it is in *what is being asserted*. This is not a weak signal; it is the
absence of anything for a signal to read.

## DISCLOSED DESIGN FLAW — the two signals were one signal

I registered SHAPE and APPLICABILITY as two signals. **They return identical
numbers in every cell, and that is not corroboration — it is construction.**
APPLICABILITY was defined as *"which verifiers accept an object of this shape"*,
i.e. a function of SHAPE. So **one signal was tested, not two**, and the two
matching columns must not be read as replication.

Stated plainly because two identical columns look like independent confirmation
and are not.

**Does the terminal condition still hold?** For ASSERTION-differing pairs, yes,
and not because two signals failed: P2 is an **argument**, not a measurement —
byte-identical objects admit no separating function, whatever the signal. For
TOUCH-differing pairs the 0.70 is a **lower bound from one signal**; a genuinely
independent signal (runtime touch-set, capability requested) might beat it.
Adding one now would be choosing a signal after seeing the number, which the
discipline forbids, so the route stops where it was told to.

## What this means for O2

**Per-task human type assignment stands as a permanent cost**, and now for two
distinct reasons rather than one:

1. **Where claim types differ in what they ASSERT about the same object**
   (`unit_test_execution` vs `execution_output_content`), *no* object-derived
   signal can help. Argued, not merely measured.
2. **Where they differ in what they TOUCH**, a shape signal gets 0.70 — better
   than the 0.5 text ceiling, but short of mechanical.

The second is not closed and is the honest opening left: a runtime touch-set
signal is untested and could plausibly resolve the envelope family, since
`verify_chain` and `verify_dag` read *different* fields of the same object.

## What this cannot establish

Gyza's own 12 verifier-backed claim types, one corpus, **one effective signal**.
It does not show no signal exists for TOUCH-differing types — it shows this one
reaches 0.70.

**And there is a vocabulary-design reading, which belongs to O1 rather than
being a rescue for O2:** a vocabulary with no assertion-differing pairs would not
have failure mode (1) at all. The envelope family collides because *three
separate claim types were minted about one object*. That is a choice, and a
different vocabulary could avoid it.
