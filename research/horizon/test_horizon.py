"""Pins R-N's claims. Run: ~/dev/marshal/.os/bin/python -m pytest research/horizon/ -q"""
from __future__ import annotations

import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
for d in ("", "../hierarchy", "../margin"):
    sys.path.insert(0, str((HERE / d).resolve()))

from run_horizon import feasible_delta                          # noqa: E402
from tree import ceiling_at, cell, kappa_level                  # noqa: E402


def test_flat_has_a_FINITE_horizon():
    """eps*(flat) = 8: feasible at 8, nothing anywhere below the ceiling at 16.
    Composability is unaffected by staleness, so this is the second condition."""
    ds8, _ = feasible_delta(1, 512, 8)
    assert ds8 is not None and ds8 > 0
    ds16, _ = feasible_delta(1, 512, 16)
    assert ds16 is None, f"expected no feasible margin at eps=16, got {ds16}"


def test_the_last_feasible_flat_cell_sits_ONE_GRID_STEP_from_the_ceiling():
    """P-N5. The approach is continuous, so the horizon is where required
    margin meets available margin."""
    ds, info = feasible_delta(1, 512, 8)
    assert abs(float(ds) - info["ceiling"]) <= 0.0051, (ds, info["ceiling"])


def test_the_tree_margin_SATURATES_instead_of_approaching_the_ceiling():
    """The result: hierarchy removes the horizon rather than moving it.
    Identical to four decimals across a 4x range of staleness."""
    vals = [feasible_delta(3, 8, e)[0] for e in (32, 64, 128)]
    assert all(v is not None for v in vals), vals
    assert vals[0] == vals[1] == vals[2], vals
    c = float(ceiling_at(8, kappa_level(3)))
    assert float(vals[0]) / c < 0.75, "saturated well below the ceiling"


def test_same_population_opposite_horizons():
    """P-N4: M = 512 in both arms. The horizon is a property of the PARTITION,
    not of the population."""
    assert feasible_delta(1, 512, 16)[0] is None       # flat: dead
    assert feasible_delta(3, 8, 16)[0] is not None     # tree: alive, M is 512 too


def test_UNREACHABLE_is_not_a_horizon():
    """The tree defeats the attack outright at eps<=2. That is better than any
    finite delta*, not a missing measurement -- the conflation R-B walked into."""
    ds, info = feasible_delta(3, 8, 1)
    assert info["reachable"] is False and ds == 0
    assert cell(3, 8, F(0), 1, 3, 40)["violations"] == 0
