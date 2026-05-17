"""
Wallet projection tests.

These lock the properties the rest of the economy will stand on:
exact (non-float) arithmetic, idempotent dedup (a double-count is a
silent mint), settled-only spendable balance, defensive exclusion
of self-dealing / conflicting entries, order-independence, and the
deliberately-fake non-monetary posture.
"""
from __future__ import annotations

import random

import pytest

from gyza.economy.ledger import LedgerEntry
from gyza.economy.wallet import (
    TOKEN_IS_FAKE,
    TOKEN_TICKER,
    Credits,
    Wallet,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64


def _e(eid, payer, earner, amount, *, settled=True) -> LedgerEntry:
    return LedgerEntry(
        entry_id=eid,
        from_compositor=payer,     # payer
        to_compositor=earner,      # earner
        amount_credits=amount,
        work_item_id=f"w-{eid}",
        icp_envelope_hash=f"h-{eid}",
        model_identifier="m",
        tokens_out=1,
        duration_ms=1,
        created_at_ns=1,
        from_signature="sigP" if settled else "",
        to_signature="sigE",
        settled=settled,
    )


# ----------------------------------------------------------------------
# Fundamentals
# ----------------------------------------------------------------------

def test_empty_wallet_is_zero():
    w = Wallet([])
    assert w.net_balance(A) == Credits.zero()
    st = w.statement(A)
    assert st.net == Credits.zero()
    assert st.settled_entry_count == 0


def test_single_settled_earn_is_positive():
    w = Wallet([_e("1", payer=B, earner=A, amount=2.5)])
    assert w.net_balance(A) == Credits(2_500_000)
    # ...and the symmetric debt for the payer.
    assert w.net_balance(B) == Credits(-2_500_000)


def test_single_settled_spend_is_negative():
    w = Wallet([_e("1", payer=A, earner=B, amount=1.0)])
    assert w.net_balance(A) == Credits(-1_000_000)


def test_net_is_global_across_distinct_counterparties():
    # Earn 3 from B, spend 1 with C. Net = +2. (This is a *read*
    # projection — it does NOT imply the B-credits are spendable
    # with C; that's the gated L1 line. The projection is still a
    # well-defined global net.)
    w = Wallet([
        _e("1", payer=B, earner=A, amount=3.0),
        _e("2", payer=A, earner=C, amount=1.0),
    ])
    assert w.net_balance(A) == Credits(2_000_000)


def test_negative_net_is_allowed_and_not_clamped():
    w = Wallet([
        _e("1", payer=A, earner=B, amount=5.0),
        _e("2", payer=C, earner=A, amount=1.0),
    ])
    assert w.net_balance(A) == Credits(-4_000_000)


# ----------------------------------------------------------------------
# Exactness — the float-safety proof
# ----------------------------------------------------------------------

def test_arithmetic_is_exact_not_float():
    # 0.1 + 0.2 in float is 0.30000000000000004. The wallet folds in
    # integer micro-credits derived from the signed canonical string,
    # so the sum is EXACTLY 0.3 → 300000 micros.
    w = Wallet([
        _e("1", payer=B, earner=A, amount=0.1),
        _e("2", payer=B, earner=A, amount=0.2),
    ])
    assert w.net_balance(A) == Credits(300_000)
    assert w.net_balance(A).micros == 300_000


def test_sub_microcredit_amounts_round_to_signed_canonical():
    # The ledger signs f"{x:.6f}" — 7th decimal is not committed.
    # The wallet's unit must match what was signed exactly.
    w = Wallet([_e("1", payer=B, earner=A, amount=1.23456789)])
    assert w.net_balance(A) == Credits(1_234_568)  # round-half-to-even @6dp


# ----------------------------------------------------------------------
# Silent-mint guards
# ----------------------------------------------------------------------

def test_duplicate_entry_id_counted_once_idempotent():
    # Reconciliation re-delivers the SAME entry with its existing
    # cosignatures. Counting it twice would mint credits from thin
    # air — the single worst failure for a verifiable ledger.
    dup = _e("1", payer=B, earner=A, amount=10.0)
    w = Wallet([dup, dup, _e("1", payer=B, earner=A, amount=10.0)])
    assert w.net_balance(A) == Credits(10_000_000)
    assert w.statement(A).settled_entry_count == 1


def test_conflicting_settled_entry_id_is_excluded_and_flagged():
    # Same id, two DIFFERENT settled amounts → genuine dispute. We
    # must not silently pick one. Drop it from every balance.
    w = Wallet([
        _e("1", payer=B, earner=A, amount=10.0),
        _e("1", payer=B, earner=A, amount=999.0),
    ])
    st = w.statement(A)
    assert st.net == Credits.zero()
    assert st.excluded_conflicting == 1


def test_settled_supersedes_unsettled_for_same_id():
    w = Wallet([
        _e("1", payer=B, earner=A, amount=4.0, settled=False),
        _e("1", payer=B, earner=A, amount=4.0, settled=True),
    ])
    assert w.net_balance(A) == Credits(4_000_000)
    assert w.statement(A).settled_entry_count == 1


def test_self_dealing_excluded_and_flagged():
    # earner == payer is rejected at creation but a forged/relayed
    # entry could carry it; counting one leg = a mint vector.
    w = Wallet([_e("1", payer=A, earner=A, amount=50.0)])
    st = w.statement(A)
    assert st.net == Credits.zero()
    assert st.excluded_self_dealing == 1


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"),
                                 float("-inf")])
