"""
Quorum-gating (control plane) and partition-isolation (gossip) tests.

These assert the CAP split directly:
  * the control plane pauses on the minority side and keeps authority
    on the majority side (quorum intersection), and
  * the data plane converges within a partition but not across it,
    then closes the gap on heal.
"""
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.demo.control_plane import ControlPlane, QuorumError
from gyza.demo.gossip import GossipNode, Network, run_until_converged
from gyza.icp import ICPSigner, compute_envelope_hash


IDS = ["n0", "n1", "n2", "n3", "n4"]


def _mk_env(tag: int):
    seed = bytes([tag % 251 + 1]) * 32
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pk = sk.public_key().public_bytes_raw().hex()
    return ICPSigner(seed, pk, "00" * 32).sign_action(
        "i", f"a{tag}", ["00" * 32], f"{tag:064x}", None,
        "mock", "mock", 0, 0, 0,
    )


# ----------------------------------------------------------------------
# Control plane
# ----------------------------------------------------------------------

def test_full_cluster_has_quorum():
    net = Network(IDS)
    assert net.majority() == 3
    for nid in IDS:
        assert ControlPlane(nid, net).has_quorum()


def test_minority_loses_quorum_majority_keeps_it():
    net = Network(IDS)
    net.partition(["n0", "n1", "n2"], ["n3", "n4"])
    majority = [ControlPlane(n, net) for n in ("n0", "n1", "n2")]
    minority = [ControlPlane(n, net) for n in ("n3", "n4")]
    assert all(cp.has_quorum() for cp in majority)
    assert not any(cp.has_quorum() for cp in minority)


def test_issue_grant_blocked_on_minority_allowed_on_majority():
    net = Network(IDS)
    net.partition(["n0", "n1", "n2"], ["n3", "n4"])

    maj = ControlPlane("n0", net)
    assert maj.issue_grant(lambda: "GRANT") == "GRANT"

    minr = ControlPlane("n3", net)
    with pytest.raises(QuorumError):
        minr.issue_grant(lambda: "GRANT")


def test_produce_callback_not_invoked_without_quorum():
    # The signing callback must never run on the minority side — a grant
    # that is never minted cannot leak.
    net = Network(IDS)
    net.partition(["n0", "n1", "n2"], ["n3", "n4"])
    calls = []
    minr = ControlPlane("n4", net)
    with pytest.raises(QuorumError):
        minr.issue_grant(lambda: calls.append(1))
    assert calls == []


def test_quorum_restored_after_heal():
    net = Network(IDS)
    net.partition(["n0", "n1", "n2"], ["n3", "n4"])
    minr = ControlPlane("n3", net)
    assert not minr.has_quorum()
    net.heal()
    assert minr.has_quorum()
    assert minr.issue_grant(lambda: "ok") == "ok"


# ----------------------------------------------------------------------
# Gossip / data plane
# ----------------------------------------------------------------------

def _build_cluster():
    net = Network(IDS)
    nodes = [GossipNode(n, net) for n in IDS]
    for n in nodes:
        n.attach_peers(nodes)
    return net, nodes


def test_gossip_converges_within_partition_not_across():
    net, nodes = _build_cluster()
    net.partition(["n0", "n1", "n2"], ["n3", "n4"])

    maj_env = _mk_env(100)
    minr_env = _mk_env(200)
    nodes[0].record(maj_env)   # n0 on majority side
    nodes[3].record(minr_env)  # n3 on minority side

    run_until_converged(nodes)

    maj_h = compute_envelope_hash(maj_env)
    minr_h = compute_envelope_hash(minr_env)

    # Majority side shares maj_env among itself, never sees minr_env.
    for i in (0, 1, 2):
        assert maj_h in nodes[i].state
        assert minr_h not in nodes[i].state
    # Minority side shares minr_env, never sees maj_env.
    for i in (3, 4):
        assert minr_h in nodes[i].state
        assert maj_h not in nodes[i].state


def test_gossip_closes_gap_after_heal():
    net, nodes = _build_cluster()
    net.partition(["n0", "n1", "n2"], ["n3", "n4"])
    nodes[0].record(_mk_env(100))
    nodes[3].record(_mk_env(200))
    run_until_converged(nodes)

    net.heal()
    run_until_converged(nodes)

    # Every node now holds the union of both events.
    full = nodes[0].state.event_hashes()
    assert len(full) == 2
    for n in nodes:
        assert n.state.event_hashes() == full
