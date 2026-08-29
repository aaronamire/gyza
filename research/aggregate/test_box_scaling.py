"""The static box at federation scale — soundness, cost, and the exit hole.

WHY THESE ARE TESTS AND NOT PROSE. Every claim in FINDINGS_BOX_SCALING.md is an
assertion about `env_aggregate.box_bounds`, which is committed code. A claim
about committed code that no test checks is an assumption, and this program has
recorded that species repeatedly. So each finding below is executable, and each
one that could pass vacuously carries a negative control.

NOTHING HERE MODIFIES THE COMMITTED ENVIRONMENT. `box_bounds` is imported.

Run:
  ~/dev/marshal/.os/bin/python -m pytest research/aggregate/test_box_scaling.py -q
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "federation"))

import env_aggregate as A                      # noqa: E402

K = A.KAPPA
SCALES = (2, 3, 4, 5, 8, 10, 25, 50, 100, 500, 1000)
EPS = 1e-9


def _worst_case(m: int) -> float:
    """One principal at U, every other at L — the extremal in-box state."""
    low, high = A.box_bounds(m)
    return high / (high + (m - 1) * low)


# --------------------------------------------------------------------------- #
#  1. SOUNDNESS — tested by CONSTRUCTION, not by evaluating its own formula    #
# --------------------------------------------------------------------------- #
def test_the_box_is_sound_at_every_scale_by_random_construction():
    """33,000 states built inside the box; none may exceed kappa.

    This does not ask `box_is_sound()` whether it is sound -- that would be the
    formula grading itself. It builds states and measures concentration.
    """
    rng = random.Random(1)
    tested = exceeded = 0
    for m in SCALES:
        low, high = A.box_bounds(m)
        for _ in range(3000):
            totals = [rng.uniform(low, high) for _ in range(m)]
            conc = max(totals) / sum(totals)
            tested += 1
            if conc > K + EPS:
                exceeded += 1
    assert tested == 33_000
    assert exceeded == 0, f"{exceeded}/{tested} in-box states exceeded kappa"


def test_negative_control_a_shrunk_floor_IS_detected_as_unsound():
    """Without this the test above proves only that the fixture is quiet."""
    for m, shrink in ((10, 0.5), (100, 0.1), (1000, 0.01)):
        low, high = A.box_bounds(m)
        bad = high / (high + (m - 1) * low * shrink)
        assert bad > K + EPS, (
            f"m={m}: shrinking the floor {shrink}x was NOT detected; "
            f"this check cannot see an unsound box")


def test_the_extremal_worst_case_is_DEFINITIONALLY_exactly_kappa():
    """Diagnosing the clean number rather than reporting it.

    `L` solves U(1-k) = k(m-1)L for EQUALITY, so the extremal in-box state sits
    exactly on the bound at every m. That is the construction, not evidence that
    the box is well-calibrated.
    """
    for m in SCALES:
        assert abs(_worst_case(m) - K) < 1e-12, m


# --------------------------------------------------------------------------- #
#  2. COST — the individual burden vanishes; the COLLECTIVE one does not       #
# --------------------------------------------------------------------------- #
def test_the_individual_floor_decays_as_one_over_m_minus_one():
    prev = None
    for m in SCALES:
        low, _high = A.box_bounds(m)
        if prev is not None:
            assert low < prev, f"floor did not fall from m-1 to m={m}"
        prev = low
    low_2, high_2 = A.box_bounds(2)
    low_1000, _ = A.box_bounds(1000)
    assert low_2 / high_2 > 0.6           # 66.7% of endowment at M=2
    assert low_1000 / high_2 < 0.001      # ~0.07% at M=1000


def test_the_AGGREGATE_floor_is_INVARIANT_in_m():
    """THE CORRECTION TO 'it gets cheaper at scale'.

    (m-1)L = U(1-k)/k is constant. The federation's total committed floor never
    shrinks -- it is redistributed over more participants. Cheapness per
    participant is real; cheapness is not.
    """
    _low, high = A.box_bounds(2)
    expected = high * (1.0 - K) / K
    for m in SCALES:
        low, _ = A.box_bounds(m)
        assert abs((m - 1) * low - expected) < 1e-9, (
            f"m={m}: aggregate floor {(m-1)*low} != invariant {expected}")


def test_the_attack_margin_grows_toward_the_full_endowment():
    """A principal breaches only by shedding below L, so the required shed is
    U-L. It grows monotonically and asymptotes at U: at M=2 you shed a third of
    your holdings, at M=100 essentially everything."""
    prev = None
    for m in SCALES:
        low, high = A.box_bounds(m)
        need = (high - low) / high
        if prev is not None:
            assert need > prev, f"margin did not grow at m={m}"
        prev = need
    low2, high2 = A.box_bounds(2)
    low100, high100 = A.box_bounds(100)
    assert (high2 - low2) / high2 < 0.34          # 33.3%
    assert (high100 - low100) / high100 > 0.99    # 99.3%


# --------------------------------------------------------------------------- #
#  3. MEMBERSHIP — underestimating m is safe; m FALLING is not                 #
# --------------------------------------------------------------------------- #
def test_underestimating_the_federation_size_is_conservative():
    """L is decreasing in m, so any underestimate over-constrains. A planetary
    federation therefore needs only a LOWER BOUND on its own size -- never a
    live count, never membership consensus."""
    for true_m, assumed_m in ((100, 10), (1000, 100), (10_000, 2)):
        low_assumed, _ = A.box_bounds(assumed_m)
        low_true, _ = A.box_bounds(true_m)
        assert low_assumed >= low_true, (true_m, assumed_m)
        # and the enforced floor still implies the bound at the TRUE size
        _l, high = A.box_bounds(true_m)
        assert high / (high + (true_m - 1) * low_assumed) <= K + EPS


def test_negative_control_m_FALLING_breaks_the_box():
    """THE EXIT HOLE, and it is the sharp edge of the whole result.

    A floor that was safe at m=1000 is catastrophically unsafe at m=100,
    because L is DECREASING in m. Underestimating is safe; the estimate going
    stale downward is not. Membership must be monotone, or exits must be
    detected promptly.
    """
    breaches = []
    for assumed, actual in ((1000, 100), (1000, 10), (100, 3)):
        low_stale, _ = A.box_bounds(assumed)
        _l, high = A.box_bounds(actual)
        conc = high / (high + (actual - 1) * low_stale)
        if conc > K + EPS:
            breaches.append((assumed, actual, round(conc, 4)))
    assert len(breaches) == 3, (
        f"m falling was NOT detected as unsafe in every case: {breaches}")
    assert all(c > 0.9 for _a, _b, c in breaches), (
        f"expected catastrophic breach, got {breaches}")


# --------------------------------------------------------------------------- #
#  4. THE BOUNDARY — this result does NOT extend to cumulative quantities      #
# --------------------------------------------------------------------------- #
def test_the_box_is_a_statement_about_an_INSTANTANEOUS_quantity_only():
    """C7 (BUILD_PLAN, from R13): no stateless local check bounds a cumulative
    quantity. `concentration` is a function of the CURRENT joint state; the box
    bounds it. `CrossDrainAccumulator` is path-dependent and no box exists for
    it. The distinction is what stops this result being over-read.
    """
    import inspect
    # concentration reads only the current state pair
    src = inspect.getsource(A.concentration)
    assert "principal_totals(s0, s, ps)" in src
    # the cumulative quantity accumulates over a trajectory
    assert hasattr(A.CrossDrainAccumulator, "observe"), \
        "the cumulative class must be path-dependent for this contrast to hold"
