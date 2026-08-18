# Program status — TERMINAL

> ### ⚠ READ `research/CORRECTIONS.md` FIRST
>
> Several claims in this corpus are now known to be **wrong or narrower than
> they read** — including `FINDINGS_BOX_SCALING` §4b (refuted), the PROOF-carried
> figure (61.1% → 55.6%), and `ENGINEERING_STATUS`'s capability paragraph (replaced
> 2026-08-15; the new one leads with the aggregate-alignment results).
> Superseded text
> stands unedited by design, so the index is the only way to find what moved.
>
> Work after 2026-08-13 lives in `research/planetary/` (the scaling equation and
> its consequences), `research/arena/` (the first environment expressing M > 3),
> and `research/harm_redteam/` (§4.2, run against the shipped guard).

The verification research program has reached a terminal conclusion. **No further
experimental round is planned.** This file is the formal closure record; the paper-shaped
account is `COMPETENCE_BOUND.md`, the publishability audit is `PAPER_READINESS.md`, and the
map of what remains open is `FRONTIER_LEDGER.md`.

## The terminal claim

**Cheap verification of natural-language reasoning is bounded by the verifier's competence:
you cannot cheaply verify what you cannot understand.** Demonstrated across **six
structurally independent mechanism families**, each preregistered with a decision rule before
data, each failing for the same reason from a different direction:

1. **Agreement** between independent producers — shared competence, not independence.
2. **Consistency** / metamorphic self-audit — its power was re-solving, not content-free
   checking.
3. **Defensibility** under challenge — catches strategic lies, not sincere confusion.
4. **Cross-model checking** (± reasoning witness) — works inside competence, collapses outside.
5. **Mechanical (CAS) checking** — sound checker, but the LLM extraction stage re-imports the
   bound.
6. **Native test-writing** — code + unit tests escape only with *externally specified* tests;
   an LLM asked to write them re-imports the bound through test validity.

Families 5 and 6 are the same lesson twice: an LLM that must *supply* the check carries the
competence dependence back in, whether the machinery behind it is a CAS or a unit-test runner.

## Decision record (one line per phase, with commit hash)

| Phase / route | Committed decision | Commit |
|---|---|---|
| correlated_failure (H2) | H2 FALSIFIED — no universal cross-family blind spot | `7a18152` |
| correlated_failure (CI-null) | Conditional-independence null: "universal blind spot" is a constrained wrong-answer space (Case A); excess ≈ 0 | `d484d74` |
| Route 2 (agreement, decisive) | Preregistered decision UNREACHABLE (output-space structure) | `365e079` |
| Route 3 (adversarial attractor) | GATE B not met → **Route 2 UNFALSIFIABLE-IN-PRACTICE** (terminal) | `c150442` |
| Route 3 (cardinality scope) | Agreement-informativeness holds for ≥3-agent committees, unmeasurable for bare pairs | `5231be5` |
| Channel A (consistency) | **A-LIVE** — surface-keyed error detectable, beats self-consistency | `c2052a0` |
| Channel A (Phase 4 ablations) | A-LIVE survives; deployable {T2,T3,T4} J = 0.94 | `399a9b4` |
| Channel A (Phase 6A) | Downgraded: T2 J = 1.0 is a **DE-TRAPPING artifact** | `2a12400` |
| Channel B (defensibility) | **B-INSINCERE-ONLY** — catches assigned lies, not held errors | `40d2d32` |
| Phase 6B (cross-verify) | **ASYMMETRY-WEAK** — verification ≈ re-solving on MATH | `a7cd073` |
| Phase 7 (witness/localize) | **WITNESS-DEAD** — the trace creates no verification asymmetry | `74faa91` |
| Phase 8 (canonicalization) | Contamination corrected; artifact real, **no decision changed** | `4ecb603` |
| Route 5 (mechanical CAS) | **R5-DEAD** — extraction re-imports the bound | `27438b1` |
| Route 6 (audit mechanism) | Known framework (Townsend/Becker/Stackelberg) + competence-calibrated `q`; LR-not-J feasibility | `212f35d` |
| Route 6 (correction) | G2 inversion fixed: target the consequence-to-gain ratio | `f46445c` |
| Route 8 (native tests) | **ESCAPE-ILLUSORY** — test-writing is competence-bounded | `ba500f5` |
| Synthesis | `COMPETENCE_BOUND.md` (six families) | `e8d7c79` (+ this closure) |

