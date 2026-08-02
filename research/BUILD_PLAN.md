# Gyza — System Logic Build Plan

*The containment logic is settled (R9–R14, fifteen routes, twelve caught artifacts). This document specifies the remaining system: the containment layer in code, the verification layer, and the coordination layer — which is 0% designed and 0% built. It is written so Claude Code can act autonomously: every component has a purpose, a constraint set derived from measured results, an acceptance criterion, and — where a design choice is genuinely open — a selection route that resolves it.*

---

## 0. How to read this document

**Two kinds of route, and they are not the same thing.**

- **Discovery route** — "is X true?" The research program (R2–R14) ran these. They are **terminated**. Do not open new discovery routes without explicit instruction; the program reached a documented terminal state.
- **Selection route** — "which of A/B/C is the better engineering choice?" These are subordinate tools. They have a natural stopping point (pick the winner, build it, close the route). This document authorizes selection routes only, and names each one.

**Precedence when sources conflict:** measured results in committed FINDINGS files > this document > any prior design document > intuition. If this document contradicts a committed finding, the finding wins and the contradiction must be reported.

**Verify every code citation against the tree.** Prior documents in this program have carried stale line numbers, including ones written by the same program that measured why documents drift.

---

## 1. Constraints the build must respect

These are measured, not assumed. Any design that violates one is wrong regardless of how attractive it looks.

| # | Constraint | Source |
|---|---|---|
| C1 | Cheap verification of natural-language reasoning is bounded by verifier competence. Do not build a correctness verifier. | Competence bound, six families |
| C2 | Invariants must be over **state**, not action shapes. An invariant over action kinds is a filter, and filters leak totally. | R9 |
| C3 | An invariant's **frame must float** with the harm measure's frame. Pinning the frame is not conservative — it is catastrophic. | R9 (G4′ lost 175000; G4 bounded at 50) |
| C4 | Adequacy is **per harm class**. Conjunction of invariants is free by induction; one invariant covers one class. | R9 |
| C5 | Harm must be declared as a **measure**, not a boolean. A boolean has no dial and forces the corner. | R10 Part B |
| C6 | **Conservation-class** and **monotone-non-cumulative** invariants compose statelessly across depth, breadth, and principals. **Cumulative/budget-class** invariants do not. | R9+R10+R13 |
| C7 | **Statelessness ⊥ cumulative bounding.** No stateless local check bounds a cumulative quantity. Cumulative bounds require a serialization point. | R13 |
| C8 | A guard scales in breadth only if **its own state partitions** along the action axis. A single counter serializes regardless of how the resource is partitioned. | R10 (H-CONS refutation) |
| C9 | Under **append-only** storage, recoverability composes concurrently; under mutable storage it does not. Rollback frequency bounds resource loss; only append-only bounds content loss. | R10 H-APPEND, R11 Part A2 |
| C10 | Routing must be **structural** (type check), never predictive. Difficulty-based routing fails even with oracle difficulty. | R11 (ROUTER-DEAD) |
| C11 | Models cannot author valid specs for problems they cannot solve. Deployable spec quality is **below a one-line type check**. Partial specs are **human-authored, once per claim type**. | R14 (unconditional kill 0.1177 vs type-only floor 0.2864) |
| C12 | Federation of independently-guarded principals does **not** bound cumulative cross-principal harm. A signature authorizes an action, not a consequence. | R13 |
| C13 | Blind channels are **not** mechanically discoverable. Harm-model completeness must be established adversarially, by humans. | R12 (UNSOUND) |
| C14 | Chained **unverified** steps decay as (1−p)ⁿ. At the measured tier (p≈0.35) depth beyond ~10 is worthless. Verified claims (p=1 for the proven property) do not decay. | Derived; do not re-test |
| C15 | Containment ends at **emission**. A guard can refuse to emit; after emission there is no containment and no detector helps. | R9 §7, ARCHITECTURAL_PRINCIPLE |

**The representation rule that follows from C6/C8/C9:** *append-only, partitioned, derived-not-stored.* Compute every safety-relevant quantity as a pure fold over append-only state, and have the guard invoke the same function the harm measure uses. This makes blind channels architecturally impossible, frame alignment automatic, and breadth composition free. Cost: nothing is ever freed.

---

## 2. Target architecture

