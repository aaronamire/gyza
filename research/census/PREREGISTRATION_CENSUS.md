# Preregistration — the decidability census

**Committed BEFORE any classification.** Attack on Correctness 1, item A.
Analytic, **zero credits**, source-reading only. No mechanism is built.

The question: the program has treated "unverifiable" as ONE category. Two later
results suggest it is at least two — respecification moved two claim types into
mechanically checkable form and found two real bugs doing it, and AR-1 found
provenance composes to arbitrary depth while correctness is 0.0 at depth 1.
**If "unverifiable" does not decompose, Attacks 2 and 3 are built on sand.**

---

## 1. The two axes, verbatim, classified INDEPENDENTLY

**AXIS 1 — SPEECH ACT.** What kind of claim is it?

| class | success condition |
|---|---|
| **DECLARATIVE** | **FELICITY** — true iff its own form is well-constructed. A signature does not *claim* approval, it *constitutes* it. No fact of the matter beyond the convention. |
| **COMMISSIVE** | **FULFILMENT** — did the world come to match the words. |
| **DIRECTIVE** | **COMPLIANCE** — was it done as specified. Requires a stated specification. |
| **ASSERTIVE** | **CORRESPONDENCE** to a fact. |

**AXIS 2 — DETERMINACY.** Where does the truth condition live?

| class | criterion |
|---|---|
| **INTERNAL** | evaluable over state the system already holds **plus parameters the claim itself names** |
| **UNDERDETERMINED** | a success condition exists, but the claim does not name enough to evaluate it |
| **EXOGENOUS** | the success condition requires a fact outside the system |
| **CONTESTED** | no fact of the matter, or one requiring judgement |

## 2. The mechanical criterion for axis 2

Applied as a decision procedure, in this order. First match wins.

```
Q1. Is there a fact of the matter at all — could two competent parties
    disagree with no procedure that settles it?
        YES-disagreement-unsettleable -> CONTESTED
Q2. Can the success condition be written as a function of
        (a) state the system already stores, and
        (b) fields the CLAIM ITSELF names?
        YES -> INTERNAL
Q3. Does a success condition exist, and would NAMING MORE PARAMETERS
    in the claim make Q2 answer YES, without acquiring any new fact
    from outside the system?
        YES -> UNDERDETERMINED
Q4. Otherwise -> EXOGENOUS
```

> **THE CONSERVATIVE DIRECTION IS BINDING.** Where a claim's referent cannot be
> **resolved to stored state by inspection**, classify **EXOGENOUS**. Classify by
> what the referent resolves to, never by what the claim seems to mean.

**Q2 is deliberately counterfactual: "could this check be written", not "has
someone written it".** A type is INTERNAL whether or not a verifier exists
today. Otherwise the census would measure implementation effort and call it
decidability.

## 3. Circularity hazards — DISCLOSED, and one of them is not fully guardable

**H1 — the classifier is the respecifier.** I wrote the respecifications and
would benefit from a favourable answer. Guards: classify from the type's
DEFINITION and CALL SITES; run Part C's retrodiction first, so the criterion is
tested against four already-committed outcomes before it is turned on anything
new.

**H2 — CARRIER BLINDING IS NOT AVAILABLE TO ME, and I will not claim it.**
Gate 0b asks that each type be classified before looking at its current carrier.
**I already know Gyza's carrier distribution (12 PROOF / 1 TEST / 3 SPEC /
2 NONE) from earlier work in this same session.** I cannot un-know it. Reporting
a blinded classification would be false. Instead:

- Gyza's classification is **explicitly unblinded**, and every disagreement
  between carrier and axis-2 class is reported rather than smoothed.
- **The external vocabulary (Part B) IS uncontaminated by carrier knowledge** —
  those 240 names have no carrier and I have never classified them. Part B
  therefore carries the decision, which is also why the decision rule is defined
  on the external vocabulary.

