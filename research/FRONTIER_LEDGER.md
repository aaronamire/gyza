# Research-frontier ledger

The map for deciding the next direction. Every epistemic channel for trusting an AI output,
classified **CLOSED** / **MEASURED-BOUNDED** / **ANALYTICALLY-BOUNDED** / **GENUINELY-OPEN**,
with the evidence or the reason it wasn't tested. Its job is to let the next decision be made
with clear eyes — **it does not manufacture optimism.** Where a channel is low-probability,
it says so.

Reference frame: the verification program (`PROGRAM_STATUS.md`) closed the black-box
cheap-verification question. This ledger places that result among all the channels and marks
what remains.

---

## 1. Reality contact — Route 1 — CLOSED (the committed answer)

Run the code against real tests, execute against ground truth, contact the world, or have a
human adjudicate. **Always works; it is the definition of correctness.** It is the fallback the
whole program was trying to *avoid*, not beat.

- **Cost structure:** O(1) model calls but expensive *per claim* — full re-execution, a human,
  or real-world contact. It does not amortize into cheap verification; that is precisely why
  optimistic verification exists. Route 6 formalizes when you must fall back to it: everything
  outside the cheap checker's competence (LR ≈ 1.25, un-priceable) is routed here.
- **Status:** CLOSED. It is the deployable substrate (Gyza's provenance receipt binds *which*
  answer was produced; reality contact adjudicates *whether* it was right when the stakes
  warrant the cost).

## 2. Correlated observers / agreement — Routes 2–3 — CLOSED

Independent producers agreeing certifies correctness only if their errors are independent.
They are not: agreement measures shared competence. Excess agreement-on-wrong ≈ 0 vs the
conditional-independence null; the informative regime (dense high-cardinality wrong-answer
space) does not occur naturally and could not be induced (GATE B 22/25); method disjointness
does not break a shared attractor (nested escape rates COT 0.955 > DECOMP 0.727 > CODE 0.318).

- **Status:** CLOSED (Route 2 UNFALSIFIABLE-IN-PRACTICE, `c150442`). Not worth revisiting on
  this task distribution.

## 3. Logical structure of the claim — Channels A, B, R5, R8 — MEASURED-BOUNDED

Interrogate the claim's own structure rather than re-solving: self-consistency (A),
defensibility under challenge (B), mechanical CAS checking (R5), native unit tests (R8). All
work **inside** the checker's competence and collapse outside it, because each needs a
competent stage somewhere (a restatement that re-solves, a model that can tell defensible truth
from defensible error, a competent transcriber, a competent test author).

- **Scoped regime where it works:** in-competence claims — 6B cell (a) J = 0.777, LR = 19.8,
  n = 433. This is a *real, deployable* positive: cheap structural checks are trustworthy on
  claims the checker could itself solve.
- **Status:** MEASURED-BOUNDED. The boundary is the checker's competence; the well-powered R8
  cell (b) (n = 127–290) demonstrates the collapse. No further black-box structural mechanism
  is worth testing — six have converged.

## 4. Economics / deterrence — Route 6 — MEASURED-BOUNDED (takes the bound as input)

Do not detect error; *price* it. Deterrence needs `p ≥ g/(qB)`, participation `w ≥ pfB`, jointly
`LR = q/f ≥ g/w`. A bonded market is viable over in-competence claims (LR 19.8) and infeasible
over out-of-competence ones (LR 1.25). The framework is standard (Townsend/Becker/Stackelberg);
the calibrated competence-bounded `q` and the tier-routing floor are the contribution.

- **What it needs from a live deployment before it is more than paper:** the calibrated `q_in`,
  `q_out`, `f`, base rate, and stake/gain distribution are from MBPP/MATH. A real deployment
  must **re-measure `q_in`/`q_out` on Gyza's own claim distribution** and locate its own ε(r)
  plateau (`audit_mechanism/GYZA_DESIGN_RULES.md`). Until then the numbers are illustrative.
- **Status:** MEASURED-BOUNDED (theory closed; deployment calibration is engineering, not a
  research question).

