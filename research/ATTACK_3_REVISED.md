# Attack 3 — revised against the census that tested it

**SCOPE, in the header where it belongs and not in a footnote.** The census
that licenses this document measured **bug reports and feature requests against
two mature Python data-science libraries**. It licenses claims about *that*
claim population. It does **not** license claims about natural-language
reasoning tasks — MBPP, MATH, the NoOp fixtures — which is where all six
mechanism families measured the competence bound. Nothing here touches that
result or its scope.

**Source of the prior text.** `ATTACK_ON_CORRECTNESS_3.md` lives at
`~/Downloads/`, **outside this repository**. An in-place CORRECTION block was
therefore not possible, so this is a **new document** that quotes the passages
it corrects verbatim, per standing discipline. *If the original is added to
`research/`, this file should be linked from it* — and note that `research/` is
public, so publishing the three Attack documents is a call for their author, not
for me.

---

## 0. THE CORRECTION THAT COMES FIRST — and it is a correction to MY OWN findings

The task that produced this document stated:

> *"The census contradicts Attack 3's stated mechanism and confirms its thesis by
> a different route… Attack 3 predicted the lever would be in DETERMINACY — that
> respecification moves claims from underdetermined to internal. The data says
> the lever is in SPEECH ACT."*

**That is wrong, and I need to own that I am the source of it.**
`FINDINGS_CLAIMS_CENSUS.md` §6 says the census *"relocates"* Attack 3's thesis. I
wrote that **without having read Attack 3** — it was not in the repository and I
had reconstructed its thesis from context. Having now read it:

> **Attack 3's thesis is ALREADY the speech-act thesis. There is nothing to
> relocate.**

Its own words, verbatim:

| § | text |
|---|---|
| 1.3 | *"**The competence bound is a bound on ASSERTIVES.** It was measured exclusively on assertives, and the program generalized it to all claims without testing the other classes."* |
| 2.4 | *"Attack 2 is a repair applied to assertives. **Attack 3 is a selection over speech acts** — and it applies at design time, before any claim exists."* |
| 2.4 | *"**Declaratives are verifiable by construction, not by repair.** … there is no fact of the matter beyond the convention, so there is nothing to be underdetermined about."* |
| V.C | *"**The declarative maximisation question.** … how much of a system's claim traffic can be made declarative?"* |

The determinacy lever is **Attack 2's**, and Attack 3 §2.4 explicitly
distinguishes itself from it. So the census does not contradict Attack 3.

> **It confirms it, quantitatively, on the measurement Attack 3 itself asked for
> and named "★ run first; everything depends on it".**

`FINDINGS_CLAIMS_CENSUS.md` §6 is committed and is not edited; this paragraph is
the correction of record.

---

## 1. Attack 3 passes its own falsifier, by a factor of ~5

It staked itself in advance:

> *"**Falsifier:** ≥80% assertive-exogenous kills the document."*

| vocabulary | assertive-exogenous |
|---|---|
| Gyza's 18 registry types | **2/18 = 0.111** |
| external claims (215) | **23/215 = 0.107** |
| external, incl. CONTESTED | 0.163 |
| external, after the **adversarial** stress pass | **0.228** |

**Survives with a factor of ~4.9 in hand**, and survives its own adversarial
re-reading. This is a preregistered falsifier that did not fire — which is worth
more than a confirmation that was not staked.

## 2. Its Part V.A predictions: two confirmed, one REFUTED

Predictions made before measurement, scored:

| prediction | outcome |
|---|---|
| *"provenance and capability types classify **declarative**"* | ✅ **CONFIRMED** — 10/18 of Gyza's vocabulary, incl. every envelope, manifest and content-address type |
| *"the genuinely semantic types classify **assertive-exogenous** or contested"* | ✅ **CONFIRMED** — `execution_output_content`, `routing_match_quality` |
| *"**Ledger and settlement types classify commissive-internal**"* | ❌ **REFUTED** |
| *"execution and retrieval types classify directive-internal if their specification is stated"* | ⚠️ partial — post-respecification I classified `memory_retrieval_relevance` **assertive**-internal, not directive |

