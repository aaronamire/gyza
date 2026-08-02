"""
Phase 2 tests — S1 append-only log, C-5 staging, C-6 promotion gate,
C-7 rollback, C-8 guard configuration.

Several of these correspond one-to-one with BUILD_PLAN §7 acceptance criteria
and are named so that is visible.
"""
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.containment import (
    GuardEngine, HarmClass, HarmModelRegistry, Invariant, InvariantClass,
    InvariantRegistry, Phase,
)
from gyza.containment.guardconfig import (
    GuardConfigError, GuardConfigStore, sign_config,
)
from gyza.containment.log import AppendOnlyLog, KIND_ROLLBACK
from gyza.containment.staging import (
    NotInteriorError, PromotionGate, StagingArea,
)


class Bal:
    def __init__(self, total: float):
        self.total = total


def _projector(events):
    """State is ALWAYS a fold. Never stored."""
    return Bal(sum(e.payload.get("delta", 0.0) for e in events))


def _drain(s0, s):
    return float(s0.total - s.total)


def _engine(bound=100.0, cls=InvariantClass.CUMULATIVE):
    h = HarmModelRegistry()
    h.register(HarmClass(id="spend", description="credits spent",
                         quantity=_drain, frame="account", frame_mutable=False,
                         code_path="test:0"))
    h.load_bounds({"spend": bound})
    i = InvariantRegistry()
    i.register(Invariant(id="INV-spend", harm_class="spend", cls=cls,
                         description="spend stays within bound"))
    return GuardEngine(h, i)


def _staged(engine=None, bound=100.0, cls=InvariantClass.CUMULATIVE):
    st = StagingArea(projector=_projector)
    return st, PromotionGate(engine or _engine(bound, cls), st)


# --------------------------------------------------------------------------- #
#  S1 — append-only                                                            #
# --------------------------------------------------------------------------- #
def test_log_has_no_update_and_no_delete_api():
    """Not discouraged — absent. If history can be rewritten the fold is no
    longer a function of what happened."""
    log = AppendOnlyLog()
    for name in ("update", "delete", "remove", "pop", "__delitem__", "__setitem__"):
        assert not hasattr(log, name), f"AppendOnlyLog exposes {name!r}"


def test_partition_key_is_mandatory():
    """C8: a guard scales in breadth only if its state partitions along the
    action axis. An unpartitioned event would silently reintroduce a global
    counter."""
    with pytest.raises(ValueError, match="partition"):
        AppendOnlyLog().append("", "stage_artifact", {})


def test_log_is_tamper_evident():
    log = AppendOnlyLog()
    for i in range(4):
        log.append("p", "stage_artifact", {"n": i})
    assert log.verify() == (True, "")
    # excise the middle event
    log._events.pop(2)
    ok, why = log.verify()
    assert not ok and ("out of order" in why or "broken link" in why)


def test_state_is_derived_by_fold_not_stored():
    log = AppendOnlyLog()
    for n in (3, 4, 5):
        log.append("p", "stage_artifact", {"n": n})
    assert log.fold(lambda a, e: a + e.payload["n"], 0) == 12
    # there is no aggregate attribute an unmodelled path could write behind the
    # guard's back
    assert not any(a for a in ("total", "balance", "_sum") if hasattr(log, a))


# --------------------------------------------------------------------------- #
#  C-5 — the interior                                                          #
# --------------------------------------------------------------------------- #
def test_irreversible_and_egress_cannot_be_staged_in_the_interior():
    st, _ = _staged()
    for act in ("sign_envelope", "send_message", "delete_artifact"):
        with pytest.raises(NotInteriorError):
            st.stage("p", act)


def test_staged_work_is_invisible_until_promoted():
    st, _ = _staged()
    st.stage("p", "stage_artifact", {"delta": -30.0})
    assert st.baseline_state().total == 0.0, "the interior must not leak"
    assert st.staged_state().total == -30.0


