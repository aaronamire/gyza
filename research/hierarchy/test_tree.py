"""Pins R-H1's claims and its instrument's controls.

Run:  ~/dev/marshal/.os/bin/python -m pytest research/hierarchy/ -q
"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "margin"))

from tree import (                                              # noqa: E402
    KAPPA, Tree, box_floor_at, ceiling_at, cell, kappa_level,
    level_endowment, max_fan_in,
)

TOPO = ((1, 512), (2, 23), (3, 8))


# --- the arithmetic that must hold before any measurement means anything ----
def test_per_level_kappa_never_exceeds_the_global_bound():
    """Defect #1. A per-level kappa above the true d-th root makes the composed
    bound exceed the global one BY CONSTRUCTION."""
    for d in range(1, 9):
        assert kappa_level(d) ** d <= KAPPA, d


def test_the_floor_SCALES_with_level_endowment():
    """Defect #2. A level-k node's children hold f**(k-1) * U each."""
    f, kl = 8, kappa_level(3)
    l1 = box_floor_at(f, kl, F(0), level_endowment(f, 0))
    l2 = box_floor_at(f, kl, F(0), level_endowment(f, 1))
    # ceiling-rounded independently, so they agree only up to the rounding slack
    assert abs(l2 - f * l1) <= f, (l1, l2)


def test_the_commons_is_PER_CLUSTER_and_a_drain_stays_inside_it():
    """The mechanism behind the whole result: hierarchy makes the pool smaller,
    so other-caused error is bounded by one cluster rather than the federation."""
    t = Tree(2, 23)
    assert t.n_clusters == 23
    other = t.leaf_total(23 * 22)              # a leaf in a DIFFERENT cluster
    t.divest(0, t.leaf_total(0))               # drain cluster 0 completely
    assert t.pool[0] < t.pool[1], "the drain did not stay in its own cluster"
    assert t.leaf_total(23 * 22) == other, "damage crossed a cluster boundary"


# --- the positive control: R-H1 at d=1 must reproduce R-M1 ------------------
def test_d1_reproduces_R_M1_exactly():
    """Two instruments, built independently, on the same measured quantity.
    Disagreement here is a finding, not a nuisance."""
    rm1 = json.loads((HERE.parent / "margin" / "margin_result.json").read_text())
    want = {c["eps"]: c["delta_star"] for c in rm1["cells"]
            if c["activity"] == "FIXED_FRACTION" and c["n"] == 1
            and c["M"] == 512}
    assert want[1] == 0.295 and want[2] == 0.48 and want[4] is None, want


# --- the findings -----------------------------------------------------------
def test_depth_DEFEATS_the_attack_that_flat_cannot_survive():
    """H-HELPS. The attack is IDENTICAL in both rows."""
    assert cell(1, 512, F(0), 1, seeds=3)["violations"] > 0, "flat must break"
    for d, f in ((2, 23), (3, 8)):
        assert cell(d, f, F(0), 1, seeds=3)["violations"] == 0, (d, f)
        assert cell(d, f, F(0), 2, seeds=3)["violations"] == 0, (d, f)


def test_depth_3_at_eps_4_beats_flat_at_eps_1():
    """The sharpest statement of the result."""
    assert cell(3, 8, F(265, 1000), 4, seeds=3)["violations"] == 0
    assert cell(1, 512, F(265, 1000), 1, seeds=3)["violations"] > 0


def test_fan_in_is_the_fanout_not_the_population():
    assert max_fan_in(1, 512) == 511
    assert max_fan_in(3, 8) == 7


def test_UNREACHABLE_and_INFEASIBLE_are_OPPOSITE_outcomes():
    """The scoring defect: both surfaced as `None` and the rule collapsed them.
    UNREACHABLE at delta=0 is safest-possible; INFEASIBLE is unsafe at any
    price."""
    unreachable = cell(3, 8, F(0), 1, seeds=3)
    assert unreachable["violations"] == 0          # safe with NO margin
    # ... and the OTHER pole must be a real one. A coarse-grid miss is not
    # infeasibility: R-M1 published four INFEASIBLE verdicts that were simply
    # never tested near the ceiling, and all four are safe at 0.590-0.595.
    kl = kappa_level(1)
    mid = ceiling_at(512, kl) * F(90, 100)
    assert cell(1, 512, mid, 4, seeds=3)["violations"] > 0, \
        "the flat attack must still bite at 90% of the ceiling"
