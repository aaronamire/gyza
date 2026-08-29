# Tier algebra

**The table K-6 consults before permitting a deep chain.** Derived in SR-3
(`selection_routes/PREREGISTRATION_SR3.md` `d1eff43`, findings in
`selection_routes/FINDINGS_SR3.md`). 12 three-stage pipelines over Gyza's own
claim types, 36 single-stage mutations, deterministic, zero model calls.

## The governing variable is the CARRIER, not the tier and not the class

A claim's tier says *whether* a mechanical check exists. It does not say what
that check rests on. **Composition is governed by the latter.**

| carrier | the per-stage check | detection under verified fold | n |
|---|---|---|---|
| **PROOF** — recomputes the property | sound on every input | **1.000** | 21 |
| **SPEC** — registered partial property | sound where it applies | **1.000** | 2 |
| **TEST** — finite sample | sound only where it sampled | **0.000** | 4 |

The invariant class looked like it mattered (CONSERVATION 0.667, MONOTONE
1.000) and does not: CONSERVATION decomposes into **PROOF 1.000 (n=8)** and
**TEST 0.000 (n=4)**. The class number was a carrier mixture.

## The table

`f ∘ g ∘ h`, where each stage's tier is its own and each carries evidence of
some kind. "Side condition" is what must hold for the output tier to be claimed.

| input carriers | operator | output tier | side condition | cell |
|---|---|---|---|---|
| all PROOF | **verified fold** | **min(input tiers)** — preserved | none; proofs compose | MEASURED |
| all PROOF | spec-checked merge | tier 2 | the partial spec must cover the composed property (it caught only 0.381 of proof-detectable violations) | MEASURED |
| all PROOF | contained concat | tier 3 | — | DEFINITIONAL |
| any SPEC, rest PROOF | **spec-checked merge** | **tier 2** | Occam: verified fold also reaches 1.000 here, and merge is simpler | MEASURED |
| **any TEST** | verified fold | **tier 3** | **none exists** — see counterexample | MEASURED |
| **any TEST** | spec-checked merge | **tier 3** | **none exists** | MEASURED |
| any tier-3 stage | any | **tier 3** | — | DEFINITIONAL |
| all CUMULATIVE | any | **tier 3** | **NOT MEASURED** — see below | NOT-MEASURABLE |

### The rule, stated for the scheduler

1. If **any** stage in the chain is TEST-carried, the combined claim is **tier
   3** and the combination must be forced to the promotion gate. No operator
   reached 1.0 detection; there is no side condition that rescues it.
2. If **any** stage is tier 3, the combined claim is tier 3.
3. Otherwise the combined tier is the **minimum of the input tiers**, and
   verified fold preserves it. Where a SPEC stage is present and spec-checked
   merge also reaches 1.0, prefer merge (simpler).
4. A CUMULATIVE property in the chain must be evaluated at the promotion gate
   regardless of tier (C7), and this table does **not** license any other
   treatment of it.

### The TEST counterexample (why rule 1 has no side condition)

`tested_transform` is **tier 1** — a mechanical check exists and runs. Its
check is a 3-case suite `{1→2, 2→4, 3→6}`. The mutation
`x ↦ x*2 if x < 10 else x*3` **passes every case in the suite** and is wrong on
the pipeline's actual input (50 → 150 instead of 100). All four TEST-carried
violations were missed, in every pipeline position tested.

A finite sample cannot bound behaviour outside itself. That is not a quality
problem with the suite; adding cases moves the boundary without removing it.

### Why CUMULATIVE is NOT-MEASURABLE here, not confirmed

Six single-stage cumulative mutations were run and **zero violated the
end-to-end budget**. The construction is why: the per-stage allowance is 2.0
against a 3-stage budget of 4.0, so one stage taking its full allowance brings
the total to exactly 4.0 — at the bound, not past it. Violating the budget
needs **two** stages to over-spend, which is not a single-stage mutation.

Per the preregistration's feasibility rule, this cell reports **NOT-MEASURABLE**
rather than a result. H4 (cumulative does not compose) is **not evidence from
this route** — it stands on C7 and R13, where it was measured directly.
