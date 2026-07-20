# The Correlated Failure Hypothesis — research package

Reframed per Stage-0 review to **lead with measurement**: the unclaimed,
consequential thing is not that robust aggregation degrades under
correlated honest error (established in federated learning; folklore in
social choice) but *how correlated real LLM collectives actually are* —
within vs. across model families — and whether they sit in the regime
where trimming-based mechanisms lose their advantage.

## The claim (deliberately weakened from the original H1)

Not "aggregation is worse than a single agent" (the strong form — Ladha's
correlated-Condorcet results are direct evidence against it in voting
settings, so it is dropped). Instead:

> **Reversal of advantage.** Above a correlation threshold ρ*, robust
> (trimming-based) aggregation loses its advantage over naive aggregation
> and systematically discards the correct minority. The measurement
> question is whether real LLM collectives operate above ρ*.

The destination is the **constructive** result: a settlement-primary,
reward-the-correct-minority mechanism (Gyza's bonded market,
`gyza.economy.market`) that survives the regime that breaks trimming.

## Stage 0 — prior-art (done; see the session log for citations)

Closest prior art: *Mean Aggregator is More Robust than Robust
Aggregators under Label Poisoning on Heterogeneous Data* (arXiv
2404.13647) proves mean > robust aggregators under heterogeneity, but
(a) compares to the mean, not a single agent, (b) uses δ/heterogeneity,
not a correlation ρ*, (c) is a label-poisoning (adversarial) setting.
The federated-learning consensus that robust aggregation fails under
non-IID heterogeneity is established. Ladha (1993/1995) on correlated
Condorcet. No clean measurement of cross-LLM-family error correlation
exists — that gap is this project's contribution.

## What is built so far

`rho_measure.py` — the measurement instrument (backend-agnostic):
- per-model binary error vectors → pairwise phi correlation → mean
  within-family vs. cross-family, plus a categorical shared-wrong-answer
  rate (the sharp blind-spot signal).
- `SyntheticBackend`/`SyntheticWorld` — a latent-common-factor model with
  KNOWN ρ, used to validate the instrument.
- `HFCausalBackend` — a real HuggingFace causal-LM backend that scores
  multiple-choice by per-token logprob (one forward pass per choice, no
  generation) — CPU-viable for small models.

`test_rho_measure.py` — the **correctness anchor**: the instrument
recovers the null at ρ=0 (measured cross-correlation < 0.05), is
monotonic in ρ, deterministic from a seed, and separates within- from
cross-family structure. If these fail, no real number is trustworthy.

## Hardware reality (this machine)

No GPU; a 2-core 2017 laptop CPU. A full 5–15 model × hundreds-of-question
study is **not** practical here in-session. Multiple-choice-by-logprob
(not generation) makes a small local pilot feasible: SmolLM2-135M loads
in ~2 min (one-time) and scores ~0.7 s/question on CPU. The decision-gate
run wants either patience on local tiny ungated models (Qwen2.5-0.5B/1.5B,
SmolLM2-135M/360M) or free API tiers (Groq / Google AI Studio /
OpenRouter) for real cross-family models.

## Reproduce

```bash
# validate the instrument (no models needed, ~2 s)
~/dev/marshal/.os/bin/python -m pytest research/correlated_failure/ -q

# smoke-test the real backend (downloads SmolLM2-135M, ~2 min first run)
cd research/correlated_failure && ~/dev/marshal/.os/bin/python -c "
from rho_measure import Question, HFCausalBackend, error_matrix
m = HFCausalBackend('HuggingFaceTB/SmolLM2-135M-Instruct','smollm')
print(m.predict([Question('q','2+2=',('3','4','5','6'),1)]))"
```

## First real signal (pilot — `pilot_result.json`)

3 tiny ungated models, 2 families, 120 ARC-Easy questions, seed 0, CPU:

| metric | value |
|---|---|
| within-family error corr (SmolLM 135M↔360M), φ | **0.54** |
| cross-family error corr (SmolLM↔Qwen), φ | **0.33** |
| shared-wrong-answer rate | **0.51** |
| per-model error rate | 0.74 / 0.68 / 0.53 |

Read: even across genuinely different families (different orgs,
architectures, training data), errors correlate (φ≈0.33; the tetrachoric
latent correlation is *higher* — φ on binary indicators attenuates), and
on **half** of all questions a majority of the erring models converged on
the *same specific wrong answer* (the sharp categorical blind-spot signal
that most damages trimming). Within-family > cross-family, as the family
model predicts.

**Caveats (load-bearing).** Tiny 135M–0.5B models with high error rates
(0.53–0.74) plausibly *inflate* correlation vs. frontier models; 3 models
/ 2 families / one benchmark is thin; not the decision gate. This proves
the pipeline and gives a first, directionally-positive signal — it does
not yet establish that real collectives sit above ρ*, because ρ* isn't
built yet (needs minimal Stages 1–4).

