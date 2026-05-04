"""
NetworkBlackboard — drop-in replacement for `Blackboard` that routes
writes through Raft consensus while serving reads from local SQLite.

The Phase-1 `Blackboard` already grew a `attach_raft()` hook and routes
writes through `_raft` when one is attached. This subclass formalizes
the cluster lifecycle: tracks `_cluster_mode`, exposes `cluster_status()`,
and adds a brief replication wait around the lineage-invariant check
in `post_work_item` so callers on a node that didn't author the intent
don't race the apply path.

Reads (`get_unclaimed`, `get_by_lineage`, `get_artifact`, …) stay 100%
local — Raft applies commits to local SQLite synchronously inside the
`@replicated` apply method, so the local replica is read-your-writes
consistent for any operation that returned to this node's caller.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from gyza.blackboard import Blackboard
from gyza.network.raft import GyzaRaftNode
from gyza.schema import HLC, WorkItem


LOG = logging.getLogger("gyza.network_blackboard")

_LINEAGE_REPLICATION_WAIT_S = 1.0
_LINEAGE_POLL_INTERVAL_S = 0.05


class NetworkBlackboard(Blackboard):
    def __init__(
        self,
        db_path: str,
        raft_node: GyzaRaftNode | None = None,
        local_fallback: bool = True,
    ):
        super().__init__(db_path)
        self._local_fallback = local_fallback
        self._cluster_mode = False
        if raft_node is not None:
            self.attach_raft(raft_node)

    def attach_raft(self, raft_node: GyzaRaftNode) -> None:
        super().attach_raft(raft_node)
        self._cluster_mode = True
        LOG.info(
            "[network_blackboard] entered cluster mode, leader: %s",
            raft_node.leader_addr(),
        )

    def detach_raft(self) -> None:
        """Drop back to local-only mode. Used by `GyzaCluster.leave()`."""
        self._raft = None
        self._cluster_mode = False
        LOG.info("[network_blackboard] left cluster, back to local mode")

    # ------------------------------------------------------------------
    # Writes — the parent class already routes through Raft when attached.
    # We only override `post_work_item` to add the replication wait around
    # the lineage check (the cross-node case where this node didn't post
    # the upstream intent itself).
    # ------------------------------------------------------------------

    def post_work_item(self, w: WorkItem) -> bool:
        if self._cluster_mode:
            self._wait_for_lineage(w.lineage_root)
        return super().post_work_item(w)

    def _wait_for_lineage(self, lineage_root: str) -> None:
        """Briefly poll for an intent that was posted on another node.

        post_intent's Raft call returns only after the local apply, so a
        same-node sequence doesn't need this wait. But when node A posts
        the intent and node B immediately posts a work item, B's local
        SQLite may not yet have caught up.
        """
        deadline = time.monotonic() + _LINEAGE_REPLICATION_WAIT_S
        while time.monotonic() < deadline:
            row = self._conn().execute(
                "SELECT 1 FROM human_intents WHERE intent_id=?",
                (lineage_root,),
            ).fetchone()
            if row is not None:
                return
            time.sleep(_LINEAGE_POLL_INTERVAL_S)
        # Out of patience — let post_work_item's own check raise the
        # ValueError. We don't pre-empt the contract here.

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def cluster_status(self) -> dict[str, Any]:
        if not self._cluster_mode or self._raft is None:
            return {"mode": "local", "cluster_size": 1}
        return {
            "mode": "cluster",
            "cluster_size": self._raft.cluster_size(),
            "is_leader": self._raft.is_leader(),
            "leader_addr": self._raft.leader_addr(),
            "applied_count": self._raft._applied_count,
        }


__all__ = ["NetworkBlackboard"]