```
                        ┌─────────────────────────┐
   task ──▶ DECOMPOSE ─▶│  TIER ROUTER (type chk) │
                        └────┬──────┬─────────┬───┘
                             │      │         │
              tier 1 ────────┘      │         └──────── tier 3
        native verifier             │              no verifier
     correctness recovered      tier 2            containment only
     unbounded depth        partial spec          depth ≲ 10
                          human-authored
                          per claim type
                             │
                             ▼
              ┌──────────────────────────────┐
              │  APPEND-ONLY STAGING (interior)│  ← unbounded autonomy,
              │  conservation + monotone       │    no per-action gates,
              │  invariants, stateless,        │    everything reversible
              │  concurrent                    │
              └───────────────┬────────────────┘
                              ▼
              ┌──────────────────────────────┐
              │  PROMOTION GATE (serialized)  │  ← cumulative checks live
              │  batched · cumulative bounds  │    HERE and only here (C7)
              │  irreversibility gate         │    escalation to human/oracle
              └───────────────┬────────────────┘
                              ▼
                          EGRESS (irreversible, narrow)
```

Two properties make this the shape rather than a shape:

- **The interior is free because nothing in it is irreversible** (C9). All gating collapses onto one boundary you can afford to guard.
- **The promotion gate is simultaneously the irreversibility gate and the serialization point** that C7 proves cumulative bounding requires. These are the same place by necessity, not by convenience.

**Guard trust domain.** The guard configuration (harm model, invariant registry, tier assignments, verifier registry) lives in a **separate trust domain**, versioned and signed, not modifiable by the system it constrains. If the agent can rewrite the invariant, the induction collapses — this is structural, not a policy preference.

---

## 3. Component inventory

Status: **BUILT** (exists, verified) · **PARTIAL** (exists, gaps named) · **DESIGN** (specified here, not built) · **OPEN** (design choice unresolved; selection route named).

### 3.1 Substrate

| id | component | status | notes |
|---|---|---|---|
| S1 | Append-only event store | PARTIAL | Ledger pattern exists (`wallet.py` pure fold, `ledger.py` append-only). Must be **generalized** beyond credits to arbitrary staged state. |
| S2 | Capability attenuation | BUILT | Theorem + code witness (`verify_delegation`). The memory must-declare clause is what makes `capability_subset` transitive — **do not "simplify" it away.** |
| S3 | Provenance envelopes | BUILT | Signed chain. This *is* the staging log; treat it as such. |
| S4 | Sandbox enforcement | PARTIAL | **Fails open** when no enforcement record is stamped. Empty-record hole: a content-free record passes when the manifest declares no memory cap. |
| S5 | Reproducible builds + attestation | DESIGN | Until this exists, "oracle-free" carries an asterisk: the enforcement record is stamped by a self-reported runner build. |

### 3.2 Containment layer

| id | component | status | acceptance criterion |
|---|---|---|---|
| C-1 | **Harm model registry** | DESIGN | Every harm class declares: quantity (pure function of state), frame (and whether the frame is mutable), bound level, and the code path that computes it. Bounds are currently TBD and are a **user decision** — the registry must load them, not invent them. |
| C-2 | **Invariant registry** | DESIGN | Each invariant carries a **class tag**: `CONSERVATION` \| `MONOTONE_NON_CUMULATIVE` \| `CUMULATIVE`. The tag is not documentation — the scheduler reads it to decide concurrency (C6/C7). An untagged invariant must be rejected at load. |
| C-3 | **Reversibility classifier** | DESIGN | Maps each action type to `REVERSIBLE_INTERIOR` \| `IRREVERSIBLE` \| `EGRESS`. Must be a **static table over the action vocabulary**, not a prediction (C10). Unknown action type ⇒ `IRREVERSIBLE` (fail closed). |
| C-4 | **Guard evaluation engine** | DESIGN | Evaluates invariants per state transition. Must invoke the **same function** the harm measure uses (frame alignment, C3). Must be enforced **per action**, not at grant time. |
| C-5 | **Staging area** | DESIGN | Append-only interior. Nothing written here is visible outside until promotion. |
| C-6 | **Promotion gate** | DESIGN | Batched, serialized. The **only** place cumulative invariants are evaluated (C7). Also the irreversibility gate and the escalation trigger. |
| C-7 | **Checkpoint / rollback** | DESIGN | Rollback to last promotion. Note: rollback bounds *resource and ownership* loss; only append-only storage bounds *content* loss (R11 A2). |
| C-8 | **Guard configuration** | DESIGN | Separate trust domain, signed, versioned. Guard updates are the maximally-gated action — multi-principal, serialized, human. |

