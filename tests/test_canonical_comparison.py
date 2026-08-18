"""
The MECHANISM that replaces the rule (ledger #7, #15, and #15's third
recurrence in AR-2).

Comparing representations instead of values recurred three times. It did not
recur because the rule was forgotten — it recurred because a defective
primitive was written once and reused: `codebench.py` builds an answer
signature as repr(), and routes downstream compared those strings.

WHAT THIS SCANNER CAN AND CANNOT SEE — stated because it bounds the mechanism.
The defect that actually recurred is BUILD-HERE, COMPARE-THERE: the
representation is constructed in one file and compared in another. NO
LINE-LEVEL SCANNER SEES THAT — it is a dataflow property, and this is R12's
result (blind channels are not mechanically discoverable; static analysis tests
syntactic mention, not semantic dependence) applying to this very tool.

So the scanner takes the only sound syntactic position available: EVERY use of
repr() outside a __repr__ definition is flagged, and each must be exempted with
a reason saying whether it is display or comparison. That turns "do not compare
representations" into "every representation-building site is a decision someone
recorded", which is checkable. It does not prove no such comparison exists.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from gyza.canon import canonical_form, sequences_equal, values_equal

ROOT = Path(__file__).resolve().parents[1]
# ONLY WHAT IS PRESENT. `research/` is not published in code-only releases, so
# a source scan hardcoding it fails on a tree where it is absent -- and an
# exemption for a file that does not exist here is not stale, it is
# inapplicable. Scanning what exists keeps this an honest check of the tree it
# can actually see, in both trees.
SCAN = [p for p in (ROOT / "gyza", ROOT / "research") if p.is_dir()]

PATTERN = re.compile(r"\brepr\(|str\([^()]*\)\s*[=!]=\s*str\(")
SKIP_LINE = re.compile(r"def __repr__|__repr__\s*=|\.__repr__")
_TRIPLE = ('"' * 3, "'" * 3)

# EXEMPTIONS. Each names a file and the reason it may build or compare a
# representation. An exemption is a decision; a silent skip is a gap.
EXEMPT = {
    "research/correlated_failure/codebench.py":
        "ORIGIN of the defect: builds answer signatures as repr(eval(...)). It "
        "is the substrate of committed R2/R8/R11/R14 findings, and rewriting it "
        "would make those routes non-reproducible. Superseded for MBPP by "
        "research/selection_routes/mbpp_truth.json, which re-derives verdicts "
        "by executing the asserts.",
    "gyza/network/raft.py":
        "Node-identity normalization, not value comparison: a pysyncobj node "
        "handle has no canonical form other than its string. Comparing "
        "identities is the intended operation.",
    # --- DISPLAY-ONLY. Named individually so that if one ever feeds a
    # --- comparison, the change shows up in this list rather than nowhere.
    "research/channel_discovery/run_r12.py":
        "Display only: repr of an action for the result JSON's diagnostic "
        "field. Never compared.",
    "research/federation/run_r13.py":
        "Display only: repr of a mutation sequence for the disagreement log. "
        "Never compared.",
    "research/invariant_adequacy/run_r9.py":
        "Display only: repr of first actions for the result JSON. Never "
        "compared.",
    "research/invariant_adequacy/redteam.py":
        "Display only: repr of first actions for the result JSON. Never "
        "compared.",
    "research/spec_competence/mutations.py":
        "Display only: ref_outs are repr'd INTO the result JSON. Mutant "
        "classification compares the underlying VALUES, not these strings.",
}


# KNOWN-INVISIBLE: sites this scanner provably CANNOT see. They are recorded
# here because an undetectable defect that nobody wrote down is indistinguishable
# from one that does not exist — and these two are the exact shapes that bound
# the mechanism.
INVISIBLE = {
    "research/native_verifier/native_verifier.py:219":
        "BUILD-HERE, COMPARE-THERE. The line reads `signature == expected` with "
        "no repr() on it; the reprs were built in codebench.py. A line-level "
        "scanner cannot follow that, which is R12 applied to this tool. Its "
        "labels are superseded by mbpp_truth.json (11 false WRONGs in 196, "
        "0 false CORRECTs).",
    "research/vocabulary_design/run_ar2.py:_WORKER":
        "EMBEDDED SOURCE. The repr() lives inside a worker program held in a "
        "string literal, so it is invisible to any scanner that reads the host "
        "file as text. Conservative in effect: repr equality is STRICTER, so it "
        "can only over-flag non-determinism, and AR-2's FPR was 0.0000 — "
        "nothing was flagged.",
}


def test_the_scanners_blind_spots_are_recorded_not_omitted():
    """The two shapes this mechanism cannot detect, named. An undetectable
    defect nobody wrote down is indistinguishable from one that is absent."""
    assert INVISIBLE, "the blind spot is real; it must not be left unstated"
    for site, reason in INVISIBLE.items():
        assert ":" in site and len(reason) > 60, site
    assert any("BUILD-HERE" in r for r in INVISIBLE.values())
    assert any("EMBEDDED SOURCE" in r for r in INVISIBLE.values())


def _sites():
    out = []
    for root in SCAN:
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(ROOT).as_posix()
            in_doc = False
            for i, line in enumerate(py.read_text().splitlines(), 1):
                ticks = sum(line.count(t) for t in _TRIPLE)
                if in_doc:
                    if ticks:
                        in_doc = False
                    continue
                if ticks == 1:
                    in_doc = True
                    continue
                code = line.split("#")[0]
                if SKIP_LINE.search(code):
                    continue
                if PATTERN.search(code):
                    out.append((rel, i, line.strip()))
    return out


def test_no_unexempted_site_builds_or_compares_representations():
    offenders = [(f, i, l) for f, i, l in _sites() if f not in EXEMPT]
    assert not offenders, (
        "representation built or compared without an exemption — use "
        "gyza.canon.values_equal to compare, or canonical_form for a stable "
        "key. If the site is legitimate, add it to EXEMPT with a reason:\n"
        + "\n".join(f"  {f}:{i}  {l}" for f, i, l in offenders))


def test_every_exemption_is_real_and_carries_a_reason():
    """An exemption for a site that no longer matches is dead weight that hides
    the next one."""
    hit = {f for f, _i, _l in _sites()}
    # AN EXEMPTION FOR AN ABSENT FILE IS INAPPLICABLE, NOT STALE, and the
    # distinction is file-level rather than directory-level: `research/` may be
    # present with only part of its contents (code-only releases publish
    # `gyza/` and a subset of `research/`). Requiring an exemption to match a
    # file that was never shipped would fail for a reason that says nothing
    # about canonicalisation.
    applicable = {f for f in EXEMPT if (ROOT / f).is_file()}
    stale = sorted(applicable - hit)
    assert not stale, f"exemptions no longer matching any site: {stale}"
    for f, reason in EXEMPT.items():
        assert len(reason) > 40, f"exemption for {f} needs a real reason"


# --------------------------------------------------------------------------- #
#  The helper must actually fix the three historical shapes                    #
# --------------------------------------------------------------------------- #
def test_helper_fixes_the_dict_order_shape():
    a, b = {1: 2, 2: 3, 3: 1}, {2: 3, 1: 2, 3: 1}
    assert repr(a) != repr(b), "the trap must still be real"
    assert values_equal(a, b)
    assert canonical_form(a) == canonical_form(b)


def test_helper_fixes_the_int_float_shape():
    assert repr((1, 0.0)) != repr((1.0, 0.0))
    assert values_equal((1, 0.0), (1.0, 0.0))
    assert canonical_form(1) == canonical_form(1.0)


def test_helper_fixes_the_set_order_shape():
    assert canonical_form({3, 1, 2}) == canonical_form({2, 3, 1})


def test_values_equal_is_not_merely_double_equals():
    assert values_equal(float("nan"), float("nan")), (
        "two computations that both produced NaN produced the same value")

    class Hostile:
        def __eq__(self, other):
            raise TypeError("refuses comparison")

    assert values_equal(Hostile(), Hostile()) is False, (
        "uncomparable is not equal — and is not an error either")


def test_sequences_equal_compares_elementwise_not_serialized():
    assert sequences_equal([{1: 2, 2: 3}], [{2: 3, 1: 2}])
    assert not sequences_equal([1, 2], [1, 2, 3])


# --------------------------------------------------------------------------- #
#  THE SECOND MECHANISM: a failure is not an empty value                       #
# --------------------------------------------------------------------------- #
#
# Same underlying error as the repr rule above, other half: reading something
# that is not a measurement as if it were one. `gh(...) or []` in the corpus
# extractor turned a transport failure into "this PR has 0 commits" -- the
# FOURTH recurrence of the species, one session after the rule was written down.
#
# Unlike the repr scanner, this one is AST-based rather than line-based, so it
# does not share that scanner's BUILD-HERE/COMPARE-THERE blind spot for this
# pattern: `call() or []` is a single expression and cannot be split across
# files. It still cannot see the idiom inside embedded source strings.
import ast

# Calls that are TOTAL -- defined for every input, no failure mode. `d.get(k) or
# []` is null-field normalisation, not failure absorption, and flagging it would
# bury the real signal in 40 false positives (measured: 41 raw hits, 1 real).
_TOTAL_CALLS = {"get", "getattr", "pop", "getenv"}

# Sites where a fallible call may be defaulted, each with a reason.
OR_EMPTY_EXEMPT: dict[str, str] = {}


def _is_empty_literal(n) -> bool:
    return ((isinstance(n, ast.List) and not n.elts)
            or (isinstance(n, ast.Dict) and not n.keys)
            or (isinstance(n, ast.Tuple) and not n.elts)
            or (isinstance(n, ast.Constant) and n.value in (0, "", None, False)))


def _is_fallible_call(n) -> bool:
    if not isinstance(n, ast.Call):
        return False
    f = n.func
    if isinstance(f, ast.Attribute) and f.attr in _TOTAL_CALLS:
        return False
    if isinstance(f, ast.Name) and f.id in _TOTAL_CALLS:
        return False
    return True


def _or_empty_sites():
    out = []
    for root in SCAN:
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                tree = ast.parse(py.read_text())
            except SyntaxError:
                continue
            rel = py.relative_to(ROOT).as_posix()
            for n in ast.walk(tree):
                if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
                    for i, v in enumerate(n.values[:-1]):
                        if _is_fallible_call(v) and _is_empty_literal(n.values[i + 1]):
                            out.append((rel, n.lineno, ast.unparse(n)[:90]))
    return out


def test_no_fallible_call_is_defaulted_to_an_empty_value():
    """`call() or []` makes "it failed" indistinguishable from "it found
    nothing", and those are opposite claims."""
    bad = [s for s in _or_empty_sites() if s[0] not in OR_EMPTY_EXEMPT]
    assert not bad, (
        "a call that can fail is being defaulted to an empty value. Return "
        "gyza.canon.Failure and handle it, or opt in with canon.unwrap_or(x, d):\n"
        + "\n".join(f"  {f}:{i}  {src}" for f, i, src in bad))


def test_failure_refuses_every_silent_absorption_path():
    """The mechanism is that Failure is HOSTILE, not falsy. If any of these
    stopped raising, `call() or []` would start lying again."""
    from gyza.canon import CallFailed, Failure, failed, unwrap_or

    f = Failure("HTTP 502", "gh")
    for label, thunk in (("`or` default", lambda: f or []),
                         ("len()", lambda: len(f)),
                         ("iteration", lambda: list(f)),
                         ("indexing", lambda: f[0]),
                         ("`in`", lambda: 1 in f)):
        with pytest.raises(CallFailed):
            thunk()
        assert label                      # names the path in the failure output

    assert failed(f) and not failed([])
    assert unwrap_or(f, ["d"]) == ["d"], "explicit opt-out must still work"
    assert unwrap_or([1], ["d"]) == [1]


def test_attempt_returns_a_failure_rather_than_a_stand_in():
    from gyza.canon import attempt, failed

    assert attempt(int, "42") == 42
    bad = attempt(int, "x")
    assert failed(bad) and "ValueError" in bad.reason
