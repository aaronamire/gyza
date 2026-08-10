# SR-1 causal — a costed design, and a recommendation **not to run it yet**

**Branch `sr1-design`.** **ZERO CREDITS SPENT.** This is an **ESTIMATE**, not a
measurement, and the experiment was not run. Every cost figure is arithmetic
over **assumptions**; the one measured input is the base rate.

---

## 0. The source, checked

| stated | committed source |
|---|---|
| SR-1 observational returned NOT-EVALUABLE | ✅ `FINDINGS_SR1.md` — **H1 NOT-EVALUABLE, H2 NULL, H3 MISSED** |
| arm short of the floor | ✅ CONSERVING **n = 14 < 15** preregistered minimum |
| CONSERVING was nearly just SHORT | ✅ **11/14 are depth 3** vs REVISITING median 5; *"the same 11/14 are the records already flagged for leakage risk"* |
| "roughly **an order of magnitude** more records" | ❌ **the source says ~1150 records, about 6.4×** (`FINDINGS_SR1.md:167`). Using the source |
| "more observational data does not help" | ❌ **the source says the opposite.** *"Matching on depth is the cheaper fix and should come first."* |

**That last correction is not cosmetic — it is the recommendation.** See §4.

**Also measured and load-bearing:** base substantive-FAIL rate **0.1173**;
REVISITING **0.1273**; CONSERVING **0/14**, diagnosed in the source as
small-sample (`P(0 | null) = 0.174`), carrying no evidence.

---

## 1. THE CONFOUND RESOLUTION — and two of the three offered options are **wrong**

> **In a RANDOMIZED design, depth is not a confounder. It is a MEDIATOR.**

Observationally, task difficulty causes both depth and failure, so depth
confounds. **Once strategy is randomly assigned, nothing confounds
strategy→outcome** — that is what randomization buys. Depth then sits **on the
causal path**: `strategy → depth → outcome`.

| option | verdict |
|---|---|
| **CONTROL depth** | **Wrong twice.** It blocks the mediated path, so it measures only the *direct* effect — and, as the task itself notes, *"a strategy forced to a depth it would not choose is not that strategy"* |
| **STRATIFY / block on depth** | **Wrong, and it is a known error.** Depth is **post-treatment**. Conditioning on it opens a collider path through the unmeasured common cause of depth and outcome — **task difficulty, which certainly exists and which the source already identified as the confound** |
| **MEASURE depth as a MEDIATOR** | ✅ **CORRECT and cheapest in n** — no blocking, no forced depth, full strategy fidelity |

> **And the TOTAL effect is the quantity K-2 actually needs.** K-2 picks a
> strategy; the strategy's effect *includes* whatever depth it induces.
> Conditioning depth away answers a question nobody asked.

**Cost in n: none.** Mediation is a secondary analysis on the same data.
**Cost in fidelity: none.** **This is the one place the causal design is strictly
better than the observational one, and it is why the observational confound does
not transfer.**

---

## 2. PART A — THE DESIGN

| | |
|---|---|
| **A1 TASK SET** | the **181 real goals** in `research/corpus/decompositions.json` — real PR goals from scikit-learn and pydantic, **externally authored**. Not self-authored, which is the trap this program has hit repeatedly |
| **A2 STRATEGIES** | **2 arms**: CONSERVING (file-partitioned — no file touched by two subtasks) and REVISITING (unconstrained). **Two, not three**: the question is binary and a third arm buys multiple comparisons, not clarity |
| **A3 OUTCOME** | **binary substantive FAIL**, base rate **0.1173 MEASURED** — comfortably off both 0 and 1, so not degenerate |
| **A4 CONFOUND** | mediator, §1 |
| **A5 POWER** | see below |
| **A6 FALSIFIER** | preregistered: **equivalence bound ±0.05 absolute**. If the arms fall inside it → *"decomposition strategy does not matter at this scale"*, which is a legitimate and useful result that would let K-2 ship any defensible default |

### A5 — POWER, and the effect size chosen and why

| effect (abs) | n / arm | 2 arms |
|---|---|---|
| 0.03 | 1,510 | 3,020 |
| 0.05 | 483 | 966 |
| **0.08** | **195** | **390** |
| 0.10 | 114 | 228 |
| 0.12 | 71 | 142 |

> **Powering for 0.08 absolute** (12.7% → 4.7%), two-sided α = 0.05, power 0.80.
>
> **WHY THAT SIZE:** below ~5pp **the decision does not move.** The architectural
> principle already mandates partitioning for **containment** reasons — blind
> channels impossible, frame alignment automatic — so a small outcome penalty
> would not overturn it and a small benefit would not be why it was adopted.
> **An effect too small to change what gets built is not worth measuring at any
> n.**

---

## 3. THE COST — and the number that matters is **not the dollars**

### 3a. Token cost: **~$300**, range **$155 – $590** under ±2× on the dominant term

Built from components (all **ASSUMED** except the two subtask counts, which are
corpus-derived):

| component | value | 2× sensitivity |
|---|---|---|
| `usd_per_1k_tok` | 0.009 | **2.00×** |
| `tok_subtask` | 12,000 | **1.96×** |
| `n_subtask_revisiting` | 8.0 *(corpus mean)* | 1.70× |
| `n_subtask_conserving` | 3.0 *(11/14 were depth 3)* | 1.26× |
| `retry_rate` | 0.25 | 1.19× |
| `tok_decompose` | 3,000 | 1.04× |

