"""The corpus's binding invariants (Part B2 + the design property).

These are the assertions that decide whether the corpus measures anything. Each
one corresponds to a way this build could have quietly become a tautology:

  - if `context` leaks the subtask boundaries, a strategy reads the answer out
    of its input and SR-1 measures nothing;
  - if any verdict field is derived from a structure field, the corpus measures
    whether merged work merged;
  - if a NONE verdict is defaulted to PASS, an absent measurement becomes a
    passing one (artifact #16's species: an error is not a value);
  - if the reference decomposition is stored as a target rather than as one
    strategy's output, there is one sample per goal and nothing to compare.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gyza.canon import values_equal

CORPUS = Path(__file__).resolve().parents[1] / "research" / "corpus" / "decompositions.json"

pytestmark = pytest.mark.skipif(not CORPUS.exists(),
                                reason="corpus not yet extracted (Part B)")


@pytest.fixture(scope="module")
def records():
    return json.loads(CORPUS.read_text())["records"]


# --------------------------------------------------------------------------- #
#  B2 — the leakage check                                                      #
# --------------------------------------------------------------------------- #
def test_context_does_not_contain_subtask_boundaries(records):
    """A strategy given goal+context must not be able to read the split off it."""
    bad = []
    for r in records:
        ctx = json.dumps(r["context"])
        for st in r["reference_decomposition"]["subtasks"]:
            if st["sha"] in ctx or st["sha"][:7] in ctx:
                bad.append((r["record_id"], "sha"))
            msg = st["message"].strip()
            if len(msg) > 12 and msg in ctx:
                bad.append((r["record_id"], "commit message"))
    assert not bad, f"context leaks subtask boundaries: {bad[:10]}"


def test_context_does_not_reveal_the_number_of_subtasks(records):
    """The commit count is the answer's LENGTH. A strategy that knows it is
    choosing among far fewer decompositions than one that does not."""
    for r in records:
        ctx = r["context"]
        assert "n_subtasks" not in ctx and "n_commits" not in ctx
        assert "subtasks" not in ctx and "commits" not in ctx


def test_context_carries_no_ordering_information(records):
    """Touch ORDER is decomposition information. files_touched is alphabetical."""
    for r in records:
        f = r["context"]["files_touched"]
        assert f == sorted(f), f"{r['record_id']}: files not alphabetical"


# --------------------------------------------------------------------------- #
#  THE DESIGN PROPERTY — structure and verdict from different sources          #
# --------------------------------------------------------------------------- #
def test_verdict_provenance_is_ci_and_names_its_tree_state(records):
    for r in records:
        src = r["outcome_source"]
        assert "CI check-runs" in src["kind"]
        assert len(src["tree_state"]) == 40, "the verdict must name the tree it ran on"
        assert src["command"].startswith("gh api ")
        assert src["evidence"], "a verdict with no evidence is an assertion"


def test_no_verdict_is_derived_from_merge_status(records):
    """The sharpest available mechanical proof of the separation: if `outcome`
    were merge status in disguise, these two populations would be empty."""
    merged_fail = [r for r in records if r["merged"] and r["outcome"] == "FAIL"]
    unmerged_pass = [r for r in records if not r["merged"] and r["outcome"] == "PASS"]
    assert merged_fail, "no merged-but-CI-FAIL record: outcome may be merge status"
    assert unmerged_pass, "no unmerged-but-CI-PASS record: outcome may be merge status"


def test_outcome_is_never_defaulted_and_never_none(records):
    """An absent verdict is not a passing one."""
    for r in records:
        assert r["outcome"] in ("PASS", "FAIL"), r["record_id"]
        assert values_equal(r["outcome"], r["outcome"])       # canon, not repr


def test_outcome_semantics_is_recorded_so_no_route_forgets_it(records):
    for r in records:
        s = r["outcome_semantics"]
        assert "NOT" in s and "goal was achieved" in s


# --------------------------------------------------------------------------- #
#  SR-1 must have something to compare                                         #
# --------------------------------------------------------------------------- #
def test_reference_decomposition_is_labelled_as_one_strategys_output(records):
    for r in records:
        lab = r["reference_decomposition"]["LABEL"]
        assert "ONE STRATEGY'S OUTPUT" in lab
        assert "NOT a target" in lab and "NOT ground truth" in lab


def test_every_subtask_type_assignment_carries_provenance(records):
    """Type assignment is itself a tier-3 claim; nothing may be self-declared."""
    for r in records:
        for st in r["reference_decomposition"]["subtasks"]:
            ct = st["claim_type"]
            assert set(ct) >= {"carrier", "assigned_by", "audited", "source"}
            assert ct["carrier"] in ("PROOF", "SPEC", "TEST", "NONE")
            assert isinstance(ct["audited"], bool)
            assert ct["source"], "an assignment with no source is self-declared"


def test_corpus_carries_both_outcome_classes_and_both_merge_classes(records):
    """Selection on success is the failure that disqualified source (i)."""
    assert len({r["outcome"] for r in records}) == 2, "outcome has no variance"
    assert len({r["merged"] for r in records}) == 2, "unmerged population dropped"


# --------------------------------------------------------------------------- #
#  The CODE-SUBSTANTIVE / INFRASTRUCTURE partition                             #
# --------------------------------------------------------------------------- #
import sys

sys.path.insert(0, str(CORPUS.parent))

ALL_CHECKS = CORPUS.parent / "all_checks.json"


@pytest.mark.skipif(not ALL_CHECKS.exists(), reason="check lists not fetched")
def test_every_observed_check_name_is_declared():
    """UNCLASSIFIED is a failure state, not a default. Defaulting an unknown
    check to either bucket is the same error as defaulting a missing verdict
    to PASS."""
    from check_taxonomy import classify

    names = {c["name"] for v in json.loads(ALL_CHECKS.read_text()).values() for c in v}
    undeclared = sorted(n for n in names if classify(n)[0] == "UNCLASSIFIED")
    assert not undeclared, (
        f"{len(undeclared)} check names match no rule; declare each in "
        f"check_taxonomy.RULES before use: {undeclared[:12]}")


def test_substantive_outcome_is_a_corpus_field_not_a_filter(records):
    for r in records:
        assert r["outcome_substantive"] in ("PASS", "FAIL", "NONE"), r["record_id"]
        p = r["checks_partition"]
        assert p["n_substantive"] + p["n_infrastructure"] == p["n_total"], (
            f"{r['record_id']}: checks unaccounted for — every check must land "
            f"in a declared bucket")


def test_substantive_none_is_not_treated_as_pass(records):
    """An absent verdict is not a passing one — the rule that governs the raw
    outcome governs the substantive one too."""
    none_recs = [r for r in records if r["outcome_substantive"] == "NONE"]
    for r in none_recs:
        assert r["checks_partition"]["n_substantive"] == 0, (
            "NONE must mean no substantive check ran, never 'none failed'")


def test_substantive_outcome_is_never_stricter_than_raw(records):
    """Direction check: the substantive set is a SUBSET of all checks, so it can
    only turn FAIL into PASS, never PASS into FAIL. A violation means the
    partition is dropping a failing check out of the raw set — i.e. the two
    verdicts were computed over inconsistent data."""
    bad = [r["record_id"] for r in records
           if r["outcome"] == "PASS" and r["outcome_substantive"] == "FAIL"]
    assert not bad, f"substantive FAIL under a raw PASS is impossible: {bad}"
