"""Pins A2's claims and the instrument's controls.

Run:  ~/dev/marshal/.os/bin/python -m pytest research/defector/ -q
"""
from __future__ import annotations

import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "margin"))

from defect import BOTH, HOARD, SHED, SKEW, cell, critical_k, hoard  # noqa: E402
from env_margin import Fed, KAPPA                                    # noqa: E402

#: R-M1's measured delta* at FIXED_FRACTION, n=1, eps=1.
D = {8: F(13, 100), 64: F(28, 100), 512: F(295, 1000)}


def test_the_control_holds_zero_defectors_zero_violations():
    """P-A2e, definitional: this is delta* restated. If it fails, nothing
    else in this route is readable."""
    for m, d in D.items():
        assert cell(m, d, 1, 0, SHED, seeds=5)["violations"] == 0, m


def test_ONE_defector_suffices_at_every_scale():
    """The verdict. k* <= 2 at M = 8, 64 and 512."""
    for m, d in D.items():
        assert critical_k(m, d, 1, SHED, seeds=5)["k_star"] <= 2, m


def test_version_skew_is_FAR_more_tolerable_than_malice():
    """The practical exception: a node with the floor but no margin is not
    malicious, and tolerance for it GROWS with scale."""
    k_shed = critical_k(512, D[512], 1, SHED, seeds=5)["k_star"]
    k_skew = critical_k(512, D[512], 1, SKEW, seeds=5)["k_star"]
    assert k_skew > 10 * k_shed, (k_shed, k_skew)
    assert critical_k(8, D[8], 1, SKEW, seeds=5)["k_star"] < k_skew


def test_hoarding_breaches_ALONE_refuting_the_derived_ceiling():
    """P-A2c said hoarding could not breach at any M, from a ceiling computed
    against a denominator held at U*M. The compliant population sheds, shrinking
    that denominator, and the prediction fails."""
    for m, d in D.items():
        assert cell(m, d, 1, 0, HOARD, seeds=3)["violations"] > 0, m


def test_hoarding_PAYS_and_the_payoff_grows_with_scale():
    """The refuted headline. The rational attack is also the effective one."""
    advs = [cell(m, D[m], 1, 0, HOARD, seeds=3)["defector_advantage"]
            for m in (8, 64, 512)]
    assert all(a is not None and a > 0 for a in advs), advs
    assert advs[0] < advs[1] < advs[2], advs


def test_shedding_gains_the_defector_EXACTLY_nothing():
    """Diagnosed as DEFINITIONAL, not reported as a finding: a shedder and a
    compliant principal both bottom out at the same irreducible pool claim."""
    for m, d in D.items():
        k = critical_k(m, d, 1, SHED, seeds=5)["k_star"]
        assert cell(m, d, 1, k, SHED, seeds=5)["defector_advantage"] == 0.0


def test_the_mechanism_is_the_COMMONS_not_the_defectors_own_term():
    """One defector drains the shared pool far below the compliant control.
    If impact ran through the defector's own holding, the pool would be
    unaffected."""
    m, d = 8, D[8]
    compliant = cell(m, d, 1, 0, SHED, seeds=5)["pool_remaining"]
    defected = cell(m, d, 1, 1, SHED, seeds=5)["pool_remaining"]
    assert defected < compliant / 10, (compliant, defected)


def test_hoard_is_sum_conserving():
    """The property §1b's ceiling rests on — the ceiling was wrong for a
    different reason, and this part of it is sound."""
    f = Fed.fresh(8)
    before = sum(f.totals())
    hoard(f, 0, f.pool // 2)
    assert sum(f.totals()) == before