# --------------------------------------------------------------------------- #
#  C-6 — ACCEPTANCE: cumulative only at the gate, from class tags              #
# --------------------------------------------------------------------------- #
def test_cumulative_bound_is_deferred_in_interior_and_enforced_at_the_gate():
    """BUILD_PLAN §7: 'Cumulative invariants are evaluated ONLY at the promotion
    gate ... The scheduler enforces this from class tags, not from hard-coded
    knowledge.'"""
    eng = _engine(bound=100.0, cls=InvariantClass.CUMULATIVE)
    st, gate = _staged(eng)
    st.stage("p", "stage_artifact", {"delta": -60.0})
    st.stage("p", "stage_artifact", {"delta": -60.0})

    interior = eng.evaluate(st.baseline_state(), st.staged_state(),
                            "stage_artifact", Phase.INTERIOR)
    assert interior.admit and interior.deferred == ["INV-spend"]
    assert interior.evaluated == [], "the interior must not pretend to bound it"

    res = gate.promote()
    assert not res.promoted
    assert res.decision is not None and "INV-spend" in res.decision.reasons[0]


def test_refusal_cites_the_specific_bound():
    """BUILD_PLAN §7: 'An unauthorized irreversible action is refused, and the
    refusal cites the specific bound.'"""
    st, gate = _staged(bound=100.0)
    st.stage("p", "stage_artifact", {"delta": -120.0})
    st.submit("p", "settle_credits", {"amount": 120.0})
    res = gate.promote()

    assert not res.promoted
    assert res.escalation is not None
    esc = res.escalation
    assert "120" in esc.reason and "100" in esc.reason, esc.reason
    assert esc.bounds_cited, "an escalation with no bound is a dropped alarm"
    assert "settle_credits" in esc.action_types
    assert esc.provenance, "escalation must carry provenance"


def test_promotion_advances_the_watermark_and_applies_queued_actions():
    st, gate = _staged(bound=100.0)
    st.stage("p", "stage_artifact", {"delta": -10.0})
    st.submit("p", "settle_credits", {"amount": 10.0})
    res = gate.promote()
    assert res.promoted and res.batch_size == 2
    assert st.baseline_state().total == -10.0, "promoted work is now visible"
    assert st.pending_gate == []
    assert any(e.kind == "settle_credits" for e in st.log.events())


def test_empty_promotion_is_a_noop():
    st, gate = _staged()
    r = gate.promote()
    assert r.promoted and r.batch_size == 0


# --------------------------------------------------------------------------- #
#  C-7 — ACCEPTANCE: rollback, and content loss under mutable storage          #
# --------------------------------------------------------------------------- #
def test_rollback_restores_interior_state_to_last_promotion():
    st, gate = _staged(bound=100.0)
    st.stage("p", "stage_artifact", {"delta": -10.0})
    assert gate.promote().promoted
    checkpoint = st.baseline_state().total

    st.stage("p", "stage_artifact", {"delta": -55.0})
    assert st.staged_state().total != checkpoint
    n = st.rollback("operator abort")
    assert n == 1
    assert st.baseline_state().total == checkpoint
    assert st.staged_state().total == checkpoint


