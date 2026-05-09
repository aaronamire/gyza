"""
Phase 3 §6 #25 — bilateral ledger reconciliation RPC tests.

What this exercises:

  * The two new wire types (request / response) over a fake message bus.
  * Pagination: a multi-page reconciliation against a peer with a
    larger ledger than fits in one page.
  * Bucketing: agreed / disputed / missing_ours / missing_theirs
    correctness under each scenario.
  * Reputation policy: ``record_dispute`` fires for each entry in
    ``disputed`` and for nothing else (NOT for missing_*).
  * Hostile peer guards: misrouted responses (different
    from_compositor than the peer we asked), unsolicited responses
    (request_id we didn't issue), page-cap-exceeded.
  * Edge cases: self-reconcile, timeout, missing peer_id.

We don't stand up a real daemon — the existing
test_netd_client.py::test_message_send_subscribe_two_daemons proves
the bus carries arbitrary frames Python ↔ Go ↔ Python. This file
targets the protocol layer.

Pattern: every test uses ``_make_pair`` which builds two ledgers,
two _FakeBus instances wired together, and two LedgerSettlementService
instances sharing a single in-process pub/sub. Tests then mutate the
underlying SQLite directly when they need to forge a divergent state
(otherwise both ledgers would always agree because the cosign flow
produces byte-identical entries on both sides).
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue

import pytest

from gyza.economy.ledger import ComputeLedger
from gyza.economy.settlement import (
    LEDGER_RECONCILE_REQUEST_TYPE,
    LEDGER_RECONCILE_RESPONSE_TYPE,
    LedgerSettlementService,
    ReconcileResult,
)
from gyza.identity import LocalCompositor


# ======================================================================
# Test doubles
# ======================================================================

@dataclass
class _Incoming:
    sender_peer_id: str
    sender_pubkey: str
    message_type: str
    payload: bytes
    timestamp_ns: int = 0


class _FakeBus:
    """In-process pub/sub. ``connect`` wires two buses bidirectionally
    so a send to ``other.peer_id`` lands on ``other``'s subscription
    stream. Multi-bus topologies (3+ peers) are built by chaining
    ``connect`` pairs."""

    def __init__(self, peer_id: str, sender_pubkey: str):
        self.peer_id = peer_id
        self.sender_pubkey = sender_pubkey
        self._queue: Queue = Queue()
        self._peers: dict[str, "_FakeBus"] = {}
        self._closed = threading.Event()
        self.sent: list[tuple[str, str, bytes]] = []
        self.fail_send = False

    def connect(self, other: "_FakeBus") -> None:
        self._peers[other.peer_id] = other
        other._peers[self.peer_id] = self

    def send_message(self, peer_id, message_type, payload):
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

    def inject(self, msg) -> None:
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


class _StubReputation:
    """Records record_dispute / record_success calls so tests can
    assert on counts. Uses lists rather than counters so test code can
    inspect the order, too — useful when we want to verify "exactly N
    disputes fired and they were all against peer X"."""

    def __init__(self):
        self.disputes: list[str] = []
        self.successes: list[str] = []
        self.failures: list[str] = []
        self._lock = threading.Lock()

    def record_dispute(self, peer: str) -> None:
        with self._lock:
            self.disputes.append(peer)

    def record_success(self, peer: str) -> None:
        with self._lock:
            self.successes.append(peer)

    def record_failure(self, peer: str) -> None:
        with self._lock:
            self.failures.append(peer)


@dataclass
class _Pair:
    a_compositor: LocalCompositor
    a_ledger: ComputeLedger
    a_bus: _FakeBus
    a_svc: LedgerSettlementService
    a_rep: _StubReputation

    b_compositor: LocalCompositor
    b_ledger: ComputeLedger
    b_bus: _FakeBus
    b_svc: LedgerSettlementService
    b_rep: _StubReputation

    def stop(self) -> None:
        self.a_svc.stop()
        self.b_svc.stop()
        self.a_bus.close()
        self.b_bus.close()


def _make_compositor(tmp_path: Path, name: str) -> LocalCompositor:
    p = tmp_path / f"{name}.key"
    p.write_bytes(secrets.token_bytes(32))
    p.chmod(0o600)
    return LocalCompositor(str(p))


