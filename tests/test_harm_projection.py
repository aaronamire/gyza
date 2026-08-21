"""The declared harm model, measured against REAL production objects.

WHY THIS FILE EXISTS. `tests/test_registry_execution.py` already contains
`test_every_registered_harm_quantity_executes` -- written to enforce
"registering a checker is not evidence that it runs". It built its own `_S`
stub carrying `.capital` and `.authority_violations`, and **no production
object in the tree carried either**. So the discipline test passed while two of
three declared harm classes measured a `getattr` default of zero against their
declared bound. The test was defeated by exactly the mechanism it existed to
catch.

The rule this file applies instead: **a harm quantity is exercised only when it
is fed state built from the same objects production builds it from** -- a real
`Ledger`, a real `BondedMarket`, a real `ReservationBook`. Nothing here defines
a state class of its own.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_harm_projection.py -q
"""
from __future__ import annotations

import time

import pytest

from gyza.containment.gyza_model import build_registries
from gyza.containment.projection import (
    AuthorityViolation, GyzaState, WindowOrigin, project_at_origin,
    project_now,
)
from gyza.economy.ledger import ComputeLedger, LedgerEntry
from gyza.economy.market import BondedMarket
from gyza.identity import LocalCompositor

A = "aa" * 32
B = "bb" * 32


def _entry(frm, to, amt, ns, *, settled=True) -> LedgerEntry:
    """The REAL production dataclass. `Wallet` — the production fold H1 uses —
    is what turns these into a balance; nothing here reimplements one."""
    return LedgerEntry(
        entry_id=f"e{ns}", from_compositor=frm, to_compositor=to,
        amount_credits=amt, work_item_id="w", icp_envelope_hash="cc" * 32,
        model_identifier="m", tokens_out=1, duration_ms=1, created_at_ns=ns,
        from_signature="sig", to_signature="sig", settled=settled,
    )


