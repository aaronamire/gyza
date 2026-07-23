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

## 2. Target detectability and gain-shape, NOT consequence

- **Rule.** Rank claims for audit by value density `ρ_i = v_i q_i B_i /(c_i g_i)`, not by
  stake (P2).
- Under proportional gains (`g ∝ v`) the stake **cancels** — consequence-weighted
  auditing buys nothing (P2, ρ-CV ≈ 0). Do not build a "watch the big-money claims"
  policy; it is provably no better than random selection at the optimum.
- The dispersion worth exploiting is (ranked, measured): **gain saturation → bond
  heterogeneity → the competence bound `q` → cost heterogeneity.** Audit where detection
  is strong and where lie-gains saturate.

## 3. Route claims between a cheap tier and a ground-truth oracle — and monitor the router

- **Rule.** Classify each claim as in- or out-of the cheap checker's competence, audit
  in-competence claims cheaply (`q_in ≈ 0.82`) and out-of-competence claims via the
  expensive oracle (`q_ex ≈ 1`) (P4).
- Two-tier beats all-expensive **whenever budget is scarce**, and is robust to routing
  accuracy **down to ~50%** in that regime (P4). Misrouting is asymmetric: **out→cheap
  leaks (dangerous); in→expensive only wastes budget.** Bias the router toward
  over-escalating (send the uncertain ones to the oracle).
- **Weakest link:** if deciding "is this claim within competence" is itself
  out-of-competence, the bound re-enters through the router (the R5 failure mode). Treat
  routing accuracy as a **measured, monitored** quantity with alarms, never an
  assumption. Re-measure on live traffic.
- **Regime caveat:** at abundant budget with a tight bond cap, all-expensive can beat
  two-tier. Know your budget regime.

## 4. What audit rate to run, and what ε it guarantees

- **Rule.** Run the smallest rate on the ε(r) plateau — for the calibrated parameters,
  `r ≈ 0.05` (audit ~5% of claims) already reaches the optimal floor; **higher rates
  buy nothing** on the cheap tier (P5).
- **Guarantee (bounded-error contract):** above `r ≈ 5%`, undetected consequential error
  under the optimal policy is `≤ ~0.22 × (unaudited baseline)`. That 0.22 is the
  out-of-competence + undeterrable share and is **not** reducible by more cheap auditing
  — only by the oracle tier and larger bonds.
- Report ε over the `q_out ∈ [0, 0.3]` sweep, never a point estimate — the residual
  *composition* (70–96% out-of-competence) is robust, the exact rate is not.

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

Bond from the gain (capped by capital); rank audits by `v q B /(c g)`, not by stake;
audit ~5% and accept a ~0.22×baseline error floor on the cheap tier; admit a claim to
the cheap rail only if its likelihood ratio `q/f ≥ g/w`; route everything
out-of-competence or undeterrable to a ground-truth oracle; commit to a
profile-independent randomisation. The competence bound is not just a detection ceiling
— it is a hard floor on the whole incentive mechanism, and the only way through it is
reality contact, not a cleverer detector.