### 2.1 The refutation, and it hits an entire attack

> **COMMISSIVE = 0. In BOTH vocabularies. 0 of 18 and 0 of 215 — 233 classified
> claims, zero commissives.**

`ledger_entry_signatures` classifies **declarative** (a signature constitutes,
it does not promise). `balance_fold` and `market_capital_fold` classify
**assertive**-internal — they report a derived quantity; they do not commit to
one.

**This is a direct empirical hit on Part V.D, "THE COMMISSIVE SETTLEMENT
CHANNEL"**, which is predicated on commissives being available and asks *"what
fraction of agent claims can be stated as advance commitments"*. The measured
answer, in two vocabularies, is **zero as currently written**.

That does not kill V.D. Its own falsifier was *"if most cannot [be stated as
advance commitments], the channel is narrow"* — and V.D is a proposal to
**restate** claims as commitments, so measuring zero *existing* commissives is
evidence about the **current** vocabulary, not about the **reachable** one.
**But V.D can no longer cite ledger operations as an existing instance.** It has
no existing instance at all, and should say so.

---

## 3. What the census adds that Attack 3 did NOT predict

Attack 3 asked for a census of *"a real vocabulary"* and predicted the shape of
Gyza's. It did not predict what an **external, unselected** vocabulary would
look like. That comparison is new:

| | Gyza (18 types) | external claims (215) |
|---|---|---|
| **DECLARATIVE share** | **0.556** | **0.000** |
| ASSERTIVE share | 0.389 | 0.786 |
| **f on the ASSERTIVE row** | **0.2857** | **0.2071** |

> **Within assertive claims the two vocabularies behave ABOUT THE SAME — roughly
> a fifth to a quarter genuinely exogenous. The entire measured difference is in
> HOW MUCH OF THE VOCABULARY IS ASSERTIVE AT ALL.**

**This sharpens §2.4 rather than relocating it.** Attack 3 argued declaratives
are verifiable by construction. The census shows the *magnitude*: Gyza's
advantage is **not** that its assertions are easier to check — measured, they are
about as hard — it is that **56% of its vocabulary asserts nothing at all.**

The operative sentence, which Attack 3 implied but never stated this bluntly:

> **The lever is not "make assertions more checkable." It is "make fewer claims
> assertive."**

**Mechanism, restated:** a declarative succeeds by **felicity**. There is no
correspondence to check, so there is nothing to be underdetermined *about*.
AR-1 found this empirically without naming it — *provenance composes to arbitrary
depth; correctness is absent at depth 1* — and Attack 3 §2.4 already made that
connection. The census supplies the number.

---

## 4. B3 — is declarative conversion available for real work, or only bookkeeping?

Attack 3 §4.2 concedes the relabelling objection *"in part"* and defends with
*"the choice is often free."* **The census puts pressure on "often."** Three
worked cases from Gyza's own vocabulary, with rule 3d applied unchanged — *a
claim that is verifiable because it no longer asks for anything useful is
abandonment, not conversion.*

### Case 1 — `artifact_content_address` — **conversion already done; free**
- **Assertive form:** *"these bytes have hash H."*
- **Declarative form:** the address **is** the binding. `blake3(data) == address`
  is felicity, not correspondence.
- **Cost: none.** Nothing was given up; the claim was engineered to have no
  truth conditions beyond its own form.
- **3d: PASSES.** This is the working precedent, and it is why Attack 3 §V.C
  calls this *"the deepest version of the attack."*

### Case 2 — `memory_retrieval_relevance` — **conversion PARTIAL; cost real**
- **Assertive form:** *"these memories are relevant."* Exogenous.
- **What respecification actually did:** made it assertive-**internal** by naming
  metric, k, threshold, filter and a content-addressed corpus snapshot. That is
  **Attack 2's lever, not Attack 3's** — the speech act did not change.