## Sharpened metrics + what validation revealed (`test_sharpened.py`)

Per the Stage-0-review sharpening, the instrument now measures the
*strong* signal (same **specific** wrong answer, above a base-rate null),
not mere co-failure — validated on synthetic ground truth. Three results,
one of them self-critical:

1. **The base-rate null works, with a hard limit.** A purely *attractive
   distractor* (independent errors) yields ~0 excess — good. But a blind
   spot shared **uniformly** by the whole pool is *observationally
   identical* to an attractive distractor, so it also yields ~0 excess.
   **Only *differential* correlation is identifiable** — a sub-pool (e.g.
   a family) correlating more than the rest. The confound-robust statistic
   is therefore the **within − cross excess gap**, not absolute correlation.
2. **Diversity must decorrelate the *blind spot*, not just error timing
   (intervention arm).** At fixed ensemble size and per-model competence,
   splitting into groups with *different* blind spots raises majority-vote
   accuracy monotonically: mono 0.60 → diverse 0.81 (3 groups) → 0.86
   (5 groups). This is the empirical basis for the diversity-invariant.
3. **The 3-model pilot is underpowered for the sharpened metrics** —
   discovered by re-analysis, reported plainly:
   - Difficulty-filtering on the same 3 models flips correlations negative
     (cross φ +0.33 → −0.48) — a **selection artifact**: conditioning on
     "pool accuracy 1/3 or 2/3" *is* conditioning on disagreement.
     Difficulty must be estimated from a **held-out** pool.
   - The cross-family pair is **capability-confounded** (Qwen-0.5B 0.47 vs
     SmolLM 0.26/0.32) — confound #4; families must be capability-matched.
   - `same_wrong_excess` is **underpowered** at m=3 (leave-pair-out = 1).

**Design consequence for the real gate:** need ~10–15 models, **matched
capability across families**, with **item difficulty estimated from a
held-out reference pool** — not 3 mismatched tiny models. The pilot proved
the pipeline; the sharpening proved the pilot can't carry the claim.

## The format switch: free-form verifiable ground truth (identifiability recovered)

The identifiability trap above is an artifact of the multiple-choice
FORMAT, not the phenomenon. With free-form answers checked against a
verifier (a symbolic solver, unit tests, a SAT solver, exact numeric
match) two things change: there are no distractors, so "attractive wrong
option" stops being a competing explanation; and the wrong-answer space
becomes huge, so two models producing the *same specific wrong answer* is
overwhelmingly unlikely by chance. This recovers **absolute** same-wrong
convergence, not just the within−cross gap — which matters because the
**universal blind spot** (every model shares a failure mode; no pool
diversity saves you; within−cross reads zero) is the most dangerous
regime for Gyza, and MC renders it invisible.

Validated on synthetic ground truth (`test_freeform_...`): the SAME
universal blind spot yields `same_wrong_excess ≈ 0` in multiple choice
(hidden) but `same_wrong_convergence > 0.4` with a permutation null `< 0.02`
free-form (revealed). `rho_measure.same_wrong_convergence` +
`synth_freeform` implement and validate this; `run_freeform_pilot.py` runs
it on real models (2-digit × 2-digit multiplication, exact check).

**Report both** absolute convergence AND the within−cross gap.

### Local free-form pilot: inconclusive, and it earned its keep

The cheap detectability pilot (cached tiny models, 2-digit × 2-digit
multiplication) came back **null — and caught a real metric bug**:
- Per-model **parse rate [0.0, 0.0, 1.0]**: SmolLM2-135M/360M emitted NO
  parseable integer; only Qwen-0.5B produced numbers (all wrong, 0% acc).
- The two SmolLMs showed a spurious **within-family convergence of 1.0** —
  an artifact of both hitting the "no answer" sentinel, which the metric
  wrongly counted as agreement. `same_wrong_convergence` now takes an
  ``invalid`` sentinel and drops those; the "signal" then vanishes
  (within = None). That bug would have produced false positives in the
  real run — the pilot paid for itself by catching it.

Lesson (a design requirement, not a torture of parameters): the free-form
study needs models that (a) actually attempt the task and (b) emit
parseable answers, at INTERMEDIATE difficulty. Sub-1B models on
multiplication fail all three. The harness now applies chat templates and
reports parse-rate + distinct-output diagnostics and a ``usable`` flag, so
an unusable model can never masquerade as signal again. A valid
detectability check needs ≥1.5B models (local download, blocked by a
~10-min background cap) or free API tiers.

## Task class: measure training-data misconceptions, not arithmetic

Arithmetic (the multiplication pilot) is the WRONG task class. Its errors
come from tokenization and raw capability limits, not shared training
data — so it measures the wrong mechanism and yields either null (noise)
or spurious tokenization-artifact correlation. The hypothesis is about
**training-data-induced** blind spots: the causal path from overlapping
corpora to the same *confident, specific, plausible* wrong answer — the
internally-consistent-liar mode that defeats every detection mechanism.
Tokenization error is noisy and easy to catch; misconception error is the
dangerous kind, and it is what we must measure.