def _make_pair(tmp_path: Path) -> _Pair:
    a = _make_compositor(tmp_path, "a")
    b = _make_compositor(tmp_path, "b")
    a_l = ComputeLedger(a, str(tmp_path / "a.db"))
    b_l = ComputeLedger(b, str(tmp_path / "b.db"))
    a_bus = _FakeBus("peer-a", a.pubkey_hex)
    b_bus = _FakeBus("peer-b", b.pubkey_hex)
    a_bus.connect(b_bus)
    a_rep = _StubReputation()
    b_rep = _StubReputation()
    a_svc = LedgerSettlementService(
        ledger=a_l, netd=a_bus,
        envelope_resolver=lambda _wid: None,
        reputation_store=a_rep,
    )
    b_svc = LedgerSettlementService(
        ledger=b_l, netd=b_bus,
        envelope_resolver=lambda _wid: None,
        reputation_store=b_rep,
    )
    a_svc.start()
    b_svc.start()
    return _Pair(
        a, a_l, a_bus, a_svc, a_rep,
        b, b_l, b_bus, b_svc, b_rep,
    )


def _settled_pair_entry(
    a_l: ComputeLedger, b_l: ComputeLedger,
    *, payer: LocalCompositor, earner: LocalCompositor,
    amount: float = 1.0,
    work_item_id: str | None = None,
) -> str:
    """
    Forge a SETTLED entry on both ledgers without round-tripping the
    settlement service. Both ledgers end up with byte-identical
    cosigned entries — the canonical "agreed" baseline.

    Returns the entry_id.
    """
    if work_item_id is None:
        work_item_id = "w-" + secrets.token_hex(4)
    # Earner's ledger is the to_compositor — it constructs and signs
    # first. Then payer's ledger receives + cosigns. Both stay in lock
    # step because apply_cosigned_entry verifies and persists.
    earner_l = a_l if earner.pubkey_hex == a_l.compositor_pubkey else b_l
    payer_l = a_l if payer.pubkey_hex == a_l.compositor_pubkey else b_l

    e = earner_l.create_entry(
        from_compositor=payer.pubkey_hex,
        to_compositor=earner.pubkey_hex,
        amount=amount,
        work_item_id=work_item_id,
        icp_envelope_hash="ab" * 32,
        model_identifier="mock",
        tokens_out=10,
        duration_ms=10,
    )
    e = earner_l.sign_as_earner(e)
    e = payer_l.sign_as_payer(e)
    # apply_cosigned_entry persists on payer side; for the earner,
    # we apply manually to lift them to "settled".
    earner_l.apply_cosigned_entry(e)
    return e.entry_id


# ======================================================================
# Happy path
# ======================================================================

def test_reconcile_all_agreed(tmp_path):
    """Three settled entries shared between A and B; reconciliation
    classifies all three as agreed and bumps no reputation."""
    rig = _make_pair(tmp_path)
    try:
        ids = [
            _settled_pair_entry(
                rig.a_ledger, rig.b_ledger,
                payer=rig.a_compositor, earner=rig.b_compositor,
                amount=float(i + 1),
            )
            for i in range(3)
        ]
        result: ReconcileResult = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
        )
        assert result.error is None
        assert sorted(result.agreed) == sorted(ids)
        assert result.disputed == []
        assert result.missing_ours == []
        assert result.missing_theirs == []
        # No disputes recorded against B.
        assert rig.a_rep.disputes == []
    finally:
        rig.stop()


def test_reconcile_missing_theirs_no_dispute(tmp_path):
    """A has 2 entries, B has 1 — A reconciles, sees missing_theirs=1.
    No reputation hit (could be benign pruning)."""
    rig = _make_pair(tmp_path)
    try:
        shared = _settled_pair_entry(
            rig.a_ledger, rig.b_ledger,
            payer=rig.a_compositor, earner=rig.b_compositor,
        )
        # Add an extra entry only on A. Direct INSERT bypasses the
        # cosign flow (which would propagate to B). settled=1 keeps
        # it out of "unsettled" buckets.
        _direct_insert(
            rig.a_ledger,
            entry_id="extra-only-on-a",
            from_compositor=rig.a_compositor.pubkey_hex,
            to_compositor=rig.b_compositor.pubkey_hex,
        )
        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
        )
        assert result.error is None
        assert shared in result.agreed
        assert "extra-only-on-a" in result.missing_theirs
        assert result.disputed == []
        assert rig.a_rep.disputes == []
    finally:
        rig.stop()


