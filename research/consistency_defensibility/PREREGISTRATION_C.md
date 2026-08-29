# Pre-registration — Phase 6B: the verification/generation asymmetry

Committed BEFORE any 6B generation. Git history is the timestamp. Not edited after
data is seen. **NOT a Route 2 rescue** (terminal decision stands).

## Motivation (the crux for optimistic settlement)

A2 self-inversion is **gameable**: mistral and phi-4 show FPR=0/J=0 because they
never flag their own answers, and "always answer VALID" is optimal for any bonded
agent. So self-inversion is an honest-agent *self-audit* tool, **not a fraud
proof**. The deployable form is **cross-model verification**. The foundational
question: **is CHECKING cheaper/more reliable than SOLVING?** If a checker catches
errors on problems it cannot itself solve, the asymmetry is real and cheap
oracle-free fraud proofs exist. If checking requires re-solving, there is no
economy.

## Data

Cached route2 MATH generations: 4 models × COT × 80 competition-math problems,
natural errors, known ground truth. Answer-bearing per claimant: llama 61, gemma
64, mistral 41, phi-4 60. SOLVE accuracy is already cached (not regenerated).

## Generations (the only ones permitted)

For every ordered pair (checker C, claimant M), **C ≠ M**, and every problem where
M produced a parseable answer: give C the problem statement + M's candidate answer,
ask VALID/INVALID + the specific violated condition. Temp 0. Cache by
(checker, claimant, problem_id). C = M (self-inversion, Phase 5) is the control for
direct comparability. ~678 cross-model calls.

## Primary metrics, per checker (pooled over claimants)

- **VERIFY**: TPR, FPR, LR = TPR/FPR, J = TPR−FPR, precision (ground truth = M's
  answer wrong), item-bootstrap CIs, permutation null. FPR, firing, precision, LR
  reported beside every TPR/J.
- **SOLVE**: C's own cached accuracy on the same problems.
- **THE ASYMMETRY, split by whether the checker can solve the problem:**
  - **(a)** problems C solved correctly → verify J.
  - **(b)** problems C failed to solve → verify J.
  Cell **(b)** is the crux: catching errors on problems the checker cannot solve
  demonstrates verification is strictly easier than generation. If J in (b) ≈ 0,
  verification collapses into re-solving — no asymmetry (the more consequential
  finding, reported plainly).
- **CROSS vs SELF**: paired difference in J and FPR (same claimant set). Does
  cross-model checking recover the self-validating models (mistral, phi-4 as
  CLAIMANTS)?
- **WEAK-CHECKS-STRONG**: J for (weak checker, strong claimant) pairs specifically
  (a cheap verifier auditing an expensive producer).

## Adversarial robustness (stated, not simulated)

A cross-model checker cannot be gamed by the claimant (the claimant does not
control the checker), unlike A2 self-inversion. Results are labelled by whether
they depend on checker honesty (they do — a colluding/lazy checker that always says
VALID has J=0) vs claimant honesty (they do not).

## Decision rule

- **ASYMMETRY-LIVE**: verify J in cell (b) > 0.20 with CI excluding 0 for **≥2
  checkers** → checking is genuinely easier than solving; cheap oracle-free fraud
  proofs are viable; optimistic settlement has a foundation.
- **ASYMMETRY-WEAK**: verify J positive only in cell (a) → checking works only where
  the checker could have solved it; verification ≈ re-solving; economy limited to
  reuse, not asymmetry.
- **ASYMMETRY-DEAD**: verify J CI includes 0 in both cells for most checkers →
  cross-model verification is not a usable signal on this task.

## Point predictions (stated now)

Cross-model FPR > self-inversion FPR (a checker is less deferential to someone
else's answer); cell (a) J ≈ 0.3–0.6; cell (b) J ≈ 0.1–0.3 (the open question);
weak-checks-strong J positive but attenuated. Prior: **40% LIVE / 40% WEAK /
20% DEAD.** Any single model or single problem driving a cell → inconclusive.

## Determinism

SEED = 1, temp 0. Every generation cached; no call repeated.
