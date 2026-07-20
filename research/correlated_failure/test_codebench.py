"""
Validation of the code-battery instrument on synthetic programs with
KNOWN same/different bugs. If the same-bug metric can't tell a shared bug
from independent ones, no real-model code result is trustworthy.
"""
from __future__ import annotations

from codebench import (
    expected_signature,
    extract_calls,
    run_signature,
    same_bug_convergence,
)


def test_extract_and_execute_real_subprocess():
    calls = extract_calls(["assert f(2) == 3", "assert f(5) == 6"])
    assert len(calls) == 2
    exp = expected_signature(calls)              # ['3', '6']
    assert run_signature("def f(x): return x + 1", calls) == exp
    assert run_signature("def f(x): return x", calls) != exp        # off-by-one
    # a crashing program yields a sentinel, never a spurious match
    sig = run_signature("def f(x): return 1/0", calls)
    assert all(s.startswith("ERR") or s == "TIMEOUT" for s in sig)


def test_shared_bug_converges_null_zero():
    n = 25
    expected = [[str(q)] for q in range(n)]
    bug = [[str(q - 1)] for q in range(n)]       # same off-by-one in all three
    r = same_bug_convergence([bug, bug, bug], expected, seed=0)
    assert r["same_bug_convergence"] > 0.95
    assert r["permutation_null"] < 0.1           # ~0 in the open behavior space


def test_independent_bugs_do_not_converge():
    n = 25
    expected = [[str(q)] for q in range(n)]
    m1 = [[str(q - 1)] for q in range(n)]        # off by one
    m2 = [[str(q + 7)] for q in range(n)]        # off by seven
    m3 = [[str(q * 2)] for q in range(n)]        # doubling
    r = same_bug_convergence([m1, m2, m3], expected, seed=0)
    assert r["same_bug_convergence"] < 0.1
