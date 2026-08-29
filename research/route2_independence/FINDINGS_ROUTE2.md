# Findings — Route 2 decisive engineered-independence experiment

Write-up per the pre-registration (PREREGISTRATION.md, committed before any
generation). The preregistered decision is reported first, then the numbers
that determine it, then the honest limits. Two of the reasons this result is
what it is were explicitly anticipated in the pre-registration.

## HEADLINE — the preregistered decision is UNREACHABLE (not LIVE / MIRAGE / CLOSED)

The LIVE/MIRAGE/CLOSED rule is evaluated on Δ(D) = excess(M1_same-model-samples)
− excess(M3_cross-method) and lift(M3) **in the HARD × LARGE stratum**. That
stratum cannot deliver a verdict, for **two independent reasons**, and the
honest classification is **BLOCKED / UNRESOLVED**:

1. **Output-space structure (the fundamental obstruction).** The LARGE
   wrong-answer stratum barely exists on MATH: **3 of 80 problems** have ≥5
   distinct wrong answers (HARD: **2 of 40**). The Route 2 mechanism can only be
   *tested* where there is room to disagree; that room is absent. Critically —
   and unlike the prior MBPP code result — this is **not** a shared-blind-spot
   convergence. It is **sparsity**: mean wrong-agents-per-problem ≈ 2.0 (HARD
   2.7) out of ~10, and among problems where ≥2 err, the median Simpson
   agreement is **0.0** (they *disagree* when they err). The space is small
   because errors are few and diverse, not because models pile onto one wrong
   answer.

