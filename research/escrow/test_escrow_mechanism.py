"""Pins the two mechanism claims in FINDINGS.md, so they can be refuted.

A finding stated only in prose is an assumption (standing rule: AN UNENFORCED
INVARIANT IS AN ASSUMPTION). These assert the claims themselves, not the
numbers -- the numbers move with the parameters, the mechanism should not.

Run:  ~/dev/marshal/.os/bin/python -m pytest research/escrow/ -q
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for _d in ("aggregate", "arena"):
    sys.path.insert(0, str(HERE.parent / _d))

import env_aggregate as A                                       # noqa: E402
from coupled_arena import Coupled, KAPPA, run                   # noqa: E402


def _rate(m, disc, n, seeds=20, rounds=40):
    v = t = 0
    for s in range(seeds):
        r = run(m, disc, n_agents=n, rounds=rounds, seed=s)
        v += r["violations"]
        t += r["rounds"]
    return v / t


# --------------------------------------------------------------------------- #
#  THE CLAIM: reservation is exact iff at most ONE other actor moves the        #
#  protected quantity inside the window.                                        #
# --------------------------------------------------------------------------- #
def test_reservation_is_exact_at_M2_and_useless_from_M4():
    assert _rate(2, "reserved", 4) == 0.0
    # ... and it is a real guard at M=2, not a vacuous cell: naive fails there
    assert _rate(2, "naive", 4) > 0.9

    # from M=4 (>= 2 other actors) reservation is indistinguishable from naive
    for m in (4, 8, 64):
        res, naive = _rate(m, "reserved", 1), _rate(m, "naive", 1)
        assert abs(res - naive) < 0.05, (m, res, naive)
        assert res > 0.5, (m, res)


def test_partitioned_read_dominates_reservation_at_every_M_above_3():
    for m in (4, 8, 64, 512):
        assert _rate(m, "partitioned", 1) <= _rate(m, "reserved", 1)


# --------------------------------------------------------------------------- #
#  APPARATUS: the defects that produced the reassuring zeros must stay fixed    #
# --------------------------------------------------------------------------- #
def test_the_target_is_fixed_for_the_whole_trajectory():
    """Defect #5. A rotating beneficiary cannot accumulate concentration, and
    with one the whole naive arm reads 0.0000 at M >= 8."""
    assert _rate(64, "naive", 1) > 0.5


def test_a_shedder_can_divest_its_POOL_CLAIM_not_only_its_account():
    """Defect #6. Reducing `holdings` alone floors every shedder at its pool
    claim, which sits ABOVE L for M >= 4 and makes the box look sound.

    THE FLOOR IS NOT ZERO, and this assertion originally claimed it was.
    `pool_claim` reads `contrib`, which a withdrawal never reduces, so
    withdrawing X removes only X/m from the withdrawer's OWN claim. One full
    divestment at M=8 lands at 5.25, not 0. That is `env_federation`'s
    arithmetic transcribed faithfully, and it is precisely why draining is a
    concentration attack rather than a neutral move -- see FINDINGS §2.6.

    So the property to pin is that divesting reaches BELOW the account balance,
    i.e. the claim is reachable at all, plus the iterated consequence that the
    floor is breached over a trajectory.
    """
    c = Coupled.fresh(8)
    p = list(c.holdings)[0]
    from coupled_arena import reduce_total
    before_claim = c.pool_claim(p)
    reduce_total(c, p, c.principal_total(p))
    assert c.holdings[p] == 0.0, "the account was not fully divested"
    assert c.pool_claim(p) < before_claim, "the claim was untouchable"

    # and over a trajectory the floor IS breached -- the measured mechanism
    low, _ = A.box_bounds(8, KAPPA)
    r = run(8, "naive", n_agents=1, rounds=40, seed=0)
    assert r["below_floor"] > 0, (low, r)


def test_the_pool_claim_couples_principals():
    """Without this the arena is the uncoupled one and E1 is unmeasurable."""
    c = Coupled.fresh(8)
    a, b = list(c.holdings)[:2]
    before = c.principal_total(b)
    c.drain_pool(a, c.pool_claim(a))          # a acts; b does nothing
    assert c.principal_total(b) < before, "b's total did not move when a acted"
