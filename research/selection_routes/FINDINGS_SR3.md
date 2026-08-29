# Findings — SR-3: the tier algebra

Per `PREREGISTRATION_SR3.md` (`d1eff43`), committed before any SR-3 code
existed. 12 pipelines over Gyza's own claim types, 36 single-stage mutations,
27 of which violate an end-to-end property. Deterministic, `SEED = 1`, zero
model calls. Deliverable: `research/TIER_ALGEBRA.md`.

## DECISION: **CARRIER-DOMINATED** — the algebra is governed by what the check
## rests on, not by the tier and not by the invariant class

| carrier | n | **verified fold** | spec-checked merge | contained concat |
|---|---|---|---|---|
| PROOF | 21 | **1.000** | 0.381 | 0.000 |
| SPEC | 2 | **1.000** | **1.000** | 0.000 |
| **TEST** | 4 | **0.000** | **0.000** | 0.000 |

**This was my 20% branch** ("something else"). My prior was 40% min-tier / 40%
class-dependent / 20% other. Min-tier survives as a *rule* (rules 2–3 of the
table) but it is not the *governing* variable; the carrier is.

## H1–H4 scored

| # | hypothesis | outcome |
|---|---|---|
| **H1** | proof-carrying preserves tier to arbitrary depth | ✓ **CONFIRMED** — 1.000 across 21 violations, every stage position |
| **H2** | test-carrying degrades tier on composition | ✓ **CONFIRMED, AND STRONGER THAN PREDICTED** — not degraded, **0.000**. Nothing was caught. |
| **H3** | conservation and monotone preserve tier | **✗ MISLEADING AS STATED** — see below |
| **H4** | cumulative does not compose | **NOT MEASURABLE** here — see below |

### H3 is misleading as stated, and that is the route's main finding

Measured by class, CONSERVATION detects **0.667** and MONOTONE **1.000**, which
reads as "conservation composes less well". It does not. CONSERVATION
decomposes cleanly:

| class × carrier | n | detection |
|---|---|---|
| CONSERVATION × PROOF | 8 | **1.000** |
| CONSERVATION × TEST | 4 | **0.000** |

**0.667 is a carrier mixture, not a property of the class.** Every conservation
failure is a TEST-carried failure. I predicted the invariant class would govern
composition, carrying that expectation from C6 where it governs *concurrency*.
It governs concurrency; it does not govern *evidential* composition. Those are
different questions and I had conflated them.

### H4 is NOT MEASURABLE by this design — reported, not claimed

Six single-stage cumulative mutations, **zero end-to-end violations**. The
per-stage allowance is 2.0 against a 3-stage budget of 4.0, so one stage taking
its full allowance lands *exactly at* the bound. Exceeding it requires two
stages to over-spend, which is not a single-stage mutation.

Per the preregistration's feasibility rule, the cell reports **NOT-MEASURABLE**.
H4 is not evidence from this route. It stands on C7 and R13, where it was
measured directly — and noting that is the point: a route that quietly counted
this cell as "confirmed" would have double-counted R13's result as if it were
independent replication.

**This is the same shape as SR-5's zero-refusals reading**, and it was caught
the same way: by a preregistered feasibility check that refuses to interpret a
metric sitting at a degenerate value.

## Definitional vs measured — declared in advance, honoured

| cell | status |
|---|---|
| contained concatenation → tier 3 | **DEFINITIONAL** — it makes no correctness claim by its own definition |
| any tier-3 stage → tier 3 | **DEFINITIONAL** |
| PROOF preserves under verified fold | **MEASURED** (21) |
| TEST fails under every operator | **MEASURED** (4) — the construction could have failed and did not |
| CUMULATIVE | **NOT-MEASURABLE** |

Two of eight cells are definitional and are **not counted as evidence**. The
load-bearing measured result is the PROOF/TEST split.

## Feasibility check

27 of 36 mutations violate an end-to-end property; **neither** degeneracy fired
(not all caught by every operator; not none caught). The comparison is
therefore interpretable. The pre-mutation validity check from R14 Part B4 also
passed: **all 12 pipelines satisfy their own declared spec un-mutated**,
asserted in the driver before any mutation runs.

## The counter-metric

Detection is reported beside **permissiveness**: contained concatenation scores
0.000 detection and is *maximally permissive* — it admits everything and claims
nothing. It is not "the worst operator"; it is the correct operator when no
correctness claim is being made, and it is the one the table assigns wherever
no other reaches 1.0. A detection number without its permissiveness counterpart
would make containment-only look like failure rather than like scope.

## What this cannot establish

Simulated pipelines over a hand-chosen subset of Gyza's vocabulary; **three
stages, not arbitrary depth** — H1's "arbitrary depth" claim is supported at
depth 3 and extrapolated, not measured; one mutation per stage kind; `SEED = 1`.
The 58.8% native-verifier fraction that makes Gyza's vocabulary look favourable
is a property of a cryptographic/accounting claim set, not a general result.

**Single-stage mutation is the method's binding limitation.** It cannot exhibit
any failure that requires two stages to cooperate — which is exactly the class
of failure C7 and R13 are about. A multi-stage mutation design would be the
follow-up if the cumulative cell ever needs measuring here rather than being
inherited.