2. **External data loss (an operational blocker, not a scientific null).** The
   OpenRouter account ran out of credits mid-run (HTTP 402). **486 / 1280
   generations (38%) failed**, clustered at the run tail. The **entire M1
   same-model-samples arm (320/320) was lost**, plus phi-4 DECOMP (80/80) and
   phi-4 CODE (68/80). With M1 gone, Δ = excess(M1) − excess(M3) cannot be
   formed from real data at all. (The pipeline is complete and cached; re-run
   `generate` after adding credits to fill the `__ERR__` cells and the decision
   becomes computable to the extent stratum #1 allows.)

Raw preregistered outputs, for the record (both degenerate — M1 unusable,
LARGE empty): Δ(HARD) point −0.01 (M1 is a missing-data artifact); lift(M3,HARD
× LARGE) = None (0 agreeing problems in 2 problems).

**This is a SUCCESS of the experiment, not a failure:** it shows the Route 2
question, as posed, is not answerable on MATH — the regime it targets does not
occur — and it names *why* (sparse diverse errors), which is more useful than a
forced LIVE/MIRAGE/CLOSED label would have been.

## The measured space-cardinality-by-difficulty table (the core finding)

Cardinality measured over the intact agents (see data-loss caveat; ~10 of the
16 planned agents were answer-bearing). CONSTRAINED = distinct_wrong ≤ 2,
LARGE = ≥ 5, MID = 3–4.

| stratum | n | CONSTRAINED | MID | LARGE | median distinct | mean m_wrong | median Simpson (when ≥2 wrong) |
|---|---|---|---|---|---|---|---|
| ALL  | 80 | 64 | 13 | **3** | 1.0 | 2.02 | **0.0** |
| EASY | 40 | 35 | 4  | **1** | 0.0 | 1.35 | 0.117 |
| HARD | 40 | 29 | 9  | **2** | 2.0 | 2.70 | **0.0** |

Read: on the median problem, at most one distinct wrong answer exists at all;
on HARD problems ~2.7 of ~10 agents err and they land on ~2 *different* wrong
answers (Simpson 0 = no pairwise convergence beyond chance). The "large diverse
wrong-answer space on hard problems" that Route 2 needs is essentially absent —
MATH errors from capable models are **sparse and diverse**, the opposite of the
MBPP code battery (there: Simpson ≈ 0.6, many models converging on one wrong
answer). The two studies together bracket the phenomenon: shared-blind-spot
convergence is task-dependent, strong on the constrained code battery, absent
here.

## What the intact data does show (directional; NOT the preregistered test)

M1 is gone, so no mechanism *contrast* is possible. But M2 (cross-family COT)
and M3 (cross-method, llama) are intact, and the **agreement trust-lift** (the
payoff metric: P(correct | pair agrees) − P(correct | single agent)) is
computable outside the empty LARGE stratum:

| mechanism | stratum | excess (95% CI) | trust-lift (95% CI) | single-agent acc |
|---|---|---|---|---|
| **M3 cross-method (llama COT/CODE/DECOMP)** | ALL | +0.126 [+0.049, +0.196] | **+0.270 [+0.251, +0.281]** | 0.64 |
| M3 cross-method | HARD | +0.046 [−0.013, +0.084] | **+0.40 [+0.383, +0.417]** | 0.48 |
| M3 cross-method | HARD × CONSTRAINED | +0.046 [−0.018, +0.161] | +0.32 [+0.29, +0.35] | 0.57 |
| M3 mixed model×method | ALL | −0.017 [−0.039, +0.008] | **+0.459 [+0.454, +0.479]** | 0.46 |
| M3 mixed model×method | HARD | −0.014 [−0.032, +0.004] | +0.527 [+0.495, +0.555] | 0.31 |
| M2 cross-family COT (1 banded pair) | HARD | −0.036 (1 pair) | +0.49 (1 pair) | 0.44 |

Two things, stated carefully:

- **Agreement IS a truth-signal on MATH, including on HARD problems.** When
  llama's three *methods* agree, the answer is right ~0.88 of the time versus
  0.48 single-agent (lift +0.40). Mixed model×method agreement is an even
  stronger signal (+0.53 on HARD). This is exactly because errors are sparse and
  diverse: a wrong answer rarely gets seconded, so agreement concentrates on
  truth. That is *encouraging for Route 2's premise*.
- **But this is not the preregistered claim, and does not establish engineered
  independence.** (a) It is measured outside the LARGE stratum the falsifier
  named. (b) Without M1, there is no maximal-correlation comparator, so we
  cannot show method-disjointness *decorrelates relative to same-model
  sampling* — only that agreement is informative, which sparse diverse errors
  alone would produce. (c) M3's excess is **positive overall** (+0.13, driven by
  EASY problems where the methods agree because they are all correct) and
  **straddles 0 on HARD** ([−0.013, +0.084]) — no evidence that forcing
  different methods *introduces* shared bias, and no evidence it removes any.

Robustness: R3 (CODE in vs out of M3) and R4 (EASY×LARGE, HARD×CONSTRAINED) are
reported in route2_result.json; the LARGE-restricted variants are empty/degenerate
(n≤2 problems), so R1–R4 add nothing decisive — consistent with the headline.
HARD×CONSTRAINED (n=29) M3 excess +0.046 [−0.018, +0.161] includes 0.

## Capability + data-integrity disclosure (honest limits, first-class)

COT accuracy (temp 0, 80 problems): llama-3.1-70b 0.625, gemma-2-27b 0.50,
mistral-small-3.2 0.4625, phi-4 0.6625. Capability band (within 0.10 of top):
**{llama, phi}** — so M2 cross-family reduces to a single banded pair, already
underpowered before the data loss.

Per-method answer (extraction) rates, disclosed per the honesty rule (parser
fixes only, never generation): COT 0.51–0.80, DECOMP 0.51–0.93 (phi-4 DECOMP
0.00 = 402), CODE 0.11–0.88 (phi-4 CODE 0.11, mostly 402; the executor +
\boxed-or-canonicalizable-value parser is validated in test_route2.py).

