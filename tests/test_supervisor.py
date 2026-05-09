"""
Phase 3 Session 8.5 — agent supervisor.

These tests target the policy layer of the supervisor:

  * No demand → no spawn.
  * Demand above threshold on a fresh bucket → exactly one spawn.
  * Same bucket served → no second spawn.
  * Demand spread across multiple buckets → multiple spawns up to cap.
  * max_agents respected.
  * Spawned runners are stopped cleanly on supervisor.stop().

The factory is exercised via a stub that returns a runner the test
controls — we don't actually run inference here (handled by
test_runner.py).
"""
from __future__ import annotations

import secrets
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.demand import DemandOracle, LSHIndex
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.runner import AgentRunner, make_mock_executor
from gyza.schema import EMBEDDING_DIM, WorkItem
from gyza.supervisor import AgentSupervisor, SpawnRequest


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _compositor(tmp_path: Path) -> LocalCompositor:
    p = tmp_path / "comp.key"
    p.write_bytes(secrets.token_bytes(32))
    p.chmod(0o600)
    return LocalCompositor(str(p))


def _post_intent(bb: Blackboard, intent_id: str = "i1") -> str:
    bb.post_intent({
        "intent_id": intent_id,
        "natural_text": "supervisor test",
        "category": "system_task",
        "actions": [],
        "authorization": {
            "resources": [], "preview_required": False, "reversible": True,
        },
    })
    return intent_id


def _post_work_item(
    bb: Blackboard,
    intent_id: str,
    embedding: np.ndarray,
    *,
    reward: float = 0.7,
) -> str:
    w = WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=intent_id,
        parent_id=None,
        description="supervisor demand test",
        desc_embedding=embedding,
        reward=reward,
        reward_updated_ns=time.time_ns(),
        required_tier=0,
        input_hashes=[],
        output_spec={},
        streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None,
        created_at_ns=time.time_ns() - 60_000_000_000,  # aged 60s
        ttl_ns=3600 * 1_000_000_000,
    )
    bb.post_work_item(w)
    return w.id


def _normalized(seed: int, dim: int = EMBEDDING_DIM) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= max(float(np.linalg.norm(v)), 1e-9)
    return v


# Factory used by the supervisor in tests. Builds a runner that won't
# actually do anything (no work matches its specialization in most
# tests) — we only care about whether the runner is constructed +
# tracked + stopped. Memory and SpecializationTracker are minimal.
def _make_factory(
    bb: Blackboard, tmp_path: Path,
) -> "tuple[Callable, dict]":
    """Return (factory, calls) where calls records every SpawnRequest."""
    from gyza.drift import SpecializationTracker
    from gyza.memory import EpisodicMemory
    calls: dict[str, list[SpawnRequest]] = {"requests": []}

    def factory(req: SpawnRequest) -> AgentRunner:
        calls["requests"].append(req)
        agent_dir = tmp_path / "agents" / req.identity.agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        mem = EpisodicMemory(
            agent_id=req.identity.agent_id,
            db_path=str(agent_dir / "memory"),
        )
        spec = SpecializationTracker(
            agent_id=req.identity.agent_id,
            initial_embedding=req.specialization_seed,
            db_path=str(agent_dir / "spec.db"),
        )
        return AgentRunner(
            identity=req.identity,
            blackboard=bb,
            memory=mem,
            specialization=spec,
            lsh=LSHIndex(seed=42),
            executor=make_mock_executor("supervisor-spawned"),
            min_reward_threshold=0.0,
            min_similarity_threshold=-1.0,
            poll_interval_s=0.5,
        )

    return factory, calls


# ----------------------------------------------------------------------
# Policy
# ----------------------------------------------------------------------

