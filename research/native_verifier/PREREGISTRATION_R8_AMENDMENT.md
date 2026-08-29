# Pre-registration AMENDMENT — Route 8 (substrate regeneration)

Committed BEFORE any new generation, after `PREREGISTRATION_R8.md` and `GATE0_REPORT.md`
(GATE 0b found the round-1 MBPP program TEXT was never cached — only behavioral
signatures). This amendment is **mechanical: same definitions, new measurement, no design
change.** Everything in `PREREGISTRATION_R8.md` not restated below is unchanged (isolation
of test-gen prompts; the reference-solution validity filter, reported BEFORE detection;
arms E / P / S; Q1–Q4; the ESCAPE-REAL / ESCAPE-PARTIAL / ESCAPE-ILLUSORY decision rule;
point predictions; the artifact discipline — any number near 1.0 is a suspected artifact,
diagnosed before reporting).

1. **SUBSTRATE.** Regenerate MBPP programs for the **4 in-band models only**
   (llama-3.1-70b-instruct, gemma-2-27b-it, phi-4, mistral-small-24b-instruct-2501) over the
   same seeded 50-problem set (`load_mbpp(n=50, seed=1)`, temp 0), caching **PROGRAM SOURCE
   and behavioral signature together**. Recompute pass/fail ground truth in the SAME run so
   programs and cells are internally consistent. Reuse `codebench.py`'s executor / sentinel /
   TIMEOUT / ERR handling unchanged.

2. **CELLS.** Cell (a)/(b) is defined by each checker's **newly measured** pass/fail on that
   problem, NOT round-1's cached rates. Report the new per-model pass rates alongside round-1's
   (llama 0.40, gemma 0.38, phi 0.38, mistral 0.32) as a drift disclosure. Round-1 rates are
   NOT used for cell assignment.

3. **ROSTER.** Claimants = the same 4 in-band models (not 9). Rationale (stated in the
   write-up): the 3 below-band round-1 models (llama-3.3 0.08, mistral-3.1 0.18, qwen 0.12)
   produce degenerate programs; a suite fires trivially on code that doesn't run, so including
   them would re-import artifact #2 (degenerate weak-model outputs) and inflate TPR with a
   result about broken code rather than subtle bugs. Capability-matched claimants are the
   correct test.

4. **POWER.** Report exact n per cell. Cell (b) here is ~60–68% of problems (~30+ items per
   checker, ~120 pooled cross) — the first well-powered cell (b) in the program, versus n=32–36
   pooled in the MATH phases. If it comes out underpowered anyway, say so.

5. **PAIRING.** Each checker's test suites run against the **3 OTHER** models' programs (CROSS
   — the real cross-checking result) and its **OWN** program (arm S control). Report cross and
   self separately; never pool them. (Arm S is the self-pairing of the same generated E/P
   suites, per the original prereg's gameability control — the A2 self-inversion parallel.)

6. **DRIFT CAVEAT.** Disclose in `FINDINGS_R8.md` that the substrate is freshly generated and
   does not reproduce round-1's exact programs (provider drift), so R8 is **self-contained** and
   its numbers are not continuous with round-1's per-pair convergence figures. This does not
   affect R8's internal validity: programs and ground truth come from one run.

SEED=1, temp 0. No design parameter (arm definitions, validity filter, firing threshold,
decision rule, predictions) is changed by this amendment.