### 3.3 Verification layer

| id | component | status | acceptance criterion |
|---|---|---|---|
| V-1 | **Verifier registry** | DESIGN | Claim type → verifier. Populated by humans, versioned with the guard config. |
| V-2 | **Tier router** | DESIGN | A **type check**: does this claim type have a registered verifier (tier 1), a registered partial spec (tier 2), or neither (tier 3)? Statically decidable, no model call, non-gameable (C10). |
| V-3 | **Native verifier adapters** | PARTIAL | Signature verification, ledger fold, capability-subset check, hash comparison exist. Unit-test execution adapter needed. |
| V-4 | **Partial spec registry** | DESIGN | Human-authored, one spec per **claim type** (not per instance) — this is what makes it affordable (C11). Each spec carries an invariant class tag like C-2. |
| V-5 | **Spec evaluation engine** | DESIGN | Runs registered specs. Must report **kill rate against a mutation set**, not just "the spec accepted it" — verifiable-but-vacuous is the dominant failure mode (R14). |

### 3.4 Coordination layer — **0% designed, 0% built. The largest gap.**

| id | component | status | acceptance criterion |
|---|---|---|---|
| K-1 | **Task representation** | DESIGN | A task carries: goal, claim type, tier (from V-2), harm classes touched, and a parent link. Type is what everything else routes on. |
| K-2 | **Decomposer** | OPEN | See **SR-1**. Constraint: a decomposition is itself a claim ("solving S₁…Sₙ and combining yields G") and generally has no native verifier. Conservation-preserving decompositions (partition, map, filter) **do**. |
| K-3 | **Allocator** | OPEN | See **SR-2**. Must be structural — allocate by claim type / capability class, never by predicted competence (C10). |
| K-4 | **Executor pool** | DESIGN | Runs subtasks in the staging interior. Concurrency governed by C-2 class tags: conservation/monotone run concurrent; cumulative serialize. |
| K-5 | **Combiner** | OPEN | See **SR-3**. Cannot be voting or agreement (Route 2, dead). Must be verified fold (tier 1), spec-checked merge (tier 2), or contained concatenation (tier 3). |
| K-6 | **Scheduler** | DESIGN | Reads invariant class tags and tier assignments. Enforces: depth cap per tier (C14), serialization at cumulative checks (C7), promotion batching. |
| K-7 | **Retry / escalation policy** | OPEN | See **SR-4**. Prior: retry does not help systematic errors (resampling is blind to reproducible failure). Escalation target is H-1. |
| K-8 | **Termination detection** | DESIGN | A task terminates on: goal satisfied (verified where possible), depth cap reached, harm budget exhausted, or escalation. All four must be explicit states, not implicit timeouts. |

### 3.5 Interface and observability

| id | component | status | acceptance criterion |
|---|---|---|---|
| H-1 | **Escalation queue** | DESIGN | Where tier-3 irreversible actions and exhausted budgets go. Must present the claim, its provenance chain, and the specific bound that would be exceeded. |
| O-1 | **Audit log** | BUILT | The provenance chain. Third-party verifiable. |
| O-2 | **Metrics** | DESIGN | Per run: tier distribution, depth reached, harm consumed per class as a fraction of bound, promotion batch size, escalation rate, throughput. |
| O-3 | **Alarms** | DESIGN | Harm approaching bound; tier-3 fraction rising (vocabulary drift); escalation rate spike; any invariant evaluated but not enforced. |

---

## 4. Open design choices — selection routes

Each route below resolves one engineering choice. **Selection-route discipline** (differs from discovery-route discipline):

1. Preregister the metric, the decision rule, **and an equivalence bound** — what "no meaningful difference" looks like.
2. Cap variants at **three**. Comparing more requires multiple-comparison correction and usually means the question is under-specified.
3. Report the **full frontier**, not just the winner.
4. **Occam tiebreak:** if the winner is within the equivalence bound of the simpler option, pick the simpler option and say so.
5. A route closes when the choice is made. Do not reopen without new evidence.

---

### SR-1 — Decomposition strategy (resolves K-2)

