# Pre-registration — Route 5: mechanical step verification

Committed BEFORE any generation. Git history is the timestamp. Not edited after
data is seen. **NOT a Route 2 rescue**; a DIFFERENT checker class (a CAS, not an
LLM). The Route 2 terminal decision and all prior decisions stand.

## Question

Every checker tested so far was an LLM and hit the same competence bound (6B
ASYMMETRY-WEAK cell-b J=0.111 CI incl 0; 7 WITNESS-DEAD C1 cell-b J=0.164 CI incl
0). In every *working* optimistic-verification system the verifier is a MECHANICAL
procedure, not a weaker intelligence. R5 tests whether a non-intelligent checker
(sympy) can catch reasoning errors on problems it cannot solve — checking "does
step k → step k+1 preserve the algebraic identity" needs a CAS, not the ability to
solve the problem.

## Data (GATE 0 confirmed)

Cached full COT traces: MATH (route2, 226 usable, mean 6.7–12.2 steps, corrected
wrongness base rate **0.128**, 28 errors) and NoOp (route3, 160 usable, base rate
**0.156**, 25 errors). Ground truth = final answer wrong via
`consistency_defensibility/canonicalizer_v2.equal` (Phase 8, hand-validated 27/27,
zero false merges); UNRESOLVED excluded.

## Pipeline (three stages, measured separately)

- **Stage 1 — extraction (TRANSCRIBER, not judge).** Segment each trace (Phase-7
  rule). An extractor transcribes each (step k → k+1) transition into
  `{lhs, rhs, relation ∈ {IDENTITY, SOLUTION_SET, SUBSTITUTION, ASSERTION,
  NOT_EXTRACTABLE}, free_vars, assumptions}`, verbatim, EVEN IF WRONG. The prompt
  forbids judging correctness; any correctness commentary is a PROTOCOL VIOLATION
  (rate reported). Two extractors: **strong = phi-4**, **weak = gemma-2**.
- **Stage 2 — mechanical check (zero model calls; the actual verifier).**
  IDENTITY: **random-point evaluation is PRIMARY** (≥20 random rationals, undefined
  points SKIPPED; VIOLATION iff fails at ≥2 valid points AND simplify does not
  certify equality); simplify confirmatory. SOLUTION_SET: solve()-set comparison →
  PRESERVED / ENLARGED_UNSAFE (not a primary violation; ablation counts it) /
  REDUCED (VIOLATION). SUBSTITUTION: evaluate. ASSERTION / NOT_EXTRACTABLE:
  UNCHECKABLE (→ coverage). 5 s TIMEOUT / sympy exception: UNRESOLVED (excluded).
- **Stage 3 — metrics.** Detector fires iff ≥1 transition VIOLATION. Always report
  TPR, FPR, firing rate, precision, LR=TPR/FPR, Youden J with ITEM-bootstrap CI,
  permutation null.

## The four preregistered questions

- **Q1 COVERAGE (reported FIRST).** Fraction of transitions mechanically checkable;
  relation-type distribution per dataset/model; fraction of traces with ≥1
  checkable transition. A high J on 8% of reasoning is not a fraud proof.
- **Q2 CRUX — outside the extractor's competence.** Cells by the EXTRACTOR's own
  cached ability on that problem: (a) extractor solved it, (b) did not. Cell (b) J
  is decisive. Power disclosure: MATH base rate 0.128 → cell (b) has few errors;
  a null at small n is **UNDERPOWERED-NULL**, distinct from demonstrated null; n
  reported for every cell.
- **Q3 WEAK-EXTRACTOR TEST.** Strong (phi-4) vs weak (gemma-2) extractor, paired
  over identical traces: J, FPR, coverage. If weak ≈ strong, extraction is
  mechanical transcription and a cheap verifier can audit an expensive producer; if
  weak collapses, the competence bound re-entered via extraction (R5 = 6B in
  disguise). Plus extraction fidelity on a hand-checked sample.
- **Q4 ERROR-CLASS DISSOCIATION (the headline hypothesis, ties to round 3).**
  Round 3: CODE escaped attractors LEAST because it faithfully executes a
  miscomprehension. R5 is the same species — it can verify algebra but cannot know
  the first equation misrepresents the problem. PREDICTION: **high J on MATH**
  (algebraic slips), **near-zero J on NoOp** (comprehension errors: the setup
  incorporates an irrelevant quantity, then every step is algebraically perfect).
  Report the dissociation table; it is the headline, not a pooled number.

## Free ablation — detector independence

On the same MATH traces, cross-tabulate firing of R5 (mechanical), A2
self-inversion (cached), C1 trace-check (cached). Report pairwise φ, and the J of
the OR- and AND-combinations, in cell (a) and (b). Zero new generations.

## Cost

Mean tokens: generate a solution (cached), extraction per trace, CAS check (ZERO
model tokens — stated explicitly). The CAS has no marginal model cost (the
structural difference), but a cost advantage with null detection is not an
asymmetry.

## Decision rule

- **R5-LIVE**: cell-(b) J on MATH > 0.20 (CI excl 0) AND coverage ≥ 0.30 AND weak
  extractor within 0.10 J of strong → a non-intelligent checker breaks the
  competence bound; cheap mechanical fraud proofs exist for algebraic reasoning.
- **R5-COVERAGE-BOUND**: cell-(b) J > 0.20 (CI excl 0) but coverage < 0.30 → real
  but narrow.
- **R5-EXTRACTOR-BOUND**: strong cell-(b) J > 0.20 but weak collapses → competence
  bound re-entered via extraction; no economy.
- **R5-DEAD**: cell-(b) J CI includes 0 for both extractors → mechanical checking
  of NL traces does not break the bound either — completing a general negative
  result across LLM checkers, witnesses, localization, AND mechanical checkers.
Report Q4's dissociation regardless of which fires.

## Point predictions (stated now)

Coverage 0.25–0.50 (much of a MATH trace is ASSERTION); MATH cell-(a) J 0.4–0.7;
MATH cell-(b) J 0.15–0.40 (the open question, underpowered); NoOp J ~0–0.10 (the
predicted blind spot); weak-vs-strong gap small (0–0.15) IF transcription is
mechanical; R5×A2 φ moderate-positive. Prior: **30% R5-LIVE / 25% COVERAGE-BOUND /
20% EXTRACTOR-BOUND / 25% R5-DEAD.** Any single model/problem/transition driving a
cell → inconclusive.

## What R5 cannot do even if LIVE (stated now)

It verifies internal algebraic consistency, NEVER that the first equation
faithfully represents the problem (the comprehension gap), and it depends on
extractor honesty (a colluding extractor mis-transcribes). SEED=1, temp 0, cached.
