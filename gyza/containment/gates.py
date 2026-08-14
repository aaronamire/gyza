"""Guard gates on real production paths.

WHERE A CUMULATIVE BOUND MAY LIVE, and it is not a matter of taste. C7 is
unambiguous: no stateless local check bounds a cumulative quantity, so a
cumulative bound requires a SERIALIZATION POINT. Evaluating one anywhere
concurrent looks like a check and bounds nothing, which is worse than no check.

The census that led here measured every checking component in `gyza/` for
production callers and found the whole containment layer at zero. Wiring the
promotion gate into `AgentRunner` was the obvious next move and would have been
WRONG: `runner.py` touches neither the ledger nor the market, so a guard there
would measure quantities the gated path cannot move. That is AG-3's finding
exactly -- a guard watching the wrong end of a ratio, expensive and inert.

H1 moves in exactly one place in production: the PAYER path of
`LedgerSettlementService`, where `sign_as_payer` settles an entry and credits
leave. That path is already inside `self._lock`. The serialization point C7
requires is therefore not something to invent -- it already exists, and this
module is what plugs into it.

TWO DIRECTIONAL FACTS, both easy to get backwards:

  * The EARNER path (`_handle_payer_cosigned`) settles credits IN. A drawdown
    bound there would watch the wrong direction and could never fire.
  * The gate must measure the state AS IT WOULD BE AFTER the payment, not as it
    is now. Measuring the current state admits the payment that crosses the
    bound and only notices on the next one -- the difference between bounding a
    quantity and lagging it by one entry.
"""
from __future__ import annotations

import dataclasses

from gyza.containment.engine import Decision, GuardEngine, Phase
from gyza.containment.projection import (
    WindowOrigin, project_at_origin, project_now,
)

#: The action type this gate evaluates, from the C-3 vocabulary. It is
#: IRREVERSIBLE, which is why the phase below is PROMOTION and never INTERIOR.
SETTLE = "settle_credits"


def ledger_genesis_origin() -> WindowOrigin:
    """Measure drawdown over the ledger's whole history.

    WHY THIS AND NOT "SINCE PROCESS START". A cumulative bound whose origin can
    move is not a bound (ledger artifact #13: a gate measuring from a moving
    checkpoint bought unlimited drain). An origin at process start is exactly
    that defect wearing a different hat -- restart the process and the budget
    refills. Genesis cannot move.

    THE COST IS REAL AND IS NOT MINE TO DECIDE. `guard_bounds.json` declares H1
    as "max net drawdown per run", and this measures per LEDGER. Those differ,
    the per-run reading is the gameable one, and reconciling them is a user
    decision about what the bound means -- so the origin is a required argument
    everywhere below and this is only a named, honest default.
    """
    return WindowOrigin(ledger_ns=0, capital_seq=0)


class SettlementGuard:
    """Evaluates the declared H1 bound at the settlement serialization point.

    Everything is REQUIRED. There is no constructor default that yields a guard
    measuring nothing -- the defect this whole line of work removed was two
    `getattr` defaults that turned an absent measurement into a passing one.
    """

    def __init__(self, engine: GuardEngine, owner: str, origin: WindowOrigin):
        if not owner:
            raise ValueError(
                "a settlement guard needs an owner: H1 is measured over a "
                "frame, and an unnamed frame is not a measurement")
        self._engine = engine
        self._owner = owner
        self._origin = origin

    @property
    def owner(self) -> str:
        return self._owner

    def check_payment(self, entries, pending) -> Decision:
        """Would settling `pending` push this compositor past its H1 bound?

        `entries` is the ledger's append-only history; `pending` is the entry
        about to be cosigned. It is projected as SETTLED because that is what
        `sign_as_payer` is about to make it, and `Wallet` keys the balance on
        `settled` alone.

        ONLY H1 IS EVALUATED. Adequacy is per harm class (C4), and
        `settle_credits` cannot move market capital or authority exceedance --
        evaluating those here would report on quantities this action cannot
        change, which is how a guard comes to look busy and bound nothing.
        """
        history = list(entries)
        after = history + [dataclasses.replace(pending, settled=True)]

        s0 = project_at_origin(
            owner=self._owner, ledger_entries=history,
            capital_entries=[], origin=self._origin)
        # `active_holds=0.0` is a MEASURED FACT, not a stub: H1 is drawdown
        # plus live reservation holds, and `ReservationBook` has no production
        # constructor, so nothing in the running system creates a hold. If
        # subcontracting ships, this argument must carry the real figure or the
        # gate silently under-measures its own quantity.
        s_next = project_now(
            owner=self._owner, ledger_entries=after,
            active_holds=0.0, capital_entries=[])

        return self._engine.evaluate(
            s0, s_next, SETTLE, Phase.PROMOTION, harm_classes=["H1_credits"])


__all__ = ["SettlementGuard", "ledger_genesis_origin", "SETTLE"]
