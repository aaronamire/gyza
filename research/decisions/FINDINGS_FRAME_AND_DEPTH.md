# The window has an identity; the depth field is a release decision

**Branch `frame-and-depth`.** **ZERO CREDITS.** Two commits, A first.
**A: shipped. B: STOPPED at B1, as B1 instructs.**

---

## 1. A4 — WHO GOVERNS THE WINDOW: **the caller, and that must be recorded**

> ### The window now has an **identity** and a **fixed origin**. It does **not** have a **fixed extent**.

`open_window()` is a public method. **A caller may open a new window whenever it
likes**, and doing so starts a fresh accounting period. So "10% per window" is
still gameable by *opening early*, in exactly the way A4 anticipated.

**What changed is nonetheless substantive, and the distinction is worth stating
precisely:**

| before | after |
|---|---|
| the boundary was an **implicit side effect of `promote()`** | the boundary is an **explicit, named, logged act** |
| every promotion re-based the frame | **promotions do not touch the frame at all** |
| no window existed to name | a window has an **id, an origin, and an append-only record** |
| gaming was **invisible** — indistinguishable from normal operation | gaming is **a `__window_open__` event in a tamper-evident log**, with a `reason` field and a count anyone can audit |

> **The honest characterisation: a NAMED, CALLER-CONTROLLED, AUDITABLE window.**
> That is materially weaker than a fixed one — a scheduler-driven or
> wall-clock-driven boundary would be stronger — and materially stronger than
> what existed, because **the act of re-basing is now a recorded event rather
> than an ordinary method call.**

**What would make it fixed:** window boundaries driven by something the bounded
party does not control — elapsed time, or a signed guard-configuration schedule.
**Not built; it is a policy decision about who owns the clock.**

---

## 2. A1–A3 — WHAT WAS BUILT

**A1, as found:** `_pending_gate` (a plain list), `promote()` clearing it,
`_mark_promoted` appending `KIND_PROMOTE`. **A promotion was recorded; a window
was not, because there was nothing to record.** Confirmed: `promote()`'s only
callers are tests and one research script.

**A2 — the identity is the log's own sequence number.** `KIND_WINDOW_OPEN` is a
control event; **a window's id is its marker's `seq`**, and
`AppendOnlyLog.append` assigns `seq = len(self._events)` and never rewrites one.

> **So the origin cannot re-base for the window's lifetime — not by discipline,
> but because no operation exists that would do it.** Derived-not-stored,
> applied to the frame itself.

| added | what it is |
|---|---|
| `open_window(reason)` | appends the marker, returns the immutable id |
| `current_window()` | **derived** from the log; `0` = the genesis window |
| `window_origin_state()` | distinct from `baseline_state()` (moving checkpoint) **and** `origin_state()` (run origin) |
| `windows()` | folded from the log, so it **cannot disagree** with the log it summarises |
| promotions | now carry `window_id` **in the record**, not inferable from ordering |

**A3 — asserted, with the control that gives it meaning.**
`test_frequent_promotion_cannot_re_base_the_window_origin` runs ten
stage-and-promote cycles and requires the window origin unchanged;
`test_negative_control_the_moving_checkpoint_DOES_re_base` requires
`baseline_state()` to move over the same operations. **Without the second, the
first passes vacuously.**

### Two defects found by the checks rather than by review

1. **`events()` hides control kinds by default.** The first version could not
   see its own marker, so **every window silently read as GENESIS** — an absent
   frame reading as the most permissive one, which is the **empty-record hole**
   species. Fixed with `include_control=True`, reason recorded at the call site.
2. **The negative control failed first, and was right to.** My fixture staged
   events with no `delta`, so the projector summed zeros and **every comparison
   was vacuously equal**. The control detected exactly the vacuity it exists to
   detect. Fixed by giving the window tests real deltas.

**`0` is the genesis window, diagnosed: DEFINITIONAL.** `current_window()`
returns `0` rather than `None` when no marker exists, because **an absent window
must not read as "unbounded"** — the same reasoning as `UnsetBoundError` failing
closed.

---

## 3. A5/A6 — PER-BOUND ENFORCEABILITY AFTER THE FRAME FIX

**The frame now exists. That changes what is EXPRESSIBLE, and nothing about what
is READ.**

| bound | frame | enforceable? | read by a guard? |
|---|---|---|---|
| **H1 credits** | ✅ window origin available | **NO — still SPECIFIED-BUT-UNENFORCEABLE** | the *bound* is read; the **"10%" form is not expressible as a scalar** (last session: `_credits_at_risk` returns absolute credits) |
| **H2 market capital** | ✅ available | **NO** | ❌ **no gate reads the quantity at all** |
| **H3 irreversible** | ✅ available | **NO** | ❌ **not registered — no quantity exists to bound** |
| **H4 authority** | n/a (not cumulative) | ✅ | ✅ `verify_delegation`, structurally |

