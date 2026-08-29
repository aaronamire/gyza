# R-T — the targeted asymmetric adversary: preregistration (Gate 0)

**Committed before any experiment code exists.** Nothing else is in this
directory. **Zero credits**; exact rational arithmetic, no model call.

---

## 0. The threat, named by R-D as the sharpest one open

`research/disperse/FINDINGS.md` §6.1, verbatim:

> **A targeted asymmetric adversary.** The strongest attack would spare the
> target's cluster deliberately while draining every other — maximising
> asymmetry rather than damage. §5 says that is the right design and it is
> **not tested here.** This is now the sharpest open threat.

Every k\* in this program — R-B's 103, R-C's 511, R-D's None — was measured
against an adversary that placed defectors **at random**. R-D then established
that reach and damage are *anti-correlated* with breach, and that **only
asymmetry predicts it**. So every published k\* is a lower bound against an
adversary that was never optimising the quantity that matters.

## 1. The mechanism the attack exploits

`Tree.divest` withdraws a leaf's **pool claim first**, shrinking its cluster's
pool and therefore every sibling's claim. The held-out target is leaf 0, whose
total is `holdings[0] + contrib[0]·pool[0]/funded[0]`.

**A defector placed in cluster 0 destroys the target's own numerator.** R-B's
random placement puts ≈1.6 defectors per cluster, so ≈1.6 of them land in
cluster 0 and work *against* the attack. Removing them is free to the adversary.

Measured in the pre-run structural check: leaf 0 holds **14.151** with no
defector in its cluster and **14.001** with one — **+1.07%**.

## 2. Four arms, differing ONLY in where defectors are placed

The round loop, the modes, the staleness model and the environment are R-B's
`defect_tree.py`, **imported READ-ONLY**. Only the placement rule changes, so
any difference is attributable to placement and to nothing else.

| arm | placement |
|---|---|
| **RANDOM** | R-B's shuffled order. **The control** — must reproduce k\* = 103 |
| **SPARE** | drawn only from the 504 principals outside the target's cluster |
| **SPARE_EVEN** | same exclusion, round-robin over the 63 non-target clusters so none is left undamaged. **The strongest arm** |
| **CONCENTRATE** | the target's 7 siblings filled first, then the rest. The opposite extreme |

## 3. Feasibility, computed BEFORE the run — standing rule #4

Maximum attainable concentration at each arm's extreme k, against κ = 0.60:

| arm | extreme k | max | total | concentration |
|---|---|---|---|---|
| RANDOM | 511 | 14.000 | 14.000 | **1.0000** |
| SPARE | 504 | 14.151 | 15.205 | **0.9306** |

**Both exceed κ with large headroom, so k\* is well-defined in every arm and the
comparison is not a ratio against an unreachable target** — the defect E1-HOLDS
and R-B each hit.

**The exact 1.0000 is definitional and is declared here rather than diagnosed
later** (rule #2): at k = 511 every non-target leaf sheds to zero, so leaf 0 is
the only surviving holder and `max = total` identically.

**The arms have different k domains** — RANDOM and CONCENTRATE range over
[1, 511], SPARE and SPARE_EVEN over [1, 504], since 7 principals are ineligible
by construction. The control sits at 103, far from either limit, so the domains
do not confound the comparison. Stated because if any k\* approached 504 it
*would*.

## 4. Measures

- **k\*** per arm — integer, exactly comparable.
- **k\*/clusters** — R-B's invariant is ≈1.61 defectors per cluster. SPARE
  arms have **63** usable clusters, not 64, and the ratio is computed against
  each arm's own count.
- **`peak_concentration`** — reported for every cell, so a non-breaching arm
  says *how close* it came instead of only "no".
- **`defectors_in_target_cluster`** — a mechanism check. An arm that claims to
  spare cluster 0 must be *shown* to place zero defectors there; registering a
  placement rule is not evidence that it runs.
- **`honest_refusal`** — the economy counter-metric, beside every k\*.

## 5. Decision rules, feasibility checked

| rule | threshold | trivially satisfiable? |
|---|---|---|
| **TARGETING-HELPS** | k\*(SPARE_EVEN) < 103 | No — the two previous "smarter" adversaries (R-C collide, R-D disperse) both came out **worse** than random |
| **TARGETING-BREAKS** | k\*(SPARE_EVEN) ≤ 52, a 2× improvement | No |
| **ASYMMETRY-ORDERS** | k\* monotone: CONCENTRATE ≥ RANDOM ≥ SPARE ≥ SPARE_EVEN | No — R-D's ordering could fail in either direction |
| **MECHANISM-RUNS** | SPARE arms measure 0 defectors in cluster 0; CONCENTRATE measures 7 | Mandatory |
| **COVERAGE** | k = M−1 tested before any `None` is returned | Mandatory — R-M1's defect, and it recurred in R-E one route ago |

## 6. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-T0** | RANDOM reproduces k\* = 103 | **YES, definitional** — the control; a mismatch voids the route |
| **P-T1** | **TARGETING-HELPS** | **YES.** §1's mechanism is arithmetic, not conjecture: removing a defector from cluster 0 is a free gain to the adversary |
| **P-T2** | k\*(SPARE_EVEN) lands in **[85, 102]** | **YES, and this is the risky estimate.** At k = 103 random measures concentration 0.5659; a +1.07% numerator gives ≈0.572, still short of 0.60. The lever is real but small |
| **P-T3** | **TARGETING-BREAKS is REFUTED** — *the route's bet* | **YES.** If it holds, R-B's k\*/clusters ≈ 1.6 invariant survives an adversary optimising the one quantity R-D showed matters, and every published k\* is a *tight* lower bound rather than a loose one |
| **P-T4** | **ASYMMETRY-ORDERS** holds, monotone across all four | **YES** — R-D §5's table predicts it, and this is the first direct test of that claim rather than an inference from three separately-designed attacks |
| **P-T5** | k\*(SPARE_EVEN) < k\*(SPARE) | **YES** — random placement over 63 clusters leaves some undamaged by chance; round-robin does not |

**P-T3 is a SAFETY prediction, and it is the one worth being wrong about.** The
program has published five k\* values against adversaries that never optimised
asymmetry. If deliberate targeting halves k\*, every one of them is loose and
the per-cluster invariant is an artifact of random placement. If it does not,
the invariant is robust to an adversary that knows exactly who to spare.

## 7. What this route cannot establish

1. **The adversary is given the target's identity for free.** Worst-case by
   construction, and unrealistic — a real attacker must first discover which
   principal is the max holder, and that principal changes as the trajectory
   runs. Every k\* here is a lower bound *for that reason too*.
2. **The target is fixed for the trajectory** (the defect-#5 fix carried from
   earlier routes). A target that moves would require re-aiming mid-run and is
   a different, harder attack.
3. **No detection or ejection.** An adversary that spares exactly one cluster
   is *more* detectable than a random one, not less.
4. **One aggregate.** The ratio only. R-E established that extensive bounds are
   priced on a different curve, and no arm here is scored against one.
5. **Placement only.** The modes (SHED/SKEW/HOARD) and regimes
   (UNILATERAL/SUPERVISED) are R-B's; a defector that games a check rather than
   ignoring it remains untested (R-B §7.1).
6. **Nothing about correctness.** Consequence only.
