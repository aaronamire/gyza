# Pre-registration — the decisive shared-blind-spot run

Written and committed BEFORE running the capability-matched experiment, so
interpretation cannot drift after seeing data. Git history is the timestamp.

## Claim under test

**H2 (constructive): diversity decorrelates failure.** Mixing model
families reduces shared blind spots, so **cross-family** failure
convergence is materially **lower** than **within-family** convergence.

Its negation is the dangerous case for Gyza: a **universal blind spot** —
cross ≈ within, both well above chance — where no amount of pool diversity
helps.

## Metrics (all keyed on the models' own outputs, list-free)

- **PRIMARY: code-battery same-bug convergence** (`codebench.py`). Among
  problems where two models both produce a failing program, the rate at
  which their behavioral signatures (outputs on the test inputs) are
  identical, vs. a permutation null. Confound-free: no curated list, no
  topic similarity, ~infinite wrong-program space.
- **SECONDARY: tightened TruthfulQA**, verbatim floor and semantic ceiling
  reported **separately** (`tightened_convergence`).

If the two batteries disagree, **the code battery is authoritative.**

## Design requirements (fixed in advance)

1. **≥3 within-family pairs across ≥2 families, and ≥6 cross-family pairs.**
   (E.g. 3 families × 2 models ⇒ 3 within + 12 cross.)
2. **Capability matching, verified explicitly.** Measure each model's task
   accuracy first; only models within a **±10-percentage-point** accuracy
   band are compared. Models outside the band are reported but excluded
   from the within/cross comparison, so we measure *family*, not capability.
3. **Per-pair results reported**, not just aggregates — a single outlier
   pair driving the effect must be visible.
4. Deterministic (seed fixed), same items/problems for all models.

## Predicted results (point predictions, stated now)

- Code battery: same-bug convergence **above** the permutation null for
  most pairs (models DO share some bugs) — rough guess within-family
  ~0.10–0.30, cross-family ~0.03–0.15, null ~0.01.
- **Predicted within/cross ratio ≈ 1.5–3×** (within > cross) on both the
  code battery and the verbatim TruthfulQA floor, IF H2 holds.

## Decision rule (falsifier, fixed now)

Let R = mean within-family convergence ÷ mean cross-family convergence, on
the code battery (primary), among capability-matched models.

- **R ≥ 1.5 and cross-family convergence > null** → H2 supported: diversity
  decorrelates failure (partially); mixing families helps but shared bugs
  remain.
- **0.8 ≤ R ≤ 1.2 and both within and cross > null** → **H2 FALSIFIED**:
  universal blind spot. Diversity does NOT decorrelate failure — the
  dangerous regime. (This is the specific result that would kill the
  "diversity invariant helps" story and must be reported as such.)
- **Both within and cross ≈ null (≤ ~2× null)** → no shared-blind-spot
  phenomenon at this scale: models fail near-independently. A real null;
  report it plainly.

Any per-pair pattern where one outlier pair drives R is reported as
inconclusive, not as support.

## What I will NOT do after this

Stop and write up the result — including nulls and the honest limitations.
No new methodology thread.
