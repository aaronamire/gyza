"""
Phase 3 — verification layer (V-1 … V-5) acceptance tests.

Named to match BUILD_PLAN §7 where they correspond to an acceptance criterion.
"""
from __future__ import annotations

import inspect
import socket
import urllib.request

import pytest

from gyza.containment.invariants import InvariantClass, UntaggedInvariantError
from gyza.verification import (
    AuthorshipError, PartialSpec, PartialSpecRegistry, RegistryVersionError,
    TierRouter, Verifier, VerifierRegistry, consult_tier_algebra,
    evaluate_spec_strength,
)
from gyza.verification.adapters import (
    NO_VERIFIER, all_claim_types, build_registries,
)


@pytest.fixture
def router():
    v, s = build_registries()
    return TierRouter(v, s)


# --------------------------------------------------------------------------- #
#  ACCEPTANCE: the tier router makes a decision with ZERO model calls          #
# --------------------------------------------------------------------------- #
class _NetworkTouched(AssertionError):
    pass


def _block_network(monkeypatch):
    """Any attempt to reach the network raises. A model call cannot happen
    without one."""
    def boom(*a, **k):
        raise _NetworkTouched("the routing path touched the network")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)


def test_tier_router_makes_zero_model_calls(router, monkeypatch):
    """BUILD_PLAN §7. C10: difficulty routing failed even with a literal oracle
    (AUROC 1.000 bought the same economy as 0.907), so the replacement must be
    structural — a lookup, not a question."""
    _block_network(monkeypatch)
    for ct in all_claim_types():
        r = router.route(ct)
        assert r.tier in (1, 2, 3)
    # and the module imports nothing that could reach a model
    src = inspect.getsource(type(router).__module__ and __import__(
        "gyza.verification.router", fromlist=["x"]))
    for banned in ("requests", "urllib", "socket", "openai", "anthropic",
                   "httpx", "APIBackend", "generate("):
        assert banned not in src, f"router references {banned!r}"


def test_negative_control_the_network_block_actually_detects_a_call(monkeypatch):
    """Without this, the zero-model-calls test could be vacuously passing."""
    _block_network(monkeypatch)
    with pytest.raises(_NetworkTouched):
        urllib.request.urlopen("http://example.invalid")


def test_routing_is_statically_decidable_and_not_gameable(router):
    """The claim carries no field that could argue for a better tier: routing
    is a function of the TYPE alone."""
    sig = inspect.signature(router.route)
    assert list(sig.parameters) == ["claim_type"]
    a = router.route("envelope_signature")
    b = router.route("envelope_signature")
    assert a == b


# --------------------------------------------------------------------------- #
#  ACCEPTANCE: V-4 refuses a model-authored spec                              #
# --------------------------------------------------------------------------- #
def test_model_authored_spec_is_refused(router):
    """BUILD_PLAN §7. C11: models asked to specify problems they could not
    solve produced specs measuring BELOW a one-line type check (unconditional
    kill 0.1177 vs a 0.2864 type-only floor)."""
    reg = PartialSpecRegistry()
    model_spec = PartialSpec(
        claim_type="some_claim", fn=lambda *_a: True,
        cls=InvariantClass.CONSERVATION,
        authored_by="gpt-4o-mini", human_attested=False,
        rationale="generated")
    with pytest.raises(AuthorshipError) as e:
        reg.register(model_spec)
    assert "0.1177" in str(e.value) and "0.2864" in str(e.value)
    assert "some_claim" not in reg


def test_human_attested_spec_is_accepted_but_must_carry_a_class_tag():
    reg = PartialSpecRegistry()
    good = PartialSpec("c1", lambda *_a: True, InvariantClass.CONSERVATION,
                       "xan", True, "because")
    reg.register(good)
    assert "c1" in reg

    untagged = PartialSpec("c2", lambda *_a: True, "CONSERVATION",  # type: ignore[arg-type]
                           "xan", True, "because")
    with pytest.raises(UntaggedInvariantError):
        reg.register(untagged)


def test_registries_refuse_downgrades():
    """Same discipline as C-8's bounds: a downgrade reinstates removed checks."""
    v = VerifierRegistry(version=3)
    with pytest.raises(RegistryVersionError, match="monotone"):
        v.load_version(2)
    v.load_version(4)
    assert v.version == 4


def test_verifier_must_cite_its_implementation():
    v = VerifierRegistry()
    with pytest.raises(ValueError, match="cites no implementation"):
        v.register(Verifier("x", lambda: True, witness=""))


# --------------------------------------------------------------------------- #
#  V-3 — coverage computed FROM THE REGISTRY, not copied from a document       #
# --------------------------------------------------------------------------- #
def test_coverage_is_computed_from_the_registry_and_divergence_is_explained():
    """Coverage is READ FROM THE REGISTRY, never copied from a document, and
    every divergence from R14 Part C's committed number is accounted for here
    rather than reconciled away. This test is the LEDGER of those divergences.

        R14 Part C (committed)     17 types, 10 native  = 0.588
        + unit_test_execution      18 types, 11 native  = 0.611   (Phase 3)
        + 2 RESPECIFIED types      18 types, 13 native  = 0.722   (route DR)

    R14's number is not edited -- it was a correct measurement of the registry
    as it stood. The registry has since changed twice, deliberately, and each
    change is named.
    """
    v, s = build_registries()
    r = TierRouter(v, s)
    cov = r.coverage(all_claim_types())

    assert cov["n"] == 19   # 18 -> 19: envelope_dag split into closed/open
    assert cov["tier_1"] == 14   # +1: the dag split yields two tier-1 types
    assert cov["tier_2"] == 3
    assert cov["tier_3"] == len(NO_VERIFIER) == 2

    # divergence 1 -- the unit-test adapter Phase 3 mandated
    assert "unit_test_execution" in v.claim_types()
    # divergence 2 -- the two types respecified out of NO_VERIFIER
    respecified = {"memory_retrieval_relevance", "external_send_content"}
    assert respecified <= set(v.claim_types())
    assert not (respecified & set(NO_VERIFIER))

    # the three named changes account for the WHOLE difference from R14
    # R14 Part C counted 10 native tier-1 types. The count is now 11 because
    # `envelope_dag` was SPLIT into closed/open on 2026-08-15 to repair a
    # determinacy failure — one entry proving two propositions became two
    # entries proving one each. A split raises the count without adding any
    # new verification capability, so this asserts the split rather than a gain.
    assert cov["tier_1"] - 1 - len(respecified) == 11, (
        "R14 Part C's native count, +1 for the envelope_dag split")
    assert cov["n"] - 1 == 18, "R14 Part C's type count, +1 for the envelope_dag split"


