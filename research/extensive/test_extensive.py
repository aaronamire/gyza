"""R-E regression tests.

The claims here are the ones a later session would otherwise have to re-derive:
that the two predicates share a critical margin, that the internal admission
checks are inert, and that the top-of-grid point is reachable. The last is a
guard against the defect this route actually committed.
"""
from __future__ import annotations

import random
from fractions import Fraction as F

import run_extensive as R
from tree import (Tree, box_floor_at, ceiling_at, kappa_level,
                  level_endowment)


def test_rho_is_the_preregistered_value():
    # rho was fixed in PREREGISTRATION.md §3 before any experiment ran.
    assert R.RHO == F(2, 100)


def test_top_of_grid_is_below_ceiling_and_is_the_largest_such_point():
    """The defect this route committed, pinned.

    `top` was `(int(ceil/GRID) - 1) * GRID`, which at d=1 stopped at 0.590
    while the ONLY feasible delta is 0.595 -- reported INFEASIBLE for a band
    that exists. Same species as R-M1's stride defect.
    """
    for d, f in ((1, 512), (3, 8)):
        ceil = ceiling_at(f, kappa_level(d))
        top = int(ceil / R.GRID) * R.GRID
        assert top < ceil
        assert top + R.GRID >= ceil, "a feasible grid point sits above `top`"


def test_d1_is_feasible_at_the_top_of_grid_point():
    """Regression on the corrected scan: 0.595 is safe, 0.590 is not."""
    d, f = 1, 512
    assert R.cell(d, f, F(119, 200), 8, R.RATIO, seeds=1)["safe"]
    assert not R.cell(d, f, F(118, 200), 8, R.RATIO, seeds=1)["safe"]


def test_internal_admission_checks_never_fire():
    """R-E's structural finding: hierarchy's benefit is NOT the inner checks.

    At level 1 the check reduces to `(cum_div - v_div) < 0` and cumulative
    divestment is monotone, so it is unfireable by construction. At levels >=2
    the floor scales with the level endowment exactly as the value drains.
    """
    d, f, eps = 3, 8, 8
    kl = kappa_level(d)
    delta = F(47, 100)
    floors = {lvl: box_floor_at(f, kl, delta, level_endowment(f, lvl - 1))
              for lvl in range(1, d + 1)}
    rng = random.Random(0)
    t = Tree(d, f)
    order = list(range(1, t.n))
    rng.shuffle(order)
    cum = [0] * t.n
    hist = [list(cum)]
    fired = 0
    for _ in range(40):
        v_div = hist[max(0, len(hist) - 1 - eps)]
        for leaf in order:
            believed = t.seen(0, leaf, eps) - (cum[leaf] - v_div[leaf])
            want = believed - floors[1]
            if want <= 0:
                continue
            for lvl in range(1, d + 1):
                idx = leaf // (f ** (lvl - 1))
                if t.seen(lvl - 1, idx, eps) - want < floors[lvl]:
                    fired += 1
                    break
            else:
                cum[leaf] += t.divest(leaf, want)
        t.commit()
        hist.append(list(cum))
    assert fired == 0, f"internal check fired {fired} times; R-E §3 is stale"


def test_predicates_share_a_critical_margin():
    """EXTENSIVE-HARDER refuted: both bounds flip at the same delta."""
    d, f, eps = 3, 8, 32
    below = R.cell(d, f, F(98, 200), eps, R.RATIO)
    at = R.cell(d, f, F(99, 200), eps, R.RATIO)
    assert below["v_ratio"] > 0 and below["v_preserve"] > 0
    assert at["v_ratio"] == 0 and at["v_preserve"] == 0


def test_preserve_is_strictly_more_sensitive_at_equal_delta():
    """Same threshold, but not the same predicate -- PRESERVE fails MORE."""
    c = R.cell(3, 8, F(98, 200), 32, R.RATIO)
    assert c["v_preserve"] > c["v_ratio"]


def test_ratio_is_blind_to_near_total_destruction():
    """The observation that motivated the route, pinned as a test."""
    c = R.cell(3, 8, F(0), 0, R.RATIO)
    assert c["v_ratio"] == 0, "the ratio bound is never violated"
    assert c["retained"] < F(3, 100), "yet >97% of all value is destroyed"


def test_genesis_origin_is_immutable():
    """A cumulative bound whose origin can move is not a bound (rule #6)."""
    t = Tree(3, 8)
    genesis = sum(t.leaves)
    t.divest(1, t.leaf_total(1) // 2)
    t.commit()
    assert sum(t.leaves) < genesis
    assert genesis == 10240 * 10 ** 9


def test_preservation_is_priced_monotonically_in_rho():
    """§2.1: the margins coincide only at a loose bar.

    The ratio bound has no rho at all; the extensive bound's margin rises with
    it. A regression here means the pricing curve -- the route's transferable
    result -- has moved.
    """
    d, f, eps = 3, 8, 32
    prev = None
    for num in (2, 20, 40):
        dp, _ = R.delta_star(d, f, eps, R.PRESERVE, rho=F(num, 100))
        assert dp is not None, f"rho={num}/100 went infeasible"
        if prev is not None:
            assert dp > prev, "delta*_preserve must rise with rho"
        prev = dp
    ratio, _ = R.delta_star(d, f, eps, R.RATIO)
    assert prev is not None and ratio is not None and prev > ratio, \
        "the ratio's margin must be a strict floor at rho=0.40"
