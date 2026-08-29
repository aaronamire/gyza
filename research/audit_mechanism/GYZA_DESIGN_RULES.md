# Gyza design rules implied by Route 6

Operational rules for a bonded audit mechanism over a competence-bounded checker.
Every rule traces to a proposition (`PROPOSITIONS.md`) verified in
`audit_simulator.py`. Calibration: `consistency_defensibility/FINDINGS_CORRECTION.md`
(Phase 8). These are engineering defaults, not a deployment commitment — the checker's
`q_in/q_out` must be re-measured on Gyza's own claim distribution before relying on any
number here.

## 1. Set bonds from the gain, capped by capital — and know the cap is what forces targeting

- **Rule.** Require `B_i ≥ g_i / (q_i · p_target)` for a chosen operating audit
  probability `p_target`. Then uniform auditing at `p_target` deters claim `i` (P1, P3).
- If bonds could scale freely with the gain, **uniform auditing would be optimal and no
  targeting or routing would be needed** (P3). Targeting exists only because agents are
  capital-constrained (`B_i ≤ B_max`).
- **Undeterrable set:** any claim with `g_i > q_i · B_max` cannot be deterred at any
  audit rate. Enumerate it explicitly and send it to ground-truth resolution (rule 5).
  At `B_max = 3×` mean stake, ~9.5% of claims were undeterrable in simulation.
- **Lever choice:** raising `B_max` and improving targeting/routing are **substitutes**
  (P3). Compare the marginal cost of more locked capital against the marginal cost of a
  better router before spending on either.

## 2. Prioritise by the consequence-to-gain ratio; meter each claim at its own p_min

- **Rule.** Rank *which* claims to deter by value density `ρ_i = (v_i/g_i)·(q_i B_i/c_i)`
  — whose kernel is the **consequence-to-gain ratio `v_i/g_i`** — and set each deterred
  claim's audit probability to its own `p_i^min = g_i/(q_i B_i)`, **not** proportional to
  stake (P2).
- **Under proportional gains (`g ∝ v`)** the ratio is flat, so stake carries no ranking
  information (ρ-CV ≈ 0). **Under saturating gains (`g = min(βv, g_max)`)** — the
  realistic and dominant case — the ratio rises with stake above `v* = g_max/β`, so **the
  big-stake claims ARE the right priority there** (ρ ∝ v, correlation 1.000). Which
  branch dominates depends on the stake distribution: the share of consequence above `v*`
  is 0.59 (Pareto), 0.56 (lognormal), 0.34 (uniform) — under heavy tails, most of the
  risk lives in the stake-informative branch.
- **Do NOT audit proportional to stakes.** A `p ∝ v` policy overspends the saturated tail
  (measured 2.04× optimal under G2) because tail claims need only the *constant*
  `p_min = g_max/(qB)`, not a stake-scaled probability. Prioritise by `v/g`; meter at
  `p_min`.
- The dispersion worth exploiting, ranked (measured): **gain saturation → bond
  heterogeneity → the competence bound `q` → cost.**

> **CORRECTION (Part 1).** This rule previously read *"Target detectability and gain-shape,
> NOT consequence… Do not build a 'watch the big-money claims' policy."* **That was
> wrong** — it was derived from the proportional-gain (G1) branch alone, where stake
> cancels, and it inverts the correct rule in the saturating-gain (G2) regime the analysis
> itself calls realistic and ranks as the largest dispersion source. Under G2 the
> big-money claims *are* the right priority (their gain has saturated, decoupling from
> consequence). The corrected invariant is the consequence-to-gain ratio `v/g`. The old
> text is preserved here on the record (Phase-8 correction discipline).

## 3. Route claims between a cheap tier and a ground-truth oracle — and monitor the router

- **Rule.** Classify each claim as in- or out-of the cheap checker's competence, audit
  in-competence claims cheaply (`q_in ≈ 0.82`) and out-of-competence claims via the
  expensive oracle (`q_ex ≈ 1`) (P4).
- Two-tier beats all-expensive **whenever budget is scarce**, and the gain **grows
  monotonically with routing accuracy** (ε 2737 at acc 0.5 → 1860 at acc 1.0) (P4).
  Precisely: under scarcity even an *uninformative* router (0.5) beats all-expensive —
  because any cheap capacity helps when the oracle is too dear to apply broadly — but that
  is a statement about scarcity, **not** a licence to run a bad router; a better router is
  strictly better. Misrouting is asymmetric: **out→cheap leaks (dangerous); in→expensive
  only wastes budget.** Bias the router toward over-escalating (send the uncertain ones to
  the oracle).
