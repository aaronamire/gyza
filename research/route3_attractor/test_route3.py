"""
Correctness anchor for Route 3. Synthetic — no cache, no network. Covers the
six checks in the task plus the ADDENDUM-2 held-out-lift / McNemar corrections.
If these fail, no real number is trustworthy.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from route3_experiment import (  # noqa: E402
    canon_tokens, excess_cell, heldout_lift, mcnemar, escape_rate,
)
from route2_experiment import _sym_equal, cluster_answers  # noqa: E402
from conditional_independence_null import (  # noqa: E402
    baseline_convergence, is_non_answer, observed_convergence,
)


def pp(x):
    return [x]


# 1. canonicalization
def test_canonicalization():
    assert _sym_equal("1/2", "0.5") and _sym_equal("1/2", "\\frac{1}{2}")
    ids = cluster_answers(["1/2", "0.5", "\\frac{1}{2}"])
    assert ids[0] == ids[1] == ids[2]
    # 2/3 (attractor) vs 1/2 (true) stay distinct
    ids2 = cluster_answers(["1/2", "2/3"])
    assert ids2[0] != ids2[1]


# 2. attractor detection via canon_tokens (0=true, 1=attractor, 2..=agents)
def test_attractor_detection():
    # true=8, attractor=9; agents: 8, 9, 9, 7
    toks = canon_tokens(["8", "9", "8", "9", "7"])
    true_tok, attr_tok = toks[0], toks[1]
    assert true_tok != attr_tok
    assert toks[2] == true_tok           # agent "8" -> correct, not attractor-hit
    assert toks[3] == attr_tok           # agent "9" -> attractor-hit
    assert toks[4] not in (true_tok, attr_tok)   # "7" -> other-wrong
    # canonical equivalence still collapses: attractor "9" vs "9.0"
    toks2 = canon_tokens(["8", "9", "9.0"])
    assert toks2[1] == toks2[2]


# 3. sentinel guard
def test_sentinel_never_agreement():
    expected = [pp("OK")]
    si = [pp("IMPORTERR:NOANSWER")]
    sj = [pp("IMPORTERR:NOANSWER")]
    assert is_non_answer(si[0])
    conv, d = observed_convergence(si, sj, expected)
    assert d == 1 and conv == 0.0
    sigs = [[pp("Wi")], [pp("Wj")], [pp("TIMEOUT")], [pp("IMPORTERR:X")], [pp("Z")]]
    base, _ = baseline_convergence(0, 1, sigs, expected, [0, 1, 2, 3, 4])
    assert base == 0.0
    # canon_tokens excludes sentinels from clustering
    toks = canon_tokens(["8", "IMPORTERR:NOANSWER", "TIMEOUT", "8"])
    assert 1 not in toks and 2 not in toks and toks[0] == toks[3]


# 4. estimator reuse: baseline 1/3
def test_baseline_two_of_three():
    expected = [pp("OK")]
    sigs = [[pp("Wi")], [pp("Wj")], [pp("A")], [pp("A")], [pp("B")]]
    base, d = baseline_convergence(0, 1, sigs, expected, [0, 1, 2, 3, 4])
    assert d == 1 and abs(base - 1.0 / 3.0) < 1e-9


# 5. crowd-following => excess ~ 0
def test_crowd_following_zero_excess():
    n = 6
    expected = [pp("OK")] * n
    sigs = [[pp("D") for _ in range(n)] for _ in range(6)]
    out = excess_cell([(0, 1)], sigs, expected, list(range(6)), set(range(n)), seed=1)
    p = out["per_pair"][0]
    assert abs(p["observed"] - 1.0) < 1e-9 and abs(p["baseline"] - 1.0) < 1e-9
    assert abs(p["excess"]) < 1e-9


# 6. HELD-OUT trust-lift: agreement always correct => lift = 1 - heldout_acc
def test_heldout_lift_agreement_always_correct():
    # 4 items; pair (0,1) always agree on the TRUE answer "OK"; held-out agents
    # 2,3 have known accuracy on those items.
    expected = [pp("OK")] * 4
    sigs = [
        [pp("OK"), pp("OK"), pp("OK"), pp("OK")],   # 0
        [pp("OK"), pp("OK"), pp("OK"), pp("OK")],   # 1
        [pp("OK"), pp("X"), pp("OK"), pp("X")],     # 2 held-out: acc 2/4=0.5
        [pp("OK"), pp("OK"), pp("X"), pp("X")],     # 3 held-out: acc 2/4=0.5
    ]
    out = heldout_lift(0, 1, [2, 3], sigs, expected, set(range(4)), seed=1)
    assert out["n_agree"] == 4
    assert abs(out["precision_item_ci"][0] - 1.0) < 1e-9
    # mean held-out acc per item = (0.5-ish); overall lift = 1 - mean_heldout_acc
    mean_ho = (0.5 + 0.5) / 2  # both held-out agents avg 0.5 accuracy
    assert abs(out["lift_vs_mean_item_ci"][0] - (1.0 - mean_ho)) < 1e-9


def test_heldout_lift_pair_alone_is_not_used():
    # sanity: the pair itself is NOT the comparator (that would give 0); a
    # held-out agent that is always right yields lift 0, always wrong yields 1.
    expected = [pp("OK")] * 3
    sigs = [[pp("OK")] * 3, [pp("OK")] * 3, [pp("OK")] * 3, [pp("Z")] * 3]
    right = heldout_lift(0, 1, [2], sigs, expected, set(range(3)), seed=1)
    wrong = heldout_lift(0, 1, [3], sigs, expected, set(range(3)), seed=1)
    assert abs(right["lift_vs_mean_item_ci"][0] - 0.0) < 1e-9
    assert abs(wrong["lift_vs_mean_item_ci"][0] - 1.0) < 1e-9


# McNemar (C3): paired escape
def test_mcnemar_discordant():
    # attractor token = "A" (attractor_tok is a list of string tokens);
    # agent0 escapes on q0,q1; agent1 escapes on q2 only.
    attr = ["A", "A", "A", "A"]
    sigs = [
        [["T"], ["T"], ["A"], ["A"]],   # agent0 escapes q0,q1 (gives T), hits A on q2,q3
        [["A"], ["A"], ["T"], ["A"]],   # agent1 escapes q2 only
    ]
    m = mcnemar(0, 1, sigs, attr, [0, 1, 2, 3])
    assert m["a_escapes_b_not"] == 2 and m["b_escapes_a_not"] == 1
    assert m["discordant"] == 3
    # escape_rate sanity
    assert abs(escape_rate(0, sigs, attr, [0, 1, 2, 3]) - 0.5) < 1e-9
