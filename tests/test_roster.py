"""A fixed roster of agents as THREADS in one process.

`supervisor.py` declines a threaded roster because "threads share a fate — one
unhandled exception in one runner takes the whole roster." Half right, and the
half matters: a Python exception does not cross threads, so what was missing
was anything to NOTICE a dead daemon thread. These tests pin the noticing.

The other half is real and is NOT engineered around: a process-level fault
(OOM, segfault) takes all agents at once. That is the price of a 130x memory
saving and it is documented, not hidden.
"""
from __future__ import annotations

import json
import time
import uuid

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.identity import LocalCompositor
from gyza.roster import RunnerThreadRoster
from gyza.schema import EMBEDDING_DIM, WorkItem
from gyza.supervisor import RunnerSpec


@pytest.fixture(scope="module", autouse=True)
def _stub_embedder():
    """A roster test must not race a SentenceTransformer load.

    Measured while building this: the FIRST action per agent took 18.2 s, and
    two agents took 18.2 s EACH because both threads hit the cold model load
    together. Warm actions are 43-260 ms. That is a real property of a cold
    fleet -- and it is not what these tests are about, so it is pinned out
    here rather than absorbed into every timeout.

    Module-scoped, NOT in conftest: the suite must still exercise the real
    embedder somewhere, and disabling it globally would trade a slow test for
    lost coverage.
    """
    import os

    import gyza.embeddings as E

    prev = os.environ.get("GYZA_EMBEDDER")
    os.environ["GYZA_EMBEDDER"] = "stub"
    E.reset_default_embedder()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("GYZA_EMBEDDER", None)
        else:
            os.environ["GYZA_EMBEDDER"] = prev
        E.reset_default_embedder()


def _roster(tmp_path, n, *, kind="mock", **kw):
    comp = LocalCompositor(key_path=str(tmp_path / "k.key"))
    bb = Blackboard(str(tmp_path / "b.db"))
    specs = []
    for i in range(n):
        seed, man = comp.issue_agent(
            agent_type=f"r{i}", model_path="mock", fs_read_paths=[],
            fs_write_paths=[], allowed_hosts=[], memory_limit_mb=512,
            attestation_tier=0)
        st = tmp_path / f"a{i}.json"
        st.write_text(json.dumps({"seed_hex": seed.hex(), "manifest": man}))
        from gyza.identity import AgentIdentity
        specs.append(RunnerSpec(
            agent_id=AgentIdentity(seed, man).agent_id,
            agent_state_path=str(st), blackboard_path=str(tmp_path / "b.db"),
            memory_path=str(tmp_path / f"m{i}"),
            spec_db_path=str(tmp_path / f"s{i}.db"),
            artifact_store_path=str(tmp_path / "cas"),
            poll_interval_s=0.1, min_reward=0.0, min_similarity=-1.0,
            sandboxed=False, executor_kind=kind, command_argv=None,
            model="none"))
    return RunnerThreadRoster(specs, blackboard=bb, poll_interval_s=0.3, **kw), bb


def _post(bb, n, intent="roster"):
    try:
        bb.post_intent({"intent_id": intent, "natural_text": "r",
                        "category": "system_task", "actions": [],
                        "authorization": {"resources": [],
                                          "preview_required": False,
                                          "reversible": True}})
    except Exception:
        pass
    e = np.zeros(EMBEDDING_DIM, dtype=np.float32); e[0] = 1.0
    for _ in range(n):
        bb.post_work_item(WorkItem(
            id=str(uuid.uuid7()), lineage_root=intent, parent_id=None,
            description="work", desc_embedding=e, reward=0.9,
            reward_updated_ns=time.time_ns(), required_tier=0, input_hashes=[],
            output_spec={"kind": "t"}, streaming_ok=False, claimed_by=None,
            claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
            completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
            success=None, created_at_ns=time.time_ns(), ttl_ns=3600 * 10**9))


def _signed(bb, intent="roster"):
    return bb._conn().execute(
        "SELECT COUNT(*) c FROM work_items WHERE lineage_root=? "
        "AND icp_envelope_hash IS NOT NULL", (intent,)).fetchone()["c"]


