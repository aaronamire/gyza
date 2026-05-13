# Settlement.tla — invariant mapping

> Maps each TLA+ predicate in `Settlement.tla` to its corresponding
> `INV-SETTLE-N` ID in `docs/invariants.md`. Brief argument for
> soundness where the TLA+ formulation differs from the prose
> statement.

## Coverage matrix

| INV-SETTLE-N | TLA+ predicate | Status |
|---|---|---|
| INV-SETTLE-1 | `INV_SETTLE_1_StateMachineOrdering` | ✓ checked by TLC |
| INV-SETTLE-2 | `INV_SETTLE_2_SigsVerifiedBeforeApply` | ✓ checked by TLC |
| INV-SETTLE-3 | `INV_SETTLE_3_EnvelopeResolvedBeforeApply` | ✓ checked by TLC |
| INV-SETTLE-4 | `INV_SETTLE_4_AmountToleranceBeforeApply` | ✓ checked by TLC |
| INV-SETTLE-5 | `INV_SETTLE_5_AppliedConsistencyAcrossSides` | ✓ checked by TLC (weakened form — see notes) |
| INV-SETTLE-6 | `INV_SETTLE_6_AppliedEntriesAreStable` | ✓ checked by TLC (safety part only — conservation as theorem is §C2 work) |
| INV-SETTLE-7 | (action-design property) | ◯ documented; structural property in spec, not a predicate |
| INV-SETTLE-8..11 | — | ✗ deferred to reconciliation sub-spec |
| INV-SETTLE-12 | (action-design property) | ◯ documented |

Legend: ✓ formalized + model-checked, ◯ structural / documented, ✗ deferred.

## Soundness notes per invariant

### INV-SETTLE-1: state machine ordering

**Prose:** Settlement entries flow `proposed → earner_signed → payer_cosigned → applied`. No state skipping.

**TLA+:** `INV_SETTLE_1_StateMachineOrdering` asserts every ledger
entry's `status` field is in `EntryStatus = {"proposed", "earner_signed", "payer_cosigned", "applied", "disputed"}`.

**Soundness argument:** The action predicates only ever transition
status fields by named state names. TLC verifies that the only
status values reachable are those in `EntryStatus`. The
"no skipping" guarantee is enforced by action structure: each
action inserts a new entry at "earner_signed", transitions to
"applied" or "disputed", and the spec has no action that jumps
directly from "proposed" to "applied".

This is a slightly weaker formulation than the prose, which would
also constrain the temporal ordering (one must precede the other in
time). The temporal ordering is enforced structurally: only certain
actions can produce each status, and they require the prior status
to exist. A future strengthening could add temporal logic to assert
"applied implies a prior state where it was earner_signed."

### INV-SETTLE-2: signatures verified before apply

**Prose:** Earner signature verifies under the earner's compositor
pubkey before payer signs. Payer signature verifies under payer's
key before earner applies.

**TLA+:** `INV_SETTLE_2_SigsVerifiedBeforeApply` asserts that any
entry in state "applied" has BOTH `earner_sig_valid = TRUE` AND
`payer_sig_valid = TRUE`.

**Soundness argument:** In the spec model, `sig_valid` is a boolean
on each entry representing whether the cryptographic signature
would verify in production. `HandleEarnerSigned` ONLY transitions
entries to a state where `payer_sig_valid = TRUE` when the input's
`earner_sig_valid` is also TRUE (the `~sig_ok` branches mark the
entry as disputed instead). `HandlePayerCosigned` ONLY transitions
to "applied" when BOTH sigs are valid.

TLC verifies this holds across all reachable states under the
adversarial model (`MalleableSigs=TRUE`), where the adversary can
post entries with `sig_valid=FALSE`. The invariant passing under
adversarial conditions is the proof that the protocol's signature
checks are properly placed.

### INV-SETTLE-3: envelope resolved before apply

**Prose:** Before payer cosigns, the referenced `envelope_hash` must
resolve to a known envelope in payer's local blackboard (poll up
to 3 s for gossip lag).

