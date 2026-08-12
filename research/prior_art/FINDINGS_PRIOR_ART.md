# Prior art — what is ours, what is not, and one 32-year-old open invitation

**Two rounds of literature search, primary sources read where it mattered.**
Zero credits beyond web access. **No claim below rests on a summariser** — §0
explains why that distinction turned out to be load-bearing.

---

## 0. A METHOD FINDING, FIRST, BECAUSE IT ALMOST CORRUPTED THE RESULT

Round 1's PDF summariser returned three claims about Bailis et al. Reading the
actual PDF with `pdftotext` refuted **all three**:

| summariser said | the PDF says |
|---|---|
| *"the paper acknowledges escrow and demarcation as related work"* | **zero occurrences** of either word |
| *"SUM, COUNT and 'at most N%' constraints are analysed and NOT I-confluent"* | **no aggregate, ratio or percentage constraint appears in the table** |
| a "formal definition" about non-conflicting concurrent transactions | the real one is merge-closure: *"for all I-T-reachable states Dᵢ, Dⱼ with a common ancestor state, **Dᵢ ⊔ Dⱼ is I-valid**"* |

> **A summariser asked for something a paper does not contain will often produce
> it.** Had I taken round 1 at face value I would have written *"Bailis already
> classifies ratio constraints"* into a novelty assessment — and been wrong in
> the direction that concedes a claim we actually hold. **Every finding below
> that matters was checked against a primary source.**

This is the same species as the rest of this program: **an unverified upstream
claim, believed because it was fluent.**

---

## 1. THE HEADLINE: WE SUPPLY A COUNTEREXAMPLE THE FIELD ASKED FOR IN 1994

This session measured `RESERVATION-PARTIAL` — a per-principal budget fails to
bound **concentration**, a ratio over all principals' holdings.

**Both ancestor techniques state that boundary in their own words.**

**Escrow (O'Neil, TODS 1986)** — our guard *is* escrow (`inf/val/sup`, local
reservation against an aggregate). Its scope: *"requires the database system to
be an 'expert' about the type of transactional updates… most commonly
**incremental changes to aggregate quantities**"* — increment/decrement,
commutative, single-sided.

**Demarcation (Barbará & Garcia-Molina, VLDB Journal 1994)** — the title is
*"maintaining **linear** arithmetic constraints."* And its conclusion:

> *"The demarcation protocol is limited because it only applies to **linear
> arithmetic constraints**. However, we have argued that a very large number of
> distributed constraints fall into this simple category. **As a matter of fact,
> we have difficulty envisioning more complex constraints that would arise in a
> practical distributed system.**"*

> ### THAT LAST SENTENCE IS THE POSITION.
>
> In 1994 the authors of the canonical coordination-free constraint protocol
> said they **could not envision a practical non-linear distributed
> constraint**.
>
> **"No principal holds more than κ of the federation" is exactly that
> constraint, it is non-linear (a ratio), and it arises naturally the moment you
> have many agents sharing a resource pool.**
>
> **So the honest claim is neither "we discovered this" nor "we rediscovered
> this."** It is: *the multi-agent AI setting supplies the practical non-linear
> aggregate constraint that the distributed-databases literature explicitly said
> it could not imagine — and we measured that the escrow/reservation family
> fails on it, exactly as its own stated scope predicts.*

**That is a stronger and more defensible position than novelty**, and it comes
with two 30-year-old citations doing the arguing for us.

---

## 2. DIRECTIONAL LOCALITY vs I-CONFLUENCE — subsumed in principle, unanalysed in fact

**I-confluence (Bailis et al., PVLDB 2014) is a necessary AND sufficient
condition** for coordination-free, available, convergent execution:
*merge-closure over invariant-preserving reachable states.*

**AG-3's directional locality is, in principle, an instance of it.** Two guards
each admitting against a shared pre-round state, whose effects then compose, is
the merge condition specialised to admission decisions.

**But the paper's actual analysis does not reach our case.** Verified table:

> Attribute Equality · Attribute Inequality · Uniqueness · AUTO_INCREMENT ·
> Foreign Key · Secondary Indexing · Materialized Views · `>` `<` ·
> `[NOT] CONTAINS` · `SIZE=`

**Per-record inequalities** (`balance ≥ 0`) are covered — that is the
single-principal case. **No cross-principal aggregate. No ratio.**

**Required restatement of AG-3:** *"Directional locality is a specialisation of
I-confluence to guard admission. Bailis gives the general criterion; the
ratio-type aggregate invariant we measure is not among the constraints that work
analyses."* **The impossibility result stands; the framing as a novel criterion
does not.**

---

## 3. THE COMPETENCE BOUND HAS A NAME, AND IT IS NOT OURS

The field calls it the **generation–verification gap (GV-gap)**, and the current
frontier states our result almost exactly:

> *"Recent work questions the gap's universality, hypothesising that LLMs are
> often **not reliably better at discriminating** between their own generated
> responses than they are at producing a good initial response."*
>
> *"The **lack of a generation-verification gap in natural-language theorem
> proving** hinders further improvement."*

**Restatement:** the bound is prior art. **What may survive as ours:** the
**likelihood-ratio framing** — that `LR = q/f` and not accuracy or Youden's J is
the statistic deciding whether a bonded mechanism can exist — plus the
six-family preregistered convergence with decision rules fixed before data.
**§6 flags where even that is at risk.**

---

## 4. CAPABILITY ATTENUATION AND DEPTH CAPS ARE STANDARD

**Macaroons (Google, 2014)** made attenuation-without-round-trip standard, and
*"depth limits with explicit policy at the boundary"* is named as a **surviving
production pattern**. There is also a March 2026 piece titled *"Google DeepMind
Validates Macaroon-Based Agent Delegation Architecture."*

