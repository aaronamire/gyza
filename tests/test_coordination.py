"""
Coordination layer (K-1, K-4 … K-6, K-8) + Phase 5 (H-1, O-2, O-3).

Includes the BUILD_PLAN §7 end-to-end acceptance criterion.
"""
from __future__ import annotations

import pytest

from gyza.containment import (
    GuardEngine, HarmClass, HarmModelRegistry, Invariant, InvariantClass,
    InvariantRegistry, PromotionGate, StagingArea,
)
from gyza.coordination import (
    EscalationItem, EscalationQueue, ExecutorPool, NotSelectedError, RunMetrics,
    Scheduler, TaskSpec, Termination, alarms, allocate, decompose, retry_policy,
)
from gyza.verification.scheduler import CARRIER_DEPTH_CAP, consult_tier_algebra


class Bal:
    def __init__(self, total):
        self.total = total


def _proj(events):
    return Bal(sum(e.payload.get("delta", 0.0) for e in events))


def _engine(bound=100.0):
    h = HarmModelRegistry()
    h.register(HarmClass(id="spend", description="d",
                         quantity=lambda s0, s: float(s0.total - s.total),
                         frame="account", frame_mutable=False, code_path="t:0"))
    h.load_bounds({"spend": bound})
    i = InvariantRegistry()
    i.register(Invariant(id="INV-spend", harm_class="spend",
                         cls=InvariantClass.CUMULATIVE, description="d"))
    return GuardEngine(h, i)


def _sched(bound=100.0):
    st = StagingArea(projector=_proj)
    eng = _engine(bound)
    return Scheduler(eng, st, PromotionGate(eng, st))


def _task(tid, carrier="PROOF", tier=1, cls=None, depth=0):
    return TaskSpec(task_id=tid, goal=f"goal-{tid}", claim_type="envelope_signature",
                    tier=tier, carrier=carrier, depth=depth,
                    invariant_classes=list(cls or []))


# --------------------------------------------------------------------------- #
#  K-1 / K-8                                                                   #
# --------------------------------------------------------------------------- #
def test_termination_has_four_explicit_states_and_no_timeout():
    """K-8. A timeout is not a reason, it is the absence of one, and a task
    that ends without a recorded reason cannot be audited."""
    assert {t.name for t in Termination} == {
        "GOAL_SATISFIED", "DEPTH_CAP_REACHED", "HARM_BUDGET_EXHAUSTED",
        "ESCALATED"}
    assert not any("TIMEOUT" in t.name for t in Termination)


def test_task_carries_carrier_and_knows_whether_it_composes():
    assert _task("a", carrier="PROOF").composes
    assert _task("b", carrier="SPEC").composes
    assert not _task("c", carrier="TEST").composes
    assert not _task("d", carrier="NONE").composes
    with pytest.raises(ValueError):
        _task("e", carrier="VIBES")


# --------------------------------------------------------------------------- #
#  K-2 / K-3 / K-7 are DECLARED, not defaulted                                 #
# --------------------------------------------------------------------------- #
def test_unselected_components_raise_and_name_the_blocking_artifact():
    """A default nobody chose is worse than an absence somebody noticed."""
    for fn, args in ((decompose, (_task("x"),)),
                     (retry_policy, (_task("x"), 1))):
        with pytest.raises(NotSelectedError) as e:
            fn(*args)
        assert "BLOCKED_SR1_SR2_SR4.md" in str(e.value)


def test_k2_strategy_is_selected_even_though_k2_still_raises():
    """The split: the STRATEGY question is answered, the IMPLEMENTATION is not,
    and the raise names the second rather than the first."""
    from gyza.coordination import (
        DEFAULT_DECOMPOSITION_BASIS, DEFAULT_DECOMPOSITION_STRATEGY,
        DecompositionStrategy,
    )
    assert DEFAULT_DECOMPOSITION_STRATEGY is DecompositionStrategy.CONSERVING
    with pytest.raises(NotSelectedError) as e:
        decompose(_task("x"))
    msg = str(e.value)
    assert "strategy IS selected" in msg
    assert "claim_type" in msg, "the raise must name the REMAINING blocker"


