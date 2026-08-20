"""Claim exclusion across PROCESSES, not just threads.

`blackboard.py`'s module docstring states the concurrency contract in
thread-level terms: "each thread gets its own sqlite3 connection... the
writer-lock serializes claim contention. `try_claim` uses BEGIN IMMEDIATE so
two threads racing for the same item see one winner deterministically."

**Every existing test races threads.** `grep -rl multiprocessing tests/` was
empty before this file. The deployment topology these tests are supposed to
license is many runner PROCESSES -- one host runs several, and the fleet runs
many hosts -- so the property that matters is process-level exclusion and it
had never been exercised. A documented invariant with no mechanism is a promise
the code has not made.

The mechanism is different in kind, not just in degree. Thread exclusion could
in principle be provided by the GIL or by a Python-level lock, neither of which
crosses a process boundary; only SQLite's file locking does. A test that races
threads cannot distinguish those, so it cannot support the claim.

RESULT: exclusion HOLDS across processes. These tests pin it.

MUTATION-CHECKED, because a test that passes first try against a property you
suspected might be broken has not yet been shown to discriminate. Against a
`try_claim_direct` with both guards removed, the n=2 case reports 2 winners and
the n=8 case reports all 8 -- so the barrier really does produce simultaneous
claims rather than an accidentally serial run.

ONE THING THE MUTATION REVEALED. Removing ONLY the `AND claimed_by IS NULL`
from the UPDATE (leaving the SELECT guard) does NOT fail these tests: under
BEGIN IMMEDIATE the read guard alone already excludes. The two guards are
redundant by design, and each is sufficient on its own. That is defence in
depth, not dead code -- but it means a future change that drops one of them
will not be caught here, and whoever drops the second should expect these
tests to be the thing that stops them.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _claimer(db_path: str, item_id: str, agent: str, start, results) -> None:
    """Run in a CHILD PROCESS: fresh interpreter state, fresh connection."""
    from gyza.blackboard import Blackboard
    from gyza.schema import HLC

    bb = Blackboard(db_path)
    hlc = HLC(node_id=agent)
    start.wait(timeout=30)                 # maximise the overlap
    try:
        results.append((agent, bool(bb.try_claim(item_id, agent, hlc))))
    except Exception as exc:               # noqa: BLE001
        # An exception is NOT a value: a crashed claimer must not be
        # indistinguishable from a losing one.
        results.append((agent, f"ERROR:{type(exc).__name__}:{exc}"))


def _make_item(db_path: str) -> str:
    import time
    import uuid

    import numpy as np

    from gyza.blackboard import Blackboard
    from gyza.schema import EMBEDDING_DIM, WorkItem

    bb = Blackboard(db_path)
    intent_id = "intent-proc-claim"
    # post_intent registers the lineage anchor; a work item whose lineage_root
    # is not a registered intent is rejected by design.
    bb.post_intent({"intent_id": intent_id, "goal": "process claim race"})
    w = WorkItem(
        id=str(uuid.uuid7()), lineage_root=intent_id, parent_id=None,
        description="contended", desc_embedding=np.zeros(EMBEDDING_DIM,
                                                         dtype=np.float32),
        reward=0.5, reward_updated_ns=time.time_ns(), required_tier=0,
        input_hashes=[], output_spec={"kind": "test"}, streaming_ok=False,
        claimed_by=None, claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0,
        claim_hlc_node="", completed_at_ns=None, output_hash=None,
        icp_envelope_hash=None, success=None, created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )
    assert bb.post_work_item(w) is True
    return w.id


@pytest.mark.parametrize("n_procs", [2, 8])
def test_exactly_one_process_wins_a_contended_claim(tmp_path, n_procs):
    db = str(tmp_path / "bb.db")
    item_id = _make_item(db)

    ctx = mp.get_context("spawn")          # no inherited sqlite handles
    mgr = ctx.Manager()
    results = mgr.list()
    start = mgr.Barrier(n_procs)

    procs = [
        ctx.Process(target=_claimer,
                    args=(db, item_id, f"agent-{i}", start, results))
        for i in range(n_procs)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0, f"claimer died with exitcode {p.exitcode}"

    got = list(results)
    errors = [r for r in got if isinstance(r[1], str)]
    assert not errors, f"claimers raised instead of returning a verdict: {errors}"
    winners = [a for a, won in got if won is True]
    assert len(got) == n_procs, f"expected {n_procs} verdicts, got {got}"
    assert len(winners) == 1, (
        f"claim exclusion FAILED ACROSS PROCESSES: {len(winners)} winners "
        f"{winners}. BEGIN IMMEDIATE serialises writers within a process; "
        f"this asserts SQLite's file lock does it across processes too, which "
        f"is the property a multi-process runner fleet depends on.")


def test_the_database_agrees_with_the_winner(tmp_path):
    """The return value and the persisted row must name the SAME agent.

    A claim protocol that returns True to one process while storing another's
    key would pass the count check above and still be broken.
    """
    from gyza.blackboard import Blackboard

    db = str(tmp_path / "bb.db")
    item_id = _make_item(db)

    ctx = mp.get_context("spawn")
    mgr = ctx.Manager()
    results = mgr.list()
    start = mgr.Barrier(4)
    procs = [ctx.Process(target=_claimer,
                         args=(db, item_id, f"agent-{i}", start, results))
             for i in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)

    winners = [a for a, won in list(results) if won is True]
    assert len(winners) == 1, f"expected one winner, got {winners}"

    row = Blackboard(db)._conn().execute(
        "SELECT claimed_by FROM work_items WHERE id=?", (item_id,)).fetchone()
    assert row["claimed_by"] == winners[0], (
        f"the winner was told {winners[0]} but the row records "
        f"{row['claimed_by']}")
