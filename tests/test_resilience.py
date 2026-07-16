"""
Tests for Byzantine resilience (gyza.resilience).

Covers the measurement-level detector (equivocation), the policy-level
response (quarantine + honest sub-DAG), the resilience metric, and — the
load-bearing soundness property — that an honest partition fork is NOT
mistaken for equivocation.
"""
from __future__ import annotations

import os
import secrets
import tempfile

import pytest

from gyza.adaptor import AgentAdaptor
from gyza.resilience import (
    assess_resilience,
    detect_equivocation,
    quarantine_view,
)


@pytest.fixture()
def compositor():
    from gyza.identity import LocalCompositor

    with tempfile.TemporaryDirectory() as d:
        key_path = os.path.join(d, "compositor.key")
        with open(key_path, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(key_path, 0o600)
        yield LocalCompositor(key_path=key_path)


def _adaptor(compositor, name, fn=None):
    fn = fn or (lambda prompt, ctx: f"{name}:{prompt}")
    return AgentAdaptor.from_compositor(
        compositor, fn, agent_type=name, memory_limit_mb=512,
    )


# ----------------------------------------------------------------------
# Detection
# ----------------------------------------------------------------------

def test_double_signed_action_is_equivocation(compositor):
    """A compromised agent signs the SAME action_id twice with different
    outputs — detected and attributed to its key."""
    bad = _adaptor(compositor, "compromised")
    e1 = bad.act(intent_id="m", action_id="report", prompt="all clear")
    e2 = bad.act(intent_id="m", action_id="report", prompt="under attack")
    assert e1.output_hash != e2.output_hash

    eqs = detect_equivocation([e1, e2])
    assert len(eqs) == 1
    assert eqs[0].agent_pubkey == bad.pubkey_hex
    assert eqs[0].action_id == "report"
    assert len(eqs[0].conflicting_output_hashes) == 2


def test_honest_history_has_no_equivocation(compositor):
    a = _adaptor(compositor, "honest")
    e1 = a.act(intent_id="m", action_id="step-1", prompt="x")
    e2 = a.act(intent_id="m", action_id="step-2", prompt="y", parent=e1)
    e3 = a.act(intent_id="m", action_id="step-3", prompt="z", parent=e2)
    assert detect_equivocation([e1, e2, e3]) == []


def test_idempotent_reinsert_is_not_equivocation(compositor):
    """The same envelope appearing twice (gossip dedup) is not a contradiction."""
    a = _adaptor(compositor, "honest")
    e = a.act(intent_id="m", action_id="s", prompt="x")
    assert detect_equivocation([e, e]) == []


def test_partition_fork_is_not_equivocation(compositor):
    """
    SOUNDNESS: an honest partition fork — two DIFFERENT agents extending
    the same shared parent on DIFFERENT action_ids — must not be flagged.
    This is the honest DDIL fork; only self-contradiction is Byzantine.
    """
    left = _adaptor(compositor, "left")
    right = _adaptor(compositor, "right")

    root = left.act(intent_id="m", action_id="root", prompt="start")
    # Concurrent, honest, different authors + different action_ids.
    el = left.act(intent_id="m", action_id="L", prompt="left", parent=root)
    er = right.act(intent_id="m", action_id="R", prompt="right", parent=root)

    assert detect_equivocation([root, el, er]) == []


# ----------------------------------------------------------------------
# Quarantine + route-around
# ----------------------------------------------------------------------

def test_quarantine_partitions_by_author(compositor):
    honest = _adaptor(compositor, "honest")
    bad = _adaptor(compositor, "bad")
    eh = honest.act(intent_id="m", action_id="h", prompt="x")
    eb = bad.act(intent_id="m", action_id="b", prompt="y")

    view = quarantine_view([eh, eb], {bad.pubkey_hex})
    assert [e.action_id for e in view.honest_envelopes] == ["h"]
    assert [e.action_id for e in view.quarantined_envelopes] == ["b"]


def test_collective_routes_around_compromised_agent(compositor):
    """
    Two honest agents plus one compromised agent that equivocates on its
    own (uncconsumed) action. assess_resilience quarantines the bad agent
    and the honest remainder still forms a valid DAG — mission intact.
    """
    a = _adaptor(compositor, "coordinator")
    b = _adaptor(compositor, "worker")
    bad = _adaptor(compositor, "compromised")

    root = a.act(intent_id="m", action_id="root", prompt="mission")
    work = b.act(intent_id="m", action_id="work", prompt="do it", parent=root)
    # Compromised agent equivocates on its OWN action; honest work does
    # not consume it (nobody builds on a poisoned leaf).
    r1 = bad.act(intent_id="m", action_id="rogue", prompt="lie A", parent=root)
    r2 = bad.act(intent_id="m", action_id="rogue", prompt="lie B", parent=root)

    report = assess_resilience([root, work, r1, r2])

    assert report.total_agents == 3
    assert len(report.equivocations) == 1
    assert bad.pubkey_hex in report.quarantined_agents
    assert report.mission_intact
    assert report.honest_envelopes == 2  # root + work
    # Honest fraction excludes both rogue envelopes.
    assert report.honest_fraction == pytest.approx(2 / 4)
    assert "quarantined" in report.summary()


def test_clean_collective_scores_full_resilience(compositor):
    a = _adaptor(compositor, "a")
    b = _adaptor(compositor, "b")
    root = a.act(intent_id="m", action_id="root", prompt="x")
    child = b.act(intent_id="m", action_id="c", prompt="y", parent=root)

    report = assess_resilience([root, child])
    assert report.equivocations == []
    assert report.quarantined_agents == frozenset()
    assert report.honest_fraction == 1.0
    assert report.mission_intact


def test_extra_quarantine_is_honored(compositor):
    """Evidence from outside this module (e.g. failed attestation) can
    quarantine an agent even without an equivocation."""
    a = _adaptor(compositor, "a")
    b = _adaptor(compositor, "b")
    root = a.act(intent_id="m", action_id="root", prompt="x")
    b.act(intent_id="m", action_id="c", prompt="y", parent=root)

    report = assess_resilience(
        [root, b.act(intent_id="m", action_id="c2", prompt="z", parent=root)],
        extra_quarantine={b.pubkey_hex},
    )
    assert b.pubkey_hex in report.quarantined_agents
    assert report.honest_envelopes == 1  # only a's root


# ----------------------------------------------------------------------
# The runnable scenario stays honest
# ----------------------------------------------------------------------

def test_byzantine_demo_invariants():
    from gyza.demo.byzantine import run_scenario

    result = run_scenario(verbose=False)
    assert result.over_bound_prevented            # act 2: refused at sign time
    assert len(result.report.equivocations) == 1  # act 3+4: the lie is caught
    assert len(result.report.quarantined_agents) == 1
    assert result.report.mission_intact           # honest DAG survives
    assert result.honest_dag_valid