def test_reconcile_missing_ours_no_dispute(tmp_path):
    """B has 2 entries (its private extra), A has 1. A reconciles →
    sees missing_ours=1. No reputation hit."""
    rig = _make_pair(tmp_path)
    try:
        shared = _settled_pair_entry(
            rig.a_ledger, rig.b_ledger,
            payer=rig.a_compositor, earner=rig.b_compositor,
        )
        # Insert on B only, again direct.
        _direct_insert(
            rig.b_ledger,
            entry_id="extra-only-on-b",
            from_compositor=rig.a_compositor.pubkey_hex,
            to_compositor=rig.b_compositor.pubkey_hex,
        )
        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
        )
        assert result.error is None
        assert shared in result.agreed
        assert "extra-only-on-b" in result.missing_ours
        assert result.disputed == []
        assert rig.a_rep.disputes == []
    finally:
        rig.stop()


def test_reconcile_disputed_bumps_reputation(tmp_path):
    """A and B both have entry X but B's amount diverges. A's
    reconcile classifies X as disputed and fires record_dispute(B)
    once per disputed entry."""
    rig = _make_pair(tmp_path)
    try:
        eid = _settled_pair_entry(
            rig.a_ledger, rig.b_ledger,
            payer=rig.a_compositor, earner=rig.b_compositor,
            amount=1.0,
        )
        # Mutate B's view of the same entry. Direct UPDATE ignores
        # signatures — exactly the scenario reconcile is designed to
        # surface.
        rig.b_ledger._conn().execute(
            "UPDATE ledger_entries SET amount_credits=? WHERE entry_id=?",
            (999.0, eid),
        )
        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
        )
        assert result.error is None
        assert eid in result.disputed
        assert result.agreed == []
        # Exactly one dispute, exactly against B.
        assert rig.a_rep.disputes == [rig.b_compositor.pubkey_hex]
    finally:
        rig.stop()


# ======================================================================
# Pagination
# ======================================================================

def test_reconcile_paginates_when_history_exceeds_page_size(tmp_path):
    """A and B share 12 settled entries; page_size=5 forces three
    round-trips (5, 5, 2). All 12 resolve as agreed."""
    rig = _make_pair(tmp_path)
    try:
        ids = []
        for i in range(12):
            ids.append(_settled_pair_entry(
                rig.a_ledger, rig.b_ledger,
                payer=rig.a_compositor, earner=rig.b_compositor,
                amount=float(i + 1),
            ))
            # Force monotonic created_at_ns so the lex cursor advances
            # cleanly. With nanosecond resolution this is usually
            # automatic, but a tight loop on a fast machine can produce
            # ties — defensive sleep keeps the test deterministic.
            time.sleep(0.0005)

        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
            page_size=5,
        )
        assert result.error is None
        assert result.pages == 3
        assert result.entries_received == 12
        assert sorted(result.agreed) == sorted(ids)
    finally:
        rig.stop()


def test_reconcile_advances_cursor_strictly(tmp_path):
    """After one full page, the cursor advance is strict-greater so
    re-issuing with that cursor returns the NEXT entries, not the
    one we already saw. Indirectly tested by pagination above; this
    test asserts no entry was double-counted."""
    rig = _make_pair(tmp_path)
    try:
        ids = []
        for i in range(7):
            ids.append(_settled_pair_entry(
                rig.a_ledger, rig.b_ledger,
                payer=rig.a_compositor, earner=rig.b_compositor,
                amount=float(i + 1),
            ))
            time.sleep(0.0005)
        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
            page_size=3,
        )
        assert result.error is None
        # 7 entries / 3 per page → ceil(7/3) = 3 pages.
        assert result.pages == 3
        # No duplicates.
        assert len(set(result.agreed)) == len(result.agreed) == 7
    finally:
        rig.stop()


# ======================================================================
# Hostile / malformed inputs
# ======================================================================

