"""
Correctness anchor for the Route 2 experiment. Synthetic — no cache, no
network, no API. If these fail, no real number is trustworthy. Mirrors the
five checks named in the task, plus executor-reuse self-tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from route2_experiment import (  # noqa: E402
    _sym_equal, cluster_answers, cell_excess, cell_lift, execute_code,
    extract_boxed, _extract_code,
)
from conditional_independence_null import (  # noqa: E402
    baseline_convergence, is_non_answer, observed_convergence,
)
from codebench import run_signature  # noqa: E402


def pp(x):
    return [x]


# --- 1. canonicalization -----------------------------------------------------
def test_canonicalization_equivalences():
    assert _sym_equal("1/2", "0.5")
    assert _sym_equal("1/2", "\\frac{1}{2}")
    assert _sym_equal("0.5", "\\frac{1}{2}")
    assert _sym_equal("x+1", "1+x")
    assert not _sym_equal("3", "4")


def test_canonicalization_clustering():
    # 1/2, 0.5, \frac{1}{2} collapse to ONE signature; 3 is distinct.
    ids = cluster_answers(["1/2", "0.5", "\\frac{1}{2}", "3"])
    assert ids[0] == ids[1] == ids[2]
    assert ids[3] != ids[0]
    # distinct wrongs stay distinct
    ids2 = cluster_answers(["3", "4", "5"])
    assert len(set(ids2)) == 3


# --- 2. sentinel guard -------------------------------------------------------
def test_sentinel_never_counts_as_agreement():
    expected = [pp("OK")]
    si = [pp("IMPORTERR:NOANSWER")]
    sj = [pp("IMPORTERR:NOANSWER")]
    assert is_non_answer(si[0])
    conv, d = observed_convergence(si, sj, expected)
    assert d == 1 and conv == 0.0            # both wrong, but NOT agreement
    # baseline: two other no-answer agents must not form an agreeing pair
    sigs = [[pp("Wi")], [pp("Wj")],
            [pp("TIMEOUT")], [pp("IMPORTERR:NOANSWER")], [pp("Z")]]
    base, _ = baseline_convergence(0, 1, sigs, expected, [0, 1, 2, 3, 4])
    assert base == 0.0


def test_sentinel_excluded_from_trust_lift():
    # a pair that only "agrees" via both being no-answer contributes no
    # agree-problem -> no lift entry.
    expected = [pp("OK"), pp("OK")]
    sigs = [[pp("IMPORTERR:NOANSWER"), pp("W")],
            [pp("IMPORTERR:NOANSWER"), pp("W")]]  # agree on q1 (real "W")
    out = cell_lift([(0, 1)], sigs, expected, {0, 1}, [0, 1], seed=1)
    # only q1 is a real agreement (both "W", wrong) -> precision 0, 1 pair
    assert out["n_pairs"] == 1
    assert out["per_pair"][0]["n_agree"] == 1


# --- 3. estimator reuse (baseline = 1/3) ------------------------------------
def test_baseline_two_of_three_agree():
    expected = [pp("OK")]
    sigs = [[pp("Wi")], [pp("Wj")], [pp("A")], [pp("A")], [pp("B")]]
    base, d = baseline_convergence(0, 1, sigs, expected, [0, 1, 2, 3, 4])
    assert d == 1 and abs(base - 1.0 / 3.0) < 1e-9


# --- 4. crowd-following => excess ~ 0 ---------------------------------------
def test_following_crowd_zero_excess():
    n = 6
    expected = [pp("OK")] * n
    sigs = [[pp("D") for _ in range(n)] for _ in range(6)]  # everyone -> "D"
    out = cell_excess([(0, 1)], sigs, expected, list(range(6)),
                      set(range(n)), seed=1)
    p = out["per_pair"][0]
    assert abs(p["observed"] - 1.0) < 1e-9
    assert abs(p["baseline"] - 1.0) < 1e-9
    assert abs(p["excess"]) < 1e-9              # crowd-following is not excess


# --- 5. trust-lift sanity: agreement always correct => lift = 1 - single_acc -
def test_trust_lift_agreement_always_correct():
    expected = [pp("OK")] * 4
    sigs = [[pp("OK"), pp("OK"), pp("W1"), pp("W2")],   # acc 2/4
            [pp("OK"), pp("OK"), pp("W3"), pp("W4")]]   # acc 2/4; agree only on OK
    out = cell_lift([(0, 1)], sigs, expected, {0, 1, 2, 3}, [0, 1], seed=1)
    assert abs(out["single_acc"] - 0.5) < 1e-9
    pp0 = out["per_pair"][0]
    assert abs(pp0["agree_precision"] - 1.0) < 1e-9
    assert abs(pp0["lift"] - (1.0 - out["single_acc"])) < 1e-9


# --- executor reuse self-tests ----------------------------------------------
def test_codebench_run_signature_importable_and_runs():
    # the imported executor still works (5s timeout, sentinel on crash)
    sig = run_signature("def f(x):\n    return x+1\n", [("f(1)", "2")])
    assert sig == ["2"]
    bad = run_signature("def f(x):\n    return undefined_name\n", [("f(1)", "2")])
    assert bad[0].startswith("ERR:")


def test_execute_code_boxed_and_sentinels():
    ok = execute_code("import sympy\nprint('\\\\boxed{' + str(sympy.Rational(1,2)) + '}')")
    assert extract_boxed("\\boxed{" + ok + "}") or ok  # returns '1/2'
    assert ok == "1/2"
    assert execute_code("import sys\nsys.exit(1)").startswith("IMPORTERR")
    assert execute_code("while True:\n    pass\n") == "TIMEOUT"
    # prose is rejected (must canonicalize as a math value); bare numeric ok
    assert execute_code("print('no answer here at all ...')").startswith("IMPORTERR")
    assert execute_code("print('the result is unknown')").startswith("IMPORTERR")
    assert execute_code("print(42)") == "42"


def test_extract_code_and_boxed():
    assert _extract_code("```python\nx=1\n```") == "x=1"
    assert extract_boxed("stuff \\boxed{42} more") == "42"
    assert extract_boxed("a \\boxed{1} b \\boxed{\\frac{1}{2}} c") == "\\frac{1}{2}"
    assert extract_boxed("no box") == ""
