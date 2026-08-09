# Preregistration — Attack 1.E, the internal channel

**Committed BEFORE any generation on the experiment set.** Zero credits: local
inference on cached weights, no API call, no download.

> **The idea.** Every mechanism this program has tested reads the **output
> distribution**. Internal states — logits, activations — are a strictly larger
> information set, because the output is a lossy projection of them. A model may
> compute an error while its activations encode an uncertainty that never
> survived projection to a token.
>
> **The route exists because of a pairing problem, not a modelling idea.** Prior
> corpora in this program carry correctness labels produced by OpenRouter models
> (`research/route2_independence/route2_cache/`: llama-3.1-70b, gemma-2-27b,
> mistral-small-24b, phi-4) whose **internals are unavailable**. Local models
> have accessible internals but **nobody labelled them**. Neither half is usable
> alone. **This route generates both from the SAME model in ONE pass**, which is
> the only construction that pairs them. That is confirmed as the design.

---

## 0. Gate 0 — substrate, measured on this machine before preregistering

### 0b. Model

| | |
|---|---|
| model | **`Qwen/Qwen2.5-0.5B-Instruct`** |
| parameters | 0.49 B · **24 layers** (25 hidden-state tensors: embeddings + 24 blocks) · hidden 896 |
| dtype / device | float32, CPU (**no CUDA on this machine** — `torch.cuda.is_available()` False) |
| already cached | **yes**, `~/.cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct`, **954 MB on disk** |
| resident memory | **2.46 GB RSS** measured against **3.4 GB MemAvailable** |
| internals accessible | **yes** — `output_hidden_states=True` returns 25 tensors of shape `(1, T, 896)`, verified |

**Why this model and not a larger one.** `Qwen2.5-1.5B-Instruct` is also cached
(2.9 GB) but does not fit: 1.5 B in float32 is ~6 GB against 3.4 GB available,
and bf16 has no hardware support on this CPU (**AVX2 + FMA, no AVX512**), so it
would be emulated. **The constraint is measured, not assumed.**

**Measured throughput**, `i5-7200U` (**2 physical cores / 4 threads**, 2.5 GHz):

| configuration | throughput | per problem |
|---|---|---|
| unbatched | 1.2 tok/s | ~130 s |
| **batch = 4** | **2.68 tok/s aggregate** | **57.4 s** |

Batching is a **2.2× win** because CPU decode becomes a GEMM rather than a
GEMV. `vmstat` during the run shows **si/so = 0** — the machine is genuinely
compute-bound at 95% CPU, **not swapping**. Re-forward for hidden states costs
**6.4 s** per problem and is negligible beside generation.

**Budget: ~6 hours of local background compute for 450 problems.** Accepted.

### 0c. Task set

| | |
|---|---|
| benchmark | **MBPP**, `google-research-datasets/mbpp`, config `full`, split `test` |
| already cached | **yes**, 148 KB parquet — **no download** |
| size | **500 problems**, `task_id` 11–510, **exactly 3 asserts each** |
| ground truth | **mechanical** — execute the generated program against the task's own asserts |

**CALIBRATION / EXPERIMENT split, fixed now:**

- **CALIBRATION** = `task_id` 11–60 (**50 problems**). Used **only** for the
  Gate-0 pass-rate estimate and for confirming the prompt format. **Excluded
  from the probe experiment entirely.**
- **EXPERIMENT** = `task_id` 61–510 (**450 problems**). No threshold in this
  document is fixed against any of these.

**Degeneracy gate:** if the calibration pass rate is **< 0.10 or > 0.90**, the
solved/unsolved split has nothing to train or test on and this route **STOPS at
Gate 0 and reports BLOCKED-DEGENERATE.**

**Disclosed:** an 8-problem harness smoke test ran on calibration problems
before this commit, to verify that hidden-state capture and the logprob indexing
produce correctly-shaped artifacts. Its outputs live in a scratch directory
outside the repository and are used for **no measurement**.

### 0d. Credit gate

> **ZERO CREDITS.** Model and dataset are **already on disk**; nothing is
> downloaded and no API is called. The only cost is local CPU time.

### 0e. The distinction this route rests on

Stated in the box at the top and **confirmed**: labels and activations come
from the **same model**, the **same greedy decode**, in the **same pass**. No
label is imported from a model whose internals are unavailable, and no
activation is paired with a label some other model produced.

---

## 1. Feasibility ceiling — computed BEFORE fixing the decision threshold

Standing discipline requires the attainable range before a threshold is fixed.
With **TEST-OUT ≈ 225 problems** and an expected pass rate near 0.35
(**n₁ ≈ 79 positive, n₀ ≈ 146 negative**), the Hanley–McNeil standard error of
AUROC is