**Question.** Which decomposition strategy maximizes the fraction of subtasks landing in tier 1 or 2?

**Variants.** (a) **Flat** — split into independent subtasks, no nesting. (b) **Recursive** — decompose until every leaf is tier 1/2 or depth cap. (c) **Planner-first** — one model emits a full plan, then execute.

**Metrics.** Tier distribution of resulting subtasks (primary); decomposition faithfulness — for conservation-preserving decompositions, does the mechanical check pass; depth reached; wall-clock and token cost.

**Constraint to respect.** The decomposition claim itself is usually tier 3. Report what fraction of decompositions are *conservation-preserving* (partition/map/filter over a collection), since those are the only mechanically checkable ones.

**Decision rule.** Prefer the variant maximizing tier-1+tier-2 subtask fraction. Equivalence bound: 5 percentage points. If within it, prefer flat (simplest, no depth risk).

---

### SR-2 — Allocation policy (resolves K-3)

**Question.** How much does structural allocation lose against an oracle?

**Variants.** (a) **Round-robin** (floor). (b) **Type-routed** — allocate by claim type to a registered handler. (c) **Oracle** (ceiling, not deployable) — allocate to the agent that would in fact succeed, computed post hoc from cached outcomes.

**Metrics.** Task success rate; escalation rate; throughput. Report all three; success alone hides an allocator that escalates everything.

**Decision rule.** Type-routed is the design default (C10 forbids predictive allocation). The route's job is to **measure the gap to oracle**, which sets expectations and tells you whether investing in richer type taxonomies pays. If type-routed ≈ round-robin, the type taxonomy is too coarse — that is a finding about the taxonomy, not the allocator.

---

### SR-3 — Combination operator and **tier algebra** (resolves K-5)

**This is the most valuable open question in the document and the direct extension of the invariant taxonomy into coordination.**

**Question.** Under which combination operators is **tier preserved**? If `f` and `g` are tier-1 claims, is `f∘g` tier-1?

**Reasoning to test, not assume.** Proofs compose, so proof-carrying claims should preserve tier to arbitrary depth. Tests are finite samples and do not compose — two components each passing their tests can violate an interaction property no test covers. Conservation and monotone specs compose; cumulative specs do not (R14 Part B, and C6/C7).

**Variants.** (a) **Verified fold** — combine only where a verifier exists for the combined claim. (b) **Spec-checked merge** — combine under a registered partial spec on the result. (c) **Contained concatenation** — no correctness claim on the combination, containment only.

**Metrics.** Tier of the combined claim (the primary result — build the algebra table); end-to-end correctness where measurable; whether a single-stage mutation is caught by the per-stage checks (the compositionality test).

**Deliverable.** A **tier algebra table**: for each (input tiers, operator) pair, the output tier and the side condition required. This is what the scheduler consults to decide whether a deep chain is permitted.

**Expected shape** (state as prediction, then test): conservation and monotone preserve tier; cumulative does not and forces the combination to the promotion gate; test-carrying claims degrade tier on composition.

---

### SR-4 — Retry and escalation policy (resolves K-7)

**Question.** Does retry recover failures, or does it burn budget on reproducible errors?

**Variants.** (a) **No retry** — fail to escalation immediately. (b) **Bounded retry** — k attempts, then escalate. (c) **Retry-with-decomposition** — on failure, decompose further and retry the parts.

**Metrics.** Recovery rate; wasted-token fraction (tokens spent on attempts that never succeed); escalation latency.

**Prior to state.** Resampling does not fix systematic errors — a reproducible failure reproduces. Expect (a) ≈ (b) on recovery with (b) costing more, and (c) to be the only variant that changes the error's *character*.

**Decision rule.** Equivalence bound 3 percentage points on recovery rate. If (b) is not meaningfully better than (a), pick (a) — it is simpler and cheaper.

---

### SR-5 — Promotion granularity (resolves C-6 parameterization)

**Question.** At what batch size should staged work be promoted?

**Variants.** per-action · per-task · per-batch-of-k-tasks.

**Metrics.** Harm bound consumed; effective throughput (**admitted-and-not-rolled-back** per unit time — nominal throughput is a trap: a configuration that rolls back everything shows high nominal and zero effective); escalation rate; gate cost amortization.

**Prior.** Under append-only, the harm/throughput frontier may **collapse** rather than trade off — a middling k may dominate both extremes. If so, report NOT-A-FRONTIER and pick the dominating point.

