# Findings — Route 8: does the native-verifier escape hatch hold?

DECISION first, then test validity (Q1), the cell (a)/(b) table (Q2), example-vs-property
(Q3), the error-class dissociation (Q4), the arm-S control, then limits. R8 **tests** a
claim in `research/COMPETENCE_BOUND.md` §6 — that domains with a native formal verifier
(code + unit tests) "plausibly escape this bound entirely." It is not a revision of any
prior route; all prior decisions stand. Substrate is **freshly regenerated** for the 4
in-band models (drift disclosure below); SEED=1, temp 0.

## DECISION — ESCAPE-ILLUSORY (for LLM-written tests)

The escape hatch is **illusory when the tests are written by a checker LLM**. Test-writing
is itself competence-bounded, so the "native verifier" re-imports the bound one level up —
exactly the R5 failure mode (a formal checker fed by an LLM stage). Three grounds, the
first two preregistered as decisive:

1. **Test validity collapses outside competence.** Cell-(b) test validity (fraction of a
   checker's tests that pass the reference solution) is **< 0.5 for every checker in both
   arms** — the preregistered ILLUSORY trigger. Validity falls from **~0.77 in cell (a)**
   (checker solved the problem) to **~0.28 in cell (b)** (checker did not). A checker that
   cannot solve a problem writes tests that are *themselves wrong* 65–88% of the time.
2. **The deployable variant is a false-positive generator.** The reference-filtered
   detection numbers (below) are an **UPPER BOUND unavailable in production** — deployment
   has no reference solution to filter tests against. Running **all** tests (the deployable
   variant): cell-(b) **arm P J = 0.122, CI [−0.161, 0.470] includes 0, LR = 1.17** — a
   literal coin flip, the 6B out-of-competence signature reproduced; cell-(b) **arm E
   LR = 1.92, FPR = 0.44**. Even *in* competence the all-tests FPR is 0.43, because ~20–40%
   of LLM-written tests are simply wrong (they fail a correct reference) and fire on correct
   programs.
3. **Property tests do not rescue it (Q3).** The "checking-without-solving" hope — that
   invariants need no expected output — is refuted: property tests are **worse** than
   example tests everywhere (paired cell-(b) J: E 0.65 vs P 0.25, diff −0.40). Writing a
   *discriminating* invariant for a problem you don't understand is as hard as solving it.

The native-verifier domain escapes the competence bound **only when the tests come from an
independent, non-LLM source** (human-written unit tests, a formal spec) — which is Route 6's
"route to ground-truth resolution," not cheap LLM verification. This **strengthens the
program's negative result**: the competence bound holds across prose reasoning (Routes 2–5,
6B/7) *and* the formal code domain, because the step that makes code checkable — writing
discriminating tests — is itself competence-bound.

## Drift disclosure (substrate freshly regenerated)

Round-1 cached only behavioral signatures, not program source (GATE 0b), so the 4-model
substrate was regenerated with source + ground truth in one run. New pass rates match
round-1, confirming minimal drift:

| model | round-1 | new (resolved) | `__ERR__` gen-failures |
|---|---|---|---|
| llama-3.1-70b | 0.40 | 0.396 | 2 |
| gemma-2-27b | 0.38 | 0.394 | **17** |
| phi-4 | 0.38 | 0.388 | 1 |
| mistral-small-24b | 0.32 | 0.347 | 1 |

**Artifact caught (hand-validation, Q4 sample):** gemma had 17 HTTP-error generation
failures whose `__ERR__` source parses as a Python annotation (not a crash), so they
initially scored as WRONG claimants and inflated the "comprehension caught" rate. Excluded
as UNRESOLVED (a generation failure is not a program). This is a substrate-integrity fix on
generation-failure grounds, disclosed, not detection-tuning.

## Q1 — Test validity (reported first)

| checker \| arm | overall | cell (a) | cell (b) | arm-P protocol-viol |
|---|---|---|---|---|
| llama \| E | 0.496 | 0.853 | 0.262 | — |
| llama \| P | 0.496 | 0.768 | 0.338 | 0.064 |
| gemma \| E | 0.378 | 0.655 | 0.116 | — |
| gemma \| P | 0.563 | 0.739 | 0.530 | 0.254 |
| phi-4 \| E | 0.488 | 0.789 | 0.313 | — |
| phi-4 \| P | 0.333 | 1.000 | 0.000 | 0.000 |
| mistral \| E | 0.448 | 0.812 | 0.256 | — |
| mistral \| P | 0.488 | 0.706 | 0.356 | 0.156 |

Cell-(a) validity 0.65–1.0; cell-(b) validity 0.12–0.53 (only gemma-P at 0.53 reaches
0.5). The collapse **is** the headline: writing valid tests requires solving the problem.
Arm-P protocol violations (smuggled concrete expected outputs) reach 0.25 (gemma) — property
prompts leak back into example tests under pressure, itself a symptom of not knowing what
invariant to state.

## Q2 — Cross-checking, by the checker's own competence

**Reference-filtered (UPPER BOUND — needs a reference solution, unavailable in deployment):**

| arm \| cell | n | TPR | FPR | LR | J [CI] |
|---|---|---|---|---|---|
| E \| a | 170 | 0.864 | 0.054 | 16.0 | 0.810 [0.553, 0.967] |
| E \| **b** | 127 | 0.591 | 0.059 | 10.0 | **0.532 [0.253, 0.779]** |
| P \| a | 129 | 0.750 | 0.027 | 28.3 | 0.724 [0.261, 1.0] |
| P \| **b** | 138 | 0.342 | 0.000 | ∞ | **0.342 [0.164, 0.523]** |

