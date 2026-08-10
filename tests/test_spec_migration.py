"""Structural migration + the governed cutover.

THE PROPERTY THIS FILE EXISTS TO PIN: an unattested draft NEVER enters the
governed registry. Every other test here is secondary to that one, because it
is the property that would be silently lost if a future session decided the
migration count was too low.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_spec_migration.py -q
"""
from __future__ import annotations

import pytest

from gyza.containment.invariants import InvariantClass
from gyza.verification.adapters import (
    HUMAN_SPECS, NATIVE, NO_VERIFIER, all_claim_types, build_registries,
)
from gyza.verification.authority import Attestation, FrameRef, NotApplicable
from gyza.verification.migration import (
    BY_CLAIM_TYPE, DRAFTS, JUDGEMENT, MEASURED, UNCLASSIFIABLE,
    governed_registry, manifest,
)
from gyza.verification.router import CutoverPolicy, TierRouter


def _att(who="test-human"):
    return Attestation(author=who, method="SELF_ASSERTED")


# --------------------------------------------------------------------------- #
#  THE LOAD-BEARING PROPERTY                                                   #
# --------------------------------------------------------------------------- #
def test_no_attestations_means_an_empty_governed_registry():
    """The migration must not bootstrap itself. With nothing attested the
    governed registry is EMPTY -- it does not fall back, does not default, and
    does not admit a placeholder."""
    auth, skipped = governed_registry({})
    assert auth.claim_types() == []
    assert len(skipped) == len(DRAFTS)


def test_every_draft_lacks_an_attestation_field_entirely():
    """Not 'has an empty attestation' -- has no such field. A field that could
    hold a default is a field that will."""
    for d in DRAFTS:
        assert not hasattr(d, "attestation")


def test_only_the_attested_draft_is_admitted():
    auth, skipped = governed_registry({"reputation_score": _att()})
    assert auth.claim_types() == ["reputation_score"]
    assert dict(skipped)["hlc_ordering"] == "AWAITING ATTESTATION"


def test_the_attestation_author_is_carried_through_to_the_record():
    auth, _ = governed_registry({"reputation_score": _att("xan")})
    assert auth.get("reputation_score").attestation.author == "xan"


def test_attesting_a_blocked_draft_still_does_not_admit_it():
    """Attestation does not override a structural blocker: envelope_dag's
    success condition is not fixed by the registry, and a human saying 'I
    vouch' does not fix which proposition it proves."""
    auth, skipped = governed_registry({"envelope_dag": _att()})
    assert "envelope_dag" not in auth
    assert dict(skipped)["envelope_dag"].startswith("BLOCKED:")


# --------------------------------------------------------------------------- #
#  Part A — the structural migration covers everything, and says what it is    #
# --------------------------------------------------------------------------- #
def test_every_existing_entry_has_a_draft():
    assert {d.claim_type for d in DRAFTS} == set(all_claim_types())
    assert len(DRAFTS) == len(NATIVE) + len(HUMAN_SPECS) + len(NO_VERIFIER)


def test_the_one_sampling_verifier_is_carried_as_TEST():
    """SR-3 measured TEST composing at 0.000. This is the entry that must not
    drift to PROOF."""
    d = BY_CLAIM_TYPE["unit_test_execution"]
    assert d.carrier == "TEST" and d.carrier_basis == MEASURED


def test_no_draft_declares_PROOF_while_the_authority_screen_refuses_it():
    """The structural migration must not contradict the guard it feeds."""
    from gyza.verification.authority import check_carrier_claim
    for d in DRAFTS:
        if d.fn is None:
            continue
        assert check_carrier_claim(d.fn, d.carrier).no_declared_evidence, \
            f"{d.claim_type} declares {d.carrier} against the carrier screen"


def test_no_verifier_entries_are_UNCLASSIFIABLE_not_TEST():
    """'I could not classify this' and 'this is TEST' are different claims."""
    for ct in NO_VERIFIER:
        d = BY_CLAIM_TYPE[ct]
        assert d.carrier_basis == UNCLASSIFIABLE
        assert d.carrier == "NONE" and d.fn is None
        assert d.blocked_reason is not None


def test_every_draft_states_a_carrier_reason():
    for d in DRAFTS:
        assert d.carrier_reason.strip(), f"{d.claim_type} has no stated reason"
        assert d.carrier_basis in (MEASURED, JUDGEMENT, UNCLASSIFIABLE)


def test_every_draft_states_a_success_condition():
    for d in DRAFTS:
        assert len(d.success_condition.strip()) > 20, d.claim_type


