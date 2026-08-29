# R-H1 — the hierarchy route: preregistration (Gate 0)

**Committed before any experiment code exists.** Nothing else is in this
directory. **Zero credits**; exact rational arithmetic, no model call.

---

## 0. Why this route, and what it is not

R-M1 measured that a local stale check holds a cross-principal aggregate at
M = 512 — and that the required margin **grows with M and runs out**
(INFEASIBLE at ε = 4, and at every M = 512 cell with 4 agents per principal).
A2 then showed the guarantee is a **compliance assumption**: one principal
ignoring its check breaks the bound at every scale, because the damage travels
through the commons rather than through the defector's own term.

Both results are about a **flat** federation. Every planetary system that works
— routing, DNS, federation — is hierarchical, and R-M1 §9 named hierarchy as
"a different architecture, not a tuning of this one."

**This route is not a re-run of R-M1.** δ\* is re-measured only because the
topology changes what "M" means at a check.

## 1. The composition bound, verified before any run

For any partition of principals into clusters:

```
max_i x_i  ≤  κ_local · S_{j*}  ≤  κ_local · max_j S_j
⇒   κ_global  =  max_i x_i / Σx_i   ≤   κ_local × κ_cluster
```

Checked over **200,000 random partitions: 0 violations, and tight** (max ratio
exactly 1.000). It composes multiplicatively, so a d-level tree needs per-level
`κ_l = κ^(1/d)`.

**The consequence that motivates the route: per-level M is the FANOUT, not the
population.**

| d | fanout | M = fᵈ | κ_l | L(0) per level | ceiling κ_l − 1/f |
|---|---|---|---|---|---|
| 1 | 512 | 512 | 0.600 | 0.0261 | 0.598 |
| 2 | 23 | 529 | 0.775 | 0.2645 | 0.731 |
| 3 | 8 | 512 | 0.843 | 0.5304 | **0.718** |

R-M1 measured δ\* = **0.130 at M = 8** against **0.295 at M = 512**. A 3-level
tree of fanout 8 covers the same 512 principals with every check running at the
M = 8 scale, and with **more margin available** (0.718 vs 0.598).

**Two effects compete, and which wins is the question:**

- **shallower per-level M** ⇒ smaller δ\* per check (helps)
- **staleness compounding with depth** ⇒ larger δ\* (hurts)

## 2. The compounding hypothesis, stated mechanically

A cluster sum `S_j` is computed from member states that are **themselves
ε-stale**. If each level snapshots independently — which is what an unsynchronised
gossip mesh does — then a root view is ε rounds old with respect to level-1
sums, which were ε rounds old with respect to leaves.

> **Hypothesis: effective staleness at the root is d·ε, so a depth-d tree at
> per-level staleness ε behaves like a flat federation at staleness d·ε.**

R-M1 confirmed δ\* is monotone non-decreasing in ε (P-M5), so under this
hypothesis depth costs margin. The route measures whether the fanout saving
outruns it.

## 3. Environment

`research/margin/env_margin.py` is **imported READ-ONLY** — the same rule the
escrow and defector routes followed. Exact integer nano-units, **no tolerance
parameter anywhere**, which is the precondition R-M1 established after five
float-boundary artifacts.

**Topology.** A complete tree of depth d and fanout f; principals are the fᵈ
leaves. Each internal node admits its children against a box for
`(f, κ_l = κ^(1/d), δ)`. The root's aggregate is scored by the environment.

**Gate 0 (harm independence):** global concentration is computed by the
environment over leaf state, exactly, and cannot see any guard or any level's
decision.

**GATE 0c:** UNDEFINED (total 0) is counted and excluded, never scored.

**Factors:** d ∈ {1, 2, 3} with f ∈ {512, 23, 8} so M ≈ 512 throughout ·
ε ∈ {1, 2, 4} · δ swept on an absolute grid **g = 1/200**.

## 4. Measures

