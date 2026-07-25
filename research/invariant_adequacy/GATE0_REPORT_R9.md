# Route 9 — GATE 0 report: PASS

All three sub-gates pass. Execution proceeded.

## 0a — preregistration precedes data: **PASS**

`PREREGISTRATION_R9.md` committed at **`bd61cbd`**
(`research(route9): preregister adversarial adequacy of inductive safety
invariants (pre-build, pre-generation)`).

That commit contains **only** the preregistration — no environment, no guards, no
adversary, no result artifact. Every subsequent artifact is committed strictly
after it:

| artifact | commit | after `bd61cbd`? |
|---|---|---|
| `environment.py`, `guards.py`, `test_invariants.py` | `76d4546` | yes |
| `_scripted.json`, `r9_result.json` (scripted arms) | `d0c7792` | yes |
| `_redteam.json`, `rt_cache/` (LLM arm) | `61fcfba` | yes |

The design, the two harm measures, the 40-task suite composition, the guard
parameters (β = 10, w = 5, B = 500, 2 × 25 authorized egress), the horizons, the
decision rule, and the point predictions were all on record before any data
existed. `PREREGISTRATION_R9.md` has not been edited since; the two implementation
corrections are disclosed in `FINDINGS_R9.md` §6 instead.

## 0b — harm defined independently of every invariant: **PASS**

Both harm measures are defined in `PREREGISTRATION_R9.md` §0b and implemented in
`environment.py` as pure functions of environment state and the environment's own
event log. `environment.py` imports nothing from `guards`.

Pinned by test, not by assertion in prose:

- `test_environment_does_not_import_guards`
- `test_harm_functions_read_no_guard_state` — source inspection over `h_drain`,
  `h_irrev`, `recoverable`, `principal_total`, `available_contents`, rejecting any
  reference to guard concepts (`admits`, `invariant`, `estimated_`, `BUDGET`,
  `BETA`, `consumed`, `auth`)
- `test_harm_is_unchanged_by_which_guard_ran` — the same trajectory scores
  identically under all nine guard configurations

Guard-side arithmetic is named `estimated_drain` / `estimated_irrev` throughout,
deliberately distinct from the environment's `h_drain` / `h_irrev`. The gap
between them is what an adequacy failure *is*; conflating them would have erased
the study's central result (see `FINDINGS_R9.md` §2, where G2's counter reads 0.0
while the environment measures 175000).

This is the Phase-1 circularity artifact — the base↔perturbed answer-change metric
definitionally tied to wrongness — guarded against in its new form: "harm =
violated the invariant" would have made adequacy tautological.

## 0c — credit gate: **PASS**

| | |
|---|---|
| balance at gate | **$3.357** (OpenRouter: 5.000 granted − 1.6425 used) |
| per-arm estimate (A3, the only paid arm) | **≈$0.20** — 3 models × 5 guards, ~5k-token white-box prompt + ~1.4k completion, with retry headroom |
| requirement | balance ≥ 2 × estimate = $0.40 |
| margin | **8.4×** |

**PASS.** Actual spend on A3 came in at roughly **$0.05** (15 calls, all cached to
`rt_cache/`).

Everything else in Route 9 — the environment, all nine guard configurations, both
scripted adversaries, all permissiveness measurement, all checkability
measurement, the inductiveness audit, and the Gyza self-audit — is **deterministic
simulation with zero model calls**.

## Test gate (preregistration §10)

`test_invariants.py`: **31 passed**, including the negative control
(`test_broken_guard_fails_per_action_enforcement`), which must FAIL the per-action
enforcement check for the F1 audit to have any power. It does.
