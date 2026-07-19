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

## Status

Stage 0 (prior art) ✅ · instrument + correctness anchor ✅ · real backend
proven ✅ · **next: the cross-family ρ̂ decision-gate run** (backend choice
pending — local-slow vs. free-API-fast).
