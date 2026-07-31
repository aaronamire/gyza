# Preregistration — SR-5: promotion granularity (resolves C-6 parameterization)

**Committed before any SR-5 result exists.** Selection route, not a discovery
route: it has a natural stopping point (pick the winner, build it, close it).
Selection-route discipline (BUILD_PLAN §4) applies — preregistered metric,
decision rule, **equivalence bound**, at most three variants, full frontier
reported, Occam tiebreak.

## Question

At what batch size should staged work be promoted through C-6?

## Variants (three, per the cap)

| id | k | meaning |
|---|---|---|
| **per-action** | 1 | promote after every staged action. Simplest — no batch state at all. |
| **per-task** | 4 | promote at task boundaries (a task is 4 actions in this harness). |
| **per-batch** | 32 | promote every 8 tasks. |

## Metrics

1. **Harm consumed** — peak measured harm as a fraction of the declared bound.
2. **EFFECTIVE throughput** — *admitted-and-not-rolled-back* actions per action
   attempted. **Nominal throughput is a trap**: a configuration that rolls
   everything back shows high nominal admission and zero effective work, which
   is the counter-metric rule (discipline #3) in its most concrete form.
3. **Escalation rate** — refused promotions / promotions attempted.
4. **Gate cost amortization** — guard evaluations per effectively-promoted
   action. Larger k should amortize; that is the only thing k obviously buys.

All four reported for every variant. No metric is reported alone.

## Feasibility ceiling — checked BEFORE the thresholds are fixed

Per discipline #4, and computed **under the mechanism's own dynamics** rather
than against a static state (the R13 defect):

- Effective throughput ranges over [0, 1] by construction. The ceiling is 1.0
  only if **no promotion is ever refused** — in which case every variant scores
  1.0, the metric is degenerate, and the route measures nothing.
- **Therefore the harness must be verified, before the run, to produce
  refusals at k = 1.** If the workload never trips the bound, the comparison is
  vacuous and the route reports NOT-MEASURABLE rather than a winner. This check
  is executed and its result recorded in the findings.
- Larger k mechanically loses more per refusal (the whole batch rolls back), so
  the *expected* direction is effective throughput falling with k. If it does
  not fall, that is the interesting outcome, not a bug to fix.

## Decision rule

Prefer the variant maximising **effective throughput** subject to **harm
consumed ≤ 1.0 of bound** (a variant that exceeds its bound is disqualified
regardless of throughput).

**Equivalence bound: 5 percentage points of effective throughput.** If the best
variant is within 5pp of a simpler one, **pick the simpler one and say so**
(Occam tiebreak). Simplicity order, simplest first: per-action (no batch state)
< per-task < per-batch.

## Point predictions (stated now)

- **P1** — effective throughput is **highest at k = 1** and falls with k,
  because a refusal at large k discards a whole batch of otherwise-good work.
- **P2** — harm consumed is **equal across variants**, because the bound is
  enforced at the gate in every configuration and the interior never applies
  anything irreversible.
- **P3** — gate cost amortizes with k (fewer evaluations per promoted action).
- **P4** — because of P2, this is **NOT A FRONTIER**: there is no harm /
  throughput trade-off to tune, only a throughput/cost trade-off. The plan
  anticipates this ("under append-only the frontier may collapse rather than
  trade off"); if P2 holds it is confirmed rather than discovered.

## What this cannot establish

Simulated workload, one harm class, one bound, deterministic `SEED = 1`, a
single arrival pattern, and refusal modelled as whole-batch rollback. It fixes
a **parameter** for this architecture; it is not a general claim about batching.