## 5. Producer internals — logits / activations / probes — GENUINELY-OPEN

Read the producer's own internal states — token-logit confidence, activation probes for
"truthfulness"/"knownness", representation-engineering directions — instead of its outputs.
**No phase tested this.**

- **Why it wasn't tested:** it requires **white-box access** (activations, full logits) that the
  API roster used (OpenRouter/Groq chat completions) does not expose. The open-weight models
  *could* be run locally for activation extraction — so it is runnable, just with different
  apparatus.
- **Phase-7 reason to expect it largely fails:** the program's errors are **mid-computation
  slips, not comprehension states the model represents** (median normalized error position 0.60;
  the witness/localization channel was WITNESS-DEAD). A model that makes an off-by-one does not
  obviously *represent* "I am wrong here," so a probe has nothing to read. Probes have shown
  real signal for **deception** (model knows the truth and states falsehood) — which would mirror
  Channel B's B-INSINCERE-ONLY one level deeper — but sincere computational error is the failure
  mode that actually dominates here.
- **Honest prior:** ~50–60% that internal probes detect *deliberate deception* above chance
  (consistent with existing truthfulness-probe literature); **~20–30%** that they detect
  *sincere computational error* — the case the verification program cares about — meaningfully
  better than the black-box cell-(b) bound. Most likely outcome: probes recover the same
  insincere-only boundary, deeper in the stack. Not hopeless, not promising for the hard case.
- **Apparatus required:** local GPU inference of the open-weight roster, activation/logit
  extraction, a labeled correct/incorrect activation set, probe training with the same
  preregistration + item-bootstrap + cell-(a)/(b) discipline. A new program, moderate cost.

## 6. Composition / error-compounding (the depth question) — ANALYTICALLY-BOUNDED (not open)

Does verifying steps of a multi-step chain help? The **common-mode floor** answers it without
experiment: redundancy cannot push chain error below the common-mode rate `c` shared across
replicas, and Route 3's **nested failure sets** (CODE's errors ⊂ DECOMP's ⊂ COT's) imply
`c ≈ the best replica's own error rate`. So a chain of competence-bounded verifiers has an error
floor at the competence bound itself; composition does not escape it. This predicts a **negative
result analytically**, so empirical testing is **low-value**.

- **Status:** ANALYTICALLY-BOUNDED. Marked explicitly *not open* — the analysis already answers
  it, and an experiment would spend credits to confirm a derivation. Do not test.

## 7. Objective robustness under aggregation (the "positive" question) — GENUINELY-OPEN, out of scope

Whether a *collective* of bounded agents can be organized so that the aggregate objective is
more robust than any member — the constructive counterpart to the negative verification result.
This is the open, valuable, hard direction, but it is a **years-scale research agenda**, not a
cheap experiment, and it needs apparatus (multi-agent training/eval infrastructure, an objective
robustness metric) the current setup does not have.

- **Honest prior:** genuinely unknown; not estimable from this program's data.
- **Status:** GENUINELY-OPEN but **out-of-scope for the current apparatus.** Flagged so it is not
  confused with a next-experiment; it is a next-*program* decision for the user.

---

## Summary for the next decision

| Channel | Class | One-line prior / note |
|---|---|---|
| Reality contact (R1) | CLOSED | The costly fallback; the deployable substrate. |
| Agreement (R2–3) | CLOSED | Shared competence, not independence. Don't revisit. |
| Claim structure (A/B/R5/R8) | MEASURED-BOUNDED | Works in-competence (LR 19.8), collapses out. Six mechanisms converged. |
| Economics (R6) | MEASURED-BOUNDED | Theory done; needs live-deployment `q` calibration. |
| **Producer internals** | **GENUINELY-OPEN** | ~20–30% for sincere error, ~50–60% for deception; needs white-box + GPU. |
| Composition / depth | ANALYTICALLY-BOUNDED | Common-mode floor ⇒ negative; low-value to test. |
| **Objective robustness** | **GENUINELY-OPEN** | Years-scale agenda; out-of-scope for this apparatus. |

