# Findings — Route DR: domain restriction vs the general architecture

Write-up per `PREREGISTRATION_DR.md` (`592114f`, sha256 `225add96…`), committed
before any result. 36 cells × 4000 tasks, deterministic, `SEED = 1`, **zero
model calls, $0.00 spent** — semantic ground truth reused from the corpus's
stochastic arm (MBPP asserts re-executed). 11 gate tests green. Disclosures in §7.

---

## DECISION: **DOMAIN-RESTRICTION-SPLITS — with NO crossover, and the split is not the one the metrics were built for**

> **RESTRICTED loses useful work at every depth and every fault rate, and the
> gap widens monotonically. It never crosses over — not at depth 8, and not even
> if every semantic claim type in the vocabulary were respecified into a
> verifiable form.**
>
> **But RESTRICTED's SILENT-WRONG rate is 0.0000 in every one of the 36 cells,
> against GENERAL's 0.1275 rising to 0.7020.** The architectures do differ in
> kind — just not along the axis the preregistered metrics measured. The
> difference is not *correctness vs coverage*. It is **undetected wrongness vs
> refusal.**

| clause | fires? |
|---|---|
| DOMAIN-RESTRICTION-WINS | **no** — useful work lower at every depth |
| DOMAIN-RESTRICTION-LOSES | **no** — there IS a composed advantage, and it is total |
| **DOMAIN-RESTRICTION-SPLITS** | **YES**, with no crossover on useful work |

**Prior vs outcome.** Prompt: 25 WINS / 25 LOSES / 50 SPLITS. Mine (stated in
§7 of the preregistration): 5 / 15 / **80 SPLITS with no crossover**. **SPLITS
fired, and the no-crossover prediction was correct** — it was derived
analytically at Gate 0c before the run and contradicted the prompt's expectation
of a crossover between depths 2 and 4.

---

## 1. The measured table (f = 0.00; all three fault rates in `dr_result.json`)

| depth | arm | coverage | correctness \| attempted | **useful work** | **silent-wrong rate** |
|---|---|---|---|---|---|
| 1 | GENERAL | 1.0000† | 0.8725 | **0.8725** | 0.1275 |
| 1 | RESTRICTED | 0.7225 | 1.0000† | 0.7225 | **0.0000†** |
| 2 | GENERAL | 1.0000† | 0.7428 | **0.7428** | 0.2572 |
| 2 | RESTRICTED | 0.5255 | 1.0000† | 0.5255 | **0.0000†** |
| 4 | GENERAL | 1.0000† | 0.5510 | **0.5510** | 0.4490 |
| 4 | RESTRICTED | 0.2752 | 1.0000† | 0.2752 | **0.0000†** |
| 8 | GENERAL | 1.0000† | 0.2980 | **0.2980** | 0.7020 |
| 8 | RESTRICTED | 0.0755 | 1.0000† | 0.0755 | **0.0000†** |

† **DEFINITIONAL, flagged in advance** (preregistration §8) — see §6.

**Crossover depth: NONE, at any fault rate.** `crossover_depth_useful_work` is
`null` for f = 0.00, 0.05 and 0.20.

**The arithmetic behind it, and it is the whole result.** Per step, restriction
pays `1 − 0.7222 = 0.2778` in refusals while the general architecture pays only
`0.2222 × (1 − 0.3790) = 0.1380` in undetected error. In log space the decay
rates are **−0.3254 for RESTRICTED against −0.2156 for GENERAL**. Restriction's
coverage penalty is simply the harsher of the two, and no depth reverses a
comparison of exponents.

---

## 2. THE RESPECIFIABILITY CEILING — restriction cannot win even at the limit

This is Part 3's decisive number and it settles the architecture question.

| NONE types respecified into PROOF | p(RESTRICTED) | RESTRICTED log decay | GENERAL log decay | winner |
|---|---|---|---|---|
| 0 (today) | 0.7222 | −0.3254 | −0.2156 | GENERAL |
| 1 | 0.7778 | −0.2513 | −0.1617 | GENERAL |
| 2 (my classification, §3) | 0.8333 | −0.1823 | −0.1078 | GENERAL |
| 3 | 0.8889 | −0.1178 | −0.0539 | GENERAL |
| **4 (every semantic type respecified)** | 0.9444 | −0.0572 | **0.0000** | **GENERAL** |

