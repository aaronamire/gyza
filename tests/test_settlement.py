"""
Phase 3 Session 6 — bilateral settlement protocol.

These tests exercise the protocol layer (gyza.economy.settlement)
against a fake message bus. We do NOT stand up the daemon: that path
is covered by tests/test_netd_client.py::test_message_send_subscribe_two_daemons,
which proves Python ↔ Go ↔ Python can carry an arbitrary frame.

What the protocol must guarantee:

  1. Round-trip happy path: earner submits, payer cosigns, earner
     applies. Both ledgers end up with the same settled entry.

  2. Tolerance check: payer rejects an amount diverging from its own
     recompute by more than ±20% — caps griefing on cost claims.

  3. Envelope-hash check: payer rejects an entry whose
     icp_envelope_hash doesn't match what the local blackboard knows.

  4. Routing check: payer ignores an entry where from_compositor
     is not us; earner ignores an entry where to_compositor is not us.

  5. Idempotence: re-delivery of either message type doesn't double
     anything — no duplicate cosignature, no double balance update.

  6. Verification: a forged earner signature is rejected before payer
     cosigns; a forged payer cosignature is rejected before earner
     applies.

  7. Unknown work_item_id: rejected (the local node has no completion
     record, so cannot validate the cost).
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue

import pytest

from gyza.economy.ledger import (
    ComputeLedger,
    LedgerEntry,
    canonical_sign_bytes,
    compute_task_cost,
)
from gyza.economy.settlement import (
    EARNER_SIGNED_TYPE,
    PAYER_COSIGNED_TYPE,
    LedgerSettlementService,
)
from gyza.identity import LocalCompositor


# ======================================================================
# Test doubles
# ======================================================================

@dataclass
class _Incoming:
    """Mirror of netd_pb2.IncomingMessage's accessed fields."""
    sender_peer_id: str
    sender_pubkey: str
    message_type: str
    payload: bytes
    timestamp_ns: int = 0


class _FakeBus:
    """
    In-process pub/sub that mimics NetdClient's ``send_message`` /
    ``subscribe_messages``. Two buses can be wired together via
    ``connect(other)`` so a send to ``other.peer_id`` lands as an
    incoming message in ``other``'s subscription stream.

    We don't need topology beyond two-bus pairs: settlement is strictly
    point-to-point. A test that wants three parties wires up three
    pairs.
    """

    def __init__(self, peer_id: str, sender_pubkey: str):
        self.peer_id = peer_id
        self.sender_pubkey = sender_pubkey
        self._queue: Queue = Queue()
        self._peers: dict[str, "_FakeBus"] = {}
        # Lets tests inject malformed / synthetic frames into our
        # subscription stream.
        self._inject: Queue = Queue()
        self._closed = threading.Event()
        # Rolling log of every send_message call we made (for assertion).
        self.sent: list[tuple[str, str, bytes]] = []
        # send_message can be made to fail (returns False) by setting
        # self.fail_send to True. Keeps re-entrancy bug tests simple.
        self.fail_send = False

    def connect(self, other: "_FakeBus") -> None:
        self._peers[other.peer_id] = other
        other._peers[self.peer_id] = self

    def send_message(
        self, peer_id: str, message_type: str, payload: bytes,
    ) -> bool:
        self.sent.append((peer_id, message_type, bytes(payload)))
        if self.fail_send:
            return False
        target = self._peers.get(peer_id)
        if target is None:
            return False
        target._queue.put(_Incoming(
            sender_peer_id=self.peer_id,
            sender_pubkey=self.sender_pubkey,
            message_type=message_type,
            payload=bytes(payload),
            timestamp_ns=time.time_ns(),
        ))
        return True

    def inject(self, msg: _Incoming) -> None:
        """Push a synthetic incoming straight to our subscriber."""
        self._queue.put(msg)

    def subscribe_messages(self, message_types=None):
        wanted = set(message_types or [])
        while not self._closed.is_set():
            try:
                msg = self._queue.get(timeout=0.05)
            except Empty:
                continue
            if wanted and msg.message_type not in wanted:
                continue
            yield msg

    def close(self) -> None:
        self._closed.set()


# ======================================================================
# Fixtures
# ======================================================================

def _compositor(tmp_path: Path, name: str) -> LocalCompositor:
    p = tmp_path / f"{name}.key"
    p.write_bytes(secrets.token_bytes(32))
    p.chmod(0o600)
    return LocalCompositor(str(p))