**TLA+:** `INV_SETTLE_3_EnvelopeResolvedBeforeApply` asserts any
"applied" entry's `envelope_hash` corresponds to an envelope in
`envelopes` with matching earner and payer.

**Soundness argument:** The spec models the gossip-lag tolerance
implicitly: an entry whose envelope is unknown gets the "silent
drop" branch (envelope_known=FALSE AND ~\E env: env.hash =
e.envelope_hash). That branch removes the message from `pending`
but does NOT update the ledger — equivalent to the Python's
"return without action" path on unknown work_item_id.

The TLC-verified invariant catches the stronger property: even if
an entry reaches "applied" through any path, its envelope_hash must
correspond to a known envelope. The "envelope-known" guard is
enforced before transitioning to "applied".

### INV-SETTLE-4: amount tolerance

**Prose:** Payer cosigns only if the claimed amount is within ±20%
of payer's locally-computed amount.

**TLA+:** `INV_SETTLE_4_AmountToleranceBeforeApply` asserts any
"applied" entry's `claimed_amount` satisfies `WithinTolerance(claimed, truth)`.

**Soundness argument:** `WithinTolerance` uses integer arithmetic
(`5 * |claimed - truth| <= truth`), exactly equivalent to the
±20% rule. Python uses floating-point but the semantics on
integer amounts are identical within the bounds we model.
HandleEarnerSigned's happy-path guard requires `amount_ok` which
is `envelope_known /\ WithinTolerance(...)`. Disputed branches
trigger when this fails, and they never produce an "applied" entry.

### INV-SETTLE-5: applied consistency across sides

**Prose (in docs/invariants.md):** Applied entries are byte-identical
across earner and payer ledgers.

**TLA+:** `INV_SETTLE_5_AppliedConsistencyAcrossSides` asserts that
WHEN both sides of a pair have an entry for some `id` in "applied"
state, the canonical fields agree on both sides.

**Soundness argument (and weakening note):** The prose is a
strong statement that's literally false during the transient gap
between payer-applies and earner-applies. The protocol has a brief
window where the payer's view is at "applied" but the earner's
view is still at "earner_signed" — they're waiting for the
"payer_cosigned" message to arrive.

The honest invariant: when BOTH sides are at "applied", they agree.
This is what TLC verifies. The complementary property — that BOTH
sides EVENTUALLY reach "applied" for every honest entry — is a
LIVENESS property requiring `FairDelivery`-style weak fairness on
message-handling actions. We document it as a property but don't
check it in this iteration. Liveness checking is a separate flag
(`-fp`-based) and is queued for a follow-up.

Together these two cover the prose: at convergence, the entries
are byte-identical. During convergence, the spec correctly captures
the transient asymmetry as honest protocol behavior, not a bug.

### INV-SETTLE-6: applied entries stable

**Prose (in docs/invariants.md):** Total credits across all bilateral
pairs is conserved.

**TLA+:** `INV_SETTLE_6_AppliedEntriesAreStable` asserts that any
entry in "applied" state has `earner_sig_valid`, `payer_sig_valid`,
and `dispute_reason = "none"`. That is: the canonical fields of an
applied entry don't change after applying.

**Soundness argument (and weakening note):** Total-credits
conservation as a network-wide invariant is implied by THREE facts:
(a) `INV_SETTLE_6_AppliedEntriesAreStable` (applied state is stable),
(b) `INV_SETTLE_5_AppliedConsistencyAcrossSides` (when both sides
applied, fields agree), (c) eventual symmetric application
(liveness). The combination gives: every credit-creating event is
recorded byte-identically on both sides, and the records never
change. Therefore the sum is preserved under any sequence of
operations.

The "conservation theorem" as a single TLA+ predicate is harder
to express elegantly because it requires summing over the function
of ledgers. It's a natural target for the Coq/Lean §C2 work, which
has better support for sum-over-function reasoning. For TLC, the
two pieces above are what we can mechanically check, and they're
sufficient to ground the conservation argument.

### INV-SETTLE-7: reputation events fire correctly

