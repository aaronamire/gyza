"""The split assertion, and a NEGATIVE CONTROL proving the assertion can fire.

An assertion that has never been observed to fail is not evidence of anything
-- this program has caught a harm quantity that raised on every input while
785 tests passed, and a monotonicity check that tested a label instead of the
protected quantity. So each test here comes in a pair: the real split passes,
and an injected leak of the same species FAILS.

Run:  ~/dev/marshal/.os/bin/python -m pytest research/internal_channel/test_split.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from probe import check_split, complexity, make_split


def _rows(n: int = 200) -> list[dict]:
    rng = np.random.default_rng(0)
    return [{"task_id": 1000 + i, "cx": int(rng.integers(5, 120)),
             "y": int(rng.integers(0, 2))} for i in range(n)]


def test_split_is_disjoint_by_problem_id():
    rows = _rows()
    parts = make_split(rows)
    check_split(parts, len(rows))


def test_split_is_exhaustive_and_partitions_every_problem():
    rows = _rows()
    parts = make_split(rows)
    seen = [r["task_id"] for v in parts.values() for r in v]
    assert sorted(seen) == sorted(r["task_id"] for r in rows)
    assert len(seen) == len(set(seen)), "a problem appears twice"


def test_easy_hard_are_separated_by_the_difficulty_axis():
    """TEST-OUT must be strictly harder than TRAIN, or it is not 'outside'."""
    rows = _rows()
    parts = make_split(rows)
    assert min(r["cx"] for r in parts["TEST-OUT"]) >= max(
        r["cx"] for r in parts["TRAIN"]), "EASY/HARD overlap on the axis"


# --------------------------------------------------------------------------- #
#  NEGATIVE CONTROLS -- each injects a leak and requires the check to CATCH it #
# --------------------------------------------------------------------------- #

def test_negative_control_train_test_in_leak_is_caught():
    rows = _rows()
    parts = make_split(rows)
    parts["TEST-IN"] = parts["TEST-IN"] + [parts["TRAIN"][0]]      # duplicate one
    with pytest.raises(AssertionError, match="LEAK: TEST-IN n TRAIN|LEAK: TRAIN n TEST-IN"):
        check_split(parts, len(rows) + 1)


def test_negative_control_train_test_out_leak_is_caught():
    rows = _rows()
    parts = make_split(rows)
    parts["TEST-OUT"] = parts["TEST-OUT"] + [parts["TRAIN"][3]]
    with pytest.raises(AssertionError, match="LEAK"):
        check_split(parts, len(rows) + 1)


def test_negative_control_dropped_problem_is_caught():
    """The other direction: silently losing problems is also a broken split."""
    rows = _rows()
    parts = make_split(rows)
    parts["TRAIN"] = parts["TRAIN"][:-5]
    with pytest.raises(AssertionError, match="not exhaustive"):
        check_split(parts, len(rows))


def test_negative_control_example_level_split_would_leak():
    """The species this design rules out ARCHITECTURALLY.

    If a problem contributed several examples -- several token positions, say
    -- a naive shuffle would put some in TRAIN and some in TEST under the same
    task_id. The experiment stores ONE vector per problem so this cannot
    arise; the control shows the check would catch it if it did.
    """
    rows = _rows(100)
    duplicated = rows + [dict(r) for r in rows]        # 2 examples per problem
    med = float(np.median([r["cx"] for r in duplicated]))
    easy = [r for r in duplicated if r["cx"] < med]
    idx = np.random.default_rng(1).permutation(len(easy))
    leaky = {"TRAIN": [easy[i] for i in idx[:len(easy) // 2]],
             "TEST-IN": [easy[i] for i in idx[len(easy) // 2:]],
             "TEST-OUT": [r for r in duplicated if r["cx"] >= med]}
    with pytest.raises(AssertionError, match="LEAK"):
        check_split(leaky, len(duplicated))


def test_complexity_is_label_independent_and_deterministic():
    """The stratification axis must be a property of the BENCHMARK.

    It reads MBPP's reference solution and nothing the model produced, so it
    cannot encode the outcome it is used to stratify.
    """
    src = "def f(x):\n    return sorted(x)[0]\n"
    assert complexity(src) == complexity(src)
    assert complexity(src) > complexity("def f(x): return x")
    assert complexity("def f(: syntax error") > 0        # never raises
