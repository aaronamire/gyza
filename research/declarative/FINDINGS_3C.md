# Findings — 3.C, declarative maximisation scoped by authority

> **THIS IS AN AUTHORED ANALYSIS OF A VOCABULARY THIS PROGRAM WROTE ITSELF.** I
> designed these claim types, classified them in the census, and now judge
> whether they could be declarations. **The circularity cannot be guarded away,
> only disclosed.** It is why the external corpus carries the falsifying weight
> and Gyza's own numbers are corroborating at best. **5 of the 7 assertive
> verdicts required judgement (0.7143)** — higher than the 0.40–0.70 I predicted,
> and reported as a miss below.

Preregistered at **`7c496b6`** (blob `f3e145e`), the only file in
`research/declarative/` at that commit. Zero credits; no model call.

---

## 1. PART A — the retrodiction, reported first

The authority test applied to four types whose fate is already committed. **If
it fails here it is a relabelling.**

| type | test says | reason | correct? |
|---|---|---|---|
| provenance / signature family | **CONVERTIBLE** (already converted) | **(ii) holds**: signing *is* the act. There is no prior fact "the key holder approved" that the signature reports. **(iii) holds**: entitlement is the key, issued by `LocalCompositor.issue_agent` (`gyza/identity.py:215`), which *confers* the agent's standing rather than recording it | ✅ |
| `memory_retrieval_relevance` | **NOT-CONVERTIBLE-(ii)** | the respecified form **recomputes** a ranking over a corpus that exists independently of the saying | ✅ |
| `routing_match_quality` | **NOT-CONVERTIBLE-(ii)** | match *quality* reports a counterfactual — **and see §1a** | ✅ |
| `external_send_content` | **NOT-CONVERTIBLE-(ii)** | after emission the bytes leave the system (C15); Gyza constitutes nothing about their fate | ✅ |

**4 of 4. Prediction confirmed.** The test has predictive content on the
calibration set.

### 1a. The reason for `routing_match_quality` is DISTINCT from its exogeneity

A3 asked specifically for this, and it matters structurally:

> **(ii) is about the SPEECH ACT; exogeneity is about WHERE THE TRUTH CONDITION
> LIVES. They are independent axes.**

`balance_fold` fails (ii) — declaring a balance does not make it so — **while
being fully INTERNAL**. So a claim can be reporting-not-constituting without
being exogenous. The authority test is not a re-derivation of the determinacy
axis.

### 1b. Substitution disclosed

The task's fourth calibration type, `harm_bounds_respected`, **does not exist** —
verified against all 28 branches, the fourth such check across sessions.
`external_send_content` replaced it (preregistered), and is the better test of
rule 3d because its respecification *recorded* what it lost
(`adapters.py:106`).

---

## 2. PART B — the convertibility census

### B1 — every assertive type, tested

| type | verdict | basis |
|---|---|---|
| `balance_fold` | NOT-(ii) | j |
| `market_capital_fold` | NOT-(ii) | j |
| `unit_test_execution` | NOT-(ii) | i |
| `memory_retrieval_relevance` | NOT-(ii) | j |
| `external_send_content` | NOT-(ii) | j |
| `execution_output_content` | NOT-(ii) **+ (iii)** | i |
| `routing_match_quality` | NOT-(ii) | j |

**CONVERTIBLE: 0 of 7.**

`execution_output_content` is the only type failing **(iii)** as well: no party
inside is *entitled* to declare an output correct. **That entitlement sits with
the human principal who stated the intent — outside the system.**

### B2 — the delta, which is the headline

| | |
|---|---|
| declarative share **now** | **10/18 = 0.5556** |
| hypothetical **max with standing** | **10/18 = 0.5556** |
| **DELTA** | **+0.0000** |

### B4 — diagnosing the exact zero, before reporting it

An exact 0 is a suspected artifact. **It is not one here, and the diagnosis is
checkable.**

The strongest conversion candidate was `external_send_content`, because its
content-address fragment *is* constitutive — *"these bytes are hereby bound to
hash H"* is felicitous by construction. **But that fragment is already a separate
declarative type: `artifact_content_address` (`adapters.py:69-71`).** The same
holds for envelope signing (`envelope_signature`) and ledger entries
(`ledger_entry_signatures`).

> **GYZA'S VOCABULARY HAS ALREADY BEEN FACTORED SO THAT EVERYTHING CONSTITUTABLE
> IS CONSTITUTED.** The 0.556 is not accidental — it is the *result* of that
> factoring. The seven remaining assertives are the irreducible reporting
> residue.
>
> **The delta is zero because the work was already done, not because the test is
> too strict.**

That also answers B4's circularity question in the *unfavourable* direction:
Gyza's high declarative share is not the test being permissive about a
self-authored vocabulary — the test refuses **every** remaining candidate.

### B3 — the external corpus, the falsifier: **0 of 30**

Preregistered prediction: near zero. **Measured: 0.**

A crude screen flagged one claim (`scikit-learn#34075-2`); **hand-check showed a
false positive** — *"**My hunch** would be to…"* matched a `"my "` prefix test but
is a hedged proposal, not a claim about the reporter's own artifact. **Corrected
by inspection, not by tuning the rule**: the rule was a screen, the hand-check is
the measurement.

