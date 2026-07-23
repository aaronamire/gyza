# Route 6 — the model

Optimal audit-mechanism design when the verifier is **competence-bounded**: its
detection probability depends on whether the claim falls within its competence.
This is an analytic route — zero model calls. It takes the competence bound (the
general negative result of Routes 2–5 and Phases 6B/7) as an *input* and asks the
Bitcoin/CSV question instead of the detection question: not "can we detect error
cheaply?" but "given a verifier that detects only within its competence, what audit
policy minimises undetected consequential error, and when does targeting beat
uniform random auditing?"

**NOT a rescue of any prior route.** All prior decisions stand (Route 2
UNFALSIFIABLE-IN-PRACTICE, Channel A/B, 6B ASYMMETRY-WEAK, 7 WITNESS-DEAD, R5-DEAD).
This route changes the *question*, not the verdict on detection.

## Primitives

`N` claims, indexed `i`. The auditor commits publicly to a randomised policy; a
risk-neutral adversary best-responds (Stackelberg). For each claim `i`:

- `v_i ≥ 0` — **consequence**: the principal's loss if the claim is wrong *and* the
  error goes undetected.
- `g_i ≥ 0` — the agent's **gain** from submitting a false claim.
- `B_i ≤ B_max` — the **bond** posted (capital-constrained: the cap is load-bearing).
- `p_i ∈ [0,1]` — the **audit probability** the auditor commits to (public).
- `c_i` — **audit cost**; `q_i` — **detection probability** (competence-bounded);
  `f_i` — **false-conviction probability** (the FPR — not optional, see P7).
- Budget `Σ_i c_i p_i ≤ C`; audit rate `r = C / (N c_cheap)`.

**Objective** (auditor minimises expected undetected consequential loss):

```
epsilon  =  Σ_i  [agent i lies] · (1 − p_i q_i) · v_i
```

## Numbered assumptions

1. **Risk-neutrality.** Agents and principal maximise expected value. *(A1)*
2. **Commitment / Stackelberg.** The auditor commits to `p` first; it is public
   (no security through obscurity); the adversary best-responds. *(A2)*
3. **Independent audits.** Audit draws are independent across claims; auditing `i`
   does not consume the budget reserved for `j` within a period (relaxed in P6). *(A3)*
4. **Deterrence accounting (Becker/CSV convention).** The expected payoff from lying
   on `i` is `E[lie] = g_i − p_i q_i B_i`; honest baseline `0`. Hence deter iff
   `g_i ≤ p_i q_i B_i`. *This is the conservative form:* if the gain is also clawed
   back on detection, the penalty term becomes `p_i q_i (B_i + g_i)`, which only makes
   deterrence *easier*. Using `B_i` alone is the worst case for the auditor. *(A4)*
5. **Detection is bimodal by competence.** `q_i = q_in` if claim `i` is within the
   cheap checker's competence, else `q_i = q_out`. Calibrated from 6B: in-competence
   `q_in = 0.818`; out-of-competence effective detection is bounded by the actionable
   edge `J_out = TPR_out − FPR_out = 0.111` and swept over `[0, 0.3]` because cell-(b)
   is underpowered (n=36, CI incl 0). *(A5)*
6. **Gain regimes, compared explicitly.** (G1) proportional `g_i = β v_i`;
   (G2) sub-proportional / capped `g_i = min(β v_i, g_max)`. G2 is the realistic
   saturating case. *(A6)*
7. **Detection ⇒ rejection + forfeiture.** A detected false claim is rejected (loss
   averted) and the bond forfeited. *(A7)*
8. **Router precedes audit (P4).** To use two tiers the mechanism must classify a
   claim as in/out of competence *before* auditing it, with sensitivity `s` and
   specificity `t`. This is the design's **weakest link** — the classifier is itself
   an LLM-adjacent judgement and can re-import the competence bound. *(A8)*
9. **Temptation rate.** A fraction of claims would be false if undeterred; calibrated
   to the corrected MATH wrongness base rate `0.128` (swept, and set to `1.0` where
   we want budget to bind). *(A9)*

## Which assumptions are load-bearing (and what breaks if each fails)

| Assumption | Load-bearing? | What breaks if it fails |
|---|---|---|
| A2 commitment | **critical** | Without commitment the auditor cannot deter at all (inspection game has no pure-strategy equilibrium); with an *adaptive* committed policy, coalitions manipulate the profile (P6). |
| A4 deterrence form | moderate | The `(B+g)` variant only strengthens deterrence; our bound is conservative. Risk-aversion (not modelled) would also strengthen it. |
| A5 bimodal `q` | **critical** | The entire two-tier result (P4/P5) rests on `q_out ≪ q_in`. If detection were homogeneous there is one tier and no routing problem — but 6B *measured* the bimodality. |
| A8 router accuracy | **critical & weakest** | If the router is worse than ~50% useful (P4 sweep), or if classifying competence is itself out-of-competence, the two-tier design collapses back to single-tier and the competence bound re-enters through the classifier (the R5 failure mode, one layer up). |
| A3 independence | moderate | Budget-coupling and adaptivity (P6 cases a,b) create exploitable congestion; the design rule is to commit to profile-*independent* randomisation. |
| B_max cap | **critical** | If bonds can scale freely with gain, uniform auditing is optimal and targeting is unnecessary (P3). Targeting only matters because agents are capital-constrained. |
| A9 temptation | reporting-only | Scales ε but not the qualitative results; swept. |

## What this model does NOT capture (stated plainly)

- **Risk-aversion** (would strengthen deterrence — our risk-neutral bound is
  conservative).
- **Reputation and repeated play** (a repeated game deters far more cheaply; this is
  a single-shot bound).
- **Endogenous claim submission** — agents choosing *which* claims to submit, or not
  participating, beyond the P7 participation constraint.
- **Heterogeneous agent capability** — a smarter agent may lie more convincingly,
  lowering `q_i` in a claim-specific way.
- **The cost of running the router itself** (A8) — treated as free; it is not, and it
  is the weakest link.
- **Correlated detection** — one audit revealing several lies (P6 case c); modelled
  as a note, not derived.

All quantities are refereed by `audit_simulator.py`; every proposition in
`PROPOSITIONS.md` carries its numerical check. Calibration source for `q_in, f_in,
q_out, f_out, base rate`: `consistency_defensibility/FINDINGS_CORRECTION.md` (Phase 8,
hand-validated canonicalizer).
