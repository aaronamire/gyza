"""
Raft-replicated blackboard for Gyza Phase 2.

Three operations need distributed consensus across the cluster:
  - posting an intent (lineage anchor)
  - posting a work item
  - claiming a work item (exactly-once across all nodes)
  - completing a work item (visible to all nodes)

Everything else — get_unclaimed, get_artifact, lineage queries — is a
pure local read on this node's SQLite copy of the replicated state.

Implementation rests on `pysyncobj`. Every @replicated method below
runs on the leader, gets log-replicated to a quorum, and is then
applied by every node in identical order. The apply step calls the
matching `_direct` Blackboard method, which mutates local SQLite
without re-entering Raft. Raft proves what happened; SQLite stores it.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
from pysyncobj import SyncObj, SyncObjConf, replicated

from gyza.identity import AgentIdentity
from gyza.schema import WorkItem


LOG = logging.getLogger("gyza.raft")


# ---------------------------------------------------------------------------
# WorkItem ↔ JSON-safe dict (numpy arrays don't survive json.dumps)
# ---------------------------------------------------------------------------

def work_item_to_dict(w: WorkItem) -> dict:
    return {
        "id": w.id,
        "lineage_root": w.lineage_root,
        "parent_id": w.parent_id,
        "description": w.description,
        "desc_embedding": w.desc_embedding.astype(np.float32).tolist(),
        "reward": w.reward,
        "reward_updated_ns": w.reward_updated_ns,
        "required_tier": w.required_tier,
        "input_hashes": list(w.input_hashes),
        "output_spec": dict(w.output_spec),
        "streaming_ok": bool(w.streaming_ok),
        "claimed_by": w.claimed_by,
        "claimed_at_ns": w.claimed_at_ns,
        "claim_hlc_l": w.claim_hlc_l,
        "claim_hlc_c": w.claim_hlc_c,
        "claim_hlc_node": w.claim_hlc_node,
        "completed_at_ns": w.completed_at_ns,
        "output_hash": w.output_hash,
        "icp_envelope_hash": w.icp_envelope_hash,
        "success": w.success,
        "created_at_ns": w.created_at_ns,
        "ttl_ns": w.ttl_ns,
    }


def work_item_from_dict(d: dict) -> WorkItem:
    return WorkItem(
        id=d["id"],
        lineage_root=d["lineage_root"],
        parent_id=d.get("parent_id"),
        description=d["description"],
        desc_embedding=np.asarray(d["desc_embedding"], dtype=np.float32),
        reward=float(d["reward"]),
        reward_updated_ns=int(d["reward_updated_ns"]),
        required_tier=int(d["required_tier"]),
        input_hashes=list(d.get("input_hashes", [])),
        output_spec=dict(d.get("output_spec", {})),
        streaming_ok=bool(d["streaming_ok"]),
        claimed_by=d.get("claimed_by"),
        claimed_at_ns=d.get("claimed_at_ns"),
        claim_hlc_l=int(d.get("claim_hlc_l", 0)),
        claim_hlc_c=int(d.get("claim_hlc_c", 0)),
        claim_hlc_node=str(d.get("claim_hlc_node", "")),
        completed_at_ns=d.get("completed_at_ns"),
        output_hash=d.get("output_hash"),
        icp_envelope_hash=d.get("icp_envelope_hash"),
        success=d.get("success"),
        created_at_ns=int(d["created_at_ns"]),
        ttl_ns=int(d["ttl_ns"]),
    )


# ---------------------------------------------------------------------------
# GyzaRaftNode
# ---------------------------------------------------------------------------

class GyzaRaftNode(SyncObj):
    """
    Raft-replicated state machine wrapping a local Blackboard.

    Construct with the cluster topology (this node's address + every
    other node's address) and a Blackboard. Call `blackboard.attach_raft(node)`
    so writes route through this object.

    Threading: pysyncobj runs Raft I/O on its own thread (autoTick).
    @replicated methods called with `sync=True` block the calling
    thread until the entry is committed AND applied locally — the
    return value is whatever this node's apply produced.
    """

    def __init__(
        self,
        self_addr: str,
        partner_addrs: list[str],
        blackboard: Any,
        identity: AgentIdentity,
        journal_dir: str | None = None,
    ):
        # journal_dir=None → in-memory journal. pysyncobj's mmap-backed
        # file journal mis-sizes its region for our log entries (work
        # items carry a 1.5 KB float32 embedding) and intermittently
        # IndexErrors on slice assignment. Memory-only journals avoid
        # that path entirely; a restarted node still catches up via
        # AppendEntries from a live peer's in-memory log.
        journal_file: str | None = None
        if journal_dir is not None:
            Path(journal_dir).mkdir(parents=True, exist_ok=True)
            journal_file = os.path.join(
                journal_dir,
                f"raft_{self_addr.replace(':', '_')}.journal",
            )

        conf = SyncObjConf(
            autoTick=True,
            appendEntriesPeriod=0.1,
            raftMinTimeout=0.5,
            raftMaxTimeout=1.0,
            journalFile=journal_file,
        )

        super().__init__(self_addr, partner_addrs, conf)
        self._blackboard = blackboard
        self._identity = identity
        self._applied_count = 0

    # ------------------------------------------------------------------
    # Replicated state-machine entries
    # ------------------------------------------------------------------

    @replicated
    def raft_post_intent(
        self,
        intent_id: str,
        goal_spec_json: str,
        created_at_ns: int,
        submitter_pubkey: str,
    ) -> None:
        self._blackboard.post_intent_direct(
            intent_id, goal_spec_json, created_at_ns,
        )
        self._applied_count += 1

    @replicated
    def raft_post_work_item(
        self,
        work_item_dict: dict,
        submitter_pubkey: str,
    ) -> None:
        w = work_item_from_dict(work_item_dict)
        self._blackboard.post_work_item_direct(w)
        self._applied_count += 1

    @replicated
    def raft_claim_work_item(
        self,
        work_item_id: str,
        agent_pubkey: str,
        hlc_l: int,
        hlc_c: int,
        hlc_node: str,
        claimer_compositor_pubkey: str,
    ) -> bool:
        """
        Exactly-once claim across the cluster.

        Concurrent calls from multiple nodes line up in Raft log order;
        each apply runs `try_claim_direct`, which checks that the work
        item is still unclaimed before flipping it. The first apply
        succeeds; every subsequent apply for the same item sees
        `claimed_by` already set and returns False. Each calling node
        receives only its own apply's return value.
        """
        ok = self._blackboard.try_claim_direct(
            work_item_id, agent_pubkey, hlc_l, hlc_c, hlc_node,
        )
        self._applied_count += 1
        return ok

    @replicated
    def raft_complete_work_item(
        self,
        work_item_id: str,
        output_hash: str,
        icp_envelope_hash: str,
        success: bool,
        completed_at_ns: int,
        completer_pubkey: str,
    ) -> None:
        self._blackboard.complete_work_item_direct(
            work_item_id, output_hash, icp_envelope_hash,
            success, completed_at_ns,
        )
        self._applied_count += 1

    # ------------------------------------------------------------------
    # Introspection helpers (public)
    # ------------------------------------------------------------------

    def is_leader(self) -> bool:
        try:
            status = self.getStatus()
        except Exception:
            return False
        leader = status.get("leader")
        me = status.get("self")
        if leader is None or me is None:
            return False
        return str(leader) == str(me)

    def leader_addr(self) -> str | None:
        try:
            status = self.getStatus()
        except Exception:
            return None
        leader = status.get("leader")
        return str(leader) if leader is not None else None

    def cluster_size(self) -> int:
        return len(self.otherNodes) + 1

    def wait_committed(self, timeout_s: float = 5.0) -> bool:
        """Block until this node has caught up to the cluster."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if self.isReady():
                    return True
            except Exception:
                pass
            time.sleep(0.05)
        return False

    def wait_leader(self, timeout_s: float = 5.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.leader_addr() is not None:
                return True
            time.sleep(0.05)
        return False


__all__ = [
    "GyzaRaftNode",
    "work_item_to_dict",
    "work_item_from_dict",
]
