"""
Control plane — quorum-gated grant authority (the CP half of the split).

THE ARCHITECTURAL CORRECTION THIS EMBODIES
------------------------------------------
Raft alone halts on partition: without a reachable majority it stops
accepting writes. For a DDIL deployment that is *fatal* if the whole
system runs on Raft — the network would go dark whenever it is most
needed. The correction is to run two planes with different CAP
tradeoffs:

  * CONTROL PLANE (here): trust-root membership and capability-grant
    authority. Linearizable, CP. It *may legitimately pause* under
    loss of quorum — and pausing grant authority under partition is
    the *safe* behavior, because issuing new authority you cannot
    replicate to a majority is how split-brain authority leaks.

  * DATA PLANE (``gossip`` + ``coordination_plane``): already-
    authorized work-item state. AP. Stays available under partition,
    reconciles on heal.

WHY THIS IS A FAITHFUL RAFT MODEL, NOT A TOGGLE
-----------------------------------------------
The decision to commit is the genuine quorum-intersection rule that
Raft's safety is *derived from*: a write commits iff the proposer can
reach a strict majority of the full cluster. Two disjoint partitions
can never both contain a majority (their majorities would have to
share a node), so at most one side can hold authority. We compute that
predicate directly against the shared ``Network`` rather than
hardcoding "minority refuses" — the asymmetry (majority keeps
authority, minority pauses) *emerges* from the arithmetic.

This component is shaped like a thin ``GyzaRaftNode`` (propose →
quorum-gate → commit) so that wiring the production
``gyza.network.raft.GyzaRaftNode`` in as the real control plane later
is a localized change, not a rewrite. What it deliberately does *not*
model — log replication mechanics, leader election timing, durable
journals — is irrelevant to the single invariant the DDIL story turns
on: no new authority without a quorum.
"""
from __future__ import annotations

from typing import Callable, TypeVar

from gyza.demo.gossip import Network

T = TypeVar("T")


class QuorumError(RuntimeError):
    """Raised when a control-plane write is attempted without a quorum."""


class ControlPlane:
    """
    A node's view of grant-issuing authority, gated on reachable quorum.
    """

    def __init__(self, node_id: str, network: Network) -> None:
        self.node_id = node_id
        self._net = network

    def has_quorum(self) -> bool:
        return len(self._net.reachable(self.node_id)) >= self._net.majority()

    def quorum_status(self) -> "tuple[bool, str]":
        """``(ok, human_readable_reason)`` — used by the demo trace."""
        reachable = len(self._net.reachable(self.node_id))
        need = self._net.majority()
        size = self._net.cluster_size()
        if reachable >= need:
            return True, (
                f"reachable {reachable}/{size} ≥ quorum {need} — "
                f"authority retained"
            )
        return False, (
            f"reachable {reachable}/{size} < quorum {need} — NO QUORUM, "
            f"grant authority paused"
        )

    def issue_grant(self, produce: Callable[[], T]) -> T:
        """
        Commit a control-plane write (issue a capability grant) iff this
        node currently holds a quorum. ``produce`` is the (real) signing
        callback — it is invoked ONLY after the quorum check passes, so a
        minority partition never even mints the grant.

        Raises ``QuorumError`` if there is no quorum. The caller decides
        whether that is fatal (it is not, for the demo — it is the
        *expected* safe pause on the minority side).
        """
        ok, why = self.quorum_status()
        if not ok:
            raise QuorumError(why)
        return produce()


__all__ = ["ControlPlane", "QuorumError"]
