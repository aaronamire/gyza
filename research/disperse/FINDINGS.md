# R-D — the dispersing adversary: findings

**Preregistration:** `PREREGISTRATION.md`, committed `004270d` as the only file
in this directory, BLAKE3
`a1fce15145552756b8beb643983a3b5e37c425b7a0f32a333a699256de2d8ff0`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic.

**Verdict: `DISPERSAL-IS-SELF-DEFEATING`.** The attack R-C could not test is
**strictly worse than the one it did test**, and the reason closes the question
rather than leaving it open.

---

## 1. The result

| adversary | k\* | reach | clusters below half |
|---|---|---|---|
| stationary (r = 0, R-B) | **103** | 1 | — |
| COLLIDE (r = 1, R-C) | 511 | 36 | 64 |
| **DISPERSE (this route)** | **NONE in [1, 511]** | **41** | 64 |

**No number of dispersing defectors breaches the bound.** Every one of the 511
non-target principals can defect, migrate to a fresh cluster every round, and
drain its share of 41 of the 64 commons — and global concentration never
crosses κ.

P-D1 predicted k\* < 103. P-D2 predicted k\* ∈ [10, 40]. **Both refuted, in the
opposite direction.**

## 2. Why: a ratio is scale-invariant, and dispersal is symmetric

Measured over a k = 103 DISPERSE trajectory:

| round | total federation value | max holder | concentration |
|---|---|---|---|
| 0 | 1211.88 | 14.163 | 0.0117 |
| 1 | 426.44 | 15.005 | 0.0352 |
| 5 | 63.93 | 14.258 | 0.2230 |
| 40 | **50.05** | **14.258** | **0.2848** |

**96% of all value in the federation is destroyed and the bound is never
approached.** κ = 0.60; the attack peaks at 0.285.

Two things are happening, and the second is the one R-C could not see:

1. **Total entitlement is conserved.** Under CLAIM_TRAVELS a migration moves
   `contrib` between `funded` totals; it never creates any. So the federation's
   floor is structural and the denominator cannot be driven to zero.
2. **Dispersal drains the target's cluster too.** A disperser visits *every*
   cluster including the held-out target's, which drains the target's own pool
   claim. The max holder falls from 20 to **14.258 — bare `ACCT`, its entire
   claim gone.** The attack destroys its own numerator.

> **A ratio bound is scale-invariant. Uniform destruction does not move it. An
> attacker must maximise ASYMMETRY, not damage — and dispersal is the most
> symmetric strategy available.**

That is why the stationary attack is the strongest of the three: with ~1.6
defectors per cluster, the target's cluster is drained *least*, so the numerator
survives while the denominator falls. **Concentration is breached by sparing the
target, not by hurting everyone.**

## 3. What this settles

R-C's refutation of CHURN-BREAKS was explicitly weakened by its adversary being
"coordinated but naive". R-D removes that caveat:

- COLLIDE reproduces R-C exactly (k\* = 511 — P-D0 confirmed), so the comparison
  is attributable to routing alone.
- DISPERSE, the strictly smarter routing, is **strictly worse for the attacker**.

**R-C's conclusion therefore stands without its stated limitation**, and R-N's
horizon result survives both attacks designed to break it.

## 4. Predictions, scored — three refuted

| | prediction | outcome |
|---|---|---|
| **P-D0** | COLLIDE reproduces k\* = 511 | **CONFIRMED exactly** |
| **P-D1** | DISPERSAL-HELPS: k\* < 103 | **REFUTED** — never breaches at any k |
| **P-D2** | k\* ∈ [10, 40] | **REFUTED** — the cluster-visit argument in §1 of the preregistration was wrong because it counted damage, not asymmetry |
| **P-D3** | reach ≈ min(rounds, clusters) = 40 | **CONFIRMED** — 41 |
| **P-D4** | `clusters_below_half` higher under DISPERSE | **REFUTED — and the metric was saturated.** Both arms read 64/64. Same defect species as R-B's `clusters_damaged`: a measure pinned at its maximum reports the maximum, not the treatment |
| **P-D5** | the horizon still does not return | **CONFIRMED, trivially** — the attack never breaches at δ = 0, so there is no margin to exhaust |

**My §1 reasoning was wrong in a specific and instructive way.** It computed
*cluster-visits × damage-per-visit* and concluded k\* ≈ 20. Damage is the wrong
currency for a ratio: the argument would have been right for a bound on total
value, and concentration is not that.

## 5. The three attacks, and what actually threatens a ratio

| | reach | total damage | asymmetry | breaches? |
|---|---|---|---|---|
| stationary | 1 cluster | moderate | **high** | **yes, at k = 103** |
| collide | 36 | high | low | at k = 511 |
| disperse | 41 | **highest (96%)** | **lowest** | **never** |

Reach and damage are both **anti-correlated** with success. Only asymmetry
predicts it. Any future adversary against a ratio-type invariant should be
designed to maximise asymmetry, and this table is the reason.

## 6. What this route cannot establish

1. **A targeted asymmetric adversary.** The strongest attack would spare the
   target's cluster deliberately while draining every other — maximising
   asymmetry rather than damage. §5 says that is the right design and it is
   **not tested here.** This is now the sharpest open threat.
2. **No detection or ejection**, and a principal that drains a pool and leaves
   every round is the most detectable behaviour in this program. Every k\* is a
   lower bound.
3. **Ratio aggregates only.** A bound on *total value* would have been breached
   catastrophically by this exact attack — 96% destroyed. Nothing here says a
   non-scale-invariant aggregate is safe; it says the opposite.
4. **Commons membership churns; the admission tree does not.**
5. **Nothing about correctness.** Consequence only.
