"""R-EVID Part A, mechanised.

The theorems in THEOREMS.md are elementary, which is precisely why they should
be checked rather than admired: this program's own ledger records that a
statement can be true in every clause and still be the wrong call. Each test
below computes the claim by brute force over a grid and compares it against the
closed form, in the direction this project treats as ground truth -- BFS/exhaust
is the oracle, the closed form is the optimisation.
"""
from __future__ import annotations

import math

import pytest


# --------------------------------------------------------------------------- #
#  Theorem 1 -- a separating level exists iff rho > N/K                        #
# --------------------------------------------------------------------------- #
def separating_level_exists_by_search(b: float, a: float, N: int, K: int,
                                      grid: int = 4000) -> bool:
    """Ground truth: search L directly, never using the closed form."""
    lo, hi = 0.0, max(N * b, K * a) * 1.5
    for i in range(grid + 1):
        L = lo + (hi - lo) * i / grid
        live = (N * b) <= L          # benign survives N actions
        contained = (K * a) > L      # adversary refused by action K
        if live and contained:
            return True
    return False


@pytest.mark.parametrize("N,K", [(1000, 100), (100, 100), (10, 100), (26_000, 100)])
@pytest.mark.parametrize("rho", [1.0, 1.5, 2.0, 9.9, 10.0, 10.1, 260.0, 1000.0])
def test_theorem_1_separation_condition(N, K, rho):
    b = 1.0
    a = b * rho
    predicted = rho > N / K
    actual = separating_level_exists_by_search(b, a, N, K)
    assert actual == predicted, (
        f"Theorem 1 disagrees with exhaustive search at N={N} K={K} rho={rho}: "
        f"closed form says {predicted}, search says {actual}")


def test_corollary_1_1_equal_rates_never_separate():
    """rho = 1: the measurand carries no information about the adversary.

    This is R-H3L's Q-COUNT measured at exactly 1.000 events per action for
    both behaviours. No level exists for any horizon longer than the
    containment window.
    """
    for N in (101, 1000, 10_000, 1_000_000):
        assert not separating_level_exists_by_search(1.0, 1.0, N, 100), (
            f"found a separating level at rho=1, N={N} -- impossible")
    # N <= K is the degenerate case where 'liveness' asks for less than
    # 'containment' forbids, and it is not a useful regime.
    assert separating_level_exists_by_search(1.0, 1.0, 99, 100)


def test_corollary_1_2_lifetime_is_linear_in_the_strength_ratio():
    """Max benign lifetime N < K*rho. Doubling loudness doubles lifetime, and
    that is the ONLY exchange rate available."""
    K = 100
    for rho in (2.0, 4.0, 8.0, 16.0):
        max_N = max(N for N in range(1, 20_000)
                    if separating_level_exists_by_search(1.0, rho, N, K))
        assert abs(max_N - K * rho) <= 2, (
            f"rho={rho}: max lifetime {max_N}, expected ~{K * rho}")


# --------------------------------------------------------------------------- #
#  Theorem 2 -- the cumulative bound is a timer: false-alarm probability 1     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("b,L", [(1.0, 100.0), (0.5, 100.0), (1077.0, 1.08e6),
                                 (1e-6, 1.0)])
def test_theorem_2_every_benign_agent_is_eventually_refused(b, L):
    n = 0
    Q = 0.0
    while Q <= L:
        n += 1
        Q += b
        assert n < 10**9, "did not terminate -- b must be > 0"
    assert n == math.ceil(L / b) or n == math.ceil(L / b) + 1, (
        f"benign refusal at action {n}, expected ceil(L/b)={math.ceil(L / b)}")


# --------------------------------------------------------------------------- #
#  Theorem 4 -- evidence per observation, and D = 0 when the measurand is mute #
# --------------------------------------------------------------------------- #
def kl_bernoulli(q: float, f: float) -> float:
    """Expected log-likelihood ratio per observation, in nats."""
    return q * math.log(q / f) + (1 - q) * math.log((1 - q) / (1 - f))


