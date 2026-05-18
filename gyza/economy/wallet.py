"""
Wallet — a pure read-projection over settled ledger entries.

The foundational economic read-model. An agent's identity (its
Ed25519 pubkey) is its account; its *wallet* is not a new ledger or
new state — it is a deterministic fold over the bilateral settled
entries that ``gyza/economy/ledger.py`` already stores. Everything
downstream (the subcontract loop, Proof of Useful Cognition) reads
from this projection; nothing writes new economic state here.

WHY A PROJECTION, NOT A BALANCE TABLE
-------------------------------------
Settlement is *bilateral*: a settled ``LedgerEntry`` records "payer
P paid earner E ``amount`` for envelope H, both signed". There is
no global balance anywhere — only pairwise signed facts. The wallet
*derives* a global net position by summing those facts. Because
addition is commutative and associative, the fold is
order-independent: two honest nodes holding the same set of settled
entries (keyed by ``entry_id``) compute a **bit-identical** net.
That determinism is the invariant the rest of the economy stands
on.

PROJECTION IS NOT FUNGIBILITY (the throttle nuance)
---------------------------------------------------
A global net here does NOT mean credits earned from B are spendable
with C. Spending still requires a bilateral channel; cross-graph
fungibility is multilateral clearing (a later, deliberately-gated
milestone — it is the technical boundary where bilateral L0 stops
sufficing and also the legal line where the unit would become a
transferable token). The wallet is a *read view*. It must never be
mistaken for, or quietly grown into, transferability.

THE "FAKE TOKEN"
----------------
``Credits`` is, deliberately and explicitly, a **non-monetary,
non-transferable, non-redeemable internal accounting unit with no
external value** — a fake/test token. It exists to make the
economy's *mechanics* real and testable while staying provably
below the legal cliff. Turning it into a real, transferable,
redeemable token is the §11/L1-gated step and is not done here.
The non-monetary posture is encoded in the type so it is provable
from the code, not just asserted in prose.

EXACTNESS
---------
``LedgerEntry.amount_credits`` is a Python ``float`` but the ledger
*signs* the canonical string ``f"{amount:.6f}"`` — i.e. the
cryptographically committed unit is the micro-credit (1e-6). The
wallet folds in **integer micro-credits derived from that exact
canonical string via ``Decimal``**, never by float summation, so
the wallet's arithmetic equals the signed arithmetic and
``0.1 + 0.2`` is exactly ``0.3``. Float-summing a ledger is a
classic silent-corruption bug; we do not.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from gyza.economy.ledger import LedgerEntry

# The internal accounting unit. NOT a currency. NOT tradeable. NOT
# redeemable. No external value. See module docstring + README.
TOKEN_TICKER = "GYZ"
TOKEN_IS_FAKE = True
_MICROS_PER_CREDIT = 1_000_000  # the ledger signs f"{x:.6f}" → 1e-6 unit


def _amount_to_micros(amount: float) -> int | None:
    """
    Exact micro-credit value of a ledger amount, derived from the
    SAME canonical string the ledger signs (``f"{x:.6f}"``) via
    ``Decimal`` — so the wallet's unit is byte-for-byte the
    cryptographically committed unit, with zero float error.

    Returns ``None`` for a malformed amount (non-finite or negative)
    — the ledger rejects ``< 0`` at creation, but a forged or
    peer-relayed entry could carry one, and the projection must be
    robust to adversarial input rather than let it corrupt the fold.
    """
    if not math.isfinite(amount) or amount < 0.0:
        return None
    # f"{x:.6f}" is round-half-to-even at 6 places; Decimal of that
    # string is exact; ×1e6 is therefore an exact integer.
    micros = (Decimal(f"{amount:.6f}") * _MICROS_PER_CREDIT)
    try:
        return int(micros.to_integral_exact())
    except Exception:  # noqa: BLE001 — defensive; 6dp ×1e6 is always integral
        return None


@dataclass(frozen=True, order=True)
class Credits:
    """
    An exact, integer-micro-credit amount of the FAKE internal unit.

    Frozen + typed so unit confusion is unrepresentable (you cannot
    add ``Credits`` to a token count or a duration) and so the
    "non-monetary" posture travels with the value. Negative is a
    legitimate, meaningful state — it is net debt to the network
    (you consumed more verified compute than you produced), and the
    wallet must never clamp it away.
    """

    micros: int

    @classmethod
    def zero(cls) -> "Credits":
        return cls(0)

    @classmethod
    def from_amount(cls, amount: float) -> "Credits | None":
        m = _amount_to_micros(amount)
        return None if m is None else cls(m)

    @property
    def value(self) -> float:
        """Display-only. Never fold with this — fold with ``micros``."""
        return self.micros / _MICROS_PER_CREDIT

    def __add__(self, other: "Credits") -> "Credits":
        return Credits(self.micros + other.micros)

    def __sub__(self, other: "Credits") -> "Credits":
        return Credits(self.micros - other.micros)

    def __neg__(self) -> "Credits":
        return Credits(-self.micros)

    def __str__(self) -> str:
        return (
            f"{self.value:.6f} {TOKEN_TICKER} "
            f"(FAKE — internal, non-redeemable, no external value)"
        )


@dataclass(frozen=True)
class WalletStatement:
    """
    The full, transparent breakdown for one pubkey. ``net`` is the
    spendable (settled) balance; pending is shown but is NOT
    spendable (a counterparty has not cosigned, so it is not yet a
    fact). Exclusion counters make adversarial / divergent input
    visible rather than silently swallowed.
    """

    pubkey: str
    settled_in: Credits      # Σ settled where this key is earner
    settled_out: Credits     # Σ settled where this key is payer
    net: Credits             # settled_in − settled_out (spendable; may be < 0)
    pending_in: Credits      # earner side, not yet settled (receivable)
    pending_out: Credits     # payer side, not yet settled (committed)
    settled_entry_count: int
    excluded_self_dealing: int
    excluded_malformed: int
    excluded_conflicting: int


def _canonical(e: LedgerEntry) -> tuple:
    """Identity of an entry's economically-load-bearing content.
    Two entries with the same ``entry_id`` but a different canonical
    tuple are a genuine divergence (the ledger's "disputed" case)."""
    return (e.from_compositor, e.to_compositor,
            f"{e.amount_credits:.6f}", bool(e.settled))


class Wallet:
    """
    Pure projection over an iterable of ``LedgerEntry``.

    Construct once; query many. Deduplicates by ``entry_id`` so
    reconciliation replays (which re-deliver the *same* entry with
    its existing cosignatures) cannot double-count — a double-count
    would be a silent mint, which would be catastrophic for an
    accounting system whose entire point is verifiability.

    Collision policy on a repeated ``entry_id``:
      * identical canonical content       → keep one (idempotent);
      * settled vs unsettled              → settled wins (the
        final fact supersedes the in-flight one);
      * two *settled* but differing       → genuine dispute: the
        entry is dropped from ALL balances and counted in
        ``excluded_conflicting``. We never pick an arbitrary amount
        for a contested settled fact.
    """

    def __init__(self, entries: Iterable[LedgerEntry]) -> None:
        chosen: dict[str, LedgerEntry] = {}
        conflicting: set[str] = set()

        for e in entries:
            eid = e.entry_id
            if eid in conflicting:
                continue
            prev = chosen.get(eid)
            if prev is None:
                chosen[eid] = e
                continue
            if _canonical(prev) == _canonical(e):
                continue  # exact dup — idempotent
            # Differ. Resolve by settled-supersedes-unsettled.
            if prev.settled and not e.settled:
                continue
            if e.settled and not prev.settled:
                chosen[eid] = e
                continue
            # Both settled (or both unsettled) and differ → dispute.
            conflicting.add(eid)
            chosen.pop(eid, None)

        self._entries: list[LedgerEntry] = list(chosen.values())
        self._conflicting_count = len(conflicting)

    @classmethod
    def from_ledger(cls, ledger) -> "Wallet":  # noqa: ANN001
        """Convenience: project over ``ComputeLedger.all_entries()``."""
        return cls(ledger.all_entries())

    def statement(self, pubkey: str) -> WalletStatement:
        settled_in = Credits.zero()
        settled_out = Credits.zero()
        pending_in = Credits.zero()
        pending_out = Credits.zero()
        n_settled = 0
        self_deal = 0
        malformed = 0

        for e in self._entries:
            if e.from_compositor == e.to_compositor:
                # Self-dealing is rejected at creation, but a forged
                # or relayed entry could carry it. Counting it is a
                # mint vector if only one leg is summed elsewhere;
                # we exclude it from every leg and surface the count.
                self_deal += 1
                continue
            c = Credits.from_amount(e.amount_credits)
            if c is None:
                malformed += 1
                continue

            is_earner = e.to_compositor == pubkey
            is_payer = e.from_compositor == pubkey
            if not (is_earner or is_payer):
                continue

            if e.settled:
                if is_earner:
                    settled_in += c
                if is_payer:
                    settled_out += c
                # count each distinct settled entry once for this key
                n_settled += 1
            else:
                if is_earner:
                    pending_in += c
                if is_payer:
                    pending_out += c

        return WalletStatement(
            pubkey=pubkey,
            settled_in=settled_in,
            settled_out=settled_out,
            net=settled_in - settled_out,
            pending_in=pending_in,
            pending_out=pending_out,
            settled_entry_count=n_settled,
            excluded_self_dealing=self_deal,
            excluded_malformed=malformed,
            excluded_conflicting=self._conflicting_count,
        )

    def net_balance(self, pubkey: str) -> Credits:
        """
        Spendable balance: settled-in minus settled-out for ``pubkey``.
        Settled-only on purpose — counting ``earner_signed`` (not yet
        cosigned) would let an agent "spend" credits a counterparty
        never agreed to. May be negative (net debt); never clamped.
        """
        return self.statement(pubkey).net


__all__ = [
    "TOKEN_TICKER",
    "TOKEN_IS_FAKE",
    "Credits",
    "Wallet",
    "WalletStatement",
]
