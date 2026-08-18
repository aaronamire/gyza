"""The settlement gate MECHANISM, kept alive after H1 was retired.

H1_credits was RETIRED as a harm class on 2026-08-15 (user decision): credits
are TOKEN_IS_FAKE, so no level in them is checkable -- the declared 100 refused
every real model's FIRST action -- and R-B1 classifies the quantity TRANSFERS,
so enforcing it relocated harm onto counterparties rather than removing it.
`GlobalCluster` no longer installs a settlement guard, because there is nothing
at that boundary for a declared bound to check.

THE MECHANISM IS NOT RETIRED, and these tests keep it covered: a bound evaluated
at a serialization point, measured AFTER the pending action rather than before,
from an immutable origin, recording rather than refusing by default, and never
disputing the counterparty for our own budget. When credits acquire an external
referent and a real exposure class is declared, this is where it hangs -- and
`SettlementGuard` now REFUSES construction against a class that does not exist,
so it cannot be revived silently.

The tests below therefore register an EXPOSURE class of their own. That is a
fixture, and it is legitimate here precisely because the subject is the
mechanism rather than the registry.

Superseded original header:
The first consequence bound Gyza actually ENFORCES on a production path.

WHY HERE AND NOWHERE ELSE. A census of every checking component in `gyza/`
found the containment layer at zero production callers, and the obvious next
move -- wiring the promotion gate into `AgentRunner` -- would have been wrong:
`runner.py` touches neither ledger nor market, so a guard there measures
quantities the gated path cannot move (AG-3: expensive and inert). H1 moves in
exactly one production place, the PAYER path of `LedgerSettlementService`, and
that path is already serialized, which is what C7 demands of a cumulative bound.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_settlement_harm_gate.py -q
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.test_settlement import (
    _FakeBus, _compositor, _ledger, _wait_until,
)

from gyza.containment.engine import GuardEngine
from gyza.containment.gates import SettlementGuard, ledger_genesis_origin
from gyza.containment.gyza_model import build_registries
from gyza.economy.settlement import LedgerSettlementService

BOUND = 100.0          # the exposure level these mechanism tests declare


def _exposure_registries():
    """A bounded exposure class, standing in for H1's future replacement."""
    from gyza.containment.gyza_model import _credits_at_risk
    from gyza.containment.harm import HarmClass
    from gyza.containment.invariants import Invariant, InvariantClass
    harm, inv = build_registries()
    harm.register(HarmClass(
        id="X_exposure", description="settlement exposure (mechanism fixture)",
        quantity=_credits_at_risk, frame="compositor pubkey",
        frame_mutable=True, code_path="gyza/economy/wallet.py:274 net_balance"))
    harm.load_bounds({"X_exposure": BOUND})
    inv.register(Invariant(id="INV-X-exposure", harm_class="X_exposure",
                           cls=InvariantClass.CUMULATIVE,
                           description="exposure within the declared bound"))
    return harm, inv


class _RepStore:
    """Records what the settlement path says about the peer."""
    def __init__(self):
        self.disputes: list[str] = []
        self.successes: list[str] = []

    def record_dispute(self, pk):  self.disputes.append(pk)
    def record_success(self, pk):  self.successes.append(pk)


@dataclass
class _Rig:
    payer_c: object
    payer_l: object
    payer_bus: object
    payer_env: dict
    payer_svc: object
    earner_c: object
    earner_l: object
    earner_bus: object
    earner_svc: object
    rep: _RepStore

    def stop(self):
        self.payer_svc.stop(); self.earner_svc.stop()
        self.payer_bus.close(); self.earner_bus.close()


