"""
End-to-end NetworkBlackboard ⇄ NetworkBlackboard cross-cluster
sync test.

Setup: two daemons (A, B) running gyza-netd, two NetworkBlackboard
instances each pointing at its own SQLite. Each blackboard is wired
to its daemon's GossipClient on the same project topic.

Verification: a post_intent + post_work_item on A's blackboard must
appear on B's blackboard via gossip within a deadline. A subsequent
try_claim on A must also propagate so B's local SQLite shows the
claim merged in via merge_claim_direct (LWW). And a complete on A
must propagate via merge_completion_direct.

Why this lives in its own file: the full path exercises the gossip
gRPC bridge, the libp2p mesh, the CRDT merge primitives, and the
HLC-recv ingress all at once. Failures here are usually integration
boundary issues (proto field names, JSON-encoded payloads,
embedding bytes) that don't show up in unit tests.
"""
from __future__ import annotations

import os
import secrets
import signal
import subprocess
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[1]
NETD_BIN = REPO_ROOT / "netd" / "bin" / "gyza-netd"

PROJECT_ID = "phase3-blackboard-gossip-test"


@pytest.fixture(scope="module")
def netd_binary() -> Path:
    if not NETD_BIN.exists():
        pytest.skip(f"gyza-netd binary not built at {NETD_BIN}")
    return NETD_BIN


def _boot(tmp_path: Path, name: str, netd_binary: Path) -> tuple:
    """Spawn one gyza-netd process. Returns (proc, sock_path, pubkey_hex)."""
    from gyza.network.netd_client import NetdClient

    seed_path = tmp_path / f"{name}.key"
    seed_path.write_bytes(secrets.token_bytes(32))
    os.chmod(seed_path, 0o600)
    sock_path = tmp_path / f"{name}.sock"

    proc = NetdClient.start_daemon(
            isolated=True,
        socket_path=str(sock_path),
        binary_path=str(netd_binary),
        key_path=str(seed_path),
        listen_port=0,
        log_level="info",
        startup_timeout_s=5.0,
    )
    with NetdClient(str(sock_path)) as c:
        info = c.get_node_info()
    return proc, sock_path, info


def _kill(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2.0)


def _intent_id(suffix: str) -> str:
    """Deterministic UUIDv4-shaped string."""
    d = suffix
    return f"{d*8}-{d*4}-4{d*3}-8{d*3}-{d*12}"


def _make_work_item(intent_id: str, *, embedding_seed: int = 0):
    from gyza.schema import EMBEDDING_DIM, WorkItem

    rng = np.random.default_rng(embedding_seed)
    emb = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    emb /= max(np.linalg.norm(emb), 1e-9)
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=intent_id,
        parent_id=None,
        description="cross-cluster test item",
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


