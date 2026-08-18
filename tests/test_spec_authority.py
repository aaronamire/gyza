"""The specification authority — and, mostly, its refusals.

A GUARD THAT HAS NEVER REFUSED ANYTHING HAS NO DEMONSTRATED POWER. That is the
standard the respecification verifiers were held to and it is the standard here:
every refusal condition gets a NEGATIVE CONTROL that constructs the defect and
requires the authority to reject it. A test file that only registered valid
specs would prove the authority accepts things, which is not the property in
question.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_spec_authority.py -q
"""
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.containment.invariants import InvariantClass
from gyza.verification.authority import (
    Attestation, AttestationRefused, CarrierRefused, FrameRef, FrameRefused,
    MissingField, NotApplicable, SpecAuthority, SpecRecord, SupersedeAck,
    WeakeningRefused, check_carrier_claim, check_frame_requirement,
    check_witness_resolves, sign_attestation, verify_attestation, weakening,
)


# --------------------------------------------------------------------------- #
#  Fixtures: one honest verifier of each shape                                 #
# --------------------------------------------------------------------------- #
def _recomputing(value, expected) -> bool:
    """Recomputes: no caller-supplied case set, no movable reference set."""
    return value == expected


def _sampling(fn, cases) -> bool:
    """Samples: sound only where it sampled. Must not register as PROOF."""
    return all(fn(x) == y for x, y in cases)


def _over_movable_set(claim, candidates) -> bool:
    """Ranks a caller-supplied set that can grow between claim and check."""
    return claim in candidates


def _att(author: str = "xan") -> Attestation:
    return Attestation(author=author, method="SELF_ASSERTED", basis="test basis: constructed in a unit test")


def _rec(**kw) -> SpecRecord:
    base = dict(
        claim_type="c1",
        success_condition="the computed value equals the declared one",
        fn=_recomputing,
        carrier="PROOF",
        invariant_class=InvariantClass.CONSERVATION,
        attestation=_att(),
        frame=NotApplicable("operands are passed by value; nothing can move"),
        obligations=frozenset({"equals_declared"}),
        version=1,
        witness="gyza/verification/authority.py:1",
    )
    base.update(kw)
    return SpecRecord(**base)      # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
#  The happy path exists, so the refusals below mean something                 #
# --------------------------------------------------------------------------- #
def test_a_well_formed_spec_registers():
    a = SpecAuthority()
    a.register(_rec())
    assert a.claim_types() == ["c1"]
    assert a.get("c1").version == 1
    assert len(a.registration_log()) == 1


# --------------------------------------------------------------------------- #
#  NEGATIVE CONTROL (i) — no human-authorship attestation                      #
# --------------------------------------------------------------------------- #
def test_negative_control_unattested_spec_is_refused():
    """R14: a model-authored spec measured BELOW a one-line type check."""
    with pytest.raises(AttestationRefused):
        Attestation(author="", method="SELF_ASSERTED", basis="test basis: constructed in a unit test")


def test_negative_control_spec_without_an_attestation_object_is_refused():
    with pytest.raises(AttestationRefused):
        _rec(attestation=None)


def test_negative_control_key_bound_attestation_that_does_not_verify_is_refused():
    """A binding that does not bind claims a property it lacks."""
    sk, other = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    tmp = _rec()
    sig = sign_attestation(tmp, sk)
    wrong_pub = other.public_key().public_bytes_raw().hex()
    rec = _rec(attestation=Attestation("xan", "KEY_BOUND", "t", wrong_pub, sig))
    with pytest.raises(AttestationRefused, match="does not verify"):
        SpecAuthority().register(rec)


def test_key_bound_attestation_round_trips():
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes_raw().hex()
    unsigned = _rec(attestation=Attestation("xan", "KEY_BOUND", "t", pub, "00" * 64))
    sig = sign_attestation(unsigned, sk)
    rec = _rec(attestation=Attestation("xan", "KEY_BOUND", "t", pub, sig))
    assert verify_attestation(rec)
    SpecAuthority().register(rec)          # accepted


def test_key_bound_without_a_signature_is_refused_at_construction():
    with pytest.raises(AttestationRefused, match="requires both"):
        Attestation("xan", "KEY_BOUND", "t", pubkey_hex="ab" * 32)


