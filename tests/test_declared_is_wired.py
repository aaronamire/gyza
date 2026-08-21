"""Every declared thing must be WIRED, or say in its own source why not.

WHY THIS FILE EXISTS. On 2026-08-19 an audit found EIGHT claims in this
repository that no mechanism checked, all one species:

  1. H3 registered as a measured harm class, disconnected at five points
  2. H5 and H6 carrying declared SIGNED bounds while measuring a constant 0
  3. `EgressRecorder` with zero production constructors
  4. `SettlementGuard`'s docstring saying "everything is REQUIRED" beside a
     default pointing at a RETIRED class
  5. `allow_nan=False` present in 2 of 24 canonical encoders
  6. "Autonomy is bounded instead by H6, checked in the runner" -- a design
     note in `global_cluster.py` describing a bound that was never wired, so
     nothing bounded autonomy at all
  7/8. two research headlines published from evidence that did not support them

Each was fixed by writing a check. THESE ARE THE CHECKS, generalized, so the
ninth instance fails a test instead of surviving to an audit.

THE DESIGN CONSTRAINT THAT MATTERS. A blanket "everything must be constructed"
rule fails two ways: too loose and it catches nothing, too strict and it
forbids deliberate reference implementations like `containment/staging.py`,
whose header says it is an execution model production did not adopt. Worse, a
checker that cannot fail would be instance #9 in the very commit claiming to
prevent instances.

So: SPECIFIC assertions, and the exemption is a `NON_ADOPTED` attribute on the
class ITSELF -- next to the code, where a reader changing that code sees it --
never a list in this file, which would rot silently.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import tempfile

import pytest

from gyza.containment.gates import observe_at_origin, observe_now
from gyza.containment.gyza_model import build_registries

_ROOT = pathlib.Path(__file__).resolve().parents[1]
GYZA = _ROOT / "gyza"

#: OPERATOR ENTRY POINTS COUNT AS PRODUCTION. `scripts/` holds real tools --
#: `sign_guard_config.py` signs the guard configuration and rotates the
#: authority key, `cut_release.py` cuts releases. Scanning `gyza/` alone gave
#: the census a blind spot: a mechanism whose only legitimate consumer is an
#: operator tool would read as unwired forever. Found by using this test on
#: `KeySuccession` the day both were written.
#:
#: `tests/` stays excluded, and that exclusion is the point of the file: a
#: suite that builds its own fixtures never touches the registered ones.
_PRODUCTION_TREES = (GYZA, _ROOT / "scripts")


def _constructions(name: str) -> list[str]:
    """Every `Name(...)` call for `name` in gyza/ that is REACHABLE.

    By AST rather than grep: grep counts comments, `__all__` entries and
    docstring mentions -- it reported `SettlementGuard` as constructed once
    when the hit was a comment. A census that miscounts is worse than none.

    CONSTRUCTIONS INSIDE A `NON_ADOPTED` CLASS DO NOT COUNT, and that is the
    point rather than a convenience. `AppendOnlyLog` is constructed exactly
    once, at `staging.py:108` -- inside `StagingArea`, which is itself
    NON_ADOPTED. Counting it would report the log as live production code when
    its only caller is an execution model production did not adopt. Adoption
    is transitive; a census that ignores that measures syntax, not reachability.
    """
    hits: list[str] = []
    for p in [q for tree in _PRODUCTION_TREES if tree.exists()
              for q in tree.rglob("*.py")]:
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        # classes in this file that are themselves exempt
        exempt_spans = [
            (n.lineno, n.end_lineno)
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and any(isinstance(b, ast.Assign)
                    and any(getattr(t, "id", None) == "NON_ADOPTED"
                            for t in b.targets)
                    for b in n.body)
        ]
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == name):
                continue
            if any(lo <= node.lineno <= hi for lo, hi in exempt_spans):
                continue
            hits.append(f"{p.relative_to(_ROOT)}:{node.lineno}")
    return hits


def _containment_classes() -> list[tuple[str, type]]:
    import gyza.containment as C

    out = []
    for mod_name in ("egress", "engine", "gates", "guardconfig", "harm",
                     "invariants", "log", "review", "reversibility", "staging"):
        mod = __import__(f"gyza.containment.{mod_name}", fromlist=["x"])
        for nm, obj in vars(mod).items():
            if (inspect.isclass(obj) and obj.__module__ == mod.__name__
                    and "__init__" in obj.__dict__):
                out.append((nm, obj))
    return out


# --------------------------------------------------------------------------- #
#  1. Unconsumed components must say so IN THEIR OWN SOURCE                     #
# --------------------------------------------------------------------------- #
def test_every_containment_component_is_constructed_or_marked_NON_ADOPTED():
    offenders = []
    for name, cls in _containment_classes():
        if _constructions(name):
            continue
        if getattr(cls, "NON_ADOPTED", None):
            continue
        offenders.append(name)
    assert offenders == [], (
        f"{offenders} have ZERO production constructions and no NON_ADOPTED "
        "marker. Either wire them, or state on the class why they are not "
        "wired -- an unconsumed component that LOOKS live is the defect this "
        "file exists to prevent.")


def test_NON_ADOPTED_markers_carry_a_REASON_not_just_a_flag():
    """`NON_ADOPTED = True` would be a flag; the point is the argument."""
    for name, cls in _containment_classes():
        why = getattr(cls, "NON_ADOPTED", None)
        if why is None:
            continue
        assert isinstance(why, str) and len(why) > 40, (
            f"{name}.NON_ADOPTED must explain WHY, in prose a reader can "
            f"disagree with; got {why!r}")


def test_a_marked_component_that_BECOMES_wired_fails_this_test():
    """The marker must not become a permanent excuse.

    If a NON_ADOPTED component acquires a production construction, the marker
    is now false and must be removed -- otherwise the exemption outlives the
    condition that justified it, which is how exemption lists rot.
    """
    stale = [name for name, cls in _containment_classes()
             if getattr(cls, "NON_ADOPTED", None) and _constructions(name)]
    assert stale == [], (
        f"{stale} are marked NON_ADOPTED but ARE constructed in production. "
        "Remove the marker -- it is now a false claim.")


# --------------------------------------------------------------------------- #
#  2. Every registered harm class must MOVE when its real source moves         #
#     (H5 and H6 carried SIGNED bounds while pinned at zero)                   #
# --------------------------------------------------------------------------- #
class _Store:
    def __init__(self, n): self._n = n
    def total_size_bytes(self): return self._n


def _an_envelope():
    """A real signed envelope, so H6's source is genuinely non-empty.

    Building the fixture from the production type matters: a hand-rolled row
    would test the SQL, not the path H6 actually folds.
    """
    from gyza.icp import ICPEnvelope, sign_envelope

    env = ICPEnvelope(
        action_id="a", agent_pubkey="00" * 32,
        capability_manifest_hash="11" * 32, duration_ms=1,
        inference_backend="none", input_hashes=[], intent_id="i",
        model_identifier="m", output_hash="22" * 32,
        parent_envelope_hash=None, schema_version=1,
        timestamp_ns=1, tokens_in=0, tokens_out=0,
    )
    return sign_envelope(env, b"\x01" * 32)


def test_every_registered_harm_class_is_movable_by_a_real_source():
    from gyza.blackboard import Blackboard
    from gyza.containment.egress import default_egress_recorder
    from gyza.containment.projection import AuthorityViolation

    db = str(pathlib.Path(tempfile.mkdtemp()) / "bb.db")
    rec = default_egress_recorder(db)
    rec.peer_send("send_message:probe", "peerA", 1)          # H3
    bb = Blackboard(db)
    bb.store_envelope(_an_envelope())                        # H6

    harm, _ = build_registries()
    s0 = observe_at_origin(owner="probe")
    s = observe_now(
        owner="probe", blackboard=bb, artifact_store=_Store(4096),
        authority_violations=(AuthorityViolation(
            action_id="a", agent_pubkey="p", reason="r", at_ns=1),),
    )
    pinned = [c.id for c in harm if c.quantity(s0, s) == 0.0]
    assert pinned == [], (
        f"{pinned} did not move when their real source moved. A harm class "
        "pinned at 0 is indistinguishable from a system that is safe, which "
        "is exactly why H2 was retired.")


# --------------------------------------------------------------------------- #
#  3. Injected consumers must be SUPPLIED somewhere in production              #
#     (review_queue was accepted by AgentRunner and passed by nobody)          #
# --------------------------------------------------------------------------- #
#: Guard-consumer parameters, DERIVED from AgentRunner's signature rather than
#: listed by hand.
#:
#: THE HAND-MAINTAINED LIST WAS ITSELF THE DEFECT. This test exists to catch
#: "declared but nothing supplies it", and it shipped as three literal strings
#: that someone had to remember to extend. `require_enforcement` was added to
#: `AgentRunner` afterwards, was never added here, and was supplied by NO
#: production call site while runner.py's own comment claimed "Production entry
#: points set it True explicitly" -- instance #9 of the species this file was
#: written to end, walking straight past the check.
#:
#: An inclusion list that needs manual upkeep has exactly the fragility
#: CLAUDE.md forbids in an exemption list. Deriving it means a new guard
#: parameter is covered the moment it is added.
def _guard_consumer_kwargs() -> list[str]:
    #: An INJECTED guard consumer is a constructor parameter whose name marks it
    #: as a guard, whose default is None or False, and for which the constructor
    #: builds NO working substitute. All three conditions matter, and the middle
    #: two were learned by running the broad version:
    #:
    #:   `queue or EscalationQueue()`          -> falls back to a real object
    #:   `trust_registry or TrustRegistry()`   -> falls back to a real object
    #:
    #: Those are optional-with-fallback, not injected-or-disabled, and absence
    #: disables nothing. Whereas `require_enforcement` falls back to a NAME
    #: (`REQUIRE_ENFORCEMENT_DEFAULT`, which is False) -- a disabled guard
    #: wearing a default's clothes, and exactly the case this must catch.
    #:
    #: Restricted to `__init__` because injection happens at construction. A
    #: free function taking a queue positionally is a call, not an injection --
    #: which is also what excludes `alarms(guard_loosenings=...)`, whose name
    #: matched a marker while being a list of strings.
    MARKERS = ("queue", "registry", "recorder", "require_", "guard")
    found: set[str] = set()
    for path in [q for tree in _PRODUCTION_TREES if tree.exists()
                 for q in tree.rglob("*.py")]:
        try:
            mod = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(mod):
            if not isinstance(node, ast.FunctionDef) or node.name != "__init__":
                continue
            a = node.args
            params = a.args + a.kwonlyargs
            defaults = ([None] * (len(a.args) - len(a.defaults))
                        + list(a.defaults) + list(a.kw_defaults))
            for prm, dflt in zip(params, defaults):
                if not any(m in prm.arg for m in MARKERS):
                    continue
                if not (isinstance(dflt, ast.Constant)
                        and dflt.value in (None, False)):
                    continue
                if _constructs_a_substitute(node, prm.arg):
                    continue
                found.add(prm.arg)
    assert found, "derived no guard-consumer kwargs; the marker heuristic broke"
    # `harm_guard` feeds SettlementGuard, which carries a NON_ADOPTED marker
    # ON THE CLASS giving its reason (H1_credits was retired 2026-08-15 and
    # nothing else moves at the settlement boundary). The exemption is READ
    # FROM THE CODE IT EXCUSES rather than listed here -- deleting the marker
    # re-arms this check, which is the property CLAUDE.md's "do not add an
    # exemption list" rule is protecting.
    from gyza.containment.gates import SettlementGuard
    if getattr(SettlementGuard, "NON_ADOPTED", None):
        found.discard("harm_guard")
    return sorted(found)


def _constructs_a_substitute(fn: ast.FunctionDef, name: str) -> bool:
    """True iff the constructor builds a REAL object when `name` is absent.

    Recognises `name or Thing()` and `if name is None: ... Thing()`. A fallback
    to a bare name or constant is NOT a substitute -- that is a disabled guard,
    which is the thing being hunted.
    """
    for node in ast.walk(fn):
        if (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
                and node.values and isinstance(node.values[0], ast.Name)
                and node.values[0].id == name
                and any(isinstance(v, ast.Call) for v in node.values[1:])):
            return True
        if isinstance(node, ast.If):
            t = node.test
            if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
                    and t.left.id == name
                    and any(isinstance(c, ast.Is) for c in t.ops)
                    and any(isinstance(sub, ast.Call)
                            for stmt in node.body for sub in ast.walk(stmt))):
                return True
    return False


@pytest.mark.parametrize("kwarg", _guard_consumer_kwargs())
def test_guard_consumer_kwargs_are_supplied_at_a_production_call_site(kwarg):
    """A consumer parameter that nothing ever passes is a dead guard.

    `AgentRunner` accepted `review_queue`/`harm_registry` and NO production
    construction supplied either, so `check_cadence` never ran while a design
    note claimed H6 bounded autonomy. `egress_recorder` was the same for H3.
    """
    supplied = []
    for p in [q for tree in _PRODUCTION_TREES if tree.exists()
              for q in tree.rglob("*.py")]:
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                # `kwarg=None` is not a supply -- that is the default, and
                # counting it would make this test pass on the broken state.
                if kw.arg == kwarg and not (
                        isinstance(kw.value, ast.Constant)
                        and kw.value.value is None):
                    supplied.append(f"{p.relative_to(_ROOT)}:{node.lineno}")
    assert supplied, (
        f"nothing in gyza/ passes a non-None {kwarg}=; the consumer it feeds "
        "is dead code and whatever it was meant to bound is unbounded.")