def test_malformed_amounts_excluded_and_flagged(bad):
    w = Wallet([_e("1", payer=B, earner=A, amount=bad)])
    st = w.statement(A)
    assert st.net == Credits.zero()
    assert st.excluded_malformed == 1


# ----------------------------------------------------------------------
# Settled-only spendable; pending visible but not spendable
# ----------------------------------------------------------------------

def test_pending_excluded_from_net_but_visible_in_statement():
    w = Wallet([
        _e("1", payer=B, earner=A, amount=7.0, settled=True),
        _e("2", payer=B, earner=A, amount=100.0, settled=False),
        _e("3", payer=A, earner=C, amount=9.0, settled=False),
    ])
    st = w.statement(A)
    assert st.net == Credits(7_000_000)            # only the settled one
    assert st.pending_in == Credits(100_000_000)   # receivable, not spendable
    assert st.pending_out == Credits(9_000_000)    # committed, not final


# ----------------------------------------------------------------------
# Determinism
# ----------------------------------------------------------------------

def test_fold_is_order_independent():
    entries = [
        _e(str(i), payer=B, earner=A, amount=float(i) / 7.0)
        for i in range(1, 40)
    ]
    base = Wallet(entries).net_balance(A)
    for seed in range(5):
        shuffled = entries[:]
        random.Random(seed).shuffle(shuffled)
        assert Wallet(shuffled).net_balance(A) == base


# ----------------------------------------------------------------------
# from_ledger wiring + the fake-token posture
# ----------------------------------------------------------------------

class _StubLedger:
    def __init__(self, entries):
        self._entries = entries

    def all_entries(self):
        return list(self._entries)


def test_from_ledger_reads_all_entries():
    led = _StubLedger([_e("1", payer=B, earner=A, amount=2.0)])
    assert Wallet.from_ledger(led).net_balance(A) == Credits(2_000_000)


def test_from_ledger_empty_is_zero():
    assert Wallet.from_ledger(_StubLedger([])).net_balance(A) == Credits.zero()


def test_token_is_explicitly_fake_and_nonmonetary():
    assert TOKEN_IS_FAKE is True
    assert TOKEN_TICKER == "GYZ"
    s = str(Credits(1_500_000))
    assert "FAKE" in s and "no external value" in s
    assert "1.500000 GYZ" in s


def test_credits_ordering_and_arithmetic():
    assert Credits(1) < Credits(2)
    assert Credits(5) - Credits(8) == Credits(-3)
    assert -Credits(4) == Credits(-4)
    assert Credits.from_amount(2.0) == Credits(2_000_000)
    assert Credits.from_amount(-1.0) is None
    assert Credits.zero().value == 0.0