**The total is stable under 2× variation** (nothing exceeds 2.0×), which by B2's
own standard makes it usable.

> **But I do not believe the 12,000-token subtask figure**, and the honest range
> is wider than the script's. A PR-scale subtask on scikit-learn with real file
> context is plausibly **5–10×** that. At 10× the total is **~$2,700**. **The
> band I would actually defend is $300 – $3,000**, and pinning it is the pilot's
> entire purpose.

### 3b. **THE BINDING CONSTRAINT IS GROUND TRUTH, NOT MONEY**

The corpus's outcome is **CI check-runs executed by the projects' own
infrastructure** — a 12-job matrix across Linux/macOS/Windows and
conda/pip/openblas/MKL variants (`outcome_source` in `decompositions.json`).
**That is exactly why it is valid external ground truth.**

> **That channel does not exist for agent work.** You cannot get scikit-learn's
> CI to run on a speculative patch without opening a public PR — an
> outward-facing action, and not one to take 390 times to run an experiment.
>
> **The alternative is reproducing the matrix locally: 390 executions of a
> project test suite.** This machine has **2 physical cores and ~3 GB available
> RAM** (measured in 1.E, where 450 tiny MBPP generations took 92 minutes).
> **scikit-learn's suite is ~20 minutes per run on good hardware; 390 runs is
> 130+ hours there and far worse here.**

**So SR-1 causal is blocked the same way SR-1 observational was, and the same
way egress q is: not on budget, on GROUND TRUTH.** `BLOCKED_SR1_SR2_SR4.md`
identified this originally — *"no task corpus with ground-truth outcomes"* — and
the corpus solved it **for historical human work only**. It does not solve it
for work an agent does now.

---

## 4. PART C — THE PILOT

| | |
|---|---|
| **purpose** | pin `tok_subtask` and `n_subtask` per arm, the two terms that drive the range |
| **size** | **40 tasks per arm** — bounds the mean within ±25% at 95% for CV ≈ 0.8 (heavy-tailed token counts) |
| **cost** | **~$62** (20.5% of the full experiment) |
| **status** | **NOT RUN. Reported for the user's gate.** |

### C3 — what the pilot would NOT resolve

- **It would not produce ground truth.** A pilot measures tokens; it does not
  make scikit-learn's CI available. **The blocker in §3b survives the pilot
  entirely**, which is the main reason not to spend on it yet.
- It would not measure the **failure base rate under agent execution**, which
  may differ sharply from the human 0.1173 that the power calculation assumes.
  **If the agent base rate is much lower, 195/arm is badly underpowered.**
- It would not settle **tier transfer** — a strategy comparison at one capability
  tier may not hold at another, and prior results in this program were
  tier-dependent.

---

## 5. PART D — THE HONEST ALTERNATIVE, and it is the recommendation

### D1. If it is never run

K-2 stays a stub that raises `NotSelectedError`. **A defensible default could
ship instead**, and its basis would not be this experiment: **the architectural
principle already mandates file-partitioned decomposition on containment
grounds**, independent of any outcome effect. Shipping CONSERVING as the default
**with the uncertainty documented** — *"chosen for containment; its effect on
task success is unmeasured"* — is more useful than a stub and more honest than a
default implying an outcome basis it does not have.

### D2. **THE FREE PATH IS NOT EXHAUSTED — and the committed source says so**

> `FINDINGS_SR1.md:167-169`: *"reaching a 50/50 split with the preregistered
> 0.167 detectable difference needs roughly **1150 records** — about 6.4× this
> corpus — and even then the depth confound would remain unless conserving and
> revisiting records were matched on depth. **Matching on depth is the cheaper
> fix and should come first.**"*

The corpus was built with **`gh api` at zero credits**. Expanding it to ~1150
records means more repositories and more history — **still zero credits**, only
wall-clock.

| path | credits | ground truth | answers |
|---|---|---|---|
| **expand corpus to ~1150 + depth-match** | **$0** | ✅ real CI, external | depth-adjusted **association** |
| causal experiment | $300–$3,000 | ❌ **unavailable** | causal effect |

**The free path does not answer the causal question — but it screens it.** If a
depth-matched association at n = 1150 shows nothing, the causal experiment is far
less attractive; if it shows something, the causal design has a measured effect
size to power against instead of my authored 0.08.

> ### RECOMMENDATION: **do not spend. Expand the corpus first.**
> **Three gates, not two:** free observational expansion → *then* the $62 pilot
> → *then* the experiment. **And the middle gate should not be opened until §3b's
> ground-truth problem has an answer**, because the pilot cannot supply one.

### D3. Would the result change a decision?

**Partly, and less than it looks.** A large effect favouring CONSERVING would
*confirm* a choice the architecture already forces for other reasons. **The
outcome that would genuinely change something is the opposite one** — CONSERVING
materially *worse* — because that would put containment and task success in
measured conflict and force a real trade-off. **An experiment worth running for
one of its two outcomes is worth less than its clean design suggests**, and that
belongs in the decision to fund it.

---

## 6. What this is not

1. **This is an ESTIMATE.** The only measured inputs are the base rate (0.1173),
   the arm subtask counts, and the 1150-record figure — all from
   `FINDINGS_SR1.md`. **Every token and price figure is assumed.**
2. **The power calculation assumes the human base rate transfers to agent
   execution.** It may not, and the pilot cannot check it.
3. **The 0.08 effect size is authored judgement**, argued in §A5, not derived.
4. **Nothing was run and no credits were spent.**
