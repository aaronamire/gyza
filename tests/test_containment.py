"""
Containment layer tests (BUILD_PLAN C-1 … C-4).

Each test pins a constraint that was MEASURED, not assumed. Where a test looks
pedantic, the citation says what it cost to learn.
"""
from __future__ import annotations

import inspect

import pytest

from gyza.containment import (
    Decision, GuardEngine, HarmClass, HarmModelRegistry, Invariant,
    InvariantClass, InvariantRegistry, Phase, Reversibility,
    ReversibilityTable, UnsetBoundError, UntaggedInvariantError,
)
from gyza.containment.gyza_model import UNMODELLED, build_registries


class S:
    """Minimal state stand-in."""

    def __init__(self, v=0.0, violations=()):
        self.v = v
        self.authority_violations = violations


def _quantity(s0, s):
    return float(s.v - s0.v)


def _reg(bound=None, cls=InvariantClass.CONSERVATION):
    h = HarmModelRegistry()
    h.register(HarmClass(id="X", description="test", quantity=_quantity,
                         frame="test frame", frame_mutable=False,
                         code_path="test:0"))
    if bound is not None:
        h.load_bounds({"X": bound})
    i = InvariantRegistry()
    i.register(Invariant(id="INV-X", harm_class="X", cls=cls, description="d"))
    return h, i


# --------------------------------------------------------------------------- #
#  C-1 — harm registry                                                         #
# --------------------------------------------------------------------------- #
def test_harm_module_imports_no_guard_module():
    """Discipline #5: harm must be definable without reference to the thing
    that checks it, or adequacy is tautological."""
    from gyza.containment import harm
    src = inspect.getsource(harm)
    for banned in ("from gyza.containment.engine", "from gyza.containment.invariants",
                   "import engine", "GuardEngine"):
        assert banned not in src, f"harm module references guard symbol {banned!r}"


def test_unset_bound_fails_closed_and_says_it_is_a_user_decision():
    """D1. An undeclared bound is NOT an infinite bound."""
    h, _ = _reg(bound=None)
    with pytest.raises(UnsetBoundError) as e:
        h.bound("X")
    assert "USER DECISION" in str(e.value)
    assert h.unbounded() == ["X"]
    with pytest.raises(UnsetBoundError):
        h.assert_complete()


def test_bounds_are_loaded_never_invented():
    h, _ = _reg(bound=None)
    assert h.get("X").bound is None
    h.load_bounds({"X": 5.0})
    assert h.bound("X") == 5.0
    # a typo'd id must not silently leave the intended class unbounded
    with pytest.raises(KeyError):
        h.load_bounds({"typo": 1.0})


def test_harm_must_be_a_measure_not_a_boolean():
    """C5: a boolean has no dial and forces the corner."""
    h = HarmModelRegistry()
    h.register(HarmClass(id="B", description="bool", quantity=lambda a, b: True,
                         frame="f", frame_mutable=False, code_path="t:0"))
    with pytest.raises(TypeError, match="MEASURE"):
        h.get("B").measure(S(), S())


def test_mutable_frame_is_flagged():
    """R9's G4' hazard: a pinned frame is not conservative, it is catastrophic
    (G4' lost 175000 where G4 bounded at 50)."""
    h, _ = build_registries()
    assert "H1_credits" in h.mutable_frames()


# --------------------------------------------------------------------------- #
#  C-2 — invariant registry and class tags                                     #
# --------------------------------------------------------------------------- #
def test_untagged_invariant_is_rejected_at_load():
    """There is no default tag: guessing would silently place a cumulative
    bound in the concurrent interior — R13's measured failure."""
    i = InvariantRegistry()
    for bad in (None, "CONSERVATION_TYPO", 3):
        with pytest.raises(UntaggedInvariantError):
            i.register(Invariant(id="bad", harm_class="X", cls=bad,  # type: ignore[arg-type]
                                 description="d"))
    assert len(i) == 0


def test_class_tags_determine_stateless_composition():
    """C6: conservation and monotone compose; cumulative does not."""
    assert InvariantClass.CONSERVATION.composes_statelessly
    assert InvariantClass.MONOTONE_NON_CUMULATIVE.composes_statelessly
    assert not InvariantClass.CUMULATIVE.composes_statelessly


