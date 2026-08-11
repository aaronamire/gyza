# The three decisions — one shipped, three refused at their gates

**Branch `decisions`.** **ZERO CREDITS.**

> ## PROVENANCE OF EVERY VALUE BELOW
> These are **USER DECISIONS**: **recommended by the assistant and accepted by
> the repository owner on 2026-08-11**. **Nothing here was derived, measured,
> tuned, or computed.** No experiment supports 3 over 4, or 1 over 2. Where a
> value is recorded in code, that sentence is recorded beside it.

---

## 1. A4 — THE FRAME VERDICT, FIRST, BECAUSE IT IS A STOP

> ### **"Per promotion window" is the exact defect SR-5 found and this codebase already fixed. A cumulative bound anchored there is unenforceable.**

`StagingArea.origin_state()` (`gyza/containment/staging.py:103-119`) says it in
its own docstring:

> *"The rollback checkpoint moves forward with every promotion; the frame a
> CUMULATIVE bound is measured over must not. **Measuring cumulative harm from
> the last promotion lets an agent defeat the bound entirely by promoting after
> every action** — each batch measures a fresh, tiny drain and the run-level
> total is never anyone's frame."*

`PromotionGate._promote_locked` (`:195-200`) therefore measures from
`st.origin_state()` — **the accounting-period origin, which does not move** —
and explicitly **not** from `baseline_state()`. `FINDINGS_SR5.md:60-79` records
this as a real defect found by its preregistered feasibility check, and it is
pinned by `test_frequent_promotion_cannot_reset_a_cumulative_budget`.

**And the window is caller-controlled:** `PromotionGate.promote()` is a public
method. Whoever runs the agent decides when a window ends.

> **So a per-promotion-window bound is not a tight frame — it is a frame the
> bounded party sets.** Registering "10% per promotion window" would re-arm
> **artifact #13** in the very session that names the moving-frame species as
> having recurred four times.

**VERDICT: the bounds' frame must be the RUN (origin-anchored), not the
promotion window.** The window is the right place to *evaluate* — cumulative
invariants may only be checked at the serialization point — but the wrong place
to *anchor*. **Evaluation point and accounting origin are different things, and
conflating them is the defect.**

---

## 2. A0 — THE BOUNDS ARE NOT UNSET

`gyza/containment/guard_bounds.json` header: **"USER DECISION, 2026-07-31."**

| class | currently set | quantity | frame | reader |
|---|---|---|---|---|
| **H1_credits** | **100.0** | `_credits_at_risk` — settled net balance − holds, **in absolute credits** | compositor pubkey, floats with `s` | engine, via `bounded_by` |
| **H2_market_capital** | **100.0** | market capital fold | agent pubkey in `_capital` | **NONE — no gate reads it** |
| **H3_irreversible_change** | **ABSENT** | **none exists** | — | — |
| **H4_authority** | **0.0** | authority exceedance count | delegation chain root | `verify_delegation` |

**Verified by execution**, not by reading: `build_registries()` reports
registered classes `['H1_credits', 'H2_market_capital', 'H4_authority']`,
bounds `{100.0, 100.0, 0.0}`, and `unbounded() == []`.

**A0's instruction was to report rather than overwrite. Nothing was
overwritten.**

---

## 3. A1 — EACH OF THE FOUR VALUES, AND WHY THREE CANNOT BE SET AS STATED

### H1 — "10% of settled balance": **NOT EXPRESSIBLE AS A BOUND LEVEL**

`_credits_at_risk` returns **absolute credits**
(`(before.micros - after.micros)/1e6 + holds`), and `HarmClass.bound` is a
**scalar** compared against it by `inv.predicate(h, bound, s0, s_next)`
(`engine.py:114`).

> **Writing `bound = 0.10` would mean 0.1 CREDITS — a thousand times TIGHTER
> than the current 100.0, not "10%".** A reader who set it expecting a
> percentage would silently install a near-total freeze.

**But the constructive form exists, and it is worth stating precisely:** the
predicate signature is `(h, bound, s0, s)` — **it receives the state**. So a
relative bound is expressible as **an INVARIANT PREDICATE that computes 10% of
`s0`'s settled balance**, never as a bound level. **That is a small, real piece
of work, and it is not what "register a bound" means.** Not built here.

