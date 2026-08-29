# Route DR — DOMAIN RESTRICTION. PREREGISTRATION

**Committed before any result artifact.** Print this file's hash; confirm it
predates `dr_result.json` and `FINDINGS_DR.md`.

---

## 0. Citation checks against the tree (a prior session got one wrong)

| claim | verified |
|---|---|
| R14 Part C: 61.1% of 18 types have a native verifier | **confirmed** — registry has 18 types; PROOF+TEST = 11/18 = **0.6111** exactly |
| SR-3: PROOF 1.000, SPEC 1.000, TEST 0.000 | **confirmed**, `FINDINGS_SR3.md` |
| AR-1: chains 100% PROOF-carried, flat to depth 8, correctness 0.0 at every depth | **confirmed**, `FINDINGS_AR1.md` |
| mbpp_truth agreement 0.9439, false_wrong 11, false_correct 0 | **confirmed**, `mbpp_truth.json` |
| `research/THE_CORE.md` | **absent**; not used |
| CLAUDE.md §7 native-packaging unmerged | **CORRECT, and my own last-session "correction" of it was WRONG** — see Part 0 report |

## 1. GATE 0b — the verifier registry, cited, and NONE authored here

Every verifier used in scoring pre-exists this route. Enumerated with citations
from `gyza/verification/adapters.py`:

| claim type | carrier | implementation |
|---|---|---|
| envelope_signature | PROOF | `gyza/icp.py:82` |
| envelope_chain | PROOF | `gyza/icp.py:105` |
| envelope_dag | PROOF | `gyza/icp.py:217` |
| manifest_identity | PROOF | `gyza/identity.py:101` |
| enforcement_within_manifest | PROOF | `gyza/sandbox/...` |
| delegation_attenuation | PROOF | `gyza/economy/delegation.py:213` |
| ledger_entry_signatures | PROOF | `gyza/economy/ledger.py` |
| balance_fold | PROOF | `gyza/economy/wallet.py:274` |
| market_capital_fold | PROOF | `gyza/economy/market.py` |
| artifact_content_address | PROOF | `gyza/network/artifact_store.py:47` |
| unit_test_execution | **TEST** | V-3 adapter (finite sample) |
| hlc_ordering / reputation_score / work_claim_exclusivity | SPEC | human-authored, `adapters.py:121-130` |
| execution_output_content, memory_retrieval_relevance, routing_match_quality, external_send_content | **NONE** | `NO_VERIFIER` |

**Vocabulary: 18 types = PROOF 10, TEST 1, SPEC 3, NONE 4.**

Semantic ground truth comes from **MBPP's own asserts, re-executed** — external
to this program and to any model. **No verifier in this route is model-authored
or authored by me for the task it checks**, asserted by
`test_no_verifier_was_authored_during_this_route` with a negative control.

## 2. The two architectures, operationalized

