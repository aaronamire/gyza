# Methods & reproducibility — the correlated-failure decisive experiment

Everything a reader needs to reproduce the result, pulled from the repo
(not recollection). Values are from `decisive_result_openrouter.json`,
`PREREGISTRATION.md`, the metric source (`codebench.py`, `truthful.py`,
`rho_measure.py`), and git. All artifacts are on `main`.

Headline: on the confound-free primary battery, **cross-family same-bug
convergence 0.560 vs. null 0.044** and **within-family 0.603**, R = 1.08 —
which triggers the pre-registered falsifier (0.8 ≤ R ≤ 1.2, both > null):
**H2 falsified.** Diversity does not decorrelate failure.

**Mechanism corrected (§9, conditional-independence null).** The
permutation null above only shows the wrong-answer distribution is
non-degenerate *across problems*; against the *right* null — the
leave-pair-out per-problem wrong-answer distribution — pairwise excess is
≈ 0 for both within and cross (Case A). The H2 decision (family-invariant
failure) stands; the mechanism is a **constrained wrong-answer space**
(median 1 distinct wrong answer/problem), not a shared cognitive blind
spot. Full reanalysis: `FINDINGS_CI_NULL.md`.

---

## 1. Models and families

Nine models, five families, via OpenRouter. Deterministic: `seed = 1`;
identical items/problems for all models.

| model ID | family |
|---|---|
| `meta-llama/llama-3.1-70b-instruct` | llama |
| `meta-llama/llama-3.3-70b-instruct` | llama |
| `google/gemma-2-27b-it` | gemma |
| `google/gemma-3-27b-it` | gemma |
| `mistralai/mistral-small-24b-instruct-2501` | mistral |
| `mistralai/mistral-small-3.1-24b-instruct` | mistral |
| `mistralai/mistral-small-3.2-24b-instruct` | mistral |
| `qwen/qwen-2.5-72b-instruct` | qwen |
| `microsoft/phi-4` | phi |

Same-family pairs are matched in size (Llama 70B×2, Gemma 27B×2, Mistral
24B×3) so within-family pairs co-occur in the capability band.

## 2. Capability band ("matched how?")

- **Band metric:** MBPP **code pass rate** (fraction of the 50 code
  problems solved correctly). This is the band used for the *primary*
  battery. TruthfulQA accuracy is measured too and bands the secondary.
- **Threshold:** a model is in-band iff `top_score − score ≤ 0.10`
  (±10 percentage points, pre-registered). Out-of-band models are
  reported but excluded from the within/cross comparison, so the
  comparison measures *family*, not *capability*.

Per-model scores (both measured):

| model | TruthfulQA acc | **code pass** | in code band? |
|---|---|---|---|
| llama-3.1-70b-instruct | 0.525 | **0.400** | ✓ (top) |
| llama-3.3-70b-instruct | 0.463 | 0.080 | ✗ |
| gemma-2-27b-it | 0.613 | **0.380** | ✓ |
| gemma-3-27b-it | 0.525 | **0.400** | ✓ |
| mistral-small-24b-2501 | 0.450 | **0.320** | ✓ |
| mistral-small-3.1-24b | 0.438 | 0.180 | ✗ |
| mistral-small-3.2-24b | 0.512 | **0.360** | ✓ |
| qwen-2.5-72b-instruct | 0.300 | 0.120 | ✗ |
| phi-4 | 0.550 | **0.380** | ✓ |

- **Code band = 6 models, 4 families** (pass 0.32–0.40): llama-3.1-70b,
  gemma-2-27b, gemma-3-27b, mistral-2501, mistral-3.2, phi-4. Excluded:
  llama-3.3-70b (0.08), mistral-3.1 (0.18), qwen-72b (0.12).
- **TruthfulQA band = 4 models** (acc within 0.10 of top 0.613 → ≥0.513):
  llama-3.1-70b, gemma-2-27b, gemma-3-27b, phi-4.

**Pair counts** (`design`): code = **2 within / 13 cross**; TruthfulQA =
**1 within / 5 cross**.

