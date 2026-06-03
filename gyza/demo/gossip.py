"""
In-process anti-entropy gossip over the CRDT coordination plane.

This is the data-plane transport: a deliberately small epidemic
protocol that pulls missing events from reachable peers. It has no
coordinator and no leader — every node runs the same loop.

The ``Network`` object is the one place partitions live. A partition
is a set of disjoint groups; a node can only reach peers in its own
group. During a partition, gossip therefore converges *within* each
side but not across; on heal, the next rounds close the gap. The same
``Network`` is consulted by the control plane (``gyza.demo
.control_plane``) to decide quorum, so both planes see one coherent
view of connectivity.

Convergence model: gossip here is *pull-based* anti-entropy. One round
pulls, from each reachable peer, every event the local replica is
missing. Because the underlying CRDT is a join-semilattice (see
``coordination_plane``), repeated rounds are monotone and reach a
fixpoint — the union over the connected component — regardless of the
order nodes are visited.
"""
from __future__ import annotations

from gyza.demo.coordination_plane import CoordinationState
from gyza.icp import ICPEnvelope


class Network:
    """
    Shared connectivity + partition state for an in-process cluster.

    Fully connected at construction. ``partition`` splits the nodes
    into disjoint groups; ``heal`` restores the single group. Quorum
    arithmetic (``majority``) is computed against the *full* cluster
    size — that is what makes a minority partition unable to commit.
    """

    def __init__(self, node_ids: "list[str]") -> None:
        self._ids: list[str] = list(node_ids)
        self._groups: list[set[str]] = [set(self._ids)]

    def reachable(self, node_id: str) -> "set[str]":
        """The set of nodes ``node_id`` can currently reach (incl. self)."""
        for g in self._groups:
            if node_id in g:
                return set(g)
        return {node_id}

    def can_reach(self, a: str, b: str) -> bool:
        return b in self.reachable(a)

    def partition(self, *groups: "list[str] | set[str]") -> None:
        """Install a partition. ``groups`` must cover every node exactly once."""
        flat: list[str] = []
        for g in groups:
            flat.extend(g)
        if sorted(flat) != sorted(self._ids):
            raise ValueError(
                "partition groups must be a disjoint cover of all node ids"
            )
        self._groups = [set(g) for g in groups]

    def heal(self) -> None:
        self._groups = [set(self._ids)]

    def cluster_size(self) -> int:
        return len(self._ids)

    def majority(self) -> int:
        """Raft quorum: a strict majority of the full cluster."""
        return len(self._ids) // 2 + 1

    def group_of(self, node_id: str) -> "set[str]":
        return self.reachable(node_id)


class GossipNode:
    """
    One node's data-plane endpoint: a CRDT replica plus an anti-entropy
    pull loop over its reachable peers.
    """

    def __init__(self, node_id: str, network: Network) -> None:
        self.node_id = node_id
        self._net = network
        self.state = CoordinationState()
        self._peers: dict[str, "GossipNode"] = {}

    def attach_peers(self, peers: "list[GossipNode]") -> None:
        """Register the full node set (including self — self is skipped)."""
        for p in peers:
            self._peers[p.node_id] = p

    def record(self, envelope: ICPEnvelope) -> str:
        """Locally append a signed envelope (a data-plane write)."""
        return self.state.add(envelope)

    def pull_round(self) -> int:
        """
        One anti-entropy round: pull every locally-missing event from
        each reachable peer. Returns how many new events were absorbed.
        """
        gained = 0
        for pid, peer in self._peers.items():
            if pid == self.node_id:
                continue
            if not self._net.can_reach(self.node_id, pid):
                continue
            missing = peer.state.event_hashes() - self.state.event_hashes()
            for h in missing:
                env = peer.state.get(h)
                if env is not None:
                    self.state.add(env)
                    gained += 1
        return gained


def run_until_converged(
    nodes: "list[GossipNode]", *, max_rounds: int = 50
) -> int:
    """
    Drive anti-entropy across ``nodes`` until a fixpoint (no node gains
    a new event in a full sweep) or ``max_rounds`` is hit. Returns the
    number of rounds run. Within a connected component every node ends
    holding the union of that component's events.
    """
    for r in range(1, max_rounds + 1):
        total = sum(n.pull_round() for n in nodes)
        if total == 0:
            return r
    return max_rounds


__all__ = ["Network", "GossipNode", "run_until_converged"]
