# Pre-registration — Route 2 decisive engineered-independence experiment

Written and committed BEFORE any model generation, so interpretation cannot
drift after seeing data. Git history is the timestamp (mirrors
../correlated_failure discipline). This file is the contract; it is not edited
after data is seen.

## Claim under test

**Route 2** = trust agent *agreement* as a truth-signal because errors are
independent. Prior work (../correlated_failure) showed model-FAMILY diversity
does NOT decorrelate errors, and that in a CONSTRAINED output space (~1 wrong
answer/problem) no mechanism can help because there is no room to disagree.

This experiment tests the stronger, unresolved question:

> **Does METHOD/PATH disjointness — forcing one model onto structurally
> different solution methods — produce genuine error-decorrelation that
> SURVIVES on HARD tasks in a LARGE output space?**

Engineered independence is a real primitive to build on only if it decorrelates
errors *where it is needed* (hard problems, room to disagree) AND makes
agreement a usable truth-signal there.

## Dataset & problem set (fixed)

MATH competition test split (EleutherAI/hendrycks_math mirror), all 7 subjects.
Seeded (numpy default_rng(1)) stratified sample: 40 EASY (levels 1-2) + 40 HARD
(levels 4-5) = 80 problems, from the id-sorted eligible pool (problems with a
brace-balanced \boxed reference). Same 80 problems for every model and method.
Levels drawn: {"1": 14, "2": 26, "4": 23, "5": 17}.

### The 80 problem IDs (contract)

EASY (40):
  algebra#1117, algebra#1133, algebra#269, algebra#428, algebra#431, algebra#477
  algebra#507, algebra#786, algebra#971, algebra#994, counting_and_probability#131, counting_and_probability#155
  counting_and_probability#272, counting_and_probability#286, counting_and_probability#388, geometry#179, geometry#278, geometry#342
  intermediate_algebra#1, intermediate_algebra#118, intermediate_algebra#161, intermediate_algebra#450, intermediate_algebra#473, intermediate_algebra#653
  intermediate_algebra#689, number_theory#360, prealgebra#377, prealgebra#418, prealgebra#557, prealgebra#644
  prealgebra#672, prealgebra#685, prealgebra#733, prealgebra#804, prealgebra#813, precalculus#203
  precalculus#272, precalculus#280, precalculus#425, precalculus#87

HARD (40):
  algebra#171, algebra#203, algebra#245, algebra#3, algebra#604, algebra#8
  algebra#890, algebra#919, counting_and_probability#22, counting_and_probability#459, geometry#182, geometry#247
  intermediate_algebra#184, intermediate_algebra#297, intermediate_algebra#389, intermediate_algebra#393, intermediate_algebra#512, intermediate_algebra#551
  intermediate_algebra#643, intermediate_algebra#701, intermediate_algebra#91, number_theory#236, number_theory#24, number_theory#282
  number_theory#84, prealgebra#119, prealgebra#140, prealgebra#25, prealgebra#307, prealgebra#335
  prealgebra#4, prealgebra#481, prealgebra#544, prealgebra#548, prealgebra#616, prealgebra#645
  prealgebra#684, prealgebra#726, precalculus#48, precalculus#8

## Roster (OpenRouter), 4 models / 4 families

- meta-llama/llama-3.1-70b-instruct  (llama)   — the FIXED model for M1 & M3
- google/gemma-2-27b-it              (gemma)
- mistralai/mistral-small-3.2-24b-instruct (mistral)
- microsoft/phi-4                    (phi)

## Methods (3)

- **COT**: direct chain-of-thought, final answer in \boxed{}.
- **CODE**: model writes a self-contained sympy program that prints
  \boxed{...}; executed via the imported codebench 5s-timeout subprocess
  executor; the printed boxed value is the answer.
- **DECOMP**: explicit numbered decomposition into subproblems, solve each,
  combine; final answer in \boxed{}.

Prompts are fixed (see route2_experiment.prompt_for) and are NEVER tuned after
seeing convergence. Extraction-failure fixes touch only the PARSER, never the
decision-relevant generation; per-method parse rate is disclosed.

## Mechanism levels (the "agents" whose pairwise same-wrong convergence we measure)

- **M1 SAME-MODEL-SAMPLES**: llama-3.1-70b, COT, K=4 independent samples at
  temperature 0.7 (seeds 1000..1003). Maximal-correlation baseline.
- **M2 CROSS-FAMILY**: the 4 models, COT, temperature 0. Same method, different
  families (replicates prior work; the weak decorrelator).
- **M3 CROSS-METHOD (PRIMARY, model-controlled)**: FIX llama-3.1-70b; its three
  method-runs {COT, CODE, DECOMP} (temp 0) are the three agents. The ONLY thing
  varying is the solution path — isolates method-disjointness from capability.
  The mixed model x method version is computed and reported separately (R1);
  the model-controlled M3 is PRIMARY.

## Answer canonicalization (fixed)

