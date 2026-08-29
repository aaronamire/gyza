# Preregistration — SR-3: the tier algebra (resolves K-5)

**Committed before any code that produces an SR-3 result.** Selection-route
discipline (BUILD_PLAN §4): preregistered metric, decision rule, **equivalence
bound**, at most three variants, full frontier reported, Occam tiebreak.

Deliverable is a **table**, not only a winner: `research/TIER_ALGEBRA.md`, which
the scheduler (K-6) consults before permitting a deep chain.

## Question

Under which combination operators is **tier preserved**? If `f` and `g` are
tier-1 claims, is `f ∘ g` tier-1?

## Tiers (from V-2, a pure type check)

| tier | meaning |
|---|---|
| 1 | a native verifier exists for the claim type |
| 2 | a registered human-authored partial spec exists |
| 3 | neither — containment only |

## The three operators (the cap is three)

| id | operator | definition |
|---|---|---|
| **a** | VERIFIED FOLD | combine only where a verifier exists for the **combined** claim |
| **b** | SPEC-CHECKED MERGE | combine under a registered partial spec on the result |
| **c** | CONTAINED CONCATENATION | no correctness claim on the combination; containment only |

## THE PREDICTION — mine, a hypothesis to falsify

Recorded as a hypothesis, not a premise. **Four preregistered predictions in
this program have been refuted by data** (R9's G4/G4′ inversion, R10's H-CONS,
R13's P2/P5/P7, R14's P1, SR-5's P2). Disconfirming evidence is reported
prominently.

- **H1** — PROOF-CARRYING claims preserve tier to arbitrary depth. A signature
  is a proof of its property; proofs compose.
- **H2** — TEST-CARRYING claims DEGRADE tier on composition. A test suite is a
  finite sample, so two components each passing their own tests can violate an
  interaction property no test covers.
- **H3** — CONSERVATION and MONOTONE_NON_CUMULATIVE specs preserve tier (C6).
- **H4** — CUMULATIVE specs do NOT; the combination must be forced to the
  promotion gate (C7).

## Method

**12 three-stage pipelines over GYZA'S OWN claim types**, not synthetic
functions — the question is about the real vocabulary. Stage kinds are drawn
from the R14 Part C enumeration and carry a tier and an invariant class:

| stage kind | tier | class | property |
|---|---|---|---|
| `sign_envelope` | 1 (proof) | MONOTONE | chain linkage verifies |
| `store_artifact` | 1 (proof) | CONSERVATION | content address matches bytes |
| `settle_credits` | 1 (proof) | CUMULATIVE | total spend within bound |
| `hlc_stamp` | 2 (spec) | MONOTONE | ratchet is non-decreasing |
| `tested_transform` | 1 (**test**) | CONSERVATION | passes its own unit tests |
| `produce_output` | 3 | — | none (semantic; competence bound) |

Per (input-tier profile, operator) cell, measure:

1. **TIER OF THE COMBINED CLAIM** — the primary result.
2. **COMPOSITIONALITY** — mutate exactly ONE stage and check whether the
   per-stage checks catch it. *A per-stage check that misses a single-stage
   mutation has not composed.*
3. **SIDE CONDITION** — the assume-guarantee condition required for
   preservation, stated explicitly, or the counterexample showing none exists.

## DEFINITIONAL vs MEASURED — declared in advance

From R14 Part B: extremes here may follow **from construction** rather than
from measurement. Conservation composing and cumulative not composing are both
definitional — three per-stage allowances of ≤2 admit 6 against a budget of 4,
and that gap is unobservable locally **by definition**. Operator (c) is
definitional in the same way: contained concatenation makes no correctness
claim, so its combined tier is 3 by its own definition.

**Every cell is labelled DEFINITIONAL or MEASURED in the output table.** A
definitional cell illustrates the theory; it does **not** independently confirm
it, and it will not be counted as evidence.

**The genuinely MEASURED cell is H2**, test-carrying degradation. It requires
constructing an interaction bug that each stage's own unit tests miss — that is
a real construction which can fail, not an identity.

## Pre-mutation validity check — the R14 Part B4 lesson

R14's B4 conservation cell was **voided** because the prompt said "preserved"
while the pipelines added elements, so all 24 model specs rejected the correct
pipeline. That measured the prompt, not the models.

**Therefore: every pipeline must be hand-verified to satisfy its own declared
spec BEFORE any mutation runs, asserted by test.** A pipeline that fails its own
spec un-mutated makes every downstream number meaningless.

## Feasibility ceiling — checked under the mechanism's own dynamics

Detection rate ranges over [0, 1]. Two degeneracies are checked **before** any
threshold is trusted:

- If **no** mutation is ever caught, the harness is broken, not the theory.
- If **every** mutation is caught in every cell, the metric is at its ceiling
  and the comparison is vacuous — H2 in particular would be untestable.

**Both are verified in the run and reported.** If either fires, the affected
cells report NOT-MEASURABLE rather than a result.

## Decision rule

For each input-tier profile, K-5 must use the **most permissive operator whose
single-stage mutation detection rate is 1.0**. If no operator reaches 1.0 for a
profile, the combination is **forced to the promotion gate** and the combined
claim is **tier 3**.

**Equivalence bound: 5 percentage points of detection rate, applied ONLY to
comparisons BETWEEN operators — never to soften the 1.0 soundness threshold.**
An operator that catches 95% of single-stage mutations is not "equivalent to" a
verifier; it is not a verifier. Stated explicitly because an equivalence bound
is a tool for choosing between comparable options, not for lowering a bar.

**Occam tiebreak:** where two operators both reach 1.0 for a profile, prefer the
simpler. Simplicity order, simplest first: contained concatenation < spec-checked
merge < verified fold.

## Prior

40% the algebra is **min-tier** (the combined tier is the minimum over input
tiers, so one tier-3 stage forces the chain to tier 3) · 40% **class-dependent**
(preservation depends on the invariant class, not on the tier) · 20% **something
else**, including the possibility that tier is preserved less than H1–H4 predict.

**A result showing LESS preservation than predicted is the more consequential
outcome** and constrains the coordination layer directly. It will be reported at
full strength.

## What this cannot establish

Simulated pipelines over a hand-chosen subset of Gyza's claim vocabulary; three
stages, not arbitrary depth; one mutation operator set; `SEED = 1`. It fixes an
algebra **for this vocabulary**, and the vocabulary is Gyza's own — the 58.8%
native-verifier fraction that makes it look favourable is a property of a
cryptographic/accounting claim set, not a general result.
