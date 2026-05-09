"""
Phase 3 Session 6 — free-rider filter on NetworkBlackboard.get_unclaimed.

Three behaviors to lock in:

1. With no filter installed, get_unclaimed returns every unclaimed item
   exactly as the parent Blackboard would (the override is invisible).

2. With a filter installed, items whose intent creator the filter
   rejects are hidden; items whose creator it accepts come through;
   items whose creator is unknown locally bypass the filter (we'd
   rather over-include than refuse work because we lack provenance —
   a strict deny would create a denial-of-service vector).

3. The remote-intent attribution path: when ``_apply_delta`` ingests
   an intent carried in a delta, the intent's creator is recorded as
   the delta's ``sender_compositor_pubkey``. Without this, the filter
   would only fire on locally-created intents — which the local node
   already trusts — making it a no-op for the case it was designed
   for. We exercise this without standing up the full gossip stack:
   _apply_delta is exposed as an instance method and we call it
   directly with a synthetic BlackboardDelta.

Why no daemon: the filter logic is pure Python + SQLite, separable
from libp2p / gRPC. The two-daemon gossip flow is covered by
test_network_blackboard_gossip.py — duplicating it here would slow
the suite without finding additional bugs.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import numpy as np

from gyza.network.netd_client import (
    BlackboardDelta,
    IntentRecord,
    WorkItemRecord,
)
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _bb(tmp_path: Path, name: str) -> NetworkBlackboard:
    return NetworkBlackboard(str(tmp_path / f"{name}.db"))


def _attach_pseudo_gossip_hlc(bb: NetworkBlackboard, node_id: str) -> None:
    """
    The free-rider filter attribution path keys off ``_gossip_hlc.node_id``
    in ``post_intent``. We don't want the full attach_gossip dance for
    these unit tests (no daemon) — just seed the HLC slot directly so
    post_intent records a creator pubkey.
    """
    bb._gossip_hlc = HLC(node_id=node_id)


def _post_intent(bb: NetworkBlackboard, intent_id: str) -> str:
    """Post a minimally-valid intent. The blackboard requires intent_id
    inside goal_spec; everything else is for the GoalSpec validator's
    happy path."""
    bb.post_intent({
        "intent_id": intent_id,
        "natural_text": "free-rider filter unit test",
        "category": "system_task",
        "actions": [],
        "authorization": {
            "resources": [],
            "preview_required": False,
            "reversible": True,
        },
    })
    return intent_id


def _mk_item(intent_id: str, *, seed: int) -> WorkItem:
    rng = np.random.default_rng(seed)
    emb = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    emb /= max(np.linalg.norm(emb), 1e-9)
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=intent_id,
        parent_id=None,
        description="filter unit test item",
        desc_embedding=emb,
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


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------

def test_no_filter_returns_all_items(tmp_path):
    """Default behavior: the override is a no-op when no filter set."""
    bb = _bb(tmp_path, "default")
    intent_id = "11111111-1111-4111-8111-111111111111"
    _post_intent(bb, intent_id)
    bb.post_work_item(_mk_item(intent_id, seed=1))
    bb.post_work_item(_mk_item(intent_id, seed=2))

    got = bb.get_unclaimed(min_reward=0.0, tier=0)
    assert len(got) == 2


def test_filter_hides_free_rider_creators(tmp_path):
    """
    Filter returning False for a creator hides every work item lineaged
    to that creator's intent. Work items lineaged to a trusted creator
    pass through.
    """
    bb = _bb(tmp_path, "filtered")
    me_pubkey = "aa" * 32
    free_rider_pubkey = "bb" * 32
    trusted_pubkey = "cc" * 32

    # We need _gossip_hlc for post_intent to record a creator. Use our
    # own pubkey first so the local-post path works.
    _attach_pseudo_gossip_hlc(bb, me_pubkey)

    # Intent created locally by us (creator == me_pubkey).
    self_intent = "22222222-2222-4222-8222-222222222222"
    _post_intent(bb, self_intent)

    # Manually set creators on two more intents: one from a free-rider
    # peer, one from a trusted peer. These represent intents that arrived
    # from gossip and were attributed via _apply_delta.
    free_rider_intent = "33333333-3333-4333-8333-333333333333"
    _post_intent(bb, free_rider_intent)
    bb._intent_creator[free_rider_intent] = free_rider_pubkey

    trusted_intent = "44444444-4444-4444-8444-444444444444"
    _post_intent(bb, trusted_intent)
    bb._intent_creator[trusted_intent] = trusted_pubkey

    bb.post_work_item(_mk_item(self_intent, seed=10))
    bb.post_work_item(_mk_item(free_rider_intent, seed=11))
    bb.post_work_item(_mk_item(trusted_intent, seed=12))

    # Filter rejects free_rider_pubkey only.
    bb.set_free_rider_filter(lambda pk: pk != free_rider_pubkey)

    got = bb.get_unclaimed(min_reward=0.0, tier=0)
    creators = [bb._intent_creator.get(w.lineage_root) for w in got]
    assert free_rider_pubkey not in creators, (
        "filter failed to hide free-rider's items"
    )
    assert me_pubkey in creators, "filter wrongly hid a self-authored item"
    assert trusted_pubkey in creators, "filter wrongly hid a trusted peer's item"
    assert len(got) == 2


def test_filter_unknown_creator_bypasses(tmp_path):
    """
    Items whose lineage_root has no recorded creator (we never observed
    the originating intent's provenance) bypass the filter — refusing
    to claim work because we lack provenance is too strict and creates
    a DoS vector. The filter only excludes items we have positive
    free-rider evidence on.
    """
    bb = _bb(tmp_path, "unknown")
    _attach_pseudo_gossip_hlc(bb, "aa" * 32)

    intent_with_creator = "55555555-5555-4555-8555-555555555555"
    intent_no_creator = "66666666-6666-4666-8666-666666666666"
    _post_intent(bb, intent_with_creator)
    _post_intent(bb, intent_no_creator)
    # Drop the auto-recorded creator for the second intent — this
    # simulates an intent that arrived through some path that didn't
    # carry provenance (older daemon, malformed delta).
    bb._intent_creator.pop(intent_no_creator, None)
    # Mark the first intent's creator as a free-rider.
    bb._intent_creator[intent_with_creator] = "ee" * 32

    bb.post_work_item(_mk_item(intent_with_creator, seed=20))
    bb.post_work_item(_mk_item(intent_no_creator, seed=21))

    bb.set_free_rider_filter(lambda _pk: False)  # reject everyone

    got = bb.get_unclaimed(min_reward=0.0, tier=0)
    # The known-creator item is filtered; the unknown-creator item passes.
    assert len(got) == 1
    assert got[0].lineage_root == intent_no_creator


def test_filter_exception_does_not_starve_queue(tmp_path):
    """
    A filter that raises must not nuke the unclaimed queue. The override
    catches and logs; the offending item passes through (fail-open). A
    runtime error in user-supplied filter code should degrade behavior,
    not shut down the agent.
    """
    bb = _bb(tmp_path, "exc")
    _attach_pseudo_gossip_hlc(bb, "aa" * 32)
    intent_id = "77777777-7777-4777-8777-777777777777"
    _post_intent(bb, intent_id)
    bb.post_work_item(_mk_item(intent_id, seed=30))

    def angry(_pk: str) -> bool:
        raise RuntimeError("filter exploded")

    bb.set_free_rider_filter(angry)

    got = bb.get_unclaimed(min_reward=0.0, tier=0)
    # Item is included despite the filter exception.
    assert len(got) == 1


def test_filter_disable_restores_full_queue(tmp_path):
    """Setting the filter back to None restores the unfiltered view."""
    bb = _bb(tmp_path, "toggle")
    _attach_pseudo_gossip_hlc(bb, "aa" * 32)
    intent_id = "88888888-8888-4888-8888-888888888888"
    _post_intent(bb, intent_id)
    bb._intent_creator[intent_id] = "ff" * 32
    bb.post_work_item(_mk_item(intent_id, seed=40))

    bb.set_free_rider_filter(lambda _pk: False)
    assert bb.get_unclaimed(min_reward=0.0, tier=0) == []

    bb.set_free_rider_filter(None)
    assert len(bb.get_unclaimed(min_reward=0.0, tier=0)) == 1


def test_apply_delta_attributes_remote_intent_to_sender(tmp_path):
    """
    The architectural fix: when a remote intent arrives via
    _apply_delta, its creator is recorded as the delta's sender. This
    makes the filter actually fire on free-rider peers' work items —
    the case it was designed for.

    Without standing up libp2p, we hand-build a BlackboardDelta whose
    sender_compositor_pubkey simulates a peer node, then call
    _apply_delta directly. The resulting _intent_creator entry must
    match the sender. The work item carried in the same delta then
    inherits that attribution via lineage_root.
    """
    bb = _bb(tmp_path, "apply")
    me_pubkey = "aa" * 32
    peer_pubkey = "bb" * 32
    _attach_pseudo_gossip_hlc(bb, me_pubkey)

    remote_intent_id = "99999999-9999-4999-8999-999999999999"
    rng = np.random.default_rng(50)
    emb = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    emb /= max(np.linalg.norm(emb), 1e-9)

    delta = BlackboardDelta(
        project_id="phase3-filter-attribution",
        sender_compositor_pubkey=peer_pubkey,
        sender_seq=1,
        timestamp_ns=time.time_ns(),
        new_intents=[IntentRecord(
            intent_id=remote_intent_id,
            goal_spec_json=json.dumps({
                "intent_id": remote_intent_id,
                "natural_text": "remote intent",
                "category": "system_task",
                "actions": [],
                "authorization": {
                    "resources": [],
                    "preview_required": False,
                    "reversible": True,
                },
            }),
            created_at_ns=time.time_ns(),
        )],
        new_items=[WorkItemRecord(
            id=str(uuid.uuid7()),
            lineage_root=remote_intent_id,
            parent_id="",
            description="remote work item",
            desc_embedding_bytes=emb.astype("<f4").tobytes(),
            reward=0.5,
            reward_updated_ns=time.time_ns(),
            required_tier=0,
            input_hashes_json="[]",
            output_spec_json="{}",
            streaming_ok=False,
            created_at_ns=time.time_ns(),
            ttl_ns=3600 * 1_000_000_000,
        )],
    )

    bb._apply_delta(delta)

    # Attribution: the intent was credited to the delta's sender.
    assert bb._intent_creator.get(remote_intent_id) == peer_pubkey

    # Filter that hates that peer hides the remote work item.
    bb.set_free_rider_filter(lambda pk: pk != peer_pubkey)
    got = bb.get_unclaimed(min_reward=0.0, tier=0)
    assert got == [], "remote work item from filtered peer leaked through"

    # Filter that accepts the peer lets it through.
    bb.set_free_rider_filter(lambda _pk: True)
    got = bb.get_unclaimed(min_reward=0.0, tier=0)
    assert len(got) == 1
    assert got[0].lineage_root == remote_intent_id


def test_apply_delta_self_loop_skipped(tmp_path):
    """
    The receive loop already short-circuits deltas whose sender pubkey
    matches our own gossip HLC node_id. This test guards that invariant
    so a future refactor doesn't strip it — without the skip, a node
    that loses and re-receives its own delta (e.g. via gossipsub mesh
    re-formation after a transient disconnect) would record itself as
    the creator of every remote intent.
    """
    bb = _bb(tmp_path, "selfloop")
    me_pubkey = "aa" * 32
    _attach_pseudo_gossip_hlc(bb, me_pubkey)

    intent_id = "abababab-abab-4bab-8bab-ababababab01"
    delta = BlackboardDelta(
        project_id="phase3-filter-selfloop",
        sender_compositor_pubkey=me_pubkey,  # ← us
        new_intents=[IntentRecord(
            intent_id=intent_id,
            goal_spec_json=json.dumps({
                "intent_id": intent_id,
                "natural_text": "self loopback",
                "category": "system_task",
                "actions": [],
                "authorization": {
                    "resources": [], "preview_required": False, "reversible": True,
                },
            }),
            created_at_ns=time.time_ns(),
        )],
    )
    bb._apply_delta(delta)
    # Nothing was applied — no intent and no creator entry.
    row = bb._conn().execute(
        "SELECT 1 FROM human_intents WHERE intent_id=?", (intent_id,),
    ).fetchone()
    assert row is None
    assert intent_id not in bb._intent_creator
