from __future__ import annotations

import socket
import threading
import time
import uuid

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.network.raft import GyzaRaftNode
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem


# Raft tests are real-network: pysyncobj uses TCP and there's no mock.
# Mark them integration so `pytest -m "not integration"` skips by default.
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


def _intent_id(suffix: str) -> str:
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


def _work_item(lineage_root: str, embedding: np.ndarray | None = None) -> WorkItem:
    if embedding is None:
        embedding = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=lineage_root,
        parent_id=None,
        description="raft test",
        desc_embedding=embedding.astype(np.float32),
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


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------

class _Cluster:
    def __init__(self, blackboards, nodes, identities):
        self.blackboards = blackboards
        self.nodes = nodes
        self.identities = identities

    def leader_index(self) -> int | None:
        for i, n in enumerate(self.nodes):
            if n.is_leader():
                return i
        return None

    def wait_leader(self, timeout=10.0) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            idx = self.leader_index()
            if idx is not None:
                return idx
            time.sleep(0.1)
        raise AssertionError("no leader elected within timeout")

    def shutdown(self):
        for n in self.nodes:
            try:
                n.destroy()
            except Exception:
                pass


def _build_cluster(tmp_path, n: int = 3) -> _Cluster:
    ports = [_free_tcp_port() for _ in range(n)]
    addrs = [f"127.0.0.1:{p}" for p in ports]

    bbs, nodes, idents = [], [], []
    for i in range(n):
        bb = Blackboard(str(tmp_path / f"bb-{i}.db"))
        ident = _identity(tmp_path, f"n{i}")
        partners = [a for j, a in enumerate(addrs) if j != i]
        node = GyzaRaftNode(
            self_addr=addrs[i],
            partner_addrs=partners,
            blackboard=bb,
            identity=ident,
            journal_dir=None,  # in-memory journal; see raft.py for why
        )
        bb.attach_raft(node)
        bbs.append(bb)
        nodes.append(node)
        idents.append(ident)
    return _Cluster(bbs, nodes, idents)


@pytest.fixture
def cluster(tmp_path):
    c = _build_cluster(tmp_path, 3)
    try:
        c.wait_leader(timeout=15.0)
        yield c
    finally:
        c.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_leader_election(cluster):
    leaders = [i for i, n in enumerate(cluster.nodes) if n.is_leader()]
    assert len(leaders) == 1, f"expected exactly one leader, got {leaders}"
    # Followers know who the leader is.
    leader_addr = cluster.nodes[leaders[0]].leader_addr()
    assert leader_addr is not None
    for i, n in enumerate(cluster.nodes):
        if i == leaders[0]:
            continue
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if n.leader_addr() == leader_addr:
                break
            time.sleep(0.1)
        assert n.leader_addr() == leader_addr, (
            f"follower {i} sees leader {n.leader_addr()}, expected {leader_addr}"
        )


def test_post_intent_replicates(cluster):
    intent_id = _intent_id("a")
    cluster.blackboards[0].post_intent(_goal_spec(intent_id))

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if all(
            bb._conn().execute(
                "SELECT 1 FROM human_intents WHERE intent_id=?", (intent_id,)
            ).fetchone() is not None
            for bb in cluster.blackboards
        ):
            return
        time.sleep(0.05)
    pytest.fail("intent did not replicate to all nodes")


@pytest.mark.parametrize("iteration", list(range(20)))
def test_concurrent_claim_exactly_once(tmp_path, iteration):
    """20 iterations of: 3 nodes simultaneously claim the same work item.
    Exactly one must win. No node may report it claimed by anyone other
    than the single winner."""
    c = _build_cluster(tmp_path, 3)
    try:
        c.wait_leader(timeout=15.0)
        intent_id = _intent_id("c")
        c.blackboards[0].post_intent(_goal_spec(intent_id))
        w = _work_item(intent_id)
        c.blackboards[0].post_work_item(w)

        # Make sure every node has the work item before the race.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if all(
                bb._conn().execute(
                    "SELECT 1 FROM work_items WHERE id=?", (w.id,)
                ).fetchone() is not None
                for bb in c.blackboards
            ):
                break
            time.sleep(0.05)
        else:
            pytest.fail("work item did not replicate before claim race")

        # 3 threads claim concurrently. Each thread uses its own HLC.
        results: list[bool] = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(3)

        def claim(idx: int):
            hlc = HLC(node_id=f"agent{idx}")
            barrier.wait()
            ok = c.blackboards[idx].try_claim(w.id, f"agent{idx}_pk", hlc)
            with results_lock:
                results.append(ok)

        threads = [
            threading.Thread(target=claim, args=(i,)) for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results) == 1, (
            f"iteration {iteration}: expected exactly 1 winner, got {results}"
        )

        # Every node sees the same single winner.
        deadline = time.monotonic() + 3.0
        winners: set[str] = set()
        while time.monotonic() < deadline:
            winners = {
                bb._conn().execute(
                    "SELECT claimed_by FROM work_items WHERE id=?", (w.id,)
                ).fetchone()["claimed_by"]
                for bb in c.blackboards
            }
            if None not in winners and len(winners) == 1:
                break
            time.sleep(0.05)
        assert len(winners) == 1 and None not in winners, (
            f"iteration {iteration}: divergent claim views {winners}"
        )
    finally:
        c.shutdown()