| true AUROC | SE | 95% CI |
|---|---|---|
| 0.50 | 0.042 | [0.418, 0.582] |
| **0.65** | **0.039** | **[0.573, 0.727]** |

> **The smallest AUROC whose CI excludes 0.5 is ≈ 0.582.** The preregistered
> **0.65** bar therefore sits **inside** the attainable range — it is neither
> unreachable nor trivially satisfied — with ~0.07 of headroom above the
> detection floor. **The threshold is feasible at this n and is adopted.**

Had TEST-OUT been ~60 problems the half-width would be ~0.15 and a 0.65 bar
would be unfalsifiable; that is why the full 450 are generated rather than a
faster subset.

---

## 2. THE SPLIT — the experiment, and where the obvious design breaks

**The literal design "train on SOLVED, test on UNSOLVED" is not runnable, and
this must be said before it is worked around.** Each partition would be
**single-class**, and **AUROC is undefined on a single class**. Splitting on the
*label* cannot produce a partition that has labels to score. The task document
anticipates the degeneracy and asks for it to be resolved explicitly; the
resolution follows.

**Competence is stratified on an axis that is independent of the label and
independent of the model:** the syntactic complexity of **MBPP's own reference
solution** (`code` field), counted as **AST node count**. It is a property of
the benchmark, computable before any generation, and it **cannot encode the
model's outcome**.

```
EASY  = reference complexity  <  median      the competent region
HARD  = reference complexity  >= median      outside it

TRAIN     = 70% of EASY   (seed 1)     probe fits here, and only here
TEST-IN   = 30% of EASY                in-competence generalisation
TEST-OUT  = ALL of HARD                out-of-competence transfer  <-- the question
```

Both partitions retain **both classes**, so AUROC is defined on each, and the
decision rule maps onto them directly.

### 2a. The precondition, checked rather than assumed

**If EASY and HARD do not differ in pass rate, the axis is not measuring
competence** and the transfer question is unanswerable by it. That comparison is
computed and printed **first**; if `pass(EASY) <= pass(HARD)` the transfer cells
are reported **INCONCLUSIVE** and no CHANNEL verdict is claimed from them.

### 2b. Why the problem-level split holds by construction

Each problem contributes **exactly one** `(activation, label)` pair — the
final-token hidden state, or the mean over generated tokens. **There is no
second example from the same problem that could land on the other side of the
split.** This is an architectural guarantee rather than a discipline item, which
is this program's standing preference (append-only / derived-not-stored is the
same move).

It is asserted anyway, at experiment time and under pytest
(`test_split.py`), with **negative controls** that inject each leak species —
TRAIN∩TEST-IN, TRAIN∩TEST-OUT, dropped problems, and a simulated
**example-level** split — and require the assertion to **fire**. A passing
assertion that has never been shown to fail is not evidence; this program has
already been bitten by exactly that (a harm quantity that raised on every input
under 785 green tests).

---

## 3. The probe, fixed now

| | |
|---|---|
| family | **linear** — L2 logistic regression on standardized hidden states, `C = 1.0` |
| features | (a) **final-token** state, (b) **mean over generated tokens**; both reported |
| layers | **all 25**, swept; the **full curve is reported**, never just the best |
| layer selection | **argmax of TRAIN 5-fold cross-validated AUROC.** Test performance is **never** consulted |

**Nonlinear probes are not run first.** A linear failure says the information is
not linearly available; a nonlinear success may be fitting the split. If linear
fails and a nonlinear probe is tried, **both are reported and the nonlinear
result is labelled EXPLORATORY**.

## 4. Baselines — none optional, and the second group is the point

1. **CHANCE** / majority class.
2. **OUTPUT-DISTRIBUTION** — `mean_logprob`, `min_logprob`, `sum_logprob`,
   `mean_entropy`, `max_entropy`, each as a single-feature logistic fit, **plus
   a joint fit over all five (`DIST-ALL`)**. Every one is fit on TRAIN and
   scored on TEST, exactly as the probe is, so sign and calibration are handled
   identically.
3. **PROBLEM DIFFICULTY** — the reference-complexity feature itself. *A probe
   that only recovers "this problem is hard" has not detected "this answer is
   wrong."*
4. **LENGTH** — `n_gen_tokens`, a trivial baseline that is often embarrassingly
   strong.

> **The headline statistic is NOT the probe's AUROC.** It is the **paired
> difference against the strongest output-distribution baseline**, bootstrapped
> on the same resamples. 1.E's entire claim is that internals carry what the
> output does not; reporting AUROC alone would be reporting the wrong number.

## 5. Statistics

