# Preregistration — AR-3: is there a NON-TEXT signal for claim-type assignment?

**Committed before any AR-3 result.** Discovery route. O2.

## Question

Text-based assignment is capped at **0.5** because 196 of 196 external artifacts
carry more than one legitimate claim type from *identical* source text
(`selection_routes/type_assignment_external.json`). Does a **non-text** signal
beat that ceiling?

## Signals under test (all non-text, all derived from the object, not its description)

| id | signal |
|---|---|
| **SHAPE** | the runtime type/structure of the object the claim is about |
| **APPLICABILITY** | the set of registered V-1 verifiers whose input contract the object satisfies |

## The decomposition that is the actual hypothesis

Claim types differ from one another in one of two ways, and the prediction is
that **the signals resolve one kind and provably cannot resolve the other**:

| pair kind | example | expectation |
|---|---|---|
| **TOUCH-differing** | `artifact_content_address` vs `delegation_attenuation` — different objects, different state touched | resolvable in principle |
| **ASSERTION-differing** | `unit_test_execution` vs `execution_output_content` — *same* object, different thing asserted about it | **not resolvable by any signal derived from the object**, because the distinction is not in the object |

This is not an artifact of corpus construction: both are **registered claim
types in Gyza's own vocabulary**, and "did this pass its tests" and "is this
correct" are both real claims about one artifact.

## Metrics — never accuracy alone

1. **Unique-determination rate** — fraction of tasks whose claim type is
   uniquely determined by the signal.
2. **AMBIGUITY RATE (the counter-metric)** — fraction where ≥ 2 claim types
   share the signal. A signal that maps everything to one bucket has perfect
   coverage and zero discrimination; the ambiguity rate is what stops that.
3. Both, decomposed by pair kind.

## Feasibility ceiling, before thresholds

- Requires both pair kinds present in the corpus: **≥ 2 TOUCH-differing types
  and ≥ 2 ASSERTION-differing types**. The corpus has 5 and 2. ✔
- If SHAPE collides for every type, the signal carries no information and the
  route reports NOT-MEASURABLE rather than 0.

## Decision rule

- **SIGNAL-EXISTS** — unique-determination ≥ 0.75 overall **and** > 0.5 on
  ASSERTION-differing pairs. Type assignment becomes mechanical; C11's cost
  model changes materially.
- **SIGNAL-PARTIAL** — resolves TOUCH-differing (≥ 0.75) but **not**
  ASSERTION-differing (≤ 0.5). Assignment is mechanical *only* where claim types
  touch different state; where they assert different things about the same
  state, per-task human audit stands.
- **NO-SIGNAL** — below 0.75 on both.

## Point predictions, with a prior

- **P1** — SHAPE **collides within the envelope family**: `envelope_signature`,
  `envelope_chain` and `envelope_dag` all take an ICPEnvelope, so shape alone
  will not uniquely determine type even among TOUCH-differing types.
- **P2** — ASSERTION-differing pairs resolve at **exactly chance (0.5)**, and
  the exact value will be **definitional**, not measured: the two claims are
  about a byte-identical object, so no function of the object can separate them.
- **P3** — SIGNAL-PARTIAL fires.

**Prior: 60% SIGNAL-PARTIAL / 30% NO-SIGNAL / 10% SIGNAL-EXISTS.**

**What would falsify P2:** any object-derived signal separating
`unit_test_execution` from `execution_output_content` above chance.

## Terminal condition

Ends when both signals are measured over the corpus and decomposed by pair kind.
Two signals is the cap; if neither resolves ASSERTION-differing pairs, the route
does not go looking for a third, because P2 gives the reason none can exist.

## What this cannot establish

Gyza's own 18-type vocabulary and one corpus. A vocabulary with no
assertion-differing pairs would not have this problem — which is a claim-
vocabulary *design* observation (O1), not a rescue for O2.
