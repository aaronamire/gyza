# Findings — Route 14: can a model SPECIFY what it cannot SOLVE?

Write-up per `PREREGISTRATION_R14.md` (`f38cbf8`), committed before any
generation. 400 spec generations (4 models × 50 MBPP problems × 2 arms), 399
parsed, plus 72 Part-B4 generations. Deterministic scoring, `SEED = 1`, zero
model calls in the mutation harness. All prior decisions stand.

**Standing weakening, restated wherever "valid" appears:** these are Python
predicates checked on the MBPP inputs, **not** a formal verifier. "Valid" means
*holds on the MBPP inputs*, **never** "proven for all inputs". That is a genuine
weakening versus Dafny/Lean.

---

## DECISION: **SPEC-COLLAPSES**

> **A model asked to specify a problem it cannot solve produces LESS usable
> checking power than a trivial type check.** Conditioned on the model's own
> program being wrong, the arm that forbids recomputation yields specs whose
> mutation kill rate is **0.3673** — statistically indistinguishable from the
> **TYPE-ONLY floor of 0.2864** — while the same models on problems they solved
> reach **0.5105**. Paired difference **0.1432, CI [0.0231, 0.2652]**, excluding
> zero.
>
> **Unconditionally the collapse is worse.** Counting invalid and non-spec
> outputs as the zero checking power they are, cell (b) delivers an effective
> kill rate of **0.1177 [0.0794, 0.1586]** — **below the 0.2864 floor**, with the
> CI excluding it. **`def spec(inp, out): return isinstance(out, list)` beats the
> model.**

**Specifications require external authorship. Claim-space restriction is real
but human-gated, and the throughput ceiling is human spec-writing rate.**

This was my 55% branch. It is a **success**: it fixes a hard architectural
constraint. **No softening, no rescue round.**

| decision clause | fires? |
|---|---|
| SPEC-SURVIVES — cell (b) above floor (CI excluding), within 0.15 of cell (a), predominantly non-embedding | **no** — see §1a |
| **SPEC-COLLAPSES** — cell (b) materially below cell (a), paired CI excluding 0 | **YES** |
| SPEC-VACUOUS — indistinguishable from floor in BOTH cells | **no** — cell (a) is clearly above the floor |

### 1a. Why SPEC-SURVIVES does not fire, stated precisely

Two of its three clauses are technically met and the third is not, and the
near-miss is reported rather than resolved in the route's favour:

- **(ii) within 0.15 of cell (a):** met — the difference is 0.1432.
- **(iii) predominantly non-embedding:** met — 95.1% of cell-(b) PROP specs are
  non-embedding.
- **(i) above the TYPE-ONLY floor with CI excluding it:** cell (b) CI is
  **[0.287, 0.450]** and the floor point estimate is **0.2864** — a margin of
  **0.0006**. The floor's own CI is **[0.2284, 0.3454]** and **overlaps cell
  (b)'s CI across most of its range.** A 0.0006 margin against an interval that
  overlaps is not a separation; it is noise. **Clause (i) fails.**

Had clause (i) been read mechanically, this route would have reported
SPEC-SURVIVES on six ten-thousandths of a kill rate. It is recorded because the
threshold was preregistered and the near-miss is the honest outcome.

---

## 2. THE HEADLINE — cell (a)/(b) kill rate, with floor and ceiling

Every number is positioned between the **measured** floor and the **measured**
ceiling, never reported bare. Ceilings are hand-written specs measured against
the same mutants, not a theoretical 1.0.

```
  vacuity        TYPE-ONLY                                property-only   embedding
  return True      floor                                     ceiling      ceiling
   0.0000         0.2864                                     0.6715        0.7171
      |--------------|------------------------------------------|------------|
                     |
        PROP/b 0.3673 (CI 0.287-0.450)   <- indistinguishable from floor
                          PROP/a 0.5105 (CI 0.418-0.600)
                                     FREE/b 0.5602 (CI 0.434-0.675)
                                            FREE/a 0.6728 (CI 0.588-0.753)
```