**H3 — the corpus already carries MY taxonomy.** `research/corpus/check_taxonomy.py`
partitions check names CODE-SUBSTANTIVE / INFRASTRUCTURE. **That is this
program's authorship and is NOT imported.** Part B uses only the raw
third-party check NAMES from `all_checks.json`.

## 4. Sources, fixed now

| part | source | authored by |
|---|---|---|
| A | the 18 V-1 claim types, `gyza/verification/adapters.py:115-181` | this program |
| B | **240 distinct CI check names** over 181 PRs, `research/corpus/all_checks.json` | scikit-learn / pandas maintainers — **external** |

`build_registries()` has **14 call sites, all tests, zero production** (verified).
So the V-1 registry is **the vocabulary's SPECIFICATION, not its deployed
behaviour**, and Part A is a census of what Gyza says it checks.

**Part B procedure, fixed before data:** apply the §2 criterion to all 240
distinct names. Where the name alone underdetermines the class, record
**UNSURE** — never a default. Then hand-audit a random sample of **30**
(`SEED = 1`) to estimate the rule's own error rate. **UNSURE is reported
separately from EXOGENOUS**: "I could not classify this" and "this is exogenous"
are different claims.

## 5. Decision rule

Let **f = fraction of the ASSERTIVE row that is EXOGENOUS or CONTESTED**,
measured on the **EXTERNAL** vocabulary (Part B), since Gyza's own is the
favourable case.

| outcome | condition | consequence |
|---|---|---|
| **CENSUS-FAVOURABLE** | `f < 0.50` **AND** Part C retrodiction succeeds | most assertive claims are underdetermined, not exogenous; the bound covers a smaller region than 16 routes suggested; **Attacks 2 and 3 licensed** |
| **CENSUS-UNFAVOURABLE** | `f >= 0.80` | the underdetermined class is small; respecification's ceiling is low; the bound is as binding as treated. **ATTACKS 2 AND 3 KILLED**, recorded closed |
| **CENSUS-INTERMEDIATE** | `0.50 <= f < 0.80`, or retrodiction mixed | report the number, claim neither, say which classes fall where |

**Any cell driven by a single claim type → report INCONCLUSIVE for that cell.**

**CENSUS-UNFAVOURABLE IS A SUCCESS.** It closes two documents' worth of proposed
work cheaply and confirms the bound at full strength. It will not be softened
and no rescue will be proposed.

## 6. Point predictions, stated now

| prediction | value |
|---|---|
| Gyza concentrates in DECLARATIVE × INTERNAL | **10–13 of 18** |
| external vocabulary concentrates in ASSERTIVE | yes, split UNDERDETERMINED / EXOGENOUS |
| **f on the external vocabulary** | **0.4 – 0.7** |
| Part C retrodiction succeeds | **≥ 3 of 4** |

**Prior: 35% FAVOURABLE / 45% INTERMEDIATE / 20% UNFAVOURABLE.**

## 7. Part C — the criterion's own test, run FIRST

Apply the §2 criterion to four types whose fate is **already committed**:

- `memory_retrieval_relevance`, `external_send_content` — successfully
  respecified. The criterion should say **UNDERDETERMINED**.
- `routing_match_quality`, `execution_output_content` — resisted, recorded
  IRREDUCIBLY SEMANTIC by rule 3d. The criterion should say **EXOGENOUS** or
  **CONTESTED**.

**Reported before the census totals**, so the census is read through a criterion
whose validity is already established or already doubted. If it does not
retrodict, **the criterion is a relabeling and will be reported as one.**

## 8. Standing discipline

Any cell exactly 0 or exactly a full row → **diagnose the coupling before
reporting**. No tuning after seeing results: if the criterion needs refinement,
that is a **FINDING about the criterion** and every changed classification is
named. Label **DEFINITIONAL vs MEASURED**. Report, per type, whether the
classification **followed by inspection** or **required judgement**, and report
the judgement count and the UNSURE count separately. **This is an authored
classification unless the criterion is genuinely mechanical**, and it will be
labelled as such throughout.

**Zero credits.** If any step appears to need a model call: STOP and report.
