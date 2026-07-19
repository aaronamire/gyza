"""
Tests for the resolution layer (gyza.economy.resolution) — the
accountable, minimal ground-truth injection that closes the bonded
market's loop.
"""
from __future__ import annotations

import os
import random
import secrets
import tempfile

import pytest

from gyza.economy.market import BondedMarket, sign_assertion
from gyza.economy.resolution import (
    OracleResolver,
    Verdict,
    resolve_round,
    select_targeted,
    sign_verdict,
    verify_verdict,
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


def _identity(compositor) -> AgentIdentity:
    seed, manifest = compositor.issue_agent(
        agent_type="m", model_path="mock", fs_read_paths=[], fs_write_paths=[],
        allowed_hosts=[], memory_limit_mb=512, attestation_tier=1,
    )
    return AgentIdentity(seed, manifest)


# ----------------------------------------------------------------------
# Signed verdicts — the truth is accountable
# ----------------------------------------------------------------------

def test_verdict_signs_and_verifies(compositor):
    r = _identity(compositor)
    v = sign_verdict(r, "task-1", "yes", method="oracle")
    assert v.resolver_pubkey == r.pubkey_hex
    assert verify_verdict(v)


def test_tampered_verdict_fails(compositor):
    r = _identity(compositor)
    v = sign_verdict(r, "task-1", "yes", method="oracle")
    forged = Verdict(v.task_id, "no", v.resolver_pubkey, v.method, v.signature)
    assert not verify_verdict(forged)


# ----------------------------------------------------------------------
# Driver — settle the checkable, refund the rest
# ----------------------------------------------------------------------

def test_resolve_round_settles_known_refunds_unknown(compositor):
    a, b = _identity(compositor), _identity(compositor)
    oracle = _identity(compositor)
    mkt = BondedMarket({a.pubkey_hex: 100.0, b.pubkey_hex: 100.0},
                       diversity_threshold=0.0)
    mkt.submit(sign_assertion(a, "known", "yes", 10.0))
    mkt.submit(sign_assertion(b, "known", "no", 10.0))
    mkt.submit(sign_assertion(a, "unknown", "yes", 10.0))

    truths = {"known": "yes"}  # "unknown" is not checkable
    resolver = OracleResolver(oracle, lambda t: truths.get(t))
    out = resolve_round(mkt, resolver, ["known", "unknown"])

    assert out.settled == ["known"]
    assert out.refunded == ["unknown"]
    # a won b's 10 on 'known' (+10) and got its 'unknown' stake refunded (0).
    assert mkt.capital_of(a.pubkey_hex) == pytest.approx(110.0)
    assert mkt.capital_of(b.pubkey_hex) == pytest.approx(90.0)   # lost 10 on 'known'


def test_unverifiable_verdict_is_not_trusted(compositor):
    a = _identity(compositor)
    imposter = _identity(compositor)
    mkt = BondedMarket({a.pubkey_hex: 100.0}, diversity_threshold=0.0)
    mkt.submit(sign_assertion(a, "t", "yes", 10.0))

    class BadResolver:
        def resolve(self, task_id, claims):
            # a verdict with a broken signature
            return Verdict(task_id, "no", imposter.pubkey_hex, "oracle", "00" * 64)

    out = resolve_round(mkt, BadResolver(), ["t"])
    assert out.settled == [] and out.refunded == ["t"]
    assert mkt.capital_of(a.pubkey_hex) == pytest.approx(100.0)  # refunded, not settled


# ----------------------------------------------------------------------
# Targeted selection
# ----------------------------------------------------------------------

def test_targeted_selection_prefers_contested_stake(compositor):
    a, b, c = (_identity(compositor) for _ in range(3))
    mkt = BondedMarket({i.pubkey_hex: 100.0 for i in (a, b, c)},
                       diversity_threshold=0.0)
    # 'hot' task: split 10 vs 10 (contested). 'cold' task: unanimous.
    mkt.submit(sign_assertion(a, "hot", "yes", 10.0))
    mkt.submit(sign_assertion(b, "hot", "no", 10.0))
    mkt.submit(sign_assertion(c, "cold", "yes", 10.0))
    assert select_targeted(mkt, 1) == ["hot"]


# ----------------------------------------------------------------------
# CAPSTONE — the fully closed loop, with an accountable signed oracle
# ----------------------------------------------------------------------

def test_closed_loop_bankrupts_wrong_majority_via_signed_oracle(compositor):
    rng = random.Random(3)
    n = 20
    ids = [_identity(compositor) for _ in range(n)]
    oracle = _identity(compositor)
    mono = set(i.pubkey_hex for i in ids[: int(0.6 * n)])
    mkt = BondedMarket({i.pubkey_hex: 100.0 for i in ids}, diversity_threshold=0.0)

    truths: dict[str, str] = {}
    resolver = OracleResolver(oracle, lambda t: truths.get(t))

    total_settlements = 0
    for r in range(150):
        truth = "A" if rng.random() < 0.5 else "B"
        task = f"r{r}"
        truths[task] = truth
        for i in ids:
            claim = (("A" if truth == "B" else "B")
                     if i.pubkey_hex in mono else truth)
            stake = min(10.0, mkt.capital_of(i.pubkey_hex))
            if stake > 0:
                mkt.submit(sign_assertion(i, task, claim, stake))
        # sparse TARGETED resolution: budget of 1, spent on the most
        # contested open task, settled against a SIGNED verdict.
        out = resolve_round(mkt, resolver, select_targeted(mkt, budget=1))
        for v in out.verdicts:
            assert verify_verdict(v)          # every settlement is accountable
        total_settlements += len(out.settled)
        # unresolved open tasks are refunded so capital isn't stranded
        for t in list(mkt.open_task_ids()):
            mkt.cancel(t)

    diverse_cap = sum(mkt.capital_of(i.pubkey_hex) for i in ids
                      if i.pubkey_hex not in mono)
    mono_cap = sum(mkt.capital_of(i.pubkey_hex) for i in ids if i.pubkey_hex in mono)
    # The wrong majority is bankrupted, and every settlement that did it
    # rode a verified signed verdict — the loop is closed AND accountable.
    assert diverse_cap > mono_cap
    assert total_settlements > 0
    assert mkt.total_capital() == pytest.approx(n * 100.0)  # conserved throughout
