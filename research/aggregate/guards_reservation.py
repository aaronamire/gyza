"""Per-principal reservation — AG-3's one named repair, tested.

READ-ONLY REUSE, NOT A COPY. This module IMPORTS `env_aggregate`,
`env_federation` and `guards_aggregate` rather than duplicating them. A copied environment
is a second frame that can drift from the one AG-3 measured; importing makes
drift impossible. The committed originals are untouched and their sha256s are
recorded in FINDINGS_RESERVATION.md.

THE SEMANTICS ARE FIXED IN PREREGISTRATION_RESERVATION.md 2 (commit 09996bf,
blob 270125b) AND ARE NOT REVISED HERE. If they turn out wrong, that is a
FINDING about the design, reported with every changed behaviour named.

WHAT THIS GUARD IS. Every other guard in AG-3 re-reads a snapshot for each
admission; under concurrency that snapshot is the same frozen pre-round state
for every agent, so N agents of one principal each independently pass the same
check and their effects compose past the bound. Reservation replaces the
re-read with a LOCAL BUDGET decremented on admission, making the guard stateful
for the duration of one round. It is a serialization point of width ONE
PRINCIPAL rather than width M.

WHAT IT CANNOT SEE (preregistration 2, A4, stated before any result): any other
principal's holdings at any time, any other principal's admissions, the
federation total, and therefore the concentration ratio itself.
"""
from __future__ import annotations

import env_aggregate as A          # aggregate QUANTITIES: concentration, box_bounds
import env_federation as E          # the ENVIRONMENT: State, Action, apply, totals
import guards_aggregate as G


class ReservationAgg(G.AggGuard):
    """Local budget, decremented on admission, reset once per round.

    The budget is denominated in the same units as `principal_total` and
    measures HOW MUCH THIS PRINCIPAL MAY STILL SHED this round before crossing
    the static box's lower bound L.

    SHEDDING, NOT ACQUIRING, AND THE REASON IS MEASURED. AG-3's counterexample
    raises A's concentration by shrinking the DENOMINATOR -- B and C shed while
    A does nothing. So the side the stale read leaks through, in the case this
    repair was proposed for, is the LOWER one. The upper side is left to the
    existing box check and is deliberately not reimplemented here.
    """

    name = "RESERVATION"
    reads_others_live = False

    def __init__(self, p, ps, kappa=A.KAPPA):
        super().__init__(p, ps, kappa)
        self._origin: float | None = None
        self._budget: float | None = None

    # -- the round boundary ------------------------------------------------
    def open_round(self, s: E.State) -> None:
        """Fix the origin and the budget for this round. Called ONCE.

        `_origin` is written here and NOWHERE ELSE. That is the whole of A3:
        a budget whose origin re-bases mid-round measures from a moving frame,
        which is the species this program has recorded five times. It is
        asserted by test, with a negative control that must detect a mutant
        which re-bases inside `admits`.
        """
        self._origin = E.principal_total(self.s0, s, self.p)
        low, _high = A.box_bounds(len(self.ps), self.kappa)
        # How much may still be shed before crossing the box floor. Never
        # negative: a principal already below L has no budget, not a debt.
        self._budget = max(0.0, self._origin - low)

    # -- admission ---------------------------------------------------------
    def admits(self, s: E.State, a: E.Action) -> bool:
        if a.principal != self.p:
            return True
        if self._budget is None:
            # An unopened round is NOT an unbounded one. Fail closed.
            return False
        if not E.physically_valid(s, a):
            return False

        before = E.principal_total(self.s0, s, self.p)
        after = E.principal_total(self.s0, E.apply(s, a), self.p)
        shed = max(0.0, before - after)

        if shed > self._budget + 1e-9:
            return False
        self._budget -= shed
        return True


def make_guards(config: str, ps: tuple[str, ...], kappa: float = A.KAPPA) -> dict:
    """Extends AG-3's config map with RESERVATION. Originals unmodified."""
    if config == "RESERVATION":
        return {p: ReservationAgg(p, ps, kappa) for p in ps}
    return G.make_guards(config, ps, kappa)


__all__ = ["ReservationAgg", "make_guards"]
