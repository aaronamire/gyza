# Findings — Route 6: optimal audit mechanism under a competence-bounded verifier

HEADLINE first (which targeting dimension matters + the feasibility frontier), then
the ε(r) contract, then the two-tier design and its routing floor, then prior-art
honesty, then limits. **Analytic route: zero model calls, zero credits.** NOT a rescue
of any prior route — it changes the *question* (from "detect error cheaply?" to "price
error optimally?"), not the verdict. All prior decisions stand.

## HEADLINE

**1. Target the consequence-to-gain ratio `v/g` — which means stakes DO matter once
gains saturate.** The value density is `ρ_i = (v_i/g_i)·(q_i B_i/c_i)`; the invariant
kernel is the consequence-to-gain ratio `v_i/g_i`. It has two branches:
- **proportional gains (G1, `g=βv`):** `v/g = 1/β` is constant, so stake carries no
  ranking information (`ρ`-CV = 2.6e-16; deterring high- vs low-stake first deters the
  same total to 0.13%);
- **saturating gains (G2, `g=min(βv, g_max)`, `v*=g_max/β`):** above `v*`, `v/g = v/g_max`
  rises with stake, so `ρ` rises linearly with `v` (`ρ`~`v` correlation above `v*` = 1.000)
  and **ranking by consequence IS optimal ranking there** — high-stake claims are the
  right priority precisely because their gain has decoupled from their stake.

Under heavy-tailed stakes the saturated branch governs the **majority of consequence**
(fraction above `v*`: Pareto 0.59, lognormal 0.56, uniform 0.34), so this is not a
negligible tail. The dispersion sources that make targeting valuable, ranked:
**gain saturation (ρ-CV 1.69) > bond heterogeneity (0.90) > competence `q` (0.78) > cost
(0.41).** **Prioritise by `v/g`; meter each claim at its own `p_min = g/(qB)`** (see the
correction note — the naive "audit ∝ stakes" policy overspends the saturated tail and is
2.04× optimal under G2).

> **CORRECTION (Part 1, this revision).** The original headline read *"Consequence is
> the wrong thing to target… Auditing where the money is provides no gain."* **That was
> a derivation error** — it applied the G1 branch (`v` cancels) as if it were general,
> while the same document ranks G2 (saturating gains) as the *largest* dispersion source
> and calls it realistic. Under G2 above `v*`, `ρ ∝ v` rises, so ranking by `ρ` = ranking
> by consequence, and stakes *are* the right target. The corrected invariant is: target
> the **consequence-to-gain ratio** `v/g`. The error inverted design-rule 2 (below) in
> exactly the regime the analysis calls realistic; both the error and the fix are kept on
> the record, same discipline as the Phase 8 canonicalization correction. Numerically
> confirmed: under G2 consequence-order deters the same value as ρ-order (4078.5 =
> 4078.5) and far more than low-first (1840); under G1 all orders tie.

**2. The likelihood ratio `q/f`, not TPR/FPR/J, decides whether a bonded mechanism can
exist at all.** A mechanism both deters lying and retains honest agents iff
`LR = q/f ≥ g/w` (gain-to-honest-profit). The measured operating points:

| regime | TPR | FPR | J | **LR = q/f** | feasible? |
|---|---|---|---|---|---|
| **in-competence** (6B cell-a, n=433) | 0.818 | 0.041 | 0.777 | **19.95** | yes, up to `g/w ≈ 20` |
| **out-of-competence** (6B cell-b, n=36) | 0.556 | 0.444 | 0.111 | **1.25** | only if `g/w ≤ 1.25` — effectively no |

Two checkers with **identical J = 0.5** but different LR (6 vs 2.25) have **opposite**
feasibility at `g/w = 5`. The whole earlier research program measured J; **J is not the
decision-relevant statistic — the likelihood ratio is.** The in-competence checker sits
comfortably inside the feasibility frontier; the out-of-competence checker sits on its
edge.

## The ε(r) bounded-error contract (calibrated)

At audit rate `r = C/(N·c_cheap)`, expected undetected consequential loss under the
optimal cheap-only policy (calibrated `q_in=0.818, q_out=0.111`, α_in=0.6, base-rate
temptation 0.128, `e0` = unaudited baseline):

| `r` | ε(optimal) / e0 | ε(uniform) / e0 |
|---|---|---|
| 0.00 | 1.000 | 1.000 |
| 0.05 | **0.219** | 0.806 |
| 0.10 | 0.219 | 0.674 |
| 0.30 | 0.219 | 0.449 |
| 0.60 | 0.219 | 0.267 |

**The optimal ε plateaus and never improves past a threshold rate.** The residual is
entirely **out-of-competence + bond-capped-undeterrable** consequence a cheap checker
cannot touch at any audit rate; the floor is set by the competence bound, not the budget
(Monte-Carlo reproduces the closed form to 0.02%).

**Two things must be stated precisely (Part-1 corrections):**

- **The plateau's EXISTENCE is robust; its LOCATION is calibration-dependent.** That more
  budget buys nothing past some `r*` is general (the floor is the undeterrable residual).
  *Where* `r*` sits is not: from `π_i = c·g/(q·B)`, the cheap tier saturates once budget
  covers every deterrable in-competence claim, i.e. at
  `r* ≈ α · E[g/(q_in B)] / c_cheap` (for the calibrated draw, `r* ≈ 0.05`). A different
  `β` (gain-to-stake), bond cap, or base rate moves `r*`. **Measure your own plateau; do
  not assume 5%.**
- **`0.22` is a RATIO (a 78% reduction), NOT an absolute error bound.** The plateau says
  ε(optimal) `≈ 0.22 · e0`, where `e0` is the unaudited baseline — a relative reduction,
  not a procurement-grade absolute guarantee. The **absolute** form is
  `ε_floor ≈ N · λ · [(1−α)·E[v | out] + α·P(g>q_in B_max)·E[v | undeterrable]]`, i.e. the
  base-rate (`λ ≈ 0.128`) times the out-of-competence-plus-undeterrable consequence mass
  of the actual claim distribution. A bounded-error *contract* must quote this absolute
  number for the deployment's own `N, λ, α, v`-distribution — the ratio alone is not a
  contract.

**Robustness of the composition.** Sweeping `q_out` across the full underpowered interval
`[0, 0.3]`, the fraction of residual loss from out-of-competence claims stays
**0.70–0.96** — the floor's *composition* is robust to the exact (uncertain) `q_out`.
DEMONSTRATED-ROBUST, not a point-estimate artifact. (The `0.219` ratio itself is at the
calibrated `q_out`; treat it as illustrative, the composition as robust.)

## The two-tier design and its routing floor

Out-of-competence claims (`q_out ≈ 0`) are undeterrable by the cheap tier at any rate;
they need the expensive oracle (`q_ex ≈ 1`, cost `c_ex ≫ c_cheap`). A two-tier
mechanism routes claims and audits each in its tier. At **scarce budget** (`r = 0.05`,
`c_ex = 20`) two-tier beats single-tier all-expensive (ε 1860 vs 3833 at perfect
routing). Misrouting is **asymmetric**: out→cheap is dangerous (leaks), in→expensive is
merely wasteful.

**Stated precisely (Part-1 correction):** the sweep shows that *under budget scarcity,
even an uninformative router (accuracy 0.5) beats all-expensive.* That is a statement
about **scarcity** — when the oracle is too expensive to apply broadly, splitting off any
cheap capacity helps — **not** about routing *quality*. Routing quality still matters
monotonically (ε falls from 2737 at acc 0.5 to 1860 at acc 1.0); a better router is
strictly better. The correct claim is: *two-tier dominates single-tier whenever budget is
scarce, and the gain grows with routing accuracy* — not "routing accuracy down to 50% is
fine" in general. At abundant budget with a tight bond cap the ordering can flip (single
wins), so the result is scarcity-conditional.