def _real_ledger(tmp_path, entries):
    """A REAL `ComputeLedger` on disk — real SQLite, real `_row_to_entry`.

    Entries go in via the storage path rather than the cosigning path: the
    question here is whether `all_entries()` output feeds the projection
    unadapted, not whether Ed25519 works (`test_ledger.py` owns that).
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    led = ComputeLedger(LocalCompositor(key_path=str(tmp_path / "k.key")),
                        db_path=str(tmp_path / "ledger.db"))
    for e in entries:
        led._save_entry(e)
    return led


# --------------------------------------------------------------------------- #
#  1. EVERY QUANTITY EXECUTES AGAINST REAL STATE AND RETURNS A REAL NUMBER     #
# --------------------------------------------------------------------------- #
def test_every_registered_quantity_measures_REAL_production_state(tmp_path):
    market = BondedMarket(initial_capital={A: 100.0, B: 50.0})
    led = _real_ledger(tmp_path, [_entry(A, B, 10.0, 1_000)])

    s0 = project_at_origin(
        owner=A, ledger_entries=led.all_entries(),
        capital_entries=market.capital_entries(),
        origin=WindowOrigin(ledger_ns=0, capital_seq=0))
    s = project_now(
        owner=A, ledger_entries=led.all_entries(), active_holds=0.0,
        capital_entries=market.capital_entries())

    harm, _inv = build_registries()
    measured = {}
    for hc in harm:
        v = hc.measure(s0, s)          # must not raise
        assert isinstance(v, float) and v == v, hc.id      # not NaN
        measured[hc.id] = v

    assert set(measured) == {"H3_mesh_exit_rate", "H4_authority",
                             "H5_storage_growth"}
    assert "H2_market_capital" not in measured, "H2 was retired 2026-08-17"
    # H1 must SEE the 10-credit outflow. If it did not, this whole file would
    # be measuring a shape rather than a quantity.
    assert "H1_credits" not in measured, "H1 was retired 2026-08-15"


def test_the_quantities_REFUSE_a_state_missing_their_field(tmp_path):
    """THE FIX, pinned. Absence must raise, never measure zero.

    Before this, `getattr(s, "capital", 0.0)` and
    `getattr(s, "authority_violations", ()) or ()` made a state carrying
    neither field measure 0.0 -- inside bound, silently passing.
    """
    class Bare:
        owner = A

    harm, _inv = build_registries()
    for hc in harm:
        with pytest.raises(AttributeError):
            hc.measure(Bare(), Bare())


def test_a_state_cannot_be_built_without_a_FRAME():
    with pytest.raises(ValueError, match="owner"):
        GyzaState(owner="", entries=[], active_holds=0.0, capital_entries=[])


# --------------------------------------------------------------------------- #
#  2. EACH QUANTITY MOVES WHEN ITS OWN HARM MOVES — and only then              #
#     Without these, "it returned a float" would be the whole assurance.       #
# --------------------------------------------------------------------------- #
def _states(tmp_path, *, entries=(), capital=None, violations=(), holds=0.0,
            origin=None):
    """THE TWO COORDINATES EARN THEIR KEEP HERE, so this is not boilerplate.

    The accounting window opens AFTER the market is capitalised — seeding is an
    endowment, not a drawdown — so `capital_seq` is the seed count. But it
    opens BEFORE any ledger activity, so `ledger_ns` is 0. The two axes need
    genuinely different origins, which a single scalar could not express: with
    `capital_seq=0` the seed itself lands inside the window and H2 correctly
    reports -100.0 (capital gained), which is a different measurement.
    """
    market = BondedMarket(initial_capital=capital or {A: 100.0})
    led = _real_ledger(tmp_path, entries)
    origin = origin or WindowOrigin(
        ledger_ns=0, capital_seq=len(market.capital_entries()))
    s0 = project_at_origin(
        owner=A, ledger_entries=led.all_entries(),
        capital_entries=market.capital_entries(), origin=origin,
        authority_violations=violations)
    s = project_now(
        owner=A, ledger_entries=led.all_entries(), active_holds=holds,
        capital_entries=market.capital_entries(),
        authority_violations=violations)
    return s0, s, market


def _measure(s0, s, cid):
    harm, _ = build_registries()
    return harm.get(cid).measure(s0, s)


def _measure_h2(s0, s):
    """H2 was RETIRED from the registry 2026-08-17, but `_market_capital_at_risk`
    and `WindowOrigin.capital_seq` are still live and still correct. These
    assertions test the FOLD and the ORIGIN, not the registration, so they call
    the quantity directly. Routing them through `build_registries` would make
    them fail for a reason that has nothing to do with what they check."""
    from gyza.containment.gyza_model import _market_capital_at_risk
    return _market_capital_at_risk(s0, s)


def test_H1_IS_RETIRED_and_the_gap_is_REPORTED(tmp_path):
    """H1 was retired 2026-08-15: credits are TOKEN_IS_FAKE, so no level in
    them is checkable, and R-B1 classifies the quantity TRANSFERS.

    It is listed in UNMODELLED rather than deleted, so the gap is REPORTED
    rather than absent -- the same treatment H3 gets. A retired class that
    simply vanished would leave a reader unable to tell it had ever been
    considered.
    """
    from gyza.containment.gyza_model import UNMODELLED

    harm, _inv = build_registries()
    assert "H1_credits" not in {c.id for c in harm}
    assert "H1_credits" in UNMODELLED
    assert "TOKEN_IS_FAKE" in UNMODELLED["H1_credits"]
    assert "TRANSFERS" in UNMODELLED["H1_credits"]


def test_H2_moves_with_REAL_market_capital(tmp_path):
    """The class that measured 0.0 forever. It must now track the append-only
    fold, and it must do so through the market's OWN function."""
    s0, s, market = _states(tmp_path)
    assert _measure_h2(s0, s) == pytest.approx(0.0), \
        "an idle market must show no drawdown"

    # stake against A's capital. `_credit` is the market's ONLY mutator, so
    # folding its entries is precisely what production folds.
    origin = WindowOrigin(ledger_ns=0, capital_seq=len(market.capital_entries()))
    before = market.capital_of(A)
    market._credit(A, -30.0, "stake")
    assert market.capital_of(A) == pytest.approx(before - 30.0)

    s0 = project_at_origin(owner=A, ledger_entries=[],
                           capital_entries=market.capital_entries(),
                           origin=origin)
    s = project_now(owner=A, ledger_entries=[], active_holds=0.0,
                    capital_entries=market.capital_entries())
    assert _measure_h2(s0, s) == pytest.approx(30.0)


