# spec/ — Gyza formal protocol specification

> **Status (Session 19):** First C1 sub-spec — `Settlement.tla` covers
> the bilateral settlement protocol. Other sub-specs (Attestation,
> Blackboard, DHT, Gossip) are queued as follow-up sessions under
> the §C1 binding work.

## Why this exists

Under the Session 17 vNext commitment (CLAUDE.md §8), the protocol
gains a formal-methods foundation. §C1 in the migration plan is the
TLA+ behavioral spec of v1; §C2 is the Coq/Lean proofs of
load-bearing invariants.

This directory holds the spec artifacts. Each sub-spec is a TLA+
module with a TLC configuration file for model-checking, an
invariants-mapping document that ties TLA+ predicates back to
`docs/invariants.md` IDs, and a brief on what's covered vs. deferred.

## How to run

You need:

- Java 11+ (`java -version`)
- `tla2tools.jar` from https://github.com/tlaplus/tlaplus/releases/latest

The repo includes a copy at `spec/tools/tla2tools.jar` (~2 MB).
Pulled via `curl -L -o spec/tools/tla2tools.jar https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar`.

To model-check Settlement:

```bash
cd spec
java -XX:+UseParallelGC -cp tools/tla2tools.jar tlc2.TLC \
    -deadlock -workers 4 -config Settlement.cfg Settlement.tla
```

Flags:
- `-deadlock` — disables deadlock-as-error. Our spec reaches terminal
  states (all envelopes processed, no messages pending) by design.
- `-workers 4` — parallel model-checking workers. Tune to CPU count.
- `-XX:+UseParallelGC` — TLC's recommended GC.

A clean run reports `Model checking completed. No error.` plus a
state count. An invariant violation reports the counterexample trace
(invaluable when debugging the spec).

## Files

| File | Purpose |
|---|---|
| `Settlement.tla` | TLA+ behavioral spec of bilateral settlement |
| `Settlement.cfg` | TLC model configuration (bounded constants + invariants list) |
| `Settlement_invariants.md` | Mapping from TLA+ predicates to `docs/invariants.md` IDs |
| `tools/tla2tools.jar` | Official TLA+ tools jar (TLC + SANY + Pluscal translator) |

## Scope of `Settlement.tla` (Session 19)

**Covered (formalized as TLA+ + checked by TLC):**

- Bilateral state machine: `proposed → earner_signed → payer_cosigned → applied`
- Four dispute paths: forged earner sig, envelope mismatch, amount
  outside ±20%, misroute
- Adversarial submit (modeled with `MalleableSigs=TRUE`): forged
  sigs, wrong envelope hashes, wrong amounts, misrouted entries
- Message delivery model: pending bus with explicit drop action
- Reputation updates: success/dispute monotonic adjustments
- Type invariants over all state variables
- Safety: state-machine ordering, sigs-verified-before-apply,
  envelope-resolved-before-apply, amount-tolerance-before-apply,
  applied-symmetry-when-both-applied, applied-entries-stable

**Out of scope for Session 19 (deferred to a follow-up):**

- Reconciliation RPC (INV-SETTLE-8..11): lex-cursor pagination,
  cross-peer injection guards, page caps, for-peer guard. Separable
  sub-spec; complex enough to warrant its own session.
- Liveness: every honestly-submitted entry eventually reaches
  applied under fair delivery. The spec design supports this proof
  (with `FairDelivery` weak-fairness condition) but we haven't
  enabled liveness checking on TLC yet.
- Cross-component interactions: settlement assumes envelopes exist;
  the spec doesn't formalize how they get there (that's the
  blackboard / runner spec's job).
- Conservation as an explicit theorem. Followed structurally from
  INV-SETTLE-5 (when both sides applied, fields agree) +
  INV-SETTLE-6 (applied state is stable) + eventual symmetry
  (liveness). When we add Coq/Lean proofs in §C2, the conservation
  theorem is a top deliverable.

## Constants for the TLC model

The Settlement.cfg uses small constants so model-checking completes
in seconds:

- `Peers = {p1, p2, p3}` — three peers; covers earner/payer/third-party
- `EnvelopeIDs = {h1, h2}` — two distinct envelope hashes
- `EntryIDs = {e1, e2}` — two distinct entry IDs
- `MaxAmount = 4` — amounts in 1..4, gives meaningful tolerance arithmetic
- `MalleableSigs = TRUE` — adversary CAN forge sigs; spec must hold

State space at these bounds: ~10^5 states (rough estimate after
initial validation). Scale up for deeper exploration once the spec
stabilizes.

## How the spec maps to the implementation

Each major action in `Settlement.tla` corresponds to a function in
`gyza/economy/settlement.py`:

| TLA+ action | Python equivalent |
|---|---|
| `PostEnvelope` | `gyza/runner.py::_complete` (envelope appears in blackboard) |
| `SubmitEarned` | `LedgerSettlementService::submit_earned` |
| `AdversarialSubmit` | (no honest equivalent — models attacks) |
| `HandleEarnerSigned` | `_handle_earner_signed` (the 4-branch validation) |
| `HandlePayerCosigned` | `_handle_payer_cosigned` |
| `DropMessage` | network partition / gossipsub drop |

Each branch of `HandleEarnerSigned` in the TLA+ corresponds to a
specific code path in `_handle_earner_signed`. The branch labels
match the dispute_reason strings the Python sets.

## Maintenance

When the implementation changes a settlement state transition or
invariant, the spec must be updated to match. Workflow:

1. Modify the Python (or the spec) first.
2. Re-run TLC against the spec.
3. If TLC reports a violation, the implementation and spec are
   out of sync — either fix the implementation or update the spec.
4. Commit both together with a session narrative entry in CLAUDE.md
   §5 explaining what changed and why.

The spec is the ground truth for the protocol's intended behavior;
the implementation is the realization. Drift between the two is the
bug class formal methods exist to prevent.

## Next sub-specs

- `Attestation.tla` — Tier-3 challenge-response protocol +
  attestation cert verification (INV-ATT-*). Includes the
  applicant-proposed-body invariant from Session 14.
- `Blackboard.tla` — ICP envelope chain verification, work-item
  state machine, claim/complete races.
- `Gossip.tla` — gossipsub delta propagation, eventual consistency
  under partition.
- `DHT.tla` — Kademlia put/get + gyzaValidator dispatch, including
  Session 16's TTL bounding and recursive verifier.

Each sub-spec follows the same pattern: TLA+ behavior + TLC config
+ invariants-mapping doc.
