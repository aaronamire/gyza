"""
Phase 3 Session 6 spec tests for the bilateral compute-credit ledger.

All six tests called out in the spec:

    test_bilateral_settlement
    test_payer_must_sign_first
    test_balance_calculation
    test_free_rider_score
    test_reconciliation
    test_cost_calculation

Plus a small set of hardening tests around verify_entry rejection
paths.
"""
from __future__ import annotations

import secrets
import time
from pathlib import Path

import pytest

from gyza.economy.ledger import (
    CREDIT_RATES,
    ComputeLedger,
    LedgerEntry,
    canonical_sign_bytes,
    compute_task_cost,
    verify_earner_signature,
    verify_payer_signature,
)
from gyza.identity import LocalCompositor


def _make_compositor(tmp_path: Path, name: str) -> LocalCompositor:
    """Write a 32-byte master seed at mode 0600 and load a compositor.
    Each test that needs two parties spins up two compositors with
    independent master seeds."""
    key_path = tmp_path / f"{name}.key"
    key_path.write_bytes(secrets.token_bytes(32))
    key_path.chmod(0o600)
    return LocalCompositor(str(key_path))


def _make_ledger(tmp_path: Path, compositor: LocalCompositor, name: str) -> ComputeLedger:
    db_path = tmp_path / f"{name}.db"
    return ComputeLedger(compositor, str(db_path))


# =============================================================================
# Spec tests
# =============================================================================

def test_bilateral_settlement(tmp_path):
    """
    The full happy path. Earner creates an entry, signs first, sends
    to payer. Payer countersigns. Payer echoes the cosigned entry
    back; earner stores its own settled copy via apply_cosigned_entry.
    Both ledgers end up with byte-identical records.
    """
    payer = _make_compositor(tmp_path, "payer")
    earner = _make_compositor(tmp_path, "earner")

    payer_ledger = _make_ledger(tmp_path, payer, "payer")
    earner_ledger = _make_ledger(tmp_path, earner, "earner")

    # Earner builds + signs first.
    entry = earner_ledger.create_entry(
        from_compositor=payer.pubkey_hex,
        to_compositor=earner.pubkey_hex,
        amount=12.5,
        work_item_id="work-001",
        icp_envelope_hash="cafe" * 16,
        model_identifier="mock",
        tokens_out=125,
        duration_ms=1500,
    )
    entry = earner_ledger.sign_as_earner(entry)
    assert entry.to_signature
    assert not entry.settled
    assert not entry.from_signature

    # Payer countersigns.
    entry = payer_ledger.sign_as_payer(entry)
    assert entry.from_signature
    assert entry.settled

    # Echo cosigned entry back to earner. After this, both ledgers
    # hold the same fully-settled record.
    earner_ledger.apply_cosigned_entry(entry)
    earner_settled = earner_ledger.get_entry(entry.entry_id)
    assert earner_settled is not None and earner_settled.settled

    valid, reason = earner_ledger.verify_entry(entry)
    assert valid, reason
    valid, reason = payer_ledger.verify_entry(entry)
    assert valid, reason


def test_payer_must_sign_first(tmp_path):
    """
    Reversed-order signing must fail. Spec name kept for clarity, but
    the actual rule is "earner must sign before payer countersigns" —
    the payer's signature is the binding "I owe this" ack and the
    earner's prior signature is its precondition.
    """
    payer = _make_compositor(tmp_path, "payer")
    earner = _make_compositor(tmp_path, "earner")
    payer_ledger = _make_ledger(tmp_path, payer, "payer")
    earner_ledger = _make_ledger(tmp_path, earner, "earner")

    entry = earner_ledger.create_entry(
        from_compositor=payer.pubkey_hex,
        to_compositor=earner.pubkey_hex,
        amount=1.0,
        work_item_id="work-002",
        icp_envelope_hash="ab" * 32,
        model_identifier="mock",
        tokens_out=10,
        duration_ms=100,
    )
    # Skip earner sign; try payer countersign directly. Must fail.
    with pytest.raises(ValueError, match="earner must sign"):
        payer_ledger.sign_as_payer(entry)


