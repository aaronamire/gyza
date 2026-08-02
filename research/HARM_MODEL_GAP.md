# Harm-model gap — the 13 unmeasured stateful action types

**A PROPOSAL, NOT A DECLARATION.** Nothing here registers a harm class or sets a
bound. Declaring what harm a system must bound is a statement of what its owner
is willing to lose, and that is not a decision an implementer makes.

**Source of the list.** `selection_routes/unmeasured_actions.json` — for each
action type in the C-3 vocabulary, apply it and ask whether any *declared* harm
quantity moves. 19 action types, 15 change state, **13 move nothing**. Sound in
one direction only: a gap found is definite; a gap not found proves nothing
(R12).

**Columns.** (a) the quantity that would plausibly move; (b) whether it is a
**pure function of state** — the precondition for being a declarable harm class
at all; (c) its invariant class if declarable; (d) whether any existing code
computes it.

---

## Declarable — a state function exists

| action | (a) quantity | (b) pure fn of state | (c) class | (d) existing code |
|---|---|---|---|---|
| `delete_artifact` | content made unreachable: `|{contents in s₀} \ {reachable in s}|` | **yes** — a fold over the artifact store plus archive | CONSERVATION | R10's `lost_by_class` computes exactly this **in the research environment**; nothing in `gyza/` does |
| `rotate_key` | credits attributable to the retired key that become unreachable | **yes** — settled entries referencing the old key are append-only state | CONSERVATION | **none.** No rotation path exists; `settlement.py:71-72` defers it, and `HARM_MODEL_DRAFT` flags it as R9's frame lemma unimplemented |
| `grant_delegation` | outstanding delegated authority — breadth of the granted `CapabilitySpec`, or count of live grants | **yes** — the chain is append-only and `CapabilitySpec` is state | MONOTONE_NON_CUMULATIVE for attenuation; CUMULATIVE for total outstanding | `verify_delegation` **checks** attenuation but does not **measure** granted breadth; H4 counts *violations*, not authority handed out |
| `stage_artifact`, `stage_envelope` | **storage growth** — bytes or events retained | **yes** — log length is a fold | CUMULATIVE | **none** |
| `update_guard_config` | change in the guard's own **permissiveness** — e.g. Σ bound levels, or count of invariants removed | **yes** — config is versioned state and bounds are numbers | MONOTONE_NON_CUMULATIVE (bounds should not loosen) | **none** — see the finding below |
| `sign_envelope` | count of non-repudiable claims emitted | **yes** for the *count* | CUMULATIVE | envelope-log length; nothing bounds it |
| `external_send`, `send_message`, `publish_agent`, `publish_delta`, `publish_attestation`, `write_outside_sandbox` | count/volume of emissions beyond recall | **yes** for the *count* | CUMULATIVE | **none** counts them |

### Two findings that fall out of the table

**1. The architecture's own stated cost has no declared bound.**
`ARCHITECTURAL_PRINCIPLE.md` says the price of append-only is that **nothing is
ever freed**, "paid forever". `stage_artifact`/`stage_envelope` grow storage
without limit and **no declared quantity measures it**.

#### PROPOSAL: a storage-growth harm class (not registered, no bound set)

| | |
|---|---|
| **quantity** | retained bytes, or retained event count: `Σ len(event) over the append-only log`, including abandoned (rolled-back) events, which by design are never removed |
| **frame** | the log itself — a single append-only sequence per node. **Immutable origin**: the log's genesis, per discipline #10. A storage bound whose origin moved with each promotion would be the SR-5 defect again |
| **pure function of state?** | **yes** — it is a fold over the log, the same shape as `balance_fold`. No stored aggregate is needed and none should be added |
| **invariant class** | **CUMULATIVE**, almost certainly. Retained bytes only increase; nothing frees them; the quantity is a running total by construction |
| **existing code** | `AppendOnlyLog.__len__` and the events themselves. Nothing measures bytes, and nothing bounds either |

**And the class placement is convenient rather than awkward.** CUMULATIVE means
C7 applies: it cannot be bounded by any stateless local check and must be
evaluated at a **serialization point**. The architecture already has exactly
one — the promotion gate — and already serializes there for the credit budget.
So if a storage bound is ever declared, **it lands in the place the design
already pays for**, with no new serialization and no new coordination.

**The meta-point, recorded in `ARCHITECTURAL_PRINCIPLE.md` as well:** the
document states a cost it does not bound. That is the architecture failing its
own rule applied to itself — the rule being that a safety-relevant quantity
should be a declared fold that a guard reads.

**2. The guard configuration refused downgrades by VERSION but not by
PERMISSIVENESS — now FIXED.** `GuardConfigStore` tested `version <= current` and
nothing else, so a correctly-signed **v2** could raise every bound and install
cleanly. **Owner decision taken:** bounds MAY loosen, but loosening is a
**distinct operation**. Permissiveness is now computed structurally per bound
(`diff_bounds`), the ordinary update path refuses any config that loosens
anything, and loosening requires a separately-signed `LooseningRecord` naming
exactly the bounds that move with their old and new values and a reason — a
record that under-reports is refused, and every loosening raises an O-3 alarm.

**One subtlety that had to be right:** an UNSET bound **fails closed**
(`engine.py:99-101` refuses every action on an unbounded class), so **adding** a
bound is a *loosening* and **removing** one is a *tightening*. Computed from
magnitudes alone, both come out inverted — which is the same label-vs-quantity
error the fix exists to correct, one level down.

---

## NOT declarable as state functions — the competence bound, reappearing

For these, a *count* is declarable but the **harm is not the count**, and no
function of the modelled state distinguishes a harmless instance from a
catastrophic one.

| action | what is countable | why the harm is not a state function |
|---|---|---|
| `external_send`, `send_message`, `publish_*`, `write_outside_sandbox` | how many emissions | The harm is **what the emitted content does in the world**. That leaves modelled state entirely (C15: a guard can refuse to emit; after emission there is no containment and no detector helps). Bounding the count bounds the *rate of exposure*, not the *consequence*. |
| `sign_envelope` | how many envelopes | The harm is **attesting to something false**. Whether a signed claim is true is semantic content — the competence bound, closed across six families and terminal. |
| `delete_artifact` *(partially)* | reachability loss | Reachability **is** a state function and belongs in the table above. But *whether the lost content mattered* is semantic. R9 made the point directly: one deletion of the right object is catastrophic while one deletion of a duplicated object costs nothing. R10's reachability measure captures the structural half and not the rest. |

> **This is the competence bound reappearing in the harm model rather than in
> verification, and it is worth naming as such.** The verification layer met it
> as "cheap checking cannot establish correctness". The harm model meets it as
> **"the quantity you actually care about is not a function of the state you
> can observe."** Same wall, different face. A harm model can be complete over
> *state* and still silent about *consequence*, and no amount of declaring fixes
> that — which is why §4.2's human red team is about completeness of the
> declared model and not about closing this.

---

## What this changes about the containment claim

The containment results are **not** invalidated: they were always scoped to
declared harm. What the table shows is how narrow "declared" currently is —
**2 of 15 stateful action types (13.3%)** — and that the untouched majority is
not exotic. It is deletion, key rotation, delegation, storage growth, guard
updates, and every form of emission.

Roughly two thirds of the gap is **declarable today** and is a specification
task, not a research problem. The remaining third is the semantic residue above,
and no specification closes it.