## Power note

The strength of the result is **six-family convergence plus one well-powered demonstration**,
not any single underpowered cell.

- **Well-powered:** Route 8 cell (b) is n = 127–290 (nw = 110–123) — the first adequately
  powered out-of-competence cell in the program. Its ESCAPE-ILLUSORY verdict rests on
  demonstrated numbers, not a null.
- **UNDERPOWERED-NULL (labeled as such):** the MATH-phase out-of-competence cells pool to
  n = 32–36 — 6B cell (b) J = 0.111 (CI incl 0), Phase-7 C1 cell (b) J = 0.164 (CI incl 0),
  R5 cell (b). These are directionally consistent with the bound but are **not individually
  decisive**; they are corroborating, not load-bearing.

The one durable **positive** is also well-powered: 6B cell (a) — within competence — J = 0.777,
LR = 19.8, n = 433, permutation p = 0. Cheap checking works *inside* competence. That is the
deployable regime (see `audit_mechanism/GYZA_DESIGN_RULES.md`).

## Scope of the closure — what it does and does NOT close

- **Closes:** the *detection* and *cheap-verification* question for natural-language reasoning
  via **black-box** mechanisms — asking the producer, other models, the trace, a CAS, or
  LLM-written tests. All re-import the competence bound.
- **Does NOT close:** the **producer-internals** channel (logits / activations / probes). No
  phase tested it; it requires **white-box access unavailable through the API roster** used
  (OpenRouter/Groq chat completions). It is listed GENUINELY-OPEN in `FRONTIER_LEDGER.md`,
  with an honest low-ish prior and the Phase-7 reason to expect it also fails (errors are
  mid-computation slips, not comprehension states the model represents).
- **Does NOT claim generality beyond the apparatus:** two task families (MBPP, MATH) + one
  fixture set (NoOp), one open-weight capability tier (pass 0.32–0.40), English, numeric /
  collection answers. The **frontier-model gap** — whether the bound *shifts* (not vanishes)
  with much stronger models — is the single most important untested variable
  (`PAPER_READINESS.md`).

## Status

**TERMINAL.** Engineering follow-ups (Gyza's bonded-market design over in-competence claims)
live in `audit_mechanism/GYZA_DESIGN_RULES.md`. Choosing whether to open a *new* channel is a
user decision informed by `FRONTIER_LEDGER.md`; it would be a new program, not a continuation
of this one.


---

## Post-closure routes (appended 2026-08-18)

The program was declared terminal at twelve routes. Five more have run since,
each preregistered before any code, each with its hash re-verified after the
runs. **This section exists because a reader of this file would otherwise
believe the program ended where it did not.**

| route | verdict |
|---|---|
| **escrow** | `ESCROW-CONVERTS-LOSS-TO-FORGONE-GAIN` — unpaid work → 0, but the same 80 credits reappear as work never commissioned. Also `RESERVATION-DEAD-ABOVE-M=3` |
| **R-M1 margin** | `MARGIN-GROWS-WITH-M-AND-APPROACHES-THE-CEILING` — δ\* rises 0.130 → 0.295 (M=8→512); margin is a STEP, not a dial |
| **A2 defector** | `COMPLIANCE-ASSUMPTION-NOT-SECURITY-PROPERTY` — one defector breaks the bound at every flat scale, via the COMMONS |
| **R-H1 hierarchy** | `HIERARCHY-HELPS-DECISIVELY` — depth 2–3 defeats at ε≤2 with NO margin; max fan-in 511 → 7 |
| **R-B blast radius** | `BLAST-RADIUS-IS-ONE-CLUSTER` — ~1.6 defectors per cluster; hoarding stops breaching at depth 3 |
| **R-N horizon** | `COMPOSABILITY-IS-NOT-SUFFICIENT` — flat has a finite staleness horizon (eps\* = 8); the tree's margin SATURATES at 68.68% of ceiling, identical at eps = 32, 64, 128 |

**Corrections to previously published findings are indexed in
`research/CORRECTIONS.md` (21 entries).** Two closed forms and one scan have
failed; do not cite a number from any document without recomputing it.

**Open, named by the work itself:** churn (clusters are fixed everywhere above);
a defector that GAMES a check rather than ignoring it; colluding defectors
concentrated in one cluster; and the amortization lever `A`, still untouched and
still the binding term in `N ≤ H·A/[(1−p)(1−c)]`.
