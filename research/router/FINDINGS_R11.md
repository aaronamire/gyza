# Findings — Route 11: the router

Write-up per `PREREGISTRATION_R11.md` (`ddd03c6`) and Amendment 1 (`c000aa6`), both
committed before any prediction call. 3080 calls, $0.1298, 100% parse rate, 0 API
errors. Part A's corrected re-analysis of R10 is in `R10_CORRECTIONS.md`; the
cross-route synthesis is in `research/ARCHITECTURAL_PRINCIPLE.md`. All prior decisions
stand.

---

## DECISION: **ROUTER-DEAD**

> **DIFFICULTY-BASED ROUTING FAILS EVEN WITH ORACLE DIFFICULTY.** Across the 6
> adequately-powered cells whose predictor reaches **AUROC ≥ 0.85** — including one at
> **AUROC = 1.000, a literal difficulty oracle** — the **maximum routing economy at
> recall 0.95 is 0.320**, against a preregistered deployability bar of **0.40**. No
> predictor of any kind, in any configuration, clears the bar.

Competence-classification is itself competence-bounded. The bound re-enters through the
router exactly as Route 6 feared, and step 3 of the containment architecture must be
replaced by a **static/structural** rule — route by claim TYPE, not by predicted
difficulty.

The verdict does not rest on weak predictors. It rests on the fact that **a
near-perfect difficulty predictor still cannot buy a conservative operating point.**
Accuracy was never the binding constraint.

| decision clause | fires? |
|---|---|
| ROUTER-VIABLE — paired Δ > 0, CI excluding 0, ≥ 2 models | **no** — 0 of 10 models have a positive Δ |
| ROUTER-REDUNDANT — economy ≥ 0.40 with Δ CI including 0 | **no** — economy never reaches 0.40 |
| ROUTER-MIRAGE — works in EASY only | **shape present**, but the one cell is INCONCLUSIVE (below) |
| **ROUTER-DEAD** — economy < 0.40 at recall 0.95 in every configuration | **YES** |

The second DEAD disjunct also holds: 3 of 4 MATH Δ CIs include 0, and one confidence
distribution (phi-4 / MBPP) is DEGENERATE.

**Prior was 20% DEAD.** This is the least likely outcome I named, arrived at through
the clause I expected least to fire.

---

## 1. The paired delta against the population null — scoped to MATH

**MATH is the load-bearing arena and the delta claim is scoped to it.** MBPP's null is
near-ceiling for a structural reason given in §2, which makes its deltas uninterpretable
as self-knowledge measurements.

| MATH model | self AUROC | null AUROC | **paired Δ** | **95% CI** |
|---|---|---|---|---|
| google/gemma-2-27b-it | 0.726 | 0.760 | **−0.035** | [−0.168, +0.094] |
| meta-llama/llama-3.1-70b-instruct | 0.666 | 0.739 | **−0.072** | [−0.208, +0.069] |
| microsoft/phi-4 | 0.767 | 0.803 | **−0.036** | [−0.143, +0.069] |
| mistralai/mistral-small-3.2-24b-instruct | 0.546 | 0.700 | **−0.154** | [−0.299, −0.008] |

**On MATH, self-assessment is at or below a predictor that uses zero self-knowledge.**
Three CIs include 0 — no detectable self-knowledge; one excludes 0 on the **negative**
side — measurably worse than knowing what is hard in general. Not one model beats the
null.

MBPP corroborates in direction (Δ = −0.239 to −0.479, all six CIs excluding 0,
all negative) but **its magnitudes are not a measurement of self-knowledge** and are not
claimed as one.

**Cap caveat, carried explicitly into the MATH rows.** A no-`\boxed` completion is
labelled a failure (Amendment 1), and is partly an artifact of the cached run's token
cap. **The MATH absolute AUROCs are therefore cap-dependent.** The **paired delta is
not**: the null is computed from the same labels for every model, so the cap moves both
AUROCs together. This is why the delta is the headline and the absolutes are secondary.

---

## 2. Why MBPP's null is near-ceiling — diagnosed before reporting

