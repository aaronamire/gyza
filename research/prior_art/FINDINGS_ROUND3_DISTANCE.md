# Round 3 — correctness, coordination, aggregate alignment, and the honest distance

**Three findings that change the map, and one assessment that is uncomfortable
and I think correct.**

---

## 1. THE CLAIM MOST AT RISK — **SURVIVES**

Round 2 flagged arXiv 2606.13621 (*"Shield Synthesis as Defensibility
Analysis"*) as possibly overtaking our *"the literature red-teams monitors, not
predicates"* claim. **Read: it does not.**

> It builds a **constrained two-player safety game over network topologies**,
> extracts a *"defensibility fingerprint"* from attractor structure, and its
> output is *"whether a topology-specification pair can be defended."*
> **Explicitly: it "doesn't use preregistration or traditional adversary
> construction against an invariant."**

**It analyses whether an architecture is defensible. We ask whether a declared
invariant is adequate against an adversary trying to cause harm inside it.**
Adjacent, genuinely different. **Claim restored** — and now with a citation for
what the nearest neighbour actually does.

---

## 2. COORDINATION — **SR-1 CAUSAL MAY BE UNBLOCKED BY SOMEONE ELSE'S WORK**

I declared SR-1 causal blocked, twice, on: *"no execution oracle exists for
agent-produced work; you cannot get a project's CI to run on a speculative patch
without opening a public PR."*

> **SWE-Bench++ (arXiv 2512.17419): 11,133 instances from 3,971 repositories
> across 11 languages.** Its four stages are **programmatic sourcing,
> environment synthesis, test oracle extraction, and quality assurance** —
> harvesting live PRs covering both bug fixes and feature requests.
>
> **SWE-smith (arXiv 2504.21798)** generated 5,016 expert trajectories and
> fine-tuned a 32B model to 40.2% on SWE-bench Verified.

**That is precisely the missing artifact.** "Environment synthesis + test oracle
extraction" is an execution oracle for agent-produced work, built and published.

**What this changes, stated carefully:**

- The **ground-truth blocker** on SR-1 causal is **no longer a research
  blocker** — it is now an integration question.
- **It does not change the machine constraint.** Running those environments
  still needs compute this laptop does not have (2 physical cores, ~3 GB).
- **It does not change §D3's deflation:** an experiment worth running for only
  one of its two outcomes is still worth less than its design suggests.

**But "blocked on ground truth" must be downgraded to "blocked on compute," and
that is a materially different — and purchasable — problem.**

---

## 3. AGGREGATE ALIGNMENT — **the field moved, and our ledger is stale**

`FRONTIER_LEDGER.md` calls this *"GENUINELY-OPEN… a years-scale research agenda…
out-of-scope for the current apparatus"* and my prior was *"nothing formal
exists."* **That is now wrong.**

**De Marzo, Bellina, Castellano, Priesemann & Garcia (arXiv 2605.10721),
*"Conformity Generates Collective Misalignment in AI Agent Societies"* (May
2026)** — and this is a *formal theory*:

> Two competing forces per agent (majority-following vs intrinsic bias). Using
> **statistical physics**, they derive *"a quantitative theory that predicts when
> populations become trapped in long-lived misaligned configurations, and
> identifies **predictable tipping points where small numbers of adversarial
> agents can irreversibly shift population-level alignment even after
> manipulation ceases**."* Nine LLMs, one hundred opinion pairs.
>
> **Conclusion: *"individual-level alignment provides no guarantee of collective
> safety."***

**Also now in the field:** *"A Sober Look at Agentic Misalignment in Automated
Workflows"*; *"Tool Use Enables Undetectable Steganography in Multi-Agent LLM
Systems"*; *"Emergent Coordination in Multi-Agent Language Models"*; *"Learning
to Negotiate: Multi-Agent Deliberation for Collective Value Alignment."*
Measured regularities include *"the misalignment surface area widens with
workflow size"* and *"unaligned multi-agent accuracy drops monotonically with
agent count."*

### But the gap that matters is still open, and it is precisely ours

**Everything above is DESCRIPTIVE — when does collective misalignment emerge.
Nothing is PRESCRIPTIVE with proven bounds.**

The nearest prescriptive work, *"Institutional AI: Governing LLM Collusion via
Public Governance Graphs,"* relies on **monitoring and institutional design
rather than hard structural constraints**, and by its own account proves nothing
about **composition** or **aggregate bounds**.

> **So the field now has: a theory of how collective misalignment arises, and
> governance proposals with no composition guarantees.**
>
> **AG-3 sits exactly in the hole between them** — a structural impossibility
> result about what local guards can bound, with a constructive counterexample.
> **That is more valuable now than when it was written**, because there is
> finally a literature for it to speak to.

**Required ledger correction:** aggregate alignment is no longer GENUINELY-OPEN
in the sense of "nobody is working on it." It is **actively measured, formally
modelled, and mechanistically unsolved.**

---

## 4. THE DISTANCE TO THE VISION

Asked directly: how far is Gyza from a beneficial planetary-scale intelligence?
**I'll answer in three parts, because the honest answer is different for each.**

### 4a. What is genuinely close — months, not years

**A per-operator accountability and containment layer.** Signed per-action
provenance bound to a capability manifest, attenuation proven across delegation,
audit that fails closed. **This is built, tested, and answers a published open
problem** (2606.04990's Gap 1). The market exists and is forming.

**It needs one thing it does not have: something running through it.** Every key
surface has zero production consumers. **That is engineering, not research, and
it is the single highest-value move available.**

### 4b. What is medium — 1–2 years, no unknowns, just work

Coordination with negotiation; the audit economics with real parameters;
correctness within competence (LR 19.95 — *works*, and is deployable today);
SR-1 causal now that the oracle exists.

**None of these is blocked on an idea.** They are blocked on compute, wiring, and
decisions.

### 4c. What is far, and may be structurally impossible — and this is the part that matters

> **The research program has produced a negative result about the vision
> itself, and I do not think it has been stated plainly enough.**

Assemble four measured results:

1. **AGGREGATE-IS-HARDER** — an admission decision from a stale read of a
   quantity others can move is unsound, *even for an instantaneous quantity,
   even with a perfectly consistent read.*
2. **Directional locality / I-confluence** — ratio-type collective quantities
   admit **no exact local test**.
3. **RESERVATION-PARTIAL** — the one named repair fixes the within-principal
   race and introduces a new staleness; it is not a general repair.
4. **Demarcation, 1994** — the coordination-free constraint literature is
   **limited to linear constraints** and said so.

**Together these say:** *bounding a collective ratio-type quantity requires a
serialization point whose width is the whole federation.*

**"Planetary scale" means precisely that you cannot have one.**

> ### So on current evidence, a planetary-scale system with *bounded collective harm* is not attainable. Not "not yet built" — **structurally obstructed**, by a result this program proved and then failed to break.

**What remains attainable at planetary scale, and it is not nothing:**

| property | scales? | why |
|---|---|---|
| **Non-repudiation / attribution** | ✅ **yes** | local by construction; every action signed by its actor |
| **Authority containment** | ✅ **yes** | attenuation **composes** — proven, `manifest(hᵢ) ⊆ manifest(h₀)` |
| **Correctness inside competence** | ✅ yes | LR 19.95, mechanically checkable claims |
| **Correctness outside competence** | ❌ no | competence bound, six families |
| **Collective / aggregate harm bounds** | ❌ **no** | §4c |

### 4d. The restatement I would actually stand behind

> **A planetary-scale *accountability and containment* substrate is achievable.
> A planetary-scale *collective-harm-bounded* intelligence is not, on current
> evidence.**

**That is a smaller vision and a defensible one.** It says: every agent action is
attributable to a principal, every principal's authority is provably bounded and
non-increasing down its delegation chain, and every claim carries its own truth
conditions — **but nobody can promise the aggregate behaviour of the whole is
benign, and this program has measured why not.**

**I think that is a stronger pitch than the larger claim**, for three reasons:
it is true; the negative half is *defensible research* rather than a missing
feature; and **for DIU specifically, "here is exactly what we can and cannot
guarantee, with the impossibility proof attached" is a more credible artifact
than an unbounded promise.**

---

## 5. What this changes in the roadmap

| item | before | after |
|---|---|---|
| SR-1 causal | blocked on ground truth | **blocked on compute** — SWE-Bench++ exists |
| Aggregate alignment | GENUINELY-OPEN, nobody working | **actively measured, mechanistically unsolved** — our niche is sharper |
| "red-teams predicates not monitors" | at risk | **survives**, with the nearest neighbour identified |
| The vision | planetary beneficial intelligence | **planetary accountability + containment; collective bounds structurally obstructed** |

## 6. Honest limits

1. **§2 rests on abstracts.** Whether SWE-Bench++ environments actually run at
   the scale SR-1 needs is unverified.
2. **§4c is an argument, not a theorem.** It assembles four results into a claim
   none of them makes alone. The weak joint is whether "planetary scale" strictly
   implies "no federation-wide serialization point" — a hierarchical or sharded
   serialization might evade it, and **I have not tested that.** It is the single
   most valuable thing to attack next.
3. **The field moved faster than the ledger.** Three of the five most relevant
   papers here are from 2026. Any novelty claim decays quickly and should be
   re-checked before each external use.
