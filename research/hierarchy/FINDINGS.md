# R-H1 — the hierarchy route: findings

**Preregistration:** `PREREGISTRATION.md`, committed `b97d511` as the only file
in this directory, BLAKE3
`b586da6f591fc71b9e2cd142e2df894cc80a6b891949585a6e63c5ea58bde835`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic.

**Verdict: `HIERARCHY-HELPS-DECISIVELY`** — and the route's bet, P-H1b, was
right for a reason stronger than predicted.

---

## 1. The result

M ≈ 512 at every depth. δ\* is the smallest margin with zero violations across
all seeds; the **attack is identical in every row.**

| d | fanout | max fan-in | ε=1 | ε=2 | ε=4 |
|---|---|---|---|---|---|
| **1 (flat)** | 512 | **511** | 0.295 | 0.480 | 0.593 *(99.2% of its ceiling)* |
| **2** | 23 | 22 | *attack defeated* | *attack defeated* | 0.500 *(68%)* |
| **3** | 8 | **7** | *attack defeated* | *attack defeated* | **0.265** *(37%)* |

> **At ε ≤ 2 a 2- or 3-level tree defeats, with NO margin at all, the same attack
> that flat federation cannot survive without δ\* = 0.295–0.480. At ε = 4 flat
> needs 99.2% of every margin its box can give, while depth 3 needs 37% — and
> 0.265 is less than flat needs at ε = 1.**

Depth 3 at four rounds of staleness is safer than flat at one.

**The ε = 4 flat cell read INFEASIBLE until the scan was fixed** (§5a). That
correction propagates to R-M1 and is written up separately.

## 2. The positive control: an independent instrument reproduces R-M1 exactly

At d = 1 the tree is a single cluster of 512 leaves over one shared pool —
structurally R-M1's flat federation. It was built separately, from a different
module, by a different route.

| | R-M1 (`margin_result.json`) | R-H1 (d=1) |
|---|---|---|
| ε=1 | 0.295 | **0.295** |
| ε=2 | 0.480 | **0.480** |
| ε=4 | INFEASIBLE | **INFEASIBLE** |

**Exact agreement to the grid at every cell — including on the shared defect.**
Both instruments reported ε=4 as INFEASIBLE and both were wrong for the same
reason (§5a): the agreement validated the environment and the arithmetic, and was
blind to a scan bug the two implementations had in common. **A positive control
confirms what two instruments share, which includes their shared mistakes.** This is the strongest validation
either route has: two instruments, built independently, agreeing on a measured
quantity neither was tuned to reproduce.

## 3. P-H1a — staleness does not compound in the damaging direction

Predicted: δ\*(d, ε) ≈ δ\*(1, d·ε) — depth costs margin because each level reads
sums that were themselves stale.

**REFUTED.** If compounding dominated, d = 3 at ε = 1 should behave like flat at
ε = 3, i.e. somewhere between 0.480 and INFEASIBLE. It instead **defeats the
attack outright**. Whatever compounding exists is swamped by the fanout saving:
per-level M drops 512 → 8, and R-M1 already measured δ\* falling 0.295 → 0.130
across that range.

The mechanism, now visible: the commons is **compartmentalised**. A leaf's
divestment drains *its own cluster's* pool, so the other-caused error a sibling
suffers is bounded by one cluster's commons rather than the federation's. This
is the direct structural answer to A2, whose whole result was that damage
travels through the shared pool — **hierarchy makes the pool smaller.**

## 4. H-SOUND fails its second clause, and the global bound holds anyway

`below_box` is **180–195 of 200 rounds** in every δ\* cell, at every depth. Nodes
routinely end below their own box floor while global concentration stays within
κ.

> **The composition theorem's precondition fails while its conclusion holds.**
> Global safety at δ\* is therefore *not* being delivered by the composition —
> it is slack. The inequality κ_global ≤ κ_local × κ_cluster is sound and tight
> in the instantaneous case (0 violations in 200,000 random partitions), but the
> measured safety here does not depend on it.

This is worth stating plainly because the tempting write-up — "the composition
bound holds under staleness" — would be true as an outcome and wrong as an
explanation. R-M1 found the same shape at d = 1: δ\* guarantees the *aggregate*,
never that every principal stays in box.

## 5. The decision rule conflated two opposite outcomes

**H-COMPOUNDS / H-HELPS printed UNSCORABLE in all six cross-depth comparisons**,
because one side was `None`. But `None` meant two opposite things:

- at ε ≤ 2, d ∈ {2,3}: **UNREACHABLE** — the attack could not move the aggregate
  at δ = 0. Better than any finite δ\*.
- at ε = 4, d = 1: **INFEASIBLE** — which then turned out to be a scan artifact
  (§5a), so the token was not merely ambiguous, it was wrong.

Collapsing "safest possible" and "unsafe at any price" into one token made every
comparison unscorable. This is the **fifth** instance of standing rule #4's
species and a **new variety**: not an unreachable threshold or a bad denominator,
but a *sentinel-value conflation* — the same defect as `AN ERROR IS NOT A VALUE`,
one level up, in the scoring rather than the measurement.

