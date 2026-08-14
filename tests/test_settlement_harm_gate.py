"""The first consequence bound Gyza actually ENFORCES on a production path.

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

BOUND = 100.0          # guard_bounds.json, user decision 2026-07-31


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


def _rig(tmp_path, *, guarded=True, origin=None):
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
        harm, inv = build_registries()
        guard = SettlementGuard(
            GuardEngine(harm, inv), owner=payer.pubkey_hex,
            origin=origin or ledger_genesis_origin())

    payer_svc = LedgerSettlementService(
        ledger=payer_l, netd=pbus, envelope_resolver=penv.get,
        reputation_store=rep, harm_guard=guard)
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
    rig = _rig(tmp_path)
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
    rig = _rig(tmp_path)
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
    rig = _rig(tmp_path)
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
    rig = _rig(tmp_path)
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
        harm, inv = build_registries()
        g = SettlementGuard(GuardEngine(harm, inv),
                            owner=rig.payer_c.pubkey_hex,
                            origin=ledger_genesis_origin())
        e = _settle(rig, "w1", 5000)
        # flip the direction: the guarded owner is the EARNER on this entry
        import dataclasses
        inbound = dataclasses.replace(
            e, from_compositor=rig.earner_c.pubkey_hex,
            to_compositor=rig.payer_c.pubkey_hex)
        d = g.check_payment([], inbound)
        assert d.admit, f"receiving credits was refused: {d.reasons}"
        assert d.measured["H1_credits"] <= 0.0, d.measured
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
    harm, inv = build_registries()
    fresh = SettlementGuard(GuardEngine(harm, inv), owner=rig.payer_c.pubkey_hex,
                            origin=ledger_genesis_origin())
    import dataclasses
    pending = dataclasses.replace(entries[0], entry_id="second",
                                  amount_credits=50.0)
    d = fresh.check_payment(entries, pending)
    assert not d.admit, \
        "a restart refilled the drawdown budget — the origin moved"
    assert d.measured["H1_credits"] == pytest.approx(140.0)


# --------------------------------------------------------------------------- #
#  6. THE PRODUCTION INSTALL SITE                                              #
#                                                                              #
#  Everything above drives a `LedgerSettlementService` this file constructs.    #
#  That exercises the GATE but says nothing about whether the thing production  #
#  builds has one — the distinction between a checker being registered and      #
#  being run. `GlobalCluster` is the only production install site.              #
# --------------------------------------------------------------------------- #
def test_GLOBALCLUSTER_installs_the_guard_on_its_settlement_service(tmp_path):
    from tests.test_global_cluster import (
        _FakeCapability, _FakeGossip, _FakeNetd,
    )
    from tests.test_global_cluster import _compositor as _gc_compositor

    from gyza.config import GyzaConfig
    from gyza.economy.ledger import ComputeLedger
    from gyza.network.network_blackboard import NetworkBlackboard
    from gyza.network.global_cluster import GlobalCluster

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
    # start() is async; test_global_cluster's own helper does the same.
    from tests.test_global_cluster import _run, _start
    _start(gc)
    try:
        guard = gc._settlement._harm_guard
        assert guard is not None, \
            "the production settlement service has NO harm guard installed"
        assert guard.owner == comp.pubkey_hex, \
            "the guard's frame is not this node's compositor key"
    finally:
        _run(gc.stop())


def test_a_guard_REQUIRES_a_frame():
    harm, inv = build_registries()
    with pytest.raises(ValueError, match="owner"):
        SettlementGuard(GuardEngine(harm, inv), owner="",
                        origin=ledger_genesis_origin())
