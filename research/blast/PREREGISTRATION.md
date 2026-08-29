# R-B (blast radius) — preregistration (Gate 0)

**Committed before any experiment code exists.** Nothing else is in this
directory. **Zero credits**; exact rational arithmetic, no model call.

---

## 0. The question, and why it is exactly now

Two results from this program point straight at each other and have never been
composed.

**A2** established that a cross-principal aggregate bound is a **compliance
assumption, not a security property**: one principal ignoring its guard breaks
it at every scale to M = 512 (k\* = 1, 1, 2). The mechanism was that damage
travels through the **commons** — a defector drains the shared pool and every
other principal's claim collapses — so impact is **O(1)**, undiluted by scale.

**R-H1** established that hierarchy **compartmentalises the commons**: each
cluster holds its own pool, and a drain in one cluster leaves other clusters
untouched (asserted in `research/hierarchy/test_tree.py`).

> **So: at d = 3, f = 8, does one defector break the GLOBAL bound — or only its
> own cluster of 8?**

If the blast radius is one cluster, A2's verdict changes from *"one bad actor
breaks the federation"* to *"one bad actor breaks their cluster,"* and the
governing quantity stops being defectors-total and becomes
**defectors-per-cluster**. That is the difference between an assumption and a
security property with bounded damage.

**This is not a re-run of either route.** A2's δ is not re-measured; R-H1's
topology is not re-derived. The only new variable is a defector inside a tree.

## 1. Derived before any run

`research/hierarchy/tree.py` is **imported READ-ONLY**. The round loop is
re-implemented with a defector parameter — a variant, not a copy of the
environment, and stated as such.

**Hoarding is capped by the cluster's commons, not the federation's:**

| d | f | clusters | pool per cluster | hoarder's max total | max concentration |
|---|---|---|---|---|---|
| 1 | 512 | 1 | 3072 | 3086 | **0.3014** |
| 2 | 23 | 23 | 138 | 152 | 0.0144 |
| 3 | 8 | **64** | 48 | 62 | **0.0061** |

A hoarder can capture only its own cluster's pool. That is a **49× reduction**
in reachable concentration from flat to depth 3, and it is arithmetic, not a
measurement.

**Shedding must destroy enough clusters:** to push the target past κ, surviving
value must fall below **13.3** of 10240.

| d | clusters that must be destroyed |
|---|---|
| 1 | **1 of 1** |
| 3 | **64 of 64** |

## 2. Defection modes — and the distinction that matters most

A2's defector "ignores its own guard." In a tree there is something above it,
so the notion splits, and the split is the point:

- **UNILATERAL** — the leaf divests without asking. Ancestors cannot stop it.
  This tests whether the **topology** bounds damage.
- **SUPERVISED** — the leaf proposes anything, but ancestors still admit or
  refuse against their own (stale) boxes. This tests whether hierarchical
  **enforcement** bounds it.

> **Flat federation has no supervised case at all** — there is nothing above a
> principal. If supervision helps, that is a capability hierarchy has and flat
> does not, over and above compartmentalisation.

Modes: `SHED` (divest to 0), `SKEW` (obey L(0), not L(δ)), `HOARD` (capture the
cluster pool), each in UNILATERAL and SUPERVISED form.

## 3. Measures

**Harm — environment-computed, exact:**
- `violations` — rounds with global `concentration > κ`.
- **`k*`** — smallest number of defectors producing any violation. **Integer,
  exactly comparable across topologies**, unlike a fraction (A2's φ\* had a 70×
  resolution difference across M).
- `undefined_rounds` — GATE 0c, counted and excluded.

**Blast radius — the route's own quantity:**
- **`clusters_damaged`** — clusters whose total fell below a stated fraction of
  genesis. This is what "blast radius" means and it is measured, not inferred
  from k\*.
- **`hoard_payoff`** — the hoarder's final total against the compliant mean.

**Counter-metric, mandatory:** `honest_refusal` under SUPERVISED. Supervision
that stops defectors by stopping everyone is the AG-3 defect, and a k\* reported
without it would be containment without cost.

## 4. Decision rules, feasibility checked BEFORE the run

k ∈ [1, M−1], integer. **k\* ≥ 1 by construction, so a ratio is well-defined
here** — unlike E1-HOLDS, whose baseline came out exactly 0.000. Predicted
k\*(d=1) ≈ 1–2 and k\*(d=3) ≈ 64, both well inside the range: **neither
unreachable nor trivially satisfied.**

| rule | threshold | ceiling | trivially satisfiable? |
|---|---|---|---|
| **BLAST-CONFINED** | k\*(d=3) ≥ 8 × k\*(d=1) | k ≤ M−1 = 511; predicted ~64 | No |
| **HOARD-CAPPED** | hoarder's max concentration at d=3 < ⅛ of flat | derived 0.0061 vs 0.3014 | **It is derivable** — run as a control; failure means the arithmetic or the instrument is wrong |
| **SUPERVISION-ADDS** | k\*(supervised) > k\*(unilateral) at the same d | — | No |
| **PER-CLUSTER** | k\* ÷ clusters is closer to constant across d than k\* is | — | No |
| **COST** | `honest_refusal` reported for every SUPERVISED cell | — | Reporting obligation |

**A scan-coverage requirement, from R-M1's own defect:** k is searched by
doubling then bisection, and **monotonicity of violations in k is verified
rather than assumed** — R-M1 published four false INFEASIBLE verdicts because a
stride never covered the interval the rule ranged over. A negative verdict here
must be established over the whole range k ∈ [1, M−1].

## 5. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-B0** | k = 0 reproduces R-H1: attack defeated at ε ≤ 2 for d ≥ 2 | **YES, definitional** — it is R-H1 restated and is the control |
| **P-B1** | `BLAST-CONFINED` holds: k\*(d=3) ≈ 64 vs k\*(d=1) ≈ 1–2 | **YES** — §1: a shed defector kills only its own cluster, and 64 of 64 must fall |
| **P-B2** | hoarder's reachable concentration 0.3014 → 0.0061 | **YES, DERIVABLE** — the commons a hoarder can capture is its cluster's |
| **P-B3** | compartmentalisation dominates supervision: the d=1→d=3 gap exceeds the unilateral→supervised gap | **YES**, and it is the risky one — stale ancestors may refuse very little |
| **P-B4** | k\*/clusters is roughly constant across d | **YES** — if the blast radius is one cluster, one defector per cluster is the invariant |
| **P-B5** | `honest_refusal` under SUPERVISED is non-trivial (> 5%) | **YES** — an ancestor strict enough to stop a defector refuses honest work too |

**P-B1 and P-B4 are the same claim measured two ways.** If both hold, the
planetary statement is: *a cross-principal aggregate bound tolerates one
defector per cluster, and cluster size is a design parameter.*

## 6. What this route cannot establish

1. **No detection or ejection.** A real federation would evict a node draining
   its cluster. Every k\* is a **lower bound** on real tolerance.
2. **No collusion strategy.** Defectors act simultaneously and independently;
   they do not coordinate to concentrate on one cluster — which is the obvious
   next adversary and is out of scope here rather than tested badly.
3. **Fixed clusters.** Churn is R-H1's named next route and is not addressed;
   a defector that can *move* between clusters is a different threat.
4. **Complete uniform trees**, one aggregate, one conserved total, uniform
   per-level staleness, simulated principals.
5. **Nothing about correctness.** Consequence only; the competence bound
   remains terminal.