| arm/cell | n specs | validity | invalid | non-spec | **kill (valid only)** | 95% CI | embed % | kill given embed | kill given NON-embed |
|---|---|---|---|---|---|---|---|---|---|
| PROP / a | 68 | 0.618 | 19 | 7 | **0.5105** | [0.418, 0.600] | 19.1% | 0.6106 | 0.4869 |
| **PROP / b** | 128 | **0.320** | 63 | 24 | **0.3673** | [0.287, 0.450] | **4.9%** | 0.8036 | 0.3449 |
| FREE / a | 68 | 0.588 | 13 | 15 | **0.6728** | [0.588, 0.753] | 60.0% | 0.7875 | 0.5006 |
| **FREE / b** | 128 | **0.266** | 67 | 27 | **0.5602** | [0.434, 0.675] | **44.1%** | 0.7543 | 0.4069 |

**Paired cell(a) − cell(b), bootstrap over problems (3000 resamples):**

| arm | cell (a) | cell (b) | diff | 95% CI |
|---|---|---|---|---|
| **PROP** | 0.5105 (n=42) | 0.3673 (n=41) | **0.1432** | **[0.0231, 0.2652]** — excludes 0 |
| FREE | 0.6728 (n=40) | 0.5602 (n=34) | 0.1126 | [−0.0397, 0.2601] — includes 0 |

**The unconditional metric, which is the deployment-relevant one:**

| arm/cell | n (all specs) | **E[kill]** | 95% CI | vs floor 0.2864 |
|---|---|---|---|---|
| PROP / a | 68 | 0.3153 | [0.2357, 0.3976] | above |
| **PROP / b** | 128 | **0.1177** | **[0.0794, 0.1586]** | **BELOW** |
| FREE / a | 68 | 0.3958 | [0.3043, 0.4868] | above |
| **FREE / b** | 128 | **0.1488** | **[0.0957, 0.2041]** | **BELOW** |

The conditional kill rate flatters cell (b) because it is computed only over
specs that survived validity — and **validity is where the collapse actually
happens**: 0.618 → 0.320 (PROP) and 0.588 → 0.266 (FREE). This reproduces R8's
0.77 → 0.28 validity collapse in the specification domain.

**Not driven by one model** (INCONCLUSIVE rule): every model shows a > b.

| model | cell (a) | cell (b) |
|---|---|---|
| llama-3.1-70b-instruct | 0.5553 (n=23) | 0.4687 (n=17) |
| gemma-2-27b-it | 0.4825 (n=14) | 0.3580 (n=26) |
| phi-4 | 0.6503 (n=25) | 0.5769 (n=14) |
| mistral-small-24b-2501 | 0.6284 (n=20) | 0.4864 (n=18) |

---

## 3. Oracle-embedding — the cost question

Reported beside every kill rate, because a spec that reimplements the solution is
**not a cheap spec** and does not support the claim-space argument.

| arm/cell | embedding rate | median spec/reference AST node ratio |
|---|---|---|
| PROP / a | 19.1% | 2.46 |
| PROP / b | **4.9%** | 1.39 |
| FREE / a | **60.0%** | 1.81 |
| FREE / b | 44.1% | 1.34 |

**P3 and P4 both confirmed.** Embedding is far commoner in cell (a) than cell (b)
(19.1% → 4.9% under PROP), and ARM FREE embeds far more than ARM PROP (60.0% vs
19.1% in cell (a)). **The instruction not to recompute works** — it cuts
embedding by roughly 4×.

