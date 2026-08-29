# Pre-registration — Phase 7: the witness/localization test

Committed BEFORE any generation. Git history is the timestamp. Not edited after
data is seen. **NOT a Route 2 rescue** (terminal decision stands).

## Question

Phase 6B found ASYMMETRY-WEAK: verifying a bare (problem, answer) pair is
re-solving. But every working optimistic-verification system (PoW, rollup fraud
proofs, TrueBit) gets its economy from checking a **witness** and **localizing** the
dispute to a single step. Does that asymmetry exist for LLM reasoning?

## Data

Cached route2 MATH COT generations, 4 models × 80 problems, known ground truth.
**Confirmed: the cache retains the full COT reasoning text** (the witness), not just
the parsed answer. Traces are segmented into numbered steps by: split before
explicit step markers (`## Step N`, `Step N:`, `^N.`); if <2 markers, split on
blank-line paragraphs; else on sentence boundaries. Applied uniformly (lines are
grouped by step-header start). **Mean 10.3 steps/trace** (median 8, range 2–36).

## Conditions (paired on the SAME claimant answers as Phase 6B)

- **C0 NO-WITNESS** (reused from 6B, not regenerated): checker sees problem + answer.
- **C1 FULL-TRACE**: checker sees problem + numbered trace + final answer; returns
  `NONE` or the INDEX of the first invalid step + a one-line reason.
- **C2 PREFIX-ONLY** (localization): checker sees problem + steps 1..k only (no final
  answer), k = 1, 2, 3; asked "is the reasoning so far valid?" (VALID/INVALID).
- **C3 FABRICATED-TRACE** (fraud case): for a sample of items where the claimant was
  CORRECT, a different model fabricates a plausible trace concluding a wrong answer
  (target = a natural wrong answer another model gave, so the fraud target is
  grounded); a checker checks it under C1. Tests whether trace-checking survives a
  claimant who fabricates a supporting witness.

Checker = each of the 4 models; claimant ≠ checker (C1/C2), temp 0.

## Primary metrics (per checker, per condition)

TPR, FPR, LR = TPR/FPR, J, precision, item-bootstrap CIs, permutation null (FPR,
precision, LR reported beside every TPR/J).

- **THE (a)/(b) COMPETENCE SPLIT** (as 6B): (a) problems the checker SOLVED, (b)
  problems the checker FAILED. Report J in cell (b) for C1 and C2 with CIs and n.
- **THE PAIRED WITNESS EFFECT**: C1 − C0 difference in J, restricted to cell (b),
  paired over identical (checker, claimant, problem) triples. *This single number is
  the phase.*
- **LOCALIZATION ACCURACY**: when the checker names a first-invalid-step index and the
  answer IS wrong, how often does it match a hand-determined error location (sample
  ≥25 wrong traces; traces where the location can't be determined with certainty are
  EXCLUDED, not guessed; exclusion count reported).
- **ERROR-POSITION DISTRIBUTION**: histogram of hand-labelled error step index,
  normalized by trace length. Prediction (from round-3 CODE + 6A de-trapping):
  **front-loaded** (comprehension/setup, not late arithmetic).
- **COST ASYMMETRY**: mean output tokens for (i) generating a solution, (ii) C1
  full-trace check, (iii) C2 k=1 prefix check; report the ratios. An asymmetry claim
  requires BOTH higher-than-null detection AND materially lower cost.

## Decision rule

- **WITNESS-ASYMMETRY-LIVE**: cell-(b) J for C1 > 0.20 with CI excluding 0 for ≥2
  checkers, AND the paired C1−C0 witness effect in cell (b) is positive with CI
  excluding 0 → the certificate creates a real asymmetry; optimistic settlement has a
  foundation via trace-checking.
- **LOCALIZATION-LIVE** (weaker but valuable): cell-(b) J for C2 (k≤3 prefix) > 0.20
  with CI excluding 0 → errors are catchable EARLY without the full solution; bisection
  is viable even if full-trace checking is not.
- **WITNESS-DEAD**: neither clears → ASYMMETRY-WEAK stands unscoped; checking LLM
  reasoning requires re-solving even with the witness — a hard architectural
  constraint, reported as the headline, not softened.

## Point predictions (stated now)

Error positions front-loaded (median normalized index < 0.4); C1 cell-(b) J ≈
0.15–0.40; C2 k=1 catches most comprehension errors; **C3 substantially WEAKER than
C1** (a fabricated witness is designed to look valid) — if C3 collapses, trace-checking
works against honest error but NOT strategic fraud (the mirror of Channel B's
B-INSINCERE-ONLY), stated as such. Prior: **40% WITNESS-LIVE / 30% LOCALIZATION-ONLY /
30% WITNESS-DEAD.** Any single checker/problem driving a cell → inconclusive.

## Honesty

C1/C2/C3 depend on CHECKER honesty (a colluding checker returns NONE); only
claimant-gameability is ruled out (the claimant does not control the checker). Report
the cost ratio next to every detection claim. WITNESS-DEAD is a success and the most
consequential outcome. SEED=1, temp 0, cached, no call repeated.