def test_drafts_with_movable_reference_sets_name_a_frame_identifier():
    movable = [d for d in DRAFTS if isinstance(d.frame, FrameRef)]
    assert movable, "the migration found no movable reference set at all"
    for d in movable:
        assert d.frame.identifier.strip()


def test_the_retrieval_frame_is_the_one_already_carried_in_production():
    """corpus_snapshot is the working precedent, not a PENDING placeholder."""
    d = BY_CLAIM_TYPE["memory_retrieval_relevance"]
    assert isinstance(d.frame, FrameRef)
    assert d.frame.identifier == "corpus_snapshot"
    assert "ALREADY CARRIED" in d.frame.digest


def test_manifest_reports_the_judgement_fraction_and_the_ready_count():
    m = manifest()
    assert m["n"] == len(DRAFTS)
    assert 0.0 <= m["judgement_fraction"] <= 1.0
    assert m["structurally_ready"] + m["blocked"] == m["n"]
    assert all(r["attestation"] is None for r in m["entries"])


# --------------------------------------------------------------------------- #
#  Part B — the cutover                                                        #
# --------------------------------------------------------------------------- #
def test_an_authority_without_a_policy_is_refused():
    """A policy nobody chose is how ungoverned entries accumulated."""
    v, s = build_registries()
    auth, _ = governed_registry({})
    with pytest.raises(ValueError, match="CutoverPolicy"):
        TierRouter(v, s, authority=auth)


def test_legacy_construction_is_unchanged():
    """No authority supplied -> exactly the behaviour that existed before."""
    v, s = build_registries()
    r = TierRouter(v, s)
    assert r.route("envelope_signature").tier == 1
    assert r.route("hlc_ordering").tier == 2
    assert r.route("execution_output_content").tier == 3
    assert r.route("envelope_signature").governed is False


def test_fail_closed_routes_unattested_claim_types_to_tier_3():
    v, s = build_registries()
    auth, _ = governed_registry({})
    r = TierRouter(v, s, authority=auth, policy=CutoverPolicy.FAIL_CLOSED)
    rt = r.route("envelope_signature")
    assert rt.tier == 3 and rt.carrier == "NONE" and not rt.governed
    assert rt.reason.startswith("FAIL_CLOSED")


def test_fail_closed_admits_an_attested_claim_type_at_its_carrier_tier():
    v, s = build_registries()
    auth, _ = governed_registry({"reputation_score": _att("xan")})
    r = TierRouter(v, s, authority=auth, policy=CutoverPolicy.FAIL_CLOSED)
    rt = r.route("reputation_score")
    assert rt.governed and rt.tier == 2 and rt.carrier == "SPEC"
    assert "attested by 'xan'" in rt.reason


def test_dual_read_falls_back_and_MARKS_the_fallback():
    """An unmarked fallback is a fallback that never expires."""
    v, s = build_registries()
    auth, _ = governed_registry({})
    r = TierRouter(v, s, authority=auth, policy=CutoverPolicy.DUAL_READ)
    rt = r.route("envelope_signature")
    assert rt.tier == 1 and not rt.governed
    assert rt.reason.startswith("UNGOVERNED FALLBACK (DUAL_READ)")


def test_governance_counts_the_migration_debt():
    v, s = build_registries()
    auth, _ = governed_registry({"reputation_score": _att()})
    r = TierRouter(v, s, authority=auth, policy=CutoverPolicy.DUAL_READ)
    g = r.governance(all_claim_types())
    assert g["governed"] == 1
    assert g["ungoverned_fallback"] == len(all_claim_types()) - 1
    assert "envelope_signature" in g["fallback_claim_types"]
    assert g["policy"] == "DUAL_READ"


def test_fail_closed_governance_names_what_it_closed_on():
    v, s = build_registries()
    auth, _ = governed_registry({})
    r = TierRouter(v, s, authority=auth, policy=CutoverPolicy.FAIL_CLOSED)
    g = r.governance(all_claim_types())
    assert g["governed"] == 0
    assert g["failed_closed"] == len(all_claim_types())
    assert g["ungoverned_fallback"] == 0


def test_attesting_more_entries_monotonically_grows_the_governed_tier():
    """The forcing function, made measurable: attestation is the only input
    that raises coverage under FAIL_CLOSED."""
    v, s = build_registries()
    seen = []
    for atts in ({}, {"reputation_score": _att()},
                 {"reputation_score": _att(), "hlc_ordering": _att()}):
        auth, _ = governed_registry(atts)
        r = TierRouter(v, s, authority=auth, policy=CutoverPolicy.FAIL_CLOSED)
        seen.append(r.governance(all_claim_types())["governed"])
    assert seen == [0, 1, 2]
