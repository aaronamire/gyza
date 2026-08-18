# R-N — the staleness horizon: findings

**Preregistration:** `PREREGISTRATION.md`, committed `e46ba43` as the only file
in this directory, BLAKE3
`150b26978404659155f89c275acc5489e2e2ba09e41b21d12c23a02ccb8c685d`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic.

**Verdict: `COMPOSABILITY-IS-NOT-SUFFICIENT`, and — unexpectedly —
`HIERARCHY-REMOVES-THE-HORIZON-RATHER-THAN-MOVING-IT`.**

---

## 1. The result

Same population (M = 512), same aggregate, same attack. Only the topology and
the staleness differ.

| ε | flat δ\* | flat consumed | tree δ\* | tree consumed |
|---|---|---|---|---|
| 1 | 0.2930 | 49.0% | *attack defeated* | — |
| 2 | 0.4780 | 79.9% | *attack defeated* | — |
| 4 | 0.5880 | **98.3%** | 0.2634 | 36.7% |
| 8 | 0.5930 | **99.2%** | 0.4684 | 65.2% |
| 16 | **NONE** | — | 0.4884 | 68.0% |
| 32 | — | — | 0.4934 | 68.68% |
| 64 | — | — | **0.4934** | **68.68%** |
| 128 | — | — | **0.4934** | **68.68%** |

> **ε\*(flat) = 8.** Beyond it, no margin anywhere below the ceiling is safe —
> established by sweeping the ceiling region first and then the whole interior.
>
> **The tree has no horizon in range.** Its required margin is *identical to
> four decimal places* at ε = 32, 64 and 128. It does not approach the ceiling;
> it stops at **68.68%** of it.

**Composability is necessary and not sufficient.** Concentration composes at
every ε — the inequality κ_global ≤ κ_local × κ_cluster is exact and does not
depend on staleness. Yet flat enforcement fails at ε = 16. A second condition is
required, and for the flat topology it is violated at a finite, small value.

## 2. The mechanism: the horizon is set by the size of the commons

A2 established that damage travels through the **shared pool**. R-B established
that hierarchy **compartmentalises** it. R-N is the consequence:

> A stale reader's error is bounded by the shared resource it is stale *about*.
> Flat: that resource is the whole federation, so the error grows with ε until
> it exceeds any available margin. Tree: it is one cluster's commons, which is
> **finite and small**, so the error is bounded and so is the margin.

The saturation value is predicted, not merely observed. A leaf's maximum
other-caused error is its entire pool claim, at most `CONTRIB = 6` of a
`U = 20` endowment. R-M1's closed form at per-level M = f = 8, κ_l = 0.8434
gives δ\* ≈ **0.539** against a measured **0.4934** — over by 9%, consistent
with that form's known conservatism (R-M1 §4 measured it conservative by ≈2×).
The *mechanism* is confirmed; the constant is not claimed.

## 3. Predictions, scored

| | prediction | outcome |
|---|---|---|
| **P-N1** | ε\*(flat) finite, in [4, 16] | **CONFIRMED — 8** |
| **P-N2** | ε\*(tree) ≥ 4 × ε\*(flat) | **CONFIRMED, and stronger**: no horizon through ε = 128 |
| **P-N3** | `margin_consumed` monotone, → 1 at ε\* | **CONFIRMED for flat** (0.49 → 0.80 → 0.983 → 0.992). **REFUTED for the tree** — monotone but saturating at 0.687. *The refutation is the finding.* |
| **P-N4** | ε\* is not explained by M alone | **CONFIRMED** — identical M = 512, one horizon at 8, the other unbounded |
| **P-N5** | at ε just below ε\*, δ\* within one grid step of the ceiling | **CONFIRMED exactly** — 0.5930 against 0.5980, one grid step of 1/200 |

Four confirmed, one confirmed-then-refuted where the refutation is the result.

## 4. What this changes

**For the vision.** Bounded staleness was an assumption every result above
rested on. It is now a *measured, topology-dependent* quantity: a flat
federation tolerates 8 rounds of staleness and a 3-level tree tolerates at least
128 with margin to spare. In a planetary mesh, propagation delay is the one
thing you cannot control — so **the topology that removes the horizon is the
only one deployable at all.**

**For the composability story.** The tempting claim after R-H1 was "composable
aggregates are hierarchically enforceable." That is false as stated. The
correct statement is:

> An aggregate is hierarchically enforceable if it composes **and** the shared
> resource a stale reader is stale about is bounded. Composition is a property
> of the aggregate; the second condition is a property of the **partition**.

Both are architecture, not policy. This is the fifth lever the four-locus
framework is missing, now with a measured horizon attached.

## 5. Apparatus — the defect this route was designed around

R-M1 published **four false INFEASIBLE verdicts** because its δ-scan stepped
past the ceiling region without testing it. ε\* is *defined* by the absence of a
feasible δ, so this route is precisely the one that defect would poison.

Every negative verdict here sweeps the **ceiling region first**, downward at the
fine grid, and only then the interior — and `NONE` is returned only after both.
The flat ε = 16 cell was checked both ways.

**UNREACHABLE is reported separately from a horizon.** The tree at ε ≤ 2 defeats
the attack at δ = 0; that is *better* than any finite δ\*, not a missing
measurement. Collapsing the two is the defect R-B walked into one route after
recording it.

## 6. What this route cannot establish

1. **One aggregate.** Concentration only. The composable class is larger and
   nothing here says the horizon behaves the same across it.
2. **ε\*(tree) is a lower bound**, not a measurement: it exceeds the tested
   range of 128. The saturation is strong evidence it is unbounded, and that is
   an inference, not a result.
3. **Uniform staleness** across principals and levels; real staleness is
   per-observer.
4. **No defectors.** Every ε\* assumes universal compliance and is optimistic.
5. **Fixed clusters.** Churn is untested and would attack exactly the
   compartmentalisation this result depends on.
6. **Nothing about correctness.** Consequence only; the competence bound
   remains terminal.