**Regime caveat (PARAMETER-DEPENDENT).** The two-tier win is a budget-scarcity effect.
At *abundant* budget with a *tight* bond cap, single-tier all-expensive can win, because
the higher `q_ex` deters bigger bond-capped whales. The mechanism designer must know
which budget regime they are in.

**The weakest link, stated plainly.** The two-tier design assumes a router that
classifies "is this claim within the checker's competence" *before* auditing. If that
classification is *itself* out-of-competence, the competence bound re-enters one layer
up — precisely the R5 failure mode (an LLM step re-importing the bound). Routing
accuracy must be treated as an empirical, monitored quantity, never assumed.

## Other verified results (see PROPOSITIONS.md for proofs + numbers)

- **P1 deterrence.** Lie iff `g > p q B`; claims with `g > q B` are undeterrable at any
  `p ≤ 1` (9.5% of claims at `B_max=3`). Threshold flips exactly in simulation.
- **P3 bond ⇄ targeting substitution.** Raising `B_max` lowers ε under both uniform and
  optimal policies; bonds and targeting are substitute levers. Targeting's marginal
  value peaks at intermediate bond capacity and declines as the undeterrable set empties.
- **P6 collusion-proofness.** Under committed, independent, profile-*independent*
  randomisation, a coalition's joint best-response equals independent best-responses
  (brute-forced over `2^14`). It breaks under adaptive auditing: flooding `3N` decoys
  dilutes a target's audit probability 4.65×. **Commit to marginals the realised profile
  cannot move.**

