"""Pins R-C's claims. Run: ~/dev/marshal/.os/bin/python -m pytest research/churn/ -q"""
from __future__ import annotations

import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
for d in ("", "../hierarchy", "../margin"):
    sys.path.insert(0, str((HERE / d).resolve()))

from churn_tree import (                                        # noqa: E402
    ADVERSARIAL, BENIGN, CLAIM_STAYS, CLAIM_TRAVELS, ChurnTree, cell,
    critical_k,
)


def test_r0_reproduces_the_environment_it_attacks():
    """P-C0. If the churn instrument does not reproduce R-B at r=0, no cell in
    this route is readable."""
    assert critical_k(3, 8, F(0), 1, F(0), CLAIM_TRAVELS, ADVERSARIAL,
                      seeds=3) == 103
    assert cell(3, 8, F(0), 1, 1, F(0), CLAIM_TRAVELS, ADVERSARIAL,
                seeds=3)["pools_touched"] == 1


def test_REACH_breaks_completely():
    """Compartmentalisation of reach does not survive churn."""
    lo = cell(3, 8, F(0), 1, 1, F(0), CLAIM_TRAVELS, ADVERSARIAL, seeds=3)
    hi = cell(3, 8, F(0), 1, 1, F(1), CLAIM_TRAVELS, ADVERSARIAL, seeds=3)
    assert lo["pools_touched"] == 1
    assert hi["pools_touched"] > 20, hi["pools_touched"]


def test_DAMAGE_does_not_break_the_horizon_survives():
    """The result: saturation persists under maximal churn. Compare against
    R-N's no-churn 0.4934 at the same epsilons."""
    a = cell(3, 8, F(495, 1000), 32, 1, F(1), CLAIM_TRAVELS, ADVERSARIAL,
             seeds=2)
    b = cell(3, 8, F(495, 1000), 128, 1, F(1), CLAIM_TRAVELS, ADVERSARIAL,
             seeds=2)
    assert a["safe"] and b["safe"], (a["violations"], b["violations"])


def test_migration_moves_entitlement_it_does_not_create_it():
    """The mechanism behind §2: total funded across pools is conserved under
    CLAIM_TRAVELS, so reaching more pools cannot multiply a claim."""
    t = ChurnTree(3, 8)
    before = sum(t.funded)
    t.migrate(1, 5, CLAIM_TRAVELS)
    t.migrate(1, 9, CLAIM_TRAVELS)
    assert sum(t.funded) == before
    # ...and under CLAIM_STAYS entitlement is DESTROYED, which is why benign
    # churn collapses under it
    u = ChurnTree(3, 8)
    b2 = sum(u.funded)
    u.migrate(1, 5, CLAIM_STAYS)
    assert sum(u.funded) < b2 and u.contrib[1] == 0


def test_the_policy_choice_is_threat_dependent():
    """Neither policy dominates: STAYS is catastrophic under benign churn."""
    stays = critical_k(3, 8, F(0), 1, F(1, 10), CLAIM_STAYS, BENIGN, seeds=3)
    travels = critical_k(3, 8, F(0), 1, F(1, 10), CLAIM_TRAVELS, BENIGN,
                         seeds=3)
    assert stays == 1 and travels > 20, (stays, travels)
