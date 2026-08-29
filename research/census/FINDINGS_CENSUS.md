# Findings — the decidability census

Per `PREREGISTRATION_CENSUS.md` (commit `eb711a8`, blob `429c2a87`), committed
before any classification and the only file in `research/census/` at that
commit. Analytic, **zero credits, no model call**. No mechanism was built.

---

## DECISION: **CENSUS-VOID — the preregistered decision cannot be evaluated**

> **The external vocabulary I preregistered is SELECTED ON THE OUTCOME BEING
> MEASURED.** `f(external) = 0.0143` would trigger CENSUS-FAVOURABLE and license
> Attacks 2 and 3. **It must not be allowed to**, because a CI check name exists
> precisely when somebody already built a mechanical check for it. Asking what
> fraction of CI checks are mechanically checkable has the answer 1 by
> construction. **The number is DEFINITIONAL, not MEASURED.**

**Attacks 2 and 3 are neither licensed nor killed. They are BLOCKED**, on an
artifact, in the same way SR-1 and SR-4 are blocked — see §6.

---

## 1. PART C FIRST — the criterion's own test: **4 / 4, it retrodicts**

Applied to four types whose fate was committed before this route existed.

| type | criterion says | committed outcome | ✓ |
|---|---|---|---|
| `memory_retrieval_relevance` *(pre-respec)* | **UNDERDETERMINED** | successfully respecified | ✓ |
| `external_send_content` *(pre-respec)* | **UNDERDETERMINED** | successfully respecified | ✓ |
| `routing_match_quality` | **EXOGENOUS** | resisted; IRREDUCIBLY SEMANTIC | ✓ |
| `execution_output_content` | **EXOGENOUS** | resisted; IRREDUCIBLY SEMANTIC | ✓ |

**Working, so the reasoning can be checked rather than trusted:**

