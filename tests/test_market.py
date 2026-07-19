"""
Tests for the bonded-assertion market (gyza.economy.market).

Covers the security/economic invariants (real signatures, conservation,
deterministic settlement, diversity gate) and — the capstone — reproduces
the consensus-lab E4 finding on the REAL signed substrate: a correlated-
wrong majority is bankrupted and truth recovers, given sparse ground
truth.
"""
from __future__ import annotations

import os
import secrets
import tempfile

import pytest

from gyza.economy.market import (
    Assertion,
    BondedMarket,
    settle,
    sign_assertion,
    verify_assertion,
)
from gyza.identity import AgentIdentity, LocalCompositor


@pytest.fixture()
def compositor():
    with tempfile.TemporaryDirectory() as d:
        key_path = os.path.join(d, "compositor.key")
        with open(key_path, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(key_path, 0o600)
        yield LocalCompositor(key_path=key_path)


def _identity(compositor, mem=512) -> AgentIdentity:
    seed, manifest = compositor.issue_agent(
        agent_type="market", model_path="mock", fs_read_paths=[],
        fs_write_paths=[], allowed_hosts=[], memory_limit_mb=mem,
        attestation_tier=1,
    )
    return AgentIdentity(seed, manifest)


# ----------------------------------------------------------------------
# Signed assertions — real crypto, verifiable, tamper-evident
# ----------------------------------------------------------------------

def test_assertion_signs_and_verifies(compositor):
    idn = _identity(compositor)
    a = sign_assertion(idn, "task-1", "yes", 10.0)
    assert a.agent_pubkey == idn.pubkey_hex
    assert verify_assertion(a)


def test_tampered_assertion_fails(compositor):
    idn = _identity(compositor)
    a = sign_assertion(idn, "task-1", "yes", 10.0)
    forged = Assertion(a.agent_pubkey, a.task_id, "no", a.stake, a.nonce, a.signature)
    assert not verify_assertion(forged)         # claim changed
    bumped = Assertion(a.agent_pubkey, a.task_id, a.claim, 999.0, a.nonce, a.signature)
    assert not verify_assertion(bumped)         # stake changed


def test_zero_stake_rejected(compositor):
    idn = _identity(compositor)
    with pytest.raises(ValueError):
        sign_assertion(idn, "t", "x", 0.0)


# ----------------------------------------------------------------------
# Settlement — deterministic, conservative
# ----------------------------------------------------------------------

def test_settlement_is_zero_sum_and_pays_winners(compositor):
    a = _identity(compositor)
    b = _identity(compositor)
    c = _identity(compositor)
    asserts = [
        sign_assertion(a, "t", "yes", 10.0),   # correct
        sign_assertion(b, "t", "no", 10.0),    # wrong
        sign_assertion(c, "t", "no", 30.0),    # wrong
    ]
    s = settle(asserts, "yes")
    assert set(s.winners) == {a.pubkey_hex}
    assert set(s.losers) == {b.pubkey_hex, c.pubkey_hex}
    # winner gets the whole pot (only winner); losers lose their stakes.
    assert s.pnl[a.pubkey_hex] == pytest.approx(40.0)
    assert s.pnl[b.pubkey_hex] == pytest.approx(-10.0)
    assert s.pnl[c.pubkey_hex] == pytest.approx(-30.0)
    assert sum(s.pnl.values()) == pytest.approx(0.0)  # zero-sum


def test_settlement_is_deterministic(compositor):
    a = _identity(compositor)
    b = _identity(compositor)
    asserts = [sign_assertion(a, "t", "yes", 5.0), sign_assertion(b, "t", "no", 7.0)]
    assert settle(asserts, "yes") == settle(list(reversed(asserts)), "yes")


def test_no_winner_refunds_all(compositor):
    a = _identity(compositor)
    s = settle([sign_assertion(a, "t", "no", 10.0)], "yes")
    assert s.refunded
    assert s.pnl[a.pubkey_hex] == pytest.approx(0.0)


# ----------------------------------------------------------------------
# Market — escrow, conservation, one-per-agent
# ----------------------------------------------------------------------

def test_market_conserves_total_capital(compositor):
    a, b = _identity(compositor), _identity(compositor)
    mkt = BondedMarket({a.pubkey_hex: 100.0, b.pubkey_hex: 100.0})
    before = mkt.total_capital()
    assert mkt.submit(sign_assertion(a, "t", "yes", 20.0))
    assert mkt.submit(sign_assertion(b, "t", "no", 20.0))
    mkt.resolve("t", "yes")
    assert mkt.total_capital() == pytest.approx(before)
    assert mkt.capital_of(a.pubkey_hex) == pytest.approx(120.0)
    assert mkt.capital_of(b.pubkey_hex) == pytest.approx(80.0)


def test_market_rejects_overstake_and_duplicate(compositor):
    a = _identity(compositor)
    mkt = BondedMarket({a.pubkey_hex: 15.0})
    assert not mkt.submit(sign_assertion(a, "t", "yes", 20.0))  # over capital
    assert mkt.submit(sign_assertion(a, "t", "yes", 10.0))
    assert not mkt.submit(sign_assertion(a, "t", "no", 5.0))    # duplicate agent


def test_decision_follows_capital_not_headcount(compositor):
    # Three poor wrong agents vs one rich correct agent: capital wins.
    poor = [_identity(compositor) for _ in range(3)]
    rich = _identity(compositor)
    cap = {p.pubkey_hex: 5.0 for p in poor}
    cap[rich.pubkey_hex] = 500.0
    mkt = BondedMarket(cap, diversity_threshold=0.0)
    for p in poor:
        mkt.submit(sign_assertion(p, "t", "no", 5.0))
    mkt.submit(sign_assertion(rich, "t", "yes", 100.0))
    assert mkt.decide("t").claim == "yes"


# ----------------------------------------------------------------------
# Diversity gate
# ----------------------------------------------------------------------

def test_diversity_gate_flags_monoculture(compositor):
    agents = [_identity(compositor) for _ in range(6)]
    mkt = BondedMarket({a.pubkey_hex: 100.0 for a in agents},
                       diversity_threshold=0.1)
    # Everyone answers identically across several tasks → zero diversity.
    for t in range(4):
        for a in agents:
            mkt.submit(sign_assertion(a, f"t{t}", "same", 1.0))
    d = mkt.decide("t3")
    assert d.diversity == pytest.approx(0.0)
    assert not d.trusted


# ----------------------------------------------------------------------
# CAPSTONE — reproduce consensus-lab E4 on the real signed substrate
# ----------------------------------------------------------------------

def test_market_bankrupts_correlated_wrong_majority(compositor):
    """
    A 60% monoculture that is confidently wrong on trap questions, plus a
    diverse-correct minority, all trading REAL signed assertions. With
    sparse ground-truth resolution the wrong majority is bankrupted and
    the collective decision recovers — the settlement-primary thesis,
    now on the actual substrate rather than the abstract sim.
    """
    import random
    rng = random.Random(7)
    n = 20
    ids = [_identity(compositor) for _ in range(n)]
    mono = set(i.pubkey_hex for i in ids[: int(0.6 * n)])  # correlated-wrong
    # diverse-correct = the rest
    mkt = BondedMarket({i.pubkey_hex: 100.0 for i in ids}, diversity_threshold=0.0)

    correct_after = 0
    checked = 0
    for r in range(120):
        truth = "A" if rng.random() < 0.5 else "B"
        task = f"round-{r}"
        for i in ids:
            if i.pubkey_hex in mono:
                claim = "A" if truth == "B" else "B"   # confidently wrong
            else:
                claim = truth                          # diverse-correct
            stake = min(10.0, mkt.capital_of(i.pubkey_hex))
            if stake > 0:
                mkt.submit(sign_assertion(i, task, claim, stake))
        # sparse resolution: settle against ground truth ~20% of rounds;
        # otherwise the market never learns the truth and must refund.
        if rng.random() < 0.2:
            mkt.resolve(task, truth)
        else:
            mkt.cancel(task)
        # measure decision accuracy in the back half, once capital moved
        if r >= 90:
            # re-decide a fresh probe task, then refund it (a measurement,
            # not a settled round)
            probe = f"probe-{r}"
            for i in ids:
                claim = (("A" if truth == "B" else "B")
                         if i.pubkey_hex in mono else truth)
                stake = min(10.0, mkt.capital_of(i.pubkey_hex))
                if stake > 0:
                    mkt.submit(sign_assertion(i, probe, claim, stake))
            correct_after += (mkt.decide(probe).claim == truth)
            checked += 1
            mkt.cancel(probe)

    # Diverse-correct minority now holds the capital; late decisions are right.
    diverse_cap = sum(mkt.capital_of(i.pubkey_hex) for i in ids
                      if i.pubkey_hex not in mono)
    mono_cap = sum(mkt.capital_of(i.pubkey_hex) for i in ids
                   if i.pubkey_hex in mono)
    assert diverse_cap > mono_cap                 # majority bankrupted
    assert correct_after / checked > 0.8          # decisions recovered