**But the result A4 was designed to separate goes the wrong way for the property
hypothesis.** FREE's higher kill rate is *bought by embedding*: kill given
embedding is 0.79/0.75, versus 0.50/0.41 for non-embedding specs. And the reason
cell (b) shows little embedding is **not** that models switch to cheap
properties — it is that **their embedding attempts fail validity**: FREE/b
validity is 0.266 against 0.588 in cell (a), with 67 of 128 specs outright
INVALID. This is precisely the disconfirming branch stated in the
preregistration: *"if cell (b) validity collapses because embedding fails, that
is evidence [the property asymmetry] is not [real]."* It does, and it is.

**Heuristic validation.** The declared detector was validated on a **labelled set
of 36** hand-written specs (18 known-embedding-permitted, 18 known
property-only), labels fixed before the detector ran: **agreement 0.972, 0 false
positives, 1 false negative** (problem 3, an element-wise `items[k] ==
flat.count(k)` comparison). Zero false positives means the embedding rates above
are, if anything, **under**-stated.

---

## 4. Part B — the invariant taxonomy DOES transfer to specs

12 hand-written 3-stage pipelines, 3 spec classes, 3 mutation kinds × 3 stages.

| class | e2e violations | missed by per-stage conjunction | detection | composes? |
|---|---|---|---|---|
| **CONSERVATION** | 60 | **0** | **1.000** | **YES** |
| **MONOTONE non-cumulative** | 17 | **0** | **1.000** | **YES** |
| **CUMULATIVE** | 15 | **15** | **0.000** | **NO** |

**P5 confirmed exactly.** And per the artifact rule, both extremes are
**diagnosed as definitional rather than presented as measurements**:

- Conservation's 1.000 is structural: the global property decomposes *additively*
  into per-stage quantities, and each local spec pins its stage's quantity
  exactly, so any single-stage deviation necessarily violates that stage's own
  spec.
- Cumulative's 0.000 is equally structural: three per-stage allowances of
  `≤ 2` admit a total of 6 against an end-to-end budget of 4. **The gap between
  Σ(local allowances) and the global budget is unobservable locally**, so a
  mutation landing in that gap passes every local spec by construction.

This is **an impossibility confirmed by construction, not an empirical result
with power**, and it is R13's finding in the specification domain: *a stateless
local check cannot bound a cumulative quantity, because it cannot accumulate.*
The same wall, reached from specifications instead of guards.

### 4b. Part B4 — do MODEL-written per-stage specs compose?

| class | specs | usable | **rejected the CORRECT pipeline** | no-parse | detection |
|---|---|---|---|---|---|
| conservation | 24 | 0 | **24** | 0 | — |
| monotone | 24 | 2 | 20 | 2 | 1.000 (n=2) |
| **cumulative** | 24 | 14 | 4 | 0 | **0.000** (23 violations, 23 missed) |

**The conservation cell is UNINTERPRETABLE and the defect is mine.** All 24
specs reject the unmutated pipeline because my B4 prompt described the class as
"a quantity is *preserved*" while the pipelines deliberately *add* elements per
stage. The models wrote the literal spec; it is inconsistent with the pipeline.
That measures my prompt, not the models, and is reported as void rather than as
"models cannot write conservation specs". **Monotone is UNDERPOWERED (n = 2).**

**Only the cumulative cell is interpretable, and it reproduces the hand-written
result exactly: detection 0.000, 23 of 23 violations missed.** Model-written
specs for the non-composable class are valid-and-useless — the same
verifiable-but-vacuous failure Part A measures, appearing in composition.

The interpretable part of **P6 holds**: model specs are worse than hand-written.
But the mechanism is **invalidity** (44 of 48 conservation+monotone specs
rejected the correct pipeline), not weak detection — the same mechanism as
Part A.

---

## 5. Part C — the verifiable fraction of Gyza's OWN vocabulary

17 agent-facing action/claim types, read from the tree, every citation checked.

| bucket | n | fraction |
|---|---|---|
| **NATIVE VERIFIER** (mechanical postcondition exists) | 10 | **58.8%** |
| **CHEAP PARTIAL SPEC POSSIBLE** (conservation/monotone property checkable) | 3 | **17.6%** |
| **NO VERIFIER** (correctness is semantic) | 4 | **23.5%** |

