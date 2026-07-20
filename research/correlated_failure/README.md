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