## Prior-art honesty

The framework is **not new**. Townsend (1979) costly state verification, Becker (1968)
deterrence, Reinganum–Wilde tax-audit theory, and Stackelberg security games (Tambe;
Korzhyk et al.; von Stengel & Zamir) supply P1–P3 and P6 as KNOWN or KNOWN-VARIANT. The
genuine contribution is narrow and empirical:

1. treating the **competence-bounded, measured `q`** as a first-class parameter;
2. the **two-tier routing corollary** with its asymmetric-misrouting accuracy floor (P4);
3. the **ε(r) contract whose floor equals the measured out-of-competence mass** (P5);
4. the **LR-not-J feasibility frontier** with the measured operating points (P7).

"This framework is known; our contribution is the empirical calibration and the
tier-routing corollary" is the honest one-line summary. We do not claim to have invented
optimal auditing.

## Limits (what this does NOT establish)

- **Single-shot, risk-neutral.** Repeated play and risk-aversion both deter more
  cheaply; this is a conservative one-shot bound (A4 also uses the conservative penalty
  form). Real reputation systems will do better than ε(r) predicts.
- **`q_out` is measured on n=36 with a CI including 0.** Every result is reported over
  the `[0,0.3]` sweep; the *floor composition* is robust, but the exact out-of-competence
  detection rate is not pinned down. Treat `q_out` as an interval, never a point.
- **The router (A8) is the weakest link and is modelled as free.** Its real cost, and
  the risk that competence-classification is itself out-of-competence, are the two things
  most likely to break a deployment. This is flagged, not solved.
- **Endogenous submission, heterogeneous agent skill, correlated detection** are not
  modelled.
- **No suspiciously-clean number survived unexamined.** The one very clean result — the
  ρ-CV = 2.6e-16 cancellation — is an exact algebraic identity (`v` literally cancels),
  verified by order-indifference, not a coincidence. The ε-plateau at 0.219 was diagnosed
  to the out-of-competence residual, not reported as magic. The three initial
  proof/simulation disagreements (G1-cancellation policy claim, top-k exploitability
  regime, two-tier budget regime) were resolved by **fixing the propositions**, not the
  simulator, and the corrected regime-dependencies are reported as robust-vs-parameter-
  dependent labels above.

## What it means for the program

Routes 2–5 and Phases 6B/7 established you cannot *detect* out-of-competence error
cheaply. Route 6 shows the economic consequence precisely: **a bonded audit mechanism
can price in-competence error into deterrence with a cheap checker (LR 19.8, feasible,
ε floored at ~0.22×baseline), but out-of-competence error is both undetectable *and*
un-priceable (LR 1.25) — it must be routed to ground-truth resolution.** The competence
bound is not merely a detection ceiling; it is a hard floor on any incentive mechanism
built over the checker. The design response is not a better detector — it is to
**bound claims to the checker's competence and send the rest to reality.**