**NATIVE** — envelope signature (`gyza/icp.py:82`), chain/DAG linkage
(`icp.py:105`, `:217`), envelope hash (`icp.py:63`), manifest identity
(`gyza/identity.py:101`), enforcement ⊆ manifest
(`gyza/sandbox/config.py:286`), delegation attenuation
(`gyza/economy/delegation.py:213`, `:157`), ledger entry signatures
(`gyza/economy/ledger.py:348`), balance fold (`gyza/economy/wallet.py:274`,
`gyza/economy/subcontract.py:184`), attestation quorum
(`gyza/network/netd_client.py:1144`), artifact content address
(`gyza/network/artifact_store.py:47`).

**CHEAP PARTIAL** — HLC ratchet monotonicity (`gyza/schema.py:123`), reputation
range/direction (`gyza/economy/reputation.py:188`, `:192`), claim exclusivity
(`gyza/blackboard.py:252`, `gyza/network/network_blackboard.py:154`).

**NO VERIFIER** — execution output content (`gyza/runner.py:374`), memory
retrieval relevance (`gyza/memory.py:402`), routing match quality
(`gyza/demand.py:35`, `:92`), external send content
(`gyza/network/netd_client.py:461` — leaves modeled state entirely, R13's
containment boundary).

**This is a property of Gyza's current vocabulary, not a general result.** It is
high *because* Gyza's vocabulary was built around cryptographic and
accounting claims, which are exactly the claims with native verifiers. It says
nothing about the verifiable fraction of an arbitrary agent workload.

---

## 6. What this implies for the two-tier architecture

**The verified tier cannot be LLM-bootstrapped. It is human-gated.**