def test_append_only_preserves_content_where_mutable_storage_loses_it():
    """BUILD_PLAN §7: 'the test suite includes a case where content loss would
    occur under mutable storage and does not under append-only.'

    R10's H-APPEND, reduced to its essence: the abandoned events REMAIN in the
    log, so the content they carried is still derivable after a rollback. A
    mutable store has nothing to derive it from -- the bytes are gone.
    """
    CONTENT = "the-only-copy"

    # --- mutable storage ---------------------------------------------------
    mutable = {"x": CONTENT}
    del mutable["x"]                      # a staged deletion, applied in place
    # rollback has nothing to restore FROM: the value is not anywhere.
    assert "x" not in mutable
    assert CONTENT not in mutable.values()

    # --- append-only -------------------------------------------------------
    log = AppendOnlyLog()
    log.append("p", "stage_artifact", {"key": "x", "op": "put", "val": CONTENT})
    st = StagingArea(projector=lambda evs: {
        e.payload["key"]: e.payload["val"] for e in evs
        if e.payload.get("op") == "put"
    }, log=log)

    # A CONTENT harm measure, matching R10's content class: how many of the
    # baseline's values are no longer reachable. (The default `_drain` used
    # elsewhere in this file measures a scalar balance and does not apply to a
    # key-value projection.)
    h = HarmModelRegistry()
    h.register(HarmClass(
        id="content_lost", description="values no longer reachable",
        quantity=lambda s0, s: float(len(set(s0.values()) - set(s.values()))),
        frame="key-value store", frame_mutable=False, code_path="test:0"))
    h.load_bounds({"content_lost": 0.0})
    iv = InvariantRegistry()
    iv.register(Invariant(id="INV-content", harm_class="content_lost",
                          cls=InvariantClass.CONSERVATION,
                          description="no content becomes unreachable"))
    gate = PromotionGate(GuardEngine(h, iv), st)
    # promote the put so it is the checkpoint
    assert gate.promote().promoted
    assert st.baseline_state() == {"x": CONTENT}

    # stage a deletion, then abandon it
    st.stage("p", "stage_artifact", {"key": "x", "op": "delete"})
    st.rollback("aborted")

    assert st.baseline_state() == {"x": CONTENT}, "content survives rollback"
    # and the abandoned event is still ON DISK -- nothing was destroyed
    kinds = [e.kind for e in st.log.events(include_control=True)]
    assert KIND_ROLLBACK in kinds
    assert any(e.payload.get("op") == "delete"
               for e in st.log.events()), "abandoned events are retained"
    assert st.log.verify() == (True, "")


def test_rollback_is_recorded_in_the_log_not_hidden():
    st, _ = _staged()
    st.stage("p", "stage_artifact", {"delta": -1.0})
    st.rollback("because")
    marker = [e for e in st.log.events(include_control=True)
              if e.kind == KIND_ROLLBACK]
    assert len(marker) == 1
    assert marker[0].payload["reason"] == "because"
    assert marker[0].payload["abandoned"] == [0]


# --------------------------------------------------------------------------- #
#  C-8 — ACCEPTANCE: the constrained system cannot rewrite its own guard       #
# --------------------------------------------------------------------------- #
def _keys():
    a = Ed25519PrivateKey.generate()
    return a.private_bytes_raw(), a.public_key().public_bytes_raw()


def test_attempted_self_modification_of_guard_config_is_refused():
    """BUILD_PLAN §7: 'Guard configuration cannot be modified by the system it
    constrains — demonstrated by an attempted self-modification that is
    refused.' If the agent can rewrite the invariant, the induction has no base
    case and nothing is being enforced."""
    authority_sk, authority_pk = _keys()
    agent_sk, _agent_pk = _keys()

    store = GuardConfigStore(authority_pk)
    good = {"version": 1, "bounds": {"spend": 100.0}, "tier_assignments": {}}
    store.load(good, sign_config(good, authority_sk))
    assert store.config.bounds == {"spend": 100.0}

    # the agent tries to raise its own bound, signing with the key it HAS
    evil = {"version": 2, "bounds": {"spend": 1e9}, "tier_assignments": {}}
    with pytest.raises(GuardConfigError) as e:
        store.attempt_update(evil, sign_config(evil, agent_sk),
                             requested_by="agent-0")
    assert "REFUSED" in str(e.value) and "agent-0" in str(e.value)
    assert store.config.bounds == {"spend": 100.0}, "bounds must be untouched"


def test_tampered_config_fails_verification():
    authority_sk, authority_pk = _keys()
    store = GuardConfigStore(authority_pk)
    cfg = {"version": 1, "bounds": {"spend": 100.0}, "tier_assignments": {}}
    sig = sign_config(cfg, authority_sk)
    tampered = dict(cfg, bounds={"spend": 999.0})
    with pytest.raises(GuardConfigError):
        store.load(tampered, sig)


def test_old_signed_config_cannot_be_replayed_to_loosen_bounds():
    """A downgrade attack: a genuinely authority-signed OLD config, replayed to
    reinstate bounds that were since tightened."""
    authority_sk, authority_pk = _keys()
    store = GuardConfigStore(authority_pk)
    loose = {"version": 1, "bounds": {"spend": 1e6}, "tier_assignments": {}}
    tight = {"version": 2, "bounds": {"spend": 10.0}, "tier_assignments": {}}
    store.load(loose, sign_config(loose, authority_sk))
    store.load(tight, sign_config(tight, authority_sk))
    with pytest.raises(GuardConfigError, match="monotone"):
        store.load(loose, sign_config(loose, authority_sk))
    assert store.config.bounds == {"spend": 10.0}