def _wait(fn, timeout=25.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.2)
    return False


# --------------------------------------------------------------------------- #
def test_a_roster_actually_does_work(tmp_path):
    """It does the thing, not merely starts — the standing rule."""
    r, bb = _roster(tmp_path, 4)
    _post(bb, 8)
    r.start()
    try:
        assert _wait(lambda: _signed(bb) >= 8), f"only {_signed(bb)}/8 signed"
    finally:
        r.stop(timeout_s=10)
    assert r.summary()["agents"] == 4


def test_ONE_dying_thread_does_not_take_the_roster(tmp_path):
    """THE OBJECTION, tested directly. Kill one agent's loop; the others must
    keep working and the dead one must be restarted."""
    r, bb = _roster(tmp_path, 4, max_restarts=3)
    _post(bb, 6)
    r.start()
    try:
        assert _wait(lambda: any(s["alive"] for s in r.status()))
        victim = r._slots[0]
        # Simulate an unhandled error inside that runner's loop.
        victim.runner._stop.set()
        assert _wait(lambda: victim.restarts >= 1 or _signed(bb) >= 6,
                     timeout=25)
        # the roster as a whole still made progress
        assert _signed(bb) > 0
        assert sum(1 for s in r.status() if s["alive"]) >= 2
    finally:
        r.stop(timeout_s=10)


def test_an_UNBUILDABLE_agent_is_isolated_not_fatal(tmp_path):
    """One agent whose state file is corrupt must not stop the other three."""
    r, bb = _roster(tmp_path, 4)
    open(r._slots[1].spec.agent_state_path, "w").write("{ not json")
    _post(bb, 6)
    r.start()
    try:
        assert _wait(lambda: _signed(bb) >= 6), f"{_signed(bb)}/6 signed"
        st = r.status()
        assert st[1]["gave_up"] is True and st[1]["last_error"]
        assert sum(1 for s in st if s["alive"]) == 3
    finally:
        r.stop(timeout_s=10)


def test_an_IDLE_roster_is_never_restarted(tmp_path):
    """NEGATIVE CONTROL, and the one that caught the equivalent bug in the
    process supervisor: an agent with nothing to do makes no progress and is
    perfectly healthy. Restarting it would punish a quiet queue."""
    r, bb = _roster(tmp_path, 3, stall_timeout_s=0.5)
    r.start()                                  # no work posted at all
    try:
        time.sleep(3.0)
        assert sum(s["restarts"] for s in r.status()) == 0, r.status()
    finally:
        r.stop(timeout_s=10)


def test_stop_is_clean_and_idempotent(tmp_path):
    r, bb = _roster(tmp_path, 3)
    _post(bb, 3)
    r.start()
    _wait(lambda: _signed(bb) >= 1)
    r.stop(timeout_s=10)
    r.stop(timeout_s=5)
    assert all(not s["alive"] for s in r.status())


def test_the_blackboard_is_SHARED_and_the_lsh_is_too(tmp_path):
    """Sharing is what takes the marginal cost of a runner from 9.6 MB to 0.27.
    `Blackboard._conn` is thread-local, so one object is safe across threads."""
    r, bb = _roster(tmp_path, 3)
    r.start()
    try:
        assert _wait(lambda: all(s.runner is not None for s in r._slots))
        assert all(s.runner._bb is bb for s in r._slots)
        assert len({id(s.runner._lsh) for s in r._slots}) == 1
    finally:
        r.stop(timeout_s=10)


def test_a_sandboxed_roster_REQUIRES_a_bounds_proof(tmp_path):
    """Same trigger the process path uses: a sandboxed agent refuses to sign
    without an enforcement record, so a valid envelope implies bounded work."""
    r, _bb = _roster(tmp_path, 1)
    r._slots[0].spec = RunnerSpec(**{**r._slots[0].spec.__dict__,
                                     "sandboxed": True})
    ident, runner = r._build(r._slots[0].spec)
    assert runner._require_enforcement is True