# --------------------------------------------------------------------------- #
#  NEGATIVE CONTROL (ii) — a sampling verifier declared PROOF                  #
# --------------------------------------------------------------------------- #
def test_negative_control_sampling_verifier_declared_proof_is_refused():
    """SR-3: PROOF 1.000 / TEST 0.000 under composition. A mislabelled
    TEST-carrier poisons every chain containing it, invisibly, until depth."""
    with pytest.raises(CarrierRefused, match="finite case set"):
        SpecAuthority().register(_rec(fn=_sampling, carrier="PROOF"))


def test_the_same_sampling_verifier_registers_as_TEST():
    """The refusal is about the LABEL, not the function. Declared honestly it
    is admissible -- otherwise the authority would be banning finite samples
    rather than banning lying about them."""
    a = SpecAuthority()
    a.register(_rec(fn=_sampling, carrier="TEST"))
    assert a.get("c1").carrier == "TEST"


def test_carrier_screen_reports_a_judgement_not_a_bare_bool():
    """`passed` must not be readable as `verified` -- it is a necessary
    condition only, and the field name says so."""
    r = check_carrier_claim(_recomputing, "PROOF")
    assert r.no_declared_evidence is True
    assert "no declared sampling parameter" in r.detail
    bad = check_carrier_claim(_sampling, "PROOF")
    assert bad.no_declared_evidence is False


# --------------------------------------------------------------------------- #
#  NEGATIVE CONTROL (iii) — movable reference set with no frame                #
# --------------------------------------------------------------------------- #
def test_negative_control_movable_reference_without_a_frame_is_refused():
    """G4'/SR-5: a bound measured from an origin that can move is not a bound."""
    with pytest.raises(FrameRefused, match="movable reference set"):
        SpecAuthority().register(
            _rec(fn=_over_movable_set,
                 frame=NotApplicable("I did not think about this")))


def test_the_same_spec_registers_once_the_frame_is_pinned():
    a = SpecAuthority()
    a.register(_rec(fn=_over_movable_set,
                    frame=FrameRef("corpus_snapshot", "ab" * 32)))
    assert a.get("c1").frame.identifier == "corpus_snapshot"


def test_frame_ref_requires_both_a_name_and_a_digest():
    with pytest.raises(MissingField):
        FrameRef("corpus_snapshot", "")
    with pytest.raises(MissingField):
        FrameRef("", "ab" * 32)


# --------------------------------------------------------------------------- #
#  A2 — versioning over the PROTECTED QUANTITY, not over the label             #
# --------------------------------------------------------------------------- #
def test_negative_control_higher_version_with_fewer_obligations_is_refused():
    """THE EXACT GuardConfigStore DEFECT, inverted into a test.

    That store checked the VERSION INTEGER and called it monotone, so a
    correctly-signed higher version could raise every bound and install
    cleanly. Here the higher version is REFUSED because the obligation set --
    the protected quantity -- shrank.
    """
    a = SpecAuthority()
    a.register(_rec(obligations=frozenset({"o1", "o2", "o3"}), version=1))
    with pytest.raises(WeakeningRefused, match="drops obligations"):
        a.register(_rec(obligations=frozenset({"o1"}), version=99))


def test_weakening_is_computed_over_obligations_not_versions():
    old = _rec(obligations=frozenset({"a", "b"}), version=1)
    new = _rec(obligations=frozenset({"a"}), version=7)
    assert weakening(old, new) == frozenset({"b"})
    assert weakening(new, old) == frozenset()          # strengthening is free


def test_acknowledged_weakening_is_permitted():
    a = SpecAuthority()
    a.register(_rec(obligations=frozenset({"o1", "o2"}), version=1))
    a.register(_rec(obligations=frozenset({"o1"}), version=2),
               supersede=SupersedeAck(frozenset({"o2"}), "xan",
                                      "o2 was subsumed by the type check"))
    assert a.get("c1").version == 2


def test_negative_control_supersede_ack_that_misdescribes_is_refused():
    """An acknowledgement naming the wrong obligation acknowledges nothing."""
    a = SpecAuthority()
    a.register(_rec(obligations=frozenset({"o1", "o2"}), version=1))
    with pytest.raises(WeakeningRefused, match="actually drops"):
        a.register(_rec(obligations=frozenset({"o1"}), version=2),
                   supersede=SupersedeAck(frozenset({"o9"}), "xan", "wrong"))


def test_strengthening_needs_no_acknowledgement():
    a = SpecAuthority()
    a.register(_rec(obligations=frozenset({"o1"}), version=1))
    a.register(_rec(obligations=frozenset({"o1", "o2"}), version=2))
    assert a.get("c1").obligations == frozenset({"o1", "o2"})