**The finding does not depend on the broken rule**: with the two cases
distinguished, H-HELPS holds at every ε, decisively.

### 5a. The INFEASIBLE verdicts were a scan artifact — in this route and in R-M1

The coarse scan stepped δ by 1/40 from 0. Below a ceiling of 0.5980 the last
point tested is **0.575**; the next stride lands at 0.600, the loop exits, and
the cell is declared INFEASIBLE — **without (0.575, 0.598) ever being tested.**

Found by a test I wrote to assert the opposite pole existed. Every affected cell
is in fact safe:

| cell | published | actual |
|---|---|---|
| R-H1 d=1, ε=4 | INFEASIBLE | **0.593** |
| R-M1 M=512, ε=4, n=1 | INFEASIBLE | safe at **0.590** |
| R-M1 M=512, ε=1, n=4 | INFEASIBLE | safe at **0.595** |
| R-M1 M=512, ε=2, n=4 | INFEASIBLE | safe at **0.595** |
| R-M1 M=512, ε=4, n=4 | INFEASIBLE | safe at **0.595** |

**A verdict of "no margin works" must be established over the whole admissible
range, not over the part a stride happened to land on.** The scan now refines
downward from the ceiling before returning INFEASIBLE.

R-M1's headline `MARGIN-GROWS-WITH-M-AND-RUNS-OUT` is corrected in
`research/margin/CORRECTION_INFEASIBLE.md`: the margin **does not run out**. It
approaches the ceiling asymptotically — 99.2% of it at ε = 4 — which is a
different and weaker claim than infeasibility.

## 6. P-H1d — the fan-in, which is why any of this matters

| d | max fan-in |
|---|---|
| 1 | **511** |
| 2 | 22 |
| 3 | **7** |

Flat requires every principal to read every other. A tree requires *f* at every
level **regardless of population**. Reporting δ\* without this would hide the
actual reason hierarchy is worth anything: at 100,000 agents a flat check is not
merely expensive, it is not implementable.

## 7. Predictions, scored

| | prediction | outcome |
|---|---|---|
| **P-H1a** | staleness compounds ~linearly in depth | **REFUTED** — swamped by the fanout saving; depth 3 at ε=4 beats flat at ε=1 |
| **P-H1b** | δ\*(d=3) < δ\*(d=1) at ε=1 — *the route's bet* | **CONFIRMED, more strongly than stated**: not smaller, but *unnecessary* |
| **P-H1c** | H-SOUND holds | **HALF REFUTED** — the global bound holds; the per-level boxes are breached in 90–98% of rounds |
| **P-H1d** | fan-in 511 → 7 | **CONFIRMED**, derivable as flagged |
| **P-H1e** | attack reachable at every d | **REFUTED, and that IS the result** — the identical attack is defeated by depth at ε ≤ 2 |

## 8. Apparatus defects — four, all caught by controls before data

1. **`κ_l**d > κ` at d = 3.** `limit_denominator` returns the *closest* rational,
   not the closest from below, so the per-level κ came out **above** the true
   d-th root. A per-level bound even slightly too permissive makes the composed
   bound exceed the global one **by construction** — the route would have
   measured its own arithmetic error. Replaced with a bisection on a fixed
   denominator plus an asserted post-condition.
2. **An unscaled floor.** `box_floor_at` hardcoded the leaf endowment, so level-2
   and level-3 checks used a floor *f* and *f²* times too small — a guard that
   admits almost anything, reported as a guard.
3. **A parent divesting through its children's floors.** Divestment was drained
   leaf-by-leaf from the front of a subtree, so `below_box` read 200/200
   everywhere. Divestment now originates at a leaf and is admitted upward, the
   only direction that respects every box on the path.
4. **Amnesia — and this one had already been fixed once.** Leaves re-shed
   `believed − L` every round against a stale view of *their own* value, drained
   to zero, and made d = 1 INFEASIBLE at every ε — contradicting R-M1.
   **R-M1's `trial.py` had recorded and fixed exactly this defect, and the fix
   did not transfer to a new instrument built on the same environment.** A
   defect list is not a mechanism; nothing carried it across.

And one **null worth keeping**: before the per-cluster commons existed, every
topology measured 0 violations at δ = 0. A leaf that knows itself exactly has no
other-caused change, so the box is sound *by definition* — the same definitional
null R-M1's uncoupled arena produced. A2 had already established that the commons
is the mechanism; the environment had to contain one before the question was
askable.

## 9. What this route cannot establish

1. **No membership churn.** Clusters are fixed. Re-clustering moves the frame,
   and frame drift is this program's most-repeated defect — now including
   `gates.py`'s own rationale, which inverted when H1/H2 retired. **This is the
   next route.**
2. **No defectors.** A2's result is orthogonal; every δ\* here assumes universal
   compliance and is therefore an **optimistic** bound. Whether hierarchy
   compartmentalises a *defector's* damage the way it compartmentalises
   staleness is strongly suggested by §3 and is **not measured here.**
3. **Complete, uniform trees**, one aggregate, one conserved total, uniform
   per-level staleness, simulated principals.
4. **Nothing about correctness.** Consequence only; the competence bound remains
   terminal.
