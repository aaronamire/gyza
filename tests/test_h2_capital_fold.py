"""
H2 fix — market capital is append-only, partitioned, derived-not-stored.

FINDINGS_GYZA_INVARIANT_AUDIT and ARCHITECTURAL_PRINCIPLE named
``BondedMarket._capital`` the anti-pattern living in the same codebase as the
pattern: a mutable stored aggregate, mutated in place at four sites, that no
gate read. These tests pin the representational fix.
"""
from __future__ import annotations

import inspect

import pytest

import os
import secrets

from gyza.economy.market import BondedMarket, CapitalEntry, sign_assertion
from gyza.identity import AgentIdentity, LocalCompositor


@pytest.fixture
def agents(tmp_path):
    key_path = os.path.join(tmp_path, "compositor.key")
    with open(key_path, "wb") as f:
        f.write(secrets.token_bytes(32))
    os.chmod(key_path, 0o600)
    c = LocalCompositor(key_path=key_path)
    out = []
    for i in range(3):
        seed, manifest = c.issue_agent(
            agent_type=f"a{i}", model_path="mock", fs_read_paths=[],
            fs_write_paths=[], allowed_hosts=[], memory_limit_mb=512,
            attestation_tier=1,
        )
        out.append(AgentIdentity(seed, manifest))
    return out


def _mkt(agents, cap=100.0):
    return BondedMarket({a.pubkey_hex: cap for a in agents},
                        diversity_threshold=0.0)


# --------------------------------------------------------------------------- #
#  ACCEPTANCE: no mutable aggregate a gate must separately read                #
# --------------------------------------------------------------------------- #
def test_no_mutable_capital_aggregate_remains(agents):
    """The defect was a stored dict. Assert it is gone rather than trusting the
    diff: a gate that must read a second mutable pool is the failure mode."""
    m = _mkt(agents)
    assert not hasattr(m, "_capital"), "the mutable aggregate is back"

    # No attribute holds a per-agent balance map. `_entries` is the log,
    # `_escrow` is per-task held stake (not a derived balance).
    for name, val in vars(m).items():
        if name in ("_entries", "_escrow", "_open", "_history", "_threshold"):
            continue
        assert not isinstance(val, dict), (
            f"unexpected dict attribute {name!r} — is it a stored aggregate?")

    src = inspect.getsource(BondedMarket)
    assert "self._capital" not in src


def test_capital_is_a_pure_fold_recomputable_from_outside(agents):
    """Derived-not-stored: an external auditor folding the SAME entries must
    get the SAME answer. That identity is what makes a gate frame-aligned by
    construction rather than by convention."""
    m = _mkt(agents)
    a = agents[0]
    m.submit(sign_assertion(a, "t1", "yes", 30.0))

    external = sum(e.delta for e in m.capital_entries()
                   if e.agent_pubkey == a.pubkey_hex)
    assert external == m.capital_of(a.pubkey_hex) == 70.0
    assert sum(e.delta for e in m.capital_entries()) == m.total_capital()


def test_every_capital_moving_path_writes_an_entry(agents):
    """ACCEPTANCE (plan §7): every credit-moving path writes an entry. If a
    path could move capital without appending, the fold would stop being a
    function of what happened and a blind channel would reopen."""
    a, b, _c = agents
    m = _mkt(agents)
    n0 = len(m.capital_entries())

    # seed already wrote one entry per agent
    assert n0 == 3
    assert {e.reason for e in m.capital_entries()} == {"seed"}

    m.submit(sign_assertion(a, "t1", "yes", 10.0))          # stake
    m.submit(sign_assertion(b, "t1", "no", 10.0))
    assert len(m.capital_entries()) == n0 + 2
    assert [e.reason for e in m.capital_entries()[-2:]] == ["stake", "stake"]

    m.resolve("t1", "yes")                                   # settle
    assert {e.reason for e in m.capital_entries()[-2:]} == {"settle"}

    m.submit(sign_assertion(a, "t2", "yes", 5.0))
    m.cancel("t2")                                           # refund
    assert m.capital_entries()[-1].reason == "refund"


def test_entries_are_append_only_and_partitioned(agents):
    """Append-only by ABSENCE of a mutator, and partitioned by agent pubkey so
    the guard's state partitions along the action axis (C8)."""
    m = _mkt(agents)
    m.submit(sign_assertion(agents[0], "t1", "yes", 10.0))

    entries = m.capital_entries()
    assert [e.seq for e in entries] == list(range(len(entries)))
    assert all(e.agent_pubkey for e in entries), "every entry carries a partition"
    assert all(isinstance(e, CapitalEntry) for e in entries)

    # frozen: an entry cannot be edited after the fact
    with pytest.raises(Exception):
        entries[0].delta = 999.0  # type: ignore[misc]

    # the only mutator is the append helper
    mutators = [n for n, _ in inspect.getmembers(BondedMarket, inspect.isfunction)
                if n in ("update_capital", "set_capital", "delete_entry")]
    assert mutators == []


def test_capital_entries_returns_a_copy_not_the_live_log(agents):
    m = _mkt(agents)
    got = m.capital_entries()
    got.append(CapitalEntry(seq=99, agent_pubkey="x", delta=1e9, reason="evil"))
    assert m.total_capital() == 300.0, "the log must not be writable via the view"


def test_conservation_still_holds_after_the_representation_change(agents):
    """Regression guard: settlement is zero-sum by construction and the change
    must not have perturbed it."""
    a, b, _c = agents
    m = _mkt(agents)
    before = m.total_capital()
    m.submit(sign_assertion(a, "t1", "yes", 40.0))
    m.submit(sign_assertion(b, "t1", "no", 40.0))
    m.resolve("t1", "yes")
    assert m.total_capital() == pytest.approx(before)
    assert m.capital_of(a.pubkey_hex) == pytest.approx(140.0)
    assert m.capital_of(b.pubkey_hex) == pytest.approx(60.0)