def test_invariant_must_name_a_harm_class():
    """C4: adequacy is PER HARM CLASS."""
    i = InvariantRegistry()
    with pytest.raises(ValueError):
        i.register(Invariant(id="x", harm_class="", cls=InvariantClass.CONSERVATION,
                             description="d"))


# --------------------------------------------------------------------------- #
#  C-3 — reversibility is a static table, never a prediction                   #
# --------------------------------------------------------------------------- #
def test_unknown_action_type_is_irreversible():
    """Fail closed. C10 forbids predicting; a vocabulary that outgrows its
    table is exactly when this matters."""
    t = ReversibilityTable()
    assert t.classify("some_action_invented_tomorrow") is Reversibility.IRREVERSIBLE
    assert "some_action_invented_tomorrow" in t.unknown_seen


def test_egress_is_distinct_from_irreversible():
    """C15: after emission there is no containment and no detector helps, so
    egress cannot be collapsed into ordinary irreversibility."""
    t = ReversibilityTable()
    assert t.classify("send_message") is Reversibility.EGRESS
    assert t.classify("sign_envelope") is Reversibility.IRREVERSIBLE
    assert t.classify("read") is Reversibility.REVERSIBLE_INTERIOR


# --------------------------------------------------------------------------- #
#  C-4 — the engine                                                            #
# --------------------------------------------------------------------------- #
def test_engine_refuses_when_a_bound_is_unset():
    h, i = _reg(bound=None)
    d = GuardEngine(h, i).evaluate(S(0), S(1), "read", Phase.INTERIOR)
    assert not d.admit
    assert any("USER DECISION" in r for r in d.reasons)


def test_engine_admits_within_bound_and_refuses_beyond_it():
    h, i = _reg(bound=5.0)
    g = GuardEngine(h, i)
    assert g.evaluate(S(0), S(3), "read", Phase.INTERIOR).admit
    d = g.evaluate(S(0), S(9), "read", Phase.INTERIOR)
    assert not d.admit
    assert "INV-X" in d.reasons[0] and "9" in d.reasons[0]


def test_cumulative_invariants_are_DEFERRED_in_the_interior_not_evaluated():
    """C7. Evaluating a cumulative bound per-action in the concurrent interior
    would look like a check and bound nothing — R13 measured that shape leaving
    a joint pool overdrawn while every local check passed."""
    h, i = _reg(bound=5.0, cls=InvariantClass.CUMULATIVE)
    g = GuardEngine(h, i)

    interior = g.evaluate(S(0), S(99), "read", Phase.INTERIOR)
    assert interior.admit, "interior must not pretend to bound a cumulative quantity"
    assert interior.deferred == ["INV-X"]
    assert interior.evaluated == []

    gate = g.evaluate(S(0), S(99), "read", Phase.PROMOTION)
    assert not gate.admit, "the serialized gate is where it MUST bite"
    assert gate.evaluated == ["INV-X"]
    assert gate.deferred == []


def test_irreversible_and_egress_actions_are_refused_in_the_interior():
    h, i = _reg(bound=5.0)
    g = GuardEngine(h, i)
    for act in ("sign_envelope", "send_message"):
        d = g.evaluate(S(0), S(0), act, Phase.INTERIOR)
        assert not d.admit
        assert "promotion gate" in d.reasons[0]


def test_frame_alignment_is_structural_the_invariant_cannot_re_measure():
    """C3. The predicate receives the value the registry measured, so there is
    no second frame to drift against."""
    seen = {}

    def spy_quantity(s0, s):
        seen["calls"] = seen.get("calls", 0) + 1
        return float(s.v - s0.v)

    def predicate(h_value, bound, s0, s):
        seen["got"] = h_value
        # the signature offers no way to obtain a differently-framed measure
        return h_value <= bound

    h = HarmModelRegistry()
    h.register(HarmClass(id="X", description="d", quantity=spy_quantity,
                         frame="f", frame_mutable=False, code_path="t:0"))
    h.load_bounds({"X": 10.0})
    i = InvariantRegistry()
    i.register(Invariant(id="INV-X", harm_class="X",
                         cls=InvariantClass.CONSERVATION, description="d",
                         predicate=predicate))
    d = GuardEngine(h, i).evaluate(S(0), S(4), "read", Phase.INTERIOR)
    assert d.admit
    assert seen["calls"] == 1, "harm measured exactly once, by the registry"
    assert seen["got"] == 4.0 == d.measured["X"]


