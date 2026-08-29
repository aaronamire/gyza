# R-E — extensive bounds: findings

**Preregistration:** `PREREGISTRATION.md`, committed `d621ea1` as the only file
in this directory, BLAKE3
`1972a374b5f8553e470d1c78a8a344800670ab047d15c3771dec3203b0631447`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic.

**Verdict: `THE-RATIO-IS-THE-FLOOR-AND-PRESERVATION-IS-PRICED`.** The route bet
that an extensive bound would be strictly harder than a ratio and would have the
staleness horizon the ratio lacks. **Both refuted.** At the preregistered bar the
two bounds cost the *same* margin; across the bar they separate into a smooth
**pricing curve** with no cliff, which is more useful than the bet was.

---

## 1. The result

δ\* on the **same trajectories**, both predicates scored per round:

| ε | d | δ\*_ratio | %ceiling | δ\*_preserve | %ceiling | retained |
|---|---|---|---|---|---|---|
| 8 | 1 | 0.5950 | 99.5% | 0.5950 | 99.5% | 0.39063 |
| 8 | 3 | 0.4700 | 65.4% | **0.4800** | 66.8% | 0.02341 |
| 32 | 1 | 0.5950 | 99.5% | 0.5950 | 99.5% | 0.39063 |
| 32 | 3 | 0.4950 | 68.9% | **0.4950** | 68.9% | 0.04222 |
| 128 | 1 | 0.5950 | 99.5% | 0.5950 | 99.5% | 0.39063 |
| 128 | 3 | 0.4950 | 68.9% | **0.4950** | 68.9% | 0.04028 |

**EXTENSIVE-HARDER required δ\*_preserve > δ\*_ratio + 2g. It fails in 6 of 6
cells** — identical in five, and one grid step (exactly 2g, not more) in the
sixth.

**PRESERVE saturates at 68.9% of ceiling, ε = 32 and ε = 128 identical.**
R-N's saturation is not a property of scale invariance. **P-E4 refuted.**

## 2. Why: both bounds are violated by the same event

Sweeping δ at d = 3, ε = 32 (3 seeds × 40 rounds = 120):

| δ | ratio viol | preserve viol | retained |
|---|---|---|---|
| 0.4850 | 75 | 87 | 0.00137 |
| 0.4900 | 42 | 66 | 0.00188 |
| **0.4950** | **0** | **0** | 0.04222 |

**PRESERVE is strictly more sensitive at every δ — and flips at exactly the
same one.** The two predicates are not independent tests of the trajectory;
they are two readings of one failure: a leaf shedding below its box floor
because a stale belief told it there was room.

The box floor is *simultaneously* the per-principal preservation bound whose
sum is the total, and the per-principal bound whose max/sum is the
concentration. δ\* is the margin that eliminates overshoot. Once overshoot is
gone, **both** hold; while it remains, **both** fail.

That is why my §2 argument lost. It said "the ratio tolerates the overshoot
that violates preservation." At δ\* there *is* no overshoot to tolerate.

### 2.1 But the coincidence is a property of ρ, and I nearly overclaimed it

The first draft of this section read *"aggregates built over the same
per-principal box share a margin — compute δ\* once and it serves any of
them."* **The preregistration named ρ as the sharpest threat to exactly that
claim (§7.5), so I ran it before committing. The claim does not survive.**

| ρ | δ\*_preserve | % ceiling | vs δ\*_ratio |
|---|---|---|---|
| 0.02 | 0.4950 | 68.9% | **+0.0000** |
| 0.05 | 0.5000 | 69.6% | +0.0050 |
| 0.10 | 0.5050 | 70.3% | +0.0100 |
| 0.20 | 0.5150 | 71.7% | +0.0200 |
| 0.40 | 0.5800 | 80.7% | +0.0850 |
| 0.60 | 0.6550 | 91.2% | +0.1600 |
| 0.80 | 0.6950 | 96.7% | +0.2000 |

**δ\*_ratio is 0.4950 at every one of these rows — the ratio bound has no ρ.**
The extensive bound carries a strictness parameter the ratio does not have at
all, and the margins coincide only at the loose bar the preregistration
happened to calibrate.

> **The ratio's margin is the FLOOR of the extensive bound's margin, not its
> equal.** Bounding concentration buys the weakest preservation guarantee for
> free. Buying more costs margin **monotonically and without a cliff** — 68.9%
> → 96.7% of ceiling as ρ goes 0.02 → 0.80, still feasible at the top.

That is a **pricing curve**, and it is the transferable result: a designer can
read off what a given preservation guarantee costs in staleness tolerance.
`retained` at δ\* tracks ρ within a few points at every row, so the bound is
tight rather than slack — P-E5 generalises across the whole sweep.

## 3. The structural finding: the internal admission checks are INERT

Instrumented over 47,523 divest attempts across four (δ, ε) configurations:
**the level-1, level-2 and level-3 checks fired zero times.** Not rarely —
never.

