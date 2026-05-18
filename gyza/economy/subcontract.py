"""
Subcontract accounting core — the pure decision substrate under the
dual-role subcontract loop.

Built and exhaustively tested BEFORE any runner/daemon wiring — the
same discipline that built the bounds predicate before the brick-3
gate, the wallet before any consumer, and the delegation floor
before this. The stateful loop is unsound to build until "may I
commit this bounty, and how do holds/settlement/abandonment net
out exactly?" is correct and proven. Now it is.

TWO ORTHOGONAL CONCERNS (deliberately not conflated)
----------------------------------------------------
* Solvency / holds — against the agent's WALLET (actual settled
  credits): available = settled_net − Σ(active holds). Stops a set
  of concurrent subcontracts from double-spending the same credits.
* Budget — against the TASK's spend envelope: Σ(sub-budgets) ≤
  parent budget ⇒ the whole subtree's credits ≤ the root ⇒
  recursion is economically finite (the §9 runaway backstop,
  complementing MAX_DELEGATION_DEPTH). A child Budget is a strict
  sub-allocation of its parent's.

Both must pass independently. A rich agent on a small-budget job
must not overspend the job; a broke agent on a big-budget job
cannot commit.

THE NO-DOUBLE-COUNT IDENTITY (the correctness core)
---------------------------------------------------
A reservation is a HOLD, not a debit. In flight: the wallet shows
no debit yet (no settled entry) but the hold reduces `available`.
On settlement: a real settled entry lands in the wallet (−B) AND
the hold is released — simultaneously — so the net change to
`available` at the settlement instant is ZERO (B was already
subtracted as a hold; now it is subtracted as a real entry
instead — reclassified, never counted twice). Reserve→settle:
`available` unchanged at settle. Reserve→release (no pay):
`available` rises by B. This identity is exact at every step.

CRASH-SAFETY (do not persist or trust this as payment state)
------------------------------------------------------------
This book is TRANSIENT, per-process. The durable source of truth
is the wallet (settled, dual-signed entries). Reservations are
only ever conservative holds; PAYMENT IS NEVER AUTHORIZED BY THIS
BOOK — it is gated by the durable verify-and-cosign path. A hold
lost to a crash can only make solvency re-evaluate freshly against
settled reality; it can never cause a double-spend. A future
contributor MUST NOT persist this or treat a reservation as proof
of payment.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from gyza.economy.wallet import Credits


class _WalletView(Protocol):
    """Just the slice of Wallet this module needs (injected, not
    owned) so the core stays pure and trivially testable."""

    def net_balance(self, pubkey: str) -> Credits: ...


# ---------------------------------------------------------------------------
# Budget — the task spend envelope + the strictly-shrinking tree.
# ---------------------------------------------------------------------------
class Budget:
    """
    A finite envelope of (fake) credits a task is authorised to
    spend. ``child`` carves a strict sub-allocation; the sum of all
    allocations can never exceed ``total``, so the entire delegation
    subtree's credits are bounded by the root budget — recursion is
    finite by economics, not only by the depth cap.
    """

    def __init__(self, total: Credits) -> None:
        if total.micros < 0:
            raise ValueError("budget total must be ≥ 0")
        self._total = total
        self._allocated = Credits.zero()

    @property
    def total(self) -> Credits:
        return self._total

    @property
    def allocated(self) -> Credits:
        return self._allocated

    def remaining(self) -> Credits:
        return self._total - self._allocated

    def try_allocate(self, amount: Credits) -> tuple[bool, str]:
        if amount.micros <= 0:
            return False, "allocation must be > 0"
        if amount > self.remaining():
            return False, (
                f"allocation {amount.value:.6f} exceeds remaining "
                f"{self.remaining().value:.6f}"
            )
        self._allocated = self._allocated + amount
        return True, ""

    def refund(self, amount: Credits) -> None:
        """
        Return a prior allocation to the envelope. Used ONLY when a
        subcontract is RELEASED (abandoned, no payment): the task did
        not actually spend those credits, so a flaky subcontractor
        must not permanently burn the job's budget. A SETTLED (paid)
        subcontract is never refunded — that budget was genuinely
        spent. Always called with a real prior allocation, so it
        cannot legitimately drive ``allocated`` below zero; clamped
        defensively (a negative would signal a caller bug).
        """
        if amount.micros <= 0:
            return
        self._allocated = self._allocated - amount
        if self._allocated.micros < 0:
            self._allocated = Credits.zero()

    def child(self, amount: Credits) -> "Budget":
        """Allocate ``amount`` from this budget and return it as a
        fresh child Budget. Raises iff the allocation does not fit —
        callers that want to branch should ``try_allocate`` first."""
        ok, why = self.try_allocate(amount)
        if not ok:
            raise ValueError(f"cannot create child budget: {why}")
        return Budget(amount)


# ---------------------------------------------------------------------------
# Reservation — per-subcontract hold with a terminal state machine.
# ---------------------------------------------------------------------------
class ResvState(Enum):
    ACTIVE = "active"
    SETTLED = "settled"     # paid: a real settled ledger entry now exists
    RELEASED = "released"   # abandoned: no payment, credits returned


@dataclass(frozen=True)
class Reservation:
    child_work_item_id: str
    amount: Credits
    state: ResvState


@dataclass(frozen=True)
class ReserveOutcome:
    ok: bool
    reservation: Reservation | None
    reason: str


class ReservationBook:
    """
    Transient, single-agent solvency + idempotency ledger for
    in-flight subcontracts. Enforces BOTH the wallet-solvency and
    the task-budget constraints on every reserve. Never authorises
    payment (see module docstring) — it makes concurrent commit
    decisions conservative and exact.
    """

    def __init__(
        self,
        wallet: _WalletView,
        owner_pubkey: str,
        budget: Budget,
    ) -> None:
        self._wallet = wallet
        self._owner = owner_pubkey
        self._budget = budget
        self._resv: dict[str, Reservation] = {}

    # --- queries -------------------------------------------------------
    def _active_holds(self) -> Credits:
        h = Credits.zero()
        for r in self._resv.values():
            if r.state is ResvState.ACTIVE:
                h = h + r.amount
        return h

    def available(self) -> Credits:
        """
        Spendable headroom for a NEW commitment — the tighter of the
        two constraints:
          * wallet:  settled_net(owner) − Σ(active holds)
          * budget:  remaining task budget
        May be negative (the agent is in net debt and/or the budget
        is exhausted) — never clamped; callers must treat ≤ 0 as
        "cannot commit".
        """
        wallet_room = self._wallet.net_balance(self._owner) - self._active_holds()
        budget_room = self._budget.remaining()
        return wallet_room if wallet_room < budget_room else budget_room

    def can_reserve(self, amount: Credits) -> tuple[bool, str]:
        if amount.micros <= 0:
            return False, "reservation amount must be > 0"
        if amount > self.available():
            return False, (
                f"insufficient headroom: need {amount.value:.6f}, "
                f"have {self.available().value:.6f}"
            )
        return True, ""

    # --- mutations -----------------------------------------------------
    def reserve(self, child_wid: str, amount: Credits) -> ReserveOutcome:
        """
        Idempotent. Re-reserving the SAME (wid, amount) returns the
        existing reservation (a retry / re-post must not double-hold).
        Same wid with a DIFFERENT amount is a conflict and is
        rejected — a committed reservation is never silently mutated.
        A wid whose reservation already reached a terminal state
        cannot be re-reserved.
        """
        existing = self._resv.get(child_wid)
        if existing is not None:
            if existing.state is not ResvState.ACTIVE:
                return ReserveOutcome(
                    False, None,
                    f"{child_wid} already {existing.state.value}; "
                    f"cannot re-reserve",
                )
            if existing.amount == amount:
                return ReserveOutcome(True, existing, "")  # idempotent
            return ReserveOutcome(
                False, None,
                f"{child_wid} already reserved for a different amount "
                f"({existing.amount.value:.6f} ≠ {amount.value:.6f})",
            )

        ok, why = self.can_reserve(amount)
        if not ok:
            return ReserveOutcome(False, None, why)

        # Charge the task budget at reserve time so concurrent
        # reserves see the depleted envelope; the wallet hold is
        # reflected via _active_holds().
        b_ok, b_why = self._budget.try_allocate(amount)
        if not b_ok:
            return ReserveOutcome(False, None, b_why)

        r = Reservation(child_wid, amount, ResvState.ACTIVE)
        self._resv[child_wid] = r
        return ReserveOutcome(True, r, "")

    def _terminate(
        self, child_wid: str, target: ResvState
    ) -> tuple[bool, bool, str]:
        """Returns ``(ok, transitioned, reason)``. ``transitioned`` is
        True ONLY on a real ACTIVE→target change, so callers apply
        any side-effect (e.g. budget refund) exactly once and never
        on an idempotent repeat."""
        r = self._resv.get(child_wid)
        if r is None:
            return False, False, f"no reservation for {child_wid}"
        if r.state is target:
            return True, False, ""  # idempotent: same terminal repeated
        if r.state is not ResvState.ACTIVE:
            # opposite terminal — a paid subcontract must never be
            # retroactively released, nor vice versa.
            return False, False, (
                f"{child_wid} is already {r.state.value}; refusing "
                f"{target.value} (a subcontract is paid XOR abandoned)"
            )
        self._resv[child_wid] = Reservation(child_wid, r.amount, target)
        return True, True, ""

    def settle(self, child_wid: str) -> tuple[bool, str]:
        """
        The subcontract was verified and PAID — a real settled ledger
        entry now exists, so the wallet already reflects the −B.
        Drop the hold (it is now redundant) WITHOUT a second debit:
        the no-double-count identity. The task budget is NOT refunded
        (it was genuinely spent on paid work). Idempotent; refuses to
        settle an already-released reservation.
        """
        ok, _transitioned, why = self._terminate(child_wid, ResvState.SETTLED)
        return ok, why

    def release(self, child_wid: str) -> tuple[bool, str]:
        """
        The subcontract failed / timed out / verification rejected —
        NO payment. Drop the hold; the credits return to
        ``available`` with no debit, AND the task budget allocation
        is refunded (exactly once, on the real transition) so a flaky
        subcontractor cannot permanently burn the job's budget.
        Idempotent; refuses to release an already-settled reservation.
        """
        r = self._resv.get(child_wid)
        ok, transitioned, why = self._terminate(child_wid, ResvState.RELEASED)
        if transitioned and r is not None:
            self._budget.refund(r.amount)
        return ok, why

    def reservation(self, child_wid: str) -> Reservation | None:
        return self._resv.get(child_wid)


__all__ = [
    "Budget",
    "Reservation",
    "ReservationBook",
    "ReserveOutcome",
    "ResvState",
]
