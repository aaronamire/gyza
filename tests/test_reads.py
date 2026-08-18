"""The read-set analysis, and the measurement that says it must NOT be a gate.

THIS FILE EXISTS TO PIN A NEGATIVE. The analysis has real power — it catches a
closed-over threshold and a module-level config dict, which is the exact shape
the carrier rule was derived from. On the LIVE registry it flags two entries and
BOTH are false positives, one of them a genuinely PROOF-carried verifier. So it
is a triage tool and not a refusal, and `test_the_analysis_is_not_wired_into_
the_refusal_path` is the test that keeps it that way.

A check that refuses some mislabelled carriers and silently admits others is
worse than none: it creates the impression of enforcement.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_reads.py -q
"""
from __future__ import annotations

import inspect

from gyza.verification.authority import CARRIER_ASSURANCE, SpecAuthority
from gyza.verification.migration import DRAFTS
from gyza.verification.reads import analyze, unnamed_state_report

RECOMPUTING_FIVE = ("envelope_signature", "envelope_chain",
                    "artifact_content_address", "manifest_identity",
                    "enforcement_within_manifest")


# --------------------------------------------------------------------------- #
#  POSITIVE CONTROLS — the mechanism must have demonstrated power              #
# --------------------------------------------------------------------------- #
def test_a_closed_over_threshold_is_caught():
    """The shape the rule was derived from: two closures, two verdicts, and
    the claim names neither threshold."""
    def make(threshold):
        def check(value):
            return value <= threshold
        return check
    r = analyze(make(100))
    assert r.reads_unnamed_state
    assert "threshold" in r.closure_data
    assert r.named_params == frozenset({"value"})


def test_a_module_level_config_read_is_caught():
    r = analyze(_reads_module_config)
    assert r.reads_unnamed_state and "MODULE_CONFIG" in r.global_data


def test_a_pure_recomputation_is_not_flagged():
    def pure(a, b):
        return a == b
    assert not analyze(pure).reads_unnamed_state


def test_calling_an_imported_function_is_not_a_state_read():
    """Code is not state. Flagging every verifier that imports something would
    make the analysis useless, and getting this backwards is the easiest way to
    build a checker that flags everything."""
    def calls_out(x):
        from gyza.canon import values_equal
        return values_equal(x, x)
    assert not analyze(calls_out).reads_unnamed_state


# --------------------------------------------------------------------------- #
#  THE APPROXIMATION DIRECTION — conservative, and counted                     #
# --------------------------------------------------------------------------- #
def test_dynamic_access_defaults_to_flagged_and_is_counted():
    """Unresolvable must count AGAINST the verifier. The other direction admits
    a mislabelled PROOF, which SR-3 measured composing at 0.000."""
    def dyn(obj, name):
        return bool(getattr(obj, name, None))
    r = analyze(dyn)
    assert r.reads_unnamed_state and "getattr" in r.dynamic
    assert r.n_conservative_defaults >= 1


def test_an_uninspectable_callable_is_conservative_not_clean():
    class Callable_:
        def __call__(self, x):
            return True
    r = analyze(Callable_())
    assert r.reads_unnamed_state and r.n_conservative_defaults >= 1


def test_function_local_imports_are_followed():
    """A LOAD_GLOBAL-only scan saw the adapter shell and none of the verifier —
    an UNDER-approximation, the dangerous direction. Every adapter in this
    codebase imports inside the body, so this is the common case, not an edge."""
    from gyza.verification.adapters import NATIVE
    fn = next(v.fn for v in NATIVE if v.claim_type == "envelope_signature")
    r = analyze(fn, depth=1)
    assert "verify_envelope" in r.global_code, \
        "the delegate was not resolved; the analysis is seeing only the shell"


# --------------------------------------------------------------------------- #
#  THE MEASUREMENT — why this is SCREENING-ONLY                                #
# --------------------------------------------------------------------------- #
def test_none_of_the_recomputing_five_is_falsely_flagged():
    """The failure mode that would make it unusable outright."""
    by = {d.claim_type: d for d in DRAFTS}
    for ct in RECOMPUTING_FIVE:
        assert not analyze(by[ct].fn, depth=2).reads_unnamed_state, ct


def test_the_flagged_set_on_the_live_registry_is_exactly_the_two_false_positives():
    flagged = sorted(d.claim_type for d in DRAFTS if d.fn is not None
                     and analyze(d.fn, depth=2).reads_unnamed_state)
    # `envelope_dag` is gone: split into closed/open, each binding
    # require_closed internally, so the read analyser no longer sees a
    # caller-chosen kwarg to flag conservatively.
    assert flagged == ["memory_retrieval_relevance"], flagged


