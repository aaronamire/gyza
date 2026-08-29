# Findings — Route 5: mechanical step verification

DECISION first, then coverage (Q1), the cell (a)/(b) table (Q2), weak-vs-strong
extractor (Q3), the MATH-vs-NoOp dissociation (Q4), independence, cost, limits.
**NOT a Route 2 rescue**; a different checker class (a CAS). The Route 2 terminal
decision and all prior decisions stand.

## DECISION — R5-DEAD (the competence bound holds for mechanical checkers too)

A non-intelligent checker (sympy) does **not** break the competence bound that
killed every LLM checker. R5-DEAD on two **demonstrated** grounds plus one
underpowered one:

1. **Coverage 0.20** (< the 0.30 LIVE bar) — most reasoning is not mechanically
   checkable at all. **Demonstrated.**
2. **The extraction bottleneck re-imports the competence dependence.** The CAS is
   sound, but it can only check what an LLM *transcriber* gives it, and that
   transcription is unreliable and **model-dependent** (strong and weak extractors
   give *opposite* J on identical traces). **Demonstrated.**
3. Cell-(b) (outside the extractor's competence) is **UNDERPOWERED** (n_wrong=7):
   strong J=0.286 but CI [0, 0.667] includes 0 — cannot conclude either way.

Combined with 6B (LLM cross-checking) and 7 (witness + localization), this
**completes a general negative result**: the competence bound holds across LLM
checkers, witnesses, localization, AND mechanical checkers — because even a
"mechanical" verifier needs an LLM to translate natural-language reasoning into
checkable form, and that translation re-imports the competence dependence and adds
noise. The CAS's non-intelligence does not help when the pipeline in front of it is
an LLM.

## Q1 — Coverage (reported first)

MATH transitions by relation (strong extractor, all sources): **ASSERTION 1020
(the plurality)**, IDENTITY 928, SOLUTION_SET 635, SUBSTITUTION 215,
NOT_EXTRACTABLE 128. **Mechanically-checkable fraction = 0.202**; fraction of traces
with ≥1 checkable transition = 0.43; JSON parse-fail 0.20 (partly long-trace
truncation, salvaged where possible); **protocol-violation rate = 0.0** (the
transcriber role held — the extractor never commented on correctness). NoOp
checkable fraction 0.28. A detector that can inspect ~1/5 of reasoning is not a
general fraud proof regardless of accuracy on that fifth.

## Q2 — Does it work outside the extractor's competence? (cells by EXTRACTOR ability)

| extractor / dataset | cell | n | n_wrong | J [CI] | FPR |
|---|---|---|---|---|---|
| strong (phi-4) MATH | ALL | 218 | 28 | **−0.089** | 0.232 |
| strong MATH | (a) solved | — | — | −0.159 | 0.243 |
| strong MATH | **(b) failed** | 10 | **7** | **0.286 [0.0, 0.667]** | 0.0 |
| weak (gemma-2) MATH | ALL | 218 | 28 | **+0.149** | 0.316 |
| weak MATH | (b) failed | — | 24 | −0.042 [−0.33, 0.25] | — |

Overall J is **≈0 or negative** for both extractors — the detector fires on ~23–32%
of *correct* traces (FPR), and TPR does not exceed it. **The high FPR is entirely
extraction noise**: of 67 correct traces that false-fire, every examined one is a
transcription artifact — a **conditional equation** (`x=8`, `x+(x+20)=180`) or a
**definition** (`mean=…`, `abc=−r`) that the extractor mislabelled IDENTITY, which
the CAS then correctly flags as a false *identity*. The CAS is right; the
transcription is wrong. Cell-(b) shows a faint positive lean (J=0.286, FPR 0) but
**n_wrong=7, CI includes 0 → UNDERPOWERED-NULL**, not a demonstrated null.

## Q3 — Weak vs strong extractor (the confound test)

| extractor | J (MATH) | coverage |
|---|---|---|
| strong (phi-4) | **−0.089** | 0.211 |
| weak (gemma-2) | **+0.149** | 0.218 |

Coverage is nearly identical, but the **J's have opposite sign** (gap 0.237,
≫ 0.10). Same CAS, same traces, two extractors → *opposite* detection. **Extraction
is not mechanical transcription — it is model-dependent judgement.** This is the
R5-EXTRACTOR-BOUND signature: the competence bound re-entered through the extractor.
R5 is 6B in disguise, with a sound but starved CAS at the end.