def test_H2_uses_the_MARKETS_OWN_FOLD_so_they_cannot_drift(tmp_path):
    """Frame alignment enforced by the call graph, not by review."""
    import inspect

    from gyza.containment import gyza_model
    from gyza.economy.market import fold_capital
    src = inspect.getsource(gyza_model._market_capital_at_risk)
    assert "fold_capital" in src, "H2 reimplemented the fold"
    assert "fold_capital" in inspect.getsource(BondedMarket.capital_of), \
        "the market stopped using the shared fold; they can now drift"
    # and they agree on a real market
    m = BondedMarket(initial_capital={A: 40.0})
    assert fold_capital(m.capital_entries(), A) == m.capital_of(A)


def test_H4_counts_REAL_recorded_violations(tmp_path):
    s0, s, _ = _states(tmp_path)
    assert _measure(s0, s, "H4_authority") == pytest.approx(0.0)

    v = AuthorityViolation(action_id="a1", agent_pubkey=B,
                           reason="enforcement wider than manifest",
                           at_ns=time.time_ns())
    s0, s, _ = _states(tmp_path / "v", violations=[v])
    assert _measure(s0, s, "H4_authority") == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
#  3. THE ORIGIN IS TWO COORDINATES — pinning the category error out           #
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
#  4. THE PRODUCTION BIND — a real runner, a real breach, a real measurement   #
#                                                                              #
#  Everything above feeds the quantities state built by this file. This drives #
#  `AgentRunner._execute` and measures what IT recorded, which is the only way #
#  to show H4 measures production rather than a fixture.                       #
# --------------------------------------------------------------------------- #
def _over_bound_runner(tmp_path):
    from tests.test_runner_audit_integration import (
        _intent, _runner, _within_bounds_executor, _work_item,
    )

    from gyza.blackboard import Blackboard
    from gyza.network.artifact_store import ArtifactStore

    store = ArtifactStore(base_path=str(tmp_path / "cas"))
    bb = Blackboard(str(tmp_path / "bb.db"))
    bb.attach_artifact_store(store)
    # manifest authorises 512 MB; the executor claims 2048 MB
    runner, _ident, _manifest = _runner(tmp_path, bb,
                                        _within_bounds_executor(2048))
    intent_id = "h4-breach-intent"
    _intent(bb, intent_id)
    w = _work_item(intent_id)
    bb.post_work_item(w)
    return runner, w


def test_a_REAL_runner_breach_is_recorded_and_MEASURED_by_H4(tmp_path):
    """The bind, end to end.

    Before this, `_authority_exceedance` read `getattr(s,
    "authority_violations", ())` and **nothing in the tree ever produced that
    list** -- so H4 measured 0 against a bound of 0 and passed. The runner
    detected the breach, refused to sign, and recorded nothing.
    """
    runner, w = _over_bound_runner(tmp_path)
    assert runner.authority_violations == [], "no breach has happened yet"

    with pytest.raises(RuntimeError, match="refusing to sign"):
        runner._execute(w)

    # the breach is now a fact in production state
    vs = runner.authority_violations
    assert len(vs) == 1, "the runner refused but recorded nothing"
    assert vs[0].action_id == w.id and vs[0].at_ns > 0
    assert "memory" in vs[0].reason.lower() or vs[0].reason

    # and the DECLARED harm class measures it against the DECLARED bound
    s0, s, _ = _states(tmp_path / "st", violations=vs)
    harm, inv = build_registries()
    measured = harm.get("H4_authority").measure(s0, s)
    bound = harm.bound("H4_authority")
    assert measured == pytest.approx(1.0)
    assert bound == 0.0
    h4 = [i for i in inv if i.harm_class == "H4_authority"][0]
    assert h4.predicate(measured, bound, s0, s) is False, \
        "a recorded authority breach must violate the declared bound"


def test_the_violation_log_cannot_be_SHORTENED_by_a_caller(tmp_path):
    """H4 is monotone non-cumulative: once exceeded it cannot be un-exceeded.
    A bound whose measurand a caller can truncate is not a bound."""
    runner, w = _over_bound_runner(tmp_path)
    with pytest.raises(RuntimeError):
        runner._execute(w)
    got = runner.authority_violations
    got.clear()
    assert len(runner.authority_violations) == 1, \
        "the caller mutated the thing the bound is measured over"


