from __future__ import annotations

import threading
import time
import uuid

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.icp import verify_envelope
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.runner import AgentRunner, make_mock_executor
from gyza.schema import EMBEDDING_DIM, WorkItem


def _intent(suffix: str) -> str:
    d = suffix
    return f"{d*8}-{d*4}-4{d*3}-8{d*3}-{d*12}"


def _goal_spec(intent_id: str) -> dict:
    return {
        "intent_id": intent_id,
        "natural_text": "test",
        "category": "system_task",
        "actions": [],
        "authorization": {
            "resources": [], "preview_required": False, "reversible": True,
        },
    }


def _normed(rng: np.random.Generator) -> np.ndarray:
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _make_runner(
    tmp_path,
    bb: Blackboard,
    compositor: LocalCompositor,
    initial_spec: np.ndarray,
    label: str,
) -> tuple[AgentRunner, AgentIdentity, EpisodicMemory, SpecializationTracker]:
    seed, manifest = compositor.issue_agent(
        agent_type=f"worker-{label}",
        model_path="mock-model",
        fs_read_paths=["/tmp"],
        fs_write_paths=["/tmp"],
        attestation_tier=2,
    )
    ident = AgentIdentity(seed, manifest)
    mem = EpisodicMemory(
        agent_id=ident.agent_id,
        db_path=str(tmp_path / f"mem-{label}"),
    )
    spec = SpecializationTracker(
        agent_id=ident.agent_id,
        initial_embedding=initial_spec,
        db_path=str(tmp_path / f"spec-{label}.db"),
    )
    runner = AgentRunner(
        identity=ident,
        blackboard=bb,
        memory=mem,
        specialization=spec,
        lsh=LSHIndex(seed=7),
        executor=make_mock_executor(response=f"{label}-output"),
        min_reward_threshold=0.0,
        min_similarity_threshold=-1.0,  # accept anything for tests
        poll_interval_s=0.05,
    )
    return runner, ident, mem, spec


def _make_work_item(lineage_root: str, embedding: np.ndarray) -> WorkItem:
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=lineage_root,
        parent_id=None,
        description="run an experiment on input X",
        desc_embedding=embedding.astype(np.float32),
        reward=0.8,
        reward_updated_ns=time.time_ns(),
        required_tier=0,
        input_hashes=[],
        output_spec={"kind": "text"},
        streaming_ok=False,
        claimed_by=None,
        claimed_at_ns=None,
        claim_hlc_l=0,
        claim_hlc_c=0,
        claim_hlc_node="",
        completed_at_ns=None,
        output_hash=None,
        icp_envelope_hash=None,
        success=None,
        created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )


@pytest.fixture
def bb(tmp_path) -> Blackboard:
    return Blackboard(str(tmp_path / "bb.db"))


@pytest.fixture
def compositor(tmp_path) -> LocalCompositor:
    return LocalCompositor(key_path=str(tmp_path / "compositor.key"))


