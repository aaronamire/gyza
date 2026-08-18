"""Pins R-B's claims. Run: ~/dev/marshal/.os/bin/python -m pytest research/blast/ -q"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
for d in ("", "../hierarchy", "../margin"):
    sys.path.insert(0, str((HERE / d).resolve()))

from defect_tree import (                                       # noqa: E402
    HOARD, SHED, SUPERVISED, UNILATERAL, cell, critical_k,
)

#: R-H1's delta* per topology at eps=1 — each arm starts SAFE at its own margin,
#: which is what makes k* well-defined (see FINDINGS §4).
DELTA = {1: F(295, 1000), 2: F(0), 3: F(0)}
TOPO = {1: 512, 2: 23, 3: 8}


def test_every_arm_starts_SAFE_at_its_own_margin():
    """Without this, k*(d=1) is 0 and the ratio divides by zero — the defect
    this route walked into one route after recording it."""
    for d, f in TOPO.items():
        assert cell(d, f, DELTA[d], 1, 0, SHED, UNILATERAL)["violations"] == 0, d


def test_blast_radius_is_ONE_CLUSTER():
    """Damage does not cross a cluster boundary: a defector's own cluster is
    emptied while clusters without one retain what they retain at k=0."""
    r = cell(3, 8, F(0), 1, 1, SHED, UNILATERAL, seeds=3)
    base = cell(3, 8, F(0), 1, 0, SHED, UNILATERAL, seeds=3)["frac_clean"]
    # THE CLAIM IS A DIFFERENTIAL, SO ASSERT THE DIFFERENTIAL. An absolute
    # threshold of 1e-6 failed at 4.37e-05 -- the dirty cluster is NOT exactly
    # emptied, and the "0.0000" in the first table was four-decimal display
    # rounding of a nonzero value.
    assert r["frac_dirty"] < r["frac_clean"] / 100, (r["frac_dirty"],
                                                     r["frac_clean"])
    assert abs(r["frac_clean"] - base) < 0.002, (r["frac_clean"], base)


def test_defectors_PER_CLUSTER_is_the_invariant():
    ks = {d: critical_k(d, TOPO[d], DELTA[d], 1, SHED, UNILATERAL,
                        seeds=3)["k_star"] for d in (1, 2, 3)}
    assert ks[1] == 2 and ks[2] > 8 * ks[1] and ks[3] > 8 * ks[1], ks
    per = {d: ks[d] / (TOPO[d] ** (d - 1)) for d in (2, 3)}
    assert abs(per[2] - per[3]) < 0.5, per        # ~1.61 at both depths


def test_hoarding_STOPS_BREACHING_at_depth_3():
    """A2: the profitable attack was also the effective one. Under hierarchy it
    is profitable and INEFFECTIVE — it can only capture its own cluster's pool."""
    flat = cell(1, 512, DELTA[1], 1, 1, HOARD, UNILATERAL, seeds=3)
    deep = cell(3, 8, DELTA[3], 1, 1, HOARD, UNILATERAL, seeds=3)
    assert flat["violations"] > 0 and deep["violations"] == 0
    assert flat["payoff"] > 40 * deep["payoff"], (flat["payoff"], deep["payoff"])


def test_supervision_defeats_shedding_and_the_win_is_DEFINITIONAL():
    """It must hold — and the reason must stay documented, because the check
    tests exactly the quantity the defector violates."""
    for d, f in TOPO.items():
        assert critical_k(d, f, DELTA[d], 1, SHED, SUPERVISED,
                          seeds=2)["k_star"] is None, d
    txt = (HERE / "FINDINGS.md").read_text()
    assert "DEFINITIONAL" in txt and "GAMES the check" in txt
