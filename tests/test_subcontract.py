"""
Subcontract accounting-core tests.

Hardest / most important:
  * test_no_double_count_identity — reserve→settle leaves `available`
    UNCHANGED at the settle instant (hold reclassified into the real
    settled debit, never counted twice); reserve→release RETURNS the
    headroom with no debit.
  * test_release_refunds_budget_settle_does_not — a flaky
    subcontractor must not permanently burn the job's budget; a paid
    one genuinely consumes it.
If either is wrong the economic core is unsound.
"""
from __future__ import annotations

from gyza.economy.subcontract import Budget, ReservationBook
from gyza.economy.wallet import Credits

OWNER = "owner-pk"


def C(n: float) -> Credits:
    return Credits(round(n * 1_000_000))


class _W:
    """Controllable wallet stub — set() simulates a settled ledger
    entry landing (what cosign-as-payer would cause in reality)."""

    def __init__(self, credits: float) -> None:
        self._m = round(credits * 1_000_000)

    def set(self, credits: float) -> None:
        self._m = round(credits * 1_000_000)

    def net_balance(self, pubkey: str) -> Credits:
        return Credits(self._m)


def _book(wallet_credits: float, budget_credits: float) -> tuple:
    w = _W(wallet_credits)
    b = Budget(C(budget_credits))
    return ReservationBook(w, OWNER, b), w, b


# ----------------------------------------------------------------------
# THE no-double-count identity
# ----------------------------------------------------------------------

def test_no_double_count_identity():
    book, w, b = _book(100, 100)
    assert book.available() == C(100)

    assert book.reserve("W1", C(30)).ok
    assert book.available() == C(70)          # hold 30
    assert book.reserve("W2", C(20)).ok
    assert book.available() == C(50)          # holds 50
    before = book.available()

    # The loop cosigns-as-payer for W1 → a real settled −30 entry
    # lands in the wallet. Simulate that AND settle the hold.
    w.set(70)
    ok, why = book.settle("W1")
    assert ok, why
    # available is UNCHANGED at the settle instant: 70 wallet − 20
    # remaining hold = 50. The 30 moved from "hold" to "real debit",
    # never subtracted twice.
    assert book.available() == before == C(50)

    # W2 is abandoned (no payment). Wallet unchanged; hold returns.
    ok, why = book.release("W2")
    assert ok, why
    assert w._m == 70_000_000                 # no debit for W2
    assert book.available() == C(70)          # 70 − 0 holds


# ----------------------------------------------------------------------
# Budget refund semantics (caught by thinking hard about release)
# ----------------------------------------------------------------------

def test_release_refunds_budget_settle_does_not():
    book, w, b = _book(1000, 50)              # wallet rich; budget tight

    assert book.reserve("S1", C(40)).ok
    assert b.remaining() == C(10)
    # Subcontractor S1 flakes out — released. Budget must come back,
    # else two bad subcontractors exhaust a 50-credit job.
    book.release("S1")
    assert b.remaining() == C(50)             # refunded

    # Retry with a fresh subcontractor on the refunded budget.
    assert book.reserve("S2", C(40)).ok
    w.set(960)                                 # paid -40
    book.settle("S2")
    assert b.remaining() == C(10)             # settled spends it for good
    # A further release of the PAID one must not refund.
    ok, why = book.release("S2")
    assert not ok and "already settled" in why
    assert b.remaining() == C(10)


# ----------------------------------------------------------------------
# The two constraints bind INDEPENDENTLY
# ----------------------------------------------------------------------

def test_budget_binds_even_when_wallet_is_rich():
    book, _w, _b = _book(1000, 10)
    assert book.available() == C(10)
    assert book.reserve("X", C(8)).ok
    out = book.reserve("Y", C(5))             # only 2 budget left
    assert not out.ok and "insufficient headroom" in out.reason


def test_wallet_binds_even_when_budget_is_huge():
    book, _w, _b = _book(5, 1000)
    assert book.available() == C(5)
    assert not book.reserve("X", C(8)).ok
    assert book.reserve("Y", C(4)).ok