def test_reconcile_response_with_wrong_from_compositor_dropped(tmp_path):
    """
    A registers a pending request and sends to B. We then inject a
    response with the same request_id but from_compositor=C (a third
    party). The handler MUST drop it without signaling A's waiter,
    so the legitimate B response (or the timeout) wins.

    This tests the cross-peer injection guard.
    """
    rig = _make_pair(tmp_path)
    try:
        # Pre-stage a settled entry so B's legitimate response has
        # something to return.
        _settled_pair_entry(
            rig.a_ledger, rig.b_ledger,
            payer=rig.a_compositor, earner=rig.b_compositor,
        )
        # Build the third party.
        c = _make_compositor(tmp_path, "c")

        # Block B's legitimate replies so only our injection can win.
        rig.b_bus.fail_send = True

        # Spawn the request in a thread; meanwhile, we'll snoop the
        # pending request_id via the most recent send to B and inject
        # a forged response.
        result_holder: list[ReconcileResult] = []

        def _go():
            r = rig.a_svc.request_reconciliation(
                peer_compositor=rig.b_compositor.pubkey_hex,
                peer_id=rig.b_bus.peer_id,
                page_timeout_s=0.5,
            )
            result_holder.append(r)

        t = threading.Thread(target=_go, daemon=True)
        t.start()

        # Wait for A to actually send the request frame.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if any(mt == LEDGER_RECONCILE_REQUEST_TYPE for (_, mt, _) in rig.a_bus.sent):
                break
            time.sleep(0.01)
        # Decode the request_id A used.
        req_payload = next(
            payload for (_, mt, payload) in rig.a_bus.sent
            if mt == LEDGER_RECONCILE_REQUEST_TYPE
        )
        req_id = json.loads(req_payload.decode("utf-8"))["request_id"]

        # Inject a forged response: claims to be from C, not B.
        forged = json.dumps({
            "request_id": req_id,
            "from_compositor": c.pubkey_hex,
            "entries": [],
            "cursor_timestamp_ns": 0,
            "cursor_entry_id": "",
            "has_more": False,
        }).encode("utf-8")
        rig.a_bus.inject(_Incoming(
            sender_peer_id="peer-c",
            sender_pubkey=c.pubkey_hex,
            message_type=LEDGER_RECONCILE_RESPONSE_TYPE,
            payload=forged,
        ))

        t.join(timeout=2.0)
        assert result_holder, "request_reconciliation did not return"
        # The forged response was dropped — A's call timed out instead
        # of accepting C's bogus empty page as authoritative.
        assert result_holder[0].error == "timeout"
    finally:
        rig.stop()


def test_reconcile_response_for_unknown_request_id_dropped(tmp_path):
    """A receives a response for a request_id it never sent. The
    handler drops silently — no exception, nothing to assert on the
    happy paths since there's no pending state to corrupt."""
    rig = _make_pair(tmp_path)
    try:
        forged = json.dumps({
            "request_id": "totally-fabricated",
            "from_compositor": rig.b_compositor.pubkey_hex,
            "entries": [],
            "cursor_timestamp_ns": 0,
            "cursor_entry_id": "",
            "has_more": False,
        }).encode("utf-8")
        rig.a_bus.inject(_Incoming(
            sender_peer_id=rig.b_bus.peer_id,
            sender_pubkey=rig.b_compositor.pubkey_hex,
            message_type=LEDGER_RECONCILE_RESPONSE_TYPE,
            payload=forged,
        ))
        # Give the receive loop a moment to chew on it.
        time.sleep(0.2)
        # Sanity: a follow-up legitimate reconcile still works.
        _settled_pair_entry(
            rig.a_ledger, rig.b_ledger,
            payer=rig.a_compositor, earner=rig.b_compositor,
        )
        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
        )
        assert result.error is None
        assert len(result.agreed) == 1
    finally:
        rig.stop()