def test_balance_calculation(tmp_path):
    """
    Five settled entries between two parties in mixed directions.
    Net balance should be the algebraic sum: positive = peer owes us.
    """
    me = _make_compositor(tmp_path, "me")
    peer = _make_compositor(tmp_path, "peer")
    ml = _make_ledger(tmp_path, me, "me")
    pl = _make_ledger(tmp_path, peer, "peer")

    def settle(direction: str, amount: float, work_id: str) -> None:
        """direction == 'incoming' means peer owes us."""
        if direction == "incoming":
            from_, to_ = peer.pubkey_hex, me.pubkey_hex
            payer_l, earner_l = pl, ml
        else:
            from_, to_ = me.pubkey_hex, peer.pubkey_hex
            payer_l, earner_l = ml, pl
        # Earner builds, signs first; payer countersigns; payer echoes
        # cosigned entry back so both ledgers hold the settled record.
        entry = earner_l.create_entry(
            from_compositor=from_,
            to_compositor=to_,
            amount=amount,
            work_item_id=work_id,
            icp_envelope_hash="ff" * 32,
            model_identifier="mock",
            tokens_out=int(amount * 100),
            duration_ms=int(amount * 1000),
        )
        entry = earner_l.sign_as_earner(entry)
        entry = payer_l.sign_as_payer(entry)
        earner_l.apply_cosigned_entry(entry)

    settle("incoming", 10.0, "w1")  # +10
    settle("incoming", 7.5,  "w2")  # +7.5
    settle("outgoing", 4.0,  "w3")  # -4
    settle("incoming", 2.5,  "w4")  # +2.5
    settle("outgoing", 6.0,  "w5")  # -6
    # Net = +10 + 7.5 - 4 + 2.5 - 6 = +10.0

    balance = ml.get_balance(peer.pubkey_hex)
    assert abs(balance - 10.0) < 1e-9, f"got {balance}"

    # Earned + spent totals.
    assert abs(ml.get_total_earned() - 20.0) < 1e-9
    assert abs(ml.get_total_spent() - 10.0) < 1e-9