**Two channels are genuinely open. Both need new apparatus, and the cheaper one (producer
internals) has a low prior for the case that matters (sincere error). Neither is a continuation
of the verification program; each is a decision to start a new one.** This ledger recommends
nothing — it lets the user choose with the priors stated honestly.


---

## Post-closure routes (appended 2026-08-18)

The program was declared terminal at twelve routes. Five more have run since,
each preregistered before any code, each with its hash re-verified after the
runs. **This section exists because a reader of this file would otherwise
believe the program ended where it did not.**

| route | verdict |
|---|---|
| **escrow** | `ESCROW-CONVERTS-LOSS-TO-FORGONE-GAIN` — unpaid work → 0, but the same 80 credits reappear as work never commissioned. Also `RESERVATION-DEAD-ABOVE-M=3` |
| **R-M1 margin** | `MARGIN-GROWS-WITH-M-AND-APPROACHES-THE-CEILING` — δ\* rises 0.130 → 0.295 (M=8→512); margin is a STEP, not a dial |
| **A2 defector** | `COMPLIANCE-ASSUMPTION-NOT-SECURITY-PROPERTY` — one defector breaks the bound at every flat scale, via the COMMONS |
| **R-H1 hierarchy** | `HIERARCHY-HELPS-DECISIVELY` — depth 2–3 defeats at ε≤2 with NO margin; max fan-in 511 → 7 |
| **R-B blast radius** | `BLAST-RADIUS-IS-ONE-CLUSTER` — ~1.6 defectors per cluster; hoarding stops breaching at depth 3 |
| **R-D disperse** | `DISPERSAL-IS-SELF-DEFEATING` — the smarter routing never breaches at any k; a ratio is scale-invariant so an attacker must maximise ASYMMETRY, not damage |
| **R-C churn** | `REACH-BREAKS-DAMAGE-DOES-NOT` — churn destroys compartmentalisation of reach (1 -> 41 pools) and the horizon still does not return; the claim policy is a threat-dependent safety parameter |
| **R-N horizon** | `COMPOSABILITY-IS-NOT-SUFFICIENT` — flat has a finite staleness horizon (eps\* = 8); the tree's margin SATURATES at 68.68% of ceiling, identical at eps = 32, 64, 128 |

**Corrections to previously published findings are indexed in
`research/CORRECTIONS.md` (21 entries).** Two closed forms and one scan have
failed; do not cite a number from any document without recomputing it.

**Open, named by the work itself:** churn (clusters are fixed everywhere above);
a defector that GAMES a check rather than ignoring it; colluding defectors
concentrated in one cluster; and the amortization lever `A`, still untouched and
still the binding term in `N ≤ H·A/[(1−p)(1−c)]`.

## H3's level — CLOSED AS A MEASUREMENT, OPEN AS A DESIGN CHOICE (2026-08-20)

`research/h3_level/` (R-H3L, preregistered `c5a3ab6`) answers the question
`PROGRAM_STATUS` named as the real-system arm's first, and the answer relocates
it rather than settling it.

**What is closed.** The attainable range was measured. Cumulative MESH_EXIT
*count* cannot carry a level at all: it rises by exactly 1.000 per action, so
the benign and exfiltrating nodes exhaust it at the same rate. Cumulative
*bytes* can, but the separating condition is `b_adv/b_benign > N/K`, so the
bound weakens linearly as the demanded operating lifetime grows.

**What is open, and it is not a measurement.** A cumulative quantity over an
immutable origin buys bounded total harm and unbounded lifetime but never a
bound that binds; an agent-advanced origin buys the other two and is artifact
#13; a time-windowed origin bounds the rate and so permits unbounded total over
unbounded time. **Choosing among the three is a product decision** — it fixes
what Gyza's containment claim *means*, not how strong it is.

**The one piece of that which is codeable now** and is currently a comment
rather than a mechanism: if a windowed origin is ever adopted, the window origin
must be a function of **wall-clock time only, never of agent-controlled state**.
That is precisely what distinguishes it from artifact #13's moving checkpoint,
and an unenforced invariant is an assumption. No such check exists today because
no windowed origin exists today; it must land in the same commit as the first
one that does.
