# Route 8 — GATE 0 report: STOP at 0b (substrate not cached)

Per the preregistered discipline ("If program text was not cached, report this and STOP —
the claimant programs are the substrate and cannot be regenerated cheaply without drift").
Execution halted before any Stage-1 generation. No credits spent.

## 0a — preregistration

`PREREGISTRATION_R8.md` committed before any generation (this commit). Design, metrics,
decision rule, and point predictions are on record and predate any data.

## 0b — cache inventory: **FAIL**

The substrate R8 requires is the **generated program TEXT** for the 9 models × 50 seeded
MBPP problems. It was **not cached**.

**Evidence.**
- `correlated_failure/or_cache/*_code_s1.json` and `groq_cache/` store, per (model, problem),
  a **behavioral signature** — a list of output strings on the 3 original MBPP asserts — not
  the program source. Example (`microsoft__phi-4_code_s1.json`, first entry):
  `[["[4, 8, 12]", "[2, 4, 6, 8, 10]", "[9, 18]"]]`.
- The round-1 harness discards the source: in `run_openrouter.py` (and identically
  `run_groq.py`), the generated `code` is used only to compute `run_signature(code, c)`; the
  signature is cached and the program text is dropped (lines ~104–109 / ~88–93).
- An exhaustive scan of every `*cache*` directory under `research/` found program source only
  in `route2_independence/route2_cache/` and `route3_attractor/route3_cache/` — and those are
  **CODE-on-MATH** (keys like `algebra#428`), a script that computes a math word-problem
  answer. That is the wrong substrate: it is verified by a single numeric output (the MATH
  regime that already died in Routes 2–5), **not** by unit tests over a function — which is
  exactly the "native formal verifier" the escape-hatch claim is about.

**Why this is a genuine STOP, not a filter to work around.** R8's Stage 2 executes *new,
checker-written* tests against each claimant program. A new test calls the function on inputs
the cached 3-assert signature does not cover, so the behavioral signature cannot answer it.
The programs cannot be reconstructed from cache; they can only be re-generated, which the
preregistration flags as introducing drift (below).

## 0c — ground truth / cell definitions: **recoverable**

What the cache *does* retain is enough to define the cells and the ground truth — just not the
programs to test. Round-1 MBPP pass rates (the `code_pass_rate` that defines each checker's
cell-(a)/(b) split) are intact:

| model | round-1 MBPP pass |
|---|---|
| llama-3.1-70b-instruct | 0.40 |
| gemma-2-27b-it | 0.38 |
| phi-4 | 0.38 |
| mistral-small-24b-2501 | 0.32 |

So the diagnosis is precise: **cell membership and round-1 correctness are recoverable; the
claimant programs needed to run checker-written tests against are not.** Only the substrate is
missing.

## 0d — credits

Balance **$3.40**. A full R8 run (regenerate 9×50 claimant programs *with source cached* +
recompute ground-truth signatures + 4 checkers × 50 problems × 2 arms × 5 tests + arm S) is
~900–1300 short generations, roughly **$0.5–1.5** — within budget. Cost is not the blocker;
the preregistered STOP is.

## The decision (user-owned)

R8 is executable, but only by **regenerating the round-1 substrate from scratch** — and the
preregistration explicitly makes that a STOP because it changes the design:

- **Drift.** Re-generating at temp 0 today need not reproduce the round-1 programs (model
  versions/endpoints move). New programs would have their own correctness, so the cached
  `code_pass_rate` cells would no longer describe them.
- **The clean fix** is to regenerate the *whole* round-1 code substrate in one run — claimant
  programs **with source cached** AND their signatures/ground-truth recomputed together — so
  cells and programs are internally consistent. That is a new, larger data-collection round,
  not a continuation of the cached experiment.

This is a scope + budget call that belongs to the user (it spends credits and departs from the
preregistered "reuse the cache" substrate). Options:

1. **Authorize a fresh substrate regeneration** (~$1–1.5): regenerate 9×50 MBPP programs with
   source cached + recompute ground truth in the same run, then execute R8 as preregistered.
   The internally-consistent-regeneration caveat is disclosed in the write-up.
2. **Leave R8 blocked** and record that §6's escape-hatch claim remains REASONED-not-MEASURED,
   with the exact reason (the round-1 harness cached signatures, not source).

No `research/COMPETENCE_BOUND.md` DIFF is produced: with no measurement, there is nothing to
restate §6 against. `main` untouched; no committed findings edited.