Data loss (route2_result.json → data_integrity): **486/1280 (38%) HTTP-402
failures.** Fully lost: M1COT 320/320, phi-4 DECOMP 80/80, phi-4 CODE 68/80.
Cardinality and all cells are therefore computed over ~10 intact agents, not
the planned 16. **The LARGE count (3/80) is thus a lower bound** — the four
missing llama temp-0.7 samples and two phi methods could add a few distinct
wrong answers on some problems. But the missing agents are dominated by four
*same-model* llama samples (low added diversity), and the median-1-distinct
convergence across the intact 4-family × 3-method pool is strong; adding six
agents (four of them near-duplicates) is very unlikely to move most median-1
problems past the ≥5 LARGE threshold. Direction robust; exact counts understated.

**Canonicalization is validated as conservative, not collapsing** (the artifact
that inflated the prior TruthfulQA headline). Verified on real outputs:
`\frac{243}{8}` ≡ `243/8`, and `67.5` ≡ `\frac{135}{2}` ≡ `67.5000000000000`
correctly merge to one signature, while genuinely distinct wrongs
(`175/35/133/207/23`) stay distinct; two independent `\text{No Solution}`
answers correctly merge (real convergence). If anything it slightly *over*-counts
distinct answers (formatting variants like `10^{th}` vs `10^{th} grade`), which
would inflate LARGE, not deflate it — so the empty-LARGE finding is not a
collapse artifact.

## What this means: Route 2 vs Route 1

- **The specific Route 2 claim under test — that forcing a model onto disjoint
  solution methods manufactures error-independence that *survives on hard tasks
  in a large output space* — is UNTESTED here.** Not refuted, not supported:
  the large-output-space regime it requires does not occur on MATH, and the
  same-model comparator was lost to an external credit failure.

- **The more fundamental obstruction is real and matters for the roadmap:** on a
  genuine reasoning benchmark with capable models, you cannot manufacture a
  large diverse wrong-answer space, because capable models rarely *co-fail*, and
  when they do they scatter. Route 2's failure mode is not "the mechanism
  doesn't decorrelate" — it is "there is nothing to decorrelate, because errors
  are already sparse and diverse." This is a different, and arguably better,
  world than the constrained-space MBPP result: agreement is already a strong
  truth-signal (lift +0.40 on hard) without any engineered independence.

- **Provisional read for the build decision:** do **not** treat this as a green
  light to build Route 2 (engineered method-independence) — the decisive test
  did not run. But the intact data undercuts the *pessimistic* case too: on
  MATH, plain agreement (even across methods of one model) already concentrates
  on truth. If the goal is "trust agreement as a truth-signal," the cheap
  version already works on this task; the expensive engineered-independence
  version is unproven and may be unnecessary where errors are naturally sparse.
  Where errors are *dense and convergent* (the MBPP regime), the prior work
  showed diversity does not help — so Route 2's value, if any, lives in a middle
  regime this experiment did not populate.

## To actually complete the preregistered test

1. **Credits.** Add OpenRouter credits and re-run `generate` (fills the 486
   `__ERR__` cells, incl. the whole M1 arm; cache makes the rest free). Cost to
   finish ≈ the unspent fraction of the $0.52 estimate.
2. **A task that populates LARGE.** MATH with capable models cannot supply a
   dense-diverse-error stratum. Testing Route 2 as designed needs a task where
   capable models co-fail *often* and in an *open* answer space — e.g. harder
   open-ended proof/derivation with a verifier, or a deliberately harder
   difficulty band where m_wrong is high. Until such a task exists, the
   HARD×LARGE cell will stay empty and the falsifier will stay unreachable —
   which is itself the finding.

## Status

Preregistered ✅ (committed before data, hash in git log) · instrument + tests
✅ (10/10 green) · generation ✅ but **38% lost to OpenRouter 402** (M1 arm gone)
· canonicalization validated conservative ✅ · **preregistered decision
UNREACHABLE** (output-space structure + data loss) · directional trust-lift
positive on hard (+0.40) but not the preregistered test · reproduce:
`python route2_experiment.py analyze` (cache-only, free); raw per-model outputs
cached in `route2_cache/` (git-ignored); result in `route2_result.json`.
