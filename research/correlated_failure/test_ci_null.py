"""
Tests for the conditional-independence null. Synthetic signatures with
known agreement structure — no cache, no network. Pins the four cases the
task specifies, including the artifact-#4 sentinel guard.

Data model (matches codebench): a model's full signature is a list over
problems; each per-problem signature is a list[str] (one entry per test
call). ``pp(x)`` builds a one-call per-problem signature ``[x]``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from conditional_independence_null import (  # noqa: E402
    baseline_convergence, is_non_answer, observed_convergence,
)


def pp(x: str) -> list[str]:
    """A one-call per-problem behavioral signature."""
    return [x]


def test_baseline_two_of_three_agree():
    # other-wrong = [A, A, B]: agreeing = C(2,2)+C(1,2) = 1, total = C(3,2) = 3,
    # baseline = 1/3.
    expected = [pp("OK")]
    # 0=i, 1=j (both wrong, distinct); 2,3=A, 4=B — all wrong on the problem.
    sigs = [[pp("Wi")], [pp("Wj")], [pp("A")], [pp("A")], [pp("B")]]
    base, d = baseline_convergence(0, 1, sigs, expected, [0, 1, 2, 3, 4])
    assert d == 1
    assert abs(base - 1.0 / 3.0) < 1e-9


def test_baseline_all_distinct_is_zero():
    # other-wrong = [A, B, C, D]: every C(1,2)=0 -> baseline = 0.
    expected = [pp("OK")]
    sigs = [[pp("Wi")], [pp("Wj")],
            [pp("A")], [pp("B")], [pp("C")], [pp("D")]]
    base, d = baseline_convergence(0, 1, sigs, expected, [0, 1, 2, 3, 4, 5])
    assert d == 1
    assert base == 0.0


def test_following_the_crowd_gives_zero_excess():
    # i and j both always emit the population's dominant wrong answer "D",
    # and so does everyone else wrong. Observed = 1, baseline = 1 -> excess
    # ~ 0: following the crowd is not pairwise-specific correlation.
    nprob = 6
    expected = [pp("OK")] * nprob
    sigs = [[pp("D") for _ in range(nprob)] for _ in range(6)]
    ref = list(range(6))
    obs, _ = observed_convergence(sigs[0], sigs[1], expected)
    base, _ = baseline_convergence(0, 1, sigs, expected, ref)
    assert abs(obs - 1.0) < 1e-9
    assert abs(base - 1.0) < 1e-9
    assert abs(obs - base) < 1e-9   # excess ~ 0


def test_sentinel_collision_excluded_from_observed_and_baseline():
    # Artifact #4: a problem where i and j both emit TIMEOUT must NOT count
    # as agreement, in observed OR baseline.
    expected = [pp("OK")]
    si = [pp("TIMEOUT")]
    sj = [pp("TIMEOUT")]
    assert is_non_answer(si[0])       # the guard recognizes the per-problem sig
    conv, d = observed_convergence(si, sj, expected)
    assert d == 1                     # both are wrong, so it IS a both-wrong problem
    assert conv == 0.0                # ...but excluded from agreement (not 1.0)

    # baseline: two OTHER models also TIMEOUT must not form an agreeing pair.
    # others = [TIMEOUT, TIMEOUT, Z]: answer-bearing agreeing = 0 (Z alone),
    # total = C(3,2) = 3 -> baseline = 0 (would be 1/3 if TIMEOUTs counted).
    sigs = [[pp("Wi")], [pp("Wj")],
            [pp("TIMEOUT")], [pp("TIMEOUT")], [pp("Z")]]
    base, _ = baseline_convergence(0, 1, sigs, expected, [0, 1, 2, 3, 4])
    assert base == 0.0


def test_err_is_answer_bearing_in_primary_but_not_in_err_variant():
    # Two models both emitting ERR:TypeError agree under the PRIMARY sentinel
    # set (ERR is behavior), but not when all-ERR is excluded (ERR variant).
    expected = [pp("OK")]
    si = [pp("ERR:TypeError")]
    sj = [pp("ERR:TypeError")]
    assert not is_non_answer(si[0], include_err=False)   # primary: answer-bearing
    assert is_non_answer(si[0], include_err=True)          # variant: non-answer
    conv_primary, _ = observed_convergence(si, sj, expected, include_err=False)
    conv_variant, _ = observed_convergence(si, sj, expected, include_err=True)
    assert conv_primary == 1.0
    assert conv_variant == 0.0