The mechanism is structural, not sampling luck: **a GitHub issue reporter is by
definition outside the software they report on.** GitHub confers standing to
*file*, never to *constitute* facts about the code. **The test is not too
permissive.**

---

## 3. PART C — the constituted / observed partition

| partition | n | DECLARATIVE | share | assertive | convertible |
|---|---|---|---|---|---|
| **constituted** | 13 | 10 | **0.7692** | 2 | 0 |
| **observed** | 5 | 0 | **0.0000** | 5 | 0 |

**C1's prediction is CONFIRMED, and sharply.**

The two assertives inside the *constituted* partition are `balance_fold` and
`market_capital_fold` — **folds over declaratives**. Each signed `LedgerEntry`
constitutes a transfer; the *sum* reports about those constitutive acts. **A fold
over declaratives is not itself a declarative**, which is why constituted-state
claims are 0.769 rather than 1.000.

**Diagnosing the observed partition's exact 0.0000:** the mechanism is verifiable
per type — code under test, whether nearness *is* relevance, bytes after
emission, model-output correctness, a counterfactual over handlers. Each referent
sits outside what Gyza constitutes. **But n = 5, so the exact zero is a
weakly-powered *rate*** even though the *mechanism* holds individually.

### C2 — the finding, stated as scoping rather than limitation

> **The declarative lever's reach is exactly the system's sphere of authority.**

This is a structural statement, not a technique. It says:

- **Where a system constitutes its own state** — its keys, its ledger, its
  capability grants, its provenance — claims about that state can be
  declarative, and verification is **constructive**: felicity, decidable by
  convention, with no correspondence to check and nothing to be underdetermined
  about.
- **Where a system observes state it does not constitute** — another program's
  output, a model's answer, the fate of bytes after emission — the lever is
  **unavailable in principle**, not merely unbuilt. No amount of engineering
  confers standing to constitute someone else's facts.

**What it implies for where this architecture can operate:** it is at its
strongest as a **substrate of record** — provenance, capability, settlement,
attribution — where the system *is* the authority for what it records. It is at
its weakest, irreducibly, as an **evaluator of external work**, which is exactly
where the competence bound was measured across six mechanism families.

**These are the same boundary seen from two directions**, and that is the
route's contribution: the competence bound and the authority constraint are not
independent obstacles. A system cannot cheaply verify what it did not constitute,
and it cannot constitute what it merely observes.

---

## 4. PART D — REFUSED

**D1 does not fire: there is no CONVERTIBLE assertive type to select.** 0 of 7.

The gates were not reached, but both would have failed anyway and it is worth
recording why:

- **CONSUMER GATE** — would fail regardless. `build_registries()` has **0
  production callers and 14 test callers**; nothing consumes any claim of any
  type.
- **POWER GATE** — the one design that *would* have passed it is already built:
  `artifact_content_address` has real felicity conditions that **can fail**
  (`blake3(data) != address`), which is why it is already declarative.

**This is the third consecutive refusal** (RESPEC-3, RESPEC-4, now 3.C). Per D3
that is further evidence the gates bind, and **nothing was built to avoid
refusing.**

---

## 5. Is 3.C closed?

> ## YES — **3C-CLOSED-NEGATIVE**, and the negative is the result.

Decision rule, preregistered: *convertible assertives ≤ 1 of 7 **and** external
≈ 0* → CLOSED-NEGATIVE. **Measured: 0 of 7, and 0 of 30.** Both conditions met
with margin.

**What 3.C concluded:**

1. **Declarative maximisation is not a lever that can be pulled.** Gyza's 0.556
   is already the maximum available to it; the delta with standing is
   **+0.0000**.
2. **The declarative share is a PROPERTY of what a system constitutes**, not a
   technique it can apply. This converts a proposed engineering direction into a
   **scoping result**.
3. **The authority constraint and the competence bound are the same boundary
   from two sides.** That is the durable finding, and it did not require building
   anything.

**Predictions scored:** retrodiction 4/4 ✅ · convertible 0 (predicted 0–2) ✅ ·
delta +0.0000 (predicted ≤ +0.11) ✅ · external 0 of 30 (predicted 0–2) ✅ ·
partition holds ✅ · **judgement fraction 0.7143, predicted 0.40–0.70 — MISSED
HIGH by 1.02×.** Small, but outside the stated range and recorded as a miss.

## 6. Honest limits

1. **Authored throughout, on a self-authored vocabulary.** 5 of 7 verdicts
   required judgement. The external corpus is the only uncontaminated evidence
   and it is a **negative** — it shows the test is not too permissive, not that
   it is correctly calibrated.
2. **n is small.** 18 Gyza types, 5 in the observed partition. The mechanisms are
   verifiable per type; the *rates* are not well powered.
3. **B2's delta is DEFINITIONAL given B4's diagnosis.** Once the constitutive
   fragments have been factored into their own types, a census of what remains
   *must* find them non-convertible. The finding is that **the factoring already
   happened** — which is a fact about this codebase, not a general law.
4. **§3's partition assignment is authored.** `unit_test_execution` as *observed*
   is the least obvious call: the tests are held in the repo, but what they
   measure — the behaviour of code under test — is not constituted by running
   them.