- **AUROC** with a **2000× bootstrap CI resampled over PROBLEMS**.
- **TPR and FPR** at an operating point fixed on TRAIN (never on test).
- **Permutation null**: labels shuffled **3000×**, empirical `p = (ge+1)/(n+1)`.
- **Paired difference** vs the best output-distribution baseline, CI from the
  **same** bootstrap resamples.

## 6. Decision rule

| outcome | condition |
|---|---|
| **CHANNEL-LIVE** | TEST-OUT AUROC **> 0.65** with CI excluding 0.5, **AND** paired difference vs best output-distribution baseline **positive with CI excluding 0** |
| **CHANNEL-REDUNDANT** | beats chance but **not** the output-distribution baselines → internals add nothing the logprobs did not carry, and require white-box access for no gain |
| **CHANNEL-COMPETENCE-BOUND** | strong on **TEST-IN**, at chance on **TEST-OUT** → the bound holds internally too |
| **CHANNEL-DEAD** | at chance everywhere |

**Any result driven by a single layer, a single problem family, or the
crash/wrong-answer imbalance → INCONCLUSIVE for that cell.**

## 7. Point predictions, stated before data

**Mine, and they disagree with the task's ordering:**

| outcome | task's prior | **mine** |
|---|---|---|
| CHANNEL-COMPETENCE-BOUND | 45% | **30%** |
| **CHANNEL-REDUNDANT** | 30% | **45%** |
| CHANNEL-LIVE | 25% | **15%** |
| CHANNEL-DEAD | — | **10%** |

**The argument for moving mass onto REDUNDANT.** Beating chance is easy and
beating logprobs is hard, and those are different bars. Mean token logprob is a
well-established correctness signal for code, and a 0.5 B model's final-token
state largely encodes *what it just wrote* — format, length, whether it emitted
a fenced block — which correlates with correctness through the same channel the
logprobs already expose. **The probe will very likely clear chance somewhere and
very likely fail the paired test**, and that combination is REDUNDANT, not
COMPETENCE-BOUND.

**Where the task's Phase-7 argument is right, and where the substrate cuts
against it.** `research/FRONTIER_LEDGER.md` records measured error positions
**mid-computation (median normalized ≈ 0.60)** — arithmetic slips rather than
comprehension failures a model would represent as uncertainty, which is a real
reason to expect a negative. **But that was measured on frontier-tier models.**
A 0.5 B model fails far more often by *misreading the problem entirely*, and
gross comprehension failure is more plausibly represented in activations than a
mid-computation slip. **The substrate therefore pushes slightly toward LIVE
relative to the Phase-7 prior, and I have still put LIVE lowest** — the
paired-comparison bar is what dominates.

**Quantitative predictions:**

| quantity | predicted |
|---|---|
| MBPP pass rate (Qwen2.5-0.5B-Instruct) | **0.30 – 0.45** |
| CRASH-class share of failures | **0.35 – 0.60** |
| selected layer, as depth fraction | **0.60 – 0.90** |
| TEST-IN AUROC | **0.62 – 0.75** |
| TEST-OUT AUROC | **0.52 – 0.65** |
| best output-distribution baseline, TEST-OUT | **0.58 – 0.70** |
| paired difference on TEST-OUT | **−0.05 to +0.05, CI including 0** |

## 8. Honesty conditions

- **A NEGATIVE IS A SUCCESS AND COMPLETES THE MAP.** 3.C closed
  CLOSED-NEGATIVE and 1.B closed VIABLE-but-NOT-ROBUST. A fourth item closing
  cleanly is the right shape. **No larger model will be proposed to rescue a
  negative**, and no threshold will move after data.
- **Diagnose any exact 0 or 1**, and **any AUROC at or near 1.0 — that indicates
  leakage before it indicates a finding.**
- **The split assertion and its negative controls are reported BEFORE any
  result.**
- **CRASH vs WRONG-ANSWER is reported beside every headline number**, and the
  probe is scored separately on the wrong-answer subset when that subset is
  large enough. A probe that detects "this will raise" has detected something
  much easier than "this is wrong."
- **Label DEFINITIONAL vs MEASURED.**
- **SCOPE, and it is narrow.** This measures **ONE local open-weight 0.5 B model
  on ONE benchmark**. It licenses claims about that. **It does not license
  claims about frontier models, whose internals are unavailable to this program
  by construction** — which is the very fact that made this route necessary.
- **Precedence check.** `research/BUILD_PLAN.md` C1 says *do not build a
  correctness verifier*, and §0 forbids opening discovery routes without
  explicit instruction. This route is **explicitly instructed**, and it **builds
  nothing** — it runs a falsifier against a channel the competence bound has not
  been tested on. No committed finding is edited.