def test_uncovered_harm_class_is_refused_not_ignored():
    """C4: a class nobody covers is unbounded, and silence about it is the bug."""
    h = HarmModelRegistry()
    h.register(HarmClass(id="X", description="d", quantity=_quantity, frame="f",
                         frame_mutable=False, code_path="t:0"))
    h.load_bounds({"X": 1.0})
    d = GuardEngine(h, InvariantRegistry()).evaluate(S(0), S(0), "read")
    assert not d.admit
    assert "no registered invariant" in d.reasons[0]


# --------------------------------------------------------------------------- #
#  Gyza's own model                                                            #
# --------------------------------------------------------------------------- #
def test_gyza_model_cannot_claim_containment_until_bounds_are_declared():
    """D1 is a real gate, not a note. With no declared model the engine refuses
    everything; the bounds file is what lifts it."""
    h, i = build_registries(bounds_file=None)
    r = GuardEngine(h, i).readiness()
    assert r["can_claim_containment"] is False
    assert set(r["unbounded"]) == {"H1_credits", "H2_market_capital", "H4_authority"}
    assert r["uncovered"] == []


def test_declared_bounds_file_lifts_the_d1_gate():
    """The declared model (guard_bounds.json, user decision 2026-07-31)."""
    h, i = build_registries()
    r = GuardEngine(h, i).readiness()
    assert r["can_claim_containment"] is True
    assert r["unbounded"] == []
    assert h.bound("H4_authority") == 0.0, (
        "authority exceedance is a BREACH, not a budget — the attenuation "
        "theorem says it cannot happen at all")
    assert h.bound("H1_credits") == 100.0


def test_authority_bound_of_zero_admits_none_and_refuses_one():
    """A zero bound must still behave as a bound, not as 'unset'."""
    h, i = build_registries()
    g = GuardEngine(h, i)
    clean = g.evaluate(S(0, violations=()), S(0, violations=()), "read",
                       Phase.INTERIOR, harm_classes=["H4_authority"])
    assert clean.admit
    breached = g.evaluate(S(0, violations=()), S(0, violations=("hop3",)), "read",
                          Phase.INTERIOR, harm_classes=["H4_authority"])
    assert not breached.admit
    assert "INV-H4-attenuation" in breached.reasons[0]


def test_gyza_model_reports_the_unmodelled_harm_class_rather_than_inventing_one():
    """H3 has no quantity anywhere in gyza/. Registering it with an invented
    measure would be the circularity the discipline forbids."""
    h, _ = build_registries()
    assert "H3_irreversible_change" in UNMODELLED
    assert "H3_irreversible_change" not in h


def test_gyza_credit_invariant_is_cumulative_and_lands_at_the_gate():
    """A monotone budget over one pool does not compose (R10 H-CONS, R13)."""
    h, i = build_registries()
    plan = GuardEngine(h, i).concurrency_plan()
    assert "INV-H1-drain" in plan["promotion_serialized"]
    assert "INV-H4-attenuation" in plan["interior_concurrent"]


# --------------------------------------------------------------------------- #
#  E2 — the fail-open gate and the empty-record hole (BUILD_PLAN S4)           #
# --------------------------------------------------------------------------- #
def _manifest(mem=None, read=(), write=()):
    caps = {"filesystem": {"read": list(read), "write": list(write)},
            "network": {"allowed_hosts": [], "allowed_ports": []},
            "spawn": {"permitted": [], "resource_budget": {}}}
    if mem is not None:
        caps["spawn"]["resource_budget"]["memory_limit_mb"] = mem
    return {"capabilities": caps}