def _rig(tmp_path, *, guarded=True, origin=None, enforce=False):
    payer = _compositor(tmp_path, "payer")
    earner = _compositor(tmp_path, "earner")
    payer_l = _ledger(tmp_path, payer, "payer")
    earner_l = _ledger(tmp_path, earner, "earner")
    pbus, ebus = _FakeBus("peer-payer", payer.pubkey_hex), _FakeBus(
        "peer-earner", earner.pubkey_hex)
    pbus.connect(ebus)
    penv: dict[str, str] = {}
    rep = _RepStore()

    guard = None
    if guarded:
        harm, inv = _exposure_registries()
        guard = SettlementGuard(
            GuardEngine(harm, inv), owner=payer.pubkey_hex,
            origin=origin or ledger_genesis_origin(),
            harm_class="X_exposure")

    payer_svc = LedgerSettlementService(
        ledger=payer_l, netd=pbus, envelope_resolver=penv.get,
        reputation_store=rep, harm_guard=guard, harm_enforce=enforce)
    earner_svc = LedgerSettlementService(
        ledger=earner_l, netd=ebus, envelope_resolver={}.get)
    payer_svc.start(); earner_svc.start()
    return _Rig(payer, payer_l, pbus, penv, payer_svc,
                earner, earner_l, ebus, earner_svc, rep)


def _settle(rig, wid, tokens):
    """Earner submits work; returns the entry. cost = tokens * 0.1"""
    h = "ab" * 32
    rig.payer_env[wid] = h
    return rig.earner_svc.submit_earned(
        payer_compositor=rig.payer_c.pubkey_hex,
        payer_peer_id=rig.payer_bus.peer_id,
        work_item_id=wid, icp_envelope_hash=h, model_identifier="mock",
        tokens_out=tokens, duration_ms=10)


def _settled(rig, entry) -> bool:
    e = rig.payer_l.get_entry(entry.entry_id)
    return e is not None and e.settled


# --------------------------------------------------------------------------- #
#  1. THE BOUND BINDS — and the positive control that it is not blocking all   #
# --------------------------------------------------------------------------- #
def test_a_payment_INSIDE_the_bound_settles(tmp_path):
    rig = _rig(tmp_path)
    try:
        e = _settle(rig, "w1", 500)            # 50.0 credits
        assert _wait_until(lambda: _settled(rig, e)), "an in-bounds payment was blocked"
        assert rig.rep.successes, "an admitted settlement must still bump success"
    finally:
        rig.stop()


def test_the_payment_that_CROSSES_the_bound_is_REFUSED(tmp_path):
    """CUMULATIVE, not per-transaction. Each payment is individually legal; it
    is the running total that crosses, which is exactly the class of bound that
    needs a serialization point (C7)."""
    rig = _rig(tmp_path, enforce=True)
    try:
        a = _settle(rig, "w1", 600)            # 60 -> total 60, admitted
        assert _wait_until(lambda: _settled(rig, a))

        b = _settle(rig, "w2", 600)            # would take total to 120 > 100
        assert not _wait_until(lambda: _settled(rig, b), timeout_s=0.6), \
            "a payment crossing the declared bound was cosigned"
        # and the ledger reflects the refusal: only the first drawdown landed
        from gyza.economy.wallet import Wallet
        net = Wallet(rig.payer_l.all_entries()).net_balance(rig.payer_c.pubkey_hex)
        assert net.micros == -60_000_000, net
    finally:
        rig.stop()


def test_UNGUARDED_settlement_is_UNCHANGED(tmp_path):
    """Negative control for the test above. Without a guard the same two
    payments both settle, so the refusal is the guard's doing and not some
    other limit in the path."""
    rig = _rig(tmp_path, guarded=False)
    try:
        a = _settle(rig, "w1", 600)
        assert _wait_until(lambda: _settled(rig, a))
        b = _settle(rig, "w2", 600)
        assert _wait_until(lambda: _settled(rig, b)), \
            "unguarded settlement changed behaviour"
    finally:
        rig.stop()