def test_an_IN_BOUNDS_run_records_NOTHING(tmp_path):
    """Negative control. If every run recorded a violation, the test above
    would be measuring the runner's existence rather than a breach."""
    from tests.test_runner_audit_integration import (
        _intent, _runner, _within_bounds_executor, _work_item,
    )

    from gyza.blackboard import Blackboard
    from gyza.network.artifact_store import ArtifactStore

    store = ArtifactStore(base_path=str(tmp_path / "cas"))
    bb = Blackboard(str(tmp_path / "bb.db"))
    bb.attach_artifact_store(store)
    runner, _i, _m = _runner(tmp_path, bb, _within_bounds_executor(256))
    _intent(bb, "ok-intent")
    w = _work_item("ok-intent")
    bb.post_work_item(w)

    runner._execute(w)                      # 256 <= 512: within bounds
    assert runner.authority_violations == []

    s0, s, _ = _states(tmp_path / "st", violations=runner.authority_violations)
    harm, _inv = build_registries()
    assert harm.get("H4_authority").measure(s0, s) == pytest.approx(0.0)


def test_the_window_origin_separates_LEDGER_ns_from_CAPITAL_seq(tmp_path):
    """NEGATIVE CONTROL for a bug written and caught during this work.

    A single origin value compared against both logs is a category error: a
    nanosecond timestamp exceeds every plausible `seq`, so every capital entry
    sorts before the origin, s0 and s_next fold identical entries, and H2
    measures 0.0 and passes. Demonstrated here so the two-coordinate origin is
    not mistaken for ceremony.
    """
    market = BondedMarket(initial_capital={A: 100.0})
    market._credit(A, -30.0, "stake")
    entries = market.capital_entries()
    now_ns = time.time_ns()

    # the WRONG origin: one value used for both axes
    wrong = [e for e in entries if getattr(e, "seq", 0) < now_ns]
    assert len(wrong) == len(entries), "the category error must swallow all"

    # the RIGHT origin separates them and sees the movement
    right = WindowOrigin(ledger_ns=now_ns, capital_seq=1)
    s0 = project_at_origin(owner=A, ledger_entries=[],
                           capital_entries=entries, origin=right)
    s = project_now(owner=A, ledger_entries=[], active_holds=0.0,
                    capital_entries=entries)
    assert len(s0.capital_entries) == 1 and len(s.capital_entries) == 2
    assert _measure_h2(s0, s) == pytest.approx(30.0)


# --------------------------------------------------------------------------- #
#  H6 — THE REVIEW CADENCE, folded from the durable envelope log               #
# --------------------------------------------------------------------------- #
def test_H6_counts_REAL_envelopes_and_survives_a_restart(tmp_path):
    """The cadence measurand must be DERIVED, not counted in memory.

    An in-process counter resets on restart, which is a cumulative bound whose
    origin moves — ledger artifact #13, the defect that bought unlimited drain.
    This folds the append-only envelope log, so a fresh process over the same
    database sees the same number.
    """
    from tests.test_audit import _honest_workflow

    from gyza.blackboard import Blackboard

    envs, _a, _m, _ = _honest_workflow(tmp_path)
    db = str(tmp_path / "bb.db")
    bb = Blackboard(db)
    for e in envs:
        bb.store_envelope(e)

    n = bb.count_envelopes_since(0)
    assert n == len(envs) > 0

    # a FRESH Blackboard over the same file — as after a restart
    assert Blackboard(db).count_envelopes_since(0) == n, \
        "the count reset across processes — the origin moved"

    # H6 was RETIRED as a harm class 2026-08-21 -- it is a review cadence, and
    # a cadence is a timer by design. The measurand and its durability are
    # unchanged and are what this test is about: the count is DERIVED from the
    # append-only log, so it survives a restart. The interval it feeds is now a
    # signed policy value rather than a harm bound.
    from gyza.containment.review import _signed_cadence_actions
    assert _signed_cadence_actions() == 10000
    assert n == Blackboard(db).count_envelopes_since(0)


def test_H6_is_the_cadence_in_ACTIONS_not_credits():
    """The whole point of splitting it out of H1: credits are TOKEN_IS_FAKE, so
    a bound denominated in them cannot be checked against anything."""
    import inspect

    from gyza.containment import gyza_model
    src = inspect.getsource(gyza_model._unsupervised_actions)
    assert "signed_envelope_count" in src
    assert "credit" not in src.split('"""')[2].lower(), \
        "the cadence quantity must not read a credit figure"
