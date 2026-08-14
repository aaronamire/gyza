"""R-B1 — the taxonomy, tested rather than asserted.

A table of classifications is a table of opinions until something checks it. The
discriminant is CONSERVATION, and conservation is empirically testable: sum the
quantity over every frame and see whether it is invariant under the operations
that move it.

THE PREDICTIVE CONTENT, which is what these tests actually check:

  conserved     => preventing the movement leaves the total UNCHANGED; the
                   quantity sits with someone else. Bounding TRANSFERS.
  non-conserved => preventing the movement leaves the total LOWER; nobody
                   gained. Bounding EXTINGUISHES.

If both cases behaved identically the taxonomy would be decoration.

Run:  ~/dev/marshal/.os/bin/python -m pytest research/planetary/ -q
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import conservation as C                                       # noqa: E402

from gyza.containment.log import AppendOnlyLog                 # noqa: E402
from gyza.economy.ledger import LedgerEntry                    # noqa: E402
from gyza.economy.wallet import Wallet                         # noqa: E402

A, B, Z = "aa" * 32, "bb" * 32, "cc" * 32


def _entry(frm, to, amt, ns, settled=True):
    return LedgerEntry(
        entry_id=f"e{ns}", from_compositor=frm, to_compositor=to,
        amount_credits=amt, work_item_id="w", icp_envelope_hash="cc" * 32,
        model_identifier="m", tokens_out=1, duration_ms=1, created_at_ns=ns,
        from_signature="s", to_signature="s", settled=settled)


def _total_over_all_frames(entries, parties):
    """The quantity summed over every frame. Conservation means invariant."""
    return sum(Wallet(entries).net_balance(p).micros for p in parties)


# --------------------------------------------------------------------------- #
#  1. CREDITS ARE CONSERVED — measured, not assumed                            #
# --------------------------------------------------------------------------- #
def test_credits_are_CONSERVED_over_all_frames():
    """Zero-sum: every settled entry moves value between two frames."""
    parties = [A, B, Z]
    assert _total_over_all_frames([], parties) == 0
    for entries in ([_entry(A, B, 60.0, 1)],
                    [_entry(A, B, 60.0, 1), _entry(B, Z, 25.0, 2)],
                    [_entry(A, B, 60.0, 1), _entry(B, Z, 25.0, 2),
                     _entry(Z, A, 10.0, 3)]):
        assert _total_over_all_frames(entries, parties) == 0, entries


def test_PREVENTING_a_credit_movement_leaves_the_total_UNCHANGED():
    """THE TRANSFER SIGNATURE. The payer is better off by exactly what the
    earner is worse off by, so the total does not move -- the harm went
    somewhere rather than away."""
    parties = [A, B]
    allowed = [_entry(A, B, 60.0, 1)]
    refused: list = []                        # the guard declined to settle

    assert _total_over_all_frames(allowed, parties) == 0
    assert _total_over_all_frames(refused, parties) == 0        # UNCHANGED

    payer_saved = (Wallet(refused).net_balance(A).micros
                   - Wallet(allowed).net_balance(A).micros)
    earner_lost = (Wallet(allowed).net_balance(B).micros
                   - Wallet(refused).net_balance(B).micros)
    assert payer_saved == earner_lost == 60_000_000, (payer_saved, earner_lost)


# --------------------------------------------------------------------------- #
#  2. STORAGE IS NOT CONSERVED — the contrast that gives the taxonomy power    #
# --------------------------------------------------------------------------- #
def test_storage_growth_is_NOT_conserved():
    """Appending CREATES events. No other log loses one, so the total over all
    frames rises -- the defining difference from credits."""
    l1, l2 = AppendOnlyLog(), AppendOnlyLog()

    def total():
        return len(l1.events(include_control=True)) + \
               len(l2.events(include_control=True))

    before = total()
    l1.append("p", "stage_artifact", {"bytes": 1024})
    assert total() == before + 1, "appending did not raise the total"


def test_PREVENTING_storage_growth_leaves_the_total_LOWER():
    """THE EXTINGUISH SIGNATURE, and the negative control for the test above.
    Refusing the append means nobody gains the event -- the harm did not move,
    it did not happen."""
    l1, l2 = AppendOnlyLog(), AppendOnlyLog()

    def total():
        return len(l1.events(include_control=True)) + \
               len(l2.events(include_control=True))

    allowed_baseline = total()
    l1.append("p", "stage_artifact", {"bytes": 1024})
    allowed = total()

    m1, m2 = AppendOnlyLog(), AppendOnlyLog()          # the refused world
    refused = len(m1.events(include_control=True)) + \
        len(m2.events(include_control=True))

    assert refused == allowed_baseline < allowed, (refused, allowed)
    # and crucially: no counterparty gained anything
    assert len(m2.events(include_control=True)) == 0


# --------------------------------------------------------------------------- #
#  3. THE TAXONOMY IS DERIVED, NOT ASSIGNED                                    #
# --------------------------------------------------------------------------- #
def test_the_outcome_is_computed_from_the_two_structural_facts():
    """If outcomes were hand-assigned this would be a table of opinions."""
    import inspect
    src = inspect.getsource(C.Quantity.outcome.fget)
    assert "self.conserved" in src and "self.prevented" in src
    for q in C.QUANTITIES:
        if not q.prevented:
            assert q.outcome == C.ALREADY_REALIZED, q.id
        elif q.conserved:
            assert q.outcome == C.TRANSFERS, q.id
        else:
            assert q.outcome == C.EXTINGUISHES, q.id


def test_the_conserved_set_is_exactly_the_economic_layer():
    """P-B1a, fixed in PROGRAM.md §6 before this ran."""
    conserved = sorted(q.id for q in C.QUANTITIES if q.conserved)
    assert conserved == ["H1_credits", "H2_market_capital"], conserved


def test_the_taxonomy_is_not_degenerate():
    """All three outcomes must be populated, or the classification separates
    nothing and the whole exercise is vacuous."""
    s = C.summary()
    assert set(s) == {C.TRANSFERS, C.EXTINGUISHES, C.ALREADY_REALIZED}, s
    assert min(s.values()) >= 2, s


def test_every_quantity_states_its_basis():
    """A classification with no stated reason cannot be argued with, which is
    the same defect as a citation that resolves to nothing."""
    for q in C.QUANTITIES:
        assert len(q.basis.split()) >= 8, q.id
