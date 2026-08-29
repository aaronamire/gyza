# Route 6 — propositions, proofs, numerical checks, prior art

Each proposition is proved analytically, verified against `audit_simulator.py`
(the referee — a proof that fails simulation is wrong), and classified against the
literature: **KNOWN** / **KNOWN-VARIANT** / **PLAUSIBLY-NOVEL**, conservatively.

Notation from `MODEL.md`. Numbers from `audit_result.json` (SEED=1).

---

## P1 — Deterrence threshold and the undeterrable set

**Claim.** A risk-neutral agent lies on `i` iff `g_i > p_i q_i B_i`. Hence `i` is
deterred iff `p_i ≥ p_i^min := g_i /(q_i B_i)`. The **price of deterrence** is
`π_i = c_i p_i^min = c_i g_i /(q_i B_i)`. Feasibility needs `p_i^min ≤ 1`; claims with
`g_i > q_i B_i` **cannot be deterred at any audit probability**.

**Proof.** By A4, `E[lie_i] = g_i − p_i q_i B_i` and `E[honest_i] = 0`. The agent
lies iff `E[lie_i] > E[honest_i] ⇔ g_i > p_i q_i B_i`. Solving for the minimum
deterring probability gives `p_i^min = g_i/(q_i B_i)`; multiplying by the audit cost
gives the budget it consumes, `π_i`. Since `p_i ≤ 1`, deterrence is achievable only
if `g_i/(q_i B_i) ≤ 1 ⇔ g_i ≤ q_i B_i`. ∎

**Numerical check.** For 200 tempted deterrable claims, best-response flips exactly
at `p_i^min ± 1e-4` (`threshold_flips_exact = True`). Every claim with `g_i > q_i B_i`
has `p_i^min > 1` (`undeterrable_all_pmin_gt1 = True`); undeterrable fraction 0.095 at
`B_max = 3`. ✓

**Prior art. KNOWN.** Becker (1968), *Crime and Punishment*: offend iff gain exceeds
expected penalty `p·f`. Townsend (1979) costly-state-verification; Border & Sobel
(1987); Mookherjee & Png (1989). The undeterrable set is the standard "judgment-proof"
/ limited-liability observation (e.g. Innes 1990). No novelty claimed.

---

## P2 — The optimal policy is a knapsack, and the stakes cancel

**Claim.** With budget `C`, the loss-minimising policy deters the set `S` maximising
`Σ_{i∈S} v_i` s.t. `Σ_{i∈S} π_i ≤ C`. The fractional relaxation is solved greedily by
value density `ρ_i = v_i/π_i = v_i q_i B_i /(c_i g_i)`. **The invariant kernel is the
consequence-to-gain ratio `v_i/g_i`.** It has two branches:

- **G1 (`g_i = β v_i`):** `v_i/g_i = 1/β` is constant, so `ρ_i = qB/(cβ)` is constant —
  stake carries **no** ranking information; at the optimum, selecting *which* claims to
  deter by consequence yields no gain over any other selection.
- **G2 (`g_i = min(β v_i, g_max)`), saturation threshold `v* = g_max/β`:** below `v*`,
  `g_i = β v_i` so `ρ_i = qB/(cβ)` is constant (same as G1); **above `v*`, `g_i = g_max`
  so `ρ_i = v_i qB/(c g_max)` rises *linearly* in `v_i`.** Ranking by `ρ` in the
  saturated tail **is** ranking by consequence — high-stake claims are exactly the right
  target there, because their gain has decoupled from their stake.

Dispersion in `ρ_i` (which makes targeting valuable) comes from, in measured rank
order: **gain saturation (G2) > bond heterogeneity > competence (`q`) > cost.**

**Proof.** A deterred claim contributes `0` to ε; an undeterred one contributes
`(1−p_i q_i)v_i`, maximised at `v_i` when `p_i=0`. Fully deterring `i` costs `π_i`
(P1) and removes `v_i` from ε; the value-per-dollar is `ρ_i = v_i/π_i`. Partial
auditing of a deterrable claim to `p_i<p_i^min` removes `q_i v_i` per unit `p` at cost
`c_i`, density `q_i v_i/c_i`; the ratio partial/full `= g_i/B_i ≤ q_i ≤ 1` for
deterrable claims, so full deterrence weakly dominates partial auditing — the problem
is a 0/1 knapsack, greedily solved by `ρ_i`. Since `ρ_i = (v_i/g_i)(q_i B_i/c_i)`, the
`v_i/g_i` branches above give: constant under G1; and under G2, for `v_i > v* = g_max/β`,
`ρ_i = v_i q_i B_i/(c_i g_max)` — increasing linearly in `v_i` (continuous at `v*`,
where it equals `qB/(cβ)`). ∎

