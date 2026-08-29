# Gyza credit ledger — blind-channel audit (Route 12 Part C)

Code-only, zero credits, **no security logic changed**. Every claim cites
`file:line` and was checked by reading the source.

Applying R12's criterion to real code: `FINDINGS_GYZA_INVARIANT_AUDIT.md`
established that Gyza's one economic consequence bound is "structurally a
G2-class monotone budget", and R9 showed that class losing 100% of holdings when
its counter failed to track a channel. This audit asks whether that happens here.

**Headline: no blind channel exists in the bilateral credit ledger today, and the
reason is structural rather than lucky. Two findings are latent — one conditional
on planned work, one is an absence.** Note throughout that the criterion is
**one-sided**: nothing below certifies the ledger as adequate.

---

## C1 — every path that moves credits or changes who controls them

| # | path | `file:line` | what it writes |
|---|---|---|---|
| 1 | `ComputeLedger.create_entry` | `gyza/economy/ledger.py:241` | builds an **unsigned** entry; rejects negative amounts (`:257`) and self-pay (`:259`) |
| 2 | `ComputeLedger.sign_as_earner` | `gyza/economy/ledger.py:277` | `to_signature`; entry still unsettled |
| 3 | `ComputeLedger.sign_as_payer` | `gyza/economy/ledger.py:298` | `from_signature`, `settled=True`, row + balance cache (`:321-324`) |
| 4 | `ComputeLedger.apply_cosigned_entry` | `gyza/economy/ledger.py:326` | `settled=True`, row + balance cache (`:339-341`) |
| 5 | `ComputeLedger._save_entry` (UPSERT) | `gyza/economy/ledger.py:369`, SQL at `:375` | the `ledger_entries` row |
| 6 | `ComputeLedger._update_balance_cache` | `gyza/economy/ledger.py:463`, SQL at `:478` | the `balance_cache` row |
| 7 | `Budget.try_allocate` / `Budget.refund` | `gyza/economy/subcontract.py:95` / `:106` | task-budget allocation (not credits) |
| 8 | `ReservationBook.reserve` / `release` | `gyza/economy/subcontract.py:209` / `:161` (state enum `:136`) | holds; explicitly **not** payment state (`:39`) |
| 9 | `SubcontractCoordinator.subcontract` → `cosign_as_payer` | `gyza/economy/coordinator.py:257` (gate) then the settlement payer path | the only payment authority |
| 10 | **`BondedMarket` capital pool** | `gyza/economy/market.py:287` (stake debit), `:325`, `:332`, `:345` (settle / cancel credits) | `self._capital` — **a second credit-like quantity** |

**Ownership-changing paths: none.** There is no compositor-key rotation, no
account-ownership transfer, and no path that re-keys existing entries.
`ReservationBook._owner` is set once at construction (`subcontract.py:172`) and
never reassigned. This matters: it is precisely the `reassign` / `set_principal`
channel that destroyed G2 and G4′ in R9, and it **does not exist here**.

---

## C2 — what the gate actually reads

`ReservationBook.available()` (`gyza/economy/subcontract.py:184-196`):

```python
wallet_room = self._wallet.net_balance(self._owner) - self._active_holds()
budget_room = self._budget.remaining()
return min(wallet_room, budget_room)
```

Transitively, `READS(gate)` =

- `Wallet.net_balance(pubkey)` (`wallet.py:274`) → `Wallet.statement` → a fold over
  `LedgerEntry` fields `entry_id`, `from_compositor`, `to_compositor`,
  `amount_credits`, `settled` (canonical tuple at `wallet.py:161-166`);
- `_active_holds()` (`subcontract.py:177`) → reservation amounts in `ACTIVE` state;
- `Budget.remaining()` (`subcontract.py:92`).

**The load-bearing structural fact: a Gyza credit balance is not a mutable pot.
It is a pure fold over signed entries** (`wallet.py:171` — "Pure projection over
an iterable of `LedgerEntry`"). There is no balance field for an unmodelled
channel to write. Any path that changes a balance must write a `LedgerEntry`, and
the gate reads exactly the entry fields that determine the balance.

Two further properties that matter to the criterion:

- **Settled-only** (`wallet.py:276-280`): counting earner-signed-but-not-cosigned
  entries "would let an agent spend credits a counterparty never agreed to." This
  is the same discipline R9's G4 needed.
- **Both write paths verify before setting `settled`**: `sign_as_payer` verifies
  the earner signature (`ledger.py:315`); `apply_cosigned_entry` calls
  `verify_entry` on both (`ledger.py:337`). So the `settled` flag the gate reads
  is not a bare stored boolean an unverified path can set.

---

## C3 — applying the criterion

| credit-moving path | writes | read by the gate? | verdict |
|---|---|---|---|
| 3, 4, 5 (entry rows) | `amount_credits`, `from/to_compositor`, `settled`, `entry_id` | **yes** — all five are in the `Wallet` fold | NOT BLIND |
| 6 (balance cache) | `balance_cache.net_credits` | not read — `Wallet` recomputes from entries | not a channel (cache is derived; the gate bypasses it) |
| 7, 8 (budget / holds) | budget allocation, holds | **yes** — both terms of `available()` | NOT BLIND |
| 10 (**market capital**) | `BondedMarket._capital` | **no** | **LATENT BLIND CHANNEL** — see below |

**No blind channel exists in the bilateral ledger.** Stated plainly because a
clean result is a real result. The reason is architectural: the quantity the gate
reads *is* the quantity every write path moves, because balances are derived
rather than stored. In R9's terms this is the G4 pattern (guard reads the same
frame the harm measure reads) rather than the G2 pattern (guard reads its own
action-shape counter).