def test_unconfigured_store_refuses_to_operate():
    """An absent policy is not a permissive policy."""
    _sk, pk = _keys()
    with pytest.raises(GuardConfigError, match="unconfigured"):
        _ = GuardConfigStore(pk).config


def test_bounds_reach_the_harm_registry_only_through_a_verified_config():
    authority_sk, authority_pk = _keys()
    store = GuardConfigStore(authority_pk)
    cfg = {"version": 1, "bounds": {"spend": 42.0}, "tier_assignments": {}}
    store.load(cfg, sign_config(cfg, authority_sk))

    h = HarmModelRegistry()
    h.register(HarmClass(id="spend", description="d", quantity=_drain,
                         frame="account", frame_mutable=False, code_path="t:0"))
    assert h.unbounded() == ["spend"]
    store.apply_to(h)
    assert h.bound("spend") == 42.0


def test_frequent_promotion_cannot_reset_a_cumulative_budget():
    """The cumulative bound's frame is the accounting-period ORIGIN, not the
    moving rollback checkpoint.

    Found by SR-5's preregistered feasibility check: it reported ZERO refusals
    at k=1, which could only happen if each promotion re-based the measurement.
    Promoting after every action must not buy unlimited drain.
    """
    st, gate = _staged(bound=100.0)
    total = 0.0
    refused = False
    for _ in range(40):                       # 40 x 10 = 400, far past the bound
        st.stage("p", "stage_artifact", {"delta": -10.0})
        res = gate.promote()
        if res.promoted:
            total += 10.0
        else:
            refused = True
            break
    assert refused, "per-action promotion must NOT be able to outrun the bound"
    assert total <= 100.0, total


def test_origin_frame_is_distinct_from_the_rollback_checkpoint():
    st, gate = _staged(bound=100.0)
    st.stage("p", "stage_artifact", {"delta": -10.0})
    assert gate.promote().promoted
    assert st.origin_state().total == 0.0, "origin never moves"
    assert st.baseline_state().total == -10.0, "checkpoint does move"


# --------------------------------------------------------------------------- #
#  C-8 — PERMISSIVENESS monotonicity, computed over the protected quantity     #
# --------------------------------------------------------------------------- #
def test_permissiveness_is_computed_over_the_admitted_set_not_the_number():
    """An UNSET bound FAILS CLOSED (engine.py:99-101 refuses every action on an
    unbounded class), so ADDING a bound is a LOOSENING and REMOVING one is a
    TIGHTENING. Read off the magnitudes alone, both come out inverted."""
    from gyza.containment.guardconfig import diff_bounds
    d = {c.bound_id: c.direction for c in diff_bounds(
        {"a": 100.0, "b": 5.0}, {"a": 200.0, "b": 1.0, "c": 7.0})}
    assert d == {"a": "LOOSENED", "b": "TIGHTENED", "c": "LOOSENED"}
    d2 = {c.bound_id: c.direction for c in diff_bounds({"a": 100.0}, {})}
    assert d2 == {"a": "TIGHTENED"}, "removing a bound REFUSES more, not less"


def test_a_higher_version_that_loosens_is_refused_by_the_ordinary_path():
    """The live defect. Version-integer monotonicity tests the LABEL; a
    correctly-signed v2 raising every bound would otherwise install cleanly —
    and the guard config is the trust root the whole induction rests on."""
    sk, pk = _keys()
    st = GuardConfigStore(pk)
    v1 = {"version": 1, "bounds": {"spend": 100.0}, "tier_assignments": {}}
    st.load(v1, sign_config(v1, sk))

    v2 = {"version": 2, "bounds": {"spend": 1e9}, "tier_assignments": {}}
    with pytest.raises(GuardConfigError, match="LOOSEN"):
        st.load(v2, sign_config(v2, sk))
    assert st.config.bounds == {"spend": 100.0}, "bounds must be untouched"

    # tightening through the ordinary path is fine
    v3 = {"version": 2, "bounds": {"spend": 10.0}, "tier_assignments": {}}
    st.load(v3, sign_config(v3, sk))
    assert st.config.bounds == {"spend": 10.0}