- **2 within-family code pairs:** `gemma-2-27b × gemma-3-27b`,
  `mistral-small-24b-2501 × mistral-small-3.2-24b`.
- **13 cross-family code pairs:** listed in §5.

> Honesty flag for the paper: the code band yielded **2** within-family
> pairs, **one short of the pre-registered ≥3.** The ratio's within side
> is therefore underpowered. The finding does not rest on it — the crux
> (13 cross-family pairs all ≫ null; cross ≈ within with overlapping CIs)
> is well-powered independently — but this must be stated.

## 3. Code battery (primary)

- **Benchmark:** **MBPP** (`google-research-datasets/mbpp`, `full/test`
  split, parquet via HuggingFace hub). **N = 50** problems, seeded subset
  (`numpy.random.default_rng(1).permutation(...)[:50]`, sorted).
- **Prompt:** *"Write a Python function named `<entry_point>` for this
  task: `<mbpp prompt>`. Respond with ONLY the code in a python code
  block."* `<entry_point>` is parsed from the test asserts (the fix for
  artifact #3 in §8). Generation is greedy (temperature 0), `max_tokens
  = 400`; the fenced code block is extracted.
- **Behavioral signature:** for each `assert <call> == <expected>` test,
  the candidate program is run in a **5-second-timeout subprocess** and
  the signature element is `repr(eval(<call>))`; a crash → `ERR:<type>`,
  a timeout/blank → `TIMEOUT`. `expected_signature = [repr(eval(<expected>))
  …]`. A program is **wrong** iff `signature ≠ expected`.
- **"Same specific bug":** two wrong programs with the **identical
  behavioral signature** — same outputs on the same test inputs. This is
  the confound-free "wrong answer" (no curated list, no topic similarity,
  ~infinite wrong-program space).

## 4. Convergence metric and null, stated formally

For a model pair (i, j) over problems q, with wrongness
`w_i[q] = (sig_i[q] ≠ expected[q])`:

```
convergence(i, j) = Σ_q [ w_i[q] ∧ w_j[q] ∧ (sig_i[q] = sig_j[q]) ]
                    ─────────────────────────────────────────────────
                    Σ_q [ w_i[q] ∧ w_j[q] ]
