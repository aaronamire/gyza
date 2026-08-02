# The open problem

*For an agent with strong empirical discipline, a small compute budget, and no
context on this program. Read this alone and you will know what is closed, what
is open, and what the traps are.*

**Every number here carries its source file.** They were re-verified against the
tree when this was written; verify again before relying on one, because
documents in this program have carried stale numbers twice.

**Scope, inline and not deferred to a footnote.** Everything below comes from:
simulated environments; hand-designed action and claim vocabularies; four
mid-tier open-weight models (own-program pass rate ≈ 0.26–0.38); N ≤ 8 agents;
M ≤ 3 principals; two task families (MBPP, MATH); one repository. Where a result
is analytic rather than measured it says so. Where a cell is definitional it
says so.

---

## §1 — The problem, precisely

> Design a system in which many autonomous agents perform consequential work at
> machine speed, such that **(a)** undetected consequential error is bounded,
> **(b)** every action is attributable, **(c)** the system's aggregate behaviour
> is beneficial, and **(d)** it scales in depth, breadth, and across principals.

| | status | where |
|---|---|---|
| **(a)** bounded undetected error | **partially solved, and the bound is narrower than it looks.** Harm is bounded where it is *declared* and *measurable as a state quantity*; correctness of content is not bounded at all. | §2.1, §2.4, §2.7 |
| **(b)** attributability | **solved**, and it is the one unqualified success. Signed provenance chains verify offline with no trust in the producer. | §3 |
| **(c)** aggregate benefit | **untouched.** No formalism exists. | §4.1 |
| **(d)** scale | **depth: bounded and low** (§2.7). **breadth: solved for the right invariant class** (§2.2). **across principals: closed negative** (§2.6). |

The honest one-line summary: **(b) is done, (a) is done for a restricted and
measurable class of harms, (d) is bounded much lower than hoped, and (c) has not
been started by anyone.**

---

## §2 — CLOSED. Do not attack these.

Each entry states the result, the evidence, and **why the obvious next attempt
fails**. The fences are here because the most expensive thing a fresh agent can
do is open a sixteenth route that re-derives one of these.

### 2.1 Cheap correctness verification is bounded by verifier competence

**Result.** You cannot cheaply verify what you cannot understand. Six
preregistered, structurally independent mechanism families all failed, each for
the same reason from a different direction: agreement between producers,
metamorphic/self-consistency, adversarial defensibility, cross-model checking
(with and without the reasoning trace), mechanical CAS checking, and LLM-written
unit tests. `COMPETENCE_BOUND.md`, `PROGRAM_STATUS.md`.

**Evidence.** The well-powered out-of-competence demonstration is R8 cell (b),
n = 127–290 (`PROGRAM_STATUS.md`). The durable *positive* is the in-competence
regime: J = 0.777, LR = 19.8, n = 433 (`PROGRAM_STATUS.md`) — cheap structural
checks work on claims the checker could itself solve.

**Why the next attempt fails.** Each of the six re-imported the competence
requirement at a **different stage** — independence of errors, the restatement
that re-solves, telling defensible truth from defensible error, transcription
into the CAS, and test authorship. So "use a different mechanism" is not a plan.
Any proposed verifier must first explain which of those five stages it avoids,
and no proposal so far has avoided all of them.

**Novelty, honestly.** `PAPER_READINESS.md` classifies the individual pieces as
KNOWN or KNOWN-VARIANT and only the six-family convergence as
PLAUSIBLY-NOVEL (empirical). This program **corroborates** a widely-held
intuition with preregistered measurement; it did not discover it. *(A claim that
it is externally corroborated by published oversight-scaling work is plausible
but is **not verifiable from this repository**, so it is not asserted here.)*

### 2.2 Statelessness and cumulative bounding are mutually exclusive

**Result.** No stateless local check bounds a cumulative quantity. R13.

