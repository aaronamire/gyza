# Findings — Attack 1.E, the internal channel

Preregistered at **`6df7baf`** (blob `b9756b8`), the **only** file in
`research/internal_channel/` at that commit — verified with `git ls-tree`.
**Zero credits:** local inference on already-cached weights; **nothing was
downloaded and no API was called.**

Substrate: **`Qwen/Qwen2.5-0.5B-Instruct`** (24 layers, hidden 896, float32,
CPU) over **MBPP `full/test`**, 500 problems. **50 reserved for calibration**
(`task_id` 11–60, excluded from everything below), **450 in the experiment**.
Labels and activations come from **the same model, the same greedy decode, one
pass** — which is the whole reason the route exists.

---

## 1. THE SPLIT ASSERTION, reported first

**8/8 pass, of which 4 are negative controls that are required to FIRE.**

| test | |
|---|---|
| `test_split_is_disjoint_by_problem_id` | PASS |
| `test_split_is_exhaustive_and_partitions_every_problem` | PASS |
| `test_easy_hard_are_separated_by_the_difficulty_axis` | PASS |
| `test_complexity_is_label_independent_and_deterministic` | PASS |
| **negative control** — TRAIN∩TEST-IN leak | **caught** |
| **negative control** — TRAIN∩TEST-OUT leak | **caught** |
| **negative control** — dropped problems | **caught** |
| **negative control** — simulated example-level split | **caught** |

The tests exercise `make_split` / `check_split`, **the same functions the
experiment calls**, not a reimplementation. `check_split` also runs inside
`probe.py` at experiment time, so a leak fails the run and not only the suite.

**The split holds by construction, which is stronger than holding by
discipline:** each problem contributes **exactly one** `(activation, label)`
pair, so there is no second example from the same problem that could land on the
other side.

### 1a. The design the task specified is not runnable, and this is why

> **"Train on SOLVED, test on UNSOLVED" makes both partitions single-class, and
> AUROC is undefined on a single class.** Splitting on the label cannot produce
> a partition that has labels to score.

Competence is stratified instead on **MBPP's own reference-solution complexity**
(AST node count) — a property of the **benchmark**, label-independent and
model-independent, computable before any generation.

| partition | rule | n | pass rate |
|---|---|---|---|
| **TRAIN** | 70% of EASY | 157 | 0.4522 |
| **TEST-IN** | 30% of EASY | 68 | 0.5588 |
| **TEST-OUT** | **all of HARD** | **225** | **0.2000** |

**The precondition was checked, not assumed:** EASY pass **0.4844** vs HARD
**0.2000**, gap **+0.2844**. The axis really does track competence, so
TEST-OUT is genuinely outside it.

**Diagnosing the exact 0.2000:** **coincidence, not artifact** — 45/225, and
225 × 0.2 = 45 exactly. The equal partition sizes (225/225) *are*
**DEFINITIONAL**: a median split of 450.

---

## 2. Generation and labelling

| quantity | calibration (50) | **experiment (450)** | predicted | |
|---|---|---|---|---|
| **pass rate** | 0.3800 | **0.3422** | 0.30–0.45 | ✅ |
| **CRASH-class share of failures** | 0.2581 | **0.2534** (75/296) | 0.35–0.60 | ❌ **missed low** |
| **WRONG-ANSWER share** | 0.7419 | **0.7466** (221/296) | — | — |
| canonical-comparison delta (`==` vs `values_equal`) | 0 | **0** | 0 | ✅ |

Failure modes over 296: **WRONG 221, CRASH 65, SYNTAX 9, TIMEOUT 1.**

**The crash-rate miss matters and it runs in the useful direction.** Three
quarters of failures are genuine wrong answers, so the wrong-answer subset is
large enough (n = 177) to score the probe on separately — which is the check
that stops "detects a program that will raise" from passing itself off as
"detects a wrong answer."

**On the canonical comparison.** `gyza.canon.values_equal` differs from `==`
**only on NaN**. The divergence was verified to exist on a synthetic NaN case
(native `WRONG`, canonical `PASS`) and then **measured to fire on zero MBPP
problems**. "The helper changes nothing here" is a **MEASURED** fact about this
task set, not an assumption.

---

## 3. The layer curve — reported whole, nothing selected on test

Layer selection is **argmax of TRAIN 5-fold cv-AUROC**; test performance was
never consulted. Selected **layer 15** (`final`) and **layer 20** (`mean`).

| | `final` | `mean` |
|---|---|---|
| **TEST-OUT AUROC at selected layer** | **0.6877** | **0.7072** |
| layers (of 25) with TEST-OUT > 0.65 | **13** | **18** |
| post-hoc best layer | 19 → 0.7530 | 15 → **0.8051** |

**Not a single-layer result** by the preregistered rule — 13 and 18 layers clear
0.65 — so no cell is INCONCLUSIVE on that ground. Signal rises with depth and
plateaus over roughly the last third.

### 3a. What the selection rule cost, measured

