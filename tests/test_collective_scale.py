"""
Tests for the scale + adversarial evaluation harness
(gyza.demo.collective_scale).

These assert the *properties* the harness is meant to measure hold —
convergence, full equivocation detection, honest-work preservation,
mission integrity — at small-but-nontrivial N, and that the metrics are
deterministic for a fixed seed.
"""
from __future__ import annotations

import pytest

from gyza.demo.collective_scale import MissionConfig, run_mission, sweep


def test_partitioned_byzantine_mission_stays_intact():
    m = run_mission(MissionConfig(
        n_agents=12, partition=(7, 5), byzantine_fraction=0.25, seed=1,
    ))
    # Convergence actually happened across the heal.
    assert m.scalability["all_converged"]
    # Every Byzantine agent equivocated and every one was caught.
    byz = m.resilience["byzantine_agents"]
    assert byz == 3  # round(0.25 * 12)
    assert m.resilience["equivocations_detected"] == byz
    assert m.resilience["quarantined_agents"] == byz
    # Honest work survived and the mission DAG is intact.
    assert m.resilience["mission_intact"]
    assert 0.0 < m.resilience["honest_fraction"] < 1.0
    # A partition genuinely diverged the sides before heal.
    assert m.adaptability["pre_heal_divergence"] > 0
    assert m.adaptability["recovery_rounds"] >= 1


def test_honest_collective_scores_full_resilience():
    m = run_mission(MissionConfig(n_agents=10, byzantine_fraction=0.0, seed=2))
    assert m.resilience["byzantine_agents"] == 0
    assert m.resilience["equivocations_detected"] == 0
    assert m.resilience["honest_fraction"] == 1.0
    assert m.resilience["mission_intact"]


def test_envelope_count_matches_composition():
    # 1 genesis + honest contributions (1 each) + byz contributions (2 each).
    m = run_mission(MissionConfig(
        n_agents=10, partition=(5, 5), byzantine_fraction=0.2, seed=3,
    ))
    byz = m.resilience["byzantine_agents"]
    honest_contributors = 10 - byz
    expected = 1 + honest_contributors + 2 * byz
    assert m.scalability["total_envelopes"] == expected


def test_metrics_are_deterministic_for_a_seed():
    cfg = MissionConfig(n_agents=20, partition=(12, 8),
                        byzantine_fraction=0.15, seed=7)
    a = run_mission(cfg)
    b = run_mission(cfg)
    # Counts (not key material) must be reproducible.
    assert a.scalability["gossip_rounds"] == b.scalability["gossip_rounds"]
    assert a.scalability["pull_contacts"] == b.scalability["pull_contacts"]
    assert a.scalability["total_envelopes"] == b.scalability["total_envelopes"]
    assert a.resilience["equivocations_detected"] == b.resilience["equivocations_detected"]
    assert a.resilience["honest_fraction"] == b.resilience["honest_fraction"]


def test_sweep_scales_and_stays_intact():
    results = sweep([8, 16, 32], byzantine_fraction=0.1, partition_ratio=0.5)
    assert [m.config["n_agents"] for m in results] == [8, 16, 32]
    for m in results:
        assert m.scalability["all_converged"]
        assert m.resilience["mission_intact"]
    # More agents ⇒ strictly more inter-agent messages (the O(N^2) cost
    # the harness is meant to surface honestly).
    msgs = [m.scalability["pull_contacts"] for m in results]
    assert msgs[0] < msgs[1] < msgs[2]


def test_bad_partition_is_rejected():
    with pytest.raises(ValueError):
        MissionConfig(n_agents=10, partition=(5, 4))  # sums to 9, not 10


# ----------------------------------------------------------------------
# Bounded-fanout epidemic gossip — correctness + the message-cost win
# ----------------------------------------------------------------------

def test_epidemic_converges_and_catches_all_byzantine():
    m = run_mission(MissionConfig(
        n_agents=40, partition=(24, 16), byzantine_fraction=0.1, seed=5,
        fanout=4,
    ))
    assert m.config["gossip"] == "epidemic(fanout=4)"
    assert m.scalability["all_converged"]           # exact fixpoint reached
    assert m.resilience["equivocations_detected"] == m.resilience["byzantine_agents"]
    assert m.resilience["mission_intact"]


def test_epidemic_uses_far_fewer_messages_than_all_pairs():
    cfg = dict(n_agents=60, partition=(30, 30), byzantine_fraction=0.1, seed=9)
    allpairs = run_mission(MissionConfig(**cfg, fanout=None))
    epidemic = run_mission(MissionConfig(**cfg, fanout=4))
    # Same result...
    assert allpairs.scalability["all_converged"]
    assert epidemic.scalability["all_converged"]
    assert epidemic.resilience["mission_intact"]
    # ...at a fraction of the message cost (the whole point of the fix).
    assert epidemic.scalability["pull_contacts"] < allpairs.scalability["pull_contacts"] / 3


def test_epidemic_metrics_are_deterministic_for_a_seed():
    cfg = MissionConfig(n_agents=30, partition=(18, 12),
                        byzantine_fraction=0.1, seed=11, fanout=3)
    a = run_mission(cfg)
    b = run_mission(cfg)
    assert a.scalability["gossip_rounds"] == b.scalability["gossip_rounds"]
    assert a.scalability["pull_contacts"] == b.scalability["pull_contacts"]
    assert a.resilience["honest_fraction"] == b.resilience["honest_fraction"]


def test_component_converged_predicate():
    from gyza.demo.gossip import GossipNode, Network, component_converged

    net = Network(["a", "b", "c", "d"])
    nodes = [GossipNode(i, net) for i in net._ids]
    for n in nodes:
        n.attach_peers(nodes)
    # Empty + fully connected → trivially converged.
    assert component_converged(nodes, net)

    # Partition, give one side an event the other lacks.
    net.partition(["a", "b"], ["c", "d"])
    from gyza.icp import ICPEnvelope
    env = ICPEnvelope(
        intent_id="i", action_id="x", agent_pubkey="00" * 32,
        capability_manifest_hash="00" * 32, input_hashes=["00" * 32],
        output_hash="11" * 32, parent_envelope_hash=None, timestamp_ns=1,
        inference_backend="m", model_identifier="m", duration_ms=0,
        tokens_in=0, tokens_out=0, signature="",
    )
    nodes[0].state.add(env)  # only 'a' has it; 'b' does not
    # 'a' and 'b' now disagree within their component → not converged.
    assert not component_converged(nodes, net)