## Q4 — MATH vs NoOp dissociation (the headline hypothesis: refuted)

| extractor | MATH J | NoOp J |
|---|---|---|
| strong | −0.089 | −0.190 |
| weak | +0.149 | −0.074 |

Prediction was **high-MATH / ~zero-NoOp**. It did **not** materialise: both datasets
are ≈0/negative because extraction noise dominates. There is a *faint* echo — MATH
J > NoOp J for both extractors — hinting the predicted dissociation (mechanical
checking catches algebraic slips but is blind to comprehension errors) might exist
with a cleaner extractor, but it **cannot be established here**. The round-3 blind
spot (a mechanical checker cannot know the first equation misrepresents the problem)
is not testable when the checker cannot reliably see the algebra either.

## Independence ablation (cache-only)

On identical MATH traces: **J_R5 = −0.09** (dead), J_A2 = 0.45, J_C1 = 0.43.
φ(R5, A2) = 0.14, φ(R5, C1) = 0.06 (weakly correlated). **J of OR-combination =
0.38** — i.e. the OR just recovers the A2/C1 level; **R5 adds nothing** because it
is noise, not an independent signal. Aggregation does not clear any bar.

## Cost

Mean output tokens: generate a solution 388; **extraction 343 (0.88× generation)**;
**CAS check 0 model tokens**. The CAS having zero marginal model cost is the
structural difference from every prior mechanism — but the *extraction* it requires
costs almost as much as solving the problem, and detection is null. Cheaper-CAS with
null detection and expensive extraction is not an asymmetry.

## Honest limits

- **The CAS is sound; the pipeline is not.** 7/7 unit tests pass, including zero
  false fires on a hand-built correct 10-transition trace and the random-point /
  domain-guard / solution-set discipline. The failure is the **LLM extraction
  stage**, not the verifier.
- **Parser-fix disclosure.** Three extraction-parsing fixes were made and disclosed:
  (i) handle `=` in transcribed sides, (ii) salvage truncated JSON arrays, (iii) a
  per-equation-as-identity variant that was **reverted as unsound** (it treated
  conditional equations as identities, inflating FPR — the false-fire diagnosis
  above). The final routing (equation→equation ⇒ solution-set; single equation ⇒
  identity; expression pair ⇒ identity) is a-priori defensible, not FPR-tuned.
- **Cell-(b) underpowered** (n_wrong=7): the "outside competence" question is not
  definitively answered; but coverage (0.20) fails the LIVE bar independently, and
  the extractor J-gap (0.24) demonstrates model-dependence regardless.
- **What R5 cannot do even in principle**: verify that the *first* equation
  represents the problem (the comprehension gap), and it depends on extractor
  honesty. Here it could not even reliably verify internal algebra, because the
  transcription was unreliable.
- One task family; extraction max_tokens=900 truncated the longest traces (salvaged
  partially). A domain with a *native* formal form (code + unit tests, Lean/Coq +
  kernel) would not have this extraction problem — which is precisely why those
  domains *do* have cheap fraud proofs and natural-language mathematical reasoning
  does not.

## What it means

Optimistic verification works (PoW, rollups, formal proofs) because the claim is
**already** in a mechanically-checkable form. Natural-language LLM reasoning is not,
and the step that converts it — extraction — is itself an LLM subject to the same
competence bound and adds transcription noise a CAS then faithfully flags. So the
non-intelligence of the verifier does not buy the asymmetry; the asymmetry lives in
the **representation**, not the verifier. For a bonded system over LLM reasoning:
restrict claims to a checker's competence (6B cell-a), or move the work into a
domain with a native formal verifier — mechanical checking of prose reasoning does
not break the bound.
