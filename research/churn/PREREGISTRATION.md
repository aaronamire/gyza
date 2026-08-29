# R-C — churn: preregistration (Gate 0)

**Committed before any experiment code exists.** Nothing else is in this
directory. **Zero credits**; exact rational arithmetic, no model call.

---

## 0. Why this route, and why now

Three results now rest on one mechanism:

- **A2**: damage travels through the **commons**.
- **R-B**: hierarchy **compartmentalises** the commons — blast radius is one
  cluster, ~1.6 defectors per cluster.
- **R-N**: therefore a stale reader's error is bounded, the margin **saturates
  at 68.68%**, and the tree has **no staleness horizon** through ε = 128.

Every one of those assumes **fixed clusters**. R-B §7.4 and R-N §6.5 both name
churn as the untested dependency, and R-N is the strongest result this program
has produced.

> **If a principal can draw on more than one commons over time, the resource it
> is stale about is no longer bounded — and the horizon should come back.**

This route is run because it is the most likely thing to overturn our own
result. Every prior route in this program that overturned something overturned
its own work first.

## 1. The frame decision hiding inside churn

When a principal moves between clusters, **does its claim travel with it?**
That is a frame question, and frame drift is this program's most-repeated
defect: R9's pinned frame, SR-5's floating origin, the version-integer
monotonicity check, and `gates.py`'s rationale which inverted when H1/H2
retired.

Two policies, both defensible, with opposite safety:

- **CLAIM_TRAVELS** — the principal's `contrib` moves to the new cluster's
  funded total. Natural if membership is a routing decision. **A defector can
  drain cluster A, migrate, and drain B.**
- **CLAIM_STAYS** — `contrib` remains with the origin cluster; the migrant
  holds no claim in its new one. Natural if the commons is a stake. Drainage is
  one-shot.

**If these differ, the choice is a safety parameter rather than an
implementation detail**, and that is the transferable result regardless of
which way the numbers fall.

## 2. Threat models, kept separate

- **BENIGN** — a fraction *r* of principals are reassigned to a uniformly random
  cluster each round. Load balancing, joins, departures. Not adversarial.
- **ADVERSARIAL** — only defectors migrate, and they migrate to the cluster with
  the **fullest pool**. This is the attack the mechanism is exposed to and it is
  the one that matters.

Reporting them together would let a benign result launder an adversarial one.

## 3. Environment

`research/hierarchy/tree.py` is **imported READ-ONLY**; R-H1, R-B and R-N were
all measured on it. Churn is added by a subclass in this directory that
replaces the positional pool assignment (`leaf // f`) with an explicit
`pool_of` map. **The tree's admission structure is unchanged** — only commons
membership churns, because the commons is the mechanism under test.

Exact integer nano-units, **no tolerance parameter anywhere**.

**Gate 0:** violations from `Tree.concentration_exceeds`, exact, guard-blind.
**GATE 0c:** UNDEFINED counted and excluded.

## 4. Measures

- **k\*** — smallest number of defectors that breaches, as in R-B. Integer,
  exactly comparable across churn rates.
- **ε\*** — the horizon, as in R-N. **The route's headline quantity**: R-N found
  none through ε = 128 for the tree; churn either restores one or does not.
- **`pools_touched`** — distinct commons a single defector drew from over a
  trajectory. **This is what "compartmentalisation" means operationally**, and
  measuring it directly avoids inferring the mechanism from k\* alone.
- **`margin_consumed`** = δ\*/ceiling, to see whether saturation survives.

## 5. Decision rules, feasibility checked BEFORE the run

Baselines are established, not assumed: at r = 0 this environment must
reproduce **k\* = 103** (R-B, d=3, ε=1) and **no horizon through ε = 128**
(R-N). *If it does not, the churn instrument is wrong and no cell is read.*

r ∈ [0, 1]; k ∈ [1, M−1] = [1, 511]. Rules are **additive against integers**,
never ratios — E1-HOLDS and R-B both divided by a zero baseline.

| rule | threshold | trivially satisfiable? |
|---|---|---|
| **CHURN-BREAKS** | k\*(r=1, adversarial) ≤ 4 (twice flat's k\* of 2) | No — r = 0 gives 103 |
| **HORIZON-RETURNS** | some ε ≤ 128 with no feasible δ, under churn | No — R-N found none at r = 0 |
| **POLICY-MATTERS** | k\*(CLAIM_TRAVELS) < k\*(CLAIM_STAYS) − 2 at the same r | No |
| **GRACEFUL** | k\* is monotone non-increasing in r | No |
| **COVERAGE** | every INFEASIBLE established from the ceiling down, then the interior | **Mandatory** — R-M1's defect, and R-N depends on it |

## 6. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-C0** | r = 0 reproduces k\* = 103 and no horizon | **YES, definitional** — it is the control, and a failure here voids the route |
| **P-C1** | CHURN-BREAKS holds under ADVERSARIAL migration at r = 1 | **YES** — a migrating defector drains a new commons each round, so its reach is no longer one cluster |
| **P-C2** | **HORIZON-RETURNS** under adversarial churn | **YES**, and this is the one that matters: R-N's saturation is caused by a bounded commons, and migration unbounds it |
| **P-C3** | POLICY-MATTERS — CLAIM_TRAVELS is strictly worse | **YES** — under CLAIM_STAYS a migrant has no claim to draw on, so drainage is one-shot |
| **P-C4** | benign churn degrades **gracefully**: k\* falls but stays ≥ 10× flat's at r ≤ 0.1 | **YES** — a uniformly random reassignment rarely lands a defector on a full pool |
| **P-C5** | `pools_touched` ≈ 1 at r = 0 and rises ~linearly in r | **YES, near-definitional** — stated so the mechanism is measured rather than inferred |

**P-C2 is the route's bet, and it bets against our own strongest result.** If it
holds, R-N's headline needs the qualifier *"under bounded churn"*, and the
planetary claim narrows accordingly.

## 7. What this route cannot establish

1. **No detection or ejection.** A real federation would notice a principal
   that drains a pool and migrates. Every k\* is a **lower bound**.
2. **The tree's admission structure is fixed** — only commons membership
   churns. Re-parenting the whole tree is a larger change and is out of scope.
3. **One aggregate**, one conserved total, uniform staleness, simulated
   principals — every limit from R-M1 onward carries.
4. **Nothing about correctness.** Consequence only; the competence bound
   remains terminal.
