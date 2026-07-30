# Preregistration — Route 14: can a model SPECIFY what it cannot SOLVE?

**Committed before any model generation.** At commit time `research/spec_competence/`
contained the mutation harness, the hand-written reference specs, and the ceiling
probe — all **zero-model-call, deterministic** code required by GATE 0c, which
mandates that the ceiling be *measured* before any threshold is fixed. **No spec
generation of any kind had run.** This commit hash is the pre-data marker.

Prior routes are imported read-only. All standing decisions hold: R8
ESCAPE-ILLUSORY, R9 ADEQUATE-BUT-RESTRICTIVE, R10 Part B MIXED / Part C
COMPOSES-CONDITIONALLY, R11 ROUTER-DEAD, R12 UNSOUND, R13
FEDERATION-DOES-NOT-COMPOSE.

---

## 0. The question, and why it is not already answered

R8 measured whether a checker LLM can write **tests** for code it cannot write:
validity ~0.77 on solved problems → ~0.28 on unsolved (ESCAPE-ILLUSORY,
well-powered cell (b), n = 127–290). Property tests were **worse** than example
tests in cell (b) (paired J: E 0.65 vs P 0.25).

The open question is whether **specifications** behave differently. A test is a
*sample* — computing the expected output requires solving the instance. A
specification can be a *property* ("output is sorted", "length preserved") that
requires understanding structure without solving any instance. If that asymmetry
is real and models exploit it, the verified tier can be LLM-bootstrapped. If not,
spec-writing is a permanent human bottleneck and the throughput ceiling is human
spec-writing rate.

**The literature figures in the task brief (Re:Form arXiv 2507.16331; SpecTune;
VERINA arXiv 2505.23135; DAFNYCOMP) are recorded as PROVIDED, NOT INDEPENDENTLY
VERIFIED.** The brief cites `research/CLAIM_SPACE_SURVEY.md` as their source;
**that file does not exist** — not on disk, not in any of the 14 branches, not in
git history. The route does not depend on those numbers, and no claim below rests
on them.

---

## 1. GATE 0 — results (all passed; recorded here, pre-data)

### 0b. Substrate inventory — PASS

R8's regenerated cache (`research/native_verifier/nv_cache/`, gitignored, on
disk) holds, per model, 50 entries each carrying **`source` and `status` in the
same dict entry of the same run** — so cell (a)/(b) cannot be misassigned from
stale labels. That was R8's own GATE 0b failure mode and it is structurally
excluded here.

| model | n | cell (a) CORRECT | cell (b) WRONG | UNRESOLVED |
|---|---|---|---|---|
| google/gemma-2-27b-it | 50 | 13 | 37 | 0 |
| meta-llama/llama-3.1-70b-instruct | 50 | 19 | 29 | 2 |
| microsoft/phi-4 | 50 | 19 | 30 | 1 |
| mistralai/mistral-small-24b-instruct-2501 | 50 | 17 | 32 | 1 |

Cell (b) is the majority (58–74%), as expected. **UNRESOLVED (4 of 200, 2.0%) is
excluded from cell assignment and reported separately** — it is neither
demonstrated-correct nor demonstrated-wrong, and imputing either way would
manufacture a cell. MBPP reference solutions and asserts load offline
(`prompt` / `code` / `test_list`, 50 problems, `seed=1`).

### 0c. FEASIBILITY CEILING — MEASURED, not assumed

Per R13's refinement, the ceiling is measured **under the mechanism's own
dynamics** (real specs against real mutants), never derived analytically.

**Mutant generation**, operator set fixed here: `arith_swap`, `cmp_swap`,
`int_boundary`, `bool_negate`, `return_subst`, `loop_bound`, `stmt_delete`.
Measured over all 50 problems:

| quantity | value |
|---|---|
| mutants per problem | mean **9.6** (min 3, max 20) |
| WRONG (fails asserts — the kill-rate denominator) | **422** |
| EQUIVALENT (passes asserts — excluded, cannot be killed by any sound spec) | **54** |
| DISCARDED (syntax/import failure) | **3** |

**Disclosed: the ~20-mutants-per-problem target is NOT met** (actual mean 9.6).
MBPP reference solutions are short and offer few mutable sites. Reported as
measured; the operator set is **not** expanded to hit the target, because
choosing operators to raise a count is tuning.

