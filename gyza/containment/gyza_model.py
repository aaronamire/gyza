"""
Gyza's own harm model, wired into C-1.

Quantities are taken from research/HARM_MODEL_DRAFT.md and computed with the
PRODUCTION folds, not reimplementations -- that is what makes the guard
frame-aligned rather than merely correct-looking (R12 Part C).

BOUNDS ARE NOT SET HERE. Every level in the draft is `TBD -- user decision`,
and inventing one would make the containment claim unfalsifiable. Call
`load_bounds({...})` with declared levels; until then `can_claim_containment`
is False and the engine refuses actions touching unbounded classes.

H3 is deliberately NOT registered as a bounded class: the draft records that no
function anywhere in gyza/ computes an irreversibility measure. Registering it
with an invented quantity would be exactly the circularity the discipline
forbids. It is listed in UNMODELLED so the gap is visible rather than absent.
"""
from __future__ import annotations

from pathlib import Path

from gyza.containment.harm import HarmClass, HarmModelRegistry
from gyza.containment.invariants import (
    Invariant, InvariantClass, InvariantRegistry,
)

# Harm classes named in the draft that have NO computable quantity in the
# codebase. Reported, never silently omitted.
UNMODELLED: dict[str, str] = {
    "H3_irreversible_change": (
        "no function in gyza/ computes an irreversibility measure "
        "(HARM_MODEL_DRAFT §H3). Sub-classes: signed envelopes emitted, "
        "external network sends (which leave modelled state entirely -- C15), "
        "deleted local state."
    ),
}


def _credits_at_risk(s0: object, s: object) -> float:
    """H1 -- settled net balance minus active holds, over the CURRENT frame.

    Uses the production fold (gyza.economy.wallet.Wallet, a pure projection
    over append-only LedgerEntry) rather than a private reimplementation, so
    the guard and the harm measure cannot disagree about what a balance is.
    The frame is the compositor pubkey and it FLOATS -- read from `s`, never
    pinned at `s0` (R9 condition 2).
    """
    from gyza.economy.wallet import Wallet
    before = Wallet(getattr(s0, "entries", [])).net_balance(s0.owner)
    after = Wallet(getattr(s, "entries", [])).net_balance(s.owner)
    holds = float(getattr(s, "active_holds", 0.0))
    return float(before.credits) - float(after.credits) + holds


def _market_capital_at_risk(s0: object, s: object) -> float:
    """H2 -- market capital. The draft's anti-pattern: a MUTABLE dict mutated
    in place at four sites with no gate reading it. Declared here so the
    exposure is measurable at all; the real fix is representational (route P&L
    through LedgerEntry so it lands inside the fold the gate already reads),
    not a second gate."""
    return float(getattr(s0, "capital", 0.0)) - float(getattr(s, "capital", 0.0))


def _authority_exceedance(s0: object, s: object) -> float:
    """H4 -- authority. A MEASURE, not the draft's boolean (C5): the count of
    executed actions whose enforcement exceeded the delegation root's manifest.
    Zero is the intended operating point; a count gives the dial a boolean
    lacks."""
    return float(len(getattr(s, "authority_violations", ()) or ()))


DEFAULT_BOUNDS_FILE = Path(__file__).with_name("guard_bounds.json")


def build_registries(
    bounds_file: str | Path | None = DEFAULT_BOUNDS_FILE,
) -> tuple[HarmModelRegistry, InvariantRegistry]:
    harm = HarmModelRegistry()
    harm.register(HarmClass(
        id="H1_credits",
        description="credits at risk: settled net balance minus active holds",
        quantity=_credits_at_risk,
        frame="compositor pubkey",
        frame_mutable=True,   # key rotation is deferred (settlement.py:71-72)
        code_path="gyza/economy/wallet.py:274 net_balance; fold at :169-171",
    ))
    harm.register(HarmClass(
        id="H2_market_capital",
        description="market capital exposure",
        quantity=_market_capital_at_risk,
        frame="agent pubkey in BondedMarket._capital",
        frame_mutable=False,
        code_path="gyza/economy/market.py:231 _capital (mutated :287/:325/:332/:345)",
    ))
    harm.register(HarmClass(
        id="H4_authority",
        description="count of actions exceeding the delegation root's manifest",
        quantity=_authority_exceedance,
        frame="delegation chain root manifest",
        frame_mutable=False,
        code_path="gyza/economy/delegation.py:213-289 verify_delegation",
    ))

    inv = InvariantRegistry()
    inv.register(Invariant(
        id="INV-H1-drain",
        harm_class="H1_credits",
        cls=InvariantClass.CUMULATIVE,
        description=(
            "credits at risk stay within the declared bound. CUMULATIVE: a "
            "monotone budget over one pool, so it does not compose across "
            "concurrent agents (R10 H-CONS) or principals (R13) and is valid "
            "ONLY at the serialized promotion gate."),
    ))
    inv.register(Invariant(
        id="INV-H2-capital",
        harm_class="H2_market_capital",
        cls=InvariantClass.CUMULATIVE,
        description="market capital exposure within bound; same class as H1.",
    ))
    inv.register(Invariant(
        id="INV-H4-attenuation",
        harm_class="H4_authority",
        cls=InvariantClass.MONOTONE_NON_CUMULATIVE,
        description=(
            "authority is monotone non-increasing down a delegation chain "
            "(the attenuation theorem). Once exceeded it cannot be un-exceeded, "
            "and the property is per-action and stateless, so it composes "
            "concurrently in the interior (C6)."),
    ))
    # D1 — bounds are LOADED, never invented here. Passing bounds_file=None
    # yields an unbounded registry that refuses everything, which is the
    # correct behaviour before a model is declared.
    if bounds_file is not None and Path(bounds_file).exists():
        harm.load_bounds_file(bounds_file)
    return harm, inv
