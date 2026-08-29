"""
Route 8 tests — must pass before any result is trusted. The six preregistered checks:
isolation, reference-filter, arm-P purity, sentinel discipline, conservatism, and the
zero-valid-test exclusion.
Run: ~/dev/marshal/.os/bin/python -m pytest research/native_verifier/test_native_verifier.py -q
"""
from __future__ import annotations

import native_verifier as V

_PROBLEM = {
    "prompt": "Write a function to return the sorted list of a given list of integers.",
    "code": "def sort_list(a):\n    return sorted(a)   # REFERENCE_SOLUTION_SECRET",
    "test_list": ["assert sort_list([3,1,2]) == [1,2,3]",
                  "assert sort_list([9,0]) == [0,9]"],
}


def test_isolation_prompt_leaks_nothing():
    for arm in ("E", "P"):
        p = V.testgen_prompt(_PROBLEM, "sort_list", arm)
        assert _PROBLEM["prompt"] in p            # contains the problem statement
        assert "sort_list" in p                   # contains the entry_point
        assert "REFERENCE_SOLUTION_SECRET" not in p        # NOT the reference solution
        assert "sorted(a)" not in p                        # NOT the reference body
        for t in _PROBLEM["test_list"]:
            assert t not in p                              # NOT the original asserts
        assert "== [1,2,3]" not in p                       # NOT an expected output


def test_reference_filter_excludes_wrong_tests():
    ref = "def f(x):\n    return x + 1"
    assert V.test_is_valid("assert f(1) == 2", ref)        # passes reference -> valid
    assert not V.test_is_valid("assert f(1) == 999", ref)  # fails reference -> INVALID
    assert not V.test_is_valid("assert undefined_helper(f(1))", ref)  # errors -> INVALID


def test_armP_purity_flags_smuggled_expected_output():
    # a concrete expected output smuggled into a "property" test
    assert V.is_smuggled_example("assert f([3,1,2]) == [1,2,3]", "f")
    assert V.is_smuggled_example("assert f(5) == 25", "f")
    # genuine properties: no concrete expected literal
    assert not V.is_smuggled_example("assert sorted(f(x)) == f(x)", "f")
    assert not V.is_smuggled_example("assert len(f(x)) == len(x)", "f")
    assert not V.is_smuggled_example("assert f(f(x)) == f(x)", "f")
    assert not V.is_smuggled_example("assert isinstance(f(x), list)", "f")


def test_sentinel_discipline_unresolved_excluded():
    exp = ["[1, 2, 3]", "[0, 9]"]
    assert V.program_status(["TIMEOUT", "TIMEOUT"], exp) == "UNRESOLVED"
    assert V.program_status(["IMPORTERR:SyntaxError"], exp) == "UNRESOLVED"
    # generation failure (__ERR__ source) is UNRESOLVED, never scored as a bug
    assert V.program_status(["ERR:NameError"], exp, source="__ERR__:HTTPError") == "UNRESOLVED"
    assert V.program_status(["[1, 2, 3]", "[0, 9]"], exp) == "CORRECT"
    assert V.program_status(["[3, 2, 1]", "[9, 0]"], exp) == "WRONG"   # ran, wrong output


def test_bug_classification_three_way():
    exp = ["6", "10", "3"]
    assert V.classify_bug(["6", "10", "3"], exp) is None                # correct
    assert V.classify_bug(["6", "9", "3"], exp) == "COMPUTATIONAL"      # partial right
    assert V.classify_bug(["7", "9", "2"], exp) == "COMPUTATIONAL"      # right type wrong val
    assert V.classify_bug(["ERR:TypeError"] * 3, exp) == "CRASH"        # crashes -> 3rd class
    assert V.classify_bug(["[1]", "[2]", "[3]"], exp) == "COMPREHENSION"  # wrong shape


def test_conservatism_correct_program_valid_tests_no_fire():
    prog = "def sort_list(a):\n    return sorted(a)"
    valid = ["assert sort_list([3,1,2]) == [1,2,3]",           # example, true
             "assert len(sort_list([3,1,2])) == 3",            # property, true
             "assert sort_list(sort_list([3,1,2])) == sort_list([3,1,2])"]  # idempotence
    # every test passes the correct program -> suite must NOT fire (FPR contribution 0)
    assert V.suite_fires(valid, prog) is False
    assert V.score_triple(valid, prog, wrong=False) == (False, False)


def test_zero_valid_tests_excluded_from_both():
    prog = "def f(x):\n    return x"
    assert V.score_triple([], prog, wrong=True) is None    # coverage loss, not detection
    assert V.score_triple([], prog, wrong=False) is None
    assert V.metrics_from_pairs([])["n"] == 0              # empty -> no metric


def test_detection_true_positive_sanity():
    # a valid test that a buggy program fails -> suite fires -> true positive
    buggy = "def sort_list(a):\n    return a          # bug: does not sort"
    valid = ["assert sort_list([3,1,2]) == [1,2,3]"]
    assert V.suite_fires(valid, buggy) is True
    assert V.score_triple(valid, buggy, wrong=True) == (True, True)