Post-hoc selection would have reported **+0.0653** (`final`) and **+0.0979**
(`mean`), and `mean`'s best layer (0.8051) **exceeds the strongest baseline's
0.7958** — the headline would have *looked* like a win. **Carried all the way
through the paired test it still fails:** `mean` post-hoc paired **+0.0087, 95%
CI [−0.0999, +0.1070]**; `final` post-hoc **−0.0434, CI [−0.1364, +0.0460]**.

> **The verdict is robust to the layer-selection rule.** Tuning would have
> changed the headline number and **not** the decision.

---

## 4. AUROC — held-out SOLVED-region vs held-out UNSOLVED-region

| | `final` | `mean` |
|---|---|---|
| **TEST-IN** (in-competence) | 0.6825, CI [0.5476, 0.8094], p = 0.0043 | 0.7053, CI [0.5686, 0.8318], p = 0.0037 |
| **TEST-OUT** (out-of-competence) | **0.6877**, CI [0.6007, 0.7738], **p = 0.0003** | **0.7072**, CI [0.6150, 0.7956], **p = 0.0003** |
| TPR / FPR at the TRAIN threshold (TEST-OUT) | 0.5778 / 0.2889 | 0.5778 / 0.2167 |

**No AUROC approaches 1.0** (max observed 0.8051), so there is no leakage
signature. Permutation nulls (3000×) reject chance decisively on TEST-OUT.

### 4a. The competence bound does **NOT** appear internally — the predicted outcome is REFUTED

**TEST-OUT ≥ TEST-IN for both features.** The probe does not degrade outside the
model's competent region; if anything it does marginally better there. So
**CHANNEL-COMPETENCE-BOUND — the task's modal prediction at 45% and mine at
30% — is not what happened.**

**Stated with its uncertainty:** TEST-IN has only n = 68 and a CI spanning
0.55–0.83, which **overlaps TEST-OUT's CI heavily**. The honest claim is
**"no evidence of degradation outside competence,"** not "it transfers better."
The two partitions also differ in base rate (0.5588 vs 0.2000); AUROC is
base-rate independent, but the CIs are not comparable in width.

---

## 5. THE HEADLINE — the paired comparison against the output distribution

The claim of 1.E is that **internals carry what the output does not**. The raw
AUROC is not that claim; the paired difference is.

| baseline (TEST-OUT) | AUROC |
|---|---|
| **`sum_logprob`** | **0.7958** ← strongest |
| `mean_entropy` | 0.7700 |
| `mean_logprob` | 0.7595 |
| `DIST-ALL` (joint, 5 features) | 0.7637 |
| `min_logprob` | 0.6626 |
| `max_entropy` | 0.6419 |
| `n_gen_tokens` (length) | 0.6337 |
| `difficulty(cx)` | 0.6132 |
| chance | 0.5000 |

> | paired difference, probe − `sum_logprob`, TEST-OUT | value | 95% CI | |
> |---|---|---|---|
> | **`final`** | **−0.1085** | **[−0.2182, −0.0039]** | **significantly WORSE** |
> | **`mean`** | **−0.0895** | [−0.2045, +0.0217] | worse, CI includes 0 |

**Every internal probe loses to a scalar the output distribution hands you for
free.** For `final` the loss is significant at the 95% level.

### 5a. Weakly correlated, and still adds nothing — the sharper finding

| | `final` | `mean` |
|---|---|---|
| **Spearman(probe, `sum_logprob`)** | **+0.2575** | **+0.3515** |
| `DIST-ALL` alone | 0.7637 | 0.7637 |
| `DIST-ALL` + probe score | 0.7405 | 0.7668 |
| **incremental value of the probe** | **−0.0235, CI [−0.1071, +0.0596]** | **+0.0024, CI [−0.0865, +0.0925]** |

The probe entered as **one fitted score column against five** distribution
features, so a gain could not come from dimensionality alone.

> **The probe is only weakly correlated with the logprobs (ρ ≈ 0.26–0.35) and
> still adds nothing detectable on top of them.** It is not reading a noisy copy
> of the output signal — it is reading *something else*, and that something else
> carries **no incremental information about correctness**. That is a stronger
> statement than "redundant" in the ordinary sense, and it is the most
> interesting number in this document.

### 5b. Not a crash detector

On the **wrong-answer subset with crashes dropped** (n = 177), the ordering is
unchanged: probe **0.6901** / **0.7226** vs `sum_logprob` **0.7958**; paired
**−0.1061** and **−0.0746**. **The result is not an artifact of the
crash/wrong-answer imbalance.**

---

## 6. THE DECISION

Against the preregistered rule:

| outcome | condition | met? |
|---|---|---|
| **CHANNEL-LIVE** | TEST-OUT > 0.65, CI excluding 0.5 **AND** paired difference positive with CI excluding 0 | first ✅ (0.6877 / 0.7072), **second ✗ — the difference is NEGATIVE** |
| **CHANNEL-REDUNDANT** | beats chance but not the output-distribution baselines | ✅ |
| CHANNEL-COMPETENCE-BOUND | strong on TEST-IN, chance on TEST-OUT | ✗ — TEST-OUT ≥ TEST-IN |
| CHANNEL-DEAD | chance everywhere | ✗ |