**Floor and ceiling, measured:**

| baseline | kill rate | n |
|---|---|---|
| `return True` (pure vacuity) | **0.0000** (max 0.0000) | 50 |
| **TYPE-ONLY floor** (all 50 problems) | **0.2864** | 50 |
| TYPE-ONLY on the 18-problem ceiling sample | 0.3643 | 18 |
| **REFERENCE spec, embedding permitted** | **0.7171** | 18 |
| **REFERENCE spec, PROPERTY-ONLY (strict)** | **0.6715** | 18 |

`return True` scores validity 1.0 and kill rate **exactly 0.0000** — this is a
*definitional* zero and is the load-bearing check that the metric detects
vacuity at all.

**Two ceilings are reported because writing the reference specs revealed that
several of them (2, 15, 24, 28, 42, 48, 49, 3) recompute the output and compare
— they embed oracles.** An oracle-embedding spec's kill rate is not a bound on
what a *cheap* property spec can achieve, so a second, strictly non-embedding set
was written and measured. **The property-only ceiling 0.6715 is the one the
claim-space argument needs**; the 0.0456 gap between them is itself a pre-data
observation (property specs nearly match oracle specs on this mutant set).

**The TYPE-ONLY floor of 0.2864 is high**, because `return_subst` mutants change
the return type and are trivially type-detectable. The operator is **kept** (
removing it to flatter the floor would be tuning) and two consequences are
declared instead: kill rate is reported **per operator**, and a **secondary
metric** is declared below.

### 0d. CREDIT GATE — PASS

Balance **$3.2151**. Estimate ~400 spec generations (4 models × 50 problems × 2
arms) plus ~72 Part-B4 calls, at spec-length completions on cheap open-weight
models ≈ **$0.30** (R11: 3080 calls for $0.13). Gate is 2× estimate = $0.60.
$3.2151 ≥ $0.60.

---

## 2. Metrics

**Never validity without kill rate. Never kill rate without floor and ceiling.
Never kill rate without the oracle-embedding rate beside it.**

1. **VALIDITY** — `spec(inp, out)` is True for the REFERENCE solution's outputs
   on every MBPP input. A spec rejecting the reference is **INVALID**: it is
   wrong about the problem. Invalid specs are excluded from kill-rate
   computation and **never imputed**.
2. **KILL RATE (primary)** — over WRONG mutants, the fraction for which `spec`
   returns False on at least one MBPP input. Valid specs only.
3. **KILL RATE ABOVE TYPE (secondary, declared here pre-data)** — the same,
   restricted to WRONG mutants that the TYPE-ONLY baseline does **not** kill.
   This is the sharper anti-vacuity measure: can the spec catch errors a trivial
   type check misses?
4. **NON-SPEC** — crashes, times out (5 s), or returns a non-bool. Excluded from
   **both** metrics, reported separately with its rate. Never scored as a miss.
5. **ORACLE-EMBEDDING RATE** — §4.

`inp` is the tuple of call arguments; `out` is the produced output.

**Crashing mutants.** A WRONG mutant that raises on every MBPP input is in the
primary denominator (per the brief: fails asserts ⇒ WRONG), but no spec can
reject an output that does not exist. A secondary kill rate **excluding**
all-crashing mutants is reported alongside. Both are reported; neither is chosen
after seeing results.

---

## 3. The spec prompt, verbatim

Both arms see **only** the MBPP problem statement and the entry-point name. No
reference solution, no MBPP asserts, no model-written program. **A spec written
with the answer in view is not a specification**, and the isolation is pinned by
a test with a negative control.

**ARM PROP:**

```
You are given a programming problem description and a function name.
Write a Python PREDICATE that checks whether a candidate output is acceptable.

PROBLEM: {prompt}
FUNCTION NAME: {fn}

Write exactly one function with this signature:

def spec(inp, out) -> bool:
    # inp is the tuple of arguments passed to {fn}
    # out is the value {fn} returned
    # return True iff `out` is an acceptable output for `inp`

RULES:
- Assert STRUCTURAL and PROPERTY facts only: relationships between `inp` and
  `out` such as length, type, ordering, membership, preserved quantities,
  ranges, or counts.
- You MUST NOT compute the expected output. Do NOT reimplement {fn} inside
  spec() and compare. A spec that recomputes the answer is not acceptable.
- Return only the function. No explanation, no tests, no markdown fences.
```

