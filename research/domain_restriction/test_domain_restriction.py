"""Route DR gate tests. Green before any result is trusted."""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import dr_experiment as D                                  # noqa: E402
from gyza.canon import values_equal                        # noqa: E402
from gyza.verification.adapters import NATIVE              # noqa: E402


# --------------------------------------------------------------------------- #
#  VERIFIER PROVENANCE — the whole point of the route                          #
# --------------------------------------------------------------------------- #
def _defines_a_verifier(module_src: str) -> bool:
    """Does this module DEFINE a scoring predicate, rather than import one?

    Heuristic with a stated shape: a function whose name says it verifies /
    checks / validates and that returns a bool-ish comparison.
    """
    tree = ast.parse(module_src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(k in n.name.lower()
                   for k in ("verify", "check", "validate", "is_correct")):
                return True
    return False


def test_no_verifier_was_authored_during_this_route():
    """Every verifier used in scoring pre-exists this route and is IMPORTED."""
    src = (HERE / "dr_experiment.py").read_text()
    assert not _defines_a_verifier(src), (
        "the experiment module defines a verifier; scoring must import from "
        "gyza.verification.adapters, which pre-exists this route")
    assert "from gyza.verification.adapters import" in src


def test_the_provenance_check_has_power_negative_control():
    """If this passed on a module that DOES define a verifier, the assertion
    above would be vacuous."""
    bad = "def verify_thing(x):\n    return x == 1\n"
    assert _defines_a_verifier(bad), (
        "the provenance check cannot detect an authored verifier -- it proves "
        "nothing")


def test_every_scored_carrier_comes_from_the_shipped_registry():
    vocab = D.vocabulary()
    assert len(vocab) == 18, len(vocab)
    for v in NATIVE:
        assert vocab[v.claim_type] == v.carrier, v.claim_type


# --------------------------------------------------------------------------- #
#  REFUSAL IS REFUSAL                                                          #
# --------------------------------------------------------------------------- #
def test_a_refusal_is_a_coverage_miss_not_a_failure_and_not_a_success():
    vocab = D.vocabulary()
    r = D.run_arm("RESTRICTED", 4, 0.0, vocab, [True] * 50, n_tasks=500)
    assert r.n_refused > 0, "precondition: some chains must be refused"
    # refusals are outside BOTH correctness buckets
    assert r.n_attempted + r.n_refused == r.n_total
    assert r.n_correct + r.n_caught + r.n_silent_wrong == r.n_attempted, (
        "a refusal must not be counted as correct, caught, or silently wrong")


def test_refusing_everything_gives_correctness_one_and_useful_work_zero():
    """The architectural form of the TPR-without-FPR trap; metric 3 exists to
    catch it."""
    vocab = {"only_semantic": "NONE"}
    r = D.run_arm("RESTRICTED", 1, 0.0, vocab, [True] * 10, n_tasks=200).__dict__
    d = D.ArmResult(**r).as_dict()
    assert d["coverage"] == 0.0
    assert d["correctness_on_attempted"] is None, (
        "correctness over zero attempts is UNDEFINED, not 1.0 -- an empty "
        "denominator is not perfect performance")
    assert d["useful_work"] == 0.0


# --------------------------------------------------------------------------- #
#  COMPOSED CORRECTNESS / the tier algebra                                     #
# --------------------------------------------------------------------------- #
def test_a_chain_with_one_TEST_stage_is_tier_3():
    from gyza.verification.scheduler import consult_tier_algebra

    d = consult_tier_algebra(["PROOF", "TEST", "PROOF"], [1, 1, 1], depth=3)
    assert d.tier == 3, "SR-3: one finite-sample stage forces the chain to 3"
    allproof = consult_tier_algebra(["PROOF", "PROOF"], [1, 1], depth=3)
    assert allproof.tier == 1


def test_TEST_is_excluded_from_the_restricted_composing_set():
    """The restriction admits exactly what SR-3 licenses."""
    assert "TEST" not in D.COMPOSING
    assert set(D.COMPOSING) == {"PROOF", "SPEC"}


def test_semantic_steps_use_external_ground_truth_with_errors_excluded():
    sem = D.semantic_outcomes()
    assert len(sem) > 500, len(sem)
    assert all(isinstance(x, bool) for x in sem), "None (error) must be dropped"
    rate = sum(sem) / len(sem)
    assert 0.30 < rate < 0.45, f"measured MBPP reliability drifted: {rate}"


# --------------------------------------------------------------------------- #
#  CANONICAL COMPARISON                                                        #
# --------------------------------------------------------------------------- #
def test_verdict_comparisons_go_through_canon():
    src = (HERE / "dr_experiment.py").read_text()
    assert "from gyza.canon import values_equal" in src
    assert values_equal(0.05, 0.05) and not values_equal(0.05, 0.2)


def test_depth_is_capped_where_the_cells_stay_populated():
    """0c's non-vacuity bound: depth 16 would leave RESTRICTED at 0.0055."""
    assert max(D.DEPTHS) == 8


def test_determinism():
    vocab = D.vocabulary(); sem = D.semantic_outcomes()
    a = D.run_arm("GENERAL", 4, 0.05, vocab, sem, n_tasks=300).as_dict()
    b = D.run_arm("GENERAL", 4, 0.05, vocab, sem, n_tasks=300).as_dict()
    assert a == b
