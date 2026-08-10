"""The cutover: the router now reads the ATTESTED registry.

WHAT THIS FILE PINS, and why each matters:

  * the LIVE construction point (`governed_router`) reads the governed
    registry, not the ungoverned one -- before it, twenty attested records
    governed nothing because nothing ever passed an authority;
  * the fallback's scope is ENUMERATED and finite, so "is the migration
    finished" has an answer;
  * a spec failing any refusal condition cannot enter the path the router
    reads -- on the LIVE path, with a negative control per condition, because
    registering a checker is not evidence it runs.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_registry_cutover.py -q
"""
from __future__ import annotations

from gyza.containment.invariants import InvariantClass
from gyza.verification import migration as M
from gyza.verification.adapters import all_claim_types, build_registries
from gyza.verification.authority import (
    Attestation, FrameRef, NotApplicable,
)
from gyza.verification.migration import (
    SpecDraft, fallback_scope, governed_registry, governed_router,
    load_attestations,
)
from gyza.verification.router import CutoverPolicy

GAP = ("envelope_dag", "external_send_content")


def _att():
    return Attestation("test-human", "SELF_ASSERTED", "unit test")


# --------------------------------------------------------------------------- #
#  A2 — the router consults the GOVERNED entry, not a value derived elsewhere  #
# --------------------------------------------------------------------------- #
def test_the_live_router_reads_the_governed_registry():
    r = governed_router()
    rt = r.route("envelope_signature")
    assert rt.governed is True
    assert "GOVERNED: attested by 'Aaron (repository owner)'" in rt.reason


def test_the_routers_carrier_comes_FROM_the_attested_record():
    """One attested record governs -- the router must not recompute a carrier."""
    auth, _ = governed_registry(load_attestations())
    r = governed_router()
    for ct in auth.claim_types():
        assert r.route(ct).carrier == auth.get(ct).carrier


def test_every_governed_type_routes_at_its_carriers_tier():
    r = governed_router()
    auth, _ = governed_registry(load_attestations())
    for ct in auth.claim_types():
        expected = 2 if auth.get(ct).carrier == "SPEC" else 1
        assert r.route(ct).tier == expected, ct


def test_unit_test_execution_routes_tier_1_but_TEST_carried():
    """Tier and carrier are independent, and the carrier is what composes.
    SR-3 measured TEST at 0.000 -- a chain containing this is not composable."""
    rt = governed_router().route("unit_test_execution")
    assert rt.tier == 1 and rt.carrier == "TEST" and rt.governed


# --------------------------------------------------------------------------- #
#  Gate 0c — carrier parity, and the honest note about what it is worth        #
# --------------------------------------------------------------------------- #
def test_no_governed_carrier_disagrees_with_the_ungoverned_registry():
    """MEASURED, and NOT independent confirmation: the drafts were classified
    while the pre-existing carriers were visible, so agreement is consistency,
    not corroboration. It is pinned because a DISAGREEMENT would be a defect."""
    auth, _ = governed_registry(load_attestations())
    v, _s = build_registries()
    for ct in auth.claim_types():
        ungoverned = v.get(ct).carrier if ct in v else "SPEC"
        assert auth.get(ct).carrier == ungoverned, ct


# --------------------------------------------------------------------------- #
#  B — the fallback, its scope, and the expiry condition that did not exist    #
# --------------------------------------------------------------------------- #
def test_the_fallback_scope_is_named_and_finite():
    """A fallback with unnamed scope is a permanent escape hatch."""
    gap = fallback_scope()
    assert tuple(sorted(gap)) == GAP
    for ct, why in gap.items():
        assert why.startswith("SUCCESS CONDITION IS NOT FIXED"), ct


def test_the_expiry_condition_is_now_SPECIFIED_and_currently_UNMET():
    """It was never written before: DUAL_READ shipped with marking and counting,
    which are visibility, not a termination condition. `fallback_scope() == {}`
    is the condition, and it is not met."""
    assert fallback_scope() != {}, "gap closed -- the fallback may now be removed"


def test_the_expiry_condition_IS_SATISFIABLE_when_the_defect_is_actually_fixed(
        monkeypatch):
    """B4 — THE CHECK NOBODY HAD RUN: can `fallback_scope()` ever return {}?

    A condition that cannot go false is a proxy, not a gate, and this program
    has shipped that defect before (the version-integer monotonicity check).
    Deriving the condition from registry state is only worth something if the
    state can actually reach the terminal value.

    Demonstrated by applying the REAL remedy -- binding the caller-chosen
    policy parameters so each claim names what it proves -- and observing the
    scope empty. Note that merely clearing `blocked_reason` does NOT suffice:
    the authority's determinacy screen still refuses the unbound signatures.
    That is the guard being the gate rather than the annotation being the gate.
    """
    def dag_bound(envelopes, require_closed):          # named, no default
        from gyza.icp import verify_dag
        return bool(verify_dag(envelopes, require_closed=require_closed).valid)

    def send_bound(claim, emitted, policy):            # named, no default
        from gyza.verification.respec import verify_send_claim
        return verify_send_claim(claim, emitted, policy)

    fix = {"envelope_dag": dag_bound, "external_send_content": send_bound}
    patched = [SpecDraft(**{**d.__dict__, "blocked_reason": None,
                            "fn": fix[d.claim_type]})
               if d.claim_type in fix else d
               for d in M.DRAFTS]
    monkeypatch.setattr(M, "DRAFTS", patched)
    monkeypatch.setattr(M, "BY_CLAIM_TYPE", {x.claim_type: x for x in patched})

    auth, _ = governed_registry(load_attestations())
    assert len(auth.claim_types()) == 16          # 14 -> 16
    assert fallback_scope() == {}                 # the condition GOES FALSE