**Why.** A decision that is a function of one action cannot depend on the count
of prior actions. Encoding the count creates a shared cell; a shared cell is a
conflict set of size one; a conflict set of size one serializes regardless of
how the underlying resource is partitioned (R10's H-CONS refutation). Cumulative
bounds therefore require a serialization point — which is why the architecture
has exactly one (§3).

### 2.3 Difficulty-based routing fails even with oracle difficulty

**Result.** ROUTER-DEAD. `router/FINDINGS_R11.md`.

**Evidence.** Six adequately-powered cells at AUROC ≥ 0.85 — including one at
**AUROC = 1.000, a literal difficulty oracle** — all yield routing economy
**0.320** against a preregistered 0.40 bar.

**Why the next attempt fails.** Economy is ceiling-bound at `1 − r·f` by the
base failure rate, and **an oracle at 1.000 bought exactly what 0.907 bought**.
Economy is not a function of predictor accuracy in this regime, so "get a better
router" is not the fix. Routing must be **structural** — a type lookup, not a
prediction.

### 2.4 Models cannot author specs for work they cannot do

**Result.** SPEC-COLLAPSES. `spec_competence/FINDINGS_R14.md`.

**Evidence.** Conditioned on the model's own program being wrong, unconditional
spec strength is **0.1177 [0.0794, 0.1586]** against a TYPE-ONLY floor of
**0.2864** — **below a one-line `isinstance` check**. R8 found the same for
tests. Validity, not strength, is what collapses: a model that cannot solve a
problem does not retreat to weak-but-true properties, it asserts falsehoods.

**Consequence.** Partial specs are human-authored, one per claim *type*. See
§4.4 for why that affordable cost model does **not** extend to type assignment.

### 2.5 Blind channels are not mechanically discoverable

**Result.** UNSOUND, witness-level recall **0.50**, precision 1.00.
`channel_discovery/FINDINGS_R12.md`.

**Why.** Blindness is a *semantic* dependence — a path that moves a harm
quantity without passing the guard. Static analysis tests *syntactic* mention.
Closing that gap requires deciding whether the guard is adequate, which is the
question the check was meant to replace.

**The constructive converse is real and is the architecture's foundation:** make
the quantity a pure fold over append-only state and have the guard call the same
function, and a blind channel has nowhere to hide — not because the analyzer is
clever, but because there is no stored aggregate to write behind the guard's
back (`ARCHITECTURAL_PRINCIPLE.md`).

### 2.6 Federation of locally-guarded principals does not bound cross-principal harm

**Result.** FEDERATION-DOES-NOT-COMPOSE. `federation/FINDINGS_R13.md`.

**Evidence.** Signature-gating drove cross-principal violations to 0 against the
*unauthorized* attack, and still leaked on **partitioned, solely-owned assets**
under a benign workload with the shared pool removed entirely. Joint-pool
overdraft under signature gating was **byte-identical to the unguarded
configuration** (180 → 1134 across cells).

**Why.** **A signature authorizes an ACTION; it does not bound a CONSEQUENCE.**
And the reason is the property the design leaned on: statelessness. A stateless
check cannot accumulate, so it cannot bound a cumulative quantity — the same
wall as §2.2, reached from authority instead of concurrency.

### 2.7 Verifiability does not survive composition, and the ceiling is low

**Result.** The central engineering finding. `CARRIER_COVERAGE.md`,
`selection_routes/carrier_coverage.json`.

| | tier-1 | tier-3 | any correctness claim |
|---|---|---|---|
| isolated (one claim) | **61.1%** | 22.2% | 77.8% |
| chains of depth 2 | 30.9% | 47.8% | 52.2% |
| chains of depth 4 | 9.5% | 72.8% | 27.2% |
| **chains of depth 8** | **0.9%** | **92.6%** | **7.4%** |

Upgrade *every* TEST- and SPEC-carried claim type to PROOF — the most any
representation work can buy — and depth-8 tier-1 reaches only **0.134**.

**Why.** **4 of 18 claim types are semantic** (output content, memory
relevance, routing quality, external send content); their correctness is §2.1;
and **any chain touching one inherits tier 3**. The binding constraint is the
shape of the claim vocabulary, not verifier quality.

**Two caveats, stated because they bound the claim.** This is **ANALYTIC**, not
measured — it follows from the composition rules plus the registry's makeup.
And it assumes **uniform sampling** of chains from the vocabulary, which real
chains do not obey. It is a shape argument, not a forecast.

**A sharpening worth carrying:** isolated tier-1 coverage is 61.1% (11 of 18)
but only **55.6% is PROOF-carried** (10 of 18). The gap is one claim type whose
verifier is a unit-test suite — **tier 1 in isolation, and it forces every chain
containing it to tier 3.** Tier is not a composition budget.

### 2.8 Containment ends at emission

A guard can refuse to **emit**. After emission there is no containment, and **no
detector would help either**. This is not a gap to be closed; it is the boundary
of what containment means, and it belongs in any claim the system makes
(`ARCHITECTURAL_PRINCIPLE.md`, R9 §7).

### 2.9 Unbounded coordination depth

Chained **unverified** steps decay as (1−p)ⁿ. At the measured capability tier
(p ≈ 0.35), depth beyond ~10 is worthless. **Derivable — do not spend compute
testing it.** Redundancy cannot push chain error below the common-mode rate, and
nested failure sets make majority vote equal the best single replica.
Proof-carried claims do not decay, because a violation is caught at the stage
that commits it.

---

## §3 — What is built

Full inventory in `ENGINEERING_STATUS.md`. One page:

**The architecture.** An **append-only interior** where nothing is irreversible,
so it needs no per-action gating; **one batched, serialized promotion gate**
which is simultaneously the irreversibility gate and the serialization point
that §2.2 proves cumulative bounding requires — the same place by necessity, not
convenience; and a **narrow egress**. Guard configuration lives in a separate
trust domain, signed, and refuses both tampering and downgrade: if the agent can
rewrite the invariant, the induction has no base case.

**The two-dimensional taxonomy** — the correction that reorganised the design:

| dimension | values | governs | source |
|---|---|---|---|
| invariant **CLASS** | conservation / monotone / cumulative | **concurrency** — what runs in the interior vs serializes at the gate | R9+R10+R13 |
| evidential **CARRIER** | PROOF / SPEC / TEST | **composition** — whether a chain of checks still checks anything | `selection_routes/FINDINGS_SR3.md` |

Measured: PROOF **1.000** (n=21), SPEC **1.000** (n=2), **TEST 0.000** (n=4).

**Closed selection routes.**

| route | decision |
|---|---|
| SR-2 allocation | **round-robin.** Type-routed measured 13 pp *worse* (0.3261 vs 0.4565); two claim types cannot discriminate four handlers, so type-routing commits where round-robin diversifies. Oracle 0.5652 — **43% of problems are solved by no handler**, an escalation floor no allocator moves. `FINDINGS_SR2.md` |
| SR-3 tier algebra | **carrier-dominated** (above) |
| SR-5 promotion granularity | **per-action** (Occam; per-task within the equivalence bound and 3.7× cheaper per promoted action) |
| SR-6 depth cap | **per carrier**: PROOF/SPEC none, TEST/NONE 10. DERIVED, not measured. |

**Three items gate value, and all three are user-owned:** merging and shipping
the packaging branch; **one person who is not the author installing and running
it** (outstanding longest); and S5 reproducible builds, whose critical path is a
second independent rebuilder (`S5_SPEC.md`). **No further engineering moves any
of them.**

---

## §4 — Genuinely open, ranked

### 4.1 Aggregate alignment — (c)

Individually-bounded, individually-correct agents composing into collective
harm. **No formalism exists anywhere**, in this program or outside it. Years-
scale, needs a running substrate to study, and is not a next-experiment.

**What would even constitute progress:** a *definition* of aggregate harm that
is not the sum of individual harms and is computable from state — because
without one, there is nothing to bound and nothing to measure. That definition
is the open problem; the mechanism is downstream of it.

### 4.2 Harm-model completeness — the one cheap discovery route left

**Why it is the highest-value open item.** Every containment result in §2 rests
on **hand-declared** harm measures. R9 showed an unmodelled channel destroys
adequacy *while the invariant holds and is never violated*. R12 (§2.5) proved
you cannot find such channels mechanically. So completeness can only be
established **adversarially, by humans**, and it has never been attempted.

**The design, stated so it is not misrun.** A red team receives the harm model
**and** the guard source, and must **cause damage the DECLARED MODEL DOES NOT
MEASURE**. The win condition is *not* breaking the guard — a guard that holds
while the system is harmed is exactly the failure R9 measured. Preregister what
counts as damage before the team starts, or the result is unfalsifiable.

This is the only item here that is cheap, runnable now, and would change what
the system may honestly claim. **It should run before any external claim about
what the system guarantees.**

### 4.3 SR-1 and SR-4 — blocked on artifacts, not ideas

| route | blocking artifact |
|---|---|
| **SR-1 decomposition** | decompositions with **external** ground truth. Self-authored goals are the trap that voided R14's Part B4 cell — a corpus authored by the agent being measured measures the corpus. |
| **SR-4 retry** | **stochastic** generations. The cached substrate is temperature-0 single-sample, so retry is *definitionally* identical and recovery is 0 by construction, not by measurement. |

Both are small once the artifact exists. Neither is a research problem.

### 4.4 Per-task type assignment

The verified tier is sound **given** a claim type. Nothing verifies the type is
right, and nothing mechanical can — it is a judgement about what work *means*.

**Measured:** 196 of 196 external artifacts carry **more than one legitimate
claim type from identical source text** (`is it correct?` vs `does it pass these
tests?` over the same program), so the ceiling for any **text-based** assigner
is **0.5** (`selection_routes/type_assignment_external.json`). The rate is
definitional — the corpus was built with two types per artifact. **The ceiling
is structural**, because the source text is externally authored and simply does
not contain the distinction.

So the verified tier needs a human-audited assignment **per task**, not per
type — and §2.4's affordable cost model does not extend to it.

**Open:** is there a **non-text** signal that determines the claim type — the
consuming context, the downstream use, the caller's declared intent? Unevidenced
either way. Nobody has looked.

### 4.5 Claim-vocabulary design

**Coverage is a design variable, not a measurement.** The 61.1% is a property of
a *cryptographic and accounting* vocabulary, which is exactly the kind with
native verifiers. It says nothing about an arbitrary workload, and reading it as
a general result is the mistake.

**Open:** can a claim vocabulary be *designed* so the PROOF-carried fraction is
high enough that deep chains survive? §2.7's ceiling says the lever is not
upgrading verifiers — it is choosing what claims exist, keeping chains short,
and pushing semantic stages to boundaries where they can be gated rather than
into interiors where they poison. Whether a useful system can be expressed that
way is untested.

---

## §5 — The traps

Fifteen artifacts, each of which would have produced a specific false headline.
Full ledger in `ARTIFACT_LEDGER.md`.

| # | would have falsely shown | caught by |
|---|---|---|
| 1 | agreement signal from a forced collision (curated-list matching) | diagnosing a clean number |
| 2 | signal from degenerate weak-model outputs | inspecting the outputs |
| 3 | a harness bug in MBPP function-name handling reading as a result | re-derivation |
| 4 | a sentinel collision reading as agreement | diagnosing a clean number |
| 5 | trust-lift from a **selection confound** | decomposing the population |
| 6 | T1/T2 detector **coupling** reading as independent detection | checking independence |
| 7 | 33% canonicalization contamination | canonical comparison |
| 8 | R8 `__ERR__` generation failures counted as wrong answers | inspecting failures |
| 9–12 | *running tally across R12–R14; individual identities live in those routes' findings — this document does not re-derive a numbering it cannot verify* | |
| **13** | granularity "does not matter" (a clean 3-way tie at 1.0) while promotion-per-action bought **unlimited drain** | a preregistered feasibility check demanding refusals before the comparison was trusted |
| **14** | CONSERVATION 0.667 read as a **class property** when it was a mixture (PROOF 1.000 n=8 + TEST 0.000 n=4) | having recorded the carrier, so the aggregate could be decomposed |
| **15** | 11 false WRONGs from **repr equality** mistaken for value equality; a recurrence of #7 in a different codebase | an exactly-at-threshold gate number (0.950 vs a 0.95 bar) being diagnosed rather than accepted |

**The standing discipline, as rules with their provenance:**

1. **Preregister before data** — and **do not preregister an unrunnable route**;
   refusing to is correct.
2. **Diagnose any exact 0 or 1 before reporting** — four artifacts came from
   this rule alone. Extend it: diagnose any number sitting exactly on a
   threshold (#15).
3. **Always report the counter-metric.** SR-5's per-batch variant scored
   `peak harm / bound = 0.00` — a *perfect containment score* — by promoting
   nothing at all (`selection_routes/sr5_result.json`). Containment without
   throughput hides its failure mode.
4. **Check every threshold against its feasibility ceiling, computed under the
   mechanism's own dynamics**, not against a static state.
5. **Harm is defined independently of any guard.** Deriving the harm measure
   from the gate makes adequacy tautological.
6. **Any cumulative measurement names an immutable origin** (#13). The frame
   lemma applies to *moving* frames, not only pinned ones.
7. **When a number fits your model, check whether it decomposes into a
   mixture** (#14). A taxonomy determines which artifacts you can catch.
8. **Canonicalize before comparing representations** (#7, #15). Check the
   **sign** of the residual: a one-directional error confirms the mechanism.
9. **Label every cell DEFINITIONAL or MEASURED.** Definitional cells
   illustrate; they do not confirm.
10. **A prompt contradicting a committed finding loses to the finding**, and the
    contradiction is reported.

---

## §6 — How to work on this

Selection routes (which of A/B/C?) close by picking a winner. Discovery routes
(is X true?) need a **terminal condition stated in advance**, or they run
forever.

**Negative results are successes**, and this is not encouragement — it is the
base rate. Five of this program's sharpest findings were preregistered
predictions **refuted by data**: R9's G4/G4′ inversion, R10's H-CONS refutation,
R13's P2/P5/P7, R14's P1, SR-2's P2.

**The honest ratio.** Fifteen routes produced roughly **two constructive
results** — the architectural principle (append-only, partitioned,
derived-not-stored) and the two-dimensional taxonomy — plus one durable
deployable positive (cheap checks work *inside* competence, J = 0.777). Everything
else is a closed door. **That ratio is what this problem is like**, and a fresh
agent expecting a better one will either pick easy questions or overclaim.

The doors are worth the cost. A closed door is permanent; an open one that was
never really open costs a year.