def test_completion_replicates(cluster):
    intent_id = _intent_id("d")
    cluster.blackboards[0].post_intent(_goal_spec(intent_id))
    w = _work_item(intent_id)
    cluster.blackboards[0].post_work_item(w)

    # Claim then complete via node 1 (index 1).
    hlc = HLC(node_id="agent")
    assert cluster.blackboards[1].try_claim(w.id, "winner_pk", hlc) is True
    cluster.blackboards[1].complete_work_item(
        w.id, output_hash="aa" * 32, icp_envelope_hash="bb" * 32,
        success=True, hlc=hlc,
    )

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        states = [
            bb._conn().execute(
                "SELECT completed_at_ns, success FROM work_items WHERE id=?",
                (w.id,),
            ).fetchone()
            for bb in cluster.blackboards
        ]
        if all(s is not None and s["completed_at_ns"] is not None for s in states):
            for s in states:
                assert s["success"] == 1
            return
        time.sleep(0.05)
    pytest.fail("completion did not replicate to all nodes")


def test_node_rejoin(tmp_path):
    """Stop node 3, post 5 items via node 1, restart node 3 with the same
    journal, verify it catches up via Raft AppendEntries."""
    ports = [_free_tcp_port() for _ in range(3)]
    addrs = [f"127.0.0.1:{p}" for p in ports]

    bbs, nodes, idents = [], [], []
    for i in range(3):
        bb = Blackboard(str(tmp_path / f"bb-{i}.db"))
        ident = _identity(tmp_path, f"r{i}")
        partners = [a for j, a in enumerate(addrs) if j != i]
        node = GyzaRaftNode(
            self_addr=addrs[i], partner_addrs=partners,
            blackboard=bb, identity=ident,
            journal_dir=None,
        )
        bb.attach_raft(node)
        bbs.append(bb); nodes.append(node); idents.append(ident)

    try:
        # Wait for initial leader election.
        deadline = time.monotonic() + 15.0
        leader_idx = None
        while time.monotonic() < deadline:
            for i, n in enumerate(nodes):
                if n.is_leader():
                    leader_idx = i
                    break
            if leader_idx is not None:
                break
            time.sleep(0.1)
        if leader_idx is None:
            pytest.fail("no initial leader")

        intent_id = _intent_id("e")
        bbs[0].post_intent(_goal_spec(intent_id))

        # Pick a follower to stop — keeps the leader alive so post_work_item
        # below doesn't race a re-election (LEADER_CHANGED → SyncObjException).
        # The test is about rejoin, not failover; the failover path has its
        # own dedicated test.
        stop_idx = next(i for i in range(3) if i != leader_idx and i != 0)

        nodes[stop_idx].destroy()
        time.sleep(0.5)

        # Post 5 work items via node 0 — must succeed with the remaining
        # 2-of-3 quorum.
        wids: list[str] = []
        for _ in range(5):
            w = _work_item(intent_id)
            bbs[0].post_work_item(w)
            wids.append(w.id)

        # Restart the stopped node with a fresh blackboard. With an
        # in-memory Raft journal the rejoiner has no local log and
        # catches up entirely via AppendEntries from the live peers.
        bbs[stop_idx] = Blackboard(str(tmp_path / f"bb-{stop_idx}.db"))
        bbs[stop_idx].attach_raft(None)
        new_node = GyzaRaftNode(
            self_addr=addrs[stop_idx],
            partner_addrs=[a for j, a in enumerate(addrs) if j != stop_idx],
            blackboard=bbs[stop_idx],
            identity=idents[stop_idx],
            journal_dir=None,
        )
        bbs[stop_idx].attach_raft(new_node)
        nodes[stop_idx] = new_node

        deadline = time.monotonic() + 15.0
        count = 0
        while time.monotonic() < deadline:
            count = bbs[stop_idx]._conn().execute(
                "SELECT COUNT(*) AS n FROM work_items WHERE lineage_root=?",
                (intent_id,),
            ).fetchone()["n"]
            if count == 5:
                return
            time.sleep(0.2)
        pytest.fail(f"rejoiner did not catch up; saw {count}/5 work items")
    finally:
        for n in nodes:
            try:
                n.destroy()
            except Exception:
                pass


def test_leader_failover(tmp_path):
    """Kill the current leader; a remaining node must become leader and
    accept a new write."""
    c = _build_cluster(tmp_path, 3)
    try:
        leader_idx = c.wait_leader(timeout=15.0)
        original_leader = c.nodes[leader_idx]

        # Tear down the leader.
        original_leader.destroy()

        # Within ~3-5s a new leader emerges among the survivors.
        deadline = time.monotonic() + 8.0
        new_leader_idx = None
        while time.monotonic() < deadline:
            for i, n in enumerate(c.nodes):
                if i == leader_idx:
                    continue
                if n.is_leader():
                    new_leader_idx = i
                    break
            if new_leader_idx is not None:
                break
            time.sleep(0.1)
        assert new_leader_idx is not None, "no successor leader"

        # New leader accepts a write.
        intent_id = _intent_id("f")
        c.blackboards[new_leader_idx].post_intent(_goal_spec(intent_id))
        w = _work_item(intent_id)
        c.blackboards[new_leader_idx].post_work_item(w)

        # Surviving follower sees the write.
        survivors = [i for i in range(3) if i not in (leader_idx,)]
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            present = c.blackboards[survivors[0]]._conn().execute(
                "SELECT 1 FROM work_items WHERE id=?", (w.id,),
            ).fetchone() is not None
            if present:
                return
            time.sleep(0.1)
        pytest.fail("post-failover write did not replicate")
    finally:
        c.shutdown()