def _ledger(tmp_path: Path, c: LocalCompositor, name: str) -> ComputeLedger:
    return ComputeLedger(c, str(tmp_path / f"{name}.db"))


@dataclass
class _Pair:
    """Two-node settlement test rig: payer side + earner side, wired bidirectionally."""
    payer_compositor: LocalCompositor
    payer_ledger: ComputeLedger
    payer_bus: _FakeBus
    payer_envelopes: dict[str, str]
    payer_svc: LedgerSettlementService

    earner_compositor: LocalCompositor
    earner_ledger: ComputeLedger
    earner_bus: _FakeBus
    earner_envelopes: dict[str, str]
    earner_svc: LedgerSettlementService

    def stop(self) -> None:
        self.payer_svc.stop()
        self.earner_svc.stop()
        self.payer_bus.close()
        self.earner_bus.close()


def _make_pair(tmp_path: Path) -> _Pair:
    payer = _compositor(tmp_path, "payer")
    earner = _compositor(tmp_path, "earner")
    payer_l = _ledger(tmp_path, payer, "payer")
    earner_l = _ledger(tmp_path, earner, "earner")

    payer_bus = _FakeBus("peer-payer", payer.pubkey_hex)
    earner_bus = _FakeBus("peer-earner", earner.pubkey_hex)
    payer_bus.connect(earner_bus)

    payer_envelopes: dict[str, str] = {}
    earner_envelopes: dict[str, str] = {}

    payer_svc = LedgerSettlementService(
        ledger=payer_l, netd=payer_bus,
        envelope_resolver=payer_envelopes.get,
    )
    earner_svc = LedgerSettlementService(
        ledger=earner_l, netd=earner_bus,
        envelope_resolver=earner_envelopes.get,
    )
    payer_svc.start()
    earner_svc.start()
    return _Pair(
        payer, payer_l, payer_bus, payer_envelopes, payer_svc,
        earner, earner_l, earner_bus, earner_envelopes, earner_svc,
    )