# --------------------------------------------------------------------------- #
#  2. THE GATE MEASURES THE STATE AFTER THE PAYMENT                            #
#     Measuring the CURRENT state admits the entry that crosses and only       #
#     notices on the next one — bounding vs lagging by one.                    #
# --------------------------------------------------------------------------- #
def test_a_SINGLE_payment_over_the_bound_is_refused_on_the_FIRST_attempt(tmp_path):
    rig = _rig(tmp_path, enforce=True)
    try:
        e = _settle(rig, "w1", 5000)           # 500 credits, alone over 100
        assert not _wait_until(lambda: _settled(rig, e), timeout_s=0.6), \
            "the gate measured the state BEFORE the payment and lagged by one"
        assert rig.payer_l.get_entry(e.entry_id) is None or \
            not rig.payer_l.get_entry(e.entry_id).settled
    finally:
        rig.stop()


def test_the_bound_is_exactly_the_declared_level(tmp_path):
    """A payment landing precisely ON the bound must be admitted: the predicate
    is `h <= bound`, and an off-by-one here would silently tighten a level the
    user declared."""
    rig = _rig(tmp_path, enforce=True)
    try:
        e = _settle(rig, "w1", 1000)           # exactly 100.0 == BOUND
        assert _wait_until(lambda: _settled(rig, e)), \
            "a payment exactly at the declared bound was refused"
    finally:
        rig.stop()


# --------------------------------------------------------------------------- #
#  3. A REFUSAL ON OUR BOUND IS NOT THE PEER'S FAULT                           #
# --------------------------------------------------------------------------- #
def test_the_refusal_does_NOT_dispute_the_peer(tmp_path):
    """The peer did nothing wrong; we hit our own budget. Bumping their
    reputation would punish a counterparty for our declaration and corrupt the
    only signal the dispute counter carries."""
    rig = _rig(tmp_path, enforce=True)
    try:
        e = _settle(rig, "w1", 5000)
        assert not _wait_until(lambda: _settled(rig, e), timeout_s=0.6)
        assert rig.rep.disputes == [], \
            f"a harm-bound refusal disputed the peer: {rig.rep.disputes}"
    finally:
        rig.stop()


# --------------------------------------------------------------------------- #
#  4. THE EARNER DIRECTION IS NOT GATED                                        #
# --------------------------------------------------------------------------- #
def test_RECEIVING_credits_is_never_refused(tmp_path):
    """H1 is a DRAWDOWN. The earner path settles credits IN, so a drawdown
    bound there would watch the wrong direction — the mistake this gate's
    placement exists to avoid."""
    rig = _rig(tmp_path)
    try:
        # our node earns from the peer: submit from the "earner" side means the
        # guarded node is the payer, so instead check the guarded node's own
        # earner path directly by settling a large amount TOWARD it.
        harm, inv = _exposure_registries()
        g = SettlementGuard(GuardEngine(harm, inv),
                            owner=rig.payer_c.pubkey_hex,
                            origin=ledger_genesis_origin(),
                            harm_class="X_exposure")
        e = _settle(rig, "w1", 5000)
        # flip the direction: the guarded owner is the EARNER on this entry
        import dataclasses
        inbound = dataclasses.replace(
            e, from_compositor=rig.earner_c.pubkey_hex,
            to_compositor=rig.payer_c.pubkey_hex)
        d = g.check_payment([], inbound)
        assert d.admit, f"receiving credits was refused: {d.reasons}"
        assert d.measured["X_exposure"] <= 0.0, d.measured
    finally:
        rig.stop()


# --------------------------------------------------------------------------- #
#  5. THE ORIGIN CANNOT MOVE                                                   #
# --------------------------------------------------------------------------- #
def test_the_origin_is_GENESIS_so_a_restart_does_not_refill_the_budget(tmp_path):
    """A cumulative bound whose origin moves is not a bound (ledger artifact
    #13). An origin at process start is that defect in a hat: restart and the
    budget refills. Genesis cannot move, and this pins it."""
    rig = _rig(tmp_path)
    try:
        a = _settle(rig, "w1", 900)            # 90 credits
        assert _wait_until(lambda: _settled(rig, a))
        entries = rig.payer_l.all_entries()
    finally:
        rig.stop()

    # a FRESH guard, as after a restart, over the SAME persistent ledger
    harm, inv = _exposure_registries()
    fresh = SettlementGuard(GuardEngine(harm, inv), owner=rig.payer_c.pubkey_hex,
                            origin=ledger_genesis_origin(),
                            harm_class="X_exposure")
    import dataclasses
    pending = dataclasses.replace(entries[0], entry_id="second",
                                  amount_credits=50.0)
    d = fresh.check_payment(entries, pending)
    assert not d.admit, \
        "a restart refilled the drawdown budget — the origin moved"
    assert d.measured["X_exposure"] == pytest.approx(140.0)