MBPP null AUROC reached **1.000** (mistral-small-24b) and 0.907–0.986 elsewhere. Per
the standing rule, an at-or-near-1.0 number is a suspected artifact until diagnosed.

**It is real, not leakage.** MBPP is **76% unanimous** across the six models: 24 of 50
problems solved by *none*, 14 by *all six*. With outcomes that correlated, the other
five models nearly determine the sixth. For the AUROC = 1.000 cell the separation is
exact — solved ⇒ pop_difficulty ∈ {0.8, 1.0}; failed ⇒ ∈ {0.0 … 0.6}.

Leave-one-out is pinned by test, including an invariance check that flipping the
model's own cached label does not move the null.

This is the correlated-failure program's shared-competence finding reappearing in a new
place: **MBPP at this capability tier is nearly a binary trivial/impossible split.**
MATH is 42.5% unanimous, which is why MATH carries the delta claim.

---

## 3. Routing economy — the deployable metric

Route CHEAP iff confidence ≥ t. Economy = 1 − escalation rate, at the smallest
escalation achieving recall ≥ 0.95 on failures.

| predictor | MATH | MBPP |
|---|---|---|
| **self** | 0.026 – **0.165** | 0.020 – **0.100** |
| **null (population difficulty)** | 0.000 – 0.291 | **0.320** |
| **cross-model** | 0.013 – **0.221** | 0.000 – 0.120 |

**Nothing reaches 0.40.** At recall 0.95 the best self-router still escalates 83.5% of
all claims; the worst escalates 98%.

### The AUROC ≥ 0.85 table — the headline in full

| kind | task | cell | AUROC | economy @ r ≥ 0.95 | powered? |
|---|---|---|---|---|---|
| null | mbpp | mistral-small-24b-2501 | **1.000** | **0.320** | yes |
| null | mbpp | mistral-small-3.2-24b | 0.986 | 0.320 | yes |
| null | mbpp | gemma-3-27b-it | 0.965 | 0.320 | yes |
| null | mbpp | gemma-2-27b-it | 0.955 | 0.320 | yes |
| null | mbpp | llama-3.1-70b | 0.943 | 0.320 | yes |
| null | mbpp | phi-4 | 0.907 | 0.320 | yes |
| *(9 further cells ≥ 0.85)* | | *all EASY/MID strata* | 0.857–1.000 | 0.000–0.889 | **UNDERPOWERED** |

**Six adequately-powered cells at AUROC ≥ 0.85; every one yields exactly 0.320.** A
difficulty oracle at AUROC 1.000 buys the same economy as one at 0.907. **Economy is
not a function of predictor accuracy in this regime** — which is precisely why "get a
better router" is not the fix.

### Mechanism — and a preregistration defect, disclosed

Two forces, one of them my error.

**(a) Compressed confidence.** Models emit only **5–11 distinct values**. A predictor
with a handful of levels cannot place a threshold at a conservative operating point;
demanding recall 0.95 collapses it to "escalate almost everything."

**(b) The bar was partly infeasible — third preregistration defect.** A perfect router
must escalate at least `recall × base_failure_rate` of all claims, so
`economy ≤ 1 − r·f`. I fixed the 0.40 bar without checking that ceiling per arena:

| arena | base failure | perfect-router ceiling | 0.40 bar feasible? |
|---|---|---|---|
| MATH | 0.304 – 0.494 | **0.531 – 0.711** | yes, with headroom |
| MBPP | 0.600 – 0.680 | **0.354 – 0.430** | **NO on 2 of 6 cells** |

**So MBPP cannot establish DEAD on the economy clause** — on two cells the bar exceeds
what any router could achieve. **MATH earns the verdict**: a perfect router there could
reach 0.531–0.711, and the measured routers reach **0.026–0.165**. That is a genuine
router failure with a factor of 4–20 of unused headroom, not a bar artifact.

Disclosed, not repaired. It is the third defect of this kind in two routes (R10's θ\*
rule and TUNABLE clause were the first two), and the pattern is worth naming: **a
threshold fixed in a preregistration should be checked against its own feasibility
ceiling before the run, not after.**

---

## 4. EASY / HARD — the recursive question

**MATH, on the preregistered `difficulty` field:**