def test_the_memory_retrieval_flag_is_a_FALSE_POSITIVE():
    """FILTER_SUCCESS_ONLY is a vocabulary TOKEN compared against a field the
    claim DOES name (`filter_predicate`, validated in RetrievalClaim), not a
    policy parameter. The analysis cannot tell those apart, and this entry is
    genuinely PROOF-carried — which is why wiring the analysis as a gate would
    refuse a correct entry."""
    d = next(x for x in DRAFTS if x.claim_type == "memory_retrieval_relevance")
    r = unnamed_state_report(d.fn, depth=2)
    assert r["unnamed_state"] == ["verify_retrieval_claim.FILTER_SUCCESS_ONLY"]
    from gyza.verification.respec import RetrievalClaim
    assert "filter_predicate" in inspect.get_annotations(RetrievalClaim)


def test_the_envelope_dag_flag_is_GONE_because_the_kwarg_was_BOUND():
    """WAS: `envelope_dag` was flagged by the read analyser as a conservative
    default -- the analyser could not tell a caller-chosen kwarg from a state
    read, so it flagged rather than clearing it.

    NOW: the entry no longer exists. It was split into `envelope_dag_closed`
    and `envelope_dag_open` on 2026-08-15, each binding `require_closed`
    internally, so there is no caller-chosen parameter left to be conservative
    about. The flag disappearing is the DEFECT being fixed, not the analyser
    being weakened -- `memory_retrieval_relevance` is still flagged, which is
    the control.
    """
    types = {x.claim_type for x in DRAFTS}
    assert "envelope_dag" not in types
    assert {"envelope_dag_closed", "envelope_dag_open"} <= types

def test_true_positive_count_on_the_live_registry_is_zero():
    """Diagnosed, not reported bare: both flags are false positives, so the
    analysis finds NO genuine unnamed-state read in this registry. That is a
    fact about this codebase, not about the analysis — the positive controls
    above show it fires when there is something to find."""
    flagged = [d for d in DRAFTS if d.fn is not None
               and analyze(d.fn, depth=2).reads_unnamed_state]
    genuine = [d for d in flagged
               if analyze(d.fn, depth=2).closure_data
               or analyze(d.fn, depth=2).global_data - {
                   "verify_retrieval_claim.FILTER_SUCCESS_ONLY"}]
    assert genuine == []


# --------------------------------------------------------------------------- #
#  B3 — the analysis MUST NOT be a gate, and that is enforced here             #
# --------------------------------------------------------------------------- #
def test_the_analysis_is_not_wired_into_the_refusal_path():
    """SCREENING-ONLY is a decision, and a decision needs a test or a future
    session will 'finish the job' and refuse a correct entry."""
    src = inspect.getsource(SpecAuthority.register)
    assert "analyze" not in src and "reads" not in src


def test_a_verifier_that_reads_unnamed_state_STILL_REGISTERS():
    """The consequence of SCREENING-ONLY, stated as an executable fact: the
    registry does NOT prevent this. It records who took responsibility."""
    from gyza.containment.invariants import InvariantClass
    from gyza.verification.authority import (
        Attestation, NotApplicable, SpecRecord,
    )

    def make(threshold):
        def check(value):
            return value <= threshold
        return check
    fn = make(100)
    assert analyze(fn).reads_unnamed_state           # the defect is present

    SpecAuthority().register(SpecRecord(
        claim_type="c1", success_condition="value is within an unnamed bound",
        fn=fn, carrier="PROOF", invariant_class=InvariantClass.CONSERVATION,
        attestation=Attestation("test-human", "SELF_ASSERTED", "unit test"),
        frame=NotApplicable("scalar by value"),
        obligations=frozenset({"o1"}), version=1,
        witness="gyza/verification/reads.py:1"))       # ACCEPTED


# --------------------------------------------------------------------------- #
#  B1 — the registry must say what its carrier claim rests on                  #
# --------------------------------------------------------------------------- #
def test_registration_records_that_the_carrier_is_declared_not_verified():
    from gyza.containment.invariants import InvariantClass
    from gyza.verification.authority import (
        Attestation, NotApplicable, SpecRecord,
    )
    a = SpecAuthority()
    a.register(SpecRecord(
        claim_type="c1", success_condition="a stated property holds",
        fn=lambda x, y: x == y, carrier="PROOF",
        invariant_class=InvariantClass.CONSERVATION,
        attestation=Attestation("test-human", "SELF_ASSERTED", "unit test"),
        frame=NotApplicable("by value"), obligations=frozenset({"o1"}),
        version=1, witness="gyza/verification/authority.py:1"))
    assert a.registration_log()[0]["carrier_assurance"] == CARRIER_ASSURANCE
    assert a.audit()["carrier_assurance"] == CARRIER_ASSURANCE
    assert "NOT verified" in CARRIER_ASSURANCE


MODULE_CONFIG = {"limit": 5}


def _reads_module_config(value):
    return value <= MODULE_CONFIG["limit"]