def test_negative_wallet_blocks_all_commitments():
    w = _W(0)
    w.set(-3)
    book = ReservationBook(w, OWNER, Budget(C(1000)))
    assert book.available().micros < 0
    assert not book.reserve("X", C(1)).ok


# ----------------------------------------------------------------------
# Idempotence + conflict + terminal state machine
# ----------------------------------------------------------------------

def test_reserve_is_idempotent_same_args():
    book, _w, _b = _book(100, 100)
    r1 = book.reserve("W", C(10))
    avail = book.available()
    r2 = book.reserve("W", C(10))             # retry / re-post
    assert r1.ok and r2.ok
    assert r2.reservation == r1.reservation
    assert book.available() == avail          # NOT double-held


def test_reserve_conflict_same_wid_different_amount():
    book, _w, _b = _book(100, 100)
    assert book.reserve("W", C(10)).ok
    out = book.reserve("W", C(20))
    assert not out.ok and "different amount" in out.reason
    assert book.reservation("W").amount == C(10)   # original intact


def test_cannot_re_reserve_a_terminal_wid():
    book, w, _b = _book(100, 100)
    book.reserve("W", C(10))
    w.set(90)
    book.settle("W")
    out = book.reserve("W", C(10))
    assert not out.ok and "already settled" in out.reason


def test_terminal_state_machine():
    book, w, _b = _book(100, 100)
    book.reserve("W", C(10))

    assert book.settle("W") == (True, "")
    assert book.settle("W") == (True, "")            # idempotent repeat
    ok, why = book.release("W")                       # opposite terminal
    assert not ok and "already settled" in why

    book.reserve("V", C(5))
    assert book.release("V")[0] is True
    assert book.release("V")[0] is True               # idempotent repeat
    ok, why = book.settle("V")
    assert not ok and "already released" in why


def test_settle_release_unknown_wid():
    book, _w, _b = _book(100, 100)
    assert book.settle("nope") == (False, "no reservation for nope")
    assert book.release("nope") == (False, "no reservation for nope")


def test_reserve_rejects_non_positive():
    book, _w, _b = _book(100, 100)
    assert not book.reserve("W", C(0)).ok
    assert not book.reserve("W", Credits(-5)).ok


# ----------------------------------------------------------------------
# Budget tree — strictly-shrinking, subtree ≤ root
# ----------------------------------------------------------------------

def test_budget_tree_is_finite_and_partitioned():
    root = Budget(C(100))
    child_a = root.child(C(60))
    child_b = root.child(C(30))
    assert root.remaining() == C(10)

    # a child can only sub-allocate what it received
    grand = child_a.child(C(50))
    assert child_a.remaining() == C(10)
    ok, why = child_a.try_allocate(C(20))
    assert not ok and "exceeds remaining" in why

    # over-allocating the root is rejected
    ok, why = root.try_allocate(C(50))
    assert not ok

    # whole subtree's allocations never exceed the root
    total_allocated = (
        root.allocated.micros               # 60 + 30 = 90 from root
    )
    assert total_allocated == C(90).micros
    assert grand.total == C(50)
    # creating a child you can't afford raises (callers try_allocate first)
    try:
        root.child(C(999))
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_budget_rejects_negative_total_and_nonpositive_alloc():
    try:
        Budget(Credits(-1))
        bad = False
    except ValueError:
        bad = True
    assert bad
    b = Budget(C(10))
    assert not b.try_allocate(C(0))[0]
    assert not b.try_allocate(Credits(-1))[0]


# ----------------------------------------------------------------------
# Crash-safety: a fresh book over a wallet that already reflects past
# settled debits reads reality correctly — no double count, no need to
# reconstruct lost holds.
# ----------------------------------------------------------------------

def test_fresh_book_over_already_debited_wallet_is_correct():
    # Prior process reserved+paid 40 then crashed before settle().
    # New process: empty book, wallet already shows the −40.
    w = _W(60)                                 # 100 − 40 already settled
    book = ReservationBook(w, OWNER, Budget(C(1000)))
    assert book.available() == C(60)           # just reads settled truth
    assert book.reserve("NEW", C(50)).ok
    assert book.available() == C(10)