**One-sidedness, restated:** this says the gate is not *blind*. It does not say
the gate is *adequate*. R12's criterion cannot see a guard that reads a field and
handles it wrongly — `test_criterion_is_one_sided_guard_reads_but_ignores` pins
exactly that limitation.

---

## C4 — findings by severity

### F1 — LATENT (conditional on planned work): the bonded market is a second, ungated credit pool

`BondedMarket._capital` (`gyza/economy/market.py:231`, mutated at `:287`, `:325`,
`:332`, `:345`) is a credit-like quantity that the reserve/budget gate never
reads. Today this is **not** a leak: `_capital` is seeded from a constructor
argument (`market.py:228-231`) and **no code path bridges it to `LedgerEntry`
credits** — verified by grep; there is no market↔ledger call anywhere in
`coordinator.py`, `settlement.py`, or `cli.py`. They are two disjoint quantities,
so today it is two currencies, not a drain.

**The hazard is the stated roadmap.** `market.py:21-23` describes the module as
"the *multilateral* settlement layer (vNext §8 layer 6's L1) that the bilateral L0
does not cover." The moment market capital becomes fungible with ledger credits,
this becomes **exactly R9's G2 failure**: a pool that moves value through a
channel the budget gate's counter does not track. R9's measured version of that
mistake was 100% of holdings with the invariant intact.

**Recommendation (report only, no change made):** if the bridge is built, either
(a) route market P&L through `LedgerEntry` so it lands inside the fold the gate
already reads, or (b) extend `ReservationBook.available()` to read market capital
explicitly. Option (a) is strictly better — it preserves the derived-balance
property that makes the current design blind-channel-free.

### F2 — LATENT (named in the source, deliberately deferred): compositor-key rotation is the frame hazard

`gyza/economy/settlement.py:71-72` lists as out of scope: *"rotation of the
compositor key (a settled entry references the key valid at the moment of
signing)."*

That sentence is the R9 frame lemma, unimplemented. Balances are keyed by
compositor pubkey (`wallet.py:274`, `subcontract.py:194`); entries reference the
key at signing time. Implement rotation naively and you get **precisely G4′**: the
historical entries pinned to the old key while the live gate reads the new one,
so the balance the gate sees and the credits actually owed diverge — the pinned
frame that lost 175000 in R9.

**Recommendation (report only):** when rotation is implemented, the invariant's
frame must follow the harm's frame — a signed key-succession record that makes the
fold resolve old-key entries to the current identity, not a gate that reads only
the new key.

### F3 — OBSERVATION (ambiguous by design, not a defect): revocation does not affect balances

`TrustRegistry.revoke_compositor` (`gyza/network/trust_registry.py:222`) marks a
peer revoked, and neither `Wallet` nor `ReservationBook` consults the registry
(grep: no `trust`/`revoked` reference in `wallet.py` or `subcontract.py`). So
revoking a counterparty does not remove their entries from your net balance.

This is defensible — a signed debt is a signed debt regardless of trust status —
and may well be intended. It is recorded because it is a case where "which entries
count" is a frame decision that is currently implicit. **Not scored as a
vulnerability.**

### F4 — DOCUMENTATION MISMATCH (minor)

`ledger.py:30-32` states corrections are made "by issuing a counter-entry
(negative amount, parent referencing the original) — Phase 4 territory", but
`create_entry` rejects any negative amount (`ledger.py:257-258`). The doctrine and
the code disagree; the code is the safe side. Worth reconciling when Phase 4
lands, since a negative-amount path would be a new credit-moving channel and would
need re-auditing against C2.

---

## C5 — is Gyza's harm model written down anywhere? **No.**

This is the most important finding for the roadmap, and it is an absence.

Searching `gyza/` and `docs/` for a declared harm measure — "harm model", "harm
measure", "maximum loss", "loss bound" — returns **nothing**. There is no file
that says what quantity must be bounded, over what frame, or to what level.

What exists instead is a harm measure **implicit** in the reserve/budget gate:
credits-at-risk, defined operationally as
`min(settled_net(owner) − active_holds, budget_remaining)`. It has never been
written down as a harm model, so:

- **The criterion cannot be applied to harms nobody has declared.** R12 needs
  `READS(h)`, which needs an `h`. For the credit ledger I could reconstruct one
  from the gate — but that is circular in exactly the way R9's GATE 0b forbids:
  deriving the harm measure *from the guard* makes adequacy tautological. The C3
  result above is stated against a harm measure I reconstructed by reading the
  gate, and **that is a weakness of this audit, disclosed here rather than hidden.**
- **Irreversibility is entirely unmodelled.** R9's second harm class — deletions
  with no recoverable copy, unrecallable external sends — has no counterpart
  anywhere in Gyza's economic layer. R9 showed a guard can bound drain absolutely
  and still reach an unrecoverable state in **one** action.
- The provenance/containment layer bounds *authority* (per
  `FINDINGS_GYZA_INVARIANT_AUDIT.md` §iv), the economic layer bounds *credits*,
  and no document connects them or states what the system as a whole promises to
  bound.

**The roadmap item this implies:** write the harm model down first — the quantities,
their frames, and the bound claimed for each. Until that exists, every containment
claim Gyza makes is scoped to a harm model that lives only in the reader's head,
and R12's whole method (and any static audit built on it) has nothing to check
against.