| model | stratum | n | +/− | self | null | Δ | econ self | econ null | ceiling |
|---|---|---|---|---|---|---|---|---|---|
| gemma-2-27b | EASY | 39 | 30/9 | 0.668 | 0.796 | −0.128 | 0.231 | 0.000 | 0.781 |
| gemma-2-27b | **HARD** | 37 | 13/24 | 0.667 | 0.598 | +0.069 | **0.054** | 0.000 | 0.384 |
| llama-3.1-70b | **HARD** | 38 | 19/19 | 0.632 | 0.733 | −0.101 | **0.000** | 0.000 | 0.525 |
| phi-4 | EASY | 39 | 36/3 | 0.963 | 0.949 | +0.014 | **0.718** | 0.821 | 0.927 |
| phi-4 | **HARD** | 40 | 19/21 | 0.670 | 0.650 | +0.020 | **0.025** | 0.075 | 0.501 |
| mistral-3.2-24b | **HARD** | 40 | 14/26 | 0.552 | 0.621 | −0.069 | **0.075** | 0.000 | 0.383 |

**In the HARD stratum — where routing is the entire point — economy is 0.000 to 0.075.**
Every HARD Δ CI includes 0. Routing works worst exactly where it would have to work.

**The one apparent exception is the MIRAGE signature and is INCONCLUSIVE.** phi-4/EASY
reaches economy 0.718 — but that cell is 36 correct of 39, i.e. the model succeeds
anyway and routing buys nothing; it has **3 negatives against a preregistered floor of
8** and is labelled UNDERPOWERED; and it is **a single model in a single stratum**,
which the preregistration says renders a cell INCONCLUSIVE. It is reported, and it does
not move the decision.

**MBPP tertiles are uninformative, as preregistered.** Splitting on `pop_difficulty`
produced strata with no outcome variance at all — HARD has 0–1 positives of 16, EASY
has 15–18 of 18. The range-restriction confound I disclosed before data appeared in its
extreme form. MBPP strata establish nothing and are not used.

---

## 5. Cross-model routing — the deployed configuration

Self-assessment is gameable: a bonded agent claiming competence on everything is
optimal. So the configuration that matters is a **different** model predicting the
claimant's failure. 42 ordered pairs, 2460 calls.

- **Cross-model AUROC:** 0.516–0.815 (MATH), 0.507–0.778 (MBPP). Best anywhere:
  **0.815**, gemma-2 → mistral-3.2 on MATH.
- **Cross-model economy:** 0.013–0.221 (MATH), 0.000–0.120 (MBPP). **Best anywhere
  0.221 — still far below 0.40.**
- **Cross beats self for 6 of 10 claimants** on the best-pair metric, and the mean
  cross-pair is *worse* than self for 7 of 10. Neither direction reaches deployability.
- **Cross does NOT recover the degenerate claimant.** phi-4's MBPP self-assessment is
  DEGENERATE (46 of 50 predictions on two values; self economy 0.100). Predicted by the
  other five: AUROC 0.548–0.739, economy **0.000–0.100, mean 0.048**. My point
  prediction — *cross ≥ self for models with degenerate self-assessment* — **is wrong**.

**Which results depend on claimant honesty:** the self arm (§1, §3, §4) assumes the
claimant reports its confidence sincerely, and is therefore an **upper bound** on what a
strategic agent would provide. The **cross arm depends on no such assumption** — and it
is the arm that fails hardest. That ordering matters: the honest configuration is the
optimistic one, and it still fails.

---

## 6. Token cost — the prediction really was cheap

| | |
|---|---|
| mean prediction completion tokens | **3.34** (138 prompt) |
| mean cached MATH solution (est., chars ÷ 4) | **~367** |
| **ratio** | **110× cheaper** |
| MBPP solution tokens | **NOT MEASURABLE** — program text uncached (R8 GATE 0b); generation cap 400 is an upper bound |

GATE 0d is satisfied on its own terms: capped at 50 tokens with no chain-of-thought
permitted, the prediction cost two orders of magnitude less than solving. **The failure
is not cost. The signal is not there.**

