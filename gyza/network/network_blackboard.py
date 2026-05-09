"""
NetworkBlackboard — drop-in replacement for `Blackboard` that routes
writes through Raft consensus while serving reads from local SQLite.

The Phase-1 `Blackboard` already grew a `attach_raft()` hook and routes
writes through `_raft` when one is attached. This subclass formalizes
the cluster lifecycle: tracks `_cluster_mode`, exposes `cluster_status()`,
and adds a brief replication wait around the lineage-invariant check
in `post_work_item` so callers on a node that didn't author the intent
don't race the apply path.

Phase 3 Session 4 also adds `attach_gossip(client, project_id)` for
cross-cluster sync: a background thread consumes BlackboardDelta
messages from the gossip topic and applies them via the CRDT merge
primitives (post_intent_direct, post_work_item_direct, merge_claim_direct,
merge_completion_direct). Local writes additionally publish a delta to
the gossip topic so peers can converge.

Reads (`get_unclaimed`, `get_by_lineage`, `get_artifact`, …) stay 100%
local — Raft applies commits to local SQLite synchronously inside the
`@replicated` apply method, so the local replica is read-your-writes
consistent for any operation that returned to this node's caller.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

import numpy as np

from gyza.blackboard import Blackboard
from gyza.network.raft import GyzaRaftNode
from gyza.network.netd_client import (
    BlackboardDelta,
    ClaimUpdate,
    CompletionRecord,
    GossipClient,
    IntentRecord,
    WorkItemRecord,
)
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem


LOG = logging.getLogger("gyza.network_blackboard")


# Observability — fail-closed wrapper. Direction labels are "in"
# (received from gossip) and "out" (published to gossip). The tally
# is per-delta, not per-record-inside-the-delta, since the whole
# delta is the unit of mesh transport.
try:
    from gyza.observability import GOSSIP_DELTAS_TOTAL as _GOSSIP_DELTAS_TOTAL

    def _obs_delta(direction: str) -> None:
        _GOSSIP_DELTAS_TOTAL.labels(direction=direction).inc()
except Exception:  # noqa: BLE001
    def _obs_delta(direction: str) -> None:  # type: ignore[misc]
        pass

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
        # Gossip wiring is set lazily by attach_gossip — None means no
        # cross-cluster sync. We deliberately keep these as plain
        # attributes (not a sub-object) so post_work_item / try_claim /
        # complete_work_item can take the fast path with one None check.
        self._gossip: GossipClient | None = None
        self._gossip_project_id: str | None = None
        self._gossip_thread: threading.Thread | None = None
        self._gossip_stop = threading.Event()
        self._gossip_hlc: HLC | None = None
        # Free-rider filter: a callable taking the intent's creator
        # compositor pubkey and returning True to keep the item in
        # get_unclaimed results, False to hide it. Decoupled from the
        # ledger module so this class doesn't import economy code.
        self._free_rider_filter: Callable[[str], bool] | None = None
        # Lookup of intent_id → creator compositor pubkey, populated
        # when post_intent runs locally. Cross-cluster intents apply
        # via post_intent_direct which does not record creator —
        # that's a Phase 4 concern (intent provenance gossip).
        self._intent_creator: dict[str, str] = {}
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

    def post_intent(self, goal_spec: dict[str, Any]) -> str:
        intent_id = super().post_intent(goal_spec)
        # Record local creator so the free-rider filter has a creator
        # to attribute work items to. The local compositor signs the
        # intent — for now we conflate "local intent" with "this
        # node's compositor pubkey", which holds whenever the
        # NetworkBlackboard's gossip is attached and the gossip HLC
        # node_id is the local compositor pubkey.
        if self._gossip_hlc is not None:
            self._intent_creator[intent_id] = self._gossip_hlc.node_id
        # Publish the intent so peer clusters can satisfy the lineage
        # FK before any subsequent work_item delta arrives.
        if self._gossip is not None and self._gossip_project_id is not None:
            self._publish_delta_if_attached(BlackboardDelta(
                project_id=self._gossip_project_id,
                new_intents=[IntentRecord(
                    intent_id=intent_id,
                    goal_spec_json=json.dumps(goal_spec),
                    created_at_ns=time.time_ns(),
                )],
            ))
        return intent_id

    def post_work_item(self, w: WorkItem) -> bool:
        if self._cluster_mode:
            self._wait_for_lineage(w.lineage_root)
        result = super().post_work_item(w)
        if result and self._gossip is not None and self._gossip_project_id is not None:
            self._publish_delta_if_attached(BlackboardDelta(
                project_id=self._gossip_project_id,
                new_items=[_work_item_to_record(w)],
            ))
        return result

    def try_claim(self, work_item_id, agent_pubkey, hlc):
        # Bump the gossip-side HLC so cross-cluster total order
        # observes our claim. We use the agent's own HLC to drive the
        # claim (parent class semantics) but ALSO advance the gossip
        # HLC to keep its node-id slot fresh — this matters when a
        # remote cluster's HLC.recv() later sees our claim and decides
        # whether to ratchet forward.
        won = super().try_claim(work_item_id, agent_pubkey, hlc)
        if won and self._gossip is not None and self._gossip_project_id is not None:
            compositor_pubkey = (
                self._gossip_hlc.node_id if self._gossip_hlc is not None else ""
            )
            self._publish_delta_if_attached(BlackboardDelta(
                project_id=self._gossip_project_id,
                claim_updates=[ClaimUpdate(
                    work_item_id=work_item_id,
                    agent_pubkey=agent_pubkey,
                    compositor_pubkey=compositor_pubkey,
                    hlc_l=hlc.l,
                    hlc_c=hlc.c,
                    hlc_node=hlc.node_id,
                )],
            ))
        return won

    def complete_work_item(
        self,
        work_item_id: str,
        output_hash: str,
        icp_envelope_hash: str,
        success: bool,
        hlc: HLC,
    ) -> None:
        super().complete_work_item(
            work_item_id, output_hash, icp_envelope_hash, success, hlc,
        )
        if self._gossip is not None and self._gossip_project_id is not None:
            compositor_pubkey = (
                self._gossip_hlc.node_id if self._gossip_hlc is not None else ""
            )
            self._publish_delta_if_attached(BlackboardDelta(
                project_id=self._gossip_project_id,
                completions=[CompletionRecord(
                    work_item_id=work_item_id,
                    output_hash=output_hash,
                    icp_envelope_hash=icp_envelope_hash,
                    success=success,
                    completed_at_ns=time.time_ns(),
                    completed_by_compositor_pubkey=compositor_pubkey,
                )],
            ))

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
    # Catch-up
    # ------------------------------------------------------------------

    def wait_for_sync(self, timeout_s: float = 30.0) -> bool:
        """Block until this node has caught up to the cluster's committed
        log.

        After a network partition heals, the rejoining node still has a
        stale local SQLite even though the transport reports `connected`.
        Local-only signals (`isReady()`, `last_applied >= commit_idx`)
        can lie — a follower's commit_idx is a follower-side number and
        catches up to the leader's only after the leader sends another
        AppendEntries. The only sure signal is "submit a replicated
        no-op with sync=True and wait for it to apply HERE." Once that
        returns, every prior committed entry has also been applied on
        this node (pysyncobj applies in strict log order).

        Until that holds, this node MUST NOT accept new claims (it would
        try to claim items it doesn't yet know are taken).

        Returns True once the noop applies, False on timeout.
        """
        if not self._cluster_mode or self._raft is None:
            return True
        # First wait until there's a leader, otherwise the noop will
        # block on election anyway and burn most of the budget.
        leader_deadline = time.monotonic() + min(timeout_s, 10.0)
        while time.monotonic() < leader_deadline:
            try:
                if self._raft.leader_addr() is not None:
                    break
            except Exception:
                pass
            time.sleep(0.05)
        else:
            LOG.warning("[network_blackboard] wait_for_sync: no leader")
            return False

        token = time.time_ns()
        try:
            ret = self._raft.raft_noop(token, sync=True, timeout=timeout_s)
        except Exception as e:  # noqa: BLE001
            LOG.warning("[network_blackboard] wait_for_sync raft_noop failed: %s", e)
            return False
        return ret == token

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Free-rider filter — Phase 3 Session 6
    # ------------------------------------------------------------------

    def set_free_rider_filter(
        self,
        keep: Callable[[str], bool] | None,
    ) -> None:
        """
        Install a per-intent-creator filter applied to get_unclaimed.
        ``keep(creator_pubkey)`` returns True to keep items lineage'd
        to that creator, False to hide them. ``None`` disables filtering.

        The runner's typical usage:

            ledger = ComputeLedger(...)
            bb.set_free_rider_filter(
                lambda pk: ledger.free_rider_score(pk) <= 0.7
            )

        Filter is consulted on each get_unclaimed call. We don't cache
        — peer scores can move from "trusted" to "free-rider" mid-session
        as their debts age, and the filter must observe the current
        score, not a stale one.
        """
        self._free_rider_filter = keep

    def get_unclaimed(self, min_reward: float, tier: int) -> list[WorkItem]:
        items = super().get_unclaimed(min_reward, tier)
        f = self._free_rider_filter
        if f is None:
            return items
        # Items whose lineage_root creator is unknown locally bypass
        # the filter — refusing to claim work just because the local
        # node hasn't observed the originator is a strict failure mode
        # we'd rather avoid. The filter sees only items we have a
        # creator for.
        kept = []
        for w in items:
            creator = self._intent_creator.get(w.lineage_root)
            if creator is None:
                kept.append(w)
                continue
            try:
                if f(creator):
                    kept.append(w)
            except Exception as e:  # noqa: BLE001
                LOG.warning(
                    "[network_blackboard] free-rider filter raised on %s: %s",
                    creator[:16], e,
                )
                kept.append(w)
        return kept

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

    # ==================================================================
    # Cross-cluster gossip — Phase 3 Session 4
    # ==================================================================

    def attach_gossip(
        self,
        client: GossipClient,
        project_id: str,
        node_id: str,
    ) -> None:
        """
        Bind a GossipClient and start a background apply thread.

        Caller is responsible for ``client.join_project(project_id)``
        before attach. Once attached, every local mutation
        (post_intent / post_work_item / try_claim / complete_work_item)
        emits a single-mutation delta on the gossip topic, and remote
        deltas are applied via the CRDT merge primitives.

        ``node_id`` seeds the per-node HLC used for ingress merges.
        It must be globally unique within the project — use the
        compositor pubkey hex.

        KNOWN GAP — Phase 4 will need to fix:
            The gossip-side HLC (``self._gossip_hlc``) is advanced on
            ingress via ``HLC.recv()``, but local agents claim with
            their OWN per-agent HLC instances which do not observe
            the cross-cluster ratchet. A local claim issued strictly
            after a remote claim has been merged could produce an HLC
            tuple lex-smaller than the just-merged remote, breaking
            the cross-cluster total-order invariant. The fix is to
            have runners draw their HLC from ``bb.gossip_hlc()``
            when gossip is attached, so all local + remote claims
            participate in a single ratcheting clock per node.

            Phase 3 demos use a single agent per cluster and don't
            see this; cross-agent contention within one cluster
            stays Raft-consistent so the issue is bounded to the
            cross-cluster edge.
        """
        if self._gossip is not None:
            raise RuntimeError("gossip already attached to this blackboard")
        self._gossip = client
        self._gossip_project_id = project_id
        self._gossip_hlc = HLC(node_id=node_id)
        self._gossip_stop.clear()
        self._gossip_thread = threading.Thread(
            target=self._gossip_recv_loop,
            name=f"gyza-gossip-recv-{project_id[:16]}",
            daemon=True,
        )
        self._gossip_thread.start()
        LOG.info(
            "[network_blackboard] attached gossip to project %s (node_id=%s)",
            project_id, node_id,
        )

    def detach_gossip(self) -> None:
        """Stop the apply thread and release the gossip client reference.
        Idempotent. The caller still owns the GossipClient and is
        responsible for closing it / leaving the project topic."""
        if self._gossip is None:
            return
        self._gossip_stop.set()
        # Closing the client cancels the in-flight server-streaming RPC
        # so the recv loop's `for delta in subscribe_deltas(...)` exits.
        # We don't close the client here (caller owns it) — instead we
        # rely on _gossip_stop to short-circuit the apply loop.
        if self._gossip_thread is not None:
            self._gossip_thread.join(timeout=2.0)
        self._gossip = None
        self._gossip_project_id = None
        self._gossip_thread = None
        self._gossip_hlc = None
        LOG.info("[network_blackboard] detached gossip")

    def _gossip_recv_loop(self) -> None:
        assert self._gossip is not None
        assert self._gossip_project_id is not None
        try:
            for delta in self._gossip.subscribe_deltas([self._gossip_project_id]):
                if self._gossip_stop.is_set():
                    return
                try:
                    self._apply_delta(delta)
                except Exception as e:  # noqa: BLE001
                    # Apply failures must not crash the receive thread —
                    # one malformed delta should not poison the whole
                    # gossip stream. Log and continue.
                    LOG.warning("[gossip] apply failed: %s", e, exc_info=True)
        except Exception as e:  # noqa: BLE001
            if not self._gossip_stop.is_set():
                LOG.warning("[gossip] subscribe stream exited: %s", e)

    def _apply_delta(self, delta: BlackboardDelta) -> None:
        """
        Apply a remote delta to local state via the CRDT merge
        primitives. Order is fixed:

        1. New intents (idempotent INSERT OR IGNORE).
        2. New work items (FK on lineage_root requires step 1 first).
        3. Claim updates (LWW on (hlc_l, hlc_c, hlc_node)).
        4. Completions (monotonic — first writer wins).

        For each merged claim, advance the local gossip HLC so a
        subsequent local claim attempt produces a tuple lex-greater
        than the merged remote claim.
        """
        # Skip our own deltas — pubsub already filters self-loops on the
        # daemon side, but a slow round-trip or a daemon restart could
        # surface our own historical delta back to us.
        if (
            self._gossip_hlc is not None
            and delta.sender_compositor_pubkey == self._gossip_hlc.node_id
        ):
            return

        _obs_delta("in")

        for intent in delta.new_intents:
            self.post_intent_direct(
                intent.intent_id,
                intent.goal_spec_json,
                intent.created_at_ns,
            )
            # Attribute remote intents to the delta's stamped sender so
            # the free-rider filter has a creator pubkey for cross-cluster
            # work items. The daemon stamps sender_compositor_pubkey at
            # publish time and gossipsub forwards without re-stamping, so
            # this is the originator even after multi-hop forwarding.
            # Without this attribution the filter is a no-op for the case
            # it was actually designed to catch — peers whose work we'd
            # like to deprioritize.
            if delta.sender_compositor_pubkey:
                self._intent_creator.setdefault(
                    intent.intent_id, delta.sender_compositor_pubkey,
                )
        for record in delta.new_items:
            try:
                self.post_work_item_direct(_record_to_work_item(record))
            except Exception as e:  # noqa: BLE001
                # Most likely an FK failure (intent missing): a delta
                # may carry just the work-item update without re-asserting
                # the intent. We log; a subsequent delta carrying the
                # full state will heal once the intent arrives.
                LOG.warning(
                    "[gossip] post_work_item_direct(%s) failed: %s",
                    record.id, e,
                )
        for claim in delta.claim_updates:
            updated = self.merge_claim_direct(
                claim.work_item_id,
                claim.agent_pubkey,
                claim.hlc_l, claim.hlc_c, claim.hlc_node,
            )
            if updated and self._gossip_hlc is not None:
                # Advance the local HLC so future local claims have
                # tuples lex-greater than this merged remote claim.
                self._gossip_hlc.recv(claim.hlc_l, claim.hlc_c, claim.hlc_node)
        for completion in delta.completions:
            self.merge_completion_direct(
                completion.work_item_id,
                completion.output_hash,
                completion.icp_envelope_hash,
                completion.success,
                completion.completed_at_ns,
            )

    def gossip_hlc(self) -> HLC | None:
        """Expose the gossip-side HLC so the runner can use it for
        local claims that participate in the cross-cluster total order."""
        return self._gossip_hlc

    def _publish_delta_if_attached(self, delta: BlackboardDelta) -> None:
        """Best-effort publish — never fails the local write if gossip
        is unreachable. Daemon down should not stop local progress."""
        if self._gossip is None:
            return
        try:
            self._gossip.publish_delta(delta)
            _obs_delta("out")
        except Exception as e:  # noqa: BLE001
            LOG.warning("[gossip] publish failed: %s", e)


def _record_to_work_item(r: WorkItemRecord) -> WorkItem:
    """Convert a wire-format WorkItemRecord into the in-process
    WorkItem dataclass. Embeddings are validated for shape/dtype to
    catch corrupt deltas before they hit SQLite."""
    if len(r.desc_embedding_bytes) != EMBEDDING_DIM * 4:
        raise ValueError(
            f"desc_embedding bytes len={len(r.desc_embedding_bytes)} "
            f"!= {EMBEDDING_DIM * 4}"
        )
    embedding = np.frombuffer(r.desc_embedding_bytes, dtype="<f4").astype(np.float32)
    return WorkItem(
        id=r.id,
        lineage_root=r.lineage_root,
        parent_id=r.parent_id or None,
        description=r.description,
        desc_embedding=embedding,
        reward=r.reward,
        reward_updated_ns=r.reward_updated_ns,
        required_tier=r.required_tier,
        input_hashes=json.loads(r.input_hashes_json or "[]"),
        output_spec=json.loads(r.output_spec_json or "{}"),
        streaming_ok=r.streaming_ok,
        claimed_by=None,
        claimed_at_ns=None,
        claim_hlc_l=0,
        claim_hlc_c=0,
        claim_hlc_node="",
        completed_at_ns=None,
        output_hash=None,
        icp_envelope_hash=None,
        success=None,
        created_at_ns=r.created_at_ns,
        ttl_ns=r.ttl_ns,
    )


def _work_item_to_record(w: WorkItem) -> WorkItemRecord:
    """Inverse of _record_to_work_item."""
    return WorkItemRecord(
        id=w.id,
        lineage_root=w.lineage_root,
        parent_id=w.parent_id or "",
        description=w.description,
        desc_embedding_bytes=w.desc_embedding.astype("<f4").tobytes(),
        reward=w.reward,
        reward_updated_ns=w.reward_updated_ns,
        required_tier=w.required_tier,
        input_hashes_json=json.dumps(w.input_hashes),
        output_spec_json=json.dumps(w.output_spec),
        streaming_ok=w.streaming_ok,
        created_at_ns=w.created_at_ns,
        ttl_ns=w.ttl_ns,
    )


__all__ = ["NetworkBlackboard"]