**ARM FREE:** identical, with the entire `RULES:` block removed (no restriction
at all). This measures what the model does by default.

Both arms are generated **independently**, temperature 0, `max_new_tokens=400`.

---

## 4. Oracle-embedding detection (the crux of the cost question)

A spec that reimplements the solution and compares is valid and kills mutants —
but writing it required solving the problem, so it does **not** support the
claim-space argument. Declared heuristic, a spec is flagged **EMBEDDING** if any:

1. its body contains a `Compare` with `==`/`!=` where one side is the bare name
   `out` and the other is an expression of **≥ 6 AST nodes** that references
   `inp`; or
2. it defines a nested `def` or a `lambda` containing a loop or comprehension; or
3. its AST node count is **≥ 1.0×** the reference solution's node count.

**Reported:** spec/reference AST node-count ratio per spec; the embedding rate
**per cell**; hand-validation of the heuristic on a sample of **≥ 30** flagged
and unflagged specs with agreement reported.

**Prediction to test.** Embedding is common in cell (a) and rare-or-invalid in
cell (b), because a model that cannot solve the problem cannot embed a correct
oracle. If cell (b)'s valid specs are overwhelmingly non-embedding, the property
asymmetry is real; if cell (b) validity collapses *because* embedding fails, it
is not.

---

## 5. Cells and the primary result

Cell **(a)** = the model's own MBPP program was CORRECT on that problem;
cell **(b)** = it was WRONG. Both from the same cached R8 run (§0b).

**PRIMARY RESULT: the paired cell(a) − cell(b) difference in KILL RATE**, with
a bootstrap CI over problems (3000 resamples, seed 1). The validity difference is
reported alongside, never instead.

**INCONCLUSIVE rule.** Any single model, problem, or mutation operator driving a
cell → that cell is reported INCONCLUSIVE.

---

## 6. Part B — does the invariant taxonomy transfer to specs?

12 hand-written 3-stage pipelines (`f3 ∘ f2 ∘ f1`) over MBPP-style functions,
declared in `pipelines.py`. Three spec classes per stage:

- **CONSERVATION** — a quantity is preserved (length, multiset, sum, element-set).
- **MONOTONE NON-CUMULATIVE** — a property that once established cannot be lost
  by a later stage (sortedness under a monotone map, type/shape constraints).
- **CUMULATIVE** — a budget over the whole pipeline (total elements added across
  stages).

**B2.** For each class, does the CONJUNCTION of per-stage specs imply the
end-to-end property? Determined **both** (i) mechanically, by mutating a single
stage and checking whether the per-stage conjunction rejects, and (ii) by hand,
stating the assume-guarantee side condition or the counterexample.

**B3 PREDICTION.** Conservation and monotone classes **compose** — a single-stage
mutation is caught by that stage's own spec. Cumulative **does not** — a
per-stage spec cannot see the total, so a mutation shifting consumption between
stages passes every local spec and violates the end-to-end budget. **This is
R13's statelessness impossibility in the specification domain.**

**B4.** Ask a model to write the per-stage specs; measure whether ITS specs
compose. Prediction: worse than hand-written, worst on cumulative. Report the
model-vs-hand gap.

---

## 7. Part C — coverage over Gyza's own action vocabulary

Code-only, zero credits. Enumerate Gyza's agent-facing action/claim types by
reading the tree (cite `file:line`), classify each as **NATIVE VERIFIER** /
**CHEAP PARTIAL SPEC POSSIBLE** / **NO VERIFIER**, and report the fraction in
each bucket. Stated plainly as a property of Gyza's *current* vocabulary, not a
general result.

---

## 8. Threshold feasibility — every threshold, before data

| threshold | attainable range (measured) | verdict |
|---|---|---|
| cell (b) kill rate **above the TYPE-ONLY floor** | floor 0.2864; property-only ceiling 0.6715 ⇒ **0.43 of headroom** | FEASIBLE + DISCRIMINATING |
| cell (a) − cell (b) **within 0.15** | differences range ≈ [−0.67, +0.67]; 0.15 is interior | FEASIBLE + DISCRIMINATING |
| "**predominantly** non-embedding" | defined as **> 50%** of cell-(b) valid specs non-embedding; range [0, 1] | FEASIBLE |
| SPEC-VACUOUS: indistinguishable from floor **in both cells** | floor 0.2864 with CI; range [0, 0.67] | FEASIBLE |