def test_the_default_basis_does_not_claim_an_outcome_benefit():
    """A4: if a reader could come away believing CONSERVING was chosen because
    it produces better task outcomes, the wording has failed. Pinned, because
    this is the property most likely to be softened by a later edit."""
    from gyza.coordination import DEFAULT_DECOMPOSITION_BASIS as B
    assert "UNMEASURED" in B
    assert "containment" in B.lower()
    for forbidden in ("better outcome", "improves", "more successful",
                      "higher success", "outperform"):
        assert forbidden not in B.lower(), f"basis implies an outcome claim: {forbidden}"


def test_k3_allocator_is_round_robin_per_sr2():
    """SR-2 measured type-routing 13pp WORSE than round-robin (0.3261 vs
    0.4565): a taxonomy too coarse to discriminate converts a spread into a bet
    on one handler, while round-robin diversifies."""
    hs = ["a", "b", "c"]
    got = [allocate(_task(f"t{i}"), hs) for i in range(6)]
    assert got == ["a", "b", "c", "a", "b", "c"], got
    assert len(set(got)) == 3, "the point is that it diversifies"
    with pytest.raises(ValueError):
        allocate(_task("x"), [])


# --------------------------------------------------------------------------- #
#  K-4 — concurrency from CLASS, never from carrier                            #
# --------------------------------------------------------------------------- #
def test_executor_pool_serializes_on_class_not_on_carrier():
    """CLASS says what may run at once (C6/C7); CARRIER says whether evidence
    survives chaining (SR-3). Using carrier here would serialize proof-carried
    work for no reason and run cumulative work concurrently — R13's failure."""
    pool = ExecutorPool()
    pool.submit(_task("t1", carrier="PROOF",
                      cls=[InvariantClass.CONSERVATION]), lambda: None)
    pool.submit(_task("t2", carrier="TEST",
                      cls=[InvariantClass.MONOTONE_NON_CUMULATIVE]), lambda: None)
    pool.submit(_task("t3", carrier="PROOF",
                      cls=[InvariantClass.CUMULATIVE]), lambda: None)

    assert pool.ran_concurrent == ["t1", "t2"], "class drives concurrency"
    assert pool.ran_serialized == ["t3"], "only CUMULATIVE serializes"


# --------------------------------------------------------------------------- #
#  K-5 — ACCEPTANCE: a TEST-carried stage forces the chain to tier 3           #
# --------------------------------------------------------------------------- #
def test_combiner_forces_tier_3_when_any_stage_is_test_carried():
    s = _sched()
    allproof = s.combiner.combine([_task("a"), _task("b"), _task("c")])
    assert allproof.tier == 1

    withtest = s.combiner.combine(
        [_task("a"), _task("b", carrier="TEST"), _task("c")])
    assert withtest.tier == 3, "one finite-sample stage is enough"
    assert "finite sample" in " ".join(withtest.reasons)


def test_combiner_flags_cumulative_for_the_promotion_gate():
    s = _sched()
    c = s.combiner.combine([_task("a", cls=[InvariantClass.CUMULATIVE])])
    assert c.requires_promotion_gate
    assert "C7" in " ".join(c.reasons)


# --------------------------------------------------------------------------- #
#  K-6 — SR-6's per-carrier depth cap                                          #
# --------------------------------------------------------------------------- #
def test_depth_cap_is_keyed_on_carrier_not_tier():
    """SR-6's correction. Keyed on tier, a TIER-1 TEST-CARRIED chain would have
    received NO cap while being the chain that decays fastest."""
    assert CARRIER_DEPTH_CAP["PROOF"] is None
    assert CARRIER_DEPTH_CAP["SPEC"] is None
    assert CARRIER_DEPTH_CAP["TEST"] == 10

    # tier 1 throughout, but TEST-carried: must cap
    d = consult_tier_algebra(["PROOF", "TEST"], [1, 1], depth=25)
    assert not d.depth_permitted

    deep_proof = consult_tier_algebra(["PROOF", "PROOF"], [1, 1], depth=500)
    assert deep_proof.depth_permitted, "proofs do not decay"