> **A5's instruction was not to upgrade a status because the frame now exists.
> No status is upgraded. The frame was a NECESSARY condition for three bounds
> and a SUFFICIENT one for none of them.**

**A6 — H2 stays unenforceable, and the window work must not be read as having
touched it.** `_capital` is a mutable dict mutated at four sites and folded by
nothing. **A frame for a quantity no gate reads changes nothing.** The fix
remains routing market P&L through `LedgerEntry`.

**Counter-metric:** `unbounded()` still returns `[]`, so
`can_claim_containment` is True — **while 1 of the 3 bounded classes has no
reader and 1 of the 4 declared classes is not registered at all.** *"All bounds
declared"* and *"all harms guarded"* remain different claims.

---

## 4. B1 — THE COMPATIBILITY VERDICT: **STOP**

**Determined from the code, not from intent.** `DelegationGrant`
(`delegation.py:336`) **is canonically signed**: `_grant_payload_bytes` is
*"canonical JSON of every field except `signature`"*, `grant_hash` is BLAKE3
over it, `sign_grant` is Ed25519 sign-the-hash.

**Measured, not reasoned:**

```
payload fields today: [child_work_item_id, created_at_ns, delegated_authority,
                       parent_agent_pubkey, parent_envelope_hash,
                       parent_manifest_hash, schema_version]
grant_hash today                    : da32c07dc2420ab1…
hash with a defaulted `depth` field : 64df640d12cd9998…
SAME BYTES? False
```

> ### **Adding `depth` changes the signed payload of EVERY grant, including ones already signed. Existing signatures would not verify.**
>
> **STOPPING here, as B1 instructs.** *"That is a release decision, not a code
> change, and the prior signed-bytes change was correctly deferred to the
> user."* This is the third signed-bytes change deferred in this program.

**Scope, as the counter-metric:** `DelegationGrant` is constructed at **two
production sites** (`coordinator.py:191`, `demo/ddil_partition.py:409`) and is
**persisted nowhere** in the tree — no store, no schema, no blackboard table.
**So the break may well be theoretical for this repository today.** But grants
are a **wire record** exchanged between peers, and the public mesh has been live
since S32; **whether any counterparty holds a signed grant is not knowable from
this tree.** That is precisely why it is the user's call.

**The clean path exists and is cheap:** `DelegationGrant` carries its own
`schema_version: int = 1`, deliberately separate from `ICPEnvelope`'s. **A v2
that adds `depth`, with v1 grants verified under the v1 payload rule, breaks
nothing** — and the comment at `delegation.py:309-315` shows this exact
forward-compatibility reasoning was already applied once, when a separate signed
artifact was chosen over an envelope schema bump. **Not built, because it is the
same release decision.**

---

## 5. B3/B4 — WHAT THE PREMISE GOT WRONG, AND THE REAL WEAKNESS

> **"Nothing tracks delegation depth… There is no depth field to count from, so
> the depth ≤ 3 cap is unenforceable."**

**FALSE, and I reported the same correction last session.** `delegation.py:261`:

```python
if len(chain) > max_depth:
    return False, f"delegation depth {len(chain)} exceeds max {max_depth} …"
```

**That is a genuine depth check over the presented chain, independent of the
three subset checks.** **Sixteenth premise of this shape.**

**MEASURED, both properties, exactly as B4 asks:**

| chain | result |
|---|---|
| 40 hops, **subset valid at every step** | **REFUSED** — *"delegation depth 40 exceeds max 3"* |
| within depth 3, **subset violated** | **REFUSED** — the attenuation check (pre-existing tests) |

**So B4's two properties both hold today and are independently enforced.** The
depth cap is not a subset check, and the codebase already treats them as
separate predicates — `delegation.py:317-327` names authenticity, soundness and
integrity as *"three orthogonal predicates over the same DAG, deliberately not
conflated."*

### The real weakness, which a depth FIELD would fix and `len(chain)` cannot

```
FULL 40-hop chain   -> ok=False  "delegation depth 40 exceeds max 3"
TRUNCATED to 3 hops -> ok=True
```

> **`len(chain)` measures the chain the caller CHOOSES TO PRESENT.** A holder of
> 40 hops can present the last 3 as if rooted there, and it verifies.
> `verify_delegation`'s own docstring states the precondition — the envelope
> chain must already have passed `verify_chain` — so soundness rests on the
> caller supplying the *full* chain.
>
> **This is exactly what a recorded `depth` would defeat: a hop whose grant says
> `depth=37` cannot claim to be a root.** So B's instinct is right, the
> mechanism it names is right, and **the thing that makes it worth doing is the
> same thing that makes it a release decision.**

