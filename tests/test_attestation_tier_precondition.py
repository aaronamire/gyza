"""The attestation tier is a PRECONDITION on the executor, not a capability.

Arena 2 (`research/arenas/arena2_compromised/`) ran a tier-0 agent against a
tier-3 work item: it claimed it, executed it, and produced a VALID signed
envelope. `required_tier` was read at exactly one place -- `get_unclaimed`'s
WHERE clause -- so the filter bound only agents that learned of work by POLLING.

The fix deliberately did NOT add a sixth attenuated dimension to
`CapabilitySpec`; `test_the_tier_is_not_an_attenuated_capability` below is the
negative control that pins why.
"""
from __future__ import annotations

import time
import uuid

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem


def _agent(tmp_path, tier, name="a"):
    comp = LocalCompositor(key_path=str(tmp_path / f"{name}.key"))
    seed, manifest = comp.issue_agent(
        agent_type="tier.worker", model_path="mock", fs_read_paths=[],
        fs_write_paths=[], allowed_hosts=[], memory_limit_mb=512,
        attestation_tier=tier)
    return AgentIdentity(seed, manifest)


def _item(bb, tier, intent="tier-intent"):
    try:
        bb.post_intent({"intent_id": intent, "natural_text": "t",
                        "category": "system_task", "actions": [],
                        "authorization": {"resources": [],
                                          "preview_required": False,
                                          "reversible": True}})
    except Exception:
        pass
    e = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    e[0] = 1.0
    w = WorkItem(
        id=str(uuid.uuid7()), lineage_root=intent, parent_id=None,
        description="d", desc_embedding=e, reward=0.9,
        reward_updated_ns=time.time_ns(), required_tier=tier, input_hashes=[],
        output_spec={"kind": "test"}, streaming_ok=False, claimed_by=None,
        claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(), ttl_ns=3600 * 10**9)
    bb.post_work_item(w)
    return w


# --------------------------------------------------------------------------- #
#  THE BOUNDARY: the signing path reads the COMPOSITOR-SIGNED manifest          #
# --------------------------------------------------------------------------- #
def _runner(tmp_path, ident, bb):
    from gyza.demand import LSHIndex
    from gyza.drift import SpecializationTracker
    from gyza.memory import EpisodicMemory
    from gyza.runner import AgentRunner

    v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    v[0] = 1.0
    return AgentRunner(
        identity=ident, blackboard=bb,
        memory=EpisodicMemory(agent_id=ident.agent_id,
                              db_path=str(tmp_path / "mem")),
        specialization=SpecializationTracker(
            agent_id=ident.agent_id, initial_embedding=v,
            db_path=str(tmp_path / "spec.db")),
        lsh=LSHIndex(seed=42),
        executor=lambda p, c: {"text": "ok"},
        min_reward_threshold=0.0, min_similarity_threshold=-1.0,
        verify_chain_before_claim=False)


def test_a_tier0_agent_CANNOT_execute_tier3_work(tmp_path):
    """Arena 2's A11, now refused. The refusal comes BEFORE execution."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    r = _runner(tmp_path, _agent(tmp_path, 0), bb)
    with pytest.raises(RuntimeError, match="attestation tier"):
        r._execute(_item(bb, 3))


def test_the_refusal_happens_BEFORE_the_work_runs(tmp_path):
    """Strictly better than the bounds gate, which can only withhold a
    signature after the fact. Nothing may run, and no input may be read."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    ran = []
    r = _runner(tmp_path, _agent(tmp_path, 0), bb)
    r._executor = lambda p, c: (ran.append(1), {"text": "ok"})[1]
    with pytest.raises(RuntimeError):
        r._execute(_item(bb, 2))
    assert ran == [], "the executor ran for work above the agent's tier"


def test_equal_and_lower_tiers_are_PERMITTED(tmp_path):
    """Positive control. A gate that refuses everything contains perfectly and
    is worth nothing."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    r = _runner(tmp_path, _agent(tmp_path, 2), bb)
    for t in (0, 1, 2):
        assert r._execute(_item(bb, t))["output"] == "ok"


def test_an_UNDECLARED_tier_fails_closed(tmp_path):
    """"I did not say" reads as tier 0, never as "unrestricted" -- the same
    rule the enforcement record follows."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    ident = _agent(tmp_path, 0)
    ident.manifest.pop("attestation_tier", None)
    r = _runner(tmp_path, ident, bb)
    assert r._execute(_item(bb, 0))["output"] == "ok"
    with pytest.raises(RuntimeError, match="attestation tier"):
        r._execute(_item(bb, 1))


# --------------------------------------------------------------------------- #
#  THE ADVISORY FILTER, and it must not be described as more                    #
# --------------------------------------------------------------------------- #
def test_try_claim_refuses_an_above_tier_item_reached_by_ID(tmp_path):
    """The path Arena 2 walked: get_unclaimed hides it, try_claim did not."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    hi = _item(bb, 3)
    assert hi.id not in {w.id for w in bb.get_unclaimed(min_reward=0.0, tier=0)}
    assert bb.try_claim(hi.id, "a", HLC(node_id="n"), claimant_tier=0) is False
    assert bb.try_claim(hi.id, "a", HLC(node_id="n"), claimant_tier=3) is True


def test_the_advisory_filter_is_SELF_REPORTED_and_a_liar_defeats_it(tmp_path):
    """Pinning the limit so nobody later reads the filter as a boundary.

    A compromised agent passes any number it likes here -- and is still refused
    at the signing gate, which reads the signed manifest instead.
    """
    bb = Blackboard(str(tmp_path / "bb.db"))
    hi = _item(bb, 3)
    assert bb.try_claim(hi.id, "liar", HLC(node_id="n"), claimant_tier=3) is True

    r = _runner(tmp_path, _agent(tmp_path, 0), bb)
    with pytest.raises(RuntimeError, match="attestation tier"):
        r._execute(hi)


def test_an_absent_claimant_tier_fails_closed(tmp_path):
    bb = Blackboard(str(tmp_path / "bb.db"))
    assert bb.try_claim(_item(bb, 1).id, "a", HLC(node_id="n")) is False
    assert bb.try_claim(_item(bb, 0).id, "a", HLC(node_id="n")) is True


# --------------------------------------------------------------------------- #
#  NEGATIVE CONTROL: why this is NOT a sixth CapabilitySpec dimension           #
# --------------------------------------------------------------------------- #
def test_the_tier_is_not_an_attenuated_capability(tmp_path):
    """If the tier were attenuated (`child <= parent`), a BETTER-attested
    subcontractor would be refused and the real hazard would pass.

    This test fails the moment someone adds `tier` to `CapabilitySpec`, which
    is the intent: the hazard is a FLOOR on the executor, not a CEILING on a
    delegate, and the two are different quantities.
    """
    import dataclasses

    from gyza.economy.delegation import CapabilitySpec

    fields = {f.name for f in dataclasses.fields(CapabilitySpec)}
    assert fields == {"ro", "rw", "network", "mem_cap", "rate_cap"}, (
        "CapabilitySpec grew a dimension. If it is `tier`, read "
        "AgentRunner._require_attested_tier first: attenuation refuses the "
        "SAFE direction (a tier-1 agent delegating to a tier-3 agent) and "
        "permits the hazard (tier-3 delegating to tier-0)."
    )