- **Would a declarative form exist?** *"This set is hereby the top-k under M over
  snapshot S"* — felicitous iff recomputation matches. **But that is the same
  check under a different label**, which is precisely Attack 3 §V.B's own
  falsifier: *"if conversion always requires stating exactly the truth conditions
  respecification would have stated, it is the same lever wearing different
  clothes."*
- **Verdict: HERE THE TWO LEVERS COINCIDE**, and Attack 3's falsifier fires on
  this case. Recorded rather than smoothed.
- **3d:** passes either way, but *"whether nearness under M is relevance"* is lost
  under both — the judgement moves to one human decision when M is chosen.

### Case 3 — `execution_output_content` — **conversion NOT AVAILABLE**
- **Assertive form:** *"the output is correct."* Exogenous.
- **Declarative attempt:** *"this artifact is hereby bound to hash H."* Felicitous
  by construction — and it verifies **reproducibility**, discarding correctness.
  A deterministic wrong program is felicitous every time.
- **3d: FAILS.** This is abandonment, not conversion, and `adapters.py:170-172`
  already records it as such.
- **Verdict: the conservation law.** Some work's success condition *is*
  correspondence to a fact, and no speech act reaches it.

### The judgement B3 asks for, labelled as one

> **JUDGEMENT, not measurement:** declarative conversion is **broadly available
> for bookkeeping and narrowly available for substantive work** — and the
> external corpus's **0.000 declarative** is mostly a property of the **genre**,
> not of work in general.

**Why I think genre:** bug reporters have **no standing to constitute
anything**. A declarative requires conventional authority — a signature is
felicitous because the key holder is entitled to sign. A user filing an issue is
*reporting*, and reporting is assertive by definition. **Gyza can emit
declaratives because it holds keys and defines conventions.** That asymmetry is
about *institutional position*, not about the difficulty of the work.

**The honest limit on that judgement:** it predicts an agent *inside* a system
with conventions could be far more declarative than 0.000 — but **the census did
not measure such an agent**, and Gyza's 0.556 is this program's own authorship
(H1). The claim is a mechanism, not a measurement.

---

## 5. What changes in the document, and what does not

**Unchanged and confirmed:** the thesis (§1.3), the speech-act stratification
(§3.1), the conjecture (§3.2), the reframing (§3.3), and the conservation law
(§6.2). All survive the census; the falsifier did not fire.

**Must change:**

1. **Part V.D (commissive settlement)** — remove ledger operations as a claimed
   existing instance. **COMMISSIVE = 0 in both vocabularies.** V.D is a proposal
   with **no existing instance**, and should say so.
2. **Part V.A** — mark the census **RUN**, with results, and mark the
   commissive-internal prediction **refuted**.
3. **Part V.B (conversion lever)** — its falsifier **fires on
   `memory_retrieval_relevance`**: conversion there requires stating exactly what
   respecification stated. V.B is not dead — Case 1 shows conversion that is
   genuinely free — but it is **not strictly more general** than respecification,
   which is what §V.B claims.
4. **Add the external baseline** (§3 here). It is the strongest number in the
   document and Attack 3 does not contain it.

---

## 6. Attack 2 — LICENSED, mechanism unchanged (B5)

Recorded lightly, as instructed. Attack 2's mechanism is **respecification acting
on the UNDERDETERMINED class**, and it is intact:

| | |
|---|---|
| **licence** | `f = 0.2071 < 0.50` → **CENSUS-FAVOURABLE** |
| UNDERDETERMINED, assertive row | **35/169 = 0.207** |
| UNDERDETERMINED, whole corpus | **48/215 = 0.223** |
| survives adversarial stress | yes — `f = 0.2899`, still < 0.50 |
| **scope** | bug reports against mature Python libraries; **not** NL reasoning |

The class Attack 2 acts on is **real and substantial**, and three earlier
attempts failed to observe it for three distinct structural reasons. No rewrite
needed.

**One caveat Attack 2 should carry:** §4 of this document shows that on
`memory_retrieval_relevance` the Attack 2 and Attack 3 levers **coincide**. They
are not always distinct, and the composition claim (*"pick the class first, then
respecify within it"*) is cleaner in principle than in that instance.
