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

  >> THAT RATIONALE INVERTED ON 2026-08-18 AND IS KEPT ONLY AS THE RECORD OF
  >> WHY THE DECISION WAS RIGHT WHEN IT WAS MADE.
  >>
  >> It reasons about H1 (ledger) and H2 (market). BOTH ARE NOW RETIRED. The
  >> registered classes are H3/H4/H5/H6, and `runner.py` moves THREE of them:
  >> it records `AuthorityViolation` (H4), writes through the artifact store
  >> (H5), and signs envelopes (H6). The premise "the gated path cannot move
  >> these quantities" is now false.
  >>
  >> A correct design decision became wrong because the harm model changed
  >> underneath it and nothing re-checked the rationale. That is frame drift
  >> applied to a DESIGN ARGUMENT rather than to a measurement -- the same
  >> species as R9's pinned frame and SR-5's floating origin, in a new place.
  >>
  >> What did NOT follow is "therefore wire the promotion gate here". The
  >> runner already covers those three classes by other means (H4 enforced at
  >> its own bounds gate, H5 at `ArtifactStore.max_bytes`, H6 at the review
  >> cadence), and `containment/staging.py` is a DIFFERENT EXECUTION MODEL
  >> rather than an unwired copy of this one. See that module's header.

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


def genesis_origin() -> WindowOrigin:
    """The immutable origin for the H3/H5/H6 window: the beginning of time.

    Same argument as `ledger_genesis_origin` -- an origin at process start
    refills the budget on restart, which is artifact #13 wearing a hat. At
    genesis the store holds 0 bytes and the logs hold 0 rows, so the `s0`
    values this implies are exact rather than assumed.
    """
    return WindowOrigin(ledger_ns=0, capital_seq=0, envelope_ns=0)


def observe_now(*, owner: str, blackboard: object | None = None,
                artifact_store: object | None = None,
                authority_violations=(), ledger_entries=(),
                active_holds: float = 0.0):
    """Fold the REAL sources into the state the harm model reads.

    THIS FUNCTION IS THE MISSING LINK, and its absence is why the containment
    layer measured nothing. `GyzaState` carries `stored_bytes`,
    `signed_envelope_count` and `mesh_exit_sends`; `projection.py` deliberately
    does not know what a blackboard is ("the caller folds, this projects"), and
    **no caller folded**. All three parameters defaulted to 0 at every call
    site in the repository, so H3, H5 and H6 computed `0 - 0 = 0` in every
    evaluation while H5 and H6 carried declared, signed bounds.

    That is H2_market_capital's retirement condition -- "reported as a bounded
    class while measuring exactly 0.0 in every production evaluation" -- alive
    in two more classes, and it is the reason `can_claim_containment` must not
    be flipped by declaring an H3 level. See research/H3_WIRING_GAP.md.

    The three accessors all already existed:
      H5  `ArtifactStore.total_size_bytes()`
      H6  `Blackboard.count_envelopes_since()`
      H3  `mesh_exit_sends_since()`  (the MESH_EXIT-filtered one, so a grant is
          never folded into a send count)

    `None` sources fold to 0, which is the pre-existing behaviour and is honest
    for a node that has no store or no blackboard -- but a caller that passes
    None for a source that EXISTS reintroduces the silent zero, which is what
    `tests/test_containment_observes_real_state.py` exists to prevent.
    """
    from gyza.containment.gyza_model import mesh_exit_sends_since

    origin = genesis_origin()
    stored = int(artifact_store.total_size_bytes()) if artifact_store else 0
    envelopes = (int(blackboard.count_envelopes_since(origin.envelope_ns))
                 if blackboard else 0)
    exits = mesh_exit_sends_since(blackboard, origin.envelope_ns) \
        if blackboard else 0

    return project_now(
        owner=owner, ledger_entries=list(ledger_entries),
        active_holds=active_holds, capital_entries=[],
        authority_violations=tuple(authority_violations),
        stored_bytes=stored, signed_envelope_count=envelopes,
        mesh_exit_sends=exits,
    )


def observe_at_origin(*, owner: str, ledger_entries=()):
    """The `s0` matching `observe_now`. Exact, not assumed -- see
    `genesis_origin`: at genesis every cumulative quantity is 0."""
    return project_at_origin(
        owner=owner, ledger_entries=list(ledger_entries),
        capital_entries=[], origin=genesis_origin(),
        stored_bytes_at_origin=0, mesh_exit_sends_at_origin=0,
    )


class SettlementGuard:
    """Evaluates the declared H1 bound at the settlement serialization point.

    Everything is REQUIRED. There is no constructor default that yields a guard
    measuring nothing -- the defect this whole line of work removed was two
    `getattr` defaults that turned an absent measurement into a passing one.
    """

    def __init__(self, engine: GuardEngine, owner: str, origin: WindowOrigin,
                 harm_class: str = "H1_credits"):
        # REFUSE TO WATCH A CLASS THAT DOES NOT EXIST. H1 was retired
        # 2026-08-15 (credits are TOKEN_IS_FAKE, so no level in them is
        # checkable), and a guard constructed against a retired class would
        # either raise deep inside a settlement or -- worse -- be made to
        # tolerate the absence and admit everything. Failing at construction is
        # the only version that cannot become a silent pass.
        if harm_class not in engine._harm:
            raise KeyError(
                f"cannot guard {harm_class!r}: it is not a registered harm "
                f"class. If it was retired, this guard should not be installed; "
                f"if it is new, register it before guarding it.")
        self._harm_class = harm_class
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
            s0, s_next, SETTLE, Phase.PROMOTION,
            harm_classes=[self._harm_class])


__all__ = ["SettlementGuard", "ledger_genesis_origin", "SETTLE"]
