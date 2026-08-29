# Pre-registration — Route 8: test the escape hatch (native formal verifier)

Committed BEFORE any generation. Git history is the timestamp. Not edited after data is
seen. **This is a TEST of a claim in `research/COMPETENCE_BOUND.md` §6/§7** — that domains
with a native formal verifier (code + unit tests) "plausibly escape" the competence bound
— not a revision of any prior route. All prior decisions stand.

## Question

Does cheap verification of code escape the competence bound that killed every prose-reasoning
mechanism? The naive "unit tests verify code" evades the real question: **where do the tests
come from?** If the claimant writes them they are gameable (the A2 self-inversion failure);
if the checker writes them the checker must understand the problem to write discriminating
tests (the R5 extraction failure, one level up). So the decisive question is: **does
test-writing require competence?**

Sub-case: EXAMPLE tests (input → expected output) require solving the problem; PROPERTY tests
(invariants: sorted, length-preserved, `f(f(x))==x`, type/range) do **not** — property tests
are checking-without-solving, the code analogue of Channel A's metamorphic relations but with
**no extraction stage**, because code is already formal.

## Substrate (GATE 0b — the claimant programs)

The 9 models × 50 seeded MBPP problems generated in round 1 (`correlated_failure`), reusing
`codebench.py`'s executor + sentinel/TIMEOUT/ERR handling **unchanged**. Ground truth (0c): a
claimant program is CORRECT iff its cached behavioral signature equals the expected signature
under the ORIGINAL MBPP asserts. UNRESOLVED (timeout/crash) programs are EXCLUDED, never
scored. **Requires the generated PROGRAM TEXT to be cached** — new checker-written tests must
be executed against the program source; a behavioral signature over the 3 original asserts is
insufficient, because a new test calls the function on new inputs.

## Checkers (4, spanning the round-1 MBPP band, temp 0)

llama-3.1-70b-instruct (0.40), gemma-2-27b-it (0.38), phi-4 (0.38), mistral-small-24b-2501
(0.32).

## Design

**Stage 1 — test generation (the confound).** Each checker sees ONLY the problem statement +
signature/entry_point. NEVER the reference solution, the original asserts, or any claimant
program (isolation asserted in code + tests; violation invalidates the experiment).
- ARM E (EXAMPLE): checker writes N=5 assert tests with concrete inputs/expected outputs.
- ARM P (PROPERTY): checker writes N=5 invariant checks valid for ANY correct implementation,
  WITHOUT computing expected outputs. Prompt forbids expected-value asserts; smuggled concrete
  outputs are logged (protocol-violation rate).
- ARM S (SELF-WRITTEN, gameability control): the CLAIMANT writes tests for its own program,
  run against its OWN program. Parallels A2 self-inversion; reported as a control, never a
  result.

**Stage 2 — execution (offline, zero model calls).** Run every suite against every claimant
program in a 5 s-timeout subprocess. Suite FIRES iff ≥1 test fails. Per-test outcomes recorded.
- A test that is syntactically broken or fails the MBPP REFERENCE solution is INVALID —
  excluded from numerator AND denominator.
- TEST VALIDITY RATE per checker per arm (fraction passing the reference) is a first-class
  result. Primary metrics on VALID tests only; ALL-TESTS variant reported as ablation.
- **The reference-filtered numbers are an UPPER BOUND unavailable in production** (deployment
  has no reference to filter against). Stated every time.

**Stage 3 — metrics.** Ground truth = claimant correctness. ALWAYS report TPR, FPR, firing
rate, precision, LR=TPR/FPR, Youden J with ITEM-bootstrap CI, permutation null (3000×). LR
evaluated against the feasibility frontier LR ≥ g/w (COMPETENCE_BOUND §4).

## Four preregistered questions

- **Q1 TEST VALIDITY (first).** Per checker/arm: fraction of tests passing the reference;
  fraction of problems with ≥1 valid test; arm-P protocol-violation rate. Split by whether the
  checker SOLVED that problem in round 1 — if validity collapses on unsolved problems, the
  bound bit at test-writing and that is the headline.
- **Q2 CRUX — cell (b).** Cells by the CHECKER's own round-1 ability: (a) checker's program
  correct, (b) wrong. TPR/FPR/LR/J/n per cell, per arm, per checker. Cell (b) decisive.
  **Power: round-1 pass 0.32–0.40 → cell (b) is the MAJORITY (~60–68%)** — the first
  well-powered cell (b) in the program (vs MATH n=32–36). Report exact n.
- **Q3 EXAMPLE vs PROPERTY.** Paired over identical (checker, problem, claimant) triples: J,
  LR, validity for E vs P, in cell (a) and (b). Hypothesis: E needs solving → cell-(b) degrades;
  P does not → if any arm breaks the bound it is P. Item-bootstrap CI on the paired difference.
- **Q4 ERROR-CLASS DISSOCIATION.** Classify bugs COMPUTATIONAL (right function, wrong step) vs
  COMPREHENSION (wrong function, misread spec) from cached signatures; hand-label ≥30 to
  validate. Prediction: checker tests catch COMPUTATIONAL, miss COMPREHENSION (round-3 CODE
  finding, one level up). Dissociation table; holds regardless of Q2.

## Decision rule

- **ESCAPE-REAL:** cell-(b) J > 0.30 (CI excl 0) AND LR > 5 for ≥2 checkers in ≥1 arm, AND
  cell-(b) test validity ≥ 0.5 → a checker verifies code it cannot write; §6 is MEASURED.
- **ESCAPE-PARTIAL:** the above for arm P but not E, OR only for COMPUTATIONAL bugs → real but
  scoped; that scope is the deployable domain.
- **ESCAPE-ILLUSORY:** cell-(b) J CI includes 0, or cell-(b) validity < 0.5, for most checkers
  in both arms → test-writing requires competence; the bound is universal; §6 must be retracted
  and the negative strengthened. **(A SUCCESS — a stronger claim than a scoped positive.)**

## Point predictions (stated now)

Validity 0.5–0.8 cell (a), 0.3–0.6 cell (b); arm E cell-(b) J 0.1–0.3; arm P cell-(b) J
0.2–0.5 (the open question); computational bugs caught ~2× comprehension; arm S firing on own
wrong programs well below checker-written. Prior: **30% ESCAPE-REAL / 45% ESCAPE-PARTIAL / 25%
ESCAPE-ILLUSORY.** Any single checker/problem/test driving a cell → INCONCLUSIVE.

## What this cannot establish even if ESCAPE-REAL

One benchmark (MBPP), short functions, one capability tier; does NOT address whether a SPEC is
correct (the comprehension gap one level up — a perfect test suite for the wrong spec verifies
nothing). SEED=1, temp 0.
