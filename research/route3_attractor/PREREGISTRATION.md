# Pre-registration — Route 3 adversarial attractor experiment

Committed BEFORE any Phase C generation. Git history is the timestamp. This file
is the contract; it is not edited after data is seen.

## Claim under test

Rounds 1 (MBPP: constrained answer space, dense co-failure) and 2 (MATH: open
answer space, sparse scattered failure) both failed to populate the regime
Route 2 needs — **dense shared error in an open answer space**. This round
**induces** that regime by construction (perturbed items with a strong
memorized/salient wrong answer, the *attractor*), then tests whether engineered
**method-disjointness** breaks the shared error.

> **Route 2 is LIVE only if forcing one model onto structurally different
> PURE-REASONING paths (COT vs DECOMP, no code oracle) makes it escape a shared
> attractor that same-model sampling does not — i.e. manufactured independence,
> not verification.**

The attractor is a **constructed fixture, not a finding**: that models share it
is induced deliberately. The only finding is whether method-disjointness breaks
it.

## Items (the fixture)

`items.json`, **sha256[:16] = e0d9fedd108aff4f**, N = 80, seed 1.
Composition: i_classic 20, iii_substitution 20, ii_noop 40; control modes
memorized 24, competence 56. Every true answer is machine-computed or
hand-verified; items with uncertain ground truth were excluded, not guessed.

Each item records: `item_id`, `category`, `control_mode`, `perturbed_prompt`,
`true_answer` (canonical), `attractor_answer` (the answer to the unperturbed
original — memorized/salient, now WRONG), `original_prompt`, `note`.

**Two control modes** (the rigorous reading of B3):
- **MEMORIZED** (i_classic conceptual, iii_substitution): the attractor IS the
  correct answer to the famous ORIGINAL. The B3 control (original_prompt) must
  elicit the ATTRACTOR; the perturbation moves the true answer away.
- **COMPETENCE** (ii_noop, misreading traps): an irrelevant/misdirecting clause
  leaves the true answer unchanged; the attractor wrongly incorporates the extra
  number. The B3 control is the clause-free BASE and must elicit the TRUE answer
  (models can solve it), so a perturbed failure is attractor-induced.

## Roster (OpenRouter), 4 models / 4 families

meta-llama/llama-3.1-70b-instruct (llama, the FIXED model for M1 & M3),
google/gemma-2-27b-it (gemma), mistralai/mistral-small-3.2-24b-instruct
(mistral), microsoft/phi-4 (phi).

## Methods (3), identical prompt-per-method across models

- **COT** — direct step-by-step, answer in \boxed{}.
- **DECOMP** — explicit numbered subproblem decomposition, then combine; answer
  in \boxed{}. No code execution.
- **CODE** — self-contained Python (sympy/fractions/simulation) that COMPUTES
  the answer and prints \boxed{...}; executed in the reused 5s-timeout
  subprocess; crash / no parseable boxed value = NON-ANSWER (never counts as
  agreement).

Prompts are fixed (route3_experiment.method_prompt) and never tuned after data.
Extraction fixes touch only the PARSER; per-method parse rate is disclosed.

## Mechanism arms

- **M1 same-model-samples** (maximal-correlation baseline): llama COT, K=4
  samples at temp 0.7 (seeds 1000..1003).
- **M2 cross-family**: 4 models, COT, temp 0.
- **M3 cross-method, MODEL-CONTROLLED** (primary Route 2 arm): llama's three
  method-runs {COT, DECOMP, CODE}, temp 0.
- **M3-mixed**: model×method, reported separately.

Generation order (secures the comparator first, unlike round 2): **M1 → controls
→ M3 model-controlled → M2/rest of grid**. Cache keyed
(model, method, item_id, sample_idx); `__ERR__` cells are regenerable.

## Answer canonicalization + attractor detection

Two answers are the same iff sympy simplifies their difference to 0
(normalized-string fallback), applied by per-item equivalence-clustering (reused
from route2). WRONG = token ≠ true token; ATTRACTOR-HIT = token = attractor
token; a non-answer (crash/timeout/unparseable) never counts as agreement.

## GATE B — manipulation check (HARD stopping gate, computed before any Route 2 metric)

On control-valid items (an item is control-valid iff ≥ **2 of 4** models produce
the control-expected answer on the original/base):
- **attractor hit rate** per agent; **density** = mean wrong agents per item (of
  the 12 deterministic model×method agents); **attractor concentration** =
  among wrong agents, fraction giving the attractor (median across items);
  space-cardinality table as in round 2.

**REGIME-VALID iff:** ≥ **25** control-valid items have ≥ **3** agents hitting
the attractor **AND** median attractor concentration ≥ **0.5** **AND** mean
wrong-agents-per-item ≥ **3.0**.
- If REGIME-VALID → Phase D.
- If NOT → **ROUTE 2 UNFALSIFIABLE-IN-PRACTICE** — a PRE-COMMITTED TERMINAL
  outcome (see below). No round 4.

