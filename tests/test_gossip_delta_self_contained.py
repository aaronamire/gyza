"""A work-item delta must carry its lineage intent.

WHY THIS EXISTS. Gossip does not retry. An intent published into a mesh that
has not finished GRAFTing is lost PERMANENTLY, and if work-item deltas ship
without the intent then every item under that lineage fails its foreign key on
the receiving board -- silently, because the delta ARRIVES and is rejected at
insert, surfacing as a log line rather than as a delivery error.

That was the live behaviour until 2026-08-29. The code carried a comment
promising that "a subsequent delta carrying the full state will heal once the
intent arrives", and no such delta was ever sent. Measured at 80 ms RTT:
0 of ~60 items delivered over 180 s, permanently.

The invariant is now enforced here rather than asserted in a comment.
See research/arenas/arena1_contested/FINDINGS_NETEM_SWEEP.md.
"""
from __future__ import annotations

import time
import uuid

import numpy as np
import pytest

from gyza.network.network_blackboard import NetworkBlackboard
from gyza.schema import EMBEDDING_DIM, WorkItem

PROJECT = "self-contained-delta-test"


class _RecordingGossip:
    """Captures published deltas. subscribe_deltas blocks forever so the
    apply thread parks instead of spinning."""

    def __init__(self) -> None:
        self.published: list = []

    def publish_delta(self, delta) -> None:
        self.published.append(delta)

    def subscribe_deltas(self, project_id):  # noqa: ARG002
        while True:
            time.sleep(3600)
            yield  # pragma: no cover

    def join_project(self, project_id):  # noqa: ARG002
        return 0

    def close(self) -> None:
        pass


def _item(lineage: str) -> WorkItem:
    e = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    e[0] = 1.0
    return WorkItem(
        id=str(uuid.uuid7()), lineage_root=lineage, parent_id=None,
        description="w", desc_embedding=e, reward=0.5,
        reward_updated_ns=time.time_ns(), required_tier=0, input_hashes=[],
        output_spec={"kind": "t"}, streaming_ok=False, claimed_by=None,
        claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(), ttl_ns=3600 * 10**9,
    )


@pytest.fixture()
def bb_and_gossip(tmp_path):
    bb = NetworkBlackboard(str(tmp_path / "bb.db"))
    g = _RecordingGossip()
    bb.attach_gossip(g, PROJECT, node_id="a" * 64)
    yield bb, g


def _intent_payload(intent_id: str) -> dict:
    return {
        "intent_id": intent_id, "natural_text": "t", "category": "system_task",
        "actions": [],
        "authorization": {"resources": [], "preview_required": False,
                          "reversible": True},
    }


def test_work_item_delta_carries_its_lineage_intent(bb_and_gossip):
    """The regression this file exists for."""
    bb, g = bb_and_gossip
    intent_id = bb.post_intent(_intent_payload(PROJECT))
    w = _item(intent_id)
    assert bb.post_work_item(w)

    item_deltas = [d for d in g.published if d.new_items]
    assert len(item_deltas) == 1, "expected exactly one work-item delta"
    d = item_deltas[0]

    ids = [i.intent_id for i in d.new_intents]
    assert intent_id in ids, (
        "work-item delta shipped WITHOUT its lineage intent; a receiver that "
        "missed the intent delta will reject this item on its foreign key, "
        "permanently and silently"
    )


def test_intent_record_is_faithful_not_just_present(bb_and_gossip):
    """Carrying a placeholder would satisfy the FK and lose the goal spec."""
    bb, g = bb_and_gossip
    intent_id = bb.post_intent(_intent_payload(PROJECT))
    bb.post_work_item(_item(intent_id))

    d = next(d for d in g.published if d.new_items)
    rec = next(i for i in d.new_intents if i.intent_id == intent_id)
    assert rec.goal_spec_json, "goal_spec_json must not be empty"
    assert rec.created_at_ns > 0, "created_at_ns must be a real timestamp"


def test_every_item_carries_it_not_only_the_first(bb_and_gossip):
    """The cache must not turn 'carried once' into 'carried once ever'.

    A receiver can miss ANY delta, so healing cannot depend on which item
    happened to be first.
    """
    bb, g = bb_and_gossip
    intent_id = bb.post_intent(_intent_payload(PROJECT))
    for _ in range(3):
        bb.post_work_item(_item(intent_id))

    item_deltas = [d for d in g.published if d.new_items]
    assert len(item_deltas) == 3
    for n, d in enumerate(item_deltas):
        assert any(i.intent_id == intent_id for i in d.new_intents), (
            f"work-item delta #{n} shipped without the lineage intent"
        )


def test_missing_intent_yields_no_record_rather_than_raising(tmp_path):
    """An item whose lineage has no local intent row must not crash the
    publish path. The FK makes this unreachable through post_work_item, so
    the accessor is exercised directly."""
    bb = NetworkBlackboard(str(tmp_path / "bb.db"))
    g = _RecordingGossip()
    bb.attach_gossip(g, PROJECT, node_id="b" * 64)
    assert bb._lineage_intent_records("no-such-lineage") == []