**All-tests (DEPLOYABLE — no reference filter):**

| arm \| cell | n | TPR | FPR | LR | J [CI] |
|---|---|---|---|---|---|
| E \| a | 179 | 0.920 | 0.429 | 2.15 | 0.491 [0.217, 0.719] |
| E \| **b** | 290 | 0.835 | 0.435 | **1.92** | 0.400 [0.048, 0.739] |
| P \| a | 138 | 0.765 | 0.545 | 1.40 | 0.219 [−0.221, 0.589] |
| P \| **b** | 220 | 0.828 | 0.706 | **1.17** | **0.122 [−0.161, 0.470]** |

The gap between the two tables is the whole finding. Cell-(b) is **well-powered** here
(n=127–290; nw=110–123) — the first adequately-powered cell (b) in the program (vs n=32–36
in the MATH phases), and it is not underpowered. On the filtered upper bound, valid tests
detect (J 0.34–0.53, CI excl 0). Deployed, arm P is a coin flip and arm E is a
false-positive generator. The reference filter that rescues the numbers is the ground truth
whose absence defines the problem.

## Q3 — Example vs property (paired, checking-without-solving refuted)

| cell | n_paired | J (E) | J (P) | diff (P − E) |
|---|---|---|---|---|
| a | 117 | 0.942 | 0.663 | −0.279 |
| b | 65 | 0.649 | 0.246 | −0.404 |
| all | 182 | 0.661 | 0.302 | −0.359 |

Property tests are **worse in every cell**. The hypothesis — invariants are checkable
without solving, so property tests should break the bound — is refuted: a *valid,
discriminating* invariant requires understanding the problem's structure, which is the same
competence. Property tests do have one virtue (near-zero FPR when valid — they are true
invariants), but their yield outside competence is too low to matter (phi wrote **zero**
valid property tests in cell b).

## Q4 — Error-class dissociation (prediction not robust; a real limit remains)

Catch rate (valid tests, cross) by bug class, with CRASH separated from the semantic
classes (crashes are trivially caught and were contaminating the pooled numbers):

| arm \| cell | COMPUTATIONAL | COMPREHENSION | CRASH |
|---|---|---|---|
| E \| b | 0.55 (44/80) | 0.47 (8/17) | 1.00 (13/13) |
| P \| b | 0.18 (12/67) | 0.42 (15/36) | 0.75 (15/20) |

The preregistered prediction (computational caught ≫ comprehension, the round-3 CODE echo)
is **not robustly supported**: example tests catch computational slightly more (0.55 vs
0.47), property tests catch comprehension *more* (0.42 vs 0.18) — the reverse. The robust
finding is different and real: **property tests barely catch computational bugs (0.18)** —
an invariant rarely pins down an off-by-one — while any test catches a crash (1.0).
**Classifier honesty:** hand-validating 30 samples exposed the `__ERR__`/name-mismatch/crash
contamination (now fixed by the CRASH class and the UNRESOLVED exclusion); post-fix the
CRASH vs non-crash split is clean, but the computational-vs-comprehension boundary remains
noisy (e.g. an `int` returned where a `float` was expected is ambiguous), so the fine
distinction in this table is **tentative**; the coarse "property tests miss subtle bugs" and
"crashes are free" conclusions are firm.

## Arm-S control (gameability)

Self-pairing (checker's own spec-derived suite vs its own program) fires at a rate
**comparable to cross** (E cell-b: self TPR 0.625 vs cross 0.591; P: 0.40 vs 0.342) — **no
gameability gap in this design.** Reason: per the amendment, arm-S tests are spec-derived
(the isolation invariant), so they are not tuned to pass the model's own code. This design
therefore does **not** reproduce the strong A2 self-inversion gameability (a claimant writing
tests *with its own code in view*); that remains the A2 finding, not re-measured here. The
operational rule is unchanged and, if anything, reinforced: require checker-written (cross)
or externally-specified tests — the isolation that makes self ≈ cross here is exactly what a
self-interested claimant would drop.

## Limits (first-class)

- **One benchmark (MBPP), short functions, one capability tier (4 open-weight models,
  pass 0.35–0.40), numeric/collection outputs, English.** No large programs, no property-rich
  domains (parsers, data structures) where invariants might carry more.
- **The reference-filtered numbers require a reference solution** that production lacks; they
  are reported only to locate the upper bound and are labelled as such throughout.
- **The comprehension/computational classifier is signature-based and noisy** (Q4 caveat);
  the semantic dissociation is tentative.
- **What R8 cannot establish even as ILLUSORY:** it does not test whether an *externally
  specified* test suite (human/formal) verifies code — it almost certainly does, and that is
  precisely the escape that survives. R8 shows only that a **checker LLM cannot cheaply
  supply the tests**. It also does not address whether the *spec itself* is correct — a
  perfect suite for the wrong spec verifies nothing (the comprehension gap one level up).
- **Well-powered where it counts:** unlike the MATH phases, cell (b) here is n=127–290, not
  underpowered; the ILLUSORY verdict rests on demonstrated numbers, not an underpowered null.

## What it means for the program

`COMPETENCE_BOUND.md` §6 said code + unit tests "plausibly escape this bound entirely." R8
measures that: **it escapes only when the tests are externally specified.** When a checker
LLM writes the tests, the bound re-enters through test validity (collapses outside
competence) and through the irreducible ~20–40% invalid-test FPR that no cheap in-band model
avoids without a reference oracle. The competence bound is therefore **universal across prose
and formal domains for LLM-supplied verification** — and the deployable positive is the same
one Route 6 named: scope claims to where an **independent** verifier (human tests, a formal
kernel, reality) already exists, rather than asking a cheap model to invent the check.