- **Weakest link:** if deciding "is this claim within competence" is itself
  out-of-competence, the bound re-enters through the router (the R5 failure mode). Treat
  routing accuracy as a **measured, monitored** quantity with alarms, never an
  assumption. Re-measure on live traffic.
- **Regime caveat:** at abundant budget with a tight bond cap, all-expensive can beat
  two-tier. Know your budget regime.

## 4. What audit rate to run, and what ε it guarantees

- **Rule.** Run the smallest rate on the ε(r) plateau — and **MEASURE where your plateau
  is.** The plateau's *existence* (more budget buys nothing past `r*`) is robust; its
  *location* is calibration-dependent. Locate it from your own measured parameters:
  `r* ≈ α · E[g/(q_in B)] / c_cheap` (the rate at which the cheap tier covers every
  deterrable in-competence claim). For the calibrated draw `r* ≈ 0.05`, but a different
  gain-to-stake `β`, bond cap, or base rate moves it — **do not assume 5%** (Part-1
  correction).
- **Guarantee — state it as an absolute number, not a ratio.** The plateau gives a
  *relative* reduction, ε(optimal) `≈ 0.22 · e0` (a 78% cut vs unaudited) — that is **not**
  a procurement-grade bound. The **absolute** floor for a contract is
  `ε_floor ≈ N · λ · [(1−α)·E[v | out] + α·P(g > q_in B_max)·E[v | undeterrable]]`:
  base-rate `λ` times the out-of-competence-plus-undeterrable consequence mass of *your*
  claim distribution. Quote this absolute number, computed for the deployment's own
  `N, λ, α, v`-distribution. It is **not** reducible by more cheap auditing — only by the
  oracle tier and larger bonds.
- Report ε over the `q_out ∈ [0, 0.3]` sweep, never a point estimate — the residual
  *composition* (70–96% out-of-competence) is robust; the exact `0.22` and `r*` are not.

## 5. The claim classes the mechanism CANNOT protect — send them to reality

- **Out-of-competence claims** (checker LR ≈ 1.25): both **undetectable** (Routes 2–5)
  **and un-priceable** — no bond/audit pair both deters lying and retains honest agents
  (P7, feasible only if the lie gains `≤ 1.25×` honest profit). **Do not accept these
  onto the cheap-checker rail.** Route them to ground-truth resolution (the oracle, a
  human panel, or reality contact) or refuse them.
- **Undeterrable claims** (`g_i > q_i B_max`): raise the bond or route to the oracle;
  never leave them on the cheap tier.
- **Feasibility gate (P7):** only admit a claim to the bonded cheap rail if
  `LR_i = q_i/f_i ≥ g_i/w_i`. Check the likelihood ratio, **not** Youden's J or TPR —
  two checkers with the same J can have opposite feasibility.

## 6. Commit to a profile-independent randomised policy

- **Rule.** Publish the audit marginals and **commit** (Stackelberg); make the
  randomisation independent of the realised claim profile (P6).
- **Never** make `p_i` a function of the observed profile (e.g. "audit proportional to
  today's stake mix") — a coalition floods decoys to dilute audit on a target
  (demonstrated 4.65× dilution). Fixed per-claim `p` or fixed marginals are
  collusion-proof; adaptive ones are not.
- **Never** run a deterministic top-k policy — it is the worst performer in every
  simulated cell and leaves a certain-safe hole the adversary takes (the inspection
  game).

## One-paragraph summary

Bond from the gain (capped by capital); prioritise audits by the consequence-to-gain
ratio `v/g` (so big-stake claims matter exactly when gains saturate) and meter each at its
own `p_min = g/(qB)`; run the smallest rate on your *measured* plateau and quote the
*absolute* error floor for your own claim distribution (not the 78%-reduction ratio);
admit a claim to the cheap rail only if its likelihood ratio `q/f ≥ g/w`; route everything
out-of-competence or undeterrable to a ground-truth oracle; commit to a
profile-independent randomisation. The competence bound is not just a detection ceiling
— it is a hard floor on the whole incentive mechanism, and the only way through it is
reality contact, not a cleverer detector.