**The correct content, stated plainly (this is the Part-1 CORRECTION).** The invariant
is: **target the consequence-to-gain ratio `v/g`, not consequence alone and not
detectability alone.** Under proportional gains that ratio is flat, so stake is
uninformative (the correctly-derived G1 result). Under *saturating* gains — the regime
the dispersion ranking calls dominant — the ratio grows with stake above `v*`, so
**high-stake claims are the right priority precisely there.** My original headline
("consequence is the wrong thing to target") was derived from the G1 branch alone and is
**inverted in the G2 tail.**

**Numerical check.** G1 homogeneous: `ρ`-CV `= 2.6e-16` (exact cancellation), value
deterred **order-indifferent** (high-first 3271.8 vs low-first 3267.6, 0.13%). Under G2:
`ρ`~`v` correlation *above* `v*` `= 1.000` (exactly linear, as derived) and `ρ`-CV
*below* `v*` `= 1.5e-16` (flat) — both branches confirmed. Deterring by consequence-order
under G2 captures **the same** value as deterring by `ρ`-order (4078.5 = 4078.5) and far
more than low-first (1840) — so under G2, consequence-ranking *is* optimal ranking; under
G1 all orders tie. Dispersion sources (`ρ`-CV): baseline 0.00, **G2 1.69**, bond 0.90,
**q 0.78**, cost 0.41. Deterministic `topk_stake` is still the **worst** policy in every
cell (uniform-stakes G1: 3319 vs uniform 2385) — the inspection game. ✓

**Reported disagreement (sim contradicts the naive phrasing; derivation wins).** One
might expect "the consequence-weighted *policy* (`p_i ∝ v_i`) approaches optimal under
G2." It does **not**: measured, the `p∝v` policy is **2.04× optimal under G2** versus
**1.16× under G1** — *worse*, not better. Diagnosis: the `p∝v` policy conflates *who to
deter* (correctly stake-ranked in the G2 tail) with *how much to audit*. The optimal
audit intensity is `p_i^min = g_i/(q_i B_i)`, which in the saturated tail is **constant**
(`g_max/(qB)`), not `∝ v_i`; `p∝v` therefore *overspends* the tail. **Prioritise by
consequence-to-gain ratio; meter each claim at its own `p_min`.** The ρ-ranking result
holds; the intensity heuristic does not — reported here rather than reconciled away.

**How much of the mass the G2 branch governs (1c).** Fraction of total *consequence*
sitting above `v*` (where stake becomes informative): **Pareto 0.59, lognormal 0.56,
uniform 0.34**. Under heavy-tailed stakes the saturated branch governs the *majority* of
consequence — this is not a negligible tail; it is where most of the risk lives. Only
under light (uniform) stakes is it a minority.

**Prior art. KNOWN-VARIANT.** Audit-as-knapsack / greedy value-density is standard in
security-game resource allocation (Tambe 2011; Korzhyk, Conitzer & Parr 2010) and in
optimal tax-audit theory. Reinganum & Wilde (1985) and the tax literature already note
audit probability need not rise with reported income. The crisp `v`-cancellation under
proportional gains, stated as "consequence-weighting yields zero gain," is a sharp
special case; conservatively **KNOWN-VARIANT**, with the calibrated dispersion-source
ranking as the empirical contribution.

---

## P3 — Bond-capacity ⇄ targeting substitution

**Claim.** If bonds scale with the gain (`B_i ∝ g_i`), then `p_i^min = g_i/(q_i B_i)`
is constant across claims and **uniform auditing is optimal — targeting is
unnecessary.** Targeting matters exactly when bonds are **capped** at `B_max` for the
set `{i : g_i > q_i B_max p*}` that cannot reach the target audit level. Raising bond
capacity and improving audit targeting are **substitutes**.

**Proof.** If `B_i = g_i/(q_i p*)` then `p_i^min = g_i/(q_i · g_i/(q_i p*)) = p*` for
all `i`; the uniform policy `p_i = p*` deters everything within budget `Σ c_i p* `, and
since all `p_i^min` are equal there is no density dispersion to exploit — uniform is
optimal. The cap binds when `g_i/(q_i p*) > B_max ⇔ g_i > q_i p* B_max`; only for those
claims is `p_i^min > p*`, requiring extra audit and hence targeting. As `B_max → ∞` the
binding set empties and uniform becomes optimal. ∎

**Numerical check.** Sweeping `B_max` (G1, `α_in=0.5`, `r=0.1`):