def _wait_until(predicate, timeout_s: float = 10.0, poll_s: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def test_blackboard_gossip_cross_cluster_sync(netd_binary, tmp_path):
    """
    A posts intent + work item; B's blackboard mirrors them via gossip.
    A claims; B sees the claim. A completes; B sees the completion.
    """
    from gyza.network.netd_client import GossipClient, NetdClient
    from gyza.network.network_blackboard import NetworkBlackboard
    from gyza.schema import HLC

    procA, sockA, infoA = _boot(tmp_path, "A", netd_binary)
    procB, sockB, infoB = _boot(tmp_path, "B", netd_binary)

    bbA = NetworkBlackboard(str(tmp_path / "A.db"))
    bbB = NetworkBlackboard(str(tmp_path / "B.db"))

    gossipA = GossipClient(str(sockA))
    gossipB = GossipClient(str(sockB))

    try:
        # libp2p connect — required for gossipsub mesh formation.
        loopbackB = next(
            (m for m in infoB.listen_addrs
             if m.startswith("/ip4/127.0.0.1/")),
            None,
        )
        assert loopbackB is not None
        with NetdClient(str(sockA)) as ca:
            res = ca.connect_peer(f"{loopbackB}/p2p/{infoB.peer_id}")
            assert res.success, res.error

        # Both daemons join the same project topic. JoinProject is
        # idempotent on the daemon side.
        gossipA.join_project(PROJECT_ID)
        gossipB.join_project(PROJECT_ID)

        bbA.attach_gossip(gossipA, PROJECT_ID, node_id=infoA.compositor_pubkey)
        bbB.attach_gossip(gossipB, PROJECT_ID, node_id=infoB.compositor_pubkey)

        # Mesh formation grace — gossipsub heartbeat is 1s; 2 heartbeats
        # is enough for GRAFT/PRUNE to settle on a 2-node loopback mesh.
        time.sleep(2.0)

        # ===== Stage 1: post intent + item on A, expect B to mirror =====
        intent_id = _intent_id("a")
        bbA.post_intent({
            "intent_id": intent_id,
            "natural_text": "cross-cluster test",
            "category": "system_task",
            "actions": [],
            "authorization": {
                "resources": [],
                "preview_required": False,
                "reversible": True,
            },
        })
        wi = _make_work_item(intent_id, embedding_seed=42)
        assert bbA.post_work_item(wi)

        ok = _wait_until(lambda: len(bbB.get_by_lineage(intent_id)) > 0, timeout_s=8.0)
        assert ok, "B did not receive the work item via gossip"
        on_b = bbB.get_by_lineage(intent_id)[0]
        assert on_b.id == wi.id
        assert on_b.description == wi.description
        assert np.allclose(on_b.desc_embedding, wi.desc_embedding, atol=0.0)

        # ===== Stage 2: A claims; B's local row converges via LWW =====
        hlc_a = HLC(node_id=infoA.compositor_pubkey)
        assert bbA.try_claim(wi.id, "agent_on_A", hlc_a) is True

        ok = _wait_until(
            lambda: bbB.get_by_lineage(intent_id)[0].claimed_by == "agent_on_A",
            timeout_s=8.0,
        )
        assert ok, "B did not see A's claim via gossip"

        # ===== Stage 3: A completes; B's row marks completed =====
        bbA.complete_work_item(
            wi.id,
            output_hash="a" * 64,
            icp_envelope_hash="b" * 64,
            success=True,
            hlc=hlc_a,
        )
        ok = _wait_until(
            lambda: bbB.get_by_lineage(intent_id)[0].completed_at_ns is not None,
            timeout_s=8.0,
        )
        assert ok, "B did not see completion via gossip"
        on_b = bbB.get_by_lineage(intent_id)[0]
        assert on_b.success is True
        assert on_b.output_hash == "a" * 64
        assert on_b.icp_envelope_hash == "b" * 64
    finally:
        bbA.detach_gossip()
        bbB.detach_gossip()
        gossipA.close()
        gossipB.close()
        _kill(procA)
        _kill(procB)


def test_blackboard_gossip_lww_resolves_concurrent_claims(netd_binary, tmp_path):
    """
    Concurrency case: A and B independently claim the same work_item
    via try_claim before the gossip layer has propagated either claim.
    Both blackboards converge to the same winner — the one with the
    higher HLC tuple in lex order.

    We force the race by picking specific HLC values rather than letting
    HLC.now() handle it, so the winner is predictable and the test is
    deterministic.
    """
    from gyza.network.netd_client import GossipClient, NetdClient
    from gyza.network.network_blackboard import NetworkBlackboard

    procA, sockA, infoA = _boot(tmp_path, "A", netd_binary)
    procB, sockB, infoB = _boot(tmp_path, "B", netd_binary)

    bbA = NetworkBlackboard(str(tmp_path / "A.db"))
    bbB = NetworkBlackboard(str(tmp_path / "B.db"))
    gossipA = GossipClient(str(sockA))
    gossipB = GossipClient(str(sockB))

    try:
        loopbackB = next(
            m for m in infoB.listen_addrs if m.startswith("/ip4/127.0.0.1/")
        )
        with NetdClient(str(sockA)) as ca:
            res = ca.connect_peer(f"{loopbackB}/p2p/{infoB.peer_id}")
            assert res.success
        gossipA.join_project(PROJECT_ID)
        gossipB.join_project(PROJECT_ID)
        bbA.attach_gossip(gossipA, PROJECT_ID, node_id=infoA.compositor_pubkey)
        bbB.attach_gossip(gossipB, PROJECT_ID, node_id=infoB.compositor_pubkey)
        time.sleep(2.0)

        # Seed both blackboards with the same intent + item via gossip.
        intent_id = _intent_id("b")
        bbA.post_intent({
            "intent_id": intent_id,
            "natural_text": "concurrent claim race",
            "category": "system_task",
            "actions": [],
            "authorization": {
                "resources": [],
                "preview_required": False,
                "reversible": True,
            },
        })
        wi = _make_work_item(intent_id, embedding_seed=99)
        assert bbA.post_work_item(wi)
        assert _wait_until(
            lambda: len(bbB.get_by_lineage(intent_id)) > 0,
            timeout_s=8.0,
        )

        # Apply two claims directly via merge_claim_direct so we control
        # the HLC values precisely. A's claim has the strictly larger
        # HLC tuple → A wins by LWW after both clusters converge.
        bbA.merge_claim_direct(wi.id, "agent_A", hlc_l=10, hlc_c=0,
                               hlc_node=infoA.compositor_pubkey)
        bbB.merge_claim_direct(wi.id, "agent_B", hlc_l=5, hlc_c=0,
                               hlc_node=infoB.compositor_pubkey)

        # Now have each blackboard publish a claim delta carrying its
        # local HLC values. They cross. Each merges the remote claim and
        # converges to the larger HLC tuple.
        from gyza.network.netd_client import BlackboardDelta, ClaimUpdate
        gossipA.publish_delta(BlackboardDelta(
            project_id=PROJECT_ID,
            claim_updates=[ClaimUpdate(
                work_item_id=wi.id, agent_pubkey="agent_A",
                compositor_pubkey=infoA.compositor_pubkey,
                hlc_l=10, hlc_c=0, hlc_node=infoA.compositor_pubkey,
            )],
        ))
        gossipB.publish_delta(BlackboardDelta(
            project_id=PROJECT_ID,
            claim_updates=[ClaimUpdate(
                work_item_id=wi.id, agent_pubkey="agent_B",
                compositor_pubkey=infoB.compositor_pubkey,
                hlc_l=5, hlc_c=0, hlc_node=infoB.compositor_pubkey,
            )],
        ))

        ok = _wait_until(
            lambda: bbB.get_by_lineage(intent_id)[0].claimed_by == "agent_A",
            timeout_s=8.0,
        )
        assert ok, (
            "B did not converge to A (higher HLC) winner; got "
            f"{bbB.get_by_lineage(intent_id)[0].claimed_by!r}"
        )
        # A had the higher HLC locally; the lower-HLC delta from B
        # must NOT overwrite it.
        on_a = bbA.get_by_lineage(intent_id)[0]
        assert on_a.claimed_by == "agent_A"
    finally:
        bbA.detach_gossip()
        bbB.detach_gossip()
        gossipA.close()
        gossipB.close()
        _kill(procA)
        _kill(procB)


def test_gossip_topic_isolation(netd_binary, tmp_path):
    """
    Phase 3 Session 8 — work items posted to project A must not appear
    on a subscriber listening on project B. The daemon's gossipsub
    topic is per-project ("/gyza/project/{id}/blackboard"); each
    GossipClient.subscribe_deltas filters by joined topic. Without
    correct isolation, a multi-project node would leak intents
    between unrelated collaborations.

    Topology:
      Daemon A — joins project ALPHA, posts intent + work item
      Daemon B — joins project BETA only
    Expectation: B sees nothing on its blackboard within the deadline.

    We deliberately do NOT join project ALPHA on B. The libp2p
    pubsub layer routes messages only to nodes joined to the topic;
    if B's daemon never joins ALPHA, A's delta should never reach
    B's gossip subscriber.
    """
    from gyza.network.netd_client import GossipClient, NetdClient
    from gyza.network.network_blackboard import NetworkBlackboard

    procA, sockA, infoA = _boot(tmp_path, "A", netd_binary)
    procB, sockB, infoB = _boot(tmp_path, "B", netd_binary)

    bbA = NetworkBlackboard(str(tmp_path / "A.db"))
    bbB = NetworkBlackboard(str(tmp_path / "B.db"))
    gossipA = GossipClient(str(sockA))
    gossipB = GossipClient(str(sockB))

    PROJECT_A = "phase3-isolation-alpha"
    PROJECT_B = "phase3-isolation-beta"

    try:
        loopbackB = next(
            m for m in infoB.listen_addrs if m.startswith("/ip4/127.0.0.1/")
        )
        with NetdClient(str(sockA)) as ca:
            res = ca.connect_peer(f"{loopbackB}/p2p/{infoB.peer_id}")
            assert res.success

        # A joins ALPHA only; B joins BETA only.
        gossipA.join_project(PROJECT_A)
        gossipB.join_project(PROJECT_B)
        bbA.attach_gossip(gossipA, PROJECT_A, node_id=infoA.compositor_pubkey)
        bbB.attach_gossip(gossipB, PROJECT_B, node_id=infoB.compositor_pubkey)
        time.sleep(2.0)  # gossipsub heartbeat × 2

        intent_id = _intent_id("c")
        bbA.post_intent({
            "intent_id": intent_id,
            "natural_text": "topic isolation",
            "category": "system_task",
            "actions": [],
            "authorization": {
                "resources": [], "preview_required": False, "reversible": True,
            },
        })
        wi = _make_work_item(intent_id, embedding_seed=222)
        assert bbA.post_work_item(wi)

        # Wait briefly. Without isolation, a leak would land on B
        # within the standard ~2s gossipsub propagation window.
        time.sleep(3.0)

        # B's blackboard must NOT have the work item.
        on_b = bbB.get_by_lineage(intent_id)
        assert on_b == [], (
            f"gossip isolation broken — project ALPHA delta leaked "
            f"into project BETA subscriber. B has {len(on_b)} item(s) "
            f"with lineage_root={intent_id}."
        )
        # And ALPHA on A still has it (sanity).
        on_a = bbA.get_by_lineage(intent_id)
        assert len(on_a) == 1
    finally:
        bbA.detach_gossip()
        bbB.detach_gossip()
        gossipA.close()
        gossipB.close()
        _kill(procA)
        _kill(procB)
