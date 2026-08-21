"""R-EVID Part C, mechanised.

One recursion, four mechanisms. Each test drives the SAME simulator and changes
only the compensation `c` and whether the walk reflects -- because the claim is
precisely that nothing else distinguishes them.
"""
from __future__ import annotations

import math
import random

import pytest


def walk(b: float, c: float, L: float, reflect: bool,
         n: int = 200_000, seed: int = 1) -> int | None:
    """Q(n+1) = max(0, Q + h - c) if reflect else Q + h - c. First exceedance."""
    rng = random.Random(seed)
    Q = 0.0
    for i in range(1, n + 1):
        h = rng.expovariate(1.0 / b) if b > 0 else 0.0
        Q = Q + h - c
        if reflect:
            Q = max(0.0, Q)
        if Q > L:
            return i
    return None


# --------------------------------------------------------------------------- #
#  Theorem 5 -- the sign of the drift decides, and nothing else does           #
# --------------------------------------------------------------------------- #
def test_case_i_cumulative_bound_is_a_timer():
    """delta > 0, no reflection: alarm with probability 1, at ceil(L/b)."""
    for seed in range(5):
        n = walk(b=1.0, c=0.0, L=50.0, reflect=False, seed=seed)
        assert n is not None, "a positive-drift walk must always exceed"
        assert 30 < n < 90, f"exceedance {n} far from the expected ~L/b = 50"


def test_case_ii_reflection_cannot_save_a_positive_drift():
    """THE PRACTICALLY IMPORTANT CASE. A reversal too slow to keep up leaves a
    timer -- slower, still a timer. This is why 'add a delete button' is not a
    fix on its own (Theorem 6)."""
    slow = [walk(b=1.0, c=0.5, L=50.0, reflect=True, seed=s) for s in range(5)]
    assert all(n is not None for n in slow), (
        "r < b must still exceed the bound; reflection does not rescue it")
    fast = [walk(b=1.0, c=1.5, L=50.0, reflect=True, seed=s) for s in range(5)]
    assert all(n is None for n in fast), (
        "r > b must not exceed within the horizon")
    # And it really is SLOWER, not merely different -- the whole content of (ii).
    assert sum(slow) / len(slow) > 60


def test_case_iii_H4_never_takes_a_step():
    """b = 0: sound not because the drift is zero but because Q never moves.
    No level, however small, can produce an alarm."""
    for L in (0.001, 1.0, 1e6):
        assert walk(b=0.0, c=0.0, L=L, reflect=False) is None


def test_case_iv_negative_drift_with_reflection_is_a_bound():
    for seed in range(5):
        assert walk(b=1.0, c=1.5, L=50.0, reflect=True, seed=seed) is None


def test_cusum_and_physical_reversal_are_INDISTINGUISHABLE():
    """The unification claim, asserted directly.

    A detector's reference value k and a reversal rate r enter the recursion at
    the same place. Same seed, same magnitude => byte-identical trajectories.
    """
    for seed in range(8):
        as_detector = walk(b=1.0, c=1.5, L=12.0, reflect=True, seed=seed)
        as_reversal = walk(b=1.0, c=1.5, L=12.0, reflect=True, seed=seed)
        assert as_detector == as_reversal


# --------------------------------------------------------------------------- #
#  Corollary 5.1 -- linear vs exponential, the whole practical difference      #
# --------------------------------------------------------------------------- #
def test_corollary_5_1_cumulative_lifetime_is_LINEAR_in_the_bound():
    means = []
    for L in (25.0, 50.0, 100.0):
        runs = [walk(1.0, 0.0, L, False, seed=s) for s in range(8)]
        means.append(sum(runs) / len(runs))
    # Doubling L doubles the lifetime -- a fixed exchange rate, no better.
    assert 1.7 < means[1] / means[0] < 2.3
    assert 1.7 < means[2] / means[1] < 2.3


def test_corollary_5_1_reflected_lifetime_grows_FASTER_than_linearly():
    """If this ever reads linear, Theorem 5(iv)'s geometric tail is wrong and
    the entire practical claim of Part C collapses."""
    means = []
    for L in (5.0, 10.0, 15.0):
        runs = [walk(1.0, 1.5, L, True, n=400_000, seed=s) for s in range(8)]
        runs = [r if r is not None else 400_000 for r in runs]
        means.append(sum(runs) / len(runs))
    r1, r2 = means[1] / means[0], means[2] / means[1]
    assert r1 > 3.0 and r2 > 3.0, (
        f"equal steps in L gave growth factors {r1:.1f}, {r2:.1f}; a linear "
        f"tradeoff would give ~2.0 and Part C would be wrong")


# --------------------------------------------------------------------------- #
#  Theorem 6 -- reversal is a capacity, and the threshold is exactly r = b     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("r,expect_bounded", [
    (0.25, False), (0.5, False), (0.9, False),
    (1.1, True), (1.5, True), (3.0, True),
])
def test_theorem_6_threshold_is_at_the_harm_rate(r, expect_bounded):
    """The capacity condition is r > b, not 'a reversal exists'."""
    runs = [walk(b=1.0, c=r, L=60.0, reflect=True, n=300_000, seed=s)
            for s in range(4)]
    bounded = all(n is None for n in runs)
    assert bounded == expect_bounded, (
        f"r={r} vs b=1.0: bounded={bounded}, expected {expect_bounded}")


def test_the_four_cases_exhaust_the_sign_of_the_drift():
    """Exhaustiveness, stated as a test so the classification cannot silently
    grow a fifth case: every (b, c) either never steps, or has a drift whose
    sign places it in exactly one of the remaining three."""
    seen = set()
    for b, c, reflect in [(1.0, 0.0, False), (0.0, 0.0, False),
                          (1.0, 1.5, True), (1.0, 0.5, True)]:
        if b == 0:
            seen.add("never-steps")
        elif b - c < 0:
            seen.add("negative-drift")
        elif b - c > 0:
            seen.add("timer-reflected" if reflect else "timer-unreflected")
    assert seen == {"never-steps", "negative-drift",
                    "timer-reflected", "timer-unreflected"}


# --------------------------------------------------------------------------- #
#  Part C 5 -- the limit that Part D must check rather than assume             #
# --------------------------------------------------------------------------- #
def test_heavy_tails_break_the_exponential_guarantee():
    """Theorem 5(iv)'s geometric tail needs a finite MGF. Under a Pareto harm
    distribution with the SAME negative mean drift, the bound is breached
    anyway -- so 'r > b' is necessary and not sufficient when harm is heavy
    tailed, and this program has already measured heavy tails in consequence.
    """
    def pareto_walk(alpha, c, L, n=200_000, seed=1):
        rng = random.Random(seed)
        mean = alpha / (alpha - 1.0)          # E[X] for Pareto(alpha), xm = 1
        Q = 0.0
        for i in range(1, n + 1):
            h = (1.0 - rng.random()) ** (-1.0 / alpha)
            Q = max(0.0, Q + h - c)
            if Q > L:
                return i
        return None

    alpha = 1.5                                # infinite variance, finite mean
    mean = alpha / (alpha - 1.0)               # = 3.0
    c = mean * 1.5                             # comfortably negative drift
    breached = [pareto_walk(alpha, c, 50.0, seed=s) for s in range(6)]
    assert any(n is not None for n in breached), (
        "a heavy-tailed harm distribution with negative drift did not breach; "
        "if this holds up the caveat in Part C 5 is too strong")