### H2 — same shape, and registering it fixes nothing

Identical expressibility problem. **And it governs nothing regardless**, which
`guard_bounds.json` already records: *"`_capital` is a mutable dict no gate
reads."* **A1 is right that registering the bound must not be treated as fixing
the H2 gap — and the tree already says so.** The fix remains routing market P&L
through `LedgerEntry`.

### H3 = 1 per window — **CANNOT BE REGISTERED AT ALL**

```
load_bounds({'H3_irreversible_change': 1.0})
-> KeyError: "bound declared for unknown harm class 'H3_irreversible_change'"
```

**Verified by execution.** H3 is deliberately in `UNMODELLED`
(`gyza_model.py:29-35`) because *"no function in gyza/ computes an
irreversibility measure. Registering it with an invented quantity would be
exactly the circularity the discipline forbids."*

> **A bound needs a quantity to bound. H3 has none.** Setting it would require
> first writing an irreversibility measure — and the reversibility measurement
> found **0 of 19** action types have a per-action undo, so the measure would be
> a *count of irreversible actions*, which is buildable but is new work.

**A2's reasoning is recorded anyway, because it is sound and survives:**

> *"1 per window, because irreversibility does not aggregate. This is not a
> budget to be raised; a system needing more than one irreversible change per
> window should widen the window or gate the changes individually."*

**And it is independently supported**, with one correction: the task says *"zero
of thirteen actions reversible"*; the committed measurement is **0 of 19 action
types with a per-action undo** (`research/reversibility/`, corrected in
`reversibility-correction`). **The zero is right; the denominator is not.**
**Fifteenth premise of this shape.**

### H4 = 0 — **ALREADY SET, AND ALREADY A CATEGORY STATEMENT**

`guard_bounds.json` already records exactly A3's reasoning:

> *"H4_authority: 0. Authority exceedance is a **BREACH, not a budget** — the
> attenuation theorem says it cannot happen, so any count above zero is a broken
> invariant rather than consumed allowance."*

**Diagnosing the exact 0, as required: DEFINITIONAL, not a tight bound.** It is
not a level chosen on a dial — it is the statement that the dial does not exist,
because the quantity it would measure is proven unreachable. **A3 asked me to
record it as confirming the existing category. It already is the existing
category, and nothing was changed.**

---

## 4. A5 — WHAT ACTUALLY ENFORCES WHAT

| bound | guard reads it? | evaluated at the right phase? |
|---|---|---|
| **H1** | ✅ `GuardEngine.evaluate` → `self._harm.bound("H1_credits")` (`engine.py:98`) | ✅ cumulative invariants are **deferred in INTERIOR** and evaluated only at PROMOTION (`engine.py:108-111`) |
| **H2** | ❌ **NO GATE READS THE QUANTITY.** The bound is loaded; `_capital` is a mutable dict nothing folds | n/a — **registered but unread: the write-into-a-void pattern, and it is pre-existing** |
| **H3** | ❌ not registered | n/a |
| **H4** | ✅ `verify_delegation` | ✅ structural, per-hop |

**Counter-metric beside that:** `unbounded()` returns `[]`, so
`can_claim_containment` is True — **but one of the three bounded classes has no
reader.** *"All bounds declared"* and *"all harms guarded"* are different claims,
and only the first is true.

---

## 5. B3 — DEPTH VS SUBSET: **a depth cap ALREADY EXISTED**

B3 asks whether anything caps **depth** as distinct from subset-at-each-step.

> **Yes. `delegation.py:245` — `if len(chain) > max_depth`.** It is a genuine
> structural depth cap, separate from the three subset checks, and it was
> already there at **`MAX_DELEGATION_DEPTH = 8`**.

So the policy's new content is **not** the existence of a depth cap — it is
**the value**. The task's framing ("a chain of 40 valid attenuations satisfies
subset and violates auditability") is the right argument and the codebase
already made it.

### ✅ SHIPPED: `MAX_DELEGATION_DEPTH` 8 → 3

The only change to production behaviour in this session. Recorded in the source
with its provenance:

> *"3 IS A CHOSEN VALUE, NOT A DERIVED ONE. Recommended by the assistant and
> accepted by the repository owner on 2026-08-11; nothing measured it and no
> experiment supports 3 over 4 or over the previous 8. … WHAT THIS IS NOT: it is
> not the attenuation property. Attenuation is PROVEN and is checked
> independently — a chain of 40 hops can satisfy attenuation perfectly and still
> be unauditable, which is precisely why a depth cap exists as a separate
> structural backstop."*

**It is a TIGHTENING**, which the prior comment explicitly permits: *"raise
deliberately, never silently."* Dependent citations were synced
(`migration.py` success condition, `depth_at_most_3`, `test_carrier_rule.py`) so
this does not become the stale-citation species.

### B4 — determinacy after the policy: **still UNDERDETERMINED, and I must say what is unnamed**

`capability_grant` **does not exist as a claim type** (0 hits; verified again).
The analogue is `grant_delegation`. With strict attenuation (proven) **and**
depth ≤ 3 (now set), its correctness component is **still not INTERNAL**:

> **Attenuation and depth constrain HOW MUCH authority moves and HOW FAR. They
> say nothing about WHO may receive it.** A grant can attenuate perfectly, sit at
> depth 1, and still be a grant that should never have been made — to the wrong
> principal.
>
> **STILL UNNAMED: the recipient predicate.** Which principals may receive a
> delegation. Until that is authored, the correctness claim is underdetermined
> on the recipient dimension.

---

## 6. C3 — "KNOWN PRINCIPAL" IS MECHANICALLY DEFINABLE, AND IS NOT CHECKED

**The definition exists:** `TrustRegistry.is_trusted(compositor_pubkey) -> bool`
(`gyza/network/trust_registry.py:139-146`) — a SQLite lookup against
`trusted_compositors` that returns `False` for an unknown key **and** for a
revoked one. **That is a function of state the system holds. C3 is satisfiable.**

> **But it is not reachable from the credit-transfer path.**
> `gyza/economy/settlement.py` imports no trust registry — verified by grep.
> The only policy hook is `AcceptancePolicy`
> (`settlement.py:266`), an **optional, caller-supplied** `Callable` consulted at
> `:799` **only `if self._acceptance_policy is not None`**.

**So (iii) is defined and unenforced — the unenforced-invariant species, named
rather than shipped.** Wiring `is_trusted` into settlement is real work and was
not done here.

### C4 — determinacy after the policy: **INTERNAL, conditional on wiring**

All three conditions are functions of stored state — settled balance (the
ledger fold), active holds (`ReservationBook`), recipient trust (the registry).
So with the policy authored, `credit_transfer`'s correctness **does** classify
**INTERNAL**.

**And this is NOT the claim-substitution I refused last session.** The
distinction matters:

| last session (`external_send`) | now |
|---|---|
| **no policy existed**; I was asked to invent one to make the claim decidable → **claim substitution**, forbidden by Q3 | **the owner AUTHORED the policy** as a product decision → the referent now exists and the claim merely names it |

**That is exactly the ordering I recorded then: "author first, respecify
second."** The policy creates the fact; naming it is then legitimate.

**Conservation is not re-conflated with correctness:** (i) and (ii) are
solvency conditions the ledger fold already covers; **(iii) is the entire
correctness content**, and it is the one that is unwired.

---

## 7. D — MONOTONICITY: **ALREADY BUILT, ALREADY OVER THE PROTECTED QUANTITY**

`GuardConfigStore._install` (`guardconfig.py:212-229`) computes loosening over
**the admitted set** via `diff_bounds`, with the reasoning in the source:

> *"PERMISSIVENESS monotonicity — computed over the admitted set, never inferred
> from the version integer. A version bump is a LABEL that correlates with
> intent … a correctly-signed v2 raising every bound would otherwise install
> cleanly."*

**That is the GuardConfigStore defect already fixed.** D1 asked me to verify the
check is over the property rather than a proxy — **it is**, and
`test_permissiveness_is_computed_over_the_admitted_set_not_the_number` shows
that reading magnitudes alone **inverts** the answer, because an unset bound
fails closed so *adding* one is a loosening.