**Harm — environment-computed:**
- `violations` — rounds with global `concentration > κ`, exact.
- `δ*` — smallest grid δ with zero violations across all seeds.
- `peak_concentration`, `undefined_rounds`.

**Communication — the second axis, and it is not decoration:**
- **`max_fan_in`** — the largest number of peers any single node must read in a
  round. Flat = M − 1; tree = f. This is what makes 100K agents tractable or
  not, and a margin result reported without it would hide that a flat check
  requires every node to read every other.
- `total_messages` per round.

**Reachability, checked first:** whether the attack moves the aggregate at all
at δ = 0. `UNREACHABLE ≠ δ* = 0` — that conflation produced a δ\* of −0.0200 in
R-M1 and is checked explicitly here.

## 5. Decision rules, with feasibility ceilings checked BEFORE the run

Rules are **additive against 2g**, never ratios: E1-HOLDS was a ratio rule whose
baseline came out exactly 0.000 and was unscorable, and A2's φ\* rule had a 70×
resolution difference across M. Additive rules are well-defined at a zero
baseline.

| rule | threshold | ceiling | trivially satisfiable? |
|---|---|---|---|
| **H-COMPOUNDS** | δ\*(d=3) > δ\*(d=1) + 2g at the same ε | δ ∈ [0, κ_l − 1/f); ranges differ per d (0.598 vs 0.718) and are **stated now** | No |
| **H-HELPS** | δ\*(d=3) < δ\*(d=1) − 2g | as above | No |
| **H-NEUTRAL** | neither | — | It is the default and is reported as such |
| **H-SOUND** | at δ ≥ δ\*, global concentration never exceeds κ **and** no level's own box is breached | — | No — a level can satisfy its local bound while the composition fails |
| **H-INFEASIBLE** | δ\* ≥ κ_l − 1/f at any cell | — | No: means depth cannot be made safe by margin |
| **FAN-IN** | `max_fan_in` reported for every topology | — | Reporting obligation, not a bar |

## 6. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-H1a** | staleness compounds ~linearly: δ\*(d, ε) ≈ δ\*(1, d·ε) | **YES** — §2's mechanism; each level's snapshot is taken over already-stale children |
| **P-H1b** | despite compounding, δ\*(d=3) < δ\*(d=1) at ε = 1 | **YES**, and it is the risky one: it bets the fanout saving (M 512→8, δ\* 0.295→0.130 in R-M1) outruns a 3× staleness penalty |
| **P-H1c** | H-SOUND holds — the composition inequality survives stale admission | **YES**, but it is not free: the inequality is exact for instantaneous state, and overshoot at two levels could compose |
| **P-H1d** | `max_fan_in` falls 511 → 7 from d=1 to d=3 while total messages stay Θ(M) | **YES, DERIVABLE** — reported because the margin number alone would hide the reason hierarchy is worth anything |
| **P-H1e** | at δ = 0 the attack is reachable at every d | **YES** — needed for δ\* to exist; if false the cell is UNREACHABLE and is not scored |

**P-H1b is the route's bet.** If it holds, planetary aggregate bounding is
cheaper hierarchically than flat and the ceiling moves. If it fails, depth costs
more than it saves and flat federation with bounded activity (R-M1's other
result) is the only path.

## 7. What this route cannot establish

1. **No membership churn.** Clusters are fixed for a trajectory. Re-clustering
   moves the frame, and frame drift is this program's most-repeated defect
   (R9's pinned frame, SR-5's floating origin, the version-integer check, and
   `gates.py`'s now-inverted rationale). Churn is the obvious next question and
   is deliberately out of scope here rather than tested badly.
2. **Complete, uniform trees.** Real federations are ragged.
3. **No defectors.** A2's result is orthogonal and composing the two is a
   separate route; every δ\* here assumes universal compliance and is therefore
   an **optimistic** bound.
4. **One aggregate**, one conserved total, uniform per-level staleness,
   simulated principals — R-M1's limits carry over unchanged.
5. **Nothing about correctness.** Consequence only; the competence bound
   remains terminal.
