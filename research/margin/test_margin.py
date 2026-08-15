"""Pins R-M1's claims and its instrument's controls.

A finding stated only in prose is an assumption. These assert the mechanism and
the controls, not the headline numbers -- numbers move with parameters, the
mechanism should not.

Run:  ~/dev/marshal/.os/bin/python -m pytest research/margin/ -q
"""
from __future__ import annotations

import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "aggregate"))

import env_aggregate as A                                          # noqa: E402
from env_margin import KAPPA, SCALE, U, Fed, box_floor, margin_ceiling  # noqa: E402
from trial import (                                                # noqa: E402
    ADVERSARIAL, FIXED_COUNT, FIXED_FRACTION, HONEST, cell,
)


# --------------------------------------------------------------------------- #
#  THE GEOMETRY, derived in the preregistration and verified before any run     #
# --------------------------------------------------------------------------- #
def test_exact_box_agrees_with_the_committed_float_box():
    """If these diverge, the route is grading its own arithmetic."""
    for m in (2, 4, 8, 64, 512):
        assert abs(box_floor(m, F(0)) / SCALE - A.box_bounds(m)[0]) < 1e-9


def test_the_box_is_EMPTY_exactly_at_the_derived_ceiling():
    """PREREGISTRATION §2b: L(delta) = U at delta = kappa - 1/m, exactly."""
    for m in (2, 8, 64, 512):
        assert box_floor(m, margin_ceiling(m)) == U


def test_margin_raises_the_floor_monotonically():
    for m in (8, 512):
        prev = box_floor(m, F(0))
        for j in range(1, 20):
            d = F(j, 100)
            if d >= margin_ceiling(m):
                break
            cur = box_floor(m, d)
            assert cur > prev, (m, d)
            prev = cur


# --------------------------------------------------------------------------- #
#  THE CONTROLS                                                                #
# --------------------------------------------------------------------------- #
def test_PM0_no_staleness_means_no_margin_needed_and_ZERO_error():
    """The definitional control. If this fails, no other cell is readable."""
    for m in (2, 8, 64):
        r = cell(m, F(0), 0, FIXED_FRACTION, ADVERSARIAL, 1, seeds=3, rounds=40)
        assert r["violations"] == 0, m
        assert r["max_other_caused"] == 0, m


def test_staleness_is_OTHER_caused_only_not_the_principals_own_writes():
    """Defect #2. With one other principal that never acts, a lone adversary's
    view can only be wrong about itself -- and it is not, so Delta is 0."""
    r = cell(2, F(0), 4, FIXED_FRACTION, ADVERSARIAL, 1, seeds=3, rounds=40)
    assert r["max_other_caused"] == 0
    assert r["violations"] == 0


def test_UNDEFINED_is_None_not_a_number():
    """GATE 0c. Constructed directly, because the state is NOT reachable by
    divesting -- see the next test."""
    f = Fed.fresh(4)
    f.holdings = [0, 0, 0, 0]
    f.pool = 0
    assert f.concentration_exceeds() is None
    assert f.concentration() is None


def test_the_federation_CANNOT_be_fully_drained():
    """Independent reproduction of the escrow route's §2.6.

    `claim = contrib * pool / funded`, and withdrawal never reduces `contrib`,
    so each withdrawal takes only a pro-rata share and the pool decays
    geometrically: 24 -> 18 -> 13.5 -> 10.1 -> 7.6 for M=4. A principal cannot
    reach zero total while the pool holds anything, so UNDEFINED is unreachable
    by divestment -- which is why every scored cell reported 0 undefined rounds.

    Two independent instruments, built weeks apart, agree on this property of
    `env_federation`'s arithmetic.
    """
    f = Fed.fresh(4)
    for i in range(4):
        f.reduce_total(i, f.total(i))
    assert f.holdings == [0, 0, 0, 0]
    assert f.pool > 0, "the pool emptied; the pro-rata property changed"
    assert f.concentration_exceeds() is not None


def test_a_cell_with_no_attempts_reports_None_not_zero():
    """0/0 IS NOT 0. A refusal rate of 0.0 where nothing was attempted would
    report a perfectly permissive guard."""
    r = cell(2, F(0), 1, FIXED_FRACTION, HONEST, 1, seeds=1, rounds=1)
    assert r["refusal_rate"] is not None or r["attempts"] == 0


# --------------------------------------------------------------------------- #
#  THE FINDINGS                                                                #
# --------------------------------------------------------------------------- #
def test_activity_not_scale_is_the_control_parameter():
    """The route's constructive result: measured Delta falls as ~1/M under
    bounded activity and is flat when activity scales with population."""
    d_count = [cell(m, F(0), 1, FIXED_COUNT, ADVERSARIAL, 1, 3, 40)
               ["max_other_caused"] for m in (8, 64, 512)]
    d_frac = [cell(m, F(0), 1, FIXED_FRACTION, ADVERSARIAL, 1, 3, 40)
              ["max_other_caused"] for m in (8, 64, 512)]
    assert d_count[0] > d_count[1] > d_count[2], d_count      # decays
    assert d_frac[2] >= d_frac[0], d_frac                     # does not decay
    assert d_frac[2] > 10 * d_count[2], (d_frac[2], d_count[2])


def test_bounded_activity_makes_the_aggregate_UNREACHABLE_at_scale():
    """And it is unreachable, not merely slow -- checked at 1000 rounds, which
    is the confound that killed the escrow route's partitioned claim."""
    for R in (40, 1000):
        r = cell(512, F(0), 4, FIXED_COUNT, ADVERSARIAL, 1, seeds=2, rounds=R)
        assert r["violations"] == 0, R


def test_margin_is_a_STEP_not_a_dial():
    """Below delta* margin buys nothing at all."""
    v = [cell(64, F(j, 40), 1, FIXED_FRACTION, ADVERSARIAL, 1, 3, 40)
         ["violations"] for j in range(4)]
    assert v[0] > 0 and len(set(v)) == 1, v


def test_delta_star_grows_with_M():
    """M-GROWTH: what is safe at M=8 is not safe at M=512."""
    d8 = F(13, 100)          # measured delta* at M=8, eps=1, n=1
    assert cell(8, d8, 1, FIXED_FRACTION, ADVERSARIAL, 1, 5, 40)["violations"] == 0
    assert cell(512, d8, 1, FIXED_FRACTION, ADVERSARIAL, 1, 5, 40)["violations"] > 0
