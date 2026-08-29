# R-C — churn: findings

**Preregistration:** `PREREGISTRATION.md`, committed `f30643d` as the only file
in this directory, BLAKE3
`b4996f361e66957a980c25ac0e4f5ea3a7ab42bf4959fbeb68039958bc388d88`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic.

**Verdict: `REACH-BREAKS-DAMAGE-DOES-NOT`.** R-N survives its most likely
attack. **The route's own bet — P-C2 — lost.**

---

## 1. The headline: the horizon does not return

R-N found the tree's required margin saturates at **68.68%** of ceiling,
identical at ε = 32, 64, 128. Under **maximal churn (r = 1.0, adversarial)**:

| policy | ε=8 | ε=32 | ε=128 |
|---|---|---|---|
| CLAIM_TRAVELS | 0.4700 (65.4%) | 0.4950 (68.9%) | **0.4950 (68.9%)** |
| CLAIM_STAYS | 0.4700 (65.4%) | 0.4900 (68.2%) | **0.4900 (68.2%)** |
| *R-N, no churn* | *0.4684 (65.2%)* | *0.4934 (68.68%)* | *0.4934 (68.68%)* |

**Saturation survives, and the value barely moves** — 68.9% against 68.68%.
The staleness horizon stays absent under the attack designed to restore it.

## 2. Why: migration moves a claim, it does not create one

`pools_touched` — the number of distinct commons one defector drew from — rises
exactly as predicted:

| rate | 0 | 0.1 | 0.5 | 1.0 |
|---|---|---|---|---|
| pools reached | **1** | 10 | 30 | **41** |

**Compartmentalisation of REACH breaks completely.** A defector at r = 1 touches
41 of 64 clusters.

And it does not matter, because a migrant's `contrib` is fixed. Its claim on any
pool is `contrib × pool/funded`; moving relocates that entitlement rather than
duplicating it. **Reaching forty-one pools does not let you drain forty-one
pools' worth** — you drain your share of each, and your share is the same total.

> **Compartmentalisation of reach is not what R-N depended on. Compartmentalisation
> of entitlement is, and migration does not touch it.**

That distinction was not visible before this route, because at r = 0 the two
coincide.

## 3. k\* went UP, and the reason is an adversary limitation I must state

| mode / policy | r=0 | r=0.1 | r=0.5 | r=1.0 |
|---|---|---|---|---|
| ADVERSARIAL / TRAVELS | **103** | 64 | 444 | **511** |
| ADVERSARIAL / STAYS | 103 | 235 | 504 | 511 |

**P-C1 predicted k\* ≤ 4. It measured 511.** Non-monotone, and mostly *rising*.

**The refutation is weaker than it looks, and the reason is my adversary.**
Defectors migrate to the *fullest* pool, so **every defector chooses the same
destination** and they self-concentrate into one cluster. A concentrated attack
is weaker than a distributed one, which is exactly R-B's k\*/clusters result
read backwards. A smarter adversary would spread deliberately.

So `CHURN-BREAKS` is refuted **against a coordinated-but-naive adversary**, and
the sharper attack — deliberate dispersion — is untested. Recorded as the
route's main limitation rather than claimed as a general result.

## 4. The frame decision is a safety parameter — in both directions

P-C3 predicted CLAIM_TRAVELS would be strictly worse. **The policies differ
enormously, and neither dominates:**

| | CLAIM_TRAVELS | CLAIM_STAYS |
|---|---|---|
| ADVERSARIAL, r=0.1 | k\* = **64** *(worse)* | k\* = 235 |
| BENIGN, r=0.1 | k\* = 61 | k\* = **1** *(catastrophic)* |

**CLAIM_STAYS collapses under benign churn.** Setting `contrib = 0` on every
move means ordinary reassignment *annihilates* entitlement: benign churn moves
everyone, the commons evaporates, total value collapses, and one defector
finishes it. **k\* = 1 there is not compartmentalisation failing — it is the
policy destroying the thing being compartmentalised.**

> The safe policy depends on which churn you expect. Adversarial migration
> favours CLAIM_STAYS; benign reassignment demands CLAIM_TRAVELS. **A system
> that picks one without naming its threat model picks wrong half the time.**

That is the transferable result, and it is the one the route was designed to
find regardless of direction.

## 5. Predictions, scored — my bet lost

| | prediction | outcome |
|---|---|---|
| **P-C0** | r=0 reproduces k\* = 103 and pools = 1 | **CONFIRMED exactly** — the instrument reproduces the environment it attacks |
| **P-C1** | CHURN-BREAKS: k\* ≤ 4 at r=1 | **REFUTED** — 511. Weakened by §3's adversary limitation |
| **P-C2** | HORIZON-RETURNS — *the route's bet* | **REFUTED.** Saturation survives at 68.9% vs 68.68% |
| **P-C3** | POLICY-MATTERS, TRAVELS worse | **CONFIRMED that they differ; DIRECTION REFUTED** — it is threat-dependent |
| **P-C4** | benign degrades gracefully | **HALF** — holds for TRAVELS (61), fails for STAYS (1) |
| **P-C5** | pools_touched ≈1 at r=0, rising | **CONFIRMED** — 1 → 10 → 30 → 41 |
| **GRACEFUL** | k\* monotone in r | **REFUTED** — 103 → 64 → 444 → 511 |

Two confirmed, three refuted, one half, one rule refuted. **The route bet
against our own strongest result and lost, which is the outcome that leaves
R-N standing.**

## 6. What this changes

**R-N's headline no longer needs the qualifier I expected to add.** I wrote in
R-N §6.5 that churn "would attack exactly the compartmentalisation this result
depends on." It does attack it — and the attack lands on *reach*, which turns
out not to be load-bearing.

The corrected statement of what hierarchy provides:

> A stale reader's error is bounded by **the entitlement it holds**, not by the
> set of pools it can reach. Hierarchy bounds entitlement per principal;
> migration redistributes reach without changing entitlement. So the horizon is
> removed by the **partition of stake**, and churn does not restore it.

## 7. What this route cannot establish

1. **A dispersing adversary** (§3). Defectors here all migrate to the same
   fullest pool and collide. This is the most important untested case and it
   is the one that could still overturn §1.
2. **No detection or ejection** — a principal that drains a pool and migrates is
   exactly what a real federation would notice. Every k\* is a lower bound.
3. **Commons membership churns; the admission tree does not.** Re-parenting the
   whole hierarchy is a larger change and out of scope.
4. **One aggregate**, one conserved total, uniform staleness, simulated
   principals.
5. **Nothing about correctness.** Consequence only; the competence bound
   remains terminal.
