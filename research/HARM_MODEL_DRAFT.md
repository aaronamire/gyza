# Gyza harm model — DRAFT SPECIFICATION PROPOSAL

**Status: PROPOSAL, not a commitment, and not a research result.** Every BOUND
LEVEL below is left as `TBD — user decision`. This document exists because
Route 12 §C5 found that Gyza has **no written harm model at all**: a search of
`gyza/` and `docs/` for a declared harm measure returns nothing, and R12's audit
had to reconstruct one *from the guard*, which is circular in exactly the way R9's
GATE 0b forbids. Until the quantities are declared independently of the guards,
**no containment claim Gyza makes can be checked**, by a human or a tool.

What follows declares, per harm class: the **quantity** as a function of state,
its **frame** and whether that frame is mutable, the **code path** with
`file:line`, the **claimed bound** (TBD), and whether **any guard currently reads
the same fields the quantity reads**.

The two structural conditions come from R9 and are load-bearing throughout:

- **R9 condition 2 (frame).** An invariant is adequate only if evaluated over the
  same frame as the harm. G4′ pinned its frame at `s_0` and lost 175000; G4 read
  the current frame and bounded at 50.
- **R9 condition 3 (per harm class).** Adequacy does not carry across harm classes.
  G4 bounds drain absolutely and still reaches an unrecoverable state in **one**
  action.

---

## Summary table (GATE A deliverable)

| | quantity | frame | frame mutable? | bound | guard reads the same fields? |
|---|---|---|---|---|---|
| **H1** | credits at risk | compositor pubkey | **yes, once rotation lands** | TBD | **yes** — `ReservationBook.available()` |
| **H2** | market capital | agent pubkey in `_capital` | no (dict key) | TBD | **no** — no gate reads it |
| **H3** | irreversible state change | the node + its counterparties | n/a | TBD | **no** — unmodelled entirely |
| **H4** | authority exceedance | delegation chain root manifest | no (chain is append-only) | TBD | **yes** — `verify_delegation` |

Two of four harm classes have no guard reading their fields. One of those (H3) has
no representation in the codebase at all.

---

## H1 — CREDITS AT RISK

**(i) Quantity.** Settled net balance minus active holds, for the node's own
compositor identity:

```
H1(s) = settled_in(pubkey) − settled_out(pubkey) − Σ active_holds
```

`settled_*` counts only entries with **both** signatures present and verified
(`wallet.py:274-280`). Earner-signed-but-not-cosigned entries are excluded on
purpose: counting them would let an agent spend credits a counterparty never
agreed to.

**(ii) Frame.** The **compositor pubkey**. `Wallet.net_balance(pubkey)`
(`wallet.py:274`) filters by it; `ReservationBook._owner` (`subcontract.py:172`) is
set once at construction and never reassigned.

**Frame mutability: currently NO, prospectively YES.** There is no compositor-key
rotation path in the codebase today, which is why R12 found no blind channel here.
But `settlement.py:71-72` defers it explicitly:

> *"rotation of the compositor key (a settled entry references the key valid at the
> moment of signing)"*

**That sentence is R9's frame lemma, unimplemented.** Implemented naively it
reproduces **G4′ exactly**: history pinned to the old key, the live gate reading
the new one, and the balance the gate sees diverging from the credits actually
owed. When rotation lands, the fix is a signed key-succession record that makes the
fold resolve old-key entries to the current identity — the invariant's frame must
follow the harm's frame, not the other way round.

**(iii) Code paths.**

| role | `file:line` |
|---|---|
| quantity computed | `gyza/economy/wallet.py:274` (`net_balance`), fold at `wallet.py:171` |
| gate that reads it | `gyza/economy/subcontract.py:184-196` (`available()`) |
| paths that move it | `ledger.py:298` (`sign_as_payer`), `ledger.py:326` (`apply_cosigned_entry`), persisted at `ledger.py:369/463` |
| frame hazard | `settlement.py:71-72` |

**(iv) Claimed bound.** `TBD — user decision.` The natural shape is a per-job
ceiling (already structurally present as `Budget`, `subcontract.py:69`) plus a
per-counterparty exposure ceiling (absent). Note the quantity **may be negative**
by design (`wallet.py:276-280`, net debt is never clamped), so a bound must be
stated as a floor on net position, not a cap on magnitude.