def test_empty_enforcement_record_is_rejected_as_incomplete():
    """THE EMPTY-RECORD HOLE. Every check is a subset test and the empty set is
    a subset of anything, so a content-free record used to pass whenever the
    manifest declared no memory cap. Absence of a field means "the record does
    not say", which is not the same claim as "the sandbox granted nothing"."""
    from gyza.sandbox.config import enforcement_satisfies_manifest
    ok, why = enforcement_satisfies_manifest({"backend": "bubblewrap"},
                                             _manifest())
    assert not ok
    assert "incomplete record" in why


def test_partially_declared_record_is_rejected_field_by_field():
    from gyza.sandbox.config import enforcement_satisfies_manifest
    base = {"backend": "bubblewrap", "ro_paths": [], "rw_paths": [],
            "requires_network": False}
    ok, _ = enforcement_satisfies_manifest(base, _manifest())
    assert ok, "a COMPLETE record with genuinely empty grants is still valid"
    for drop in ("ro_paths", "rw_paths", "requires_network"):
        partial = {k: v for k, v in base.items() if k != drop}
        ok, why = enforcement_satisfies_manifest(partial, _manifest())
        assert not ok and drop in why, (drop, why)


def test_complete_record_still_enforces_the_subset_property():
    """The tightening must not weaken the original predicate."""
    from gyza.sandbox.config import enforcement_satisfies_manifest
    wide = {"backend": "bubblewrap", "ro_paths": ["/etc"], "rw_paths": [],
            "requires_network": False}
    ok, why = enforcement_satisfies_manifest(wide, _manifest(read=[]))
    assert not ok and "beyond manifest" in why


def test_runner_fail_open_is_now_a_refusable_policy():
    """The gate historically ran only `if enforcement is not None`, so an
    executor that stamped nothing skipped it and still produced a signed
    envelope. The policy is now explicit and refusable."""
    import gyza.runner as R
    assert hasattr(R, "REQUIRE_ENFORCEMENT_DEFAULT")
    sig = inspect.signature(R.AgentRunner.__init__)
    assert "require_enforcement" in sig.parameters
    assert sig.parameters["require_enforcement"].default is None

    src = inspect.getsource(R.AgentRunner._execute)
    assert "self._require_enforcement" in src, "policy must be consulted"
    i_policy = src.index("self._require_enforcement")
    i_check = src.index("enforcement_satisfies_manifest")
    assert i_policy < i_check, "the absent-record refusal must precede the subset check"


def test_every_registered_gyza_harm_quantity_actually_EXECUTES():
    """The gap that shipped a broken harm quantity.

    `_credits_at_risk` read a non-existent `.credits` attribute on `Credits`
    (which exposes `.micros`) and therefore RAISED on every input. It survived
    two sessions because every containment test used a TEST-LOCAL quantity;
    nothing ever ran the registered Gyza ones against real state.

    Registering a quantity is not evidence that it runs.
    """
    from gyza.containment.projection import (
        AuthorityViolation, WindowOrigin, project_at_origin, project_now,
    )
    from gyza.economy.market import BondedMarket

    class _E:
        def __init__(self, frm, to, amt):
            self.from_compositor, self.to_compositor = frm, to
            self.amount_credits, self.settled = amt, True
            self.entry_id = f"{frm}{to}{amt}"
            self.from_signature = self.to_signature = "x"

    # The PRODUCTION state type. The prior version of this test rolled its own
    # class with a `.capital` scalar; no production object had one, so H2 and
    # H4 read `getattr` defaults and this test could not see it.
    market = BondedMarket(initial_capital={"A": 100.0})
    origin = WindowOrigin(ledger_ns=0,
                          capital_seq=len(market.capital_entries()))
    _proj = dict(owner="A", capital_entries=market.capital_entries())

    s0 = project_at_origin(ledger_entries=[], origin=origin, **_proj)
    market._credit("A", -10.0, "stake")          # H2 moves by 10
    s1 = project_now(
        ledger_entries=[_E("A", "B", 10.0)], active_holds=0.0,
        authority_violations=[AuthorityViolation("a1", "B", "over", 1)],
        owner="A", capital_entries=market.capital_entries())

    h, _i = build_registries()
    for hc in h:
        v0 = hc.measure(s0, s0)     # must not raise
        v1 = hc.measure(s0, s1)
        assert isinstance(v0, float) and isinstance(v1, float)
        assert v0 == 0.0, f"{hc.id} must measure zero harm against itself"

    assert h.get("H1_credits").measure(s0, s1) == pytest.approx(10.0)
    assert h.get("H2_market_capital").measure(s0, s1) == pytest.approx(10.0)
    assert h.get("H4_authority").measure(s0, s1) == pytest.approx(1.0)


