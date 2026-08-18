# R-N — the staleness horizon: preregistration (Gate 0)

**Committed before any experiment code exists.** Nothing else is in this
directory. **Zero credits**; exact rational arithmetic, no model call.

---

## 0. The question

R-H1 established that a cross-principal aggregate is hierarchically enforceable,
and that per-level M is the fanout rather than the population. The obvious
reading is that composability is what makes it work.

**That reading is incomplete, and R-M1's own numbers say so.** At M = 512,
δ\* rises **0.295 → 0.480 → 0.593** for ε = 1, 2, 4 against a ceiling of
**0.5980**. At ε = 4 the margin consumes **99.2%** of everything the box can
give. One more doubling and there is nothing left.

> **Is there a finite ε\* beyond which NO margin enforces a composable
> aggregate — and if so, is it a property of the aggregate, the population, or
> the topology?**

If ε\* is finite, then **composability is necessary and not sufficient**:
hierarchical enforceability additionally requires ε < ε\*(A, topology). That is
a second condition, and it is the one nobody states.

## 1. Why this is not a re-run of R-M1

R-M1 varied δ at fixed ε and asked *how much margin*. This varies ε and asks
*whether any margin exists*. The quantity is different: **ε\* is the largest ε
for which the δ-scan finds a feasible point anywhere below the ceiling.**

R-M1 also **published four false INFEASIBLE verdicts** because its scan stepped
past the ceiling region without testing it
(`research/margin/CORRECTION_INFEASIBLE.md`). Since ε\* is *defined* by the
absence of a feasible δ, this route is exactly the one that defect would
poison. The scan here refines downward from the ceiling before any negative
verdict, and a negative is only returned after the full admissible range is
covered.

## 2. Prior art, so novelty is not overclaimed

- **Gray et al. (1997), the data cube.** *Distributive / algebraic / holistic*
  aggregates. Which aggregates are computable from partials is thirty years
  old, and the composition dichotomy this program measured is that
  classification. **Not claimed as new.**
- **I-confluence (Bailis, 2014).** Necessary and sufficient for
  *coordination-free* execution. A tree is not coordination-free — it has
  bounded fan-in — so hierarchical enforceability is a different question, but
  the relationship must be stated.
- **Escrow / demarcation (O'Neil 1986; Barbará & García-Molina 1994).** Local
  enforcement of *linear* constraints. Concentration is a ratio.
- **Staleness and bounded-inconsistency replication** (session guarantees,
  bounded-staleness consistency) bounds how *stale a read may be*. It does not
  ask whether a *safety bound* remains enforceable at that staleness.

**What is claimed:** that ε\* exists and is finite for a composable aggregate;
that it is a property of the topology and not only of the aggregate; and the
measurement of both. Not the classification, not the composition inequality.

## 3. Environment

`research/hierarchy/tree.py` is **imported READ-ONLY** — the committed
instrument R-H1's numbers were measured on, per-cluster commons included. Exact
integer nano-units; **no tolerance parameter anywhere.**

**Factors.** topology ∈ {d=1 f=512 (flat), d=3 f=8 (tree)} · ε ∈ {1, 2, 4, 8,
16, 32} · δ swept on the absolute grid g = 1/200 with **ceiling refinement**.

**Gate 0:** violations computed by `Tree.concentration_exceeds`, exact, guard-blind.
**GATE 0c:** UNDEFINED counted and excluded, never scored.

## 4. Measures

- **δ\*(ε, topology)** — smallest margin with zero violations across seeds.
- **ε\*** — the largest ε for which δ\* exists strictly below the ceiling. **The
  route's quantity.**
- **`margin_consumed` = δ\*/ceiling** — the fraction of everything the box can
  give. This is what actually approaches 1, and reporting δ\* without it hides
  how close to the wall a cell is.
- **`reachable`** — whether the attack moves the aggregate at δ = 0.
  UNREACHABLE is not ε\*, and conflating them is the defect R-B walked into.

## 5. Decision rules, feasibility checked BEFORE the run

δ ∈ [0, κ_l − 1/f). Flat ceiling **0.5980**; tree ceiling **0.7184**. ε is
searched by doubling, so ε\* is bracketed rather than assumed.

| rule | threshold | trivially satisfiable? |
|---|---|---|
| **HORIZON-FINITE** | ∃ ε ≤ 32 with no feasible δ below the ceiling, for flat | No — R-M1 found feasible δ at ε = 4 |
| **HORIZON-MOVES** | ε\*(tree) ≥ 4 × ε\*(flat) | No |
| **APPROACH** | `margin_consumed` is monotone increasing in ε and → 1 at ε\* | No |
| **COVERAGE** | every INFEASIBLE verdict established over the whole admissible range, refining from the ceiling | **Mandatory** — the R-M1 defect |

**If HORIZON-FINITE fails at ε = 32**, the honest report is that ε\* exceeds the
tested range, not that it is infinite. The search bound is stated now.

## 6. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-N1** | ε\*(flat) is finite and lies in **[4, 16]** | **YES** — δ\* consumed 99.2% of the ceiling at ε = 4; one doubling should exhaust it |
| **P-N2** | ε\*(tree) ≥ 4 × ε\*(flat) | **YES** — at ε = 4 the tree used 37% of its ceiling against flat's 99.2% |
| **P-N3** | `margin_consumed` rises monotonically and approaches 1 at ε\* | **YES**, and it is the mechanism: ε\* is where required margin meets available margin |
| **P-N4** | ε\* is NOT explained by M alone — flat at M = 512 and the tree at M = 512 differ | **YES** — same population, different horizon, which is the whole claim |
| **P-N5** | at ε just below ε\*, δ\* is within one grid step of the ceiling | **YES** — the approach is continuous, so the last feasible cell sits against the wall |

**P-N1 is the risky one.** If ε\* is much larger than 16, the "not sufficient"
claim weakens to "sufficient over any plausible staleness", which is a
materially different and less interesting result — and would be reported as such.

## 7. What this route cannot establish

1. **One aggregate.** Concentration only; the composable class is larger.
2. **Uniform staleness** across principals and levels.
3. **No defectors** — every ε\* assumes universal compliance and is therefore
   an optimistic bound.
4. **Fixed clusters** — churn untested, and it is the obvious next route.
5. **Nothing about correctness.** Consequence only; the competence bound
   remains terminal.