> **Respecification helps BOTH architectures, and it helps GENERAL more.** Moving
> a type into the verified tier removes a *refusal* for RESTRICTED but removes an
> *error source* for GENERAL — and GENERAL's penalty applies only to the semantic
> fraction, while RESTRICTED's applies to everything it refuses, which still
> includes the TEST-carried type SR-3 forbids it from composing.
>
> **There is no vocabulary design under which domain restriction wins on useful
> work.** That is a stronger statement than the measurement asked for, and it
> closes the alternative on this axis rather than on this dataset.

---

## 3. Part 3 — respecifiability. **AN AUTHORED JUDGEMENT, NOT A MEASUREMENT**

Labelled as such in the preregistration (§9) and repeated here: this is my
classification of 4 claim types. It is not data.

| type | bucket | restatement | **what the restatement LOSES** |
|---|---|---|---|
| `execution_output_content` | **IRREDUCIBLY SEMANTIC** | "output hash = H", checkable by re-execution | **whether the output is right.** A deterministic wrong program passes every time. The restatement verifies reproducibility and discards exactly the property wanted. |
| `routing_match_quality` | **IRREDUCIBLY SEMANTIC** | "routed to argmax of declared-capability overlap F" | **whether declared capability predicts competence.** R11 ROUTER-DEAD measured that difficulty routing fails even with an AUROC-1.000 oracle — so the restatement is verifiable *and known not to deliver the value*. Verifiable and worthless is not a win (3d). |
| `memory_retrieval_relevance` | **RESPECIFIABLE** | "the k nearest neighbours under metric M above threshold t" | whether nearness under M *is* relevance. Real loss — but the restatement still buys something: retrieval becomes reproducible and auditable, and M is evaluated **once** by a human instead of per query. |
| `external_send_content` | **RESPECIFIABLE** | "bytes sent = artifact A with hash H, approved by policy P" | whether sending was a good idea. But **containment ends at emission regardless**, so non-repudiation of *what left* is close to the whole of what is obtainable at that boundary. |

**2 RESPECIFIABLE / 2 IRREDUCIBLY SEMANTIC / 0 UNCLEAR — 50% of the NONE bucket,
11.1% of the vocabulary.** My preregistered prediction was 20–40% respecifiable
*of the vocabulary*; measured against the NONE bucket it is 50%, against the
whole vocabulary 11.1%. **The prediction was ambiguous about its denominator and
I am reporting both rather than picking the flattering one.**

Applying 3d strictly is what moved `routing_match_quality` out of RESPECIFIABLE:
its restatement passes a mechanical check while a committed finding says the
restated property does not deliver what was wanted.

---

## 4. What actually differs in KIND: the silent-wrong rate

| depth | GENERAL silent-wrong | RESTRICTED silent-wrong |
|---|---|---|
| 1 | 0.1275 | **0.0000** |
| 2 | 0.2572 | **0.0000** |
| 4 | 0.4490 | **0.0000** |
| 8 | **0.7020** | **0.0000** |

At depth 8 the general architecture returns an **undetected wrong answer 70% of
the time it is asked**, and by construction nobody downstream can tell. The
restricted architecture returns one **never** — every fault is caught by an
exact verifier and the chain aborts.

**Neither number is the guarantee people usually reach for.** RESTRICTED's
guarantee is *not* "the answer is correct"; at f = 0.20 its
correctness-on-attempted falls to 0.1623 at depth 8, because faults are detected
and the chain aborts. Its guarantee is **"never silently wrong"** — refusal and
detection, not correctness.

### The break-even, which is the practical deliverable

RESTRICTED is the better architecture iff one silent wrong answer costs more
than *k* refusals, where

```
k = (1 − coverage_RESTRICTED) / silent_wrong_rate_GENERAL
```

| f | d=1 | d=2 | d=4 | d=8 |
|---|---|---|---|---|
| 0.00 | 2.18 | 1.84 | 1.61 | **1.32** |
| 0.05 | 2.18 | 1.91 | 1.81 | 1.75 |
| 0.20 | 2.18 | 2.19 | 2.78 | 4.49 |

> **At f = 0 the bar falls with depth: by depth 8, one silent wrong answer need
> only be worth 1.32 refusals for restriction to be preferred.** That is a very
> low bar for most deployments — and it is the crossover the route was asked
> for, living in the cost-ratio dimension rather than the useful-work dimension.

**This is a VALUE judgement, not a measurement, and the route cannot make it.**
What the route supplies is the exchange rate.

---

## 5. WHAT THIS MEANS FOR THE ARCHITECTURE — refuse or contain?

**Contain by default; refuse per-chain, on the caller's declared cost ratio.**