## ADDENDUM 2 corrections (baked into the metrics — the Phase-A trust-lift
finding exposed that the earlier design was unsatisfiable)

- **C1 HELD-OUT trust-lift.** For any 2-agent pair the within-mechanism
  restricted comparator equals the pair's own precision (on agreed items both
  members gave the agreed answer), so its lift is 0 *by construction*. The
  trust-lift for a pair is therefore measured against **HELD-OUT agents not in
  the pair**: for the primary COT×DECOMP (llama) pair the held-out set is **the
  other three models' COT runs + the four M1 samples** (7 agents). Report
  accuracy vs each held-out agent and the mean; lift = precision-on-agreed −
  mean held-out accuracy on those items. (Same leave-pair-out logic as the
  conditional-independence null, applied to a different quantity.)
- **C2 ITEM resampling.** The primary signal is a **single pair**, where an
  over-pairs CI does not exist. All primary metrics (excess, held-out lift,
  precision) bootstrap over **ITEMS**; over-pairs CIs are reported only where ≥3
  pairs exist, and every CI is labeled with its resampling unit. A 3-point
  over-pairs interval is never presented as a significance bound.
- **C3 McNEMAR.** DECOMP-vs-COT attractor escape is paired binary data; the
  primary test is **McNemar's exact test on discordant pairs** (report the
  discordant counts and exact p), with an item-level bootstrap on the rate
  difference as secondary.

## Phase D metrics (on attractor items = control-valid items with ≥3 attractor hits)

- **EXCESS** per mechanism (reused conditional-independence estimator; baseline
  population = the 12 deterministic model×method agents, leave-pair-out).
- **ATTRACTOR ESCAPE RATE** per method (llama COT/DECOMP/CODE) = fraction of
  attractor items where the method does NOT give the attractor.
- **HELD-OUT TRUST-LIFT** (C1), item-bootstrap (C2).
- **Δ = excess(M1) − excess(M3 model-controlled)** (positive = method-
  disjointness decorrelates relative to same-model sampling).

## D2 — the Route 1 / Route 2 discriminator (preregistered so it can't be read post-hoc)

CODE breaks attractors by EXECUTING a computation — a cheap oracle, i.e. Route 1
(verification), NOT Route 2 (manufactured independence). Therefore the **PRIMARY
Route 2 signal is the COT×DECOMP pair ONLY** (two pure-reasoning paths, no
oracle). If the only method that escapes is CODE, the conclusion is
"verification works" (Route 1), not "Route 2 is live." Escape rate and pairwise
excess are reported separately for COT×DECOMP (primary), COT×CODE, DECOMP×CODE,
and the all-three aggregate.

## D3 — decision rule (corrected; computed on attractor items)

- **ROUTE 2 LIVE:** COT×DECOMP excess ≤ 0 (or CI includes 0) **AND** DECOMP
  escape exceeds COT with McNemar exact p < 0.05 (discordant favouring DECOMP)
  **AND** held-out trust-lift for COT×DECOMP > 0 with item-bootstrap CI excluding
  0. → pure-reasoning path diversity breaks the correlated blind spot.
- **ROUTE 2 MIRAGE:** escape/decorrelation appears only when CODE is included;
  COT×DECOMP shows no decorrelation (McNemar n.s. and/or held-out lift CI
  includes 0), while CODE escapes substantially more. → what works is
  verification, not independence. Commit to Route 1.
- **ROUTE 2 CLOSED:** COT, DECOMP, and same-model samples hit the attractor at
  statistically indistinguishable rates (|escape_DECOMP − escape_COT| < 0.10 and
  McNemar n.s.). → forcing different reasoning paths does not break the shared
  blind spot. Commit to Route 1 permanently.
- Any single item or single pair driving a cell → that cell is reported
  INCONCLUSIVE, not support.

### Point predictions (stated now)

CODE escapes attractors substantially more than COT or DECOMP; the open question
is whether DECOMP escapes more than COT. Prior: **30% LIVE / 45% MIRAGE / 25%
CLOSED** (with a real chance GATE B fails → UNFALSIFIABLE-IN-PRACTICE). Report
which fired.

## Terminal stopping rule (pre-committed)

If GATE B is not met, the decision is **ROUTE 2 UNFALSIFIABLE-IN-PRACTICE**:
three successive designs — natural-constrained (MBPP), natural-open (MATH), and
deliberately adversarial attractor-induced — failed to produce a testable
dense-open-error regime, so the regime is rare enough in practice that engineered
independence cannot be validated, and **Route 1 (external verification anchor) is
the committed architecture**. This is a SUCCESS of the program (it saves a year),
reported plainly. **No round 4 is proposed.**

## Determinism

SEED = 1. Greedy (temp 0) everywhere except M1 (temp 0.7, per-sample seeds
1000..1003). Every generation cached; re-analysis is free; no call repeated.