| `B_max` | ε(uniform) | ε(optimal) | targeting gain | undeterrable |
|---|---|---|---|---|
| 1 | 3814.7 | 2903.0 | 911.7 | 0.499 |
| 3 | 3177.1 | 2134.7 | 1042.3 | 0.095 |
| 10 | 2531.1 | 872.9 | 1658.2 | 0.013 |
| 100 | 567.8 | 52.8 | 515.0 | 0.000 |

ε falls under **both** policies as `B_max` rises (bond capacity substitutes for
audit); the *marginal* value of targeting is largest at intermediate bond capacity and
declines at the high end (515 at `B_max=100`, down from the 1658 peak) as the
undeterrable set empties. ✓ (Non-monotone: at tiny `B_max` half the claims are
undeterrable so neither policy can help them; at huge `B_max` uniform already suffices.)

**Practical corollary.** Compare the marginal cost of raising `B_max` (capital the
agent must lock) against the marginal cost of better targeting/routing. In the scarce
regime the two are interchangeable levers on ε.

**Prior art. KNOWN-VARIANT.** The penalty–probability substitution is Becker (1968):
expected penalty `= p·f`, so raising the fine substitutes for raising the audit rate.
Casting the *bond cap* (limited liability) as the precise reason targeting becomes
necessary, and quantifying the substitution against routing, is a variant framing;
**KNOWN-VARIANT**.

---

## P4 — Competence tiers and the routing floor

**Claim.** Out-of-competence claims have `q_i ≈ q_out` (near 0), so `π_i` is huge/∞: no
cheap-audit policy deters them; they require the expensive oracle (`q_ex ≈ 1`, cost
`c_ex ≫ c_cheap`). Split budget `C` between a cheap tier (cost `c_cheap`, detection
`q_i`, useful only in-competence) and an expensive tier (cost `c_ex`, detection `q_ex`,
universal). With an imperfect router (sensitivity `s`, specificity `t`), misrouting is
**asymmetric**: routing a truly-out claim to cheap (rate `1−t`) is *dangerous* (it
leaks); routing a truly-in claim to expensive (rate `1−s`) is merely *wasteful*.

**Proof.** For an in-competence claim, cheap is preferred iff `c_cheap/q_in < c_ex/q_ex`
(cost per unit detection); for out-of-competence, `q_out ≈ 0` makes `π^cheap → ∞`, so
only the expensive tier can deter. The optimum audits in-competence claims cheaply and
out-of-competence claims expensively, greedily by `ρ` within the realised routing. A
misrouted out→cheap claim receives detection `q_out ≈ 0` and is undeterred → contributes
`v_i` (dangerous); a misrouted in→expensive claim is still deterred, only at cost `c_ex`
instead of `c_cheap` (wasteful). ∎

**Numerical check (scarce budget `r=0.05`, `α_in=0.6`, `c_ex=20`).** Single-tier
all-expensive: ε = 3833. Two-tier by routing accuracy `s=t`:

| routing acc | ε(two-tier) | beats single? | dangerous frac |
|---|---|---|---|
| 0.5 | 2737 | yes | 0.197 |
| 0.7 | 2369 | yes | 0.117 |
| 0.9 | 2004 | yes | 0.040 |
| 1.0 | 1860 | yes | 0.000 |

**Two-tier beats single-tier across the entire routing-accuracy sweep down to 0.5**
in the scarce regime, because misrouting an out-claim to cheap only wastes a cheap
audit while the budget freed on in-claims dominates. **Regime caveat:** at *abundant*
budget with a *tight* bond cap, single-tier all-expensive can win (higher `q_ex`
deters bigger bond-capped whales); with `B_max=5` two-tier still wins at `r=0.5`. The
two-tier advantage is fundamentally a **budget-scarcity** effect. ✓

**The weakest link (A8).** This entire tier gain assumes the router can classify
competence. If classifying "is this claim within the checker's competence" is *itself*
out-of-competence, the competence bound re-enters one layer up — the R5 failure mode.
The design must treat routing accuracy as an empirical, monitored quantity, not an
assumption.