def test_reconcile_request_for_someone_else_ignored(tmp_path):
    """
    B receives a request whose ``for_peer`` is some third party. B's
    handler must NOT reply — replying would leak data about its
    pairwise ledgers with strangers.
    """
    rig = _make_pair(tmp_path)
    try:
        c = _make_compositor(tmp_path, "c")
        bogus = json.dumps({
            "request_id": "abc",
            "from_compositor": rig.a_compositor.pubkey_hex,
            "for_peer": c.pubkey_hex,  # not B!
            "since_timestamp_ns": 0,
            "since_entry_id": "",
            "max_entries": 100,
        }).encode("utf-8")
        sent_before = len(rig.b_bus.sent)
        rig.b_bus.inject(_Incoming(
            sender_peer_id=rig.a_bus.peer_id,
            sender_pubkey=rig.a_compositor.pubkey_hex,
            message_type=LEDGER_RECONCILE_REQUEST_TYPE,
            payload=bogus,
        ))
        time.sleep(0.2)
        # No response was sent.
        sent_after = len(rig.b_bus.sent)
        assert sent_after == sent_before
    finally:
        rig.stop()


def test_reconcile_self_short_circuits(tmp_path):
    """Reconciling against your own pubkey is a programming error.
    The method short-circuits without touching the bus."""
    rig = _make_pair(tmp_path)
    try:
        sent_before = len(rig.a_bus.sent)
        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.a_compositor.pubkey_hex,
            peer_id=rig.a_bus.peer_id,
        )
        assert result.error == "cannot reconcile with self"
        assert len(rig.a_bus.sent) == sent_before
    finally:
        rig.stop()


def test_reconcile_timeout_when_peer_doesnt_respond(tmp_path):
    """B's bus is configured to drop sends — A's request goes out but
    no response ever returns. A's reconcile times out after page_timeout_s."""
    rig = _make_pair(tmp_path)
    try:
        # Disconnect A→B so the request frame is silently dropped.
        rig.a_bus._peers.pop(rig.b_bus.peer_id, None)
        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
            page_timeout_s=0.3,
        )
        # send_message returned False because the peer is unreachable;
        # implementation surfaces this as "send_failed" rather than
        # waiting for the timeout.
        assert result.error in ("send_failed", "timeout")
        assert result.pages == 0
    finally:
        rig.stop()


def test_reconcile_page_cap_exceeded_error(tmp_path):
    """
    When the legitimate ledger has more pages than ``max_pages`` allows,
    the loop bails with ``error="page_cap_exceeded"`` rather than
    silently returning a truncated agreed-list. We force this by
    seeding 5 entries and asking for max_pages=2 with page_size=1, so
    the loop exhausts the page cap before the third entry.
    """
    rig = _make_pair(tmp_path)
    try:
        for i in range(5):
            _settled_pair_entry(
                rig.a_ledger, rig.b_ledger,
                payer=rig.a_compositor, earner=rig.b_compositor,
                amount=float(i + 1),
            )
            time.sleep(0.0005)
        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
            page_size=1,
            max_pages=2,
        )
        assert result.error == "page_cap_exceeded"
        # Two pages of 1 entry each were processed.
        assert result.pages == 2
        assert result.entries_received == 2
    finally:
        rig.stop()


