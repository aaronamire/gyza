"""
End-to-end tests for the DDIL partition scenario.

These pin the four claims the brief asks for:
  * an over-bound action is rejected DURING the partition (no quorum,
    no peers) by the real brick-3 gate;
  * post-heal state is byte-identical regardless of event arrival order
    and regardless of how long the partition lasted;
  * verify_chain passes on the merged history with zero loss;
  * verify_delegation proves bounds composed across the chain — and a
    laundered grant is caught (the keystone bites).

Tests pin ``sandbox_mode="construct"`` so enforcement records are
byte-stable across machines; the demo itself auto-detects bubblewrap.
"""
from __future__ import annotations

import random

from gyza.demo.coordination_plane import CoordinationState
from gyza.demo.ddil_partition import NODE_IDS, run_demo
from gyza.demo.gossip import GossipNode, Network, run_until_converged
from gyza.economy.delegation import (
    CapabilitySpec,
    DelegationHop,
    spec_from_manifest,
    verify_delegation,
)
from gyza.icp import verify_chain, verify_dag


def test_over_bound_action_rejected_during_partition():
    r = run_demo(verbose=False, sandbox_mode="construct")
    # The rogue 1024 MB action was refused against the 512 MB grant...
    assert r.over_bound_rejected
    assert "exceeds manifest budget" in r.over_bound_reason
    # ...and the refusal happened while the minority control plane was
    # paused (no quorum) — bounds held with zero connectivity.
    assert r.minority_control_paused
    assert r.majority_control_active


def test_verify_chain_on_merged_history_zero_loss():
    r = run_demo(verbose=False, sandbox_mode="construct")
    merged = r.node_states["n0"]
    assert len(merged) == 7  # nothing lost across the partition
    # Causal-spine view: the fork is still two linear, valid branches.
    chains = merged.linear_chains()
    assert len(chains) == 2
    for c in chains:
        ok, bad = verify_chain(c)
        assert ok, f"verify_chain broke at {bad}"
    # Both branches share the two pre-partition envelopes.
    prefix0 = {chains[0][0].action_id, chains[1][0].action_id}
    prefix1 = {chains[0][1].action_id, chains[1][1].action_id}
    assert prefix0 == {"W0-register-root-task"}
    assert prefix1 == {"W1-delegate-subtask"}


def test_full_provenance_dag_rejoins_fork_at_synthesis():
    # The fan-in unlock: data edges re-join the partition fork into one
    # DAG with a single root and a single leaf (the synthesis) — a shape
    # the linear chain structurally cannot represent.
    r = run_demo(verbose=False, sandbox_mode="construct")
    assert r.dag.valid, r.dag.reason
    assert len(r.dag.roots) == 1
    assert len(r.dag.leaves) == 1
    assert len(r.dag.topo_order) == 7
    leaf = r.node_states["n0"].get(r.dag.leaves[0])
    assert leaf.action_id == "W2-synthesize-results"
    root = r.node_states["n0"].get(r.dag.roots[0])
    assert root.action_id == "W0-register-root-task"
    # Independently re-derivable from the converged envelope set.
    again = verify_dag(r.envelopes, require_closed=True)
    assert again.valid
    assert [e.action_id for e in again.topo_order] == \
           [e.action_id for e in r.dag.topo_order]


def test_all_nodes_converge_identically():
    r = run_demo(verbose=False, sandbox_mode="construct")
    assert r.all_nodes_converged
    ref = r.node_states["n0"].canonical_bytes()
    for n in NODE_IDS:
        assert r.node_states[n].canonical_bytes() == ref


def test_post_heal_state_independent_of_arrival_order():
    # Same envelope set, scattered to random nodes in different orders,
    # must converge to byte-identical state (ordering is from ICP
    # linkage, never arrival/wall-clock).
    r = run_demo(verbose=False, sandbox_mode="construct")
    envs = r.envelopes

    def converge(seed: int) -> bytes:
        net = Network(NODE_IDS)
        nodes = [GossipNode(n, net) for n in NODE_IDS]
        for n in nodes:
            n.attach_peers(nodes)
        rng = random.Random(seed)
        for e in rng.sample(envs, len(envs)):
            rng.choice(nodes).record(e)
        run_until_converged(nodes)
        return nodes[0].state.canonical_bytes()

    results = {converge(s) for s in range(8)}
    assert len(results) == 1


def test_post_heal_state_independent_of_partition_duration():
    # Whether the partition lasted one gossip round or fifty, once
    # healed every node holds the same six envelopes.
    for rounds in (1, 2, 5, 50):
        r = run_demo(verbose=False, sandbox_mode="construct",
                     pre_heal_rounds=rounds)
        assert r.all_nodes_converged
        assert len(r.node_states["n0"]) == 7


def test_merge_associativity_on_real_scenario_envelopes():
    r = run_demo(verbose=False, sandbox_mode="construct")
    a = CoordinationState(); a.add_all(r.envelopes[:2])
    b = CoordinationState(); b.add_all(r.envelopes[2:4])
    c = CoordinationState(); c.add_all(r.envelopes[4:])
    left = CoordinationState.merge(CoordinationState.merge(a, b), c)
    right = CoordinationState.merge(a, CoordinationState.merge(b, c))
    assert left.canonical_bytes() == right.canonical_bytes()
    assert left.canonical_bytes() == r.converged_canonical


def test_verify_delegation_holds_on_scenario():
    r = run_demo(verbose=False, sandbox_mode="construct")
    ok, why = verify_delegation(r.delegation_hops)
    assert ok, why


def test_laundered_grant_is_caught_keystone():
    # The keystone: a subcontractor honestly inside its OWN manifest is
    # still rejected when that manifest is wider than what was delegated.
    r = run_demo(verbose=False, sandbox_mode="construct")
    coord_spec = spec_from_manifest(r.coordinator_manifest)
    # Delegated authority was 512 MB; forge a subcontractor manifest that
    # claims the full 1024 MB (laundering capability it was never granted).
    laundered = DelegationHop(
        agent_pubkey="11" * 32,
        manifest=CapabilitySpec(mem_cap=1024),       # wider than delegated
        enforcement=CapabilitySpec(mem_cap=1024),    # honestly within its (wide) manifest
        delegated=CapabilitySpec(mem_cap=512),       # but only 512 was granted
    )
    root = DelegationHop(
        agent_pubkey="22" * 32, manifest=coord_spec,
        enforcement=CapabilitySpec(mem_cap=512), delegated=None,
    )
    ok, why = verify_delegation([root, laundered])
    assert not ok
    assert "laundering" in why or "parent delegated" in why
