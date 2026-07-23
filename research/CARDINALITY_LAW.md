# The cardinality law: agreement informativeness is governed by the size of the wrong-answer space

A cross-study regularity from the Gyza correlated-failure / Route-2 program. It
is a finding independent of Gyza's architecture, and it is what the two failed
attempts to test "Route 2" (trusting agent agreement as a truth-signal) actually
produced. It rests on the conditional-independence null
(`research/METHOD_CONDITIONAL_INDEPENDENCE_NULL.md`), not on surface convergence
rates.

## The two regimes

Two studies, same estimator, same discipline, opposite structure:

| | **MBPP code battery** (round 1) | **MATH** (round 2) |
|---|---|---|
| answer space | **constrained** | **open** |
| median distinct wrong answers / problem | ≈ **1** | ≥5 on only 3/80; HARD median 2 |
| Simpson agreement among wrong models | ≈ **0.60** (converge) | ≈ **0.0** (scatter) |
| co-failure density | **dense** (many models wrong together) | **sparse** (mean ≈2.0 wrong / ~10 agents; HARD 2.7) |
| raw convergence | 0.56 | low |
| **excess over conditional-independence null** | **≈ 0** (space-driven) | **≈ 0** (few, diverse errors) |
| what "agreement" means | everyone lands on the one available wrong answer | agreement is rare and mostly on the truth |

The two studies bracket the phenomenon from opposite sides, and **neither**
populates the regime Route 2 needs (dense co-failure in an open space). But
together they establish a regularity about what agreement is *worth*.

## The law

> **The informativeness of inter-agent agreement is governed by the cardinality
> of the wrong-answer space.**

- **Constrained space (few possible wrong answers).** Agreement is **near
  worthless as a truth-signal**. When there is essentially one wrong answer to
  give, two wrong models agree *by construction*, not because they independently
  arrived at the truth. The conditional-independence null makes this precise: the
  MBPP convergence of 0.56 had **≈0 excess** over the per-problem baseline, and
  collapsed to **0.17** once restricted to problems with ≥3 distinct wrong
  answers. Agreement on a constrained-output decision carries almost no
  information about correctness — it is forced by the space.

- **Open space with rare co-failure (many possible wrong answers, capable models
  that seldom err together).** Agreement is **informative on its own** — because
  a specific wrong answer rarely gets a second vote, agreement concentrates on
  the truth. On MATH, the *corrected* trust-lift (comparator restricted to the
  agreed-on items, removing the selection confound; see below) is **positive but
  modest**: cross-method +0.115 [0.067, 0.146] on hard problems, model×method
  +0.318 [0.292, 0.341]. The *raw* precision when agents agree is high (≈0.88
  vs 0.48 base rate), but most of that gap was a selection confound — agreement
  lands on easy items. The honest signal is the corrected lift: real, positive,
  and smaller than the raw gap.

## The engineering rule it implies

- **Trust agreement on open-output tasks.** Where the answer space is large and
  capable agents rarely co-fail, "answer only when they agree" is a sound,
  cheap policy — and it does **not** require engineered diversity; plain
  agreement (even across methods of a single model) already concentrates on
  truth.
- **Never trust agreement on constrained-output tasks.** Where the answer space
  is small, agreement is uninformative regardless of how diverse the pool is —
  family diversity provides no decorrelation there (the round-1 result). Such
  decisions require an **external verification / reality anchor** (execution, a
  solver, a bonded-market ground-truth resolution), not a bigger or more diverse
  committee.
- **Corollary for Gyza.** The settlement-primary + sparse-ground-truth-resolution
  backstop is the load-bearing mechanism precisely for the constrained-output
  case; pool diversity is not a substitute for it there.

## Why this rests on the conditional-independence null (not the surface comparison)

The naive reading of round 1 was "capable models share a universal blind spot
(~13× chance)." That reading is what the permutation null produces, and it is
wrong: the conditional-independence reanalysis showed the convergence was
**problem-structural** (excess ≈ 0), and the cardinality restriction
(0.56 → 0.17 at distinct_wrong ≥ 3) showed it was **carried entirely by
tiny-space problems**. Without that reanalysis, one would conclude "agreement is
worthless because models share cognition"; *with* it, the correct conclusion is
"agreement is worthless *because the space is small*, and would be informative
if the space were open" — which round 2 then confirmed from the other side.
The law is a statement about **space cardinality**, and it is the CI-null that
licenses attributing the constrained-regime convergence to the space rather than
to the models. See `research/METHOD_CONDITIONAL_INDEPENDENCE_NULL.md`.

## Honest limits

- **Two points, not a theorem.** Two benchmarks (MBPP, MATH), one capability tier
  (~24–70B open models), both English, both capability-banded. This is a
  regularity across two regimes, not a proof; the functional form between them is
  unmeasured (the dense-open regime is exactly the gap).
- **Corrected, not raw, lift.** The MATH "agreement is informative" claim uses the
  confound-corrected trust-lift (comparator restricted to agreed items). The
  earlier raw +0.40 was substantially a selection artifact; and for a pure
  2-agent pair the corrected lift is definitionally ≈0 (the comparator contains
  the pair), so the positive corrected signal comes from 3+-agent mechanisms.
- **Coverage, not just precision.** "Trust agreement" answers only the subset
  where agents agree; the value is precision-on-that-subset plus the ability to
  abstain elsewhere, not a uniform accuracy gain.
- **Round 2 was 38% data-incomplete** (OpenRouter 402 lost the same-model-samples
  arm); the open-space numbers are from the intact ~10 agents. Direction robust,
  exact magnitudes provisional.

---

*Sources: `research/correlated_failure/FINDINGS.md`, `FINDINGS_CI_NULL.md`
(round 1, constrained); `research/route2_independence/FINDINGS_ROUTE2.md`,
`route2_result.json` (round 2, open); corrected trust-lift in
`research/route3_attractor/phase_a_corrections.py`. Method:
`research/METHOD_CONDITIONAL_INDEPENDENCE_NULL.md`.*