---

### SR-6 — Depth cap calibration (parameterizes K-6)

**Question.** What is the empirical error-vs-depth curve, per tier?

**Method.** Chain subtasks where each output feeds the next; measure realized end-to-end correctness at depths 1, 2, 4, 8, 16, per tier. Do **not** re-litigate whether a threshold theorem exists — it does not (redundancy cannot push chain error below the common-mode rate, and nested failure sets make majority vote equal the best single replica). This route sets a **parameter**, not a theory.

**Deliverable.** A per-tier depth cap for the scheduler. Expect tier 3 to cap near 10 and tier 1 not to cap.

---

## 5. Build sequence

Dependencies are real; do not reorder without stating why.

**Phase 0 — unblock (days).**
`E1` merge and tag packaging. `E2` fix S4's fail-open gate and empty-record hole. `D1` load harm-model bound levels from user decision into C-1. **Nothing downstream can be claimed until D1 exists** — every containment claim is scoped to a declared model.

**Phase 1 — containment in code (weeks).**
C-1 registry → C-2 registry with class tags → C-3 static reversibility table → C-4 evaluation engine. Then generalize S1 beyond credits. Conservation invariant on the credit ledger evaluated on the **current** frame. Route market P&L *through* the ledger rather than extending the gate — extending the gate forfeits all three architectural guarantees.

**Phase 2 — staging (weeks).**
C-5 staging area → C-6 promotion gate → C-7 checkpoint/rollback → C-8 guard config in a separate trust domain. Run **SR-5** to parameterize promotion granularity.

**Phase 3 — verification (weeks).**
V-1 registry → V-2 tier router → V-3 adapters → V-4 partial spec registry (human-authored) → V-5 evaluation with mutation-based strength measurement.

**Phase 4 — coordination (months; not a solo build).**
K-1 task representation → **SR-3** (tier algebra — do this before K-5, the algebra determines the combiner) → **SR-1** (decomposer) → **SR-2** (allocator) → K-4 executor → K-5 combiner → K-6 scheduler with **SR-6** depth caps → **SR-4** (retry) → K-8 termination.

**Phase 5 — interface and validation.**
H-1 escalation queue → O-2/O-3 metrics and alarms → S5 reproducible builds and attestation → **one external person runs it** → real-environment test.

**Recommended first real environment:** software engineering. Git is append-only by construction, the interior is fully reversible, and there is exactly one gated egress (merge/deploy). The architecture fits it almost without adaptation.

---

## 6. Standing discipline

Carried unchanged from the research program. Every entry in `ARTIFACT_LEDGER.md` was caught by these rules; they are not ceremony. (Cite the entry, not a count — a count is not a ledger.)

1. **Preregister before data.** Commit the design, metric, and decision rule before any code that produces a result. Git timestamp is the record.
2. **Diagnose any exact 0 or 1 before reporting.** Four artifacts were caught by this rule alone. A clean number is a suspected coupling until proven otherwise.
3. **Always report the counter-metric.** FPR beside TPR. Permissiveness beside adequacy. Throughput beside containment. Escalation rate beside recall. Kill rate beside validity. A metric reported alone is a metric that hides its failure mode.
4. **Check every threshold against its feasibility ceiling, computed under the mechanism's own dynamics** — not against a static state. Guards change the trajectory they are evaluated on. Three defects of this species have occurred.
5. **Harm is defined independently of any guard.** The environment computes it; guard-side arithmetic is named distinctly. Deriving the harm measure from the gate makes adequacy tautological.
6. **Explicit search is ground truth; closed forms are optimizations validated case by case.** Disagreement is a finding, never a patch.
7. **Negative results are successes.** A design that does not work, established cleanly, saves more than a design that appears to work.
8. **No tuning after seeing data.** Implementation-bug fixes only, disclosed with their rates.
9. **Verify citations against the tree**, including citations in this document.
10. **Any cumulative measurement must name its origin explicitly, and that origin
    must be immutable for the lifetime of the bound.** A cumulative bound whose
    origin can move is not a bound. Added after artifact #13
    (`ARTIFACT_LEDGER.md`): the C-6 promotion gate measured cumulative harm from
    the *moving* rollback checkpoint, so promoting after every action bought
    unlimited drain. R9's G4′ pinned a frame that should have floated; this
    floated a frame that should have been fixed. **Both are frame drift** — the
    lemma is that the invariant's frame must be the *harm's* frame, and which
    one that is depends on whether the harm is instantaneous or cumulative.

