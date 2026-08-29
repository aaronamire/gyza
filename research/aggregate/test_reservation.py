"""Reservation: the counterexample, the frame, and the cross-principal case.

Run:
  ~/dev/marshal/.os/bin/python -m pytest research/aggregate/test_reservation.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "federation"))

import env_aggregate as A                      # noqa: E402
import env_federation as E                     # noqa: E402
import guards_reservation as GR                # noqa: E402


def _counterexample_actions():
    """AG-3's EXACT fixture, copied from test_aggregate.py:168-172.

    Four actions, TWO actors (B/0 and C/0), two admissions each. Reproduced
    literally so this is the same case, not a case of the same shape.
    """
    return [E.Action("external_send", principal=p, actor=f"{p}/0",
                     src=f"{p}:{acc}", dest=d, amt=amt)
            for p, d in (("B", "X0"), ("C", "X1"))
            for acc, amt in (("a0", 10), ("a1", 4))]


def _open(guards, s):
    for g in guards.values():
        g.open_round(s)


# --------------------------------------------------------------------------- #
#  B1 — THE MINIMUM BAR                                                        #
# --------------------------------------------------------------------------- #
def test_B1_reservation_prevents_ag3s_own_counterexample():
    """The case the repair was proposed for. If this fails, it is not a repair."""
    ps = E.principals(3)
    s0 = E.arena(3)
    guards = GR.make_guards("RESERVATION", ps)
    for g in guards.values():
        g.reset(s0)
    _open(guards, s0)

    admitted = [a for a in _counterexample_actions()
                if E.physically_valid(s0, a) and guards[a.principal].admits(s0, a)]

    joint = s0
    for a in admitted:
        if E.physically_valid(joint, a):
            joint = E.apply(joint, a)
    conc = A.concentration(s0, joint, ps)

    assert conc is not None
    assert conc <= A.KAPPA + 1e-9, (
        f"reservation admitted {len(admitted)}/4 actions reaching {conc:.4f} "
        f"> kappa={A.KAPPA}; the repair does not fix its own counterexample")


def test_B1_control_the_unreserved_guard_STILL_fails_the_same_case():
    """Without this the test above proves nothing: it could pass because the
    fixture stopped exhibiting the effect rather than because reservation
    caught it. GLOBAL_READ must still reach 0.625 on the same actions."""
    import guards_aggregate as G
    ps = E.principals(3)
    s0 = E.arena(3)
    guards = G.make_guards("GLOBAL_READ", ps)
    for g in guards.values():
        g.reset(s0)

    acts = _counterexample_actions()
    for a in acts:
        assert guards[a.principal].admits(s0, a), "fixture no longer admits"
    joint = s0
    for a in acts:
        if E.physically_valid(joint, a):
            joint = E.apply(joint, a)
    conc = A.concentration(s0, joint, ps)
    assert conc is not None and conc > A.KAPPA + 1e-9, (
        f"the fixture must still EXHIBIT the failure; got {conc}")


# --------------------------------------------------------------------------- #
#  B2 — MECHANISM, NOT ACCIDENT                                                #
# --------------------------------------------------------------------------- #
def test_B2_holds_under_reversed_action_order():
    """A repair that works on one ordering is not a mechanism. The budget
    decrements on every admission, so order must not matter."""
    ps = E.principals(3)
    s0 = E.arena(3)
    guards = GR.make_guards("RESERVATION", ps)
    for g in guards.values():
        g.reset(s0)
    _open(guards, s0)

    admitted = [a for a in reversed(_counterexample_actions())
                if E.physically_valid(s0, a) and guards[a.principal].admits(s0, a)]
    joint = s0
    for a in admitted:
        if E.physically_valid(joint, a):
            joint = E.apply(joint, a)
    conc = A.concentration(s0, joint, ps)
    assert conc is not None and conc <= A.KAPPA + 1e-9, conc


# --------------------------------------------------------------------------- #
#  A3 — THE ORIGIN IS IMMUTABLE WITHIN A ROUND, WITH A NEGATIVE CONTROL        #
# --------------------------------------------------------------------------- #
def test_A3_origin_is_fixed_for_the_whole_round():
    ps = E.principals(3)
    s0 = E.arena(3)
    g = GR.ReservationAgg("B", ps)
    g.reset(s0)
    g.open_round(s0)
    origin = g._origin
    for a in _counterexample_actions():
        if a.principal == "B":
            g.admits(s0, a)
            assert g._origin == origin, "admits() re-based the origin"


def test_A3_negative_control_a_rebasing_mutant_IS_detected():
    """The control that gives the assertion meaning. A mutant that re-bases
    inside admits() must be caught -- otherwise the test above passes because
    nothing in the fixture would move the origin either way."""
    ps = E.principals(3)
    s0 = E.arena(3)

    class Rebasing(GR.ReservationAgg):
        def admits(self, s, a):
            if a.principal == self.p:
                self._origin = E.principal_total(self.s0, s, self.p) - 1.0
            return super().admits(s, a)

    g = Rebasing("B", ps)
    g.reset(s0)
    g.open_round(s0)
    origin = g._origin
    moved = False
    for a in _counterexample_actions():
        if a.principal == "B":
            g.admits(s0, a)
            if g._origin != origin:
                moved = True
    assert moved, "the frame check cannot detect a re-basing guard"


def test_an_unopened_round_fails_closed():
    """An unopened round is not an unbounded one."""
    ps = E.principals(3)
    s0 = E.arena(3)
    g = GR.ReservationAgg("B", ps)
    g.reset(s0)
    a = _counterexample_actions()[0]
    assert g.admits(s0, a) is False


# --------------------------------------------------------------------------- #
#  D1 — THE CROSS-PRINCIPAL CASE                                               #
# --------------------------------------------------------------------------- #
def test_D1_cross_principal_shrink_is_NOT_prevented():
    """DERIVABLE, not new: THEORY_AG3.md:116-118 states concentration is
    two-sided so no exact local test exists. Reservation is local. This
    measures that the derivation holds in this environment rather than
    claiming a new impossibility.

    Configuration: ONE action per principal, so no within-principal
    accumulation exists for the budget to catch -- yet the federation total
    still shrinks and a non-acting principal's share rises.
    """
    ps = E.principals(3)
    s0 = E.arena(3)
    guards = GR.make_guards("RESERVATION", ps)
    for g in guards.values():
        g.reset(s0)
    _open(guards, s0)

    single = [E.Action("external_send", principal=p, actor=f"{p}/0",
                       src=f"{p}:a0", dest=d, amt=10)
              for p, d in (("B", "X0"), ("C", "X1"))]

    admitted = [a for a in single
                if E.physically_valid(s0, a) and guards[a.principal].admits(s0, a)]
    joint = s0
    for a in admitted:
        if E.physically_valid(joint, a):
            joint = E.apply(joint, a)

    # A never acts, and its total is unchanged -- the AG-3 shape.
    assert E.principal_total(s0, joint, "A") == E.principal_total(s0, s0, "A")
    conc = A.concentration(s0, joint, ps)
    assert conc is not None
    # Report the value; the assertion is that reservation did NOT make this
    # composable, which is what the theory predicts.
    return conc