Two answers are "the same" iff sympy simplifies their difference to 0
(normalized-string fallback when sympy cannot parse). Because the estimator
compares signatures with string ==, answers are canonicalized PER PROBLEM by
equivalence-clustering under that relation. WRONG = canonical answer !=
canonical reference. A non-parse / no-boxed / crash / timeout is a NON-ANSWER
sentinel that NEVER counts as agreement (reuses the ../correlated_failure
is_non_answer guard). SIGNATURE = the canonical wrong answer.

## Strata (2 x 2 x mechanism)

- **D (difficulty)**: EASY vs HARD (by MATH level).
- **S (space size)**: CONSTRAINED (distinct_wrong_q <= 2) vs LARGE
  (distinct_wrong_q >= 5), assigned per problem from the MEASURED cardinality
  over the full 16-agent pool (12 deterministic model x method + 4 M1 samples).
  MID (3-4) is counted but excluded from the two strata. If the LARGE bin is
  under-populated even among HARD problems, that is a FIRST-CLASS finding
  (reasoning wrong-answers may be intrinsically concentrated), reported loudly.

## Two primary metrics (fixed)

- **(A) EXCESS** (mechanism-level): per mechanism x D x S cell, mean over pairs
  of (observed same-wrong convergence - leave-pair-out conditional-independence
  baseline), bootstrap CI over pairs. The baseline population is the 12
  deterministic model x method agents (leave the measured pair out). excess <= 0
  means errors are conditionally independent/anti-correlated (good for Route 2);
  excess > 0 means shared bias beyond problem structure (bad).
- **(B) AGREEMENT TRUST-LIFT** (decision-level, the payoff): within each cell,
  among problems where a pair gives the SAME answer, the fraction where that
  answer is CORRECT, MINUS the mean single-agent accuracy in that cell. Positive
  lift = agreement concentrates on truth = a usable truth-signal. Bootstrap CI.

## Capability band (fixed)

Capability = COT accuracy on the 80 problems (temp 0). Band = models within
0.10 of the top COT accuracy. Applied to the M2 cross-family aggregate and the
mixed model x method arm (so we measure family/method, not capability). M1 and
M3-model-controlled are single-model and unbanded by construction. All
accuracies reported.

## Decision rule / falsifier (computed in the LARGE-space stratum)

Let excess(M,D) and lift(M,D) be as above in HARD/EASY x LARGE. Define the
decorrelation contrast
    Delta(D) = excess(M1_same-model-samples, D) - excess(M3_cross-method, D)
(positive Delta = method-disjointness decorrelates errors relative to
same-model). Classify:

- **ROUTE 2 LIVE**: in HARD x LARGE, Delta(HARD) > 0 with 95% CI excluding 0
  AND lift(M3, HARD) > 0 with 95% CI excluding 0. -> engineered
  method-independence decorrelates where needed and agreement is a truth-signal
  on hard problems. Justifies building Route 2.
- **ROUTE 2 MIRAGE**: Delta(EASY) > 0 (CI excludes 0) but Delta(HARD) CI
  includes 0 or <= 0, OR lift positive on EASY but not HARD. -> independence
  works only where useless; do NOT build Route 2.
- **ROUTE 2 CLOSED**: Delta CI includes 0 in BOTH easy and hard. -> engineered
  independence unattainable even when forced; commit to Route 1.

Any single pair or single problem driving a cell -> report as inconclusive for
that cell, not as support.

## Point predictions (stated now, before data)

- same-model-samples (M1) excess ~ 0 or slightly positive, with HIGH absolute
  convergence.
- cross-method (M3) LOWER absolute convergence than M1.
- Open question: whether Delta(HARD) > 0 survives.
- Prior over outcomes: **35% LIVE / 40% MIRAGE / 25% CLOSED.**
- Also anticipated (to be reported regardless): the LARGE bin among HARD
  problems may be under-populated (concentrated attractor wrong-answers in
  reasoning), which is a distinct, more fundamental obstruction than the
  mechanism failing.

## Robustness variants (all reported)

- R1: M3 model-controlled (primary) vs M3 mixed model x method.
- R2: LARGE = distinct_wrong_q >= 5 explicitly (MID 3-4 excluded), to show the
  effect is not carried by borderline-space problems.
- R3: M3 with the CODE agent included vs excluded (code execution is a
  genuinely different error surface; is IT specifically what decorrelates?).
- R4: EASY x LARGE and HARD x CONSTRAINED cells (if populated) to separate the
  difficulty effect from the space-size effect.

## Determinism

SEED=1. Fixed seeded item selection. Greedy (temp 0) everywhere except M1
(temp 0.7, per-sample seeds 1000..1003, the sampling arm). Every generation
cached under route2_cache/ keyed by (model, method, problem_id, sample_idx);
all re-analysis is free and no call is ever repeated.

## What will NOT happen after this

Stop and write up the result — LIVE, MIRAGE, or CLOSED — including nulls and
honest limitations. No metric substitution, no rescope, no prompt/band tuning
after seeing convergence.