**(v) Guard alignment: YES.** `available()` reads exactly the fields the quantity
reads — entry amounts, `from`/`to` compositor, `settled`, plus holds and budget.
This is the one harm class where guard and harm are already frame-aligned, and §
"The architectural principle" explains why that is not luck.

---

## H2 — MARKET CAPITAL

**(i) Quantity.** `BondedMarket._capital[agent_pubkey]` — capital available to bond
on assertions, plus escrowed stake held against open tasks.

**(ii) Frame.** The agent pubkey used as the dict key (`market.py:231`). Not
mutable in the current code (no re-keying path).

**(iii) Code paths.**

| role | `file:line` |
|---|---|
| quantity | `gyza/economy/market.py:231` (`self._capital`), `:241` (`capital()`), `:243` (`total_capital()`) |
| mutated | `market.py:287` (stake debit), `:325` (refund on no-correct-answer), `:332` (settle P&L), `:345` (cancel refund) |
| roadmap bridge | `market.py:21-23` |

**(iv) Claimed bound.** `TBD — user decision.` Settlement is conservative by
construction — total capital is invariant across a resolve (`market.py:35-37`) —
so the natural bound is per-agent stake exposure, not system-wide.

**(v) Guard alignment: NO. No gate reads `_capital` at all.**

This is R12 finding F1. Today it is **not** a leak: `_capital` is seeded from a
constructor argument and **no code path bridges it to `LedgerEntry` credits** —
verified by grep across `coordinator.py`, `settlement.py`, and `cli.py`. They are
two disjoint quantities, so today this is two currencies rather than a drain.

**The hazard is the stated roadmap.** `market.py:21-23` describes the module as
"the *multilateral* settlement layer (vNext §8 layer 6's L1) that the bilateral L0
does not cover." The moment market capital becomes fungible with ledger credits,
**this is exactly R9's G2 failure**: a pool that moves value through a channel the
budget gate's counter does not track. R9's measured version of that mistake was
100% of holdings lost with the invariant intact and never violated.

**Recommendation (report only, nothing changed):** if the bridge is built, route
market P&L **through `LedgerEntry`** so it lands inside the fold the gate already
reads. That is strictly better than extending the gate to read a second pool,
because it preserves the property in the next section.

---

## H3 — IRREVERSIBLE STATE CHANGE

**(i) Quantity.** Proposed as R10's `H_lost`: the fraction of assets reachable at
`s_0` that are no longer reachable — measured as **how much state became
unreachable**, never as a count of irreversible actions. R9 §3.2 is the reason: an
action count is an additive bound over action shapes, and one deletion of the right
object is catastrophic while one deletion of a duplicated object costs nothing.

**(ii) Frame.** The node and its counterparties. Three sub-classes, enumerated in
Gyza's own terms:

| sub-class | irreversible because | `file:line` |
|---|---|---|
| **signed envelopes emitted** | once signed and stored, the signature is non-repudiable; publishing to peers puts it beyond recall | `icp.py:67` (`sign_envelope`), `runner.py:589` (`store_envelope`) |
| **external network sends** | leaves the modeled system entirely | `netd_client.py:316` (`publish_agent`), `:461` (`send_message`), `:928` (`publish_delta`), `:1122` (`publish_attestation`) |
| **deleted local state** | content-addressed store has no undo; artifacts and blackboard rows can be removed | `network/artifact_store.py:47` (`store`, append-only in practice — no delete path found), blackboard rows |

**(iii) Code path that computes it: NONE.** No function anywhere in `gyza/`
computes an irreversibility measure. This is R12 §C5's central absence.

**(iv) Claimed bound.** `TBD — user decision.`

**(v) Guard alignment: NO — and there is nothing to align to.** No invariant in
Gyza covers any of the three sub-classes. R9's measured consequence of exactly this
gap: **a guard that bounds drain absolutely still reaches an unrecoverable state in
one action.**

**One honest caveat that limits what any invariant could do here.** Of the three
sub-classes, **external network sends leave modeled state entirely**. A guard can
refuse to *emit*, but once a message is on the wire nothing in the state model
represents it, so no invariant and no detector can bound its consequence. That is
not a gap to be closed — it is the boundary of what containment can mean, and it
should be stated as such wherever Gyza claims containment.

---

## H4 — AUTHORITY EXCEEDANCE

