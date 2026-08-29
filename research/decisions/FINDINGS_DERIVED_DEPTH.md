# Derived delegation depth — SOUND, and sufficient only at the claim boundary

**Branch `derived-depth`.** **ZERO CREDITS.** Analysis and source inspection; **no
mechanism was built**, for the reason in §6. **Part B was not reached** (§7).

---

## 0. Premise corrections

| stated | tree |
|---|---|
| "**SubcontractGrant** is canonically serialized and signed" | **`SubcontractGrant`: 0 hits.** The class is **`DelegationGrant`** (`delegation.py:336`). The *property* is correct — it is canonically signed |
| "adding a `delegation_depth` field… raises a legacy question" | **correct, and measured last session**: payload hash `da32c07d → 64df640d` |

**Eighteenth premise of this shape.** The substance held; the name did not.

---

## 1. A1 — THE SOUNDNESS COMPARISON, WHICH IS THE CRUX

### 1a. What a grant references — and the first surprise

`DelegationGrant`'s fields are `parent_envelope_hash`, `parent_agent_pubkey`,
`parent_manifest_hash`, `child_work_item_id`, `delegated_authority`,
`created_at_ns`, `schema_version`, `signature`.

> **NO FIELD REFERENCES ANOTHER GRANT.** Verified by dataclass introspection.
> **The grant graph has no edges**, and grants are **persisted nowhere**. So
> "walk the parent chain of grants" is not a thing that can be done — there is
> no chain.

### 1b. The envelope chain is the WRONG graph, and the code says so

`icp.py:147-152` defines two edge kinds:

> *"**causal spine** — `parent_envelope_hash` (**an agent's own prior action**;
> single-parent) … **data dependency** — each `input_hashes` entry … (a
> cross-agent dependency; this is how fan-in is expressed)."*

**`parent_envelope_hash` never crosses agents.** Walking it counts one agent's
sequential actions — an agent doing 40 actions has envelope depth 40 and
delegation depth 1. **Derived depth over the envelope chain would measure the
wrong quantity**, and would return ~0 delegation hops on every chain.

### 1c. The graph that DOES carry delegation

`WorkItem` (`schema.py:34-37`) carries **`parent_id: str | None`**, and a child
work item is created **only by subcontracting** (`coordinator.py:169`,
`child_wid = uuid.uuid7()`, posted with a grant).

> ### **The work-item parent chain IS the delegation chain: one hop = one subcontract.** That is the graph to walk, and it is neither the grant graph (no edges) nor the envelope graph (within-agent).

**And it is cryptographically covered**, though not by the granter:
`WorkItemRecord.parent_id` travels in `BlackboardDelta`, whose `app_signature`
is *"BLAKE3(serialize(delta_with_app_signature_field_zeroed))"*
(`netd.pb.go:1834`) — so the publishing compositor signs it.

### 1d. THE COMPARISON — and derivation wins, for a reason that is not obvious

| | **RECORDED** field | **DERIVED** walk |
|---|---|---|
| signed by | **the granter**, in the grant payload | **the publishing compositor**, over the gossip delta |
| trust assumption | the granter does not **understate its own depth** | the item graph is complete and the publisher did not lie about `parent_id` |
| understatement attack | a granter at depth 40 writes `depth=0`. **The signature is valid over the false value** | a publisher sets `parent_id=None`. Same shape |
| **third-party detectable?** | **NO.** There is nothing to compare the asserted value against — it is self-report with no witness | **YES.** The item graph is gossiped to peers; a false `parent_id` is inconsistent with the record other nodes hold |

> ### **DERIVATION IS THE STRONGER ASSUMPTION FOR THIS CODEBASE.**
>
> Both are self-assertable. The asymmetry is **redundant witnessing**: a
> recorded depth is a claim about a quantity **nobody else holds**, while a
> derived depth is a claim about a **replicated graph**. A granter cannot
> understate a depth it does not assert — and the thing it *would* have to
> falsify instead is visible to every peer that holds the blackboard.
>
> **This is A1's crux and it goes the way A1 guessed, but for the witnessing
> reason rather than the signing reason.** Both links are signed; only one is
> corroborated.

---

## 2. A2 — TERMINATION: **already handled, and I should reuse it**

`blackboard.py:684-700` **already walks this chain**, and already bounds it:

```python
# Bound the climb so a corrupted parent cycle (shouldn't happen
# under the schema's FK but defense-in-depth) doesn't loop.
for _ in range(10_000):
```

**Cycles are prevented structurally by the schema's foreign key and bounded
defensively at 10,000 iterations.** The bound is **stated, not implicit**, which
is what A2 asks for. **No new termination argument is needed** — and writing a
second walk would be the second-frame error this program keeps catching.

---

## 3. A3 — COST

**One SQLite lookup per hop, local.** At depth 3: **3 queries**. At the current
cap that is the whole cost.

**No network access is required for the walk itself** — but the walk returns a
**`missing` sentinel** when an ancestor's envelope is not locally held, *"a
remote envelope that hasn't been gossiped to us, or a parent that hasn't
completed yet."* **That is the distributed case, and it is §5's problem.**

---

## 4. A4 — WHERE THE CHECK CAN SIT: **not at creation**

**At grant creation** (`coordinator.py:190-199`) the `SubcontractCoordinator`
holds exactly three things: a `ParentRef`, a `ReservationBook`, and a
`SubcontractEffects` protocol whose entire surface is `post_subtask`,
`await_result`, `cosign_as_payer`.