No threshold is unreachable and none is trivially satisfiable. **R13's lesson is
applied**: each was checked against a *measured* range produced by running the
actual mechanism, not against a static or analytic bound.

---

## 9. DECISION RULE

- **SPEC-SURVIVES** — cell (b) kill rate (i) above the TYPE-ONLY floor with CI
  excluding it, **AND** (ii) within 0.15 of cell (a), **AND** (iii) achieved
  predominantly by NON-embedding specs. → Models write non-vacuous specs for
  problems they cannot solve; the property asymmetry is real; the verified tier
  can be LLM-bootstrapped. **The most consequential positive result in the
  program.**
- **SPEC-COLLAPSES** — cell (b) kill rate falls materially below cell (a) (paired
  CI excluding 0), mirroring R8's validity collapse. → Specs require external
  authorship; claim-space restriction is real but **human-gated**, and the
  throughput ceiling is spec-writing rate.
- **SPEC-VACUOUS** — cell (b) kill rate indistinguishable from the TYPE-ONLY
  floor in **both** cells. → Models cannot write useful specs here at all, which
  is **worse** than the literature suggests and must be reported as such.

**SPEC-COLLAPSES and SPEC-VACUOUS are SUCCESSES.** COLLAPSES would establish that
the verified tier is human-gated — a hard architectural constraint that directly
sets the throughput ceiling. **No softening, no rescue round.**

---

## 10. POINT PREDICTIONS (stated now)

| # | prediction |
|---|---|
| P1 | ARM PROP validity **high in both cells** (properties are easy to state) |
| P2 | ARM PROP kill rate **collapses in cell (b)** |
| P3 | Oracle-embedding **common in cell (a)**, largely **absent-or-invalid in cell (b)** |
| P4 | ARM FREE shows **more embedding** than ARM PROP |
| P5 | Part B: conservation + monotone **compose**; cumulative **does not** |
| P6 | Part B4: model-written pipeline specs **worse** than hand-written, worst on cumulative |

**Prior: 20% SPEC-SURVIVES / 55% SPEC-COLLAPSES / 25% SPEC-VACUOUS.**

**Recorded against my own hope:** R8 already found property *tests* worse than
example tests in cell (b), which is direct evidence **against** the
property-asymmetry hypothesis. This route tests whether *declarative specs*
behave differently from *executable property tests*. That prior evidence is
stated in the write-up **regardless of outcome**.

---

## 11. Artifact discipline

Eleven artifacts have been caught in this program where a clean number was
definitional, coupled, or contaminated — most recently NO-ANSWER folded into
UNRESOLVED (caught by an exact 1.000), and a feasibility ceiling computed against
a static state rather than the mechanism's dynamics (R13, mine).

**If any validity is exactly 1.000, any kill rate exactly 0 or 1, or any cell
exactly matches its floor or ceiling, the coupling is DIAGNOSED BEFORE
REPORTING.** `return True`'s 0.0000 is already known-definitional and is the
detector, not a finding.

**UNDERPOWERED-NULL is distinguished from DEMONSTRATED-NULL**; n is stated for
every cell.

**No tuning after results.** The spec prompt, operator set, floor definition, and
thresholds are fixed by this document. **Parser fixes only, disclosed with
rates.**

---

## 12. What this cannot establish

- **One benchmark (MBPP), short functions, four mid-tier open-weight models**,
  single seed, temperature 0.
- **Python predicates, not a formal verifier.** "Valid" means **holds on the MBPP
  inputs**, *not* "proven for all inputs". This is a genuine weakening versus
  Dafny/Lean and is restated **every time** a validity number appears.
- Kill rate is relative to **this** mutation operator set; a different set moves
  every number. Only positions between the measured floor and ceiling are
  interpreted.
- Nothing about **semantic-content correctness** — the competence bound, closed
  across six families, terminal.
- Part C is a property of **Gyza's current vocabulary**, not a general result.