def test_free_rider_score(tmp_path):
    """
    A peer with very high debt ratio scores >0.7. A peer with no
    history scores 0. A peer who's net-positive (we owe them) scores 0
    — only debts owed TO us trigger free-rider deprioritization.
    """
    me = _make_compositor(tmp_path, "me")
    peer = _make_compositor(tmp_path, "peer")
    ml = _make_ledger(tmp_path, me, "me")
    pl = _make_ledger(tmp_path, peer, "peer")

    # No-history peer → 0.
    fresh = _make_compositor(tmp_path, "fresh")
    assert ml.free_rider_score(fresh.pubkey_hex) == 0.0

    # Helper to settle a single entry.
    def settle(from_party, from_l, to_party, to_l, amount, work_id):
        entry = to_l.create_entry(
            from_compositor=from_party.pubkey_hex,
            to_compositor=to_party.pubkey_hex,
            amount=amount,
            work_item_id=work_id,
            icp_envelope_hash="ee" * 32,
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        entry = to_l.sign_as_earner(entry)        # earner signs first
        entry = from_l.sign_as_payer(entry)       # payer countersigns
        to_l.apply_cosigned_entry(entry)          # echo back to earner

    # Build 9 incoming + 1 outgoing — peer owes us 8 / total transacted 10.
    # debt_ratio = 8/10 = 0.8 → score = min(0.8 * 1.5, 1.0) = 1.0.
    for i in range(9):
        settle(peer, pl, me, ml, 1.0, f"in{i}")
    settle(me, ml, peer, pl, 1.0, "out0")

    score = ml.free_rider_score(peer.pubkey_hex)
    assert 0.7 < score <= 1.0, f"got {score}"

    # Peer who's net-positive (we owe THEM) scores 0.
    other = _make_compositor(tmp_path, "other")
    other_l = _make_ledger(tmp_path, other, "other")
    settle(me, ml, other, other_l, 5.0, "owe-them-1")
    settle(me, ml, other, other_l, 5.0, "owe-them-2")
    assert ml.free_rider_score(other.pubkey_hex) == 0.0


def test_reconciliation(tmp_path):
    """
    Two ledgers with one disputed entry, one missing-from-each.
    reconcile_with_peer reports the diff without resolving it.
    """
    me = _make_compositor(tmp_path, "me")
    peer = _make_compositor(tmp_path, "peer")
    ml = _make_ledger(tmp_path, me, "me")

    # Build three entries on our side, fully settled.
    pl = _make_ledger(tmp_path, peer, "peer")

    def settle(work_id: str, amount: float) -> str:
        entry = ml.create_entry(
            from_compositor=peer.pubkey_hex,
            to_compositor=me.pubkey_hex,
            amount=amount,
            work_item_id=work_id,
            icp_envelope_hash="dd" * 32,
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        entry = ml.sign_as_earner(entry)
        entry = pl.sign_as_payer(entry)
        ml.apply_cosigned_entry(entry)
        return entry.entry_id

    eid_a = settle("w-a", 1.0)
    eid_b = settle("w-b", 2.0)
    eid_c = settle("w-c", 3.0)

    # Build their view: agree on A; disagree on B (different amount);
    # they have a D we don't.
    their_entries = []
    for e in ml.export_statement(peer.pubkey_hex):
        if e["entry_id"] == eid_a:
            their_entries.append(e)
        elif e["entry_id"] == eid_b:
            mutated = dict(e)
            mutated["amount_credits"] = 99.0  # disagreement
            their_entries.append(mutated)
        # eid_c omitted from their view
    their_entries.append({
        "entry_id": "their-only-entry",
        "from_compositor": me.pubkey_hex,
        "to_compositor": peer.pubkey_hex,
        "amount_credits": 5.0,
        "work_item_id": "w-d",
        "icp_envelope_hash": "11" * 32,
        "from_signature": "aa" * 64,
        "to_signature": "bb" * 64,
    })

    diff = ml.reconcile_with_peer(peer.pubkey_hex, their_entries)
    assert eid_a in diff["agreed"]
    assert eid_b in diff["disputed"]
    assert eid_c in diff["missing_theirs"]
    assert "their-only-entry" in diff["missing_ours"]


def test_cost_calculation():
    """
    compute_task_cost returns max(token_based, time_based / 2).
    Verify the rate table for a few common backends.
    """
    # mock backend: 100 tokens @ 0.1 each = 10.0 credit; 1000ms @ 0.5 = 0.5.
    # max → 10.0.
    cost = compute_task_cost("mock", tokens_out=100, duration_ms=1000)
    assert abs(cost - 10.0) < 1e-9

    # llama 3b: 8 tokens @ 1/8 = 1.0; 1000ms time = 0.5. max → 1.0.
    cost = compute_task_cost("llama.cpp:qwen2.5-3b-q4_k_m",
                             tokens_out=8, duration_ms=1000)
    assert abs(cost - 1.0) < 1e-9

    # claude opus: 100 tokens @ 120 = 12000; tiny duration. Token-dominated.
    cost = compute_task_cost("anthropic:claude-opus-4-5",
                             tokens_out=100, duration_ms=10)
    assert abs(cost - 12000.0) < 1e-9

    # Unknown model: rate = 1.0. 50 tokens → 50. duration_ms=2000 → 1.0.
    cost = compute_task_cost("unknown-backend", tokens_out=50, duration_ms=2000)
    assert abs(cost - 50.0) < 1e-9

    # Zero everything is 0.
    assert compute_task_cost("mock", 0, 0) == 0.0

    # Negative inputs are clamped to 0.
    assert compute_task_cost("mock", -5, -100) == 0.0


# =============================================================================
# Hardening: signature verification edge cases
# =============================================================================

def test_verify_rejects_tampered_amount(tmp_path):
    """
    A bad actor that flips an entry's amount AFTER bilateral signing
    must fail verify_entry — the signature is bound to the canonical
    bytes, which include the amount.
    """
    payer = _make_compositor(tmp_path, "payer")
    earner = _make_compositor(tmp_path, "earner")
    payer_ledger = _make_ledger(tmp_path, payer, "payer")
    earner_ledger = _make_ledger(tmp_path, earner, "earner")
    entry = earner_ledger.create_entry(
        from_compositor=payer.pubkey_hex, to_compositor=earner.pubkey_hex,
        amount=5.0, work_item_id="w", icp_envelope_hash="0" * 64,
        model_identifier="mock", tokens_out=10, duration_ms=10,
    )
    entry = earner_ledger.sign_as_earner(entry)
    entry = payer_ledger.sign_as_payer(entry)

    # Verify clean.
    valid, _ = earner_ledger.verify_entry(entry)
    assert valid

    # Tamper.
    entry.amount_credits = 1000.0
    valid, reason = earner_ledger.verify_entry(entry)
    assert not valid
    assert "signature mismatch" in reason


def test_verify_role_separation(tmp_path):
    """
    A payer's signature must NOT verify under the earner role and vice
    versa — the role name in canonical bytes provides domain
    separation.
    """
    payer = _make_compositor(tmp_path, "payer")
    earner = _make_compositor(tmp_path, "earner")
    earner_ledger = _make_ledger(tmp_path, earner, "earner")

    entry = earner_ledger.create_entry(
        from_compositor=payer.pubkey_hex, to_compositor=earner.pubkey_hex,
        amount=1.0, work_item_id="w", icp_envelope_hash="0" * 64,
        model_identifier="mock", tokens_out=10, duration_ms=10,
    )
    entry = earner_ledger.sign_as_earner(entry)

    # Try to claim the earner's signature is also the payer's signature.
    forged = LedgerEntry(**entry.to_dict())
    forged.from_signature = entry.to_signature  # forge!

    valid, _ = verify_payer_signature(forged)
    assert not valid, "domain separation failed — earner sig accepted as payer"


def test_canonical_bytes_stable_across_float_repr():
    """
    The amount canonicalization must not change byte output when the
    same float value reaches two different machines via different
    paths (e.g. one stored as 1.5, another reconstructed from 3/2).
    """
    e1 = LedgerEntry(
        entry_id="x", from_compositor="aa" * 32, to_compositor="bb" * 32,
        amount_credits=1.5, work_item_id="w",
        icp_envelope_hash="0" * 64, model_identifier="m",
        tokens_out=0, duration_ms=0, created_at_ns=0,
    )
    e2 = LedgerEntry(
        entry_id="x", from_compositor="aa" * 32, to_compositor="bb" * 32,
        amount_credits=3.0 / 2.0, work_item_id="w",
        icp_envelope_hash="0" * 64, model_identifier="m",
        tokens_out=0, duration_ms=0, created_at_ns=0,
    )
    assert canonical_sign_bytes(e1, "payer") == canonical_sign_bytes(e2, "payer")


def test_self_pay_rejected(tmp_path):
    """A compositor cannot create an entry where they are both
    payer and earner — that would be a noop economically and a
    likely attempt to game the balance cache."""
    me = _make_compositor(tmp_path, "me")
    ml = _make_ledger(tmp_path, me, "me")
    with pytest.raises(ValueError, match="self-pay"):
        ml.create_entry(
            from_compositor=me.pubkey_hex, to_compositor=me.pubkey_hex,
            amount=1.0, work_item_id="w",
            icp_envelope_hash="0" * 64, model_identifier="m",
            tokens_out=0, duration_ms=0,
        )


def test_credit_rates_table_keys():
    """The CREDIT_RATES table must include the named backends from
    the spec — catches accidental key renames."""
    expected = {
        "llama.cpp:qwen2.5-3b-q4_k_m",
        "llama.cpp:qwen2.5-7b-q4_k_m",
        "anthropic:claude-sonnet-4-5",
        "anthropic:claude-opus-4-5",
        "openai:gpt-4o",
        "mock",
    }
    assert expected.issubset(CREDIT_RATES.keys())


# Reference verify_payer_signature so it doesn't get flagged as
# unused — we want it in the public surface for the runner integration.
_ = verify_payer_signature
_ = time
