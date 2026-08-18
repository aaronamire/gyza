"""R-T regression tests.

The load-bearing claim is that CLUSTER COVERAGE, not defector count and not
defectors-per-cluster, governs breach. It is pinned here because it corrects a
published invariant and a later session must not re-derive it by reading R-B.
"""
from __future__ import annotations

from fractions import Fraction as F

import targeted as T

D, F_ARITY, DELTA, EPS = 3, 8, F(0), 1


def test_control_reproduces_r_b():
    """P-T0. A mismatch here voids every comparison in the route."""
    assert T.critical_k(D, F_ARITY, DELTA, EPS, T.RANDOM)["k_star"] == 103


def test_mechanism_runs_placement_is_measured_not_assumed():
    """Registering a placement rule is not evidence that it runs."""
    c_spare = T.cell(D, F_ARITY, DELTA, EPS, 103, T.SPARE)
    c_conc = T.cell(D, F_ARITY, DELTA, EPS, 103, T.CONCENTRATE)
    assert c_spare["defectors_in_target_cluster"] == 0
    assert c_conc["defectors_in_target_cluster"] == F_ARITY - 1 == 7


def test_sparing_the_target_does_not_help():
    """P-T4 refuted: the route's own hypothesis. SPARE is WORSE than RANDOM."""
    spare = T.critical_k(D, F_ARITY, DELTA, EPS, T.SPARE)["k_star"]
    assert spare is not None and spare > 103


def test_even_placement_nearly_halves_k_star():
    for arm in (T.EVEN_ALL, T.SPARE_EVEN):
        assert T.critical_k(D, F_ARITY, DELTA, EPS, arm)["k_star"] == 55


def test_cluster_coverage_is_55_in_every_arm():
    """The invariant. k*/clusters ranges 0.86..1.70; coverage does not move."""
    for arm in (T.CONCENTRATE, T.RANDOM, T.SPARE, T.EVEN_ALL, T.SPARE_EVEN):
        r = T.critical_k(D, F_ARITY, DELTA, EPS, arm)
        assert r["clusters_covered"] == 55, arm


def test_coverage_54_never_breaches_and_55_always_does():
    """Per-seed, which is what makes coverage a mechanism and not a summary."""
    for arm, ks in ((T.RANDOM, 103), (T.EVEN_ALL, 55)):
        for seed in range(3):
            lo = T.run_trial(D, F_ARITY, DELTA, EPS, ks - 1, arm, seed)
            assert lo["clusters_covered"] <= 54
            assert lo["violations"] == 0
            hi = T.run_trial(D, F_ARITY, DELTA, EPS, ks, arm, seed)
            assert (hi["violations"] > 0) == (hi["clusters_covered"] == 55)


def test_the_adversary_cannot_move_the_numerator():
    """§3: max is inert. Breach is entirely a denominator effect."""
    seen = set()
    for arm in (T.RANDOM, T.EVEN_ALL, T.CONCENTRATE):
        for k in (50, 103):
            r = T.run_trial(D, F_ARITY, DELTA, EPS, k, arm, 0)
            seen.add(r["peak_concentration"] is not None)
    assert seen == {True}
    # the target holds 14.001 whether 0, 1 or 7 defectors sit in its cluster
    from tree import Tree
    t = Tree(D, F_ARITY)
    assert t.leaf_total(T.TARGET) == 20 * 10 ** 9


def test_honest_refusal_is_zero_so_no_k_star_is_bought_with_throughput():
    """A containment number needs its counterfactual beside it."""
    for arm in (T.RANDOM, T.EVEN_ALL):
        c = T.cell(D, F_ARITY, DELTA, EPS, 55, arm)
        assert c["honest_refusal"] == 0.0


def test_eligible_domains_differ_and_do_not_confound():
    """SPARE arms have 7 fewer candidates; k* sits far from either limit."""
    assert T.eligible(T.RANDOM, 512, 8) == 511
    assert T.eligible(T.SPARE_EVEN, 512, 8) == 504
    assert 105 < 504, "if k* approached the domain limit it WOULD confound"


def test_coverage_is_not_invariant_across_depth():
    """CORRECTIONS 29: the falsification of this route's first headline.

    At d=2 full coverage is reached at k=24 and does NOT breach; k=25 has the
    same coverage and does. Coverage cannot be the governing quantity.
    """
    lo = T.run_trial(2, 23, F(0), 1, 24, T.EVEN_ALL, 0)
    hi = T.run_trial(2, 23, F(0), 1, 25, T.EVEN_ALL, 0)
    assert lo["clusters_covered"] == hi["clusters_covered"] == 23
    assert lo["violations"] == 0 and hi["violations"] > 0


def test_max_is_inert_so_breach_is_governed_by_the_denominator():
    """The invariant that survives both depths (FINDINGS 3.1)."""
    from tree import Tree
    for d, f in ((2, 23), (3, 8)):
        assert Tree(d, f).leaf_total(T.TARGET) == 20 * 10 ** 9
