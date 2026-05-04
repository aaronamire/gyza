from __future__ import annotations

import threading
import time
import uuid

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.reward import current_reward, refresh_rewards
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem


def _intent_id(suffix: str = "1") -> str:
    # GoalSpec requires UUID v4. Construct deterministic v4-shaped strings
    # from a digit so each test gets a fresh lineage root.
    d = suffix * 1
    return f"{d*8}-{d*4}-4{d*3}-8{d*3}-{d*12}"


def _goal_spec(intent_id: str) -> dict:
    return {
        "intent_id": intent_id,
        "natural_text": "test intent",
        "category": "system_task",
        "actions": [],
        "authorization": {
            "resources": [],
            "preview_required": False,
            "reversible": True,
        },
    }


def _work_item(lineage_root: str, **overrides) -> WorkItem:
    base = dict(
        id=str(uuid.uuid7()),
        lineage_root=lineage_root,
        parent_id=None,
        description="test work item",
        desc_embedding=np.zeros(EMBEDDING_DIM, dtype=np.float32),
        reward=0.5,
        reward_updated_ns=time.time_ns(),
        required_tier=0,
        input_hashes=[],
        output_spec={"kind": "test"},
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
    base.update(overrides)
    return WorkItem(**base)


@pytest.fixture
def bb(tmp_path):
    return Blackboard(str(tmp_path / "bb.db"))


def test_post_work_item_rejects_unknown_lineage(bb):
    w = _work_item("00000000-0000-4000-8000-000000000000")
    with pytest.raises(ValueError):
        bb.post_work_item(w)


def test_post_work_item_accepts_registered_lineage(bb):
    intent_id = bb.post_intent(_goal_spec(_intent_id("a")))
    assert bb.post_work_item(_work_item(intent_id)) is True
    items = bb.get_by_lineage(intent_id)
    assert len(items) == 1


def test_concurrent_claim_exactly_one_winner(bb):
    intent_id = bb.post_intent(_goal_spec(_intent_id("b")))
    w = _work_item(intent_id)
    bb.post_work_item(w)

    barrier = threading.Barrier(2)
    results: list[bool] = []
    lock = threading.Lock()

    def claim(agent_key: str) -> None:
        hlc = HLC(node_id=agent_key)
        barrier.wait()
        ok = bb.try_claim(w.id, agent_key, hlc)
        with lock:
            results.append(ok)

    t1 = threading.Thread(target=claim, args=("agentA",))
    t2 = threading.Thread(target=claim, args=("agentB",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sum(results) == 1, f"expected exactly one winner, got {results}"

    # And the row reflects exactly one claimer.
    fresh = bb.get_by_lineage(intent_id)[0]
    assert fresh.claimed_by in ("agentA", "agentB")
    assert fresh.claimed_at_ns is not None


def test_reward_inflation_60s():
    # 60s = 2 half-lives at 30s/halflife. base 0.3 → 0.3 * 4 = 1.2 → cap 1.0.
    sixty_s_ago = time.time_ns() - 60 * 1_000_000_000
    assert current_reward(0.3, sixty_s_ago) >= 1.0


def test_refresh_rewards_updates_drifted(bb):
    intent_id = bb.post_intent(_goal_spec(_intent_id("c")))
    # Item created with reward 0.1 and a 60s-old reward_updated_ns: should
    # inflate well past the 5% drift threshold.
    stale = _work_item(
        intent_id,
        reward=0.1,
        reward_updated_ns=time.time_ns() - 60 * 1_000_000_000,
    )
    bb.post_work_item(stale)

    n = refresh_rewards(bb)
    assert n == 1

    refreshed = bb.get_by_lineage(intent_id)[0]
    assert refreshed.reward > 0.1


def test_complete_work_item_sets_fields(bb):
    intent_id = bb.post_intent(_goal_spec(_intent_id("d")))
    w = _work_item(intent_id)
    bb.post_work_item(w)

    hlc = HLC(node_id="agent1")
    assert bb.try_claim(w.id, "agent1", hlc) is True

    out_hash = "a" * 64
    env_hash = "b" * 64
    bb.complete_work_item(w.id, out_hash, env_hash, True, hlc)

    item = [i for i in bb.get_by_lineage(intent_id) if i.id == w.id][0]
    assert item.completed_at_ns is not None
    assert item.output_hash == out_hash
    assert item.icp_envelope_hash == env_hash
    assert item.success is True
    assert item.claimed_by == "agent1"
    assert item.claim_hlc_node == "agent1"
    assert item.claim_hlc_l > 0


def test_hlc_monotonic_under_clock_freeze(monkeypatch):
    # Pin physical time so we can verify the counter advances even when
    # wall time hasn't moved — Kulkarni's tie-break case.
    fixed = 1_700_000_000_000
    monkeypatch.setattr("gyza.schema._pt_ms", lambda: fixed)

    h = HLC(node_id="n")
    a = h.now()
    b = h.now()
    c = h.now()
    assert a == (fixed, 0, "n")
    assert b == (fixed, 1, "n")
    assert c == (fixed, 2, "n")


def test_hlc_recv_advances_from_remote():
    h = HLC(node_id="local")
    h.recv(l=10**14, c=5, node="remote")  # far-future remote l
    assert h.l == 10**14
    assert h.c == 6  # remote l won, so c = c_m + 1


def test_artifact_roundtrip(bb):
    from gyza.schema import Artifact

    a = Artifact(
        hash="c" * 64,
        data=b"hello world",
        signature="d" * 128,
        signer_pubkey="e" * 64,
        parent_hashes=["f" * 64],
        timestamp_ns=time.time_ns(),
    )
    bb.store_artifact(a)
    got = bb.get_artifact(a.hash)
    assert got is not None
    assert got.data == a.data
    assert got.parent_hashes == ["f" * 64]