**D2's one genuine gap, now closed:** the code names each moved bound and its
old→new values, but **no test asserted it**. Added
`test_the_loosening_refusal_names_every_bound_that_moved_and_by_how_much`
(asserts `"spend: 100.0 -> 250.0"` and `"irreversible: 1.0 -> 4.0"` appear) plus
a negative control proving the assertion would catch a message that omitted the
magnitudes rather than passing vacuously. **29/29 staging tests pass.**

---

## 8. E — WHAT IS UNBLOCKED

**E1's premise does not match the tree.** *"The two egress respecifications that
are designed and waiting"* are `publish_delta` and `send_message` — the two
**INTERNAL** egress types. **They were never blocked on policy.** They are
unbuilt because the **consumer gate** fails: nothing in production consumes any
claim of any type. These decisions do not touch that.

| item | status after these decisions |
|---|---|
| `MAX_DELEGATION_DEPTH` 8→3 | ✅ **SHIPPED** |
| H1 relative bound | **buildable** — needs an invariant predicate, not a bound level (§3) |
| H2 | **still governs nothing** — needs P&L routed through `LedgerEntry` |
| H3 | **blocked on a quantity**, not on a bound — needs an irreversibility measure written first |
| H4 | **already set and already enforced** |
| `credit_transfer` correctness | **buildable** — the policy is authored and INTERNAL; needs `is_trusted` wired into settlement |
| `grant_delegation` correctness | **still UNDERDETERMINED** — recipient predicate unnamed (§5) |
| `publish_delta`, `send_message` checkers | **unchanged** — blocked on the consumer gate |

### E3 — the containment layer, honestly

**3 of 4 harm classes have a declared bound; 2 of 4 have a reader.** H2 is
registered-but-unread and was before this session. H3 is neither. **The honest
statement is: bounds are declared for the classes that have quantities, and
enforcement covers H1 and H4.**

---

## 9. What this session actually changed

- **`gyza/economy/delegation.py`** — `MAX_DELEGATION_DEPTH` 8 → 3, with
  provenance recorded in source. **The only production behaviour change.**
- **`gyza/verification/migration.py`, `tests/test_carrier_rule.py`** — citations
  synced to 3.
- **`tests/test_staging.py`** — D2's missing assertion + negative control.
- **No bound was written.** `guard_bounds.json` is **untouched**.

## 9a. Baseline, run SEQUENTIALLY — and a new flake recorded

| suite | result |
|---|---|
| Python (fast slice) | **993 passed, 1 skipped, 0 failed** (13:00) |
| Rust workspace | **108 passed** |
| Go daemon | **all 10 packages ok** |

**The depth 8 → 3 change breaks nothing anywhere.**

### A SECOND Go load-flake, distinct from the documented one

The first Go run failed
**`internal/grpc :: TestRequestAttestationHappyPath`** — *"failed to dial …
all dials failed"*. **Diagnosed before being dismissed**, in this order:

1. **Could my change reach it?** `grep -rn "MAX_DELEGATION_DEPTH|maxDepth"
   --include='*.go'` → **zero hits. Go has no delegation-depth concept at all**,
   so a Python constant cannot affect it.
2. **Isolation:** passes **3/3**.
3. **Full suite on an idle machine:** **all 10 packages ok.**

> **CLAUDE.md documents `TestSenderSeqDedupRejects` (`internal/gossip`) as the
> load-flaky Go test. This is a DIFFERENT test in a DIFFERENT package, same
> species — a libp2p dial timing out under load.** Recorded here because "the
> documented flake" is now two tests, and a future session hitting the grpc one
> would otherwise have no note to find.

## 10. Honest limits

1. **Three of the four A1 values were not set**, for three different reasons —
   not expressible (H1, H2), not registrable (H3), already set (H4). **None of
   these is a refusal of the decision; each is a statement that the mechanism
   cannot currently carry it.**
2. **The depth change is untested against a real 4-hop chain** — no test in the
   tree builds one. It is pinned only by the constant and its citations.
3. **`credit_transfer` classifying INTERNAL is conditional on wiring that does
   not exist.** A claim decidable in principle and unchecked in code is the
   unenforced-invariant species, and it is named as such here rather than
   counted as done.