A **task** is a chain of `d` claim steps. Each step's type is drawn from the
18-type vocabulary **uniformly at random** (declared now; the corpus's empirical
frequencies are not used because the corpus vocabulary is PR-shaped, not
Gyza-shaped, and mixing them would be artifact #17's species).

- **GENERAL** — attempts every chain. A step whose type has a verifier is
  checked; a step whose type has none is **executed and accepted unverified**,
  bounded only by containment.
- **RESTRICTED** — attempts a chain **only if every step's type composes**, i.e.
  carrier ∈ {PROOF, SPEC}, which is exactly the set SR-3 licenses (TEST scores
  0.000 and forces its chain to tier 3). Otherwise the chain is **REFUSED** —
  not escalated, not attempted-and-flagged. A refusal produces no output and is
  a **coverage miss counted separately**, never a correctness failure.

**Sensitivity arm declared now, not added later:** `RESTRICTED-PROOF-ONLY`
(carrier = PROOF, p = 0.5556) is reported beside the main arm because the choice
to admit SPEC is an architectural judgement, not a measurement.

**Ground truth per step:**
- **NONE-carrier steps** are realized by drawing a real MBPP sample from
  `research/corpus/stochastic.json` (K=5 at T=0.7, per-sample outcomes executed
  against MBPP's asserts). **Measured reliability 0.3790.** Zero new generation.
- **PROOF/SPEC/TEST steps** are realized by performing a real gyza operation
  with a fault injected at rate `f`; the registered verifier decides.

**`f` is a SWEPT PARAMETER, declared now: f ∈ {0.00, 0.05, 0.20}.** No
measurement of the real mechanical-fault rate exists, so a single value would be
invented. Results are reported for all three; if the decision differs across
them, the route reports the dependence rather than picking one.

## 3. Metrics — none may be reported alone

1. **COVERAGE** — fraction of tasks the architecture attempts at all.
2. **CORRECTNESS ON ATTEMPTED** — fraction of attempted tasks whose end result
   is verified correct by the external verifier.
3. **USEFUL WORK = 1 × 2.** Exists because refusing everything gives correctness
   1.0 and useful work 0 — the architectural form of TPR-without-FPR.
4. **COMPOSED CORRECTNESS** at depths **1, 2, 4, 8** — the decisive metric,
   because it is the only one where the architectures differ in KIND.

## 4. GATE 0c — FEASIBILITY CEILING, computed under the mechanism's own dynamics

Vocabulary composition is fixed by the registry; semantic reliability is
measured. The attainable ranges therefore follow analytically **before any
run**, and are stated here so nothing below can be presented as a surprise:

| d | RESTRICTED coverage `p^d` (p=0.7222) | GENERAL correctness `0.379^(0.2222d)` |
|---|---|---|
| 1 | 0.7222 | 0.8061 |
| 2 | 0.5216 | 0.6497 |
| 4 | 0.2721 | 0.4221 |
| 8 | 0.0740 | 0.1782 |

**Per-step log decay: RESTRICTED −0.3254, GENERAL −0.2156.**

> **THE PROJECTION, DECLARED: RESTRICTED DECAYS FASTER, SO THERE IS NO CROSSOVER
> ON USEFUL WORK AT ANY DEPTH.** Restriction pays 1 − 0.7222 = 0.2778 per step
> in refusals; the general architecture pays only 0.2222 × (1 − 0.379) = 0.138
> per step in undetected error. **The coverage penalty is the harsher of the
> two.**

**This contradicts the task prompt's expectation of a crossover between depth 2
and 4.** A prompt loses to arithmetic derived from committed findings, and the
disagreement is reported rather than resolved in the prompt's favour.

**Non-vacuity check (0c):** RESTRICTED completes 0.0740 of depth-8 tasks, which
is > 0, so the comparison is not vacuous and the route is MEASURABLE. At depth
16 it would be 0.0055 and the cells would be underpowered; **depth is capped at
8** for that reason.

## 5. GATE 0d — credit

Key at **`research/correlated_failure/.env`**, gitignored and loaded **by file
path** (`run_openrouter.py:31`) — which is why an environment scan misses it.
Balance **$3.121** (total 5.000, used 1.879).
**Estimate $0.00 — this route generates nothing.** Semantic ground truth is
reused from `stochastic.json`, already paid for. Gate passes trivially; it is
recorded because a route that needs no credit should say so rather than appear
to have skipped the gate.

## 6. Decision rule

- **DOMAIN-RESTRICTION-WINS** — RESTRICTED useful work ≥ GENERAL's **and**
  composed correctness at depth 8 higher by > 0.20 absolute.
- **DOMAIN-RESTRICTION-LOSES** — RESTRICTED useful work materially lower
  (equivalence bound **5pp**) **with no** composed-correctness advantage.
- **DOMAIN-RESTRICTION-SPLITS** — RESTRICTED wins composed correctness, loses
  useful work. Deliverable is the **crossover depth**, or an explicit statement
  that none exists.

Any single claim type, depth, or verifier driving a cell → **INCONCLUSIVE** for
that cell.

## 7. Point predictions, with a prior

| outcome | prompt's prior | **mine** |
|---|---|---|
| WINS | 0.25 | **0.05** |
| LOSES | 0.25 | 0.15 |
| **SPLITS** | 0.50 | **0.80** |

**My prediction, to be scored:** SPLITS, **with NO crossover** — RESTRICTED wins
composed correctness at every depth and loses useful work at every depth, the
gap widening monotonically. I expect RESTRICTED correctness-on-attempted ≈ 1.0
at f = 0 and **that value is DEFINITIONAL** (§8). Part 3: 20–40% RESPECIFIABLE.

## 8. The definitional hazard, named in advance

**RESTRICTED's correctness-on-attempted will be near 1.0, and at `f = 0` it is
DEFINITIONAL, not measured**: a task attempted only when an exact verifier exists,
and scored by that verifier, is close to scoring itself. What is **MEASURED** is
(a) the vocabulary fraction that composes, (b) semantic-step reliability 0.3790,
and (c) the resulting curves. The `f > 0` arms exist precisely so the flat curve
reflects *detection* rather than *absence of faults*. Every cell is labelled.

## 9. Part 3 is an AUTHORED JUDGEMENT, not a measurement

The RESPECIFIABLE / IRREDUCIBLY-SEMANTIC / UNCLEAR classification is **my
judgement**, will be labelled as such, and must not be read as data. For every
RESPECIFIABLE type I will state **what the restatement LOSES**; a claim that is
verifiable because it no longer asks for anything useful is IRREDUCIBLY
SEMANTIC, not a win.

## 10. What this cannot establish

Two substrates, one vocabulary (Gyza's, cryptographic/accounting — the kind that
*has* native verifiers), mid-tier open-weight models, `d ≤ 8`, synthetic chain
composition. It says nothing about vocabularies unlike this one, and Part 3 is
authored judgement.
