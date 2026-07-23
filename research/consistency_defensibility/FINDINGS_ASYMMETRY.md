# Findings — Phase 6B: the verification/generation asymmetry

Decision first, then the (a)/(b) split, per-checker, cross-vs-self,
weak-checks-strong, limits. **NOT a Route 2 rescue** (terminal decision stands).

## DECISION — ASYMMETRY-WEAK: verification ≈ re-solving (no genuine asymmetry)

Cross-model verification (checker C checks claimant M's cached MATH answer,
VALID/INVALID, no oracle) works **only where the checker could itself solve the
problem**:

| cell | n | J [CI] | FPR | LR | reading |
|---|---|---|---|---|---|
| **(a) checker SOLVED the problem** | 414 | **0.694 [0.515, 0.850]** | 0.039 | 18.8 | strong |
| **(b) checker FAILED the problem** | 71 | **−0.133 [−0.337, 0.065]** | 0.333 | 0.6 | **null / collapses** |

**No checker** has cell-(b) J > 0.20 with CI excluding 0 (llama −0.17, gemma +0.01,
mistral +0.13 [0, 0.43], phi +0.11 [0, 0.38]). Per the preregistered rule this is
**ASYMMETRY-WEAK**: checking is *not* easier than solving — on problems the checker
cannot solve, verification is worthless (J≈0, FPR 0.33). Cross-model verification
is essentially *"the checker re-solves and compares"* — strong within its own
competence, but providing **no economy**: you cannot use a cheap/weak verifier to
audit a producer on problems beyond the verifier's ability. **Optimistic settlement
premised on "checking is cheaper than solving" lacks a foundation on this task.**
(The more consequential outcome, reported plainly, not softened.)

Pooled cross-verify (all cells): n=630, TPR 0.45, FPR 0.068, LR 6.5, J 0.378,
precision 0.56. Verdict parse rate 630/678 (48 unparsed, 7%).

## Cross vs self — does cross-model recover the self-validators?

| claimant | self-inversion J (LR) | cross-model J (LR) |
|---|---|---|
| gemma-2 (self-validates poorly) | 0.433 (3.9) | **0.587 (35.6)** — cross is much cleaner |
| llama-3.1 | 0.408 (20.6) | 0.393 (5.7) — similar, higher FPR |
| **mistral-3.2** (self J=0) | 0.000 (—) | 0.055 (2.5) — **barely recovered** |
| **phi-4** (self J=0) | 0.000 (—) | 0.051 (1.4) — **barely recovered** |

Cross-model checking **cleanly catches gemma's errors** (LR 35.6 vs self 3.9 — gemma
is error-prone but on checker-solvable problems). It **does NOT recover mistral or
phi** as claimants (cross J≈0.05): their errors sit on genuinely hard problems that
the checkers also cannot solve — the same cell-(b) collapse. So cross-model fixes
the *gameability* of self-inversion (a claimant can't suppress an external checker)
but not the *competence* bound.

## Weak-checks-strong (the economically important case)

| checker → claimant | n | J | FPR | LR | precision |
|---|---|---|---|---|---|
| phi-4 → gemma-2 | 58 | **0.642** | 0.025 | 26.7 | 0.92 |
| llama → gemma-2 | 58 | **0.586** | 0.025 | 24.4 | 0.92 |
| mistral → gemma-2 | 55 | 0.529 | 0.000 | ∞ | 1.00 |
| gemma → llama | 60 | 0.412 | 0.224 | 2.8 | 0.39 |
| phi-4 → llama | 53 | 0.379 | 0.021 | 19.2 | 0.67 |
| gemma → phi-4 | 59 | 0.179 | 0.250 | 1.7 | 0.19 |
| **llama → phi-4** | 58 | **−0.057** | 0.057 | 0.0 | 0.00 |
| **mistral → phi-4** | 56 | **−0.040** | 0.040 | 0.0 | 0.00 |

Anyone checking **gemma** (errors on solvable problems) does well (J 0.53–0.64, LR
24–∞). **Nobody catches phi-4's or mistral's errors** (J ≤ 0) — those errors are on
hard problems no checker can solve. A *weak* checker auditing a *strong* producer
(gemma→llama) is noisy (FPR 0.22). So the direction that matters — **cheap verifier
auditing expensive producer on hard problems — does not work.** What works is a
*capable* checker auditing errors that fall within its competence.

## Adversarial robustness (stated, not simulated)

Cross-model verification does **not** depend on claimant honesty — the claimant
cannot control the checker, so it is a genuine (non-gameable-by-the-claimant) fraud
signal, unlike A2 self-inversion. It **does** depend on **checker honesty and
competence**: a lazy/colluding always-VALID checker has J=0, and an incompetent
checker collapses (cell b). So cheap oracle-free fraud proofs exist **only** for
problems within an honest checker's own ability.

## Correction to the "A2 is slashing-grade" claim (required)

**A2 self-inversion is GAMEABLE**: "always answer VALID" is optimal for any bonded
agent, and mistral & phi-4 already exhibit it non-adversarially (self J=0). So A2
self-inversion is an **honest-agent self-audit tool, NOT a fraud proof / slashing
mechanism.** Only **cross-model** verification can support slashing — and, per this
phase, only **within the checker's competence** (cell a: J 0.69, LR 18.8,
non-gameable-by-claimant), not on problems the checker cannot solve.

## Limits

- Cell (b) is modest n (71 pooled; 9–39 per checker) — but the pooled CI includes 0
  and no checker clears the bar, and the mechanism (checker also fails the hard
  problem) is clear.
- Verdict parse rate 93%; one generation failure of 678.
- One task (competition MATH), four models; MATH may have an unusually tight
  solve-verify coupling vs, e.g., code (where unit tests make verification cheap).
  The claim is scoped to this task.

## Implied DIFF to FINDINGS_SYNTHESIS.md (NOT applied)

```diff
@@ what it catches / slashing @@
- For slashing use A2 inversion (LR 36.8, FPR 0.015).
+ A2 SELF-inversion is GAMEABLE (always-VALID optimal; mistral/phi-4 exhibit it) -> an
+ honest-agent self-audit, NOT slashing. CROSS-model verification is the non-gameable
+ form but is COMPETENCE-BOUNDED: strong where the checker can itself solve (cell a J=0.69,
+ LR 18.8) and NULL where it cannot (cell b J=-0.13). So there is NO verification/generation
+ asymmetry on MATH -- checking ~ re-solving. Cheap oracle-free fraud proofs exist only for
+ problems within an honest checker's competence; optimistic settlement has no free-lunch
+ foundation on this task. Ground-truth resolution (Route 1) remains necessary for
+ beyond-checker-competence claims.
```
