# R-E — extensive bounds: preregistration (Gate 0)

**Committed before any experiment code exists.** Nothing else is in this
directory. **Zero credits**; exact rational arithmetic, no model call.

---

## 0. The threat to everything above

Five routes — R-M1, A2, R-H1, R-B, R-N, R-C, R-D — bound **concentration**,
`max/sum ≤ κ`. That is a **scale-invariant ratio**, and R-D established that its
scale invariance is exactly what defeats a dispersing attacker: uniform
destruction does not move it.

Measured during R-E's feasibility check, and it is the reason this route exists:

> **With ZERO defectors, the fully compliant population destroys 99.26% of all
> federation value** (retained 0.0074) while concentration stays inside κ.

**A ratio bound is compatible with near-total destruction by principals who
never break a rule.** `max/sum ≤ 0.6` says nothing about how much exists.

Most harm bounds anyone actually wants are **extensive**: *"do not destroy more
than X."* None of our results speak to one.

## 1. The question

> **Is a preservation bound — `total ≥ ρ · genesis` — enforceable by the same
> hierarchy, at what margin, and does it have the staleness horizon the ratio
> does not?**

R-N's headline is that the tree's required margin **saturates** and there is no
horizon through ε = 128. If an extensive bound *does* have one, R-N is a
statement about scale-invariant aggregates specifically and must be qualified.

## 2. Why the extensive bound is not obviously harder — and why it might be

**Not obviously harder:** a sum is *distributive* (Gray et al.), so it composes
trivially, and `x_i ≥ T/m` for every principal implies `Σx ≥ T`. It is in the
locally-enforceable class by the same criterion concentration is.

**Might be much harder:** the box floor already *is* a per-principal
preservation bound. Yet at δ = 0 principals breach their own floors massively
through staleness overshoot — R-M1 established that δ\* guarantees the
*aggregate*, never that every principal stays in box, and R-H1 measured
`below_box` at 90–98% of rounds.

**The ratio tolerates that overshoot; a preservation bound is violated by
precisely it.** Same trajectory, same guard, different verdict.

## 3. Calibrating ρ BEFORE the run — standing rule #4

- At δ = 0 the compliant population retains **0.0074** of genesis.
- If every principal held its box floor exactly, retention would be
  `512 × 0.5304 / 10240 = 0.0265`.
- As δ → ceiling, `L → U`, nothing sheds, retention → 1.

**ρ = 0.02.** Below what the box would guarantee if respected, so it is
*achievable in principle*; above what δ = 0 delivers, so it is **not trivially
satisfied**. Neither unreachable nor free — which is what the rule demands.

## 4. Environment

`research/hierarchy/tree.py` **imported READ-ONLY**; the same populations,
attacks and staleness model as R-M1 through R-D. **Only the scored predicate
changes**, so any difference is attributable to the bound and to nothing else.

- **RATIO** — violation iff `max/sum > κ`. Exactly R-N's predicate.
- **PRESERVE** — violation iff `total < ρ · genesis`. Both computed by the
  environment on the same trajectory, so the comparison is paired.

Exact integer nano-units; no tolerance parameter. **GATE 0c:** UNDEFINED
counted and excluded.

## 5. Measures

- **δ\*_ratio** and **δ\*_preserve**, on the *same runs* — paired, not two
  experiments.
- **ε\*** for each: the largest ε with a feasible δ below the ceiling.
- **`retained`** = final total / genesis, reported for every cell. The quantity
  the ratio is blind to.
- **`margin_consumed`** = δ\*/ceiling, since R-N's saturation is stated in it.

## 6. Decision rules, feasibility checked

| rule | threshold | trivially satisfiable? |
|---|---|---|
| **EXTENSIVE-HARDER** | δ\*_preserve > δ\*_ratio + 2g at the same (ε, topology) | No — both are measured on the same trajectory |
| **EXTENSIVE-HAS-A-HORIZON** | some ε ≤ 128 where PRESERVE has no feasible δ but RATIO does | No — R-N found none for RATIO |
| **HIERARCHY-STILL-HELPS** | δ\*_preserve(tree) < δ\*_preserve(flat) | No |
| **RETENTION-REPORTED** | `retained` beside every δ\* | Mandatory — it is the quantity the ratio hides |
| **COVERAGE** | every INFEASIBLE swept ceiling-down then interior | Mandatory — R-M1's defect |

## 7. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-E0** | at δ = 0 the RATIO holds while PRESERVE fails | **YES, and it is measured already** — retained 0.0074 against ρ = 0.02. The control |
| **P-E1** | **EXTENSIVE-HARDER** holds: δ\*_preserve > δ\*_ratio | **YES** — the ratio tolerates the overshoot that violates preservation |
| **P-E2** | the gap widens with ε | **YES** — overshoot grows with staleness and the ratio keeps absorbing it |
| **P-E3** | hierarchy still helps for PRESERVE | **YES** — bounded entitlement bounds overshoot, and that argument does not use scale invariance |
| **P-E4** | **PRESERVE has a finite horizon where the ratio has none** | **YES, and this is the route's bet.** If it holds, R-N narrows to scale-invariant aggregates |
| **P-E5** | at δ\*_preserve, `retained` is barely above ρ | **YES** — δ\* is a minimum, so it lands against the bar |

**P-E4 bets against the generality of our strongest result.** If PRESERVE has a
horizon, then "hierarchy removes the staleness horizon" is true of ratios and
unproven for the bounds people actually write.

## 8. What this route cannot establish

1. **One extensive bound.** Total value only; not "files deleted", not
   "irreversible actions", not H3.
2. **The honest population is still maximally shedding** — inherited from AG-3.
   A population that preserves by default would make PRESERVE easier and is a
   different experiment.
3. **No defectors.** Every δ\* assumes compliance and is optimistic.
4. **Commons membership fixed** (R-C/R-D varied it; this varies the predicate).
5. **Nothing about correctness.** Consequence only.
