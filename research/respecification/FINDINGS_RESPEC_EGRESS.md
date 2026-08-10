# Respecifying the UNDERDETERMINED egress claims — **REFUSED at Gate 0**

**Branch `respec-egress`.** **Zero credits.** **No code was written**, so no test
run was required and none is claimed. **This is the fifth refusal under these
gates.**

---

## 0. GATE 0 — **there is nothing matching the description to respecify**

### 0a. The two named types do not exist

| stated | tree |
|---|---|
| `capability_grant` | **0 hits** across every `.py`, `.md`, `.json` |
| `credit_transfer` | **0 hits** |
| "the **eight** EGRESS action types" | **SIX** (`coverage.json`) |
| "**Six** are EXOGENOUS … **Two** are UNDERDETERMINED" | committed: **3 EXOGENOUS, 2 INTERNAL, 1 NO_CLAIM, and UNDERDETERMINED = 0** |

**Twelfth premise of this shape.** The committed classification
(`research/egress_q/classification.json`) records **zero** UNDERDETERMINED egress
claims, and §1d of that finding diagnosed the zero explicitly — including
stating that *had claim substitution been allowed, `external_send` would classify
UNDERDETERMINED and the frontier would look considerably better.* **The rule
forbids it. That diagnosis is the thing this task is asking me to undo.**

### 0b. The closest real analogues, and the three layers separated

The names the task uses correspond to two **IRREVERSIBLE** (not EGRESS) action
types. Their layers:

| layer | `grant_delegation` | `settle_credits` |
|---|---|---|
| **CONSERVATION** | ✅ **ALREADY CHECKED** — `delegation_attenuation`, **governed, PROOF**. `verify_delegation` (`delegation.py:213`): `manifest(hᵢ) ⊆ manifest(h₀)` at every hop, acyclic, depth ≤ 8 | ✅ **ALREADY CHECKED** — `balance_fold`, **governed, PROOF**; ledger is append-only with no `update_entry` (`ledger.py:30`) |
| **INTEGRITY** | ✅ **ALREADY CHECKED** — `envelope_signature`, governed, PROOF | ✅ **ALREADY CHECKED** — `ledger_entry_signatures`, **governed, PROOF** (recomputes `canonical_sign_bytes` per role) |
| **CORRECTNESS** | ❌ **no policy exists** | ❌ **policy hook exists, empty by default** |

> **TWO OF THREE LAYERS ARE ALREADY CHECKED AND GOVERNED AT PROOF FOR BOTH
> TYPES**, which is why neither appears in the audit residue — they were removed
> from it precisely because governed verifiers cover them. **The scope narrows to
> the third layer alone**, exactly as 0b anticipated.

**Conservation is not correctness, and the distinction is live here:**
`delegation_attenuation` proves authority never *increases* down a chain. It says
nothing about whether the grant should have been made at all. `balance_fold`
proves the books balance. It says nothing about whether the transfer was owed.

### 0c. **WHERE THE POLICY LIVES — and this is the finding**

| type | where correctness's policy lives today |
|---|---|
| **`grant_delegation`** | **NOWHERE.** No policy store, no policy hook, no policy parameter anywhere in the delegation path |
| **`settle_credits`** | **IN A CALLER'S HAND.** `AcceptancePolicy = Callable[[LedgerEntry], tuple[AcceptanceVerdict, str]]` (`settlement.py:266`), passed as `acceptance_policy: AcceptancePolicy | None = None` (`:382`) and consulted at `:799` **only `if self._acceptance_policy is not None`**. It is **optional, caller-supplied, unstored, unversioned, and named in no claim** |

**And the egress path already has the field, defaulted to "there isn't one":**

```python
NO_POLICY_DECLARED = "no-policy-declared"        # gyza/network/netd_client.py:138
def ...(..., policy_id: str = NO_POLICY_DECLARED):   # :150
```

> **The system already carries a `policy_id` field whose PRODUCTION DEFAULT is a
> sentinel meaning no policy was declared.** The claim does not fail to reference
> a policy. **It references the absence of one.**

---

## 1. WHY RESPECIFICATION IS NOT THE LEVER — the decisive argument

The frozen criterion, verbatim (`PREREGISTRATION_CLAIMS_CENSUS.md:33-35`):

```
Q3. Does a success condition exist, and would NAMING MORE PARAMETERS
    make Q2 answer YES, without acquiring any new fact
    from outside the system?                         -> UNDERDETERMINED
```

> ### **RESPECIFICATION CANNOT MANUFACTURE ITS OWN REFERENT.**
>
> If the policy has never been written, naming `policy_id` **references
> nothing**. The fact must be **CREATED, not referenced** — and authoring a
> permission policy is a product decision about what is allowed, which is
> precisely *"a new fact from outside the system."*
>
> **So these claims are not UNDERDETERMINED in Q3's sense at all.** Q3 asks
> whether a *success condition exists* and merely needs pointing at. Here it does
> not exist. Naming the parameter would produce a claim that is decidable
> **against nothing**.

**This refines the criterion's application rather than the criterion**, and it is
worth recording because the distinction is easy to miss:

| shape | example | lever |
|---|---|---|
| the claim omits a parameter whose referent the system **holds** | `memory_retrieval_relevance` — the corpus existed; the claim did not name the snapshot | **respecification** ✅ (this worked) |
| the claim omits a parameter whose referent **does not exist** | delegation permission policy | **authoring the policy** — a product decision, not respecification |