def test_no_demand_no_spawn(tmp_path):
    """An empty blackboard yields no demand signals → supervisor never
    spawns."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    lsh = LSHIndex(seed=42)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    factory, calls = _make_factory(bb, tmp_path)
    sup = AgentSupervisor(
        compositor=_compositor(tmp_path),
        oracle=oracle, lsh=lsh, agent_factory=factory,
        spawn_threshold=1.0, max_agents=4, poll_interval_s=0.2,
    )
    sup.start()
    try:
        time.sleep(0.6)
    finally:
        sup.stop()
    assert sup.spawn_count == 0
    assert calls["requests"] == []


def test_high_demand_triggers_one_spawn(tmp_path):
    """
    Plant 5 work items that all hash to the same bucket. The deficit
    on that bucket exceeds threshold → supervisor spawns ONE agent
    serving that bucket. A second poll tick must NOT spawn again
    (the bucket is now served).
    """
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _post_intent(bb)
    lsh = LSHIndex(seed=42)
    # Same embedding for every item → same bucket → high deficit.
    target_emb = _normalized(seed=1)
    for _ in range(5):
        _post_work_item(bb, intent_id, target_emb, reward=0.8)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    oracle._poll()  # populate signals synchronously

    factory, calls = _make_factory(bb, tmp_path)
    sup = AgentSupervisor(
        compositor=_compositor(tmp_path),
        oracle=oracle, lsh=lsh, agent_factory=factory,
        spawn_threshold=1.0, max_agents=4, poll_interval_s=0.2,
    )
    sup.start()
    try:
        # Wait long enough for the initial spawn AND a second poll tick.
        time.sleep(1.0)
    finally:
        sup.stop()
    assert sup.spawn_count == 1, (
        f"expected exactly 1 spawn (bucket already served on tick 2), "
        f"got {sup.spawn_count}"
    )
    # The factory request's specialization_seed should hash to the
    # same bucket the work items are in.
    req = calls["requests"][0]
    target_bucket = lsh.hash(target_emb)
    assert lsh.hash(req.specialization_seed) == target_bucket


def test_multi_bucket_demand_spawns_per_bucket(tmp_path):
    """Two distinct hot buckets → supervisor spawns one agent per
    bucket, up to max_agents."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _post_intent(bb)
    lsh = LSHIndex(seed=42)
    emb_a = _normalized(seed=10)
    emb_b = _normalized(seed=20)
    # Pick seeds whose hashes differ — verify before relying on it.
    if lsh.hash(emb_a) == lsh.hash(emb_b):
        pytest.skip("test fixture seeds collided in LSH — pick different seeds")
    for _ in range(5):
        _post_work_item(bb, intent_id, emb_a, reward=0.8)
    for _ in range(5):
        _post_work_item(bb, intent_id, emb_b, reward=0.8)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    oracle._poll()

    factory, calls = _make_factory(bb, tmp_path)
    sup = AgentSupervisor(
        compositor=_compositor(tmp_path),
        oracle=oracle, lsh=lsh, agent_factory=factory,
        spawn_threshold=1.0, max_agents=4, poll_interval_s=0.2,
    )
    sup.start()
    try:
        time.sleep(1.0)
    finally:
        sup.stop()
    assert sup.spawn_count == 2
    spawned_buckets = {req.bucket for req in calls["requests"]}
    assert spawned_buckets == {lsh.hash(emb_a), lsh.hash(emb_b)}


def test_max_agents_cap(tmp_path):
    """Three hot buckets but max_agents=2 → only 2 spawns."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _post_intent(bb)
    lsh = LSHIndex(seed=42)
    embs = []
    seeds = iter(range(100, 1000))
    while len(embs) < 3:
        s = next(seeds)
        v = _normalized(seed=s)
        h = lsh.hash(v)
        if all(lsh.hash(e) != h for e in embs):
            embs.append(v)
    for v in embs:
        for _ in range(5):
            _post_work_item(bb, intent_id, v, reward=0.8)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    oracle._poll()

    factory, _calls = _make_factory(bb, tmp_path)
    sup = AgentSupervisor(
        compositor=_compositor(tmp_path),
        oracle=oracle, lsh=lsh, agent_factory=factory,
        spawn_threshold=1.0, max_agents=2, poll_interval_s=0.2,
    )
    sup.start()
    try:
        time.sleep(1.0)
    finally:
        sup.stop()
    assert sup.spawn_count == 2


def test_factory_failure_does_not_kill_loop(tmp_path):
    """A factory that raises must not bring the supervisor down. The
    next poll cycle still spawns for the same bucket if conditions
    permit (the oracle still reports demand)."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _post_intent(bb)
    lsh = LSHIndex(seed=42)
    emb = _normalized(seed=42)
    for _ in range(5):
        _post_work_item(bb, intent_id, emb, reward=0.8)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    oracle._poll()

    call_n = {"n": 0}

    def angry_factory(req: SpawnRequest) -> AgentRunner:
        call_n["n"] += 1
        if call_n["n"] == 1:
            raise RuntimeError("synthetic factory failure")
        # On retry, behave normally.
        good_factory, _ = _make_factory(bb, tmp_path)
        return good_factory(req)

    sup = AgentSupervisor(
        compositor=_compositor(tmp_path),
        oracle=oracle, lsh=lsh, agent_factory=angry_factory,
        spawn_threshold=1.0, max_agents=4, poll_interval_s=0.2,
    )
    sup.start()
    try:
        # Need at least 2 poll cycles: one fails, second succeeds.
        time.sleep(1.0)
    finally:
        sup.stop()
    assert call_n["n"] >= 2, "supervisor stopped after factory failure"
    assert sup.spawn_count == 1, "second attempt should have succeeded"


