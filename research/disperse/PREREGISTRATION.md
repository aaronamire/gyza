# R-D — the dispersing adversary: preregistration (Gate 0)

**Committed before any experiment code exists.** Nothing else is in this
directory. **Zero credits**; exact rational arithmetic, no model call.

---

## 0. The gap this closes, which is my own

R-C measured that churn does **not** restore the staleness horizon, and that
k\* *rose* under churn (103 → 511). R-C §3 states plainly why that refutation is
weak:

> *Defectors migrate to the fullest pool, so every defector chooses the same
> destination and they self-concentrate. A concentrated attack is weaker than a
> distributed one — which is R-B's k\*/clusters result read backwards.*

**The adversary was coordinated but naive.** R-C named deliberate dispersion as
its main untested case and as the one thing that could still overturn its §1.
This route is that case.

## 1. Why dispersal should be strictly better for the attacker

R-B established the invariant: **≈1.6 defectors per cluster**, so 64 clusters
need ≈103 stationary defectors.

A migrating defector drains its *share* of each pool it reaches — under
CLAIM_TRAVELS its `contrib` moves with it, so it arrives holding an entitlement
in a pool it has not yet drained. Over T rounds one disperser produces up to
**T cluster-visits** instead of one.

If a visit drains roughly a `contrib/funded` share (≈1/8 of a pool at f = 8),
then k dispersers over 40 rounds yield ≈5k cluster-equivalents, and the
stationary requirement of ≈103 predicts **k\* ≈ 20**.

That is a 5× improvement over stationary and a 25× improvement over R-C's
colliding adversary. **If it does not appear, R-C's conclusion is much stronger
than R-C could claim.**

## 2. The adversary

**DISPERSE** — each defector migrates each round to the cluster it has **not
yet visited** with the fullest pool, falling back to the fullest overall once
all have been visited. Defectors do not coordinate with each other beyond this
rule; there is no central assignment.

Contrasted against R-C's **COLLIDE** (fullest pool, ignoring history), kept as
the control so the difference is attributable to dispersal alone.

## 3. Environment

`research/churn/churn_tree.py` is **imported READ-ONLY** — it reproduces R-B's
k\* = 103 at r = 0, which is the control that licenses any comparison. Only the
destination rule changes. Exact integer nano-units, no tolerance parameter.

**Gate 0:** violations from `Tree.concentration_exceeds`, exact, guard-blind.
**GATE 0c:** UNDEFINED counted and excluded.

## 4. Measures

- **k\*** — smallest breaching defector count. Integer, exactly comparable.
- **`pools_touched`** — distinct commons one defector drained from. Under
  DISPERSE this should approach `min(rounds, n_clusters)`.
- **`clusters_below_half`** — clusters driven under half their genesis value.
  **The damage measure, separate from reach**, because R-C established those
  are different things and conflating them is what made reach look load-bearing.
- **δ\* and the horizon** at ε ∈ {8, 32, 128}, only if k\* falls materially.

## 5. Decision rules, feasibility checked BEFORE the run

k ∈ [1, 511], integer. At r = 0 the instrument gives 103; R-C's collide gives
511. Both endpoints are established, so **the comparison has a real baseline
and is not a ratio against zero** — the defect E1-HOLDS and R-B both hit.

| rule | threshold | trivially satisfiable? |
|---|---|---|
| **DISPERSAL-HELPS** | k\*(DISPERSE) < 103 (the stationary baseline) | No — R-C's migrating adversary measured 511 |
| **DISPERSAL-BREAKS** | k\*(DISPERSE) ≤ 10, i.e. a 10× improvement | No |
| **HORIZON-RETURNS** | with DISPERSE, some ε ≤ 128 has no feasible δ | No — R-N and R-C both found none |
| **REACH-vs-DAMAGE** | `clusters_below_half` reported beside `pools_touched` | Mandatory — R-C's central distinction |
| **COVERAGE** | every INFEASIBLE swept from the ceiling down, then the interior | Mandatory — R-M1's defect |

## 6. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-D0** | COLLIDE reproduces R-C: k\* = 511 at r = 1 | **YES, definitional** — the control; a mismatch voids the route |
| **P-D1** | **DISPERSAL-HELPS**: k\*(DISPERSE) < 103 | **YES** — §1's cluster-visit argument |
| **P-D2** | k\* lands in **[10, 40]** | **YES**, and this is the risky point estimate — ≈5 cluster-equivalents per disperser over 40 rounds |
| **P-D3** | `pools_touched` ≈ min(rounds, clusters) = 40 | **YES, near-definitional** for the destination rule; stated so reach is measured not assumed |
| **P-D4** | `clusters_below_half` under DISPERSE **exceeds** COLLIDE at equal k | **YES** — this is what dispersal is *for*, and if it fails the mechanism is not what §1 says |
| **P-D5** | the horizon still does **not** return | **YES** — entitlement is conserved under CLAIM_TRAVELS regardless of routing, which is R-C's actual mechanism |

**P-D5 is the one that matters.** If dispersal drops k\* sharply *and* the
horizon still does not return, then R-C's mechanism — *bounded entitlement, not
bounded reach* — is confirmed by the attack designed to defeat it. If the
horizon **does** return, R-N narrows and the planetary claim narrows with it.

## 7. What this route cannot establish

1. **No detection or ejection.** A principal that drains a pool and immediately
   leaves is the most detectable behaviour in this whole program. Every k\* here
   is a **lower bound** and this adversary is the least realistic one yet.
2. **No inter-defector coordination** beyond the shared destination rule; a
   central assignment covering every cluster exactly once would be stronger.
3. **Commons membership churns; the admission tree does not.**
4. **One aggregate**, one conserved total, uniform staleness, simulated
   principals.
5. **Nothing about correctness.** Consequence only.