def test_clearing_blocked_reason_alone_does_NOT_satisfy_it(monkeypatch):
    """The negative control for the test above: the annotation is not the gate.

    If clearing `blocked_reason` were enough, the expiry condition would be
    testing a LABEL rather than the protected quantity -- the fourth instance
    of that species in this program. It is not: the signatures are still
    unbound, so the authority still refuses them.
    """
    patched = [SpecDraft(**{**d.__dict__, "blocked_reason": None})
               if d.blocked_reason and d.fn is not None else d
               for d in M.DRAFTS]
    monkeypatch.setattr(M, "DRAFTS", patched)
    monkeypatch.setattr(M, "BY_CLAIM_TYPE", {x.claim_type: x for x in patched})
    assert tuple(sorted(fallback_scope())) == GAP     # still held open


def test_the_gap_is_exactly_the_blocked_entries_not_unattested_ones():
    """Every structurally-ready draft IS attested, so nothing sits in the gap
    merely awaiting a signature."""
    assert all(d.claim_type not in GAP
               for d in M.DRAFTS if d.structurally_ready)


def test_fail_closed_routes_the_gap_to_tier_3():
    r = governed_router()
    for ct in GAP:
        rt = r.route(ct)
        assert rt.tier == 3 and not rt.governed
        assert rt.reason.startswith("FAIL_CLOSED")


def test_the_fallback_mechanism_still_exists_and_is_not_removed():
    """B3: a real gap means the fallback stays. Selecting FAIL_CLOSED is a
    policy choice, not a deletion."""
    r = governed_router(CutoverPolicy.DUAL_READ)
    rt = r.route("envelope_dag")
    assert rt.tier == 1 and rt.reason.startswith("UNGOVERNED FALLBACK")


def test_governance_reports_the_gap_rather_than_hiding_it():
    g = governed_router().governance(all_claim_types())
    assert g["policy"] == "FAIL_CLOSED"
    assert g["governed"] == 14
    assert g["ungoverned_fallback"] == 0
    assert set(GAP) <= set(g["failed_closed_claim_types"])


def test_the_two_no_verifier_types_were_never_covered_by_the_fallback():
    """Counter-metric to the gap: 4 types fail closed but only 2 are fallback
    scope. execution_output_content and routing_match_quality are in NEITHER
    registry -- they were tier 3 before the cutover and are tier 3 after."""
    v, s = build_registries()
    for ct in ("execution_output_content", "routing_match_quality"):
        assert ct not in v and ct not in s
        assert ct not in fallback_scope()


# --------------------------------------------------------------------------- #
#  C3 — a failing spec cannot enter the path the router reads.                 #
#  Each condition gets a NEGATIVE CONTROL on the LIVE path.                    #
# --------------------------------------------------------------------------- #
def _inject(monkeypatch, draft: SpecDraft, attested: bool = True):
    """Put a draft into the LIVE list `governed_registry` actually reads."""
    monkeypatch.setattr(M, "DRAFTS", list(M.DRAFTS) + [draft])
    atts = dict(load_attestations())
    if attested:
        atts[draft.claim_type] = _att()
    return governed_registry(atts)


def _draft(fn, **kw) -> SpecDraft:
    base = dict(
        claim_type="injected", success_condition="an injected property holds",
        fn=fn, carrier="PROOF", carrier_basis=M.MEASURED,
        carrier_reason="test", invariant_class=InvariantClass.CONSERVATION,
        frame=NotApplicable("by value"),
        obligations=frozenset({"o1"}), witness="gyza/verification/migration.py:1")
    base.update(kw)
    return SpecDraft(**base)          # type: ignore[arg-type]


def _ok(a, b):
    return a == b


def _samples(fn, cases):
    return all(fn(x) == y for x, y in cases)


def _movable(claim, candidates):
    return claim in candidates


def test_POSITIVE_CONTROL_a_clean_injected_spec_DOES_reach_the_router(monkeypatch):
    """Without this the refusals below prove nothing -- they could be failing
    for any reason."""
    auth, _ = _inject(monkeypatch, _draft(_ok))
    assert "injected" in auth


def test_negative_control_unattested_spec_never_reaches_the_router(monkeypatch):
    auth, skipped = _inject(monkeypatch, _draft(_ok), attested=False)
    assert "injected" not in auth
    assert dict(skipped)["injected"] == "AWAITING ATTESTATION"


def test_negative_control_sampling_declared_PROOF_never_reaches_the_router(monkeypatch):
    auth, skipped = _inject(monkeypatch, _draft(_samples, carrier="PROOF"))
    assert "injected" not in auth
    assert "CarrierRefused" in dict(skipped)["injected"]


def test_negative_control_unpinned_movable_frame_never_reaches_the_router(monkeypatch):
    auth, skipped = _inject(
        monkeypatch, _draft(_movable, frame=NotApplicable("not considered")))
    assert "injected" not in auth
    assert "FrameRefused" in dict(skipped)["injected"]


def test_the_refusals_fire_on_the_LIVE_path_not_only_under_pytest(monkeypatch):
    """`governed_router()` is the production construction point. A spec refused
    by the authority is absent from the router it builds -- so the refusal is
    reached by the real call chain, not by a test calling `register` directly."""
    monkeypatch.setattr(M, "DRAFTS", list(M.DRAFTS) + [_draft(_samples)])
    r = governed_router()
    rt = r.route("injected")
    assert rt.tier == 3 and not rt.governed
    assert rt.reason.startswith("FAIL_CLOSED")


def test_a_pinned_frame_lets_the_same_movable_spec_through(monkeypatch):
    """The refusal is about the missing frame, not about the function."""
    auth, _ = _inject(monkeypatch,
                      _draft(_movable, frame=FrameRef("snap", "ab" * 32)))
    assert "injected" in auth