The calibration gap says why. On MBPP, mean confidence is 70.1–85.6 against base rates
of 0.320–0.400 — **overconfidence of +0.38 to +0.48**. MATH is far better calibrated
(−0.12 to +0.20), consistent with MATH being the more informative arena.

---

## 7. Point predictions, scored

| prediction | outcome |
|---|---|
| confidence right-skewed and compressed | ✓ 5–11 distinct values, overconfident |
| self AUROC 0.60–0.75 | ✓ mostly (0.507–0.767) |
| pop_difficulty AUROC 0.65–0.80 | ✓ MATH (0.700–0.803); ✗ MBPP overshot to 0.907–1.000 |
| **paired Δ small and possibly negative; null hard to beat** | **✓ negative in 10 of 10** |
| routing economy 0.3–0.6 at recall 0.95 | ✗ **badly wrong** — 0.020–0.320 |
| HARD weaker than EASY | ✓ decisively |
| cross ≥ self for degenerate models | ✗ no recovery for phi-4 |

The one I got most wrong is the one that decided the route: **I predicted the economy
would be adequate and driven by difficulty rather than self-knowledge. Difficulty
drives it, and it is still not adequate.**

---

## 8. What this cannot establish

- Two task families (MBPP code, MATH), **mid-tier open-weight models** (pass 0.32–0.40),
  numeric/collection answers, English, single seed, temperature 0.
- The **self** arm predicts a model's *own* competence. The deployed configuration is
  the **cross** arm, which is the smaller and weaker evidence base here — 42 pairs, one
  prompt template, no pair-level tuning.
- **MBPP establishes nothing about the economy clause** (bar above ceiling on 2 of 6
  cells) and nothing about strata (degenerate tertiles). It corroborates the delta's
  direction only.
- **A negative result about one prompt.** The templates were frozen before data and not
  tuned; a better elicitation might do better. What is established is that the
  *cheap, no-CoT, single-integer* form — the only form with an economy to defend — does
  not work. GATE 0d exists precisely because an expensive router is not a router.
- **The population-difficulty null is not free at deployment.** It needs the other
  models' outcomes *on that exact item*. On a recurring claim distribution it is
  precomputable and beats self-assessment; on a genuinely novel claim it costs N−1
  solutions. So "replaceable by a lookup table" holds **only where the table exists** —
  and where it does not, self-assessment's economy of ≤ 0.165 is what remains.
- Nothing here touches **semantic-content harm**. That is the competence bound, closed
  across six families, terminal.

---

## 9. What this establishes

1. **Difficulty-based routing fails even with oracle difficulty.** Six adequately
   powered cells at AUROC ≥ 0.85, one at exactly 1.000, all yielding economy 0.320
   against a 0.40 bar. **Economy is not a function of predictor accuracy in this
   regime.**
2. **On MATH, self-assessment does not beat a zero-self-knowledge null.** Three of four
   deltas have CIs including 0; the fourth is significantly *negative*. Metacognition,
   as elicited here, adds nothing over knowing what is hard in general.
3. **Routing fails hardest where it matters.** HARD-stratum economy is 0.000–0.075. The
   only cell above the bar is an underpowered EASY cell of a single model, where the
   model succeeds 36/39 anyway — the MIRAGE shape.
4. **Cross-model routing does not rescue it**, and does not recover a claimant whose
   self-assessment is degenerate. The gameability-resistant configuration is the weaker
   one.
5. **The failure is not cost.** Prediction ran 110× cheaper than solving. Cheap
   self-assessment is genuinely cheap and genuinely uninformative.
6. **Step 3 of the containment architecture has no mechanism.** Route 6 named the router
   the weakest link and was right. What replaces it must be **structural** — route by
   claim type, provenance, or declared capability class, all of which are properties of
   the claim rather than predictions about a model's mind.

**ROUTER-DEAD is a success.** It closes a step that was carrying an untested assumption
into every downstream design, and it points at the replacement: the architecture's
other three steps (reversibility, conservation, checkpointing) are all **structural
predicates over state**, and Part A showed those compose when the representation is
append-only, partitioned, and derived-not-stored. Step 3 was the only step that asked a
model what it knew. It is the only step that failed.