---

## 7. Acceptance criteria for "the system logic is built"

The build is done when all of the following hold and are demonstrated, not asserted:

- [ ] A task enters, is decomposed, routed by tier, executed in staging, promoted through the gate, and either completes or escalates — end to end, with a provenance chain a third party can verify.
- [ ] Every harm class in C-1 has a declared bound, an invariant in C-2 with a class tag, and a guard in C-4 that evaluates the same function the harm measure uses.
- [ ] The tier router makes a decision with **zero model calls**.
- [ ] Cumulative invariants are evaluated **only** at the promotion gate; conservation and monotone invariants run concurrent in the interior. The scheduler enforces this from class tags, not from hard-coded knowledge.
- [ ] An unauthorized irreversible action is refused, and the refusal cites the specific bound.
- [ ] Rollback to the last promotion restores interior state; the test suite includes a case where content loss would occur under mutable storage and does not under append-only.
- [ ] Guard configuration cannot be modified by the system it constrains — demonstrated by an attempted self-modification that is refused.
- [ ] The tier algebra table (SR-3) exists and the scheduler consults it before permitting a deep chain.
- [ ] Metrics O-2 are emitted per run; alarms O-3 fire on a synthetic near-violation.
- [ ] One person who is not the author has installed it, run it, and reported what broke.

That last item has been outstanding longer than any other and gates the value of all the rest.

---

## 8. What this plan does not solve, stated plainly

- **Semantic-content harm.** A persuasive, false, or manipulative output violates no state predicate. Competence bound, terminal.
- **Aggregate alignment.** Individually-bounded, individually-correct agents composing into collective harm. No formalism exists anywhere; years-scale; needs the substrate running to study.
- **Cumulative cross-principal harm under local checks.** Proven closed (C12). Requires serialization, always.
- **Harm-model completeness.** Not mechanically discoverable (C13). Requires adversarial human testing — the one discovery route still worth running, and it should run *before* any external claim about what the system guarantees.
- **Coverage generality.** The 58.8% native-verifier fraction is a property of Gyza's cryptographic/accounting vocabulary. The general lesson is the inverse of how it reads: **design the claim vocabulary so the fraction is high**, rather than measuring an existing vocabulary and hoping.


CANONICALIZE BEFORE COMPARING. An equality test between two REPRESENTATIONS of a value is a claim about the representation, not the value (artifacts #7 and #15 — a recurrence). Where an error of this species is suspected, check the SIGN of the residual: repr equality can only be stricter than value equality, so a one-directional error confirms the mechanism.

REGISTERING A CHECKER IS NOT EVIDENCE THAT IT RUNS. A registry makes a
component reachable, not exercised; a suite that builds its own fixtures never
touches the registered ones. 785 passing tests did not detect a harm quantity
that raised on every input (artifact #16). Assert that every registry entry is
executed against a real input.

AN ERROR IS NOT A VALUE. An exception written into the same channel as a
measurement makes "it broke" indistinguishable from "it found nothing", and
those are opposite claims. The false reading was the reassuring one -- 0%
unmeasured against a true 86.7% -- and the reassuring direction is the one that
does not get questioned.

A COUNT IS NOT A LEDGER. Cite the entry, not the tally. A count incremented in
prose drifts until it contradicts itself; the mechanisms survive only if they
are enumerated where they are caught (research/ARTIFACT_LEDGER.md).

A MONOTONICITY CHECK MUST BE COMPUTED OVER THE PROTECTED QUANTITY, NEVER OVER A
LABEL THAT CORRELATES WITH IT. GuardConfigStore tested the VERSION INTEGER and
called it monotone, so a correctly-signed higher version could raise every bound
and install cleanly -- in the guard configuration, which is the immutable trust
root the whole induction rests on. This is the THIRD instance of the species in
this program: R9's G4' pinned the frame at s_0, SR-5's gate floated the origin,
and this checked the label instead of the permissiveness. Each time the check
was over something that CORRELATES with the protected quantity rather than the
quantity itself. NOT recorded as a ledger artifact: the ledger is for clean
numbers that turned out false, and this produced no number -- it was found by
reading. Recording it here instead keeps the ledger's definition intact.