**Our `MAX_DELEGATION_DEPTH = 3` is not novel and should never be presented as
such.** What remains defensible is the *proof obligation* — `manifest(hᵢ) ⊆
manifest(h₀)` verified per hop with cycle and depth bounds — and its binding into
a signed provenance record (§5).

---

## 5. THE SURVEY THAT NAMES OUR GAP AS THE GAP

**arXiv 2606.04990 — "From Agent Traces to Trust: A Survey of Evidence Tracing
and Execution Provenance in LLM Agents" (2026).** Six taxonomy tables, ~30 named
systems: ReAct, Reflexion, AutoGen, **CaMeL, FIDES, AgentSpec, AgentBound,
Agent-Sentry, NeuroTaint**, ToolEmu, AgentDojo, InjecAgent, MemGPT, A-MEM,
AgentOps, TRAIL, W3C PROV-DM, NeMo Guardrails, Llama Guard…

**Two results from it, both favourable:**

1. **No named system combines cryptographic signing of provenance with
   capability-based enforcement.**
2. **Capability attenuation across delegation chains is not discussed at all** —
   the survey covers delegation in multi-agent contexts (AutoGen, CAMEL) without
   it.

**And its Gap 1, verbatim:**

> *"**No single system spans trace sources, fine granularity, runtime timing, an
> explicit representation, and multiple trust functions at once** — which is
> precisely the gap that a unified provenance layer must close."*

> ### We are not outside this field. We are inside it, and a 2026 survey states our combination as its principal open problem.
>
> **That is a better place to be than "nobody does this."** It is citable, it is
> third-party, and it converts a novelty assertion into an answer to a published
> gap.

---

## 6. THE CLAIM MOST AT RISK, AND IT IS NOT THE ONE I EXPECTED

*"The literature red-teams monitors, not predicates"* is **weakened, and
possibly overtaken.**

- Red-teaming is indeed monitor-centric: *"monitor development can be framed as
  an adversarial game between a blue team designing monitor systems and a red
  team attempting to bypass them."*
- **But shield synthesis has just been re-read as exactly our move.** arXiv
  2606.13621 (2026), *"Beyond Runtime Enforcement: Shield Synthesis as
  Defensibility Analysis"*: shields are *"a design-time analytical instrument
  whose outputs are structural insights about a system rather than runtime
  constraints,"* and are *"most valuable not as a deployment mechanism for safe
  agents, but as a framework for answering architectural questions about
  whether, where, and how a system can be defended."*

**That is adversarial analysis of a predicate rather than a detector.** It is
2026 and concurrent. **Round 3 must read it properly** before this claim is used
anywhere.

---

## 7. WHAT SURVIVES AS OURS

**Falsified as novel:** reservation for aggregate bounds · delegation depth caps
· attenuation itself · the competence bound · coordination-avoidance criteria ·
agent audit trails as a product category.

**Defensible on current evidence:**

1. **The assembly the survey names as its open gap** — signed per-action
   provenance **bound to a capability-manifest hash**, attenuation proven across
   the chain, and claim verification, in one record.
2. **The carrier taxonomy** (PROOF/SPEC/TEST) predicting composition, with
   TEST measured at 0.000. I found no prior statement that sampled evidence
   collapses under composition while recomputed evidence does not.
3. **The counterexample of §1** — the practical non-linear aggregate constraint
   demarcation could not envision.
4. **Method**: preregistration with feasibility ceilings, decision rules fixed
   before data, negative controls required, and 17 recorded artifacts. **This is
   unusual in agent-safety work and is itself a differentiator** for DIU, where
   evaluation rigour is the product.

---

## 8. COMMERCIAL — one finding that may change the corporate plan

> **DIU: *"regularly seeks proposals from both U.S.- and internationally-based
> ventures."*** Eligibility is *"any commercial entity with an applicable
> solution"*, non-traditional contractors **preferred**. AI/ML portfolio
> **$30.9M**. Timeline: 60–90 days selection→award, 3–6 months end to end.

**The foreign-founder blocker may be materially softer than assumed.** Before
restructuring around a US cofounder, **ask DIU directly** — this is one email and
it gates a large decision.

**The market exists and is forming:** Zylos and miniOrange are already selling
agent audit trails; **SPIFFE/SVID is the incumbent workload-identity pattern** we
should position against explicitly; EU AI Act, NIST AI RMF and SOC 2 are the
demand drivers.

**CaMeL is the benchmark to beat and the numbers are public:** 67% of AgentDojo
attacks defended, **2.7–2.8× token overhead**. Its mechanism is capabilities as
metadata on *values* with control/data-flow separation — **genuinely different
from authority attenuation across principals**, so a real comparison table is
available rather than a hand-wave.

---

## 9. Round 3

1. **Read arXiv 2606.13621 in full** (§6) — the claim most at risk.
2. **Read 2606.04990 in full** — confirm Gap 1 and that no system does the
   assembly.
3. **Optimal auditing / costly state verification** (Townsend 1979 and
   successors) — is `LR ≥ g/w` already a named result? §3's surviving
   contribution depends on the answer.
4. **CAMEL, AutoGen, MetaGPT** decomposition internals — does any carry an
   execution oracle for agent work? That is SR-1 causal's blocker.
5. **Ask DIU about foreign founders** (§8).

## 10. Honest limits

1. **Two rounds, ~12 searches, four primary sources actually read.** Broad, not
   exhaustive.
2. **§5's two favourable results come from a fetch of the survey's HTML, not a
   full read.** They are the load-bearing positive claims and are the least
   verified things in this document.
3. **Absence of evidence:** "I found no prior statement of X" over two rounds is
   weak evidence about a literature this large.
4. **No claim here has been tested against someone who knows these fields.** That
   is the actual test, and it happens in diligence.