Three right task classes: **common misconceptions** (TruthfulQA — nearly
purpose-built; larger models are *less* truthful because they absorbed
human falsehoods), **code with common-but-wrong idioms** (HumanEval/MBPP
by unit tests — same specific bug in an ~infinite wrong-program space),
and **cognitive-reflection items** (bat-and-ball; the intuitive wrong
answer is all over the corpus).

`truthful.py` implements the TruthfulQA measurement, fully local: a model
answers open-ended; the cached MiniLM embedder matches its answer to the
nearest reference; the wrong-answer identity is *which listed
misconception* it matched, so `same_wrong_convergence` and a
`shared_misconception_rate` measure whether models give the SAME
known-false answer. No distractor confound — the misconception IS the
mechanism. Validated on real TruthfulQA (`test_truthful.py`): exact +
paraphrased misconceptions classify correctly, and the metric separates
shared-misconception pools from independent ones.

### First real detectability result (`truthful_result_cached.json`)

3 small models, 2 families (SmolLM 135M/360M + Qwen 0.5B), 60 TruthfulQA
items, seed 1. Unlike arithmetic, these models are USABLE here — they
produce coherent answers (only 3–8% "other") and fall into misconceptions
on **53–75%** of items.

| metric | value |
|---|---|
| shared-misconception rate (≥2 models, same known-false answer) | **0.58** |
| absolute same-misconception convergence | **0.64** |
| permutation null | **0.28** |
| convergence − null | **+0.36** |
| within-family | 0.63 |
| cross-family | **0.64** |

**Read (with caveats first-class):**

1. **The signal is real and detectable.** Convergence 0.64 is 2.3× the
   permutation null; on 58% of questions ≥2 models give the *same specific
   known-false answer*. First real evidence the phenomenon exists on
   actual models, with the right task class. The obs−null gap is
   classifier-robust (both use the same MiniLM matching).
2. **Cross-family ≈ within-family (0.64 vs 0.63).** Genuinely different
   families converge on the same misconceptions *as much as* same-family
   models do — the **universal-blind-spot signature**: the correlation is
   not family-specific. This is the most dangerous regime for Gyza (no
   pool diversity saves you), and it is exactly the case the within−cross
   statistic reads as ~zero — **so this is the empirical payoff of the
   free-form absolute-convergence switch: it reveals what within−cross
   misses.**
3. **Honest limit on the null.** It is 0.28, NOT ~0, because classifying
   each answer to the nearest *listed* misconception collapses the huge
   free-form space back to a small categorical one (a handful of
   misconceptions per item). The signal survives (0.64 ≫ 0.28), but this
   is "2.3× chance", not "chance ≈ 0". A stricter design would key
   convergence on verbatim/near-verbatim wrong answers, not nearest-listed.
4. **Not the gate.** 3 weak, capability-mismatched models, 2 families, one
   within-pair. The universal-blind-spot reading is *suggestive*; the
   capability-matched multi-family run (API tiers via `APIBackend`, or Q4
   GGUF) is decisive — but the cheap local probe came back POSITIVE, which
   is the green light for it.

## Finding in its own right: how they fail, not how often

The instrument check showed decorrelating error *timing* does nothing
while decorrelating error *direction* is everything. Two agents that
disagree constantly but fail identically *when* they fail buy the
collective nothing. **Architectural consequence for Gyza:** the diversity
invariant (the signing precondition that refuses to certify a low-diversity
collective decision) must NOT be measured by disagreement rate. It must be
conditional on error — diversity in the *direction* of failure, not the
*frequency* of it. That is a sharper, more implementable spec than
"disagreement threshold", and it came out of this experiment.

## On the intervention arm (demoted to instrument check)

"Decorrelating blind spots raises accuracy 0.60 → 0.86" on a generator
*built* to have decorrelated blind spots is Condorcet restating itself —
an instrument check, not empirical evidence for the diversity invariant.
Whether *real* families have sufficiently different blind spots that
mixing helps is exactly what the free-form real-model measurement must
answer; the synthetic result will not be presented as that evidence.

## Narrowed claim (honest, per Ladha)

Not "aggregate worse than a single agent" (Ladha's correlated-Condorcet
results are direct evidence against it in voting settings — not fought).
The defended claim: **above a correlation threshold, robust/trimming
aggregation loses its advantage over naive aggregation and discards the
correct minority; the fix is decorrelating the blind spot (mixed
families), which improves collective accuracy at fixed compute.** Regimes
where it does *not* hold are to be reported, not hidden.

## Status

Stage 0 (prior art) ✅ · instrument + correctness anchor ✅ · real backend
proven ✅ · **first cross-family ρ̂ pilot ✅ (positive signal)** · next:
(a) proper gate on stronger cross-family models (free API tiers), and
(b) minimal Stages 1–4 to establish ρ* to compare ρ̂ against.
