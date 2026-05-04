from __future__ import annotations

import socket
import threading
import time
import uuid

import numpy as np
import pytest

from gyza.identity import AgentIdentity, LocalCompositor
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.network.raft import GyzaRaftNode
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem


# Real Raft over TCP; integration only.
pytestmark = pytest.mark.integration


def _free_tcp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _identity(tmp_path, label: str) -> AgentIdentity:
    compositor = LocalCompositor(key_path=str(tmp_path / f"comp-{label}.key"))
    seed, manifest = compositor.issue_agent(
        agent_type=label, model_path="mock",
        fs_read_paths=[], fs_write_paths=[], attestation_tier=1,
    )
    return AgentIdentity(seed, manifest)


def _intent_id(c: str) -> str:
    return f"{c*8}-{c*4}-4{c*3}-8{c*3}-{c*12}"


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


def _work_item(lineage_root: str) -> WorkItem:
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=lineage_root,
        parent_id=None,
        description="test",
        desc_embedding=np.zeros(EMBEDDING_DIM, dtype=np.float32),
        reward=0.5,
        reward_updated_ns=time.time_ns(),
        required_tier=0,
        input_hashes=[],
        output_spec={},
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


class _TwoNodeCluster:
    def __init__(self, blackboards, raft_nodes):
        self.bbs = blackboards
        self.nodes = raft_nodes

    def shutdown(self):
        for n in self.nodes:
            try:
                n.destroy()
            except Exception:
                pass


def _build_two_node_cluster(tmp_path) -> _TwoNodeCluster:
    ports = [_free_tcp_port() for _ in range(2)]
    addrs = [f"127.0.0.1:{p}" for p in ports]

    bbs: list[NetworkBlackboard] = []
    nodes: list[GyzaRaftNode] = []
    for i in range(2):
        ident = _identity(tmp_path, f"n{i}")
        bb = NetworkBlackboard(db_path=str(tmp_path / f"bb-{i}.db"))
        partners = [a for j, a in enumerate(addrs) if j != i]
        node = GyzaRaftNode(
            self_addr=addrs[i], partner_addrs=partners,
            blackboard=bb, identity=ident, journal_dir=None,
        )
        bb.attach_raft(node)
        bbs.append(bb)
        nodes.append(node)

    # Wait for leader election.
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if any(n.is_leader() for n in nodes):
            return _TwoNodeCluster(bbs, nodes)
        time.sleep(0.1)
    for n in nodes:
        try: n.destroy()
        except Exception: pass
    raise AssertionError("no leader elected")


@pytest.fixture
def cluster(tmp_path):
    c = _build_two_node_cluster(tmp_path)
    try:
        yield c
    finally:
        c.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_post_intent_visible_on_both_nodes(cluster):
    intent_id = _intent_id("a")
    cluster.bbs[0].post_intent(_goal_spec(intent_id))

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if all(
            bb._conn().execute(
                "SELECT 1 FROM human_intents WHERE intent_id=?", (intent_id,)
            ).fetchone() is not None
            for bb in cluster.bbs
        ):
            return
        time.sleep(0.05)
    pytest.fail("intent did not replicate to both nodes")


def test_completion_visible_cross_node(cluster):
    intent_id = _intent_id("c")
    cluster.bbs[0].post_intent(_goal_spec(intent_id))
    w = _work_item(intent_id)
    cluster.bbs[0].post_work_item(w)

    # Node B claims and completes.
    hlc = HLC(node_id="agentB")
    assert cluster.bbs[1].try_claim(w.id, "agentB_pk", hlc) is True
    cluster.bbs[1].complete_work_item(
        w.id, "aa" * 32, "bb" * 32, success=True, hlc=hlc,
    )

    # Node A sees the completion.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        row = cluster.bbs[0]._conn().execute(
            "SELECT completed_at_ns, success FROM work_items WHERE id=?",
            (w.id,),
        ).fetchone()
        if row is not None and row["completed_at_ns"] is not None:
            assert row["success"] == 1
            return
        time.sleep(0.05)
    pytest.fail("completion did not replicate to node A")


def test_local_fallback(tmp_path):
    """Without a Raft node, NetworkBlackboard behaves as a local Blackboard."""
    bb = NetworkBlackboard(db_path=str(tmp_path / "bb.db"))
    assert bb.cluster_status() == {"mode": "local", "cluster_size": 1}

    intent_id = bb.post_intent(_goal_spec(_intent_id("d")))
    w = _work_item(intent_id)
    assert bb.post_work_item(w) is True

    hlc = HLC(node_id="solo")
    assert bb.try_claim(w.id, "agent_pk", hlc) is True

    bb.complete_work_item(w.id, "aa" * 32, "bb" * 32, success=True, hlc=hlc)
    items = bb.get_by_lineage(intent_id)
    assert len(items) == 1
    assert items[0].completed_at_ns is not None
    assert items[0].success is True


def test_cluster_status(cluster):
    statuses = [bb.cluster_status() for bb in cluster.bbs]
    for s in statuses:
        assert s["mode"] == "cluster"
        assert s["cluster_size"] == 2
        assert "leader_addr" in s
        assert "applied_count" in s
    leaders = sum(1 for s in statuses if s.get("is_leader"))
    assert leaders == 1, f"expected one leader, got {leaders}"


@pytest.mark.parametrize("iteration", list(range(100)))
def test_claim_exactly_once_across_nodes(tmp_path, iteration):
    """Both nodes simultaneously try to claim the same item.
    Exactly one must win. 100 iterations, zero double-claims."""
    c = _build_two_node_cluster(tmp_path)
    try:
        intent_id = _intent_id("e")
        c.bbs[0].post_intent(_goal_spec(intent_id))
        w = _work_item(intent_id)
        c.bbs[0].post_work_item(w)

        # Wait for both nodes to see the item.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if all(
                bb._conn().execute(
                    "SELECT 1 FROM work_items WHERE id=?", (w.id,)
                ).fetchone() is not None
                for bb in c.bbs
            ):
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"iter {iteration}: work item didn't replicate")

        results: list[bool] = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(2)

        def claim(idx: int):
            hlc = HLC(node_id=f"agent{idx}")
            barrier.wait()
            ok = c.bbs[idx].try_claim(w.id, f"agent{idx}_pk", hlc)
            with results_lock:
                results.append(ok)

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results) == 1, (
            f"iter {iteration}: expected 1 winner, got {results}"
        )

        # Both nodes converge on the same single winner.
        deadline = time.monotonic() + 3.0
        winners: set = set()
        while time.monotonic() < deadline:
            winners = {
                bb._conn().execute(
                    "SELECT claimed_by FROM work_items WHERE id=?", (w.id,)
                ).fetchone()["claimed_by"]
                for bb in c.bbs
            }
            if None not in winners and len(winners) == 1:
                break
            time.sleep(0.02)
        assert len(winners) == 1 and None not in winners, (
            f"iter {iteration}: divergent winners {winners}"
        )
    finally:
        c.shutdown()