**B5 — determinacy: STILL UNDERDETERMINED, and the depth field would not
complete it.** With strict attenuation (proven) and depth ≤ 3 (enforced against
an honest presenter), the correctness component of a grant is still not
INTERNAL:

> **Attenuation constrains HOW MUCH authority moves; depth constrains HOW FAR.
> Neither says WHO MAY RECEIVE IT.** A grant can attenuate perfectly, sit at
> depth 1, and still go to a principal that should never have had it.
>
> **STILL UNNAMED: the recipient predicate.** Both halves the policy names are
> nameable; the half it does not name is the one that blocks.

---

## 6. C — KNOWN_PRINCIPAL (report only, not built)

**C1's citation does not resolve. `get_or_create` has ZERO hits in `gyza/`.**
**Seventeenth premise of this shape** — and unusually, **the concern behind it is
real and lives in a different function:**

```python
def get(self, pubkey: str) -> float:          # gyza/economy/reputation.py:151
    """Return the recorded score, or _NEUTRAL_SCORE (0.5) if we have no
    observations of this pubkey."""
```

> **An unknown principal reads as an ordinary one with a neutral score.** Not
> auto-*creation*, but the same defect in effect: **"never seen" and "seen and
> unremarkable" return the same value**, so a predicate built on reputation
> cannot distinguish them. **That is the same species C1 describes.**

**The sound predicate already exists and is the right one:**
`TrustRegistry.is_trusted(pubkey)` (`trust_registry.py:139-146`) returns
**`False` for an unknown key and for a revoked one** — a genuine three-state
distinction collapsed correctly to a refusal.

**C2 — what an honest definition requires:** *known* must mean **someone
DECLARED this principal**, not **someone REFERENCED it**. `TrustRegistry`'s
`trusted_compositors` table is exactly that — an explicit registration, distinct
from first reference. **The gap is not the definition; it is that
`gyza/economy/settlement.py` imports no trust registry**, so nothing on the
credit-transfer path consults it.

**C3 — NOT BUILT.** It changes who can receive a transfer. **Policy consequence,
not mechanism gap, and it deserves its own decision.**

---

## 7. D — STATUS: THREE STATES, AND THE DIFFERENCE MATTERS

| bound | value | frame | **REGISTERED** | **ENFORCEABLE** | **ENFORCED** |
|---|---|---|---|---|---|
| **H1 credits** | 100.0 | ✅ window origin now exists | ✅ | ❌ *"10%" not expressible as a scalar* | ⚠️ the **absolute** bound is read at PROMOTION |
| **H2 market capital** | 100.0 | ✅ | ✅ | ❌ **no gate reads the quantity** | ❌ |
| **H3 irreversible** | — | ✅ | ❌ **not registered** | ❌ **no quantity exists** | ❌ |
| **H4 authority** | 0.0 | n/a | ✅ | ✅ | ✅ `verify_delegation` |

**D2 — the two egress respecifications:**

| claim | status |
|---|---|
| `capability_grant` / `grant_delegation` | **STILL BLOCKED** — on the **recipient predicate** (§5), not on depth |
| `credit_transfer` | **BLOCKED ON WIRING**, newly precise: the predicate exists (`is_trusted`), settlement does not import it |

**Neither is buildable purely from this session's work, and neither was built.**

**D3 — SPECIFIED-BUT-UNENFORCEABLE, and why:**

1. **H1 at "10% per window"** — the frame exists now; the **percentage form**
   needs an invariant *predicate*, not a bound *level*. `predicate(h, bound, s0,
   s)` receives the state, so it is expressible — as a small, unbuilt change.
2. **H2** — quantity unread; needs P&L through `LedgerEntry`.
3. **H3** — no quantity; needs an irreversibility measure written first.
4. **Depth ≤ 3 against a truncating presenter** — needs the signed `depth` field,
   which is the deferred release decision.
5. **The window's EXTENT** — named and auditable, still caller-controlled (§1).

---

## 8. Honest limits

1. **The window is caller-controlled.** §1. It is the single largest remaining
   weakness in the frame story and is not hidden by the identity work.
2. **`window_origin_state()` has no consumer yet.** The gate still measures from
   `origin_state()` (the run origin). **Wiring the gate to the window is a
   deliberate next step, not an oversight** — it changes what every cumulative
   bound means and should land with the bound-form change, not before it.
3. **The truncation weakness is measured but unmitigated**, pending the release
   decision.
4. **Nothing in production calls any of this.** `promote()` has no production
   caller, so the frame work is correct and idle.
