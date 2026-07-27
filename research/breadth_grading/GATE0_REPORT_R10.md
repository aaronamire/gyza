# Route 10 — GATE 0 report: PASS

All four sub-gates pass. Execution proceeded.

## 0a — preregistration precedes every result: **PASS**

`PREREGISTRATION_R10.md` committed at **`2708379`**; it contains only the
preregistration. `PREREGISTRATION_R10_AMENDMENT.md` committed at **`a880f2c`**,
also before any code that produces a result — it declares the second `H_lost`
variant and fixes which one the decision rules read.

| artifact | commit | after `2708379`? |
|---|---|---|
| `HARM_MODEL_DRAFT.md`, amendment | `a880f2c` | yes |
| `env_breadth.py`, `guards_graded.py`, `agents.py`, `test_breadth.py`, `_b.json` | `df6dbd6` | yes |
| `_c.json`, `_d.json`, `r10_result.json`, write-ups | this commit | yes |

`PREREGISTRATION_R10.md` has **not** been edited. The one design refinement is in
the separate amendment, with its reason, before data.

## 0b — HARM INDEPENDENCE: **PASS**

`env_breadth.py` imports nothing from any guard module. Every harm measure —
`h_drain`, `h_irrev`, `h_lost`, `lost_by_class`, `asset_classes`,
`principal_total` — is a pure function of environment state. Guard-side
arithmetic is named `estimated_drain`.

Pinned by three tests: `test_environment_imports_no_guard_module`,
`test_harm_functions_read_no_guard_state` (source inspection over all six),
`test_same_trajectory_scores_identically_under_all_guards` (six guard
configurations, identical scores).

The **permitted** direction is used deliberately: `G5` calls the environment's own
`h_lost`. R12 Part C established that a guard invoking the same accounting the
harm measure uses is automatically frame-aligned — R9's condition 2 for free. The
prohibition is one-way and remains intact.

## 0c — BFS IS GROUND TRUTH FOR REACHABILITY: **PASS**

The closed-form recoverability predicate has broken twice in this program (R9
correction #1: zero-balance `reassign`; R12: `snapshot`+`delete`). R10 therefore
uses **explicit search only**:

- `reachable_blind` — unrestricted BFS over principal-available actions. **The
  definition.**
- `reachable_goal` — goal-directed search, used as an optimization, with its
  completeness argument stated in the preregistration §0c and its agreement with
  `reachable_blind` asserted **case by case**, not spot-checked
  (`test_goal_directed_agrees_with_blind_bfs`, 7 parametrized cases including the
  zero-balance-`reassign` regression). Disagreement is asserted as a FINDING, never
  patched. **No disagreement was found.**
- R12's `snapshot`+`delete` breakage cannot arise: R10's vocabulary has no
  `snapshot`/`restore`, asserted rather than silently dropped
  (`test_snapshot_restore_regression_is_not_applicable`).

**Disclosed state-size reduction (sanctioned by 0c).** R9's arena (300 objects,
175000 credits) makes blind BFS impossible. R10 uses a reduced arena of **42
assets** (17 content + 20 resource + 3 ownership + 2 channel), specified in the
preregistration §2 before any run.

**Disclosed search bound.** R9's `a2_ratchet` runs **unmodified** but under a 25 s
wall-clock budget; a timeout is reported per cell as `a2_search_bounded: true` and
read as "no unrecoverable state found within the bound" — the same shape as R9's
own "within depth 12". It fired only at θ ∈ {0, 0.01}, where `G5(0) == G3` (proved
by test) makes the invariant definitionally equivalent to recoverability, so no
such path can exist.

## 0d — CREDITS: **PASS (zero spend)**

Zero model calls. Deterministic simulation and source reading throughout — the
harm-model draft, the θ sweep, the breadth matrix, the checkpoint sweep, and every
reachability search. No step required a model, so no STOP was triggered.

## Test gate

`test_breadth.py`: **28 passed**, including the two load-bearing ones —
`test_concurrency_race_each_local_check_passes_joint_state_is_unrecoverable`
(without which the Part C nulls would have no power) and
`test_h_lost_is_a_measure_not_a_count` (without which `H_lost` would be R9 §3.2's
error in new clothes).
