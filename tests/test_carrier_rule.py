"""THE CARRIER RULE — totality and determinacy, and why they are two things.

The registry refuses a sampling verifier declared PROOF. That refusal needs a
stated criterion for what counts as sampling, or it is arbitrary. This file is
the criterion, executable.

    A verifier is PROOF-carried for a claim iff BOTH hold:

      TOTALITY     it decides the claimed property for EVERY input in the
                   claim's declared domain -- no proper-subset generalisation.
      DETERMINACY  the claim names every parameter that changes the verdict, so
                   exactly ONE proposition is being decided.

    fails TOTALITY     -> TEST.  Composes at 0.000 (SR-3). Naming a parameter
                                 does not help: the claim is about the function
                                 and the check is about the sample.
    fails DETERMINACY  -> UNDERDETERMINED. Every link IS fully decided, so this
                                 is not the 0.000 case; what fails is that the
                                 MEANINGS cannot be composed. Naming the
                                 parameter fixes it completely.

COLLAPSING THESE TWO WAS THE ERROR THE RULE EXISTS TO PREVENT. They have
different consequences and different remedies, and a single "is it PROOF?"
boolean cannot carry that.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_carrier_rule.py -q
"""
from __future__ import annotations

import pytest

from gyza.verification.authority import (
    CarrierRefused, UnderdeterminedClaim, check_carrier_claim,
    check_claim_determinacy,
)
from gyza.verification.migration import BY_CLAIM_TYPE, DRAFTS


# --------------------------------------------------------------------------- #
#  Fixtures: one verifier per failure mode                                     #
# --------------------------------------------------------------------------- #
def _total_and_determinate(value, expected) -> bool:
    return value == expected


def _samples(fn, cases) -> bool:
    """Fails TOTALITY."""
    return all(fn(x) == y for x, y in cases)


def _caller_chooses_via_kwargs(items, **policy) -> bool:
    """Fails DETERMINACY -- the envelope_dag shape."""
    return bool(items) if policy.get("strict") else True


def _caller_chooses_via_default(claim, check=None) -> bool:
    """Fails DETERMINACY -- the external_send_content shape."""
    return check(claim) if check is not None else True


# --------------------------------------------------------------------------- #
#  The two conditions are INDEPENDENT, which is the whole point                #
# --------------------------------------------------------------------------- #
def test_totality_and_determinacy_are_separate_screens():
    assert check_carrier_claim(_total_and_determinate, "PROOF").no_declared_evidence
    assert check_claim_determinacy(_total_and_determinate, "PROOF").no_declared_evidence


def test_a_sampler_fails_totality_but_passes_determinacy():
    """It names its case set, so it is determinate -- and still not PROOF."""
    assert not check_carrier_claim(_samples, "PROOF").no_declared_evidence
    assert check_claim_determinacy(_samples, "PROOF").no_declared_evidence


def test_an_underdetermined_verifier_passes_totality_but_fails_determinacy():
    """It recomputes over everything it is given; you just cannot tell what."""
    assert check_carrier_claim(_caller_chooses_via_kwargs, "PROOF").no_declared_evidence
    assert not check_claim_determinacy(_caller_chooses_via_kwargs, "PROOF").no_declared_evidence


# --------------------------------------------------------------------------- #
#  NEGATIVE CONTROLS -- each defect must be REFUSED, by its OWN exception      #
# --------------------------------------------------------------------------- #
def _rec(fn, carrier="PROOF"):
    from gyza.containment.invariants import InvariantClass
    from gyza.verification.authority import (
        Attestation, NotApplicable, SpecRecord,
    )
    return SpecRecord(
        claim_type="c1", success_condition="a stated property holds", fn=fn,
        carrier=carrier, invariant_class=InvariantClass.CONSERVATION,
        attestation=Attestation("test-human", "SELF_ASSERTED", "unit test"),
        frame=NotApplicable("operands by value"),
        obligations=frozenset({"o1"}), version=1,
        witness="gyza/verification/authority.py:1")