```

= P(identical wrong signature | both wrong). Reported **within = 0.603 /
cross = 0.560** are the **means of convergence(i, j) over the within /
cross pairs** in the code band.

**Permutation null:** the same statistic with model j's signature vector
**shuffled across problems** (`n_perms = 30`), averaged over permutations
and pairs. In an open behavior space chance collision → ~0; here the null
is **0.044**.

**Bootstrap CI (over pairs)** (`run_openrouter.py::_ci`): the set of
per-pair convergence values for a group (within or cross) is resampled
with replacement to its own size **3000 times**; the CI is the
**2.5th / 97.5th percentiles** of the resampled means. The CI thus
reflects **between-pair** variability — an outlier pair widens it.

## 5. Primary result — per pair

- **within:** mean **0.6027**, 95% CI **[0.5625, 0.6429]**, null 0.0437
- **cross:** mean **0.5602**, 95% CI **[0.5330, 0.5856]**, null 0.0442
- **R = 0.6027 / 0.5602 = 1.08**

| pair | type | conv | null |
|---|---|---|---|
| gemma-2-27b × gemma-3-27b | WITHIN | 0.643 | 0.046 |
| mistral-2501 × mistral-3.2 | WITHIN | 0.562 | 0.042 |
| llama-3.1-70b × gemma-2-27b | cross | 0.556 | 0.044 |
| llama-3.1-70b × gemma-3-27b | cross | 0.607 | 0.048 |
| llama-3.1-70b × mistral-2501 | cross | 0.448 | 0.039 |
| llama-3.1-70b × mistral-3.2 | cross | 0.536 | 0.041 |
| llama-3.1-70b × phi-4 | cross | 0.481 | 0.042 |
| gemma-2-27b × mistral-2501 | cross | 0.613 | 0.048 |
| gemma-2-27b × mistral-3.2 | cross | 0.533 | 0.046 |
| gemma-2-27b × phi-4 | cross | 0.593 | 0.043 |
| gemma-3-27b × mistral-2501 | cross | 0.567 | 0.042 |
| gemma-3-27b × mistral-3.2 | cross | 0.586 | 0.042 |
| gemma-3-27b × phi-4 | cross | 0.556 | 0.044 |
| mistral-2501 × phi-4 | cross | 0.600 | 0.045 |
| mistral-3.2 × phi-4 | cross | 0.607 | 0.050 |

Every pair (all 13 cross, both within) is **+0.41 to +0.60 above its
null** (~13× chance). No single pair drives R.

## 6. TruthfulQA secondary (and where it disagrees)

Band = 4 models (llama-3.1-70b, gemma-2, gemma-3, phi-4): 1 within, 5
cross pairs. Convergence is keyed on the models' own answer strings, not
the curated misconception list; wrongness uses the correct references.

- **Verbatim floor** (normalized-identical OR token-Jaccard ≥ 0.8):
  within **0.083** (1 pair; degenerate CI), cross **0.017** [0.0, 0.05].
  → *leans family-specific.*
- **Semantic ceiling** (MiniLM cosine between the two answers ≥ 0.7):
  within **0.667** (1 pair), cross **0.736** [0.672, 0.801].
  → *universal, but topic-confounded* (same-question answers are similar
  regardless of shared claim).

Per the pre-registration, on disagreement the **code battery is
authoritative** → universal. The secondary is 1-within-pair underpowered
and must be reported as a partial disagreement, not suppressed.

## 7. Pre-registration (exact, and it predates the data)

Decision rule, verbatim from `PREREGISTRATION.md`. Let R = mean
within-family ÷ mean cross-family convergence on the code battery among
capability-matched models.

- **R ≥ 1.5 and cross > null** → H2 supported (diversity partially helps).
- **0.8 ≤ R ≤ 1.2 and both within and cross > null** → **H2 FALSIFIED:
  universal blind spot.**
- **Both ≈ null (≤ ~2× null)** → no phenomenon.
- Any single outlier pair driving R → report as inconclusive.

Design required **≥3 within / ≥6 cross pairs**, **±10-pt** band,
per-pair reporting, fixed seed.

**Git provenance (pre-registration predates result):**
- `PREREGISTRATION.md` — commit `d03d289`, **2026-07-21 00:26:43 +0500**
- run harness `run_openrouter.py` — commit `2c8f759`, 2026-07-21 23:16:28
- result `decisive_result_openrouter.json` + FINDINGS — commit `7a18152`,
  2026-07-22 00:37:24

The pre-registration is committed ~24 h before the run and result.

## 8. Artifact-correction trail (verbatim from FINDINGS)

Four artifacts, each of which would have produced a false result, caught
before the decisive run:

1. **Forced collision.** Nearest-listed matching on TruthfulQA's curated
   misconception set collapses the answer space (null 0.28), fabricating a
   "universal blind spot" that vanished under list-free matching.
   *Caught by:* re-keying convergence on the answer strings.
2. **Degenerate outputs from weak models** (twice — arithmetic, then code
   pre-fix: 86–96% error signatures, 4–10 distinct signatures). Too-weak
   models collapse the space and inflate the null. *Caught by:* inspecting
   the null (0.34, not ~0) and the distinct-signature count. The
   confound-free test requires models capable at the task.
3. **Function-name harness bug.** MBPP tests call a specific function
   name; not telling the model produced universal `NameError`s and a fake
   null. *Caught by:* the degeneracy diagnosis; fix moved pass rates
   2–10% → 10–42%.
4. **Sentinel collision.** "No answer produced" counted as agreement,
   inflating within-family convergence to a spurious 1.0. *Caught by:* the
   parse-rate `[0.0, 0.0, 1.0]` diagnostic; fixed by excluding the
   sentinel from both observed and null.

Two positive methodological results:
- **Free-form absolute convergence** reveals a universal blind spot that
  the within/cross statistic reads as zero (validated on synthetic).
- **Direction, not frequency:** decorrelating *which* answer a model gives
  when wrong matters; decorrelating error *timing* does nothing.

## 9. Conditional-independence null — the real H2 test (cache-only)

The permutation null answers "is the wrong-answer distribution
non-degenerate across problems?" — not "does pair/family identity add
correlation *beyond* the population's per-problem wrong-answer structure?"
The conditional-independence reanalysis (`conditional_independence_null.py`,
no new generations) adds that missing null.

- **Layer 1 (pairwise excess).** For a pair (i,j), over problems where both
  are wrong: baseline(i,j) = P(two *other* wrong models agree),
  leave-pair-out, ratio-of-sums; excess = observed − baseline. Aggregated
  as within/cross means with bootstrap CIs over pairs (reusing
  `run_openrouter._ci`). **cross-excess −0.024 [−0.052, +0.001],
  within-excess +0.026 [−0.013, +0.065] — both include 0 (Case A).**
- **Layer 2 (space concentration, pair-independent).** Per problem, over
  all in-band wrong models: Simpson agreement, distinct wrong signatures,
  effective # of wrong answers. **Median distinct = 1, median Simpson =
  0.60** — the wrong-answer space is tiny.
- **Robustness.** R2 (all-9, weak-inclusive reference) shows positive
  excess but within ≈ cross — a capability-homogeneity effect, not family.
  R3 (distinct ≥ 3, 12 problems) → excess ≈ 0. ERR-sensitivity (exclude
  all-`ERR`) → observed 0.56 → 0.36 but excess ≈ 0.
- **Sentinel handling (artifact #4).** Primary sentinel set = {TIMEOUT,
  IMPORTERR}; a two-sentinel collision never counts as agreement, in
  observed OR baseline (pinned by `test_ci_null.py`). Zero of the observed
  agreements are TIMEOUT/IMPORTERR — the 90 highest-weight ones are all
  `ERR` (identical exceptions, real behavior) — so the published 0.560/0.603
  are not artifact-#4-contaminated.

**Run it (fully offline, from `or_cache/`, no API):**

```
HF_HUB_OFFLINE=1 python conditional_independence_null.py   # -> ci_null_result.json
python -m pytest test_ci_null.py -q                        # 5 tests, green
```

The module reproduces the published within/cross/null/R from cache first
(±0.000) before computing anything new; a mismatch aborts. Interpretation:
Layer 1 answers "does pair/family identity add correlation beyond problem
structure" (no); neither layer separates genuine shared cognition from an
intrinsically small answer space — Layer 2 only bounds the latter.

## 10. Reproduction package

**In the repo (`main`, `research/correlated_failure/`):**
- Protocol/pre-registration: `PREREGISTRATION.md`.
- Metrics: `codebench.py` (code battery), `truthful.py` (TruthfulQA
  tightened), `rho_measure.py` (backends, free-form convergence).
- Run harness: `run_openrouter.py` (the decisive run), `run_groq.py`
  (earlier inconclusive run).
- Results: `decisive_result_openrouter.json` (all numbers above),
  `decisive_result.json` (Groq run).
- Write-up: `FINDINGS.md`; conditional-independence reanalysis (§9):
  `conditional_independence_null.py`, `FINDINGS_CI_NULL.md`,
  `ci_null_result.json`.
- Instrument validation: `test_codebench.py`, `test_truthful.py`,
  `test_rho_measure.py`, `test_sharpened.py`, `test_ci_null.py`, `test_*`
  — all green.
- Config/seeds are harness constants: `SEED=1, N_TQA=80, N_CODE=50,
  BAND=0.10`.

**NOT in the repo (git-ignored):** API keys (`.env`) and the raw
per-model generations (`or_cache/`, `groq_cache/`, …). Consequently the
raw generations are not currently in the package — regenerating them
needs an OpenRouter key and will vary slightly with provider drift,
though the seeded item selection is fixed and the analysis over any cached
generations is deterministic. To freeze a fully offline repro package,
the raw cached generations (which contain no secrets) can be committed so
the analysis reproduces without any API call.