def _wait_until(predicate, timeout_s: float = 2.0, poll_s: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


# ======================================================================
# Happy path
# ======================================================================

def test_round_trip_settles_both_ledgers(tmp_path):
    """
    Full bilateral round-trip. After the dust settles:
      * payer ledger has the entry, settled, with both sigs.
      * earner ledger has the entry, settled, with both sigs.
      * the cosigned entries are byte-identical between the two ledgers.
      * payer's balance with earner is -100 (it owes the earner).
    """
    rig = _make_pair(tmp_path)
    try:
        # Mock that the payer node knows about this completed work.
        # Real-world this is fed from the local Blackboard.
        envelope_hash = "ab" * 32
        rig.payer_envelopes["work-001"] = envelope_hash

        # Earner submits.
        entry = rig.earner_svc.submit_earned(
            payer_compositor=rig.payer_compositor.pubkey_hex,
            payer_peer_id=rig.payer_bus.peer_id,
            work_item_id="work-001",
            icp_envelope_hash=envelope_hash,
            model_identifier="mock",
            tokens_out=1000,  # cost = 1000 * 0.1 = 100.0
            duration_ms=1000,
            # amount defaults to compute_task_cost = 100.0
        )
        assert entry.amount_credits == 100.0
        assert entry.to_signature
        assert not entry.from_signature
        assert not entry.settled

        # Wait for round-trip to land.
        assert _wait_until(
            lambda: (
                (e := rig.earner_ledger.get_entry(entry.entry_id)) is not None
                and e.settled
            ),
            timeout_s=2.0,
        ), "earner ledger never saw settled entry"

        payer_view = rig.payer_ledger.get_entry(entry.entry_id)
        earner_view = rig.earner_ledger.get_entry(entry.entry_id)
        assert payer_view is not None and payer_view.settled
        assert earner_view is not None and earner_view.settled
        # Byte-identical cosigned record.
        assert payer_view.to_dict() == earner_view.to_dict()

        # Balances. Earner's get_balance(payer) returns +100 (payer owes us).
        assert rig.earner_ledger.get_balance(rig.payer_compositor.pubkey_hex) == 100.0
        # Payer's get_balance(earner) returns -100 (we owe them).
        assert rig.payer_ledger.get_balance(rig.earner_compositor.pubkey_hex) == -100.0
    finally:
        rig.stop()


def test_idempotent_redelivery(tmp_path):
    """
    A second copy of "earner_signed" — say, gossipsub re-mesh
    re-delivers the frame — must not produce a second
    "payer_cosigned" reply or a second balance update.
    """
    rig = _make_pair(tmp_path)
    try:
        rig.payer_envelopes["w"] = "cd" * 32
        entry = rig.earner_svc.submit_earned(
            payer_compositor=rig.payer_compositor.pubkey_hex,
            payer_peer_id=rig.payer_bus.peer_id,
            work_item_id="w",
            icp_envelope_hash="cd" * 32,
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        assert _wait_until(
            lambda: rig.earner_ledger.get_entry(entry.entry_id).settled,
        )

        # Snapshot how many "payer_cosigned" frames we sent.
        cosigned_count_before = sum(
            1 for (_, mt, _) in rig.payer_bus.sent
            if mt == PAYER_COSIGNED_TYPE
        )
        assert cosigned_count_before == 1

        # Re-deliver the original earner_signed payload to the payer.
        original_payload = next(
            p for (_, mt, p) in rig.earner_bus.sent
            if mt == EARNER_SIGNED_TYPE
        )
        rig.payer_bus.inject(_Incoming(
            sender_peer_id=rig.earner_bus.peer_id,
            sender_pubkey=rig.earner_compositor.pubkey_hex,
            message_type=EARNER_SIGNED_TYPE,
            payload=original_payload,
        ))
        # Also re-deliver the payer_cosigned to the earner.
        original_cosigned = next(
            p for (_, mt, p) in rig.payer_bus.sent
            if mt == PAYER_COSIGNED_TYPE
        )
        rig.earner_bus.inject(_Incoming(
            sender_peer_id=rig.payer_bus.peer_id,
            sender_pubkey=rig.payer_compositor.pubkey_hex,
            message_type=PAYER_COSIGNED_TYPE,
            payload=original_cosigned,
        ))

        # Give handlers time to process the re-deliveries.
        time.sleep(0.2)

        cosigned_count_after = sum(
            1 for (_, mt, _) in rig.payer_bus.sent
            if mt == PAYER_COSIGNED_TYPE
        )
        # Crucial: the payer did NOT send a second cosigned frame.
        assert cosigned_count_after == 1, (
            f"payer cosigned {cosigned_count_after} times — settlement "
            f"is not idempotent on re-delivery"
        )
        # Balance unchanged.
        assert rig.earner_ledger.get_balance(rig.payer_compositor.pubkey_hex) == 1.0
    finally:
        rig.stop()


# ======================================================================
# Verification
# ======================================================================

def test_amount_outside_tolerance_rejected(tmp_path):
    """
    Earner inflates the claimed amount to 2.0× our recompute. Payer's
    ±20% check rejects: no payer_cosigned reply, no settlement.
    """
    rig = _make_pair(tmp_path)
    try:
        rig.payer_envelopes["w"] = "ee" * 32
        # Real cost = 100 tokens × 0.1 = 10.0. We claim 30.0 (3× over).
        entry = rig.earner_svc.submit_earned(
            payer_compositor=rig.payer_compositor.pubkey_hex,
            payer_peer_id=rig.payer_bus.peer_id,
            work_item_id="w",
            icp_envelope_hash="ee" * 32,
            model_identifier="mock",
            tokens_out=100, duration_ms=100,
            amount=30.0,  # explicit override — well outside ±20%
        )
        # Wait briefly; expectation is no settlement.
        time.sleep(0.3)

        # Earner side: never received cosigned reply.
        assert not rig.earner_ledger.get_entry(entry.entry_id).settled
        # Payer side: never persisted the entry at all (rejected before
        # sign_as_payer touched the DB).
        assert rig.payer_ledger.get_entry(entry.entry_id) is None
    finally:
        rig.stop()


def test_unknown_work_item_id_rejected(tmp_path):
    """
    Payer doesn't recognize the work_item_id (envelope_resolver returns
    None). Reject.
    """
    rig = _make_pair(tmp_path)
    try:
        # NOT seeded into payer_envelopes.
        entry = rig.earner_svc.submit_earned(
            payer_compositor=rig.payer_compositor.pubkey_hex,
            payer_peer_id=rig.payer_bus.peer_id,
            work_item_id="never-seen",
            icp_envelope_hash="ff" * 32,
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        time.sleep(0.3)
        assert not rig.earner_ledger.get_entry(entry.entry_id).settled
        assert rig.payer_ledger.get_entry(entry.entry_id) is None
    finally:
        rig.stop()


def test_envelope_hash_mismatch_rejected(tmp_path):
    """
    Earner submits an entry whose icp_envelope_hash doesn't match what
    the payer recorded for that work_item_id.
    """
    rig = _make_pair(tmp_path)
    try:
        rig.payer_envelopes["w"] = "aa" * 32  # what payer knows
        entry = rig.earner_svc.submit_earned(
            payer_compositor=rig.payer_compositor.pubkey_hex,
            payer_peer_id=rig.payer_bus.peer_id,
            work_item_id="w",
            icp_envelope_hash="bb" * 32,  # what earner claims — mismatch
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        time.sleep(0.3)
        assert not rig.earner_ledger.get_entry(entry.entry_id).settled
        assert rig.payer_ledger.get_entry(entry.entry_id) is None
    finally:
        rig.stop()


def test_misrouted_entry_ignored(tmp_path):
    """
    An entry whose from_compositor is some THIRD party arrives at our
    payer node. We are not the payer for that entry — drop it.
    """
    rig = _make_pair(tmp_path)
    try:
        # Build a synthetic entry where from_compositor is NOT our payer.
        rig.payer_envelopes["w"] = "11" * 32
        # Forge an entry from earner's perspective directed at "stranger"
        # rather than our payer.
        stranger = _compositor(tmp_path, "stranger")
        entry = rig.earner_ledger.create_entry(
            from_compositor=stranger.pubkey_hex,  # ← not us
            to_compositor=rig.earner_compositor.pubkey_hex,
            amount=1.0, work_item_id="w",
            icp_envelope_hash="11" * 32,
            model_identifier="mock", tokens_out=10, duration_ms=10,
        )
        entry = rig.earner_ledger.sign_as_earner(entry)
        rig.payer_bus.inject(_Incoming(
            sender_peer_id=rig.earner_bus.peer_id,
            sender_pubkey=rig.earner_compositor.pubkey_hex,
            message_type=EARNER_SIGNED_TYPE,
            payload=json.dumps(entry.to_dict()).encode("utf-8"),
        ))
        time.sleep(0.3)
        # Payer didn't sign anything.
        assert rig.payer_ledger.get_entry(entry.entry_id) is None
        # Payer sent zero cosigned replies.
        assert not any(
            mt == PAYER_COSIGNED_TYPE for (_, mt, _) in rig.payer_bus.sent
        )
    finally:
        rig.stop()


def test_forged_earner_signature_rejected(tmp_path):
    """
    Attacker rebuilds an entry with a different amount but the same
    earner signature — verify_earner_signature catches the canonical
    bytes mismatch and the payer drops the entry.
    """
    rig = _make_pair(tmp_path)
    try:
        rig.payer_envelopes["w"] = "22" * 32
        legit = rig.earner_ledger.create_entry(
            from_compositor=rig.payer_compositor.pubkey_hex,
            to_compositor=rig.earner_compositor.pubkey_hex,
            amount=1.0, work_item_id="w",
            icp_envelope_hash="22" * 32,
            model_identifier="mock", tokens_out=10, duration_ms=10,
        )
        legit = rig.earner_ledger.sign_as_earner(legit)
        # Tamper post-sign.
        forged = LedgerEntry(**legit.to_dict())
        forged.amount_credits = 999.0  # but to_signature is for amount=1.0

        rig.payer_bus.inject(_Incoming(
            sender_peer_id=rig.earner_bus.peer_id,
            sender_pubkey=rig.earner_compositor.pubkey_hex,
            message_type=EARNER_SIGNED_TYPE,
            payload=json.dumps(forged.to_dict()).encode("utf-8"),
        ))
        time.sleep(0.3)
        assert rig.payer_ledger.get_entry(forged.entry_id) is None
    finally:
        rig.stop()


def test_payer_cosigned_with_forged_payer_signature_rejected(tmp_path):
    """
    Earner side: a "payer_cosigned" reply arrives where the payer
    signature doesn't verify (e.g. replay from an attacker that didn't
    actually have the payer's key). apply_cosigned_entry refuses.
    """
    rig = _make_pair(tmp_path)
    try:
        # Skip the protocol; build an entry directly.
        rig.payer_envelopes["w"] = "33" * 32
        entry = rig.earner_ledger.create_entry(
            from_compositor=rig.payer_compositor.pubkey_hex,
            to_compositor=rig.earner_compositor.pubkey_hex,
            amount=1.0, work_item_id="w",
            icp_envelope_hash="33" * 32,
            model_identifier="mock", tokens_out=10, duration_ms=10,
        )
        entry = rig.earner_ledger.sign_as_earner(entry)
        # Forge a payer signature: random 64 bytes.
        entry.from_signature = secrets.token_hex(64)

        rig.earner_bus.inject(_Incoming(
            sender_peer_id=rig.payer_bus.peer_id,
            sender_pubkey=rig.payer_compositor.pubkey_hex,
            message_type=PAYER_COSIGNED_TYPE,
            payload=json.dumps(entry.to_dict()).encode("utf-8"),
        ))
        time.sleep(0.3)
        # Entry stayed unsettled on earner.
        local = rig.earner_ledger.get_entry(entry.entry_id)
        assert local is not None  # earner already saved it via sign_as_earner
        assert not local.settled, "earner accepted forged payer cosignature"
    finally:
        rig.stop()


# ======================================================================
# Defensive
# ======================================================================

def test_malformed_payload_does_not_crash_loop(tmp_path):
    """
    Garbage JSON / wrong shape must not kill the receive thread. The
    service logs and keeps going — a subsequent legit message still
    settles.
    """
    rig = _make_pair(tmp_path)
    try:
        # Garbage.
        rig.payer_bus.inject(_Incoming(
            sender_peer_id=rig.earner_bus.peer_id,
            sender_pubkey=rig.earner_compositor.pubkey_hex,
            message_type=EARNER_SIGNED_TYPE,
            payload=b"\xff\xff not json",
        ))
        # Wrong-shape JSON (missing required fields).
        rig.payer_bus.inject(_Incoming(
            sender_peer_id=rig.earner_bus.peer_id,
            sender_pubkey=rig.earner_compositor.pubkey_hex,
            message_type=EARNER_SIGNED_TYPE,
            payload=b'{"hello": "world"}',
        ))

        # Then a legitimate submission.
        rig.payer_envelopes["w"] = "44" * 32
        entry = rig.earner_svc.submit_earned(
            payer_compositor=rig.payer_compositor.pubkey_hex,
            payer_peer_id=rig.payer_bus.peer_id,
            work_item_id="w",
            icp_envelope_hash="44" * 32,
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        assert _wait_until(
            lambda: rig.earner_ledger.get_entry(entry.entry_id).settled,
            timeout_s=2.0,
        ), "service crashed after malformed payload"
    finally:
        rig.stop()


def test_send_failure_leaves_local_state_consistent(tmp_path):
    """
    If the underlying send fails (peer offline), the earner keeps the
    half-signed entry locally and submit_earned returns it. No
    double-counting on retry: a fresh submit_earned for the same work
    item creates a new entry_id.
    """
    rig = _make_pair(tmp_path)
    try:
        rig.earner_bus.fail_send = True
        rig.payer_envelopes["w"] = "55" * 32

        e1 = rig.earner_svc.submit_earned(
            payer_compositor=rig.payer_compositor.pubkey_hex,
            payer_peer_id=rig.payer_bus.peer_id,
            work_item_id="w",
            icp_envelope_hash="55" * 32,
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        # Earner saved its own half-signed copy. settled is False.
        local = rig.earner_ledger.get_entry(e1.entry_id)
        assert local is not None and not local.settled

        # Retry — fresh entry_id, payer never received first one.
        rig.earner_bus.fail_send = False
        e2 = rig.earner_svc.submit_earned(
            payer_compositor=rig.payer_compositor.pubkey_hex,
            payer_peer_id=rig.payer_bus.peer_id,
            work_item_id="w",
            icp_envelope_hash="55" * 32,
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        assert e1.entry_id != e2.entry_id

        assert _wait_until(
            lambda: rig.earner_ledger.get_entry(e2.entry_id).settled,
        )
        # Balance reflects only the settled retry, not the orphan.
        assert rig.earner_ledger.get_balance(rig.payer_compositor.pubkey_hex) == 1.0
    finally:
        rig.stop()


def test_lifecycle_start_stop_idempotent(tmp_path):
    """start() while already running is a no-op; stop() while not
    running is a no-op. Repeated calls don't leak threads."""
    rig = _make_pair(tmp_path)
    try:
        before = rig.payer_svc.is_running()
        rig.payer_svc.start()  # already running
        assert rig.payer_svc.is_running() == before
        rig.payer_svc.stop()
        rig.payer_svc.stop()  # second stop must not raise
        assert not rig.payer_svc.is_running()
    finally:
        rig.stop()


# Reference unused import so static-checkers don't trim it from the
# test bench. canonical_sign_bytes / compute_task_cost are part of the
# public surface settlement uses internally; importing them here keeps
# the import graph explicit for future tests.
_ = canonical_sign_bytes
_ = compute_task_cost
_ = pytest
