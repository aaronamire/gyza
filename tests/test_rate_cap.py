"""B6 — the action-rate capability dimension, enforced.

WHY THIS DIMENSION EXISTS, AND WHY IT IS THE FIFTH. R-M1 measured that a
cross-principal aggregate is boundable by local checks exactly when concurrent
activity per principal is bounded. A2 measured that such a bound is a COMPLIANCE
ASSUMPTION unless the limit is ENFORCED -- one principal ignoring it breaks the
aggregate at every scale, because damage travels through the commons. R-B
measured the tolerable non-compliance at ~1.6 defectors PER CLUSTER, which is
why the quantity bounded here is per-principal rate rather than a global total.

It is the first CapabilitySpec dimension derived from measurement rather than
from a threat model.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_rate_cap.py -q
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from tests.test_runner_audit_integration import (
    _intent, _within_bounds_executor, _work_item,
)

from gyza.blackboard import Blackboard
from gyza.drift import SpecializationTracker
from gyza.demand import LSHIndex
from gyza.economy.delegation import (
    CapabilitySpec, capability_subset, spec_from_manifest,
)
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.network.artifact_store import ArtifactStore
from gyza.runner import AgentRunner
from gyza.schema import EMBEDDING_DIM


# --------------------------------------------------------------------------- #
#  ATTENUATION — the theorem must extend to the new dimension                  #
# --------------------------------------------------------------------------- #
def test_rate_is_monotone_non_increasing_down_a_chain():
    outer = CapabilitySpec(rate_cap=100)
    assert capability_subset(CapabilitySpec(rate_cap=50), outer)[0]
    ok, why = capability_subset(CapabilitySpec(rate_cap=500), outer)
    assert not ok and "exceeds the granted cap" in why


def test_an_OMITTED_cap_cannot_launder_a_granted_one():
    """The mem_cap asymmetry, and it is load-bearing for the same reason:
    silence must not read as permission."""
    ok, why = capability_subset(CapabilitySpec(), CapabilitySpec(rate_cap=10))
    assert not ok and "declares no cap" in why
    # ...and with no outer cap there is nothing to attenuate
    assert capability_subset(CapabilitySpec(rate_cap=9), CapabilitySpec())[0]


def test_a_grant_signed_BEFORE_this_field_still_parses():
    """`DelegationGrant` stores `delegated_authority` as a dict and signs it as
    stored, so an old grant's payload bytes are unchanged. Parsing must
    tolerate the missing key rather than raise."""
    old = {"ro": [], "rw": [], "network": False, "mem_cap": 512}
    assert CapabilitySpec.from_canonical(old).rate_cap is None
    assert "rate_cap" in CapabilitySpec(rate_cap=7).to_canonical()


def test_it_travels_by_the_same_route_as_every_other_bound():
    m = {"capabilities": {"spawn": {"resource_budget": {
        "memory_limit_mb": 512, "action_rate_cap": 25}}}}
    assert spec_from_manifest(m).rate_cap == 25
    assert spec_from_manifest({"capabilities": {}}).rate_cap is None


# --------------------------------------------------------------------------- #
#  ENFORCEMENT — at the serialization point, refusing to SIGN                  #
# --------------------------------------------------------------------------- #
def _runner(tmp_path, rate_cap, rate_window_ns=None):
    store = ArtifactStore(base_path=str(tmp_path / "cas"))
    bb = Blackboard(str(tmp_path / "bb.db"))
    bb.attach_artifact_store(store)
    comp = LocalCompositor(key_path=str(tmp_path / "k.key"))
    seed, manifest = comp.issue_agent(
        agent_type="rate.worker", model_path="mock", fs_read_paths=[],
        fs_write_paths=[], allowed_hosts=[], memory_limit_mb=512,
        attestation_tier=0)
    if rate_cap is not None:
        manifest["capabilities"]["spawn"]["resource_budget"][
            "action_rate_cap"] = rate_cap
    ident = AgentIdentity(seed, manifest)
    v = np.zeros(EMBEDDING_DIM, dtype=np.float32); v[0] = 1.0
    runner = AgentRunner(
        identity=ident, blackboard=bb,
        memory=EpisodicMemory(agent_id=ident.agent_id,
                              db_path=str(tmp_path / "mem")),
        specialization=SpecializationTracker(
            agent_id=ident.agent_id, initial_embedding=v,
            db_path=str(tmp_path / "spec.db")),
        lsh=LSHIndex(seed=42), executor=_within_bounds_executor(256),
        min_reward_threshold=0.0, min_similarity_threshold=-1.0,
        verify_chain_before_claim=False,
        **({} if rate_window_ns is None
           else {"rate_window_ns": rate_window_ns}))
    return runner, bb


def _do(runner, bb, n, intent="rate-intent"):
    _intent(bb, intent)
    done = 0
    for _ in range(n):
        w = _work_item(intent)
        bb.post_work_item(w)
        res = runner._execute(w)
        runner._complete(w, res, True)
        done += 1
    return done


def test_the_runner_REFUSES_TO_SIGN_past_the_declared_rate(tmp_path):
    runner, bb = _runner(tmp_path, rate_cap=3)
    with pytest.raises(RuntimeError, match="rate cap"):
        _do(runner, bb, 5)
    # exactly the cap was signed, and no more
    assert bb.count_agent_envelopes_since(runner._identity.agent_id, 0) == 3
    assert runner.authority_violations, "the refusal was not recorded"
    assert "rate cap" in runner.authority_violations[-1].reason


def test_no_declared_cap_means_NO_LIMIT_not_a_default(tmp_path):
    """An absent bound must not become an invented one -- the defect that
    retired H1 was a level nobody measured."""
    runner, bb = _runner(tmp_path, rate_cap=None)
    _do(runner, bb, 6)
    assert bb.count_agent_envelopes_since(runner._identity.agent_id, 0) == 6


def test_the_count_is_PER_AGENT_not_node_wide(tmp_path):
    """A node-wide count would let one busy agent exhaust every other agent's
    budget -- the same frame error as measuring a per-principal quantity over
    the federation."""
    a, bb = _runner(tmp_path / "a", rate_cap=2)
    b, _ = _runner(tmp_path / "b", rate_cap=2)
    _do(a, bb, 2)
    assert bb.count_agent_envelopes_since(a._identity.agent_id, 0) == 2
    assert bb.count_agent_envelopes_since(b._identity.agent_id, 0) == 0


# =========================================================================== #
#  IT IS A RATE. Until 2026-08-21 it was a LIFETIME QUOTA.
#
#  The block enforcing this counted envelopes since GENESIS, so an agent
#  granted `action_rate_cap: N` was permanently refused at its Nth action for
#  the rest of its life. Every test above passed anyway, because none of them
#  could distinguish a rate from a quota: they sign a handful of actions inside
#  one window, where the two behave identically. THE TESTS ENCODED THE DEFECT.
#
#  Found by R-EVID's drift criterion (research/evidence/THEOREMS_C.md): benign
#  rate is one envelope per action, so the fold had positive drift with no
#  compensation -- a TIMER with false-alarm probability 1, not a bound.
# =========================================================================== #

def test_the_budget_REFILLS_once_the_window_passes(tmp_path):
    """The property a quota cannot have, and the reason the rename was not
    enough: after the window elapses the agent works again."""
    runner, bb = _runner(tmp_path, rate_cap=2, rate_window_ns=250_000_000)
    with pytest.raises(RuntimeError, match="rate cap"):
        _do(runner, bb, 3)
    assert bb.count_agent_envelopes_since(runner._identity.agent_id, 0) == 2

    time.sleep(0.4)                      # outrun the 250 ms window
    _do(runner, bb, 2, intent="rate-intent-2")
    assert bb.count_agent_envelopes_since(runner._identity.agent_id, 0) == 4, (
        "the agent was still refused after its window elapsed -- the origin is "
        "not advancing with the wall clock and this is still a quota")


def test_the_window_origin_ADVANCES_WITH_TIME_AND_NOT_WITH_WORK(tmp_path):
    """The distinction from ledger artifact #13, asserted rather than trusted.

    #13 was bought by a gate measuring from a checkpoint the AGENT could
    advance by acting, which purchased unlimited drain. A wall-clock window is
    a different object ONLY IF working cannot move it. So: burn the budget,
    then do more work-shaped activity WITHOUT waiting, and confirm the refusal
    stands.
    """
    runner, bb = _runner(tmp_path, rate_cap=2, rate_window_ns=60_000_000_000)
    with pytest.raises(RuntimeError, match="rate cap"):
        _do(runner, bb, 5)
    signed = bb.count_agent_envelopes_since(runner._identity.agent_id, 0)
    assert signed == 2

    for _ in range(3):
        with pytest.raises(RuntimeError, match="rate cap"):
            _do(runner, bb, 1, intent="rate-intent-retry")
    assert bb.count_agent_envelopes_since(
        runner._identity.agent_id, 0) == signed, (
        "attempting more work moved the budget; an agent must not be able to "
        "buy rate by acting, only by waiting")


def test_a_non_positive_window_is_REFUSED_not_silently_disabling(tmp_path):
    """A zero or negative window makes the lookback empty, so the cap would
    never fire and would fail OPEN while still appearing declared."""
    for bad in (0, -1):
        with pytest.raises(ValueError, match="must be positive"):
            _runner(tmp_path, rate_cap=5, rate_window_ns=bad)


def test_the_window_is_NOT_readable_from_the_manifest(tmp_path):
    """A principal that could widen its own window could restore the quota, or
    erase the cap by declaring a window longer than the deployment. The window
    belongs to the enforcement, not to the grant."""
    from gyza.economy.delegation import CapabilitySpec, spec_from_manifest

    m = {"capabilities": {"spawn": {"resource_budget": {
        "action_rate_cap": 5, "action_rate_window_ns": 1}}}}
    spec = spec_from_manifest(m)
    assert spec.rate_cap == 5
    assert not hasattr(spec, "rate_window_ns"), (
        "the window became part of the capability spec; a grant that carries "
        "its own window can widen it")
    assert "rate_window_ns" not in CapabilitySpec().to_canonical()