# --------------------------------------------------------------------------- #
#  6. THE PRODUCTION INSTALL SITE                                              #
#                                                                              #
#  Everything above drives a `LedgerSettlementService` this file constructs.    #
#  That exercises the GATE but says nothing about whether the thing production  #
#  builds has one — the distinction between a checker being registered and      #
#  being run. `GlobalCluster` is the only production install site.              #
# --------------------------------------------------------------------------- #
def test_GLOBALCLUSTER_installs_NO_guard_now_that_H1_is_retired(tmp_path):
    """Inverted from what it asserted before, and the inversion is the point.

    H1 was the only class the settlement boundary had to check. With it retired
    there is nothing there for a declared bound to evaluate, so installing a
    guard would be machinery watching a class that does not exist. This test
    will FAIL the moment a real exposure class is declared and hung here, which
    is the reminder to re-point it rather than a regression.
    """
    from tests.test_global_cluster import (
        _FakeCapability, _FakeGossip, _FakeNetd,
    )
    from tests.test_global_cluster import _compositor as _gc_compositor
    from tests.test_global_cluster import _run, _start

    from gyza.config import GyzaConfig
    from gyza.economy.ledger import ComputeLedger
    from gyza.network.global_cluster import GlobalCluster
    from gyza.network.network_blackboard import NetworkBlackboard

    comp = _gc_compositor(tmp_path, "self")
    cfg = GyzaConfig(
        compositor_key_path=str(tmp_path / "self.key"),
        netd_socket_path=str(tmp_path / "netd.sock"),
        netd_ledger_db_path=str(tmp_path / "ledger.db"),
        blackboard_db_path=str(tmp_path / "bb.db"))
    gc = GlobalCluster(
        compositor=comp, config=cfg,
        blackboard=NetworkBlackboard(str(tmp_path / "bb.db")),
        ledger=ComputeLedger(comp, str(tmp_path / "ledger.db")),
        netd_client=_FakeNetd(our_pubkey=comp.pubkey_hex),
        gossip_client=_FakeGossip(),
        capability_client_factory=_FakeCapability)
    _start(gc)
    try:
        assert gc._settlement._harm_guard is None, (
            "a settlement guard is installed but H1 is retired — it would be "
            "watching a class that does not exist")
    finally:
        _run(gc.stop())


def test_the_guard_REFUSES_construction_against_a_RETIRED_class():
    """What replaced the miscalibration tests.

    Two tests here used to document that the declared 100-credit bound refused
    every real model's first action. Retirement resolved that by removing the
    bound, so the documentation is moot — but the FAILURE MODE it guarded
    against is not: a guard silently revived against a class nobody registered
    would admit everything. Construction now fails instead.
    """
    from gyza.containment.gyza_model import UNMODELLED

    harm, inv = build_registries()
    assert "H1_credits" in UNMODELLED, "H1 must stay reported, not vanish"
    with pytest.raises(KeyError, match="H1_credits"):
        SettlementGuard(GuardEngine(harm, inv), owner="aa" * 32,
                        origin=ledger_genesis_origin(),
                        harm_class="H1_credits")


def test_a_guard_REQUIRES_a_frame():
    harm, inv = _exposure_registries()
    with pytest.raises(ValueError, match="owner"):
        SettlementGuard(GuardEngine(harm, inv), owner="",
                        origin=ledger_genesis_origin(), harm_class="X_exposure")