1. **The general architecture is the right default, and this is now a measured
   choice rather than an inherited one.** It delivers 2.6–3.9× the useful work at
   every depth, and no vocabulary redesign changes that ordering (§2).
2. **Domain restriction is not a system-wide architecture; it is a MODE.** The
   break-even is ~1.3–2.2 refusals per silent error, so any chain whose caller
   would rather be told "no" than be quietly wrong should run restricted. That is
   a per-invocation policy, and it needs one new input the system does not
   currently have: **the caller's cost ratio.**
3. **What restriction actually buys is the elimination of silent wrongness, not
   correctness.** Marketing it as correctness would be the overclaim — at f=0.20,
   depth 8, restriction is *correct* only 16% of the time it attempts. Its
   property is that the other 84% are refusals and detected aborts, never
   undetected wrong answers.
4. **The respecification lever is worth pulling anyway** — but for GENERAL's
   benefit, not RESTRICTED's. Moving `memory_retrieval_relevance` and
   `external_send_content` into verifiable form cuts GENERAL's log decay from
   −0.2156 to −0.1078: **it halves the rate at which the default architecture
   goes silently wrong with depth.** That is the highest-value item this route
   identifies, and it is a design change, not a checking change.
5. **AR-1's payload question, answered.** AR-1 found chains 100% PROOF-carried
   and correctness 0.0 at every depth because the composed checks are all
   provenance and semantic types are payload. Removing the payload — this route —
   yields a system that composes perfectly and does **7.6%** of the work at depth
   8. **The payload is where the value is; the provenance is where the guarantee
   is. They are not substitutes and cannot be traded against each other.**

---

## 6. The definitional cells, diagnosed before reporting

Named in the preregistration (§8) so none of this is discovered after the fact.

| number | verdict |
|---|---|
| GENERAL coverage = 1.0000 | **DEFINITIONAL** — GENERAL attempts everything, by definition of the arm. |
| RESTRICTED correctness-on-attempted = 1.0000 **at f = 0** | **DEFINITIONAL** — a chain admitted only when every step has an exact verifier, with no faults injected, cannot fail. This is why f was swept: at f = 0.05 and 0.20 the same figure is **MEASURED** and falls to 0.6424 and 0.1623 at depth 8. |
| RESTRICTED silent-wrong = 0.0000 in all 36 cells | **DEFINITIONAL, and the definition is the claim.** It follows from "the registered verifier is an exact predicate", which is what PROOF-carriage *means* — signature verification, hash comparison and capability-subset are exact. It is definitional in the way "a sound proof system proves no falsehoods" is definitional: true by construction, and the construction is the point. |
| GENERAL silent-wrong rates (0.1275 → 0.7020) | **MEASURED** — driven by 0.3790 semantic reliability from 1000 executed MBPP samples. |
| coverage 0.7225 / 0.5255 / 0.2752 / 0.0755 | **MEASURED** given the registry; the registry composition (10/1/3/4) is a fact about the shipped code. |

**No cell is driven by a single claim type**: chain steps are drawn uniformly
over all 18 types, and the NONE bucket contains 4 distinct types, so no single
type exceeds 5.6% of steps.

---

## 7. Honest limits and disclosures

1. **One vocabulary — and the one most favourable to the restricted arm.**
   Gyza's claim set is cryptographic/accounting, exactly the kind that *has*
   native verifiers. A vocabulary of ordinary software claims would push
   RESTRICTED's coverage far lower. R14 Part C's 61.1% is a property of this
   vocabulary, not a law.
2. **Chain composition is synthetic and uniform.** Real chains are not uniform
   draws over the vocabulary; a real workload weighted toward PROOF-carried
   operations would raise RESTRICTED's coverage. **Uniform was declared before
   the run** precisely so it could not be chosen to flatter a result.
3. **The mechanical fault rate `f` has no measurement behind it** and was swept
   over {0, 0.05, 0.20} rather than invented. The DECISION is identical at all
   three; only the break-even ratio moves.
4. **Semantic reliability 0.3790 is mid-tier open-weight models at T = 0.7.** A
   stronger model raises GENERAL's curve and makes restriction look worse still.
5. **Part 3 is my judgement, not data** (§3), and one classification
   (`routing_match_quality`) turns on reading a committed finding as decisive.
6. **This is simulation over a real registry**, not a deployed comparison. What
   is real: the 18-type registry with carriers, the 1000 executed MBPP samples,
   and the exactness of the cited verifiers. What is modelled: chain
   composition, fault injection, and the assumption that an exact verifier
   always detects.