> # CHANNEL-REDUNDANT. **1.E is CLOSED.**

**What 1.E concluded:**

1. **The internal channel is real and it is not free.** A linear probe on
   activations detects this model's own errors well above chance
   (**AUROC 0.688–0.707, p = 0.0003**), and does so **outside** the region the
   model is competent in.
2. **It buys nothing.** A scalar available from the output distribution —
   `sum_logprob`, **0.7958** — beats it, significantly so for the final-token
   feature, and the probe adds **no measurable incremental information** on top
   of the distribution features. **The strictly larger information set did not
   yield a strictly better verifier**, and requiring white-box access for a
   worse signal is a straight loss.
3. **The predicted mechanism is refuted, and the conclusion survives anyway.**
   The competence bound did **not** reappear internally — the probe transfers
   out of competence without degrading. **1.E closes on economics, not on
   competence.** That is a different reason from the six mechanism families,
   and it should not be recorded as a seventh instance of the same bound.

**Predictions scored:**

| prediction | mine | task's | actual | |
|---|---|---|---|---|
| **outcome** | REDUNDANT **45%** | REDUNDANT 30% | **REDUNDANT** | ✅ **my ordering was right** |
| | COMPETENCE-BOUND 30% | COMPETENCE-BOUND **45%** | refuted | |
| pass rate | 0.30–0.45 | — | 0.3422 | ✅ |
| CRASH share | 0.35–0.60 | ~0.40 | 0.2534 | ❌ **missed low** |
| selected layer (depth fraction) | 0.60–0.90 | — | 0.63 / 0.83 | ✅ |
| TEST-IN AUROC | 0.62–0.75 | — | 0.683 / 0.705 | ✅ |
| TEST-OUT AUROC | 0.52–0.65 | — | **0.688 / 0.707** | ❌ **missed high** |
| best output-dist baseline | 0.58–0.70 | — | **0.7958** | ❌ **missed high** |
| paired difference | −0.05 to +0.05, CI incl. 0 | — | −0.109 / −0.090 | ❌ **missed low** |

**I got the verdict right and the magnitudes wrong in a consistent direction:**
everything — probe and baselines alike — was more predictive than I expected.
The reasoning that produced the correct verdict ("beating chance and beating
logprobs are different bars") was right for the right reason; the numeric ranges
were simply set too low across the board.

---

## 7. Honest limits

1. **SCOPE, and it is narrow. ONE local open-weight 0.5 B model, ONE benchmark,
   ONE greedy sample per problem.** It licenses claims about that.
   **It does NOT license claims about frontier models, whose internals are
   unavailable to this program by construction** — which is the very fact that
   made this route necessary. A 70 B model's activations may behave differently
   and **this experiment cannot say.**
2. **The substrate was chosen by the machine, not by the science.** No CUDA,
   3.4 GB available RAM, 2 physical cores. `Qwen2.5-1.5B-Instruct` is cached but
   does not fit. **Per the preregistration's honesty condition, no larger model
   is proposed to rescue this** — but the size limit is a real external validity
   threat and is not disguised as a design choice.
3. **The difficulty axis is a proxy for competence, not competence itself.**
   Reference-solution AST count separates pass rates by 0.284, which is
   substantial, but "problems with longer reference solutions" is not identical
   to "problems this model does not understand." A per-problem competence
   estimate would need k samples per problem, which this machine cannot afford.
4. **TEST-IN is underpowered** (n = 68, CI width ≈ 0.28). The comparison in
   §4a is qualitative and is reported as such.
5. **The probe saw one decode per problem.** Probes are often fit on many
   token positions; that design would have created a genuine leak risk, which
   this one forecloses — at the cost of n = 450 examples total.
6. **`sum_logprob` is partly a length signal** (`n_gen_tokens` alone reaches
   0.6337). It is still a legitimate output-distribution feature — it is exactly
   what a black-box verifier would have — but the baseline the probe lost to is
   not purely "confidence."

---

## 8. Where this leaves the map

Three attack items have now closed on **structural** grounds and one on
**economic** grounds:

| item | verdict | closed because |
|---|---|---|
| 3.C — declarative maximisation | CLOSED-NEGATIVE | authority constraint: a system cannot constitute what it merely observes |
| 1.B — verification by consequence | VIABLE, **NOT ROBUST** | knife-edge `s`, single-repo decisive cell |
| **1.E — the internal channel** | **CHANNEL-REDUNDANT** | **the larger information set is not a better one** |

**1.E is the only item that failed for a reason unrelated to the competence
bound**, and that is the finding worth carrying: the bound was not what stopped
it. Reading internal states works, transfers outside competence, and is beaten
by a number you already have. **It should not be recorded as a seventh
mechanism family failing for the same reason** — it is a different result, and
`research/FRONTIER_LEDGER.md`'s Phase-7 argument (mid-computation slips are not
represented as uncertainty) **did not turn out to be the operative mechanism at
this tier.**