def test_a_non_increasing_version_is_refused_even_when_not_weakening():
    a = SpecAuthority()
    a.register(_rec(version=3))
    with pytest.raises(WeakeningRefused, match="versions must increase"):
        a.register(_rec(version=3))


# --------------------------------------------------------------------------- #
#  A1 — no defaults; absence is a refusal, never a filled zero                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("field,bad", [
    ("claim_type", ""),
    ("success_condition", "   "),
    ("witness", ""),
    ("obligations", frozenset()),
    ("version", 0),
])
def test_every_required_field_refuses_its_empty_value(field, bad):
    """The empty-record hole is the precedent: a content-free enforcement
    record passes `enforcement subset manifest` because empty sets are subsets
    of anything. Absence must read as refusal, not as permission."""
    with pytest.raises(MissingField):
        _rec(**{field: bad})


@pytest.mark.parametrize("field", ["invariant_class", "frame"])
def test_none_is_never_an_acceptable_value(field):
    """`None` cannot distinguish 'does not apply' from 'nobody filled it in'."""
    with pytest.raises(MissingField):
        _rec(**{field: None})


def test_not_applicable_requires_a_reason():
    with pytest.raises(MissingField, match="requires a reason"):
        NotApplicable("")


def test_carrier_NONE_is_not_registrable():
    """An entry carrying nothing is an absence, and absences are recorded by
    not registering -- not by registering a placeholder."""
    with pytest.raises(CarrierRefused):
        _rec(carrier="NONE")


# --------------------------------------------------------------------------- #
#  A4 — the witness screen, which is what binds a declaration to something     #
# --------------------------------------------------------------------------- #
def test_witness_screen_accepts_a_real_citation():
    assert check_witness_resolves("gyza/verification/authority.py:1"
                                  ).no_declared_evidence


def test_witness_screen_catches_a_missing_file():
    r = check_witness_resolves("gyza/does/not/exist.py:1")
    assert not r.no_declared_evidence and "no such file" in r.detail


def test_witness_screen_catches_a_line_past_the_end_of_the_file():
    r = check_witness_resolves("gyza/verification/authority.py:9999999")
    assert not r.no_declared_evidence and "lines" in r.detail


def test_witness_screen_passes_non_file_citations_without_pretending():
    r = check_witness_resolves("V-3 adapter (finite sample)")
    assert r.no_declared_evidence and "not checkable" in r.detail


# --------------------------------------------------------------------------- #
#  The screens must RUN over real entries, not merely be registered            #
# --------------------------------------------------------------------------- #
def test_audit_executes_every_screen_against_every_held_entry():
    """Registering a checker is not evidence that it runs (artifact #16: 785
    passing tests did not detect a harm quantity that raised on every input)."""
    a = SpecAuthority()
    a.register(_rec(claim_type="c1"))
    a.register(_rec(claim_type="c2", fn=_over_movable_set,
                    frame=FrameRef("snap", "ab" * 32)))
    rep = a.audit()
    assert rep["n"] == 2
    assert {e["claim_type"] for e in rep["entries"]} == {"c1", "c2"}
    for e in rep["entries"]:
        assert e["carrier"] and e["frame"] and e["witness"]
    assert rep["self_asserted"] == ["c1", "c2"]        # and it says so


def test_audit_names_unresolved_witnesses_rather_than_hiding_them():
    a = SpecAuthority()
    a.register(_rec(witness="gyza/nope.py:3"))
    assert a.audit()["unresolved_witnesses"] == ["c1"]


def test_registration_log_records_who_attested_and_under_which_method():
    a = SpecAuthority()
    a.register(_rec())
    row = a.registration_log()[0]
    assert row["author"] == "xan"
    assert row["attestation_method"] == "SELF_ASSERTED"
    assert len(row["digest"]) == 64


def test_digest_changes_when_any_governed_field_changes():
    """The attestation signs these bytes, so a field outside them would be
    unsigned and silently mutable."""
    base = _rec()
    assert base.digest() != _rec(carrier="TEST").digest()
    assert base.digest() != _rec(obligations=frozenset({"other"})).digest()
    assert base.digest() != _rec(version=2).digest()
    assert base.digest() != _rec(
        frame=FrameRef("snap", "cd" * 32), fn=_over_movable_set).digest()