def test_negative_control_variadic_policy_is_refused():
    from gyza.verification.authority import SpecAuthority
    with pytest.raises(UnderdeterminedClaim, match="forwards arbitrary policy"):
        SpecAuthority().register(_rec(_caller_chooses_via_kwargs))


def test_negative_control_defaulted_parameter_is_refused():
    from gyza.verification.authority import SpecAuthority
    with pytest.raises(UnderdeterminedClaim, match="defaulted parameter"):
        SpecAuthority().register(_rec(_caller_chooses_via_default))


def test_the_two_defects_raise_DIFFERENT_exceptions():
    """A caller catching CarrierRefused is handling 'this samples', which no
    parameter-naming repairs. Merging the types would erase the remedy."""
    from gyza.verification.authority import SpecAuthority
    with pytest.raises(CarrierRefused):
        SpecAuthority().register(_rec(_samples))
    with pytest.raises(UnderdeterminedClaim):
        SpecAuthority().register(_rec(_caller_chooses_via_kwargs))
    assert not issubclass(UnderdeterminedClaim, CarrierRefused)
    assert not issubclass(CarrierRefused, UnderdeterminedClaim)


def test_determinacy_is_not_applied_to_TEST_carriers():
    """A TEST carrier already claims only what it sampled, so a caller-chosen
    parameter does not widen a promise it never made."""
    assert check_claim_determinacy(_caller_chooses_via_kwargs, "TEST").no_declared_evidence


def test_naming_the_parameter_repairs_determinacy():
    """The remedy is real, not theoretical: bind it and the entry registers."""
    from gyza.verification.authority import SpecAuthority

    def bound(items, strict) -> bool:          # policy now named, no default
        return bool(items) if strict else True

    SpecAuthority().register(_rec(bound))      # accepted


# --------------------------------------------------------------------------- #
#  C4 — the rule applied to the whole registry                                 #
# --------------------------------------------------------------------------- #
def test_the_rule_refuses_exactly_the_two_entries_found_by_hand():
    """Mechanical agreement with the hand pass. Not a new discovery -- an
    ENFORCED one: the hand pass was discipline, this is a guard."""
    variable = [d.claim_type for d in DRAFTS if d.fn is not None
                and not check_claim_determinacy(d.fn, d.carrier).no_declared_evidence]
    # BOTH REPAIRED 2026-08-15: `envelope_dag` split into closed/open so the
    # claim TYPE names what the kwarg used to choose, `external_send_content`
    # had its caller-supplied policy bound out. The rule found them by hand and
    # they are now fixed, so the set it refuses is EMPTY -- which is the outcome
    # the rule existed to produce, not a weakening of it.
    assert sorted(variable) == [], sorted(variable)


def test_every_other_entry_with_a_verifier_is_determinate():
    ok = [d.claim_type for d in DRAFTS if d.fn is not None
          and check_claim_determinacy(d.fn, d.carrier).no_declared_evidence]
    # 17 -> 19: `decomposition_within_manifest` and `combine_covers_siblings`
    # (2026-08-23). Both are DETERMINATE by construction, which is the property
    # this test protects: neither exposes a caller-settable parameter that can
    # move the verdict, because both read their bounds from signed bytes -- the
    # manifest's spawn grant and the parent's signed child list.
    assert len(ok) == 19   # 14 + the dag split + external_send_content + 2


def test_delegation_attenuation_names_its_depth_bound():
    """FIXED-UNNAMED, found by applying the rule and MISSED by the hand pass.

    verify_delegation carries max_depth=3; the adapter does not expose it, so
    the verdict cannot vary per call site and PROOF stands. But a claim saying
    only 'depth is bounded' does not say WHICH bound was checked, so the value
    belongs in the success condition.
    """
    d = BY_CLAIM_TYPE["delegation_attenuation"]
    assert "3" in d.success_condition
    assert "depth_at_most_3" in d.obligations
    assert d.carrier == "PROOF"


def test_the_one_sampler_is_still_the_only_totality_failure():
    fails = [d.claim_type for d in DRAFTS if d.fn is not None
             and not check_carrier_claim(d.fn, "PROOF").no_declared_evidence]
    assert fails == ["unit_test_execution"]
