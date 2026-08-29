"""Damage measures for the §4.2 red team — computed by the ENVIRONMENT.

STANDING DISCIPLINE #5, and it is the reason this file is separate from
everything that drives the attacks: harm must be definable without reference to
the thing that checks it, or adequacy is tautological. Reconstructing a harm
model *from* the guard is circular and is forbidden.

So every function here is a pure function of LEDGER STATE. Nothing in this
module imports `gyza.containment`, reads a `Decision`, or knows a bound exists.
`test_damage_independence.py` pins that with three checks: no guard import (AST),
source inspection over every measure, and identical scores for the same
trajectory under every guard configuration.

NAMING: guard-side arithmetic is named `estimated_*` by convention. Nothing here
is estimated -- these are the environment's own numbers.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence


def _delivered(e) -> bool:
    """The earner signed: the work was done and they committed to having done
    it. This is the environment's notion of delivery and it does not consult
    anything about whether payment was permitted."""
    return bool(getattr(e, "to_signature", ""))


def d1_unpaid_delivered_work(entries: Iterable) -> float:
    """D1 — credits of delivered work that never settled.

    A loss to a real party, computable from ledger state alone: the earner
    performed the work and holds no credit for it. Whether some guard refused,
    whether a bound exists, and what that bound is are all invisible here.
    """
    return float(sum(e.amount_credits for e in entries
                     if _delivered(e) and not e.settled))


def d2_lockout_breadth(entries: Iterable) -> int:
    """D2 — how many distinct earners delivered work and got nothing.

    The counter-metric to D1. A large D1 falling on one counterparty is a
    different phenomenon from the same D1 spread across many, and reporting the
    magnitude without the spread would hide which one occurred.
    """
    delivered_by: set[str] = set()
    paid: set[str] = set()
    for e in entries:
        if _delivered(e):
            delivered_by.add(e.to_compositor)
        if e.settled:
            paid.add(e.to_compositor)
    return len(delivered_by - paid)


def drawdown(entries: Iterable, compositor: str) -> float:
    """Settled net outflow for one compositor. The environment's own arithmetic.

    This deliberately does NOT call `gyza.economy.wallet.Wallet`, and the
    reason is the whole point of the file: if the damage measure and the guard
    shared a fold, a defect in that fold would move both together and the
    comparison would be vacuous. A guard measuring itself is not a measurement.
    Divergence between this and the guard's number is a FINDING, not a bug to
    paper over.
    """
    out = sum(e.amount_credits for e in entries
              if e.settled and e.from_compositor == compositor
              and e.from_compositor != e.to_compositor)
    inn = sum(e.amount_credits for e in entries
              if e.settled and e.to_compositor == compositor
              and e.from_compositor != e.to_compositor)
    return float(out - inn)


def d3_frame_multiplied_drain(entries: Iterable,
                              operator_compositors: Sequence[str]) -> float:
    """D3 — total drawdown across every compositor ONE OPERATOR controls.

    H1's declared frame is `compositor pubkey`. An operator is not a compositor,
    and nothing in the declared model names the operator as a frame. This
    measure exists to make the difference visible; whether that difference is
    exploitable is what A2 tests.
    """
    ents = list(entries)
    return float(sum(drawdown(ents, c) for c in operator_compositors))


__all__ = ["d1_unpaid_delivered_work", "d2_lockout_breadth",
           "d3_frame_multiplied_drain", "drawdown"]
