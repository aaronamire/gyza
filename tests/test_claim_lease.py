"""A crashed runner must not leak its work item.

THE DEFECT, demonstrated before it was fixed. `release_claim` has exactly one
caller -- the in-process failure path in `_run_loop` -- and `get_unclaimed`'s
TTL filter applies only to rows that are ALREADY unclaimed. So a runner that
DIED holding a claim left `claimed_by` set forever: the item was never served
again and never expired.

WHY IT HAD TO BE FIXED BEFORE PROCESS SUPERVISION, not alongside it. That leak
is survivable while a crash is rare and takes the node with it. Supervising
runners in separate processes and restarting them makes a crash ROUTINE, so
adding supervision first would have converted a rare permanent leak into a
frequent one -- supervision would have made the system worse.

AND WHY THE OWNERSHIP CHECK HAD TO COME FIRST OF ALL. A lease without one is
unsafe: `complete_work_item` was `WHERE id=?` and nothing else, so a
slow-but-alive runner whose lease had expired could overwrite the result of
whoever legitimately reclaimed the item, silently, last-write-wins.
"""
from __future__ import annotations

import time
import uuid

import numpy as np
import pytest

from gyza.blackboard import Blackboard, ClaimLostError
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem


def _bb(tmp_path, name="bb.db"):
    bb = Blackboard(str(tmp_path / name))
    bb.post_intent({"intent_id": "i", "natural_text": "t",
                    "category": "system_task", "actions": [],
                    "authorization": {"resources": [],
                                      "preview_required": False,
                                      "reversible": True}})
    return bb


def _item(bb, ttl_ns=3600 * 10**9):
    emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    emb[0] = 1.0
    w = WorkItem(
        id=str(uuid.uuid7()), lineage_root="i", parent_id=None,
        description="d", desc_embedding=emb, reward=0.5,
        reward_updated_ns=time.time_ns(), required_tier=0, input_hashes=[],
        output_spec={}, streaming_ok=False, claimed_by=None,
        claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(), ttl_ns=ttl_ns)
    bb.post_work_item(w)
    return w


def test_a_claim_held_past_its_lease_is_RECLAIMED(tmp_path):
    bb = _bb(tmp_path)
    w = _item(bb)
    assert bb.try_claim(w.id, "agent-that-dies", HLC(node_id="n")) is True
    assert bb.get_unclaimed(0.0, 0) == [], "claimed items must not be served"

    assert bb.reclaim_expired_claims(lease_ns=1) == [w.id]
    assert [x.id for x in bb.get_unclaimed(0.0, 0)] == [w.id], (
        "the item did not return to the pool; a crashed runner still leaks it")


def test_a_claim_INSIDE_its_lease_is_NOT_stolen(tmp_path):
    """The counter-control. A reaper that took everything would be a reaper
    nobody could run, and slow work is not dead work."""
    bb = _bb(tmp_path)
    w = _item(bb)
    bb.try_claim(w.id, "agent-still-working", HLC(node_id="n"))
    assert bb.reclaim_expired_claims(lease_ns=10**12) == []
    assert bb.get_unclaimed(0.0, 0) == []


def test_a_COMPLETED_item_is_never_reclaimed(tmp_path):
    """A finished row keeps `claimed_by` as the record of who did the work.
    Reclaiming it would erase attribution for no benefit."""
    bb = _bb(tmp_path)
    w = _item(bb)
    bb.try_claim(w.id, "agent-a", HLC(node_id="n"))
    bb.complete_work_item(w.id, "aa" * 32, "bb" * 32, True, HLC(node_id="n"),
                          expected_owner="agent-a")
    assert bb.reclaim_expired_claims(lease_ns=1) == []
    row = bb._conn().execute(
        "SELECT claimed_by FROM work_items WHERE id=?", (w.id,)).fetchone()
    assert row["claimed_by"] == "agent-a"


def test_a_LATE_completion_by_the_evicted_owner_is_REFUSED(tmp_path):
    """The reason the ownership check had to land first.

    Without it the lease is a footgun: the original holder overwrites the new
    holder's result, silently, and the board records work nobody can attribute.
    """
    bb = _bb(tmp_path)
    w = _item(bb)
    bb.try_claim(w.id, "slow-agent", HLC(node_id="n"))
    bb.reclaim_expired_claims(lease_ns=1)
    assert bb.try_claim(w.id, "new-agent", HLC(node_id="n")) is True

    with pytest.raises(ClaimLostError, match="no longer claimed"):
        bb.complete_work_item(w.id, "aa" * 32, "bb" * 32, True,
                              HLC(node_id="n"), expected_owner="slow-agent")

    # ...and the rightful holder still can.
    bb.complete_work_item(w.id, "cc" * 32, "dd" * 32, True, HLC(node_id="n"),
                          expected_owner="new-agent")
    row = bb._conn().execute(
        "SELECT output_hash FROM work_items WHERE id=?", (w.id,)).fetchone()
    assert row["output_hash"] == "cc" * 32


def test_expected_owner_None_preserves_the_UNCHECKED_path(tmp_path):
    """Raft apply must not re-litigate ownership consensus already decided, so
    the check is opt-in. Asserted rather than assumed, because a default that
    silently began refusing would break replication."""
    bb = _bb(tmp_path)
    w = _item(bb)
    bb.try_claim(w.id, "agent-a", HLC(node_id="n"))
    bb.complete_work_item(w.id, "ee" * 32, "ff" * 32, True, HLC(node_id="n"))
    row = bb._conn().execute(
        "SELECT output_hash FROM work_items WHERE id=?", (w.id,)).fetchone()
    assert row["output_hash"] == "ee" * 32


def test_the_RUNNER_reaps_on_every_poll(tmp_path):
    """The mechanism must be WIRED, not merely present.

    This file's own subject is a recovery path that existed and was never
    called. Reaping lives in `_run_loop` rather than in a sweeper precisely so
    it cannot be left unconstructed: every live runner reaps for every dead
    one, and disabling it would mean disabling the work loop.
    """
    import ast
    import inspect

    from gyza.runner import AgentRunner

    src = inspect.getsource(AgentRunner._run_loop)
    calls = [n for n in ast.walk(ast.parse(src.strip()))
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "reclaim_expired_claims"]
    assert calls, "_run_loop does not reap; a crashed runner's item leaks"


def test_the_lease_is_sized_ABOVE_the_longest_legitimate_action():
    """Too short steals work from slow runners. The sandbox caps an action at
    max_cpu_seconds=300, so the lease must exceed that with margin -- if this
    fails, either the lease shrank or the sandbox cap grew, and the two must be
    reconciled deliberately."""
    from gyza.blackboard import Blackboard as BB
    from gyza.sandbox.config import SandboxConfig

    cap_s = SandboxConfig().max_cpu_seconds or 300
    assert BB.CLAIM_LEASE_NS >= 3 * cap_s * 1_000_000_000, (
        f"lease {BB.CLAIM_LEASE_NS / 1e9:.0f}s is under 3x the sandbox cap "
        f"of {cap_s}s; slow-but-alive runners would have work stolen")
