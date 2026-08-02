# Preregistration — SR-2: allocation policy (resolves K-3)

**Committed before any SR-2 result.** Selection-route discipline: metric,
decision rule, equivalence bound, three variants, full frontier, Occam tiebreak,
feasibility check under the mechanism's own dynamics.

## Substrate

The task corpus (`corpus.json`), MBPP slice: **4 handlers × 49 problems**, with
per-(handler, problem) outcomes **re-executed from MBPP's asserts** rather than
read from R8's cached label (which over-reports WRONG — see `mbpp_truth.json`,
11 false WRONGs in 196, 0 false CORRECTs).

This is the substrate SR-2 actually needs: outcomes that differ **by handler**,
from an external source, so an oracle is computable post hoc.

## Variants

| id | policy |
|---|---|
| **round-robin** | cycle handlers; the FLOOR |
| **type-routed** | allocate by claim type to a registered handler; the design default (C10 forbids predictive allocation) |
| **oracle** | allocate to the handler that in fact succeeded; the CEILING, computed post hoc, **not deployable** |

## Metrics — all three, never success alone

1. **success rate** — fraction of tasks whose allocated handler succeeded.
2. **escalation rate** — fraction with no successful handler available.
3. **throughput** — tasks completed per allocation attempt.

Success alone hides an allocator that escalates everything, which is the
counter-metric rule (SR-5's per-batch variant scored perfect containment by
promoting nothing).

## The deliverable is the GAP TO ORACLE

Not "which variant wins" — type-routed is the default by C10 regardless. The
route's job is to size the gap, because that says whether investing in a richer
type taxonomy pays.

## Decision rule

- Report the full frontier: round-robin ≤ type-routed ≤ oracle.
- **Equivalence bound: 5 percentage points of success rate.**
- **If type-routed is within the equivalence bound of round-robin, the finding
  is about the TAXONOMY, not the allocator**: the types are too coarse to
  allocate on. That is reported as a taxonomy finding, and K-3 ships
  round-robin (Occam: simpler, and no taxonomy work is being paid for).

## Feasibility check, before thresholds

The comparison is degenerate if the corpus offers no handler-dependent variance
— if every problem is solved by all handlers or by none, all three variants tie
at the same number and the route measures nothing. **Verified in the run and
reported.** If it fires, the route reports NOT-MEASURABLE.

## Point predictions

- **P1** — oracle ≫ round-robin: handler outcomes vary per problem.
- **P2** — **type-routed ≈ round-robin**, because the MBPP slice carries only
  **two** claim types (`execution_output_content`, `unit_test_execution`) across
  196 tasks. Two types cannot discriminate four handlers. This is predicted as a
  TAXONOMY limitation, stated before the data.
- **P3** — the gap to oracle is large, which sizes what a richer taxonomy could
  in principle buy — while C10 forbids closing it by prediction.

## What this cannot establish

One benchmark slice, four mid-tier open-weight handlers, two claim types, and
outcomes that are themselves 3-assert finite-sample verdicts. The oracle is not
deployable and is reported only as a ceiling.