# --------------------------------------------------------------------------- #
#  7. THE BOUND AGAINST THE REAL COST MODEL                                    #
#                                                                              #
#  R-D1b: the suite settles only at `mock` rates, which land at or under the   #
#  declared bound. Nothing exercised a REAL model's pricing, so a bound that    #
#  refuses every real model's FIRST action survived 1068 passing tests.        #
# --------------------------------------------------------------------------- #
# The two calibration tests that lived here documented that the declared
# 100-credit bound refused every real model's FIRST action. H1 was retired
# 2026-08-15, which resolves the miscalibration by removing the bound, so the
# documentation is moot. Their successor is
# `test_the_guard_REFUSES_construction_against_a_RETIRED_class` above, which
# keeps the failure mode covered: a guard revived against an unregistered class
# would admit everything.


# --------------------------------------------------------------------------- #
#  8. RECORD-ONLY IS THE DEFAULT                                               #
#                                                                              #
#  What shipped yesterday enforced a bound smaller than a single real-model     #
#  action, so it blocked all real settlement. Recording keeps the mechanism     #
#  exercised on every settlement while a miscalibrated level cannot halt the    #
#  system — and the record is what makes the level decidable.                   #
# --------------------------------------------------------------------------- #
def test_record_only_LETS_TRAFFIC_THROUGH_and_still_sees_the_bound(tmp_path):
    rig = _rig(tmp_path)                       # guarded, default record-only
    try:
        ents = [_settle(rig, f"w{i}", 600) for i in range(4)]   # 4x60 = 240 vs B=100
        for e in ents:
            _wait_until(lambda: _settled(rig, e), timeout_s=1.5)
        assert all(_settled(rig, e) for e in ents), \
            "record-only mode blocked settlement"

        s = rig.payer_svc.harm_summary()
        assert s["enforcing"] is False
        assert s["evaluations"] == 4
        assert s["would_have_refused"] == 3, s
        assert s["peak_measured"]["X_exposure"] == pytest.approx(240.0)
    finally:
        rig.stop()


def test_ENFORCING_still_refuses_exactly_as_before(tmp_path):
    """The refusal path is unchanged and still tested — record-only is a
    default, not a removal."""
    rig = _rig(tmp_path, enforce=True)
    try:
        a = _settle(rig, "w1", 600)
        assert _wait_until(lambda: _settled(rig, a))
        b = _settle(rig, "w2", 600)
        assert not _wait_until(lambda: _settled(rig, b), timeout_s=0.6), \
            "enforcing mode failed to refuse"
        s = rig.payer_svc.harm_summary()
        assert s["enforcing"] is True and s["would_have_refused"] >= 1
    finally:
        rig.stop()


def test_the_record_keeps_NEAR_MISSES_not_just_refusals(tmp_path):
    """`would_have_refused` is the counterfactual the calibration rests on.
    Recording only the admitted evaluations would leave the question this
    mechanism exists to answer unanswerable."""
    rig = _rig(tmp_path)
    try:
        e = _settle(rig, "w1", 5000)           # 500 credits, far over
        _wait_until(lambda: _settled(rig, e), timeout_s=1.5)
        recs = rig.payer_svc.harm_records
        assert len(recs) == 1 and recs[0].admitted is False
        assert recs[0].measured["X_exposure"] > 100.0
        assert recs[0].reasons, "a refusal record must carry its reason"
    finally:
        rig.stop()


def test_the_record_cannot_be_SHORTENED_by_a_caller(tmp_path):
    rig = _rig(tmp_path)
    try:
        e = _settle(rig, "w1", 600)
        _wait_until(lambda: _settled(rig, e), timeout_s=1.5)
        got = rig.payer_svc.harm_records
        got.clear()
        assert len(rig.payer_svc.harm_records) == 1, \
            "a caller mutated the record a calibration decision rests on"
    finally:
        rig.stop()