def test_concurrent_reconciles_dont_cross_wires(tmp_path):
    """
    Two distinct request_reconciliation calls (from different threads,
    same source A) must not confuse responses. We use two peers (B and
    C) so each call has its own peer_pubkey expected on responses; a
    bug in the request_id correlation would surface as one of the
    calls returning the OTHER peer's entries.
    """
    a = _make_compositor(tmp_path, "a")
    b = _make_compositor(tmp_path, "b")
    c = _make_compositor(tmp_path, "c")

    a_l = ComputeLedger(a, str(tmp_path / "a.db"))
    b_l = ComputeLedger(b, str(tmp_path / "b.db"))
    c_l = ComputeLedger(c, str(tmp_path / "c.db"))

    a_bus = _FakeBus("peer-a", a.pubkey_hex)
    b_bus = _FakeBus("peer-b", b.pubkey_hex)
    c_bus = _FakeBus("peer-c", c.pubkey_hex)
    a_bus.connect(b_bus)
    a_bus.connect(c_bus)

    a_rep = _StubReputation()
    a_svc = LedgerSettlementService(
        ledger=a_l, netd=a_bus,
        envelope_resolver=lambda _wid: None,
        reputation_store=a_rep,
    )
    b_svc = LedgerSettlementService(
        ledger=b_l, netd=b_bus,
        envelope_resolver=lambda _wid: None,
    )
    c_svc = LedgerSettlementService(
        ledger=c_l, netd=c_bus,
        envelope_resolver=lambda _wid: None,
    )
    a_svc.start(); b_svc.start(); c_svc.start()
    try:
        # Set up distinct pairwise ledger states.
        b_only_id = _settled_pair_entry(a_l, b_l, payer=a, earner=b, amount=1.0)
        c_only_id = _settled_pair_entry(a_l, c_l, payer=a, earner=c, amount=2.0)

        results: dict[str, ReconcileResult] = {}

        def _recon(name: str, peer: LocalCompositor, peer_bus: _FakeBus):
            results[name] = a_svc.request_reconciliation(
                peer_compositor=peer.pubkey_hex,
                peer_id=peer_bus.peer_id,
            )

        t1 = threading.Thread(target=_recon, args=("b", b, b_bus), daemon=True)
        t2 = threading.Thread(target=_recon, args=("c", c, c_bus), daemon=True)
        t1.start(); t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert results["b"].error is None
        assert results["c"].error is None
        # Each reconciliation saw ONLY its peer's entries.
        assert results["b"].agreed == [b_only_id]
        assert results["c"].agreed == [c_only_id]
        # No cross-contamination of "missing_*" buckets either.
        assert results["b"].missing_ours == []
        assert results["b"].missing_theirs == []
        assert results["c"].missing_ours == []
        assert results["c"].missing_theirs == []
    finally:
        a_svc.stop(); b_svc.stop(); c_svc.stop()
        a_bus.close(); b_bus.close(); c_bus.close()


def test_reconcile_no_disputes_means_no_reputation_change(tmp_path):
    """Belt-and-suspenders: a reconcile with only missing_* (no
    disputed) leaves the reputation store untouched. CLAUDE.md
    explicitly says not to penalize a peer for pruning."""
    rig = _make_pair(tmp_path)
    try:
        _settled_pair_entry(
            rig.a_ledger, rig.b_ledger,
            payer=rig.a_compositor, earner=rig.b_compositor,
        )
        _direct_insert(
            rig.a_ledger,
            entry_id="ours-only",
            from_compositor=rig.a_compositor.pubkey_hex,
            to_compositor=rig.b_compositor.pubkey_hex,
        )
        _direct_insert(
            rig.b_ledger,
            entry_id="theirs-only",
            from_compositor=rig.a_compositor.pubkey_hex,
            to_compositor=rig.b_compositor.pubkey_hex,
        )
        result = rig.a_svc.request_reconciliation(
            peer_compositor=rig.b_compositor.pubkey_hex,
            peer_id=rig.b_bus.peer_id,
        )
        assert result.error is None
        assert "ours-only" in result.missing_theirs
        assert "theirs-only" in result.missing_ours
        # Critical assertion — nobody got penalized.
        assert rig.a_rep.disputes == []
        assert rig.b_rep.disputes == []
    finally:
        rig.stop()


# ======================================================================
# Helpers
# ======================================================================

def _direct_insert(
    ledger: ComputeLedger,
    *,
    entry_id: str,
    from_compositor: str,
    to_compositor: str,
    amount: float = 1.0,
    work_item_id: str | None = None,
) -> None:
    """
    INSERT a synthetic ledger row bypassing the cosign flow. Used to
    create "we have it but they don't" scenarios that the legitimate
    settlement protocol cannot produce — both ledgers are otherwise
    kept in lockstep by apply_cosigned_entry.

    The signatures are deliberately empty: the row is unsigned. That
    matters for ``disputed`` (different sigs would diff) but not for
    ``missing_*`` which compare on entry_id only.
    """
    if work_item_id is None:
        work_item_id = "w-" + entry_id[:8]
    ledger._conn().execute(
        """
        INSERT INTO ledger_entries (
            entry_id, from_compositor, to_compositor, amount_credits,
            work_item_id, icp_envelope_hash, model_identifier,
            tokens_out, duration_ms, created_at_ns,
            from_signature, to_signature, settled
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_id, from_compositor, to_compositor, amount,
            work_item_id, "ee" * 32, "mock",
            10, 10, time.time_ns(),
            "", "", 1,
        ),
    )