def test_theorem_4_zero_evidence_when_detector_is_uninformative():
    """q = f  <=>  LR = 1  <=>  D = 0  <=>  infinite observations.

    This is the bridge: the competence bound's LR and a sequential test's
    detection delay are the same quantity seen once versus accumulated.
    """
    for p in (0.1, 0.3, 0.5, 0.7, 0.9):
        assert kl_bernoulli(p, p) == pytest.approx(0.0, abs=1e-12)


def test_theorem_4_competence_bound_numbers_give_the_stated_evidence():
    """The competence bound's measured LRs, converted to evidence per
    observation. 19.8 in-competence, 1.25 outside (COMPETENCE_BOUND.md 4)."""
    assert math.log(19.8) == pytest.approx(2.99, abs=0.01)
    assert math.log(1.25) == pytest.approx(0.22, abs=0.01)
    # The ratio is the claim that matters: an out-of-competence checker needs
    # this many times more observations for equal confidence.
    assert math.log(19.8) / math.log(1.25) == pytest.approx(13.4, abs=0.3)


def test_evidence_is_monotone_in_the_likelihood_ratio():
    """Holding the false-alarm rate fixed, more evidence is strictly better --
    so 'choose the measurand by its evidence' is a well-ordered rule."""
    f = 0.05
    prev = -1.0
    for q in (0.06, 0.1, 0.2, 0.4, 0.8, 0.95):
        d = kl_bernoulli(q, f)
        assert d > prev, f"evidence not monotone at q={q}"
        prev = d


# --------------------------------------------------------------------------- #
#  Theorem 3 -- linear vs exponential, checked by simulation                   #
# --------------------------------------------------------------------------- #
def cusum_run_length(rng, mean: float, k: float, H: float, cap: int) -> int:
    """Actions until CUSUM alarms, given per-action harm ~ Exp(mean)."""
    S = 0.0
    for n in range(1, cap + 1):
        S = max(0.0, S + rng.expovariate(1.0 / mean) - k)
        if S > H:
            return n
    return cap


def test_theorem_3_cusum_benign_lifetime_grows_faster_than_linearly():
    """The cumulative level's benign lifetime is L/b -- exactly linear.

    CUSUM's must grow FASTER than linearly in its threshold, or Theorem 3's
    claim of domination is wrong and the design rule built on it collapses.
    """
    import random
    b, a = 1.0, 4.0
    k = 2.0                       # reference between the two rates
    lifetimes = []
    for H in (2.0, 4.0, 6.0):
        rng = random.Random(1)
        runs = [cusum_run_length(rng, b, k, H, cap=200_000) for _ in range(40)]
        lifetimes.append(sum(runs) / len(runs))

    # Linear growth would give equal RATIOS between equal threshold steps.
    # Super-linear means each step multiplies by more than the last did.
    r1 = lifetimes[1] / lifetimes[0]
    r2 = lifetimes[2] / lifetimes[1]
    assert r1 > 1.5 and r2 > 1.5, (
        f"benign lifetime {lifetimes} barely grows with the threshold; "
        f"CUSUM would not dominate a fixed level")

    # And detection delay must stay small while that happens -- otherwise the
    # lifetime was bought at the same exchange rate as the naive bound.
    rng = random.Random(2)
    delays = [cusum_run_length(rng, a, k, 6.0, cap=200_000) for _ in range(40)]
    mean_delay = sum(delays) / len(delays)
    assert mean_delay < 20, f"detection delay {mean_delay} too slow to matter"
    assert lifetimes[2] / mean_delay > 50, (
        f"lifetime/delay ratio {lifetimes[2] / mean_delay:.1f} -- the whole "
        f"claim is that this ratio is unavailable to a cumulative level, "
        f"where it is pinned at rho = {a / b}")