- **`memory_retrieval_relevance`**, as it stood (`FINDINGS.md` A1: *"these
  memories are relevant"*, `NO_VERIFIER`). Q1: a procedure exists once a metric
  is fixed → not CONTESTED. Q2: the claim named **nothing** — no metric, no k,
  no threshold, no corpus → NO. Q3: naming metric/k/threshold/filter/corpus
  makes Q2 YES, and every one resolves to episodes **already in the store** — no
  outside fact acquired → **UNDERDETERMINED**.
- **`external_send_content`** (*"the right content was sent"*). Q2: NO, the
  claim named nothing. Q3: naming `artifact_hash`/`destination`/`n_bytes`
  suffices for the *binding* half, over bytes in hand at the emission boundary →
  **UNDERDETERMINED**. The *"right"* half needs a policy and is a separate
  claim — which is exactly what the respecification kept and dropped.
- **`routing_match_quality`.** The referent of *match **quality*** is a
  counterfactual — *which handler would have succeeded*. That is not stored
  state and no parameter naming reaches it; you would have to run the
  alternatives. → **EXOGENOUS**.
- **`execution_output_content`.** Follows from a committed finding
  (`adapters.py:170-172`): restating as *"output hash = H"* verifies
  reproducibility and discards correctness — a deterministic wrong program
  passes every time. → **EXOGENOUS**.

**A clarification of my own preregistered wording, flagged rather than slipped
in.** Q3 says *"naming more parameters"*. I read that as parameter **addition**
to the same claim, never claim **substitution** — otherwise every type is
trivially UNDERDETERMINED via *"restate it as `hash = H`"*. That is the
preregistered text's plain meaning, and it is not a post-hoc narrowing.

> **DR's rule 3d and this criterion's Q3 are the same constraint, reached
> independently.** DR got there empirically (*verifiable and known not to
> deliver is not a win*); Q3 gets there structurally (*you may add parameters,
> you may not swap the claim*). That convergence is the strongest evidence here
> that the criterion has content rather than being a relabeling.

**The criterion has predictive content. What follows is read through a criterion
whose validity is established — and whose LIMIT is that 10 of 18 Gyza
classifications required judgement, not inspection (§5).**

---

## 2. PART A — Gyza's vocabulary (18 types, `adapters.py:115-181`)

`build_registries()` has **14 call sites, all tests, zero production**. This is
the vocabulary's **specification, not its deployed behaviour.**

**Two readings, because the difference between them IS the finding.**
*Registered* = the claim the verifier actually evaluates. *Named* = the claim the
type's name asserts.

### A-registered

| | INTERNAL | UNDERDET | EXOGENOUS | CONTESTED |
|---|---|---|---|---|
| DECLARATIVE | **10** | 0 | 0 | 0 |
| COMMISSIVE | 0 | 0 | 0 | 0 |
| DIRECTIVE | 1 *(INCONCLUSIVE — single type)* | 0 | 0 | 0 |
| ASSERTIVE | **5** | 0 | **2** | 0 |

**f(gyza, registered) = 2/7 = 0.2857**

### A-named

| | INTERNAL | UNDERDET | EXOGENOUS | CONTESTED |
|---|---|---|---|---|
| DECLARATIVE | 8 | 0 | 2 | 0 |
| COMMISSIVE | 0 | 0 | 0 | 0 |
| DIRECTIVE | 1 *(INCONCLUSIVE — single type)* | 0 | 0 | 0 |
| ASSERTIVE | 2 | 0 | **5** | 0 |

**f(gyza, named) = 5/7 = 0.7143**

### A4 — the predicted concentration, diagnosed as instructed

**DECLARATIVE × INTERNAL = 10 of 18. Prediction was 10–13. CONFIRMED**, at the
bottom of the range.

> **This is NOT evidence the bound is weak. It is evidence the vocabulary is
> mostly NON-ASSERTIVE.** Those ten are verifiable because they **do not assert
> facts**: a signature does not *claim* that a key holder approved something, it
> **constitutes** approval. There was never a correspondence to check. Reading
> "12 of 18 are PROOF-carried, therefore mostly verifiable" would be measuring
> the wrong thing, exactly as the preregistration warned.

**The interesting number is inside the ASSERTIVE row, and it moves by a factor
of 2.5 depending on which claim you read** — 0.2857 registered vs 0.7143 named.
Three types carry that gap, and in two of them **the registry itself already
documents the split**:

| type | registered | named | the registry's own words |
|---|---|---|---|
| `hlc_ordering` | monotone ratchet | wall-clock truth | *"the ratchet is checkable; wall-clock truth is not"* |
| `reputation_score` | `0 ≤ s ≤ 1` | tracks trustworthiness | *"range is checkable; whether it tracks trustworthiness is not"* |
| `unit_test_execution` | passes THESE cases | the code works | SR-3: finite sample catches **0.000** under composition (n=4) |

> **That gap is the census's one solid positive result.** Gyza's favourable
> coverage is not a discovery that its claims are decidable. It is the
> **consequence of a vocabulary that names the checkable half of each claim and
> declines the other half** — visibly, in writing, at the point of registration.
> This is Attack 3's thesis appearing inside Gyza's own vocabulary rather than
> in the comparison that was supposed to test it.

---

## 3. PART B — the external vocabulary, and why it is VOID

240 distinct CI check names over 181 PRs (`corpus/all_checks.json`), authored by
scikit-learn and pandas maintainers. `corpus/check_taxonomy.py` is **this
program's** partition and was **not** imported; only raw third-party names were
used.

| | INTERNAL | UNDERDET | EXOGENOUS | CONTESTED | UNSURE |
|---|---|---|---|---|---|
| DECLARATIVE | 2 | 0 | 0 | 1 *(INCONCLUSIVE)* | 0 |
| COMMISSIVE | 0 | 0 | 13 | 0 | 0 |
| ASSERTIVE | **207** | 0 | 3 | 0 | 0 |
| UNSURE | 0 | 0 | 0 | 0 | **14** |

**f(external) = 3/210 = 0.0143.** UNSURE = 14/240 = 0.0583, reported separately
from EXOGENOUS — *"I could not classify this"* and *"this is exogenous"* are
different claims.

### 3a. Two extreme cells, diagnosed before reporting

**ASSERTIVE × INTERNAL = 207/210 (98.6%) — effectively a full row.**
**UNDERDETERMINED = 0 in all three tables — an exact zero.**

> **DIAGNOSIS: the population is selected on the outcome.** A CI check name
> exists *because somebody already built an automated check for it*. A check
> whose parameters were unnamed could not be a CI job at all, so
> UNDERDETERMINED is **empty by construction**, and ASSERTIVE × INTERNAL is
> **full by construction**. `f(external) = 0.0143` measures *"what fraction of
> the things people built automated checks for are mechanically checkable"* —
> and the answer is ≈ 1 definitionally.

**The corpus's own MANIFEST documents this exact species for a sibling
measurement**, and I walked into it with a different artifact from the same
corpus:

> *"Running a commit's own tests against its own tree recovers the committing
> habit, not the goal… 12/12 green. An exact 1, and it is DEFINITIONAL: a commit
> is published after its author made it pass, so the population is selected on
> the outcome being measured."*

**And the preregistered predictions refuted themselves, which is the tell.** I
predicted the external vocabulary would concentrate in ASSERTIVE **split between
UNDERDETERMINED and EXOGENOUS**, with **f ∈ [0.4, 0.7]**. It concentrated in
ASSERTIVE ✓ but split **207 : 0 : 3**, and f missed the predicted floor by
**28×**. A preregistered prediction missing by that margin is diagnostic of a
broken instrument, not of a surprising world.

**The 3 EXOGENOUS assertives are one family** — `CodSpeed Performance Analysis`,
`CodSpeed profiling`, `core / Run Rust benchmarks`, all performance benchmarking
against machine state. Per the preregistered single-type rule, **that cell is
INCONCLUSIVE**, and since it is f's entire numerator, **f itself is
inconclusive** independently of the selection effect.

### 3b. B3 — the comparison the route wanted, and what is left of it

The intended test was: if Gyza is overwhelmingly DECLARATIVE × INTERNAL and the
external vocabulary overwhelmingly ASSERTIVE × EXOGENOUS, vocabulary design is
doing the work. **That comparison cannot be run**, because the external
vocabulary is not a sample of claims — it is a sample of *checks*.

What survives is the weaker, internal comparison in §2: within Gyza's own
vocabulary, the same claim types read 0.2857 registered against 0.7143 named.
**That is a real gap and it points the same way** — but it is measured on this
program's own authorship, so H1 circularity applies, and it cannot carry the
decision.

---

## 4. The decision

| quantity | value | usable for the decision? |
|---|---|---|
| Part C retrodiction | **4/4** | yes — the criterion has content |
| **f(external)** — the preregistered decision statistic | **0.0143** | **NO — definitional; numerator is one family** |
| f(gyza, named) | 0.7143 | no — this program's own vocabulary (H1); post-hoc as a decision source |
| f(gyza, registered) | 0.2857 | no — post-respecification, so also selected |

The preregistered rule requires f on the external vocabulary. **That statistic is
void, so the rule does not evaluate.** I am not substituting a fallback number
and calling it the decision — doing so would be choosing the decision source
after seeing the results, which is the defect the whole preregistration exists
to prevent.

**CENSUS-VOID.** Not FAVOURABLE, not UNFAVOURABLE, not INTERMEDIATE.

---

## 5. Judgement, unsure, and what is authored

| | count |
|---|---|
| Gyza classifications by **inspection** | **8 / 18** |
| Gyza classifications requiring **judgement** | **10 / 18** |
| external names **UNSURE** (unmatched, not defaulted) | **14 / 240** |

> **A MAJORITY OF THE GYZA CLASSIFICATIONS REQUIRED JUDGEMENT. This is an
> AUTHORED CLASSIFICATION, not a measurement.** The criterion narrows the choice
> and, per Part C, has real predictive content — but it did not remove the
> choice on 10 of 18 types. DR's Part 3 was labelled an authored judgement
> throughout and that is the standard this meets, not exceeds.

The 14 UNSURE are genuinely unmatched, not hard cases forced into a bucket:
`Send tweet`, `welcome`, `CodeRabbit`, `matrix.name` (a template that never
expanded), `release-pydantic-core`, three `numpy-reproducer` variants, and
others. **Nothing was defaulted.**

**MECHANICAL vs AUTHORED in `census.py`:** the tabulation, the joint
distributions, f, the single-type-cell check and the pattern rule's application
are mechanical. **Every Gyza classification is authored.**

---

## 6. WHAT THIS LICENSES OR KILLS

### Attack 2 — **NOT LICENSED, NOT KILLED. BLOCKED.**
Licensing required `f < 0.50` on a valid external vocabulary. The value obtained
is definitional and its numerator is one family. Killing required `f ≥ 0.80`,
also not obtained. **Attack 2 does not proceed on this evidence** and must not
be started on `f = 0.0143`.

### Attack 3 — **NOT LICENSED, NOT KILLED. BLOCKED, but with its thesis
partially corroborated from an unexpected direction.**
The vocabulary-design thesis got no support from the intended comparison, which
could not be run. It got *indirect* support from §2: Gyza's own registry
**documents, in its own rationale strings, that it registers the checkable half
of `hlc_ordering` and `reputation_score` and declines the other half.** That is
vocabulary design doing exactly what Attack 3 claims — observed in the wrong
place, on this program's own authorship, and therefore **corroborating but not
decisive**.

### What would unblock both — and it is one artifact, not an idea

> **A vocabulary of claims that is NOT selected on being checkable.**

CI check names fail because they are checks. Gyza's registry fails because it is
this program's authorship and post-respecification. The requirement:

1. **externally authored** — not by this program;
2. **claims, not checks** — collected before anyone decided what was verifiable;
3. **large enough** that no cell rests on one family.

Candidates worth assessing, none assessed here: issue/bug-report *claims* (what
a reporter asserts is wrong, before triage decides what is testable); PR
*description* claims as distinct from the CI that ran; requirement or
acceptance-criteria statements. **This is the same class of blocker as SR-1
(needs decompositions with external ground truth) and SR-4 (needs stochastic
generations)** — small once the artifact exists, and not a research problem.

---

## 7. Honest limits

1. **The headline is a negative result about my own instrument**, not about the
   world. The census did not measure whether "unverifiable" decomposes; it
   established that neither vocabulary available to it can answer that.
2. **The UNDERDETERMINED class — the entire object of the route — was
   unobservable in both vocabularies**, for two different structural reasons
   (post-respecification in Gyza, selected-on-checkability externally). A census
   that cannot observe the class whose size it exists to measure has not
   measured it.
3. **10 of 18 Gyza classifications required judgement.** Authored throughout.
4. **The Part C retrodiction is 4/4 on n = 4**, and all four outcomes were known
   to me before I applied the criterion. It establishes the criterion is not
   *vacuous*; it does not establish accuracy at any useful precision.
5. **f(gyza, named) = 0.7143 sits in the INTERMEDIATE band** and, had I
   preregistered Gyza's named reading as the decision source, would have
   returned CENSUS-INTERMEDIATE. **I did not, and I am not backfilling it.**
   Recorded so a future reader can see what the alternative preregistration
   would have yielded.
6. The external rule was applied to names only. A name is weaker evidence than a
   job definition; a check called `lint` that actually runs a test suite would
   be misclassified, and nothing here would catch it.