def test_credits_are_folded_in_micros_not_via_the_display_property():
    """`Credits.value` is documented display-only — 'Never fold with this'."""
    import inspect
    from gyza.containment import gyza_model
    src = inspect.getsource(gyza_model._credits_at_risk)
    # strip comments: the prose legitimately names the attributes it warns about
    code = "\n".join(l.split("#")[0] for l in src.splitlines())
    assert ".micros" in code
    assert ".value" not in code and ".credits" not in code


# --------------------------------------------------------------------------- #
#  The registry's ADVERTISED partition vs the engine's ENFORCED filter.
#
#  These are TWO EXPRESSIONS OF ONE RULE, written in two files:
#
#    InvariantRegistry.interior()/promotion_only()  (invariants.py:100,104)
#        -> what concurrency_plan() ADVERTISES to the scheduler and to O-3
#    engine.evaluate()'s phase filter               (engine.py:109)
#        -> what is actually ENFORCED at evaluation time
#
#  Nothing asserted they agree. That is the same shape as the Python<->Rust
#  canonical-bytes divergence: one logical rule, two implementations, free to
#  drift, and a drift here would be SILENT -- concurrency_plan() would publish
#  a partition the engine does not honour, and the scheduler would act on it.
# --------------------------------------------------------------------------- #

def _interior_defers(cls) -> bool:
    """What the ENGINE actually does with a `cls` invariant in the interior."""
    h, i = _reg(bound=5.0, cls=cls)
    d = GuardEngine(h, i).evaluate(S(0), S(99), "read", Phase.INTERIOR)
    assert (d.deferred == ["INV-X"]) != (d.evaluated == ["INV-X"]), (
        "an invariant must be either deferred or evaluated, never both/neither")
    return d.deferred == ["INV-X"]


@pytest.mark.parametrize("cls", list(InvariantClass))
def test_engine_filter_MATCHES_registry_advertised_partition(cls):
    """The partition concurrency_plan() publishes must be the one evaluate()
    enforces, for every class -- not just for the two that happen to be
    registered in gyza_model today."""
    h, i = _reg(bound=5.0, cls=cls)
    advertised_promotion_only = [x.id for x in i.promotion_only()]
    enforced_deferral = _interior_defers(cls)

    assert enforced_deferral == ("INV-X" in advertised_promotion_only), (
        f"{cls.value}: registry advertises promotion_only="
        f"{advertised_promotion_only} but the engine "
        f"{'defers' if enforced_deferral else 'evaluates'} it in the interior")


def test_NEGATIVE_CONTROL_a_divergent_partition_is_CAUGHT():
    """A guard that has never refused anything has no demonstrated power.

    Construct the exact drift the test above exists to catch -- a registry
    whose advertised partition disagrees with the engine's filter -- and show
    the comparison FAILS. Without this, the test above could be vacuously true.
    """
    h, i = _reg(bound=5.0, cls=InvariantClass.CUMULATIVE)

    class _LyingRegistry:
        """Advertises the cumulative invariant as interior-safe."""
        def __init__(self, real): self._real = real
        def promotion_only(self): return []                  # the lie
        def interior(self): return list(self._real)
        def __getattr__(self, n): return getattr(self._real, n)

    lying = _LyingRegistry(i)
    advertised = [x.id for x in lying.promotion_only()]
    enforced_deferral = _interior_defers(InvariantClass.CUMULATIVE)

    assert enforced_deferral is True, "engine still defers -- it reads the tag"
    assert "INV-X" not in advertised, "the registry now lies about the partition"
    assert enforced_deferral != ("INV-X" in advertised), (
        "the consistency check MUST catch this divergence; if it does not, "
        "test_engine_filter_MATCHES_registry_advertised_partition is vacuous")
