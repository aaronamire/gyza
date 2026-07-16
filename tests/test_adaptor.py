"""
Tests for the local adaptor (gyza.adaptor.AgentAdaptor).

The adaptor is Gyza's answer to DICE's "local adaptor": wrap any
heterogeneous agent behind a bounded, attributable, DDIL-survivable
coordination endpoint. These tests exercise the three properties that
matter for a decentralized collective — trust lineage (signed,
chainable envelopes), authority boundaries (refuse-to-sign when
enforcement exceeds the manifest), and recoverability (envelopes
propagate and reconcile across a partition) — plus heterogeneity
(different agents interoperate through identical envelopes).
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile

import pytest

from gyza.adaptor import AgentAdaptor, BoundsViolation
from gyza.icp import verify_chain, verify_envelope
from gyza.identity import LocalCompositor


# ----------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------

@pytest.fixture()
def compositor():
    with tempfile.TemporaryDirectory() as d:
        key_path = os.path.join(d, "compositor.key")
        with open(key_path, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(key_path, 0o600)
        yield LocalCompositor(key_path=key_path)


def _bwrap_enforcement(memory_mb: int) -> dict:
    """
    A host-stamped enforcement record shaped like the real one
    (gyza/sandbox/executor.py) — an enforcing bubblewrap backend with a
    memory cap. Used to exercise the bounds gate without needing bwrap
    installed on the test host; the gate we assert against is the real
    enforcement_satisfies_manifest.
    """
    return {
        "backend": "bubblewrap",
        "ro_paths": [],
        "rw_paths": [],
        "requires_network": False,
        "max_memory_mb": memory_mb,
        "max_cpu_seconds": 300,
        "timeout_s": 300,
    }


def _echo_agent(prompt: str, context) -> str:
    return f"echo:{prompt}"


def _upper_agent(prompt: str, context) -> str:
    return prompt.upper()


# ----------------------------------------------------------------------
# Trust lineage — signed, verifiable, chainable envelopes
# ----------------------------------------------------------------------

def test_act_produces_verifiable_envelope(compositor):
    adaptor = AgentAdaptor.from_compositor(
        compositor, _echo_agent, agent_type="worker", memory_limit_mb=512,
    )
    env = adaptor.act(intent_id="i", action_id="a1", prompt="hello")

    assert env.agent_pubkey == adaptor.pubkey_hex
    assert env.capability_manifest_hash == adaptor.manifest_hash
    assert verify_envelope(env, bytes.fromhex(adaptor.pubkey_hex))
    ok, _ = verify_chain([env])
    assert ok


def test_actions_chain_by_parent(compositor):
    adaptor = AgentAdaptor.from_compositor(
        compositor, _echo_agent, agent_type="worker", memory_limit_mb=512,
    )
    e1 = adaptor.act(intent_id="i", action_id="a1", prompt="one")
    e2 = adaptor.act(intent_id="i", action_id="a2", prompt="two", parent=e1)

    from gyza.icp import compute_envelope_hash
    assert e2.parent_envelope_hash == compute_envelope_hash(e1)
    ok, _ = verify_chain([e1, e2])
    assert ok


def test_output_hash_commits_to_agent_text(compositor):
    adaptor = AgentAdaptor.from_compositor(
        compositor, _echo_agent, agent_type="worker", memory_limit_mb=512,
    )
    env = adaptor.act(intent_id="i", action_id="a1", prompt="payload")
    artifact = adaptor.artifact(env.output_hash)
    assert artifact is not None
    assert json.loads(artifact)["text"] == "echo:payload"


# ----------------------------------------------------------------------
# Authority boundaries — the refuse-to-sign gate
# ----------------------------------------------------------------------

def test_within_bounds_signs_and_commits_enforcement(compositor):
    adaptor = AgentAdaptor.from_compositor(
        compositor, _echo_agent, agent_type="worker", memory_limit_mb=512,
    )
    env = adaptor.act(
        intent_id="i", action_id="a1", prompt="x",
        enforcement=_bwrap_enforcement(512),
    )
    # The signed artifact commits to the enforcement record (bounds-proof).
    artifact = adaptor.artifact(env.output_hash)
    assert json.loads(artifact)["__enforcement__"]["max_memory_mb"] == 512


def test_over_bound_action_is_refused(compositor):
    adaptor = AgentAdaptor.from_compositor(
        compositor, _echo_agent, agent_type="worker", memory_limit_mb=512,
    )
    with pytest.raises(BoundsViolation):
        adaptor.act(
            intent_id="i", action_id="rogue", prompt="grab",
            enforcement=_bwrap_enforcement(4096),  # > 512 manifest bound
        )


def test_refused_action_is_not_recorded(compositor):
    from gyza.demo.coordination_plane import CoordinationState

    sink = CoordinationState()
    adaptor = AgentAdaptor.from_compositor(
        compositor, _echo_agent, agent_type="worker", memory_limit_mb=512,
        sink=sink,
    )
    with pytest.raises(BoundsViolation):
        adaptor.act(
            intent_id="i", action_id="rogue", prompt="grab",
            enforcement=_bwrap_enforcement(4096),
        )
    # Nothing over-bound leaks into the coordination plane.
    assert len(sink) == 0


def test_non_bubblewrap_backend_is_refused(compositor):
    adaptor = AgentAdaptor.from_compositor(
        compositor, _echo_agent, agent_type="worker", memory_limit_mb=512,
    )
    enf = _bwrap_enforcement(512)
    enf["backend"] = "none"  # not an enforcing sandbox
    with pytest.raises(BoundsViolation):
        adaptor.act(intent_id="i", action_id="a1", prompt="x", enforcement=enf)


# ----------------------------------------------------------------------
# Heterogeneity — different agents interoperate through one envelope type
# ----------------------------------------------------------------------

def test_heterogeneous_agents_interoperate(compositor):
    from gyza.demo.coordination_plane import CoordinationState

    plane = CoordinationState()
    a = AgentAdaptor.from_compositor(
        compositor, _echo_agent, agent_type="echoer", memory_limit_mb=512,
        sink=plane,
    )
    b = AgentAdaptor.from_compositor(
        compositor, _upper_agent, agent_type="upper", memory_limit_mb=256,
        sink=plane,
    )
    ea = a.act(intent_id="i", action_id="a", prompt="hi")
    eb = b.act(intent_id="i", action_id="b", prompt="hi", parent=ea)

    # Two different agents, distinct identities, one shared plane.
    assert a.pubkey_hex != b.pubkey_hex
    assert len(plane) == 2
    # Each verifies against its own author, from public keys alone.
    assert verify_envelope(ea, bytes.fromhex(a.pubkey_hex))
    assert verify_envelope(eb, bytes.fromhex(b.pubkey_hex))
    # And the cross-agent chain is intact.
    ok, _ = verify_chain([ea, eb])
    assert ok


# ----------------------------------------------------------------------
# Recoverability — envelopes reconcile across a DDIL partition
# ----------------------------------------------------------------------

def test_adaptors_reconcile_across_partition(compositor):
    from gyza.demo.gossip import GossipNode, Network, run_until_converged

    net = Network(["n0", "n1", "n2", "n3"])
    nodes = {n: GossipNode(n, net) for n in net._ids}
    for n in nodes.values():
        n.attach_peers(list(nodes.values()))

    # One adaptor lands on each side of a coming 2/2 split, each writing
    # into its local node's CRDT replica (the data-plane sink).
    left = AgentAdaptor.from_compositor(
        compositor, _echo_agent, agent_type="left", memory_limit_mb=512,
        sink=nodes["n0"].state,
    )
    right = AgentAdaptor.from_compositor(
        compositor, _upper_agent, agent_type="right", memory_limit_mb=512,
        sink=nodes["n2"].state,
    )

    # A shared root both sides hold before the split.
    root = left.act(intent_id="i", action_id="root", prompt="start")
    run_until_converged(list(nodes.values()))

    # Partition, then each side keeps working (available data plane).
    net.partition(["n0", "n1"], ["n2", "n3"])
    el = left.act(intent_id="i", action_id="L", prompt="left-work", parent=root)
    er = right.act(intent_id="i", action_id="R", prompt="right-work", parent=root)
    run_until_converged(list(nodes.values()))

    # Mid-partition: neither side has the other's write.
    assert er.output_hash not in _hashes(nodes["n0"].state)
    assert el.output_hash not in _hashes(nodes["n2"].state)

    # Heal → both sides converge to the full union; nothing signed is lost.
    net.heal()
    run_until_converged(list(nodes.values()))
    for n in nodes.values():
        assert len(n.state) == 3  # root + L + R

    # Each partition branch is an independently valid ICP chain.
    chains = nodes["n0"].state.linear_chains()
    assert len(chains) == 2
    for chain in chains:
        ok, _ = verify_chain(chain)
        assert ok


def _hashes(state) -> set:
    return set(state.event_hashes())
