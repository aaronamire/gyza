# Findings — Route 3 adversarial attractor experiment

Write-up per the pre-registration (committed at 2cb0e24, before any generation).
Decision first, then the manipulation-check numbers, then what it means. This is
the third and final round of the Route 2 program.

## DECISION — ROUTE 2 UNFALSIFIABLE-IN-PRACTICE (pre-committed terminal outcome)

GATE B (the manipulation check) was **not met**, so by the pre-registered
terminal rule the decision is **UNFALSIFIABLE-IN-PRACTICE** and **Route 1
(external verification anchor) is the committed architecture**. No round 4.

Three successive designs failed to populate the one regime where Route 2 could
be tested — **dense shared error in an open answer space**:

| round | design | answer space | co-failure | why it can't test Route 2 |
|---|---|---|---|---|
| 1 | MBPP code | constrained (≈1 wrong/problem) | dense (Simpson ≈0.6) | no room to disagree |
| 2 | MATH | open | **sparse** (mean 2.0 wrong/10; Simpson 0) | too few co-failures |
| 3 | **attractor-induced** | **still constrained** | **still sparse** (mean 2.1/12) | both, at once — see below |

## GATE B — the manipulation check (why it failed, precisely)

On the 72 of 80 control-valid items (an item is valid iff ≥2 of 4 models give
the control-expected answer on the original/base):

| metric | value | threshold | pass? |
|---|---|---|---|
| control-valid items | 72 / 80 | — | — |
| **attractor items (≥3 of 12 agents hit the attractor)** | **22** | ≥ 25 | ✗ |
| **mean wrong-agents per item (density)** | **2.10** | ≥ 3.0 | ✗ |
| median attractor concentration (among wrong, fraction on the attractor) | **1.00** | ≥ 0.5 | ✓ |
| space bins (valid items) | 70 CONSTRAINED / 1 MID / 1 LARGE | — | — |
| median distinct wrong answers | 1.0 | — | — |

The concentration of **1.0** means the induction *worked at its stated job*:
when a model is wrong on these items, it gives the **specific baited attractor**,
not some other error. But density is only **2.10 of 12** agents — capable models
mostly get even deliberately-baited items right — and only 22 items cleared ≥3
attractor-hits, short of 25. Data integrity: **0 / 1600** failures (the round-2
credit blocker is resolved).

### Where the attractor worked — and where capable models were immune

| category | n | items with ≥3 attractor-hits | mean density | mean attractor-hits |
|---|---|---|---|---|
| **ii_noop** (irrelevant-clause) | 40 | **21** | 2.85 | 2.80 |
| i_classic (Monty Hall, boy-girl, birthday, fence-post, all-but-N) | 20 | **1** | 1.40 | 0.45 |
| iii_substitution (sum, polygon, even-numbers) | 20 | **0** | 1.05 | 0.00 |

Only the **NoOp** construction (Apple GSM-NoOp style: a clause that looks
relevant but must be ignored) induced dense shared error — and even it fell just
short of density 3. The **classic puzzles barely fooled anyone** (models have
learned Monty Hall et al.), and the **numeric substitutions fooled no one** —
capable models simply recompute (zero attractor hits across 20 items).

### It is capability-driven, not a shared blind spot

Per-agent attractor hit rate (72 valid items):

| model | COT | DECOMP | CODE |
|---|---|---|---|
| gemma-2-27b | 0.31 | 0.36 | 0.33 |
| llama-3.1-70b | 0.03 | 0.10 | 0.22 |
| mistral-small-3.2 | 0.06 | 0.06 | 0.13 |
| phi-4 | 0.00 | 0.00 | 0.07 |

The "shared" error is largely one weaker model (gemma) plus scatter; phi-4 is
essentially immune. This is not a universal blind spot — it tracks capability.
(Note phi-4 was the strongest on the round-1/2 code and MATH batteries too.)

## The structural finding: dense-shared and open-space are in tension

The three rounds together suggest the dense-open regime is not merely unobserved
but **structurally hard to reach**, because the two conditions oppose each other:

- To make errors **dense and shared**, you need a strong common attractor — but a
  strong attractor collapses the wrong-answer space onto itself. Round 3 induced
  concentration 1.0 and the space stayed **CONSTRAINED** (median 1 distinct wrong
  = the attractor). Dense ⇒ constrained.
- To keep the space **open and diverse**, errors must scatter — but capable
  models that scatter their errors are, by definition, rarely co-failing. Round 2
  had an open space and **sparse** failure. Open ⇒ sparse.

So "dense shared error in an open space" asks for a strong shared attractor
(which constrains the space) that simultaneously leaves the space open (which
requires no strong shared attractor). Across a natural constrained task, a
natural open task, and a deliberately adversarial induced task, the regime did
not appear. That is the honest reason Route 2 is unfalsifiable in practice — not
"the decorrelation mechanism failed," but "the regime the mechanism would act on
does not occur."

## What it means: commit to Route 1

- **Do not build Route 2 (engineered method-independence).** Across three rounds
  it was never testable: either there was no room to disagree, or capable models
  did not co-fail, or both. The one lever that reliably induced shared error
  (NoOp clauses) is exactly a case where the fix is **reading the problem
  correctly**, i.e. competence, not committee diversity.
- **Route 1 (external verification / reality anchor) is the committed
  architecture.** Where agreement could be trusted at all (round 2, open space),
  it was already informative without engineered independence (CARDINALITY_LAW.md,
  corrected trust-lift positive for ≥3-agent committees); where errors are shared
  (constrained space, or NoOp attractors), only an external anchor breaks them.
  This matches Gyza's settlement-primary + sparse-ground-truth-resolution design.
- **The cheap agreement policy still stands on open-output tasks** (round 2); the
  expensive engineered-independence machinery is unproven and, per this round,
  likely unnecessary — the regime that would justify it does not materialise.

## Honest limits

- Four models, one capability tier, English; 80 items; one attractor taxonomy.
  "Structurally hard to reach" is an inference across three data points, not a
  theorem — a much larger or differently-constructed battery could in principle
  find the regime. But three deliberate attempts, including an adversarial one, is
  a strong practical signal.
- GATE B thresholds (≥25 items, density ≥3, concentration ≥0.5) were
  pre-registered; the result misses two of three, and the near-miss is on the NoOp
  subset only. Lowering thresholds post-hoc to force regime-validity would be
  exactly the self-deception the pre-registration exists to prevent — not done.
- The attractor is a **constructed fixture**, never reported as a discovery that
  "models share a blind spot"; that models converge on the NoOp attractor when
  wrong is induced by design. The only question asked was whether the regime is
  testable, and it is not.

## Status

Preregistered ✅ (2cb0e24, pre-generation, items sha256[:16]=e0d9fedd108aff4f) ·
instrument + tests ✅ (8/8 green) · generation ✅ (1600 calls, 0 failures) · GATE
B **not met** → **UNFALSIFIABLE-IN-PRACTICE** (terminal; Route 1 committed) ·
Phase D not computed (hard stop respected) · reproduce:
`python route3_experiment.py analyze` (cache-only); result in
`route3_result.json`; raw generations in `route3_cache/` (git-ignored).