def test_unit_test_adapter_is_tier_1_alone_but_forces_tier_3_in_a_chain():
    """The coverage fraction and the composition rule disagree about this
    adapter, and BOTH are right at their own scope: tier is a property of a
    single claim; CARRIER is what governs composition (SR-3)."""
    v, s = build_registries()
    r = TierRouter(v, s)
    assert r.route("unit_test_execution").tier == 1

    d = consult_tier_algebra(carriers=["PROOF", "TEST", "PROOF"], tiers=[1, 1, 1])
    assert d.tier == 3
    assert "finite sample" in d.reasons[0]


# --------------------------------------------------------------------------- #
#  ACCEPTANCE: the tier algebra is consulted before a deep chain              #
# --------------------------------------------------------------------------- #
def test_tier_algebra_consultation_point_exists_and_is_enforced():
    """BUILD_PLAN §7. K-6 is not built; this is the point it must call. A rule
    nobody calls is a rule that is not enforced."""
    allproof = consult_tier_algebra(["PROOF", "PROOF", "PROOF"], [1, 1, 1])
    assert allproof.tier == 1 and allproof.depth_permitted

    with_t3 = consult_tier_algebra(["PROOF", "PROOF", "NONE"], [1, 1, 3])
    assert with_t3.tier == 3

    cumulative = consult_tier_algebra(
        ["PROOF"], [1], classes=[InvariantClass.CUMULATIVE])
    assert cumulative.requires_promotion_gate
    assert "C7" in " ".join(cumulative.reasons)


def test_depth_cap_is_enforced_per_tier():
    """C14: unverified steps decay as (1-p)^n; verified claims do not decay."""
    deep_t3 = consult_tier_algebra(["NONE"], [3], depth=25)
    assert not deep_t3.depth_permitted and "exceeds" in deep_t3.reasons[-1]

    deep_t1 = consult_tier_algebra(["PROOF"], [1], depth=1000)
    assert deep_t1.depth_permitted, "tier 1 does not cap — proofs do not decay"


# --------------------------------------------------------------------------- #
#  ACCEPTANCE: V-5 reports strength as a POSITION between floor and ceiling    #
# --------------------------------------------------------------------------- #
def _ref(x):
    return sorted(x)


_MUTANTS = [
    lambda x: sorted(x)[::-1],          # WRONG
    lambda x: sorted(x)[:-1],           # WRONG
    lambda x: list(x),                  # WRONG (unsorted)
    lambda x: sorted(list(x)),          # EQUIVALENT — must be excluded
    lambda x: (_ for _ in ()).throw(ValueError()),   # DISCARDED
]
_INPUTS = [[3, 1, 2], [5, 4], [9, 0, 7]]


def test_vacuous_spec_is_valid_and_kills_nothing():
    """The load-bearing check: verifiable-but-vacuous is the dominant failure
    mode, and validity alone is exactly the metric that hides it."""
    s = evaluate_spec_strength(lambda i, o: True, _ref, _MUTANTS, _INPUTS)
    assert s.validity is True
    assert s.kill_rate == 0.0


def test_equivalent_mutants_excluded_and_broken_mutants_discarded():
    s = evaluate_spec_strength(lambda i, o: True, _ref, _MUTANTS, _INPUTS)
    assert s.equivalent == 1, "an equivalent mutant is not a miss"
    assert s.discarded == 1
    assert s.denom == 3


def test_spec_strength_is_reported_as_a_position_not_a_bare_number():
    """BUILD_PLAN §7."""
    floor = lambda i, o: isinstance(o, list)                    # type-only
    ceiling = lambda i, o: o == sorted(i)                       # reference
    strong = lambda i, o: isinstance(o, list) and len(o) == len(i) and \
        all(o[k] <= o[k + 1] for k in range(len(o) - 1))

    s = evaluate_spec_strength(strong, _ref, _MUTANTS, _INPUTS,
                               floor_spec=floor, ceiling_spec=ceiling)
    assert s.floor is not None and s.ceiling is not None
    assert "floor" in s.position and "ceiling" in s.position
    assert s.kill_rate >= s.floor

    bare = evaluate_spec_strength(strong, _ref, _MUTANTS, _INPUTS)
    assert "uninterpretable" in bare.position, (
        "a kill rate without floor and ceiling must SAY it is uninterpretable")


def test_invalid_spec_is_not_scored_for_strength():
    s = evaluate_spec_strength(lambda i, o: False, _ref, _MUTANTS, _INPUTS)
    assert s.validity is False and s.kill_rate is None