- **Level 1 is unfireable by construction.** With `want = believed − floor`,
  the check `seen(0,leaf) − want < floor` reduces to `(cum_div − v_div) < 0`,
  and cumulative divestment is monotone non-decreasing.
- **Levels ≥ 2 never bind** because `box_floor_at` scales the floor with the
  level endowment exactly as the level's value drains. Clusters finish at ≈4.5
  against a level-2 floor of 4.24 — marginal, never crossed.

**So hierarchy's benefit is not carried by any check an internal node
performs.** It is carried entirely by `kappa_level(d)` making every *leaf's own*
floor stricter: at d = 3 the leaf floor is 0.5304 against 0.0261 at d = 1, a
20× difference. This corrects how R-H1's result should be read and is indexed
as CORRECTIONS 27.

It also means my preregistered flat control was **mis-specified**: disabling
internal checks while keeping the d = 3 floor changes nothing, and tied 6/6.
The real control is depth.

## 4. Hierarchy still decides feasibility — P-E3 confirmed, after correction

Against the corrected control (d = 1, a single global box over 512 principals):

| | leaf floor | δ\* | margin consumed |
|---|---|---|---|
| d = 1 (flat) | 0.0261 | 0.5950 | **99.5% of ceiling** |
| d = 3 (tree) | 0.5304 | 0.4950 | **68.9% of ceiling** |

Flat is feasible only at the **single top grid point below its ceiling** — a
band of one. **This holds for the extensive bound exactly as for the ratio**,
and P-E3's argument (bounded entitlement bounds overshoot, and that reasoning
never invokes scale invariance) is the one prediction whose stated *mechanism*
also survived.

## 5. What motivated the route survives, in a stronger form

At δ = 0, ε = 0, with **zero defectors and zero rule-breaking**:

**retained = 0.0279 — 97.2% of all federation value destroyed, with 0 ratio
violations.**

> **A ratio bound is compatible with the destruction of 97% of everything, by
> principals who never break a rule.** `max/sum ≤ κ` says nothing about how much
> exists.

That is not fixed by §1's result. §1 says the *margin* coincides at ρ = 0.02,
not that the *bound* does — a system that bounds only concentration remains
blind to the 97%. The fix is to **declare the extensive bound too**, and §2.1
prices it: a 2% preservation floor is free, and the price rises smoothly from
there. **Free is not the same as already-implied**, which is the distinction
this section exists to hold open.

## 6. Predictions, scored — four refuted

| | prediction | outcome |
|---|---|---|
| **P-E0** | at δ = 0 the RATIO holds while PRESERVE fails | **REFUTED as worded.** At ε = 0 *both* hold (retained 0.0279 > ρ = 0.02); at ε ≥ 8 *both* fail. I asserted it was "measured already" from a **churn-environment ε = 1 figure (0.0074)** and carried it into a different environment at ε = 0. Two numbers, two populations — the species of artifact #17 |
| **P-E1** | EXTENSIVE-HARDER | **REFUTED at the preregistered ρ = 0.02, 6 of 6 cells.** CONFIRMED for ρ ≥ 0.20 (§2.1) — so the prediction was right about the *direction* and wrong that it holds at the bar I chose |
| **P-E2** | the gap widens with ε | **REFUTED** — it *shrinks*, to exactly zero |
| **P-E3** | hierarchy still helps for PRESERVE | **CONFIRMED — after correcting a mis-specified control that tied 6/6** (§3) |
| **P-E4** | PRESERVE has a horizon the ratio lacks — *the route's bet* | **REFUTED.** Saturates at 68.9%, identical to the ratio, none through ε = 128 |
| **P-E5** | at δ\*, retained is barely above ρ | **CONFIRMED, and it generalises** — 0.02341 against ρ = 0.02, and `retained` tracks ρ within a few points at every row of §2.1 |

**The route bet against the generality of R-N and lost, which leaves R-N
standing over a second, structurally different aggregate class.**

## 7. What this route cannot establish

1. **Two aggregates, one box.** §2.1 prices preservation against the same
   per-principal box. An aggregate not expressible over that box — R-D's Gini
   and variance are the known non-composing cases — is untested, and the
   pricing curve says nothing about them.
2. **One extensive bound.** Total value only. Not files deleted, not
   irreversible actions, not H3 mesh exits.
3. **No defectors.** Every δ\* here assumes full compliance and is optimistic;
   R-B/R-C/R-D measured the defector axis on the ratio only.
4. **The honest population still sheds maximally** — inherited from AG-3. A
   population that preserves by default makes PRESERVE easier and is a
   different experiment.
5. **The pricing curve is one environment, one ε, one depth.** §2.1 sweeps ρ
   at d = 3, ε = 32 only. Whether the curve's *shape* is stable across depth and
   staleness is untested, and it is what a designer would actually need.
6. **ρ > 0.80 was never reached.** The curve is still feasible at its last
   measured point, so no frontier was found — only its absence up to 0.80. A
   bound near 1.0 (preserve almost everything) is where a cliff would live if
   there is one.
7. **Nothing about correctness.** Consequence only; the competence bound
   remains terminal.
