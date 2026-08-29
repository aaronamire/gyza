"""Correctness anchor for Route 5. Synthetic; no model calls. If these fail no
result is trustworthy. NOT a Route 2 rescue."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mechanical_verifier import (  # noqa: E402
    verify_identity, verify_solution_set, verify_transition, is_violation, is_checkable)
from step_extractor import parse_extraction  # noqa: E402


# 1. identity: correct expansion passes, wrong one violates
def test_identity_basic():
    assert verify_identity("(x+1)**2", "x**2+2*x+1")[0] == "PASS"
    assert verify_identity("(x+1)**2", "x**2+1")[0] == "VIOLATION"
    assert verify_identity("(x-4*x+3)", "-3*x+3")[0] == "PASS"


# 2. random-point robustness: a true identity holds numerically -> PASS
def test_random_point_primary():
    # nested-radical constant identity that must pass numerically
    assert verify_identity("sqrt(3+2*sqrt(2))", "1+sqrt(2)")[0] == "PASS"
    # a nontrivial algebraic identity
    assert verify_identity("(x**3-1)/(x-1)", "x**2+x+1")[0] == "PASS"


# 3. domain guard: undefined points skipped, not violations
def test_domain_guard():
    # 1/x + 1 == (x+1)/x everywhere it is defined; x=0 undefined -> skipped
    assert verify_identity("1/x+1", "(x+1)/x")[0] == "PASS"


# 4. solution-set: enlarged vs reduced
def test_solution_set():
    assert verify_solution_set("x-2", "x**2-4")[0] == "ENLARGED_UNSAFE"   # x=2 -> x^2=4
    assert verify_solution_set("x**2-4", "x-2")[0] == "VIOLATION"         # x^2=4 -> x=2 (dropped -2)


# 5. unresolved discipline: parse failure -> UNRESOLVED, not scored either way
def test_unresolved_excluded():
    v = verify_identity("=@garbage@=", "x")[0]
    assert v == "UNRESOLVED"
    assert is_violation("UNRESOLVED") is False
    assert is_checkable("UNRESOLVED") is False
    # ENLARGED not a primary violation; is a violation only in the ablation
    assert is_violation("ENLARGED_UNSAFE") is False
    assert is_violation("ENLARGED_UNSAFE", count_enlarged=True) is True


# 6. extractor role: a correctness judgement is a protocol violation
def test_extractor_protocol():
    good = '[{"from_step":1,"to_step":2,"lhs":"(x+1)^2","rhs":"x^2+2*x+1","relation":"IDENTITY","free_vars":["x"],"assumptions":[]}]'
    tr, proto, ok = parse_extraction(good)
    assert ok and not proto and len(tr) == 1
    bad_key = '[{"from_step":1,"to_step":2,"lhs":"x","rhs":"x","relation":"IDENTITY","valid":false}]'
    _, proto2, _ = parse_extraction(bad_key)
    assert proto2 is True
    bad_str = '[{"from_step":1,"to_step":2,"lhs":"this step is incorrect","rhs":"x","relation":"IDENTITY"}]'
    _, proto3, _ = parse_extraction(bad_str)
    assert proto3 is True


# 7. conservatism: a correct trace with 10 valid transitions never fires
def test_conservatism_no_false_fire():
    trans = [
        {"lhs": "(x+1)**2", "rhs": "x**2+2*x+1", "relation": "IDENTITY"},
        {"lhs": "x**2+2*x+1-1", "rhs": "x**2+2*x", "relation": "IDENTITY"},
        {"lhs": "x**2+2*x", "rhs": "x*(x+2)", "relation": "IDENTITY"},
        {"lhs": "2*(a+b)", "rhs": "2*a+2*b", "relation": "IDENTITY"},
        {"lhs": "(a-b)*(a+b)", "rhs": "a**2-b**2", "relation": "IDENTITY"},
        {"lhs": "3*4", "rhs": "12", "relation": "IDENTITY"},
        {"lhs": "sin(x)**2+cos(x)**2", "rhs": "1", "relation": "IDENTITY"},
        {"lhs": "(x**2-9)/(x-3)", "rhs": "x+3", "relation": "IDENTITY"},
        {"lhs": "x", "rhs": "x", "relation": "ASSERTION"},
        {"lhs": "6/2", "rhs": "3", "relation": "IDENTITY"},
    ]
    verdicts = [verify_transition(t)[0] for t in trans]
    assert not any(is_violation(v) for v in verdicts), verdicts   # zero false fires