> **None of them exposes the work-item graph.** The coordinator *knows its own*
> `work_item_id` (`ParentRef.work_item_id`) but has no way to walk from it.
> **A creation-time derived check requires a new dependency on the grant hot
> path.**

**At the claim boundary it is already in hand.** `runner.py:339`:

```python
ancestors_chain, missing = self._bb.reconstruct_chain(parent_id)
```

This runs **in production**, at the claim boundary — *"before we burn local
compute on something we can't prove came from honest history"* — and
`len(ancestors_chain)` **is the derived depth, already computed.**

> **So the honest statement A4 asks for: this is a VERIFICATION-TIME property.
> It rejects on use rather than preventing existence.** A chain deeper than 3
> can come into existence; no one will work on it.

---

## 5. THE FAILURE MODE, AND IT IS THE ONE THE RECORDED FIELD WAS REJECTED FOR

`runner.py:340-357`: when `missing` is non-empty, behaviour depends on
`_strict_chain_verification` — and the **default is fail-OPEN** (*"Fail-open:
log once per item, accept the claim"*).

> ### An incomplete ancestor chain reads as SHALLOW.
>
> That is **exactly the "absent-read-as-zero is maximally permissive" failure**
> that made the recorded field a release decision — **arriving by a different
> route.** Withholding one ancestor makes a depth-40 chain look like depth 2.
>
> **A sound derived check must treat `missing != ""` as REFUSAL**, which the
> blackboard's own docstring already recommends: *"Callers that need a strict
> guarantee should treat `missing != ""` as verification failure."*

**And that is a policy change, not a code change:** flipping the depth dimension
to fail-closed can take live functionality offline whenever gossip is
incomplete — the same availability-versus-safety trade as the FAIL_CLOSED
cutover and the signing gate. **It is the user's call, and it is the reason
nothing was built here.**

---

## 6. A5 — THE VERDICT: **SOUND BUT INSUFFICIENT**

| | |
|---|---|
| **Sound?** | **YES.** The work-item parent chain is the delegation chain; cycles are bounded; the link is signed *and* redundantly witnessed — a **stronger** assumption than the recorded field (§1d) |
| **Sufficient at creation?** | **NO.** The coordinator has no item-graph access; adding one is a new dependency on the grant hot path |
| **Sufficient at claim time?** | **YES, and the data is already in hand** at `runner.py:339` |

### What it buys

- **Truncation resistance — the weakness I measured last session.** `len(chain)`
  counts what a caller *presents*; a 40-hop holder presenting 3 hops verifies OK.
  **A derived walk counts the item graph and catches that**, which is the main
  thing the recorded field would have bought.
- **At zero release risk.** No format change, no signature migration, no legacy
  question.
- **Reuses an existing production walk**, so no second frame.

### What it does not buy

- **Prevention.** A too-deep chain still comes into existence.
- **Soundness under incomplete gossip**, unless the fail-open default is flipped
  for this dimension (§5).

> **The recorded-field decision stays open for the user, and is now a narrower
> question:** it is worth its release cost **only** for creation-time prevention,
> because everything else derivation gives for free.

### A6 — determinacy: **STILL UNDERDETERMINED**

With attenuation (proven) and depth ≤ 3 (enforceable at claim time), the
correctness component of a grant is still not INTERNAL:

> **Attenuation constrains HOW MUCH authority moves; depth constrains HOW FAR.
> Neither says WHO MAY RECEIVE IT.** **Still unnamed: the recipient predicate** —
> the same gap as the last two sessions, and depth does not close it.

---

## 7. Part B — NOT REACHED, and I am not going to rush it

**A did not resolve quickly.** It required tracing three separate graphs (grant,
envelope, work-item) before the right one was identified, and the verdict turned
on a witnessing argument that is not visible from any single file.

**Per-principal reservation deserves better than the remainder of a session**,
and `OPEN_PROBLEM.md:436-445` attaches a binding condition:

> *"the route is legitimate **only** if … preregistered by someone who has
> [seen AG-3's results], with **AG-3's counts treated as a stated prior** and the
> entire design — guard definition, metric, decision rule, feasibility ceiling —
> **fixed and committed before any new measurement**."*

**I have now read AG-3's results.** So B's preregistration must be written and
committed **before** any code touches the federation environment. **Starting it
with an hour left would produce exactly the post-hoc design that condition
forbids.**

**Also worth carrying into B, from `OPEN_PROBLEM.md:429-434`:** its scope is
bounded in advance — reservation addresses only condition (ii), recency, and
**cannot make a ratio-type bound such as concentration composable**, because the
inter-principal counterexample stands. Its plausible reach is **same-direction
quantities only.** B5's structural question therefore has a **predicted answer
already on the record**, and the preregistration must state it as a prior rather
than discover it.

---

## 8. Honest limits

1. **Nothing was built.** The verdict is SOUND-BUT-INSUFFICIENT and the one
   change that would make it enforceable — fail-closed on incomplete chains — is
   an availability decision, not a code decision.
2. **§1d's "stronger assumption" is authored judgement**, not a measurement. It
   rests on the claim that a replicated graph is harder to falsify undetected
   than an unwitnessed scalar. I believe it and it is arguable.
3. **The work-item-hop = delegation-hop identity is read from one call path**
   (`coordinator.py:169` + `post_subtask`). If any other path creates a child
   work item without a grant, derived depth would **over**count — the safe
   direction, but it would make the check noisy rather than wrong.
4. **`len(ancestors_chain)` counts ancestors with ENVELOPES.** An ancestor that
   has not completed has no envelope, so it may be absent from the returned
   chain even when `missing` is empty. **That needs checking before any
   implementation** — it is a second route to the read-as-shallow failure.