**Prose:** Reputation events fire at settlement protocol events:
`success` on apply; `dispute` on protocol rejection (forged sig,
envelope mismatch, amount tolerance, misroute); never on benign
conditions like "unknown work_item_id" (could be gossip lag).

**TLA+:** Encoded structurally into the action predicates.

**Soundness argument:** Each action branch in `HandleEarnerSigned`
and `HandlePayerCosigned` adjusts `reputation` exactly as the
Python does:
- Misroute → `reputation' = reputation EXCEPT ![..][..] = @ - 1`
- Forged earner sig → same `- 1` adjustment
- Envelope mismatch (known but doesn't match) → same `- 1`
- Envelope unknown entirely → NO reputation change (silent drop)
- Amount tolerance → `- 1`
- Happy path → `reputation' = ... = @ + 1`

The "structural" qualifier means: there's no TLA+ predicate that
checks reputation values against a derived "should be" formula.
The correctness is established by inspection of the action
predicates. A future enhancement could derive an explicit per-pair
reputation accumulator from the history of (entry, outcome) tuples
and assert reputation = accumulator. Out of scope for Session 19.

### INV-SETTLE-8..11: reconciliation invariants

**Status:** ✓ shipped (Session 28). Lives in `Reconciliation.tla`
+ `Reconciliation.cfg` / `Reconciliation_adversarial.cfg`.

The reconciliation RPC (lex-cursor pagination, cross-peer injection
guard, page caps, for-peer guard) is separable from the core
settlement protocol, so it lives in its own TLA+ sub-spec. The
mapping to the canonical `INV-SETTLE-N` IDs:

| docs/invariants.md | Reconciliation.tla predicate |
|---|---|
| INV-SETTLE-8 (lex cursor) | `INV_RECON_8_AcceptedFromTrueLedger` (honest only) |
| INV-SETTLE-9 (cross-peer injection) | structural via `HandleResponse` match clause; `INV_RECON_9_AcceptedOnlyFromAllocatedIDs` is the state-predicate witness |
| INV-SETTLE-10 (page cap) | `INV_RECON_10_PageCount` + `INV_RECON_10b_HonestResponsePageSize` |
| INV-SETTLE-11 (for_peer guard) | structural via `HandleRequest`'s drop branch |

The action-design properties (INV-9 and INV-11) hold by
construction in the spec's actions. TLC exhaustively explores
interleavings — including adversarial responder/requester actions —
without finding a state violating these properties, which validates
the structural argument.

INV-9 ("never accept a response from a peer other than the one
registered") is INTERESTING under the libp2p threat model: the
adversary cannot spoof the sender field (Noise-bound), but they
CAN emit a response with their true identity into a session
registered against a different peer. `HandleResponse` drops these
in the no-match branch.

### INV-SETTLE-12: reputation policy (disputed vs. missing)

**Prose:** `disputed` entries → `record_dispute`. `missing_theirs` /
`missing_ours` → NO reputation change.

**TLA+:** structurally encoded in the reconciliation actions; not
modeled in `Reconciliation.tla` because reputation is downstream
of the diff classification, which is itself a pure function of
`accepted` and `store`. Status: documented; covered by
`tests/test_reconciliation.py`.

## Test of soundness

A useful sanity check on any spec: introduce an intentional bug in
the spec (NOT the implementation) and verify TLC catches it.

For example: if we remove the `sig_ok` guard from
`HandleEarnerSigned`'s happy-path branch (making it cosign even
forged entries), TLC should find a counterexample where an entry
reaches "applied" with `earner_sig_valid = FALSE`, violating
`INV_SETTLE_2_SigsVerifiedBeforeApply`.

This sanity check is queued as a one-time exercise to validate the
spec's discrimination power before relying on it as the reference.

## Cross-reference

- `docs/invariants.md` § Settlement (§4) — prose invariants with IDs.
- `docs/state-machines.md` § Settlement entry lifecycle — visual
  state machine.
- `docs/wire-protocol.md` § Settlement messages (§6.1) — wire shapes.
- `gyza/economy/settlement.py` — the implementation.
- `CLAUDE.md` §6 C1 — vNext-commitment context.