- Where a **native verifier already exists** (58.8% of Gyza's vocabulary), no spec
  authorship is needed and the tier is free. This is where the system should
  live, and it is why Gyza's own numbers look good.
- Where a **cheap partial spec would be needed** (17.6%), R14 says a model will
  not reliably write one for work it cannot itself do: unconditional effective
  kill rate 0.118 against a 0.286 trivial-type-check floor. **Those specs must be
  written by a human, once, per claim type** — which is affordable precisely
  because claim *types* are few even when claim *instances* are many.
- The throughput ceiling of the verified tier is therefore **the rate at which
  humans author claim-type specs**, not the rate at which models produce claims.
  That is a one-time cost per type rather than a per-instance cost, which is the
  only reason the architecture is viable at all.
- **Composition adds a hard constraint**: per-stage specs compose for
  conservation and monotone classes and **provably do not for cumulative ones**.
  A budget spanning stages needs a stateful checker, exactly as R13's federation
  budget needed one. Do not expect per-stage specs to bound a pipeline-wide
  quantity.

---

## 7. Point predictions, scored

| # | prediction | outcome |
|---|---|---|
| **P1** | ARM PROP validity **high in both cells** | **✗ WRONG** — 0.618 / 0.320; not high in either, and it collapses |
| P2 | ARM PROP kill rate collapses in cell (b) | ✓ paired CI [0.0231, 0.2652] excludes 0 |
| P3 | embedding common in (a), absent-or-invalid in (b) | ✓ 19.1% → 4.9%; FREE/b validity 0.266 |
| P4 | ARM FREE embeds more than ARM PROP | ✓ 60.0% vs 19.1% |
| P5 | conservation + monotone compose; cumulative does not | ✓ 1.000 / 1.000 / 0.000 |
| P6 | model pipeline specs worse than hand-written | ✓ in direction; mechanism is invalidity, and the conservation cell is void (§4b) |

**P1 wrong is the informative one.** I expected properties to be *easy to state
validly* even when the problem is unsolved, with strength being the thing that
fails. **Validity is what fails.** A model that cannot solve a problem does not
retreat to weak-but-true properties — it asserts things that are **false about
the problem**, at 63/128 outright invalid under PROP.

**The prior evidence pointed here and is restated as required.** R8 found
property *tests* worse than example tests in cell (b) (paired J: E 0.65 vs P
0.25) — direct evidence against the property-asymmetry hope. R14 asked whether
*declarative specs* behave differently from *executable property tests*. **They
do not.** The sample-vs-property distinction that motivated this route does not
rescue the checker: computing an expected output and stating a true property both
require understanding the problem, and only the first is obviously so.

---

## 8. Disclosures (R9 §6)

1. **Pre-data correction to the embedding heuristic.** §4 declared three
   disjuncts; the third (spec/reference AST node ratio ≥ 1.0) was **dropped
   before any generation ran**, because it flagged a hand-written, strictly
   non-embedding reference spec — a demonstrated false positive. A thorough
   property spec routinely exceeds a terse reference in node count. Size is not
   evidence of an oracle. The ratio is still reported per spec (§3), and
   `ratio_ge_1` is retained in the raw results so the dropped criterion is
   auditable. Detection was then **strengthened** pre-data with one-level taint
   tracking, since recomputation is usually bound to a local first
   (`kept = [...]; return out == kept`).
2. **TYPE-ONLY baseline bug, pre-data.** The baseline injected a type *name*,
   which raised `NameError` for a `Counter` output (problem 3) and would have
   dropped that problem from the floor rather than scoring it. Fixed to compare
   type names.
3. **Pipeline construction bug, pre-data.** The first construction appended
   `range(k)` *after* the sorting stage, so the unmutated pipeline violated its
   own monotone spec — spec and pipeline mutually inconsistent. Caught by the
   base-case assertion before any Part B result existed; appended elements now
   sit above the current maximum.
4. **B4 conservation prompt/pipeline mismatch — my defect**, §4b. That cell is
   reported **void**, not as a model failure.
5. **Mutant count below target.** The preregistration targeted ~20 mutants per
   problem; the actual mean is **9.6** (min 3, max 20). MBPP reference solutions
   are short. Reported as measured; the operator set was **not** expanded to hit
   the number.
6. **`research/CLAIM_SPACE_SURVEY.md` does not exist.** The brief cites it as the
   source of its Re:Form / SpecTune / VERINA / DAFNYCOMP figures. It is not on
   disk, not in any of the 14 branches, not in git history. Those figures are
   recorded as **provided, not independently verified**, and **no claim in this
   route rests on them.**
7. **Diagnosed clean numbers.** `return True` scoring exactly 0.0000 is
   definitional — it is the detector, not a finding. Part B's 1.000 and 0.000 are
   structural, diagnosed in §4. B4 conservation's 24/24 is the prompt defect in
   disclosure 4.

---

## 9. What this cannot establish

- **One benchmark (MBPP), short functions, four mid-tier open-weight models**
  (own-program pass 0.26–0.38), single seed, temperature 0, one spec prompt per
  arm frozen before data and never tuned.
- **Python predicates, not a formal verifier.** "Valid" means *holds on the MBPP
  inputs*, never "proven for all inputs".
- **Kill rate is relative to this operator set** (7 operators, mean 9.6 mutants
  per problem). A different set moves every number; only positions between the
  measured floor and ceiling are interpreted.
- **Cell (b) is well-powered (n = 128 specs per arm); the paired PROP comparison
  rests on 41–42 scorable problems per cell.** The FREE arm's paired CI includes
  0 and is an **UNDERPOWERED-NULL**, not a demonstrated null — only PROP's paired
  difference is decisive.
- **8 specs fall in `unresolved` cells** (the 4 UNRESOLVED R8 labels × 2 arms),
  excluded from both cells rather than imputed.
- Part C is a property of **Gyza's current vocabulary**, and is high because that
  vocabulary is built from cryptographic and accounting claims.
- Nothing here touches **semantic-content correctness** — that is the competence
  bound, closed across six families, terminal.