# --------------------------------------------------------------------------- #
#  H-1 — an escalation without a bound is a dropped alarm                      #
# --------------------------------------------------------------------------- #
def test_escalation_queue_refuses_an_unactionable_item():
    q = EscalationQueue()
    with pytest.raises(ValueError, match="cited bound"):
        q.push(EscalationItem("t", "claim", ["h1"], "", "d"))
    with pytest.raises(ValueError, match="provenance"):
        q.push(EscalationItem("t", "claim", [], "spend <= 100", "d"))
    q.push(EscalationItem("t", "claim", ["h1"], "spend <= 100", "d"))
    assert len(q) == 1


# --------------------------------------------------------------------------- #
#  O-2 / O-3                                                                   #
# --------------------------------------------------------------------------- #
def test_metrics_report_effective_not_nominal_throughput():
    """SR-5's lesson: nominal admission was 1.0000 for every variant while
    effective ranged 0.0542 -> 0.0000."""
    m = RunMetrics(admitted=3, rolled_back=7)
    assert m.effective_throughput == pytest.approx(0.3)


def test_alarm_fires_on_a_synthetic_near_violation():
    """BUILD_PLAN §7."""
    m = RunMetrics(admitted=10)
    m.harm_fraction_of_bound = {"spend": 0.85}
    fired = alarms(m)
    assert any("HARM-NEAR-BOUND" in a for a in fired)
    assert "85%" in " ".join(fired)


def test_alarm_fires_on_vocabulary_drift_and_on_unenforced_invariants():
    m = RunMetrics(admitted=10)
    m.carrier_distribution = {"PROOF": 2, "TEST": 3, "NONE": 5}
    fired = alarms(m, invariants_evaluated=5, invariants_enforced=3)
    assert any("VOCABULARY-DRIFT" in a for a in fired)
    assert any("EVALUATED-NOT-ENFORCED" in a for a in fired)


def test_no_alarm_on_a_healthy_run():
    m = RunMetrics(admitted=10)
    m.carrier_distribution = {"PROOF": 9, "SPEC": 1}
    m.harm_fraction_of_bound = {"spend": 0.2}
    assert alarms(m, invariants_evaluated=4, invariants_enforced=4) == []


# --------------------------------------------------------------------------- #
#  ACCEPTANCE: end to end                                                      #
# --------------------------------------------------------------------------- #
def test_end_to_end_task_completes_with_a_verifiable_provenance_chain():
    """BUILD_PLAN §7: a task enters, is routed, executed in staging, promoted,
    and completes — with a provenance chain a third party can verify."""
    s = _sched(bound=100.0)
    tasks = [_task(f"t{i}", cls=[InvariantClass.CUMULATIVE]) for i in range(3)]
    res = s.run_chain(tasks, harm_classes=["spend"])

    assert res.state is Termination.GOAL_SATISFIED
    assert res.tier_achieved == 1
    assert res.provenance, "a completed task must carry provenance"
    ok, why = s._staging.log.verify()
    assert ok, f"the provenance chain must verify independently: {why}"
    assert s.metrics.effective_throughput == 1.0
    assert s.metrics.carrier_distribution == {"PROOF": 3}


def test_end_to_end_task_escalates_and_the_escalation_cites_its_bound():
    """The other half of the criterion: it either completes OR escalates, and
    the escalation is actionable."""
    st = StagingArea(projector=_proj)
    eng = _engine(bound=1.0)
    s = Scheduler(eng, st, PromotionGate(eng, st))

    st.stage("p", "stage_artifact", {"delta": -50.0})     # blow the budget
    tasks = [_task("t0", cls=[InvariantClass.CUMULATIVE])]
    res = s.run_chain(tasks, harm_classes=["spend"])

    assert res.state is Termination.HARM_BUDGET_EXHAUSTED
    assert len(s.queue) == 1
    item = s.queue.items()[0]
    assert "bound" in item.bound_cited or "INV-spend" in item.bound_cited
    assert item.provenance
    assert s.metrics.escalations == 1


def test_end_to_end_deep_test_carried_chain_is_refused_before_execution():
    """The tier algebra is consulted BEFORE work is permitted, not after."""
    s = _sched()
    tasks = [_task(f"t{i}", carrier="TEST") for i in range(20)]
    res = s.run_chain(tasks)
    assert res.state is Termination.DEPTH_CAP_REACHED
    assert res.tier_achieved == 3
    assert s.metrics.admitted == 0, "nothing was executed"