def test_loosening_requires_a_separately_signed_record_and_raises_an_alarm():
    from gyza.containment.guardconfig import LooseningRecord, sign_loosening
    sk, pk = _keys()
    st = GuardConfigStore(pk)
    v1 = {"version": 1, "bounds": {"spend": 100.0, "other": 5.0}, "tier_assignments": {}}
    st.load(v1, sign_config(v1, sk))

    v2 = {"version": 2, "bounds": {"spend": 250.0, "other": 5.0}, "tier_assignments": {}}
    rec = LooseningRecord(changes=(("spend", 100.0, 250.0),), reason="q3 budget raise")
    cfg = st.install_loosening(v2, sign_config(v2, sk), rec,
                               sign_loosening(rec, sk), requested_by="operator")
    assert cfg.bounds["spend"] == 250.0
    assert len(st.alarms) == 1
    assert "GUARD-LOOSENED" in st.alarms[0] and "q3 budget raise" in st.alarms[0]


def test_a_loosening_record_that_under_reports_is_refused():
    """Under-reporting is worse than no record: the signature would attest to a
    change nobody read."""
    from gyza.containment.guardconfig import LooseningRecord, sign_loosening
    sk, pk = _keys()
    st = GuardConfigStore(pk)
    v1 = {"version": 1, "bounds": {"spend": 100.0, "other": 5.0}, "tier_assignments": {}}
    st.load(v1, sign_config(v1, sk))

    # BOTH loosen; the record names only one
    v2 = {"version": 2, "bounds": {"spend": 250.0, "other": 50.0}, "tier_assignments": {}}
    rec = LooseningRecord(changes=(("spend", 100.0, 250.0),), reason="partial")
    with pytest.raises(GuardConfigError, match="Undeclared loosenings"):
        st.install_loosening(v2, sign_config(v2, sk), rec, sign_loosening(rec, sk))
    assert st.config.bounds == {"spend": 100.0, "other": 5.0}
    assert st.alarms == []


def test_a_loosening_record_that_misstates_values_is_refused():
    from gyza.containment.guardconfig import LooseningRecord, sign_loosening
    sk, pk = _keys()
    st = GuardConfigStore(pk)
    v1 = {"version": 1, "bounds": {"spend": 100.0}, "tier_assignments": {}}
    st.load(v1, sign_config(v1, sk))
    v2 = {"version": 2, "bounds": {"spend": 250.0}, "tier_assignments": {}}
    rec = LooseningRecord(changes=(("spend", 100.0, 120.0),), reason="understated")
    with pytest.raises(GuardConfigError, match="misstates"):
        st.install_loosening(v2, sign_config(v2, sk), rec, sign_loosening(rec, sk))


def test_a_loosening_record_signed_by_the_wrong_key_is_refused():
    from gyza.containment.guardconfig import LooseningRecord, sign_loosening
    sk, pk = _keys()
    agent_sk, _ = _keys()
    st = GuardConfigStore(pk)
    v1 = {"version": 1, "bounds": {"spend": 100.0}, "tier_assignments": {}}
    st.load(v1, sign_config(v1, sk))
    v2 = {"version": 2, "bounds": {"spend": 250.0}, "tier_assignments": {}}
    rec = LooseningRecord(changes=(("spend", 100.0, 250.0),), reason="r")
    with pytest.raises(GuardConfigError, match="LOOSENING RECORD does not verify"):
        st.install_loosening(v2, sign_config(v2, sk), rec,
                             sign_loosening(rec, agent_sk))


def test_guard_loosening_always_raises_an_o3_alarm():
    from gyza.coordination import RunMetrics, alarms
    m = RunMetrics(admitted=10)
    m.carrier_distribution = {"PROOF": 10}
    fired = alarms(m, invariants_evaluated=1, invariants_enforced=1,
                   guard_loosenings=["GUARD-LOOSENED (requested by 'op'): spend: 100.0 -> 250.0"])
    assert any("GUARD-LOOSENED" in a for a in fired)