def test_stop_halts_spawned_runners(tmp_path):
    """After stop(), every spawned runner has stopped its thread."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _post_intent(bb)
    lsh = LSHIndex(seed=42)
    for _ in range(5):
        _post_work_item(bb, intent_id, _normalized(seed=7), reward=0.8)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    oracle._poll()

    factory, calls = _make_factory(bb, tmp_path)
    sup = AgentSupervisor(
        compositor=_compositor(tmp_path),
        oracle=oracle, lsh=lsh, agent_factory=factory,
        spawn_threshold=1.0, max_agents=4, poll_interval_s=0.2,
    )
    sup.start()
    try:
        time.sleep(0.5)
        assert sup.spawn_count >= 1
        runners_seen = []
        # Walk the call log to recover the runner instances.
        # The factory creates them; supervisor holds them in _agents.
        with sup._lock:
            for a in sup._agents.values():
                runners_seen.append(a.runner)
        assert all(r.is_running() for r in runners_seen)
    finally:
        sup.stop()
    # After stop, runners are not running.
    for r in runners_seen:
        assert not r.is_running(), (
            "supervisor.stop did not halt a spawned runner"
        )


def test_list_agents_returns_snapshot(tmp_path):
    """list_agents returns plain dicts, not references that could
    leak holds on the runner objects."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _post_intent(bb)
    lsh = LSHIndex(seed=42)
    for _ in range(5):
        _post_work_item(bb, intent_id, _normalized(seed=11), reward=0.8)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    oracle._poll()
    factory, _ = _make_factory(bb, tmp_path)
    sup = AgentSupervisor(
        compositor=_compositor(tmp_path),
        oracle=oracle, lsh=lsh, agent_factory=factory,
        spawn_threshold=1.0, max_agents=4, poll_interval_s=0.2,
    )
    sup.start()
    try:
        time.sleep(0.5)
        rows = sup.list_agents()
        assert len(rows) == 1
        assert "agent_id" in rows[0]
        assert "bucket" in rows[0]
        assert "spawned_at_ns" in rows[0]
    finally:
        sup.stop()


def test_max_agents_zero_never_spawns(tmp_path):
    """Edge case: max_agents=0 means we never spawn even with demand."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _post_intent(bb)
    lsh = LSHIndex(seed=42)
    for _ in range(5):
        _post_work_item(bb, intent_id, _normalized(seed=33), reward=0.8)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    oracle._poll()
    factory, _ = _make_factory(bb, tmp_path)
    sup = AgentSupervisor(
        compositor=_compositor(tmp_path),
        oracle=oracle, lsh=lsh, agent_factory=factory,
        spawn_threshold=1.0, max_agents=0, poll_interval_s=0.2,
    )
    sup.start()
    try:
        time.sleep(0.5)
    finally:
        sup.stop()
    assert sup.spawn_count == 0


def test_negative_max_agents_rejected(tmp_path):
    bb = Blackboard(str(tmp_path / "bb.db"))
    lsh = LSHIndex(seed=42)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    factory, _ = _make_factory(bb, tmp_path)
    with pytest.raises(ValueError):
        AgentSupervisor(
            compositor=_compositor(tmp_path),
            oracle=oracle, lsh=lsh, agent_factory=factory,
            max_agents=-1,
        )


_ = AgentIdentity  # silence unused-import in static checkers
_ = threading