def test_two_runners_one_item_exactly_one_claims(tmp_path, bb, compositor):
    intent_id = bb.post_intent(_goal_spec(_intent("a")))
    rng = np.random.default_rng(0)
    target_emb = _normed(rng)

    bb.post_work_item(_make_work_item(intent_id, target_emb))

    # Both runners start with a different specialization than the work
    # item embedding so a successful update produces visible drift.
    # (If initial == task, the update rule (1-r)*cur + r*task is a no-op
    # mathematically.)
    initial_spec = _normed(np.random.default_rng(54321))
    r1, id1, mem1, spec1 = _make_runner(tmp_path, bb, compositor, initial_spec, "a")
    r2, id2, mem2, spec2 = _make_runner(tmp_path, bb, compositor, initial_spec, "b")

    initial_spec1 = spec1.current.copy()
    initial_spec2 = spec2.current.copy()

    # Sync barrier so both threads attempt their claim cycles concurrently.
    barrier = threading.Barrier(2)

    def go(runner):
        barrier.wait()
        runner.start()

    t1 = threading.Thread(target=go, args=(r1,))
    t2 = threading.Thread(target=go, args=(r2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Wait for the work item to be completed on the blackboard. Either
    # runner could win; we just need the item to be claimed and finished.
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        items = bb.get_by_lineage(intent_id)
        if items and items[0].completed_at_ns is not None:
            break
        time.sleep(0.05)

    r1.stop()
    r2.stop()

    items = bb.get_by_lineage(intent_id)
    assert len(items) == 1
    completed = items[0]
    assert completed.completed_at_ns is not None
    assert completed.success is True
    assert completed.claimed_by in (id1.agent_id, id2.agent_id)
    assert completed.icp_envelope_hash is not None
    assert completed.output_hash is not None

    # Exactly one runner should report completion, the other zero.
    counts = sorted([r1.completed_count, r2.completed_count])
    assert counts == [0, 1], f"expected (0, 1) completions, got {counts}"

    # Identify the winner and verify integrations on its side.
    winner = r1 if r1.completed_count == 1 else r2
    winner_id = id1 if winner is r1 else id2
    winner_mem = mem1 if winner is r1 else mem2
    winner_spec = spec1 if winner is r1 else spec2
    initial = initial_spec1 if winner is r1 else initial_spec2

    # ICP envelope on the winner exists and verifies under the winner's pubkey.
    env = winner._last_envelope
    assert env is not None
    assert verify_envelope(env, bytes.fromhex(winner_id.agent_id)) is True
    assert env.action_id == completed.id
    assert env.intent_id == intent_id
    assert env.output_hash == completed.output_hash

    # Episode written.
    winner_mem.flush()
    assert winner_mem.episode_count() == 1

    # Specialization drifted from initial.
    drifted = winner_spec.current
    assert not np.allclose(drifted, initial, atol=1e-6), (
        "winner's specialization vector did not drift after a successful task"
    )
    assert winner_spec.update_count == 1


def test_runner_completes_multiple_items(tmp_path, bb, compositor):
    """Smoke test: a single runner consumes a small queue end-to-end."""
    intent_id = bb.post_intent(_goal_spec(_intent("c")))
    rng = np.random.default_rng(1)
    target_emb = _normed(rng)

    for _ in range(3):
        bb.post_work_item(_make_work_item(intent_id, target_emb))

    runner, ident, mem, spec = _make_runner(
        tmp_path, bb, compositor, target_emb, "solo",
    )
    runner.start()

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        items = bb.get_by_lineage(intent_id)
        if all(i.completed_at_ns is not None for i in items):
            break
        time.sleep(0.05)
    runner.stop()

    items = bb.get_by_lineage(intent_id)
    assert len(items) == 3
    assert all(i.success is True for i in items)
    assert runner.completed_count == 3
    assert spec.update_count == 3

    # Each completed item should chain to the prior one via ICP linkage:
    # walk the agent's chain from the last envelope and confirm length.
    # (The runner only retains the most recent envelope; chain
    # reconstruction would require persisting envelopes — out of scope
    # for Phase 1.)
    assert runner._last_envelope is not None
    mem.flush()
    assert mem.episode_count() == 3


def test_runner_handles_executor_exception(tmp_path, bb, compositor):
    intent_id = bb.post_intent(_goal_spec(_intent("d")))
    rng = np.random.default_rng(2)
    target_emb = _normed(rng)
    bb.post_work_item(_make_work_item(intent_id, target_emb))

    seed, manifest = compositor.issue_agent(
        agent_type="failing", model_path="mock",
        fs_read_paths=[], fs_write_paths=[], attestation_tier=2,
    )
    ident = AgentIdentity(seed, manifest)
    mem = EpisodicMemory(ident.agent_id, db_path=str(tmp_path / "mem-fail"))
    spec = SpecializationTracker(
        ident.agent_id, target_emb, str(tmp_path / "spec-fail.db"),
    )

    def boom(_p, _c):
        raise RuntimeError("inference exploded")

    runner = AgentRunner(
        identity=ident,
        blackboard=bb,
        memory=mem,
        specialization=spec,
        lsh=LSHIndex(seed=7),
        executor=boom,
        min_reward_threshold=0.0,
        min_similarity_threshold=-1.0,
        poll_interval_s=0.05,
    )
    runner.start()

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if runner.completed_count >= 1:
            break
        time.sleep(0.05)
    runner.stop()

    items = bb.get_by_lineage(intent_id)
    assert len(items) == 1
    # New semantics: executor exception releases the claim instead of
    # marking the item complete. Episode + drift still record the failure.
    assert items[0].claimed_by is None
    assert items[0].completed_at_ns is None
    assert items[0].success is None
    assert runner.completed_count == 1
    assert spec.update_count == 1