**(i) Quantity.** Whether any executed action's enforcement record exceeds the
delegation chain's root manifest — a boolean per chain, over the four
`CapabilitySpec` dimensions (read paths, write paths, network, memory cap;
`delegation.py:70`).

**(ii) Frame.** The delegation chain rooted at the parent manifest. **Not mutable**:
the chain is append-only and `verify_delegation` re-decides it at result-acceptance
time, not only at grant time.

**(iii) Code paths.** `delegation.py:157-194` (`capability_subset`),
`delegation.py:213-289` (`verify_delegation`), gated at `coordinator.py:175`
(proactive, grant time) and `coordinator.py:257` (before payment).

**(iv) Claimed bound.** Already proved rather than TBD — the attenuation theorem
(`FINDINGS_GYZA_INVARIANT_AUDIT.md` §iii): authority is **monotone non-increasing**
down the chain, so `manifest(h_i) ⊆ manifest(h_0)` for all `i`. The load-bearing
clause is `capability_subset`'s memory rule ("if `outer` declares a cap, `inner`
MUST declare one, ≤ it") — that asymmetry is what makes the relation transitive and
must not be simplified away.

**(v) Guard alignment: YES**, with **two known gaps**, both recorded rather than
fixed:

1. **Fail-open enforcement gate.** `runner.py:402-416` runs the bounds check only
   `if enforcement is not None`; an executor that stamps no record skips it
   entirely. Disclosed at verification time (`cli.py` emits a distinct
   `• no bounds-proof` verdict), so it is non-repudiation of a claim rather than
   refusal to proceed without one — but it is not fail-closed.
2. **Empty-record hole.** A content-free enforcement record passes
   `enforcement ⊆ manifest` when the manifest declares **no memory cap**, because
   empty path sets are a subset of anything and `network=False` is never a
   violation. Caught only when a memory cap is declared, since that is the sole
   must-declare dimension.

---

## THE ARCHITECTURAL PRINCIPLE

R12 Part C found the constructive reason Gyza's credit ledger has no blind channel,
and it generalizes into a design rule:

> **Compute the harm quantity as a pure fold over APPEND-ONLY state, and have the
> guard invoke the SAME function.**
>
> Then blind channels are **architecturally impossible** rather than merely absent,
> and **frame alignment is automatic**.

Why it works, in R9/R12 terms:

- **No mutable aggregate to write behind the guard's back.** If the balance is
  derived rather than stored (`wallet.py:171`, "Pure projection over an iterable of
  `LedgerEntry`"), then *every* path that changes it must append an entry, and the
  gate that folds those entries necessarily sees it. R12's criterion could find no
  blind channel here — not because the analyzer was clever, but because the shape of
  the code leaves nowhere for one to hide.
- **Frame alignment for free.** R9's condition 2 fails when the guard evaluates its
  predicate over a different set than the harm does. If both call the same fold, the
  frame is the same object; there is no second frame to drift. R12 observed the same
  thing in the simulation: guards that called the environment's own accounting
  helpers (`principal_total`, `recoverable`) inherited the harm's frame
  transitively, and were the ones that held.
- **Append-only is what makes the fold sound.** If history can be rewritten, the
  fold is no longer a function of what happened.

**Where this already holds in Gyza:** the bilateral credit ledger (H1). Entries are
append-only (`ledger.py:30-32` — "There is no `update_entry`"), balances are folded
(`wallet.py:171`), and the gate reads the fold (`subcontract.py:184-196`).

**Where it does not, and cannot:**

- **H2, market capital** — `_capital` is a **mutable dict**, mutated in place at
  four sites. It is the anti-pattern in the same codebase as the pattern. If the
  roadmap bridge is built, converting market P&L into ledger entries (rather than
  extending the gate) is what would bring H2 under the principle.
- **H3, external sends** — these **leave modeled state entirely**. There is no fold
  over them because there is no state to fold. Stated plainly: **no detector would
  help here either.** The only lever is refusing to emit, and after emission
  containment has no meaning. This is the boundary condition of the whole
  containment story, and it belongs in any claim Gyza makes.

---

## What this document deliberately does not do

It does not set a single bound level. Every `TBD — user decision` is a real
decision with a cost: a tighter bound on H1 constrains legitimate subcontracting;
any bound on H3 costs exactly the irreversible operations, which R9 measured at
37.5% of a representative task suite (and which R10 is measuring as a graded
frontier). Choosing those levels is a product decision informed by, but not
determined by, the measurements.