**0c's own framing anticipated this:** *"'Nowhere' is a legitimate and important
answer: it would mean the claim is underdetermined because the policy has never
been written, not because the claim fails to reference one."* **That is the
measured answer for `grant_delegation`, and one step weaker for
`settle_credits`, where a hook exists but is empty.**

---

## 2. PART A — NOT PERFORMED, and A3 is why

No parameter set is proposed. **A3's rule 3d disposes of the attempt before A1
can start:**

> *"A respecified claim that is verifiable because it no longer asks what the
> caller wanted is abandonment, not respecification."*

Naming `policy_id` and verifying *"this grant complied with policy P"* replaces
*"should this grant have been made"* with *"was it consistent with a rule someone
wrote."* **That is claim substitution** — forbidden by Q3 and by rule 3d — and it
is the same move I refused for `external_send` in the egress scoping. **Refusing
it there and permitting it here would be applying the rule to whichever answer I
preferred.**

**WHAT WOULD BE LOST, stated as A3 requires:** the thing the caller actually
cared about — whether the grant or the transfer *ought* to have happened.
**Classification: NOT RESPECIFIABLE.**

**A4 — re-applying the criterion after the hypothetical naming:** it would
classify **INTERNAL against a policy artifact that does not exist**. A claim
decidable against an empty referent is not decidable; it is vacuous.

---

## 3. PART B — THE GATES

| gate | verdict |
|---|---|
| **B1 CONSUMER** | **FAILS, unchanged.** Nothing in production consumes any claim of any type. `build_registries()` still has **zero production callers**, and `governed_router()` — built last session — has **no runtime caller either** |
| **B2 POWER** | **NOT REACHED.** There is no verifier to demonstrate. For `settle_credits` a semantic divergence *would* have been available — `acceptance_policy` present vs `None` gives two verdicts for one entry — but that demonstrates the **defect**, not a respecified verifier's power |
| **B3 CARRIER** | **NOT REACHED.** No verifier was written. Had one been: a policy check that *evaluates* a stored policy over a claim would **recompute** and be PROOF-carried; one that consults a caller-supplied callable is **VARIABLE-UNDETERMINED** and the authority would refuse it — which is exactly what the determinacy screen already does to `external_send_content` for the identical `policy=None` shape |

> **B4: this is the FIFTH refusal** (RESPEC-3, RESPEC-4, 3.C, the DAG consumer
> gate, now this). **Nothing was built to avoid refusing.**

---

## 4. PART C — THE FRONTIER AND THE EGRESS TALLY

**C1/C2 do not fire.** No respecification succeeded, so no q became measurable
and no f question arises. The egress frontier rows are **unchanged and remain
UNVALIDATABLE**, per the egress scoping.

### C3. THE STANDING LIMIT — stated in its own section, as required

> **No egress action is reversible — 0 of 19 action types have a per-action undo
> — and containment ends at emission.**
>
> **So even a fully respecified, perfectly verified egress claim buys DETERRENCE,
> NOT PREVENTION.** A false claim detected after the fact can be **attributed and
> settled, never remedied.**
>
> **This must be stated wherever the frontier is described.** A tiering table
> implies a bounded error rate you can *hold the system to*; what is actually on
> offer is a bounded rate of *undetected* error among rational actors, plus
> non-repudiation. Those are different products, and only the second is
> unconditional.

### C4. THE EGRESS PICTURE NOW

| status | n | types |
|---|---|---|
| **EXOGENOUS — human-gated, settled** | **3** | `external_send`, `publish_agent`, `publish_attestation` |
| **INTERNAL — mechanically decidable, checker unbuilt** | **2** | `publish_delta`, `send_message` |
| **NO CLAIM** | **1** | `write_outside_sandbox` (no implementation) |
| **respecified this session** | **0** | — |
| **still open** | **0** | — |

**Diagnosing the exact 0 respecified:** **DEFINITIONAL, not a failure.** The
input set was empty — there were no UNDERDETERMINED egress claims to work on.
**Counter-metric: the tally is complete at 6/6**, so "0 respecified" sits beside
"0 still open" rather than beside unfinished work.

**The one genuinely cheap thing this scoping surfaced, and it is not
respecification:** `publish_delta` and `send_message` are **INTERNAL** — their
correctness is a recompute-and-compare over stored state, giving q = 1 and f = 0
**by construction**. **Writing those two checkers is an engineering task with no
measurement, no credits, and no research question.** It is not proposed here
because B1 fails for them too — nothing would consume them — but it is the
cheapest real work remaining on egress, and it is recorded so it is not lost.

---

## 5. Honest limits

1. **This session measured nothing and built nothing.** Its output is a refusal
   and the reason for it.
2. **§1's distinction is authored judgement.** "Referencing an existing referent"
   vs "creating one" is a reading of Q3's *"without acquiring any new fact from
   outside the system"*. I think it is the right reading and it is the one that
   keeps rule 3d intact — but a different reading would license respecification
   here, and would license it for `external_send` too.
3. **The `settle_credits` case is weaker than the `grant_delegation` case.** A
   hook exists (`AcceptancePolicy`), so someone has already decided *where* a
   policy would attach. If a policy were authored and stored, that type would
   become genuinely respecifiable — **and that ordering is the point: author
   first, respecify second.**
4. **Two of three layers being already checked was not obvious in advance** and
   is the reason the scope collapsed. Had correctness been the only unchecked
   layer for a type that *also* lacked conservation and integrity, the trade
   would have looked different.
