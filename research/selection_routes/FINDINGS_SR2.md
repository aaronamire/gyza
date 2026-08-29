# Findings — SR-2: allocation

Per `PREREGISTRATION_SR2.md`, committed before any result. Deterministic,
`SEED = 1`, **zero model calls** — outcomes are the corpus's re-executed MBPP
assert verdicts. 46 problems per claim type (3 of 49 dropped for incomplete
handler rows, reported not hidden), 4 handlers.

## DECISION: ship ROUND-ROBIN; the finding is about the TAXONOMY

| policy | success | vs round-robin |
|---|---|---|
| round-robin (floor) | **0.4565** | — |
| **type-routed** (the design default) | **0.3261** | **−13.0 pp** |
| oracle (ceiling, not deployable) | **0.5652** | +11.0 pp |

**P2 predicted type-routed ≈ round-robin. It is 13 points WORSE**, outside the
5 pp equivalence bound and on the wrong side of it.

The mechanism is the taxonomy, exactly as the route was designed to detect. The
allocable slice carries **two claim types across 196 tasks**. Two types cannot
discriminate four handlers, so "route by type" collapses to *one registered
handler, always* — and commits to it. Round-robin, which knows nothing, at least
**diversifies**. A taxonomy too coarse to discriminate is not merely
uninformative; **committing to it is worse than not having it**, because it
converts a spread into a bet.

Per the decision rule (finding is about the taxonomy → K-3 ships round-robin;
Occam, since no taxonomy work is being paid for), **K-3 is round-robin**.

## The gap to oracle — what a richer taxonomy could buy

**0.2391** from type-routed, **0.1087** from round-robin. So a *perfect*
allocator beats an ignorant one by about **11 points** on this slice. That is
the entire budget available to taxonomy work here, and C10 forbids closing it by
prediction — difficulty routing failed even with a literal oracle.

**And the oracle itself is only 0.5652**: 43% of problems are solved by **no
handler at all**. That is an escalation floor no allocator can move, and it is
the counter-metric this route required — a success rate reported without it
would suggest allocation is where the loss is. It is not.

## Feasibility check

**30% of problems show handler-dependent variance.** Not degenerate: had every
problem been solved by all handlers or none, all three variants would tie and
the route would measure nothing. The check passed and is reported.

## A definitional duplication, diagnosed

The two claim types return **identical** numbers. That is not two independent
measurements: `execution_output_content` and `unit_test_execution` are two
*claims about the same artifacts*, so they inherit the same outcomes.
**DEFINITIONAL.** It is reported once, not counted twice.

## What this cannot establish

One benchmark slice; four mid-tier open-weight handlers; two claim types;
outcomes that are themselves 3-assert finite-sample verdicts. The oracle is not
deployable. The negative type-routed result is a fact about *this* taxonomy's
granularity, not a general argument against type-routing — with 18 types and
handlers specialised per type, the sign could plausibly reverse, and that is
untested.