**Prior art. PLAUSIBLY-NOVEL (the tier-routing corollary).** Tiered/hierarchical
verification exists (TrueBit's interactive verification game; optimistic rollups'
fraud-proof escalation; Kleros' appeal tiers). What is not standard is treating the
verifier's **competence-bounded `q` as a first-class, *measured* parameter** and
deriving the routing-accuracy floor from it. The framework is known; the
competence-calibrated two-tier design with an asymmetric-misrouting analysis is the
contribution. Conservatively: framework KNOWN, calibrated corollary PLAUSIBLY-NOVEL.

---

## P5 — The ε(r) bounded-error contract (the deliverable)

**Claim.** Expected undetected consequential loss `ε(r)` as a function of audit rate
`r` is piecewise-decreasing and **floored** by the undeterrable + out-of-competence
residual: beyond a modest `r`, additional cheap auditing buys nothing.

**Derivation (homogeneous-within-tier closed form).** Let fraction `α` of claims be
in-competence with identical `(v,g,q_in,B,c)`, the rest out with `q_out`. Deterring one
in-competence claim costs `π_in = c g/(q_in B)`; the number affordable at rate `r` is
`C/π_in = r N q_in B/g`, i.e. a fraction `min(1, r q_in B/(αg))` of in-competence
claims. Out-of-competence claims have `π_out = c g/(q_out B)`; when `q_out ≈ 0` they are
undeterrable at the cheap tier. Hence
```
ε(r) ≈ [α − deterred_in(r)]·N·(1−p q_in)·v   +   (1−α)·N·v_out         (cheap-only)
                              └ vanishes once budget covers in-competence ┘
```
The first term drives to its floor at `r* = αg/(q_in B)`; the second term — the
out-of-competence mass — is a **hard floor** no cheap audit rate removes. Only the
expensive tier (P4) lowers it.

**Numerical check (calibrated, `q_in=0.818`, `q_out=0.111`, pareto stakes, `α=0.6`,
`B_max=5`, temptation = base rate 0.128; `e0 = 530.5`):**

| `r` | ε(optimal) | as frac of `e0` | ε(uniform) |
|---|---|---|---|
| 0.00 | 530.5 | 1.000 | 530.5 |
| 0.05 | 116.1 | **0.219** | 427.5 |
| 0.10 | 116.1 | 0.219 | 357.7 |
| 0.30 | 116.1 | 0.219 | 238.0 |
| 0.60 | 116.1 | 0.219 | 141.7 |

**The optimal ε plateaus at 0.219·e0 for every `r ≥ 0.05` and never improves** — the
residual 116.1 is entirely out-of-competence + bond-capped-undeterrable consequence
that a cheap checker cannot touch at any audit rate. This is the bounded-error
contract's **floor**, and it is set by the competence bound, not the budget. Uniform
keeps spending to chase the same claims and never reaches the optimal's floor. The
Monte-Carlo cross-check reproduces the expectation to 0.02% (16.131 vs 16.128). ✓

**This is the number Gyza needs:** at any audit rate above ~5%, a cheap-checker
mechanism guarantees undetected consequential error `≤ 0.22 · (unaudited baseline)` —
and that 0.22 is the out-of-competence share, which *only* ground-truth resolution
removes.

**Prior art. KNOWN-VARIANT.** Audit-budget vs residual-fraud curves are standard in the
tax-compliance and security-games literature. The specific calibrated curve and the
identification of the floor with the *measured* out-of-competence mass is the
empirical contribution.

---

## P6 — Collusion-proofness under commitment (and where it breaks)

**Claim.** When the auditor commits to a randomised policy and audits are independent
(A2, A3), each agent's deterrence constraint `p_i ≥ g_i/(q_i B_i)` depends only on its
*own* `(p_i, q_i, B_i, g_i)`. The coalition's payoff is additively separable, so a
coordinating coalition gains nothing over independent agents. It breaks under
(a) adaptive auditing, (b) budget-coupling, (c) correlated detection.

**Proof.** The coalition maximises `Σ_i L_i (g_i − p_i q_i B_i)` over lie-vectors
`L ∈ {0,1}^N`. Since `p_i` is committed and audits independent (A2, A3), the summand
for `i` depends only on `L_i`, so the joint maximiser sets `L_i = 1 ⇔ g_i > p_i q_i B_i`
— exactly each agent's independent best-response. No cross-claim term exists to
exploit. ∎

**Where it breaks — case (a), adaptive auditor.** If the committed policy is a
*function of the observed claim profile* (e.g. `p_i ∝ observed stake share`), a
coalition floods `M` decoy claims to dilute `p` on a target lie. With budget fixed to
the real `N`, flooding spreads the same budget over `N+M` claims, cutting the target's
`p` by ≈ `N/(N+M)`. **Design rule: commit to a profile-independent randomisation
(fixed per-claim `p` or fixed marginals), never one the realised profile can move.**
Case (b) budget-coupling creates the same congestion channel within a period; case (c)
correlated detection *helps* the auditor and should be modelled separately.

**Numerical check.** Brute-forcing a 14-member coalition's joint best lie-vector
(`2^14` options) yields exactly the independent best-response
(`coalition_joint_equals_independent = True`). The adaptive-auditor attack: flooding
`3N` comparable-stake decoys dilutes the target's audit probability by **4.65×**,
confirming adaptive/profile-dependent policies are exploitable. ✓

**Prior art. KNOWN.** The value of commitment in Stackelberg security games is
foundational (von Stengel & Zamir 2010; Korzhyk et al. 2010; Conitzer & Sandholm 2006).
Separability under independent commitment and the manipulability of adaptive policies
are known. No novelty claimed.

---

## P7 — Participation, and why the likelihood ratio is fundamental

**Claim.** Honest agents are falsely convicted at rate `f_i` and lose `B_i`. Let `w_i`
be the honest agent's legitimate surplus. Then a mechanism that both **deters lying**
and **retains honest agents** exists iff
```
g_i/(q_i B_i)  ≤  p_i  ≤  w_i/(f_i B_i),
```
which is non-empty iff `q_i / f_i ≥ g_i / w_i`. **Feasibility depends on the likelihood
ratio `LR_i = q_i/f_i` — not on TPR, FPR, or Youden's J individually.**

**Proof.** Deterrence (P1) needs `p_i ≥ g_i/(q_i B_i)`. An honest agent participates
iff `w_i − p_i f_i B_i ≥ 0 ⇔ p_i ≤ w_i/(f_i B_i)`. A feasible `p_i` in the intersection
exists iff `g_i/(q_i B_i) ≤ w_i/(f_i B_i)`; multiplying through by `B_i > 0` gives
`g_i/q_i ≤ w_i/f_i ⇔ q_i/f_i ≥ g_i/w_i`. The bond `B_i` cancels — feasibility is
governed entirely by `LR_i = q_i/f_i` relative to the gain-to-honest-profit ratio. ∎

**Numerical check.** With the measured operating points:

- **In-competence:** `LR_in = 0.818/0.041 = 19.95` (reported 19.8). Feasible for any
  `g/w ≤ 19.95` — a lie may be worth up to ~20× honest profit and the mechanism still
  works. **Inside the frontier.**
- **Out-of-competence:** `LR_out = 0.556/0.444 = 1.25`. Feasible only if `g/w ≤ 1.25` —
  the lie must gain barely more than honest work. **On the edge; effectively
  infeasible** for any real temptation.
- **Same-J, different-LR:** checker A (TPR .6, FPR .1: J=0.5, LR=6) is feasible at
  `g/w=5`; checker B (TPR .9, FPR .4: J=0.5, LR=2.25) is **not** — identical Youden J,
  opposite feasibility. This is the decisive demonstration that **J/TPR/FPR are not the
  right sufficient statistic; the likelihood ratio is.** ✓

**Prior art. KNOWN-VARIANT.** That the likelihood ratio is the sufficient statistic of
a binary test is Neyman–Pearson; its role in incentive feasibility appears in the
statistical-decision and mechanism-design literatures. The empirically-grounded
feasibility frontier — placing the *measured* in/out-competence operating points
against the `LR ≥ g/w` boundary and showing the out-of-competence regime falls outside
it — is the contribution. Conservatively **KNOWN-VARIANT with novel calibration.**

---

## Summary of prior-art honesty

| Prop | Classification |
|---|---|
| P1 deterrence threshold | KNOWN (Becker, Townsend) |
| P2 knapsack + `v`-cancellation | KNOWN-VARIANT (security games / tax audit) |
| P3 bond ⇄ targeting substitution | KNOWN-VARIANT (Becker penalty–probability) |
| P4 competence-tier routing | framework KNOWN; **calibrated corollary PLAUSIBLY-NOVEL** |
| P5 ε(r) floor | KNOWN-VARIANT; **floor = measured out-of-competence mass is the contribution** |
| P6 commitment collusion-proofness | KNOWN (Stackelberg security games) |
| P7 LR feasibility frontier | KNOWN-VARIANT; **empirical frontier is the contribution** |

**Honest overall.** The framework is not new — costly state verification (Townsend),
Becker deterrence, and Stackelberg security games supply P1–P3 and P6. The genuine
contribution is (i) treating the **competence-bounded, empirically-measured `q`** as a
first-class parameter, (ii) the **two-tier routing design with its accuracy floor**
(P4), (iii) the **ε(r) contract whose floor is the measured out-of-competence mass**
(P5), and (iv) the **LR (not J) feasibility frontier with the measured operating
points** (P7). "This framework is known; our contribution is the empirical calibration
and the tier-routing corollary" is the honest statement.
