"""
Phase 3 Session 8.5 — reputation feedback loop.

Two layers tested:

  1. ``ReputationStore`` primitive: EWMA correctness, persistence,
     boundary conditions (clamping, neutral default, alpha range
     validation), thread-safety on concurrent updates.

  2. Integration with the runner and settlement service: successful
     completions bump the local agent's score; protocol-level
     rejections (forged sig, envelope mismatch, amount tolerance,
     misroute) bump the offending peer's score DOWN as a dispute;
     successful settlements bump the counterparty's score UP.

Settlement integration tests reuse the ``_FakeBus`` rig from
test_settlement.py to avoid standing up daemons — same approach,
extended with a ReputationStore.
"""
from __future__ import annotations

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
)
from gyza.economy.reputation import ReputationStore
from gyza.economy.settlement import (
    EARNER_SIGNED_TYPE,
    PAYER_COSIGNED_TYPE,
    LedgerSettlementService,
)
from gyza.identity import LocalCompositor


# ----------------------------------------------------------------------
# 1. Primitive: ReputationStore
# ----------------------------------------------------------------------

def test_unknown_pubkey_returns_neutral(tmp_path):
    s = ReputationStore(str(tmp_path / "r.db"))
    assert s.get("never-seen") == 0.5
    assert s.event_count("never-seen") == 0


def test_ewma_success_pulls_toward_one(tmp_path):
    """Repeated successes from the neutral start (0.5) push the score
    monotonically up but never above 1.0."""
    s = ReputationStore(str(tmp_path / "r.db"), alpha=0.1)
    pk = "agent-a"
    last = s.get(pk)
    for _ in range(50):
        new = s.record_success(pk)
        assert new > last, "monotonic increase expected"
        assert new <= 1.0, "score must clamp to 1.0"
        last = new
    # After 50 successes with alpha=0.1 we should be very close to 1.
    assert s.get(pk) > 0.99


def test_ewma_failure_pulls_toward_zero(tmp_path):
    s = ReputationStore(str(tmp_path / "r.db"), alpha=0.1)
    pk = "agent-b"
    last = s.get(pk)
    for _ in range(50):
        new = s.record_failure(pk)
        assert new < last
        assert new >= 0.0
        last = new
    # _OUTCOME_FAILURE = -0.5 → outcome_norm = 0.25, so steady-state
    # under endless failures is 0.25, not 0.0.
    assert s.get(pk) < 0.30


def test_dispute_weighs_more_than_failure(tmp_path):
    """A single dispute pulls a perfect score down further than a
    single failure does. Both peers start at 1.0; the disputed one
    ends lower."""
    s = ReputationStore(str(tmp_path / "r.db"), alpha=0.1)
    fail_pk = "fail"
    disp_pk = "disp"
    # Bring both to ~1.0 with many successes.
    for _ in range(80):
        s.record_success(fail_pk)
        s.record_success(disp_pk)
    s_fail_before = s.get(fail_pk)
    s_disp_before = s.get(disp_pk)
    s.record_failure(fail_pk)
    s.record_dispute(disp_pk)
    delta_fail = s_fail_before - s.get(fail_pk)
    delta_disp = s_disp_before - s.get(disp_pk)
    assert delta_disp > delta_fail, (
        f"dispute should pull score DOWN more than failure: "
        f"failure delta={delta_fail:.4f}, dispute delta={delta_disp:.4f}"
    )


def test_event_count_tracks_updates(tmp_path):
    s = ReputationStore(str(tmp_path / "r.db"))
    pk = "x"
    assert s.event_count(pk) == 0
    s.record_success(pk)
    s.record_failure(pk)
    s.record_dispute(pk)
    assert s.event_count(pk) == 3


def test_persistence_across_instances(tmp_path):
    db = str(tmp_path / "r.db")
    s1 = ReputationStore(db)
    pk = "persistent"
    for _ in range(10):
        s1.record_success(pk)
    score1 = s1.get(pk)
    # New instance pointing at the same DB sees the same score.
    s2 = ReputationStore(db)
    assert abs(s2.get(pk) - score1) < 1e-9
    assert s2.event_count(pk) == 10


def test_reset_clears_pubkey(tmp_path):
    s = ReputationStore(str(tmp_path / "r.db"))
    pk = "z"
    s.record_success(pk)
    assert s.get(pk) > 0.5
    s.reset(pk)
    assert s.get(pk) == 0.5
    assert s.event_count(pk) == 0


def test_alpha_range_validated(tmp_path):
    with pytest.raises(ValueError):
        ReputationStore(str(tmp_path / "r.db"), alpha=0.0)
    with pytest.raises(ValueError):
        ReputationStore(str(tmp_path / "r.db"), alpha=1.0)
    with pytest.raises(ValueError):
        ReputationStore(str(tmp_path / "r.db"), alpha=-0.1)


def test_outcome_range_validated(tmp_path):
    s = ReputationStore(str(tmp_path / "r.db"))
    with pytest.raises(ValueError):
        s._update("x", outcome=2.0)
    with pytest.raises(ValueError):
        s._update("x", outcome=-1.5)


def test_concurrent_updates_no_lost_writes(tmp_path):
    """16 threads each call record_success 50 times. event_count must
    end at exactly 16*50=800 — the lock around _update must serialize
    the read-modify-write so we don't lose increments."""
    s = ReputationStore(str(tmp_path / "r.db"), alpha=0.05)
    pk = "concurrent"
    N_THREADS = 16
    M_PER_THREAD = 50

    def worker():
        for _ in range(M_PER_THREAD):
            s.record_success(pk)

    threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert s.event_count(pk) == N_THREADS * M_PER_THREAD


def test_all_known_orders_by_score_ascending(tmp_path):
    s = ReputationStore(str(tmp_path / "r.db"))
    s.record_success("good")
    s.record_failure("bad")
    s.record_dispute("worst")
    rows = s.all_known()
    keys = [r[0] for r in rows]
    # "worst" should sort first (lowest score).
    assert keys[0] == "worst"
    assert keys[-1] == "good"


# ----------------------------------------------------------------------
# 2. Integration: settlement service
# ----------------------------------------------------------------------
#
# Reuses the same FakeBus pattern as test_settlement.py but with an
# additional ReputationStore wired in. We don't import from
# test_settlement.py because pytest fixtures don't share across files
# without conftest plumbing — duplicating the small fake here is
# cheaper than the abstraction.

@dataclass
class _Incoming:
    sender_peer_id: str
    sender_pubkey: str
    message_type: str
    payload: bytes
    timestamp_ns: int = 0


class _FakeBus:
    def __init__(self, peer_id: str, sender_pubkey: str):
        self.peer_id = peer_id
        self.sender_pubkey = sender_pubkey
        self._queue: Queue = Queue()
        self._peers: dict[str, "_FakeBus"] = {}
        self._closed = threading.Event()
        self.sent: list[tuple[str, str, bytes]] = []

    def connect(self, other: "_FakeBus") -> None:
        self._peers[other.peer_id] = other
        other._peers[self.peer_id] = self

    def send_message(
        self, peer_id: str, message_type: str, payload: bytes,
    ) -> bool:
        self.sent.append((peer_id, message_type, bytes(payload)))
        target = self._peers.get(peer_id)
        if target is None:
            return False
        target._queue.put(_Incoming(
            sender_peer_id=self.peer_id,
            sender_pubkey=self.sender_pubkey,
            message_type=message_type,
            payload=bytes(payload),
        ))
        return True

    def inject(self, msg: _Incoming) -> None:
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


def _compositor(tmp_path: Path, name: str) -> LocalCompositor:
    p = tmp_path / f"{name}.key"
    p.write_bytes(secrets.token_bytes(32))
    p.chmod(0o600)
    return LocalCompositor(str(p))


def _make_pair_with_reputation(tmp_path: Path):
    payer = _compositor(tmp_path, "payer")
    earner = _compositor(tmp_path, "earner")
    payer_l = ComputeLedger(payer, str(tmp_path / "payer.db"))
    earner_l = ComputeLedger(earner, str(tmp_path / "earner.db"))
    payer_bus = _FakeBus("peer-payer", payer.pubkey_hex)
    earner_bus = _FakeBus("peer-earner", earner.pubkey_hex)
    payer_bus.connect(earner_bus)
    payer_envelopes: dict[str, str] = {}
    payer_rep = ReputationStore(str(tmp_path / "payer-rep.db"), alpha=0.1)
    earner_rep = ReputationStore(str(tmp_path / "earner-rep.db"), alpha=0.1)
    payer_svc = LedgerSettlementService(
        ledger=payer_l, netd=payer_bus,
        envelope_resolver=payer_envelopes.get,
        reputation_store=payer_rep,
    )
    earner_svc = LedgerSettlementService(
        ledger=earner_l, netd=earner_bus,
        envelope_resolver=lambda _w: None,
        reputation_store=earner_rep,
    )
    payer_svc.start()
    earner_svc.start()
    return {
        "payer": payer, "earner": earner,
        "payer_l": payer_l, "earner_l": earner_l,
        "payer_bus": payer_bus, "earner_bus": earner_bus,
        "payer_envelopes": payer_envelopes,
        "payer_rep": payer_rep, "earner_rep": earner_rep,
        "payer_svc": payer_svc, "earner_svc": earner_svc,
    }


def _wait_until(predicate, timeout_s: float = 2.0, poll_s: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def test_successful_settlement_bumps_both_reputations(tmp_path):
    rig = _make_pair_with_reputation(tmp_path)
    try:
        envelope_hash = "ab" * 32
        rig["payer_envelopes"]["w-1"] = envelope_hash
        entry = rig["earner_svc"].submit_earned(
            payer_compositor=rig["payer"].pubkey_hex,
            payer_peer_id=rig["payer_bus"].peer_id,
            work_item_id="w-1",
            icp_envelope_hash=envelope_hash,
            model_identifier="mock",
            tokens_out=100, duration_ms=100,
        )
        assert _wait_until(
            lambda: (e := rig["earner_l"].get_entry(entry.entry_id)) is not None and e.settled,
        )
        # Payer's view of earner: bumped UP.
        assert rig["payer_rep"].get(rig["earner"].pubkey_hex) > 0.5
        # Earner's view of payer: bumped UP.
        assert rig["earner_rep"].get(rig["payer"].pubkey_hex) > 0.5
    finally:
        rig["payer_svc"].stop()
        rig["earner_svc"].stop()
        rig["payer_bus"].close()
        rig["earner_bus"].close()


def test_amount_dispute_bumps_earner_reputation_down(tmp_path):
    rig = _make_pair_with_reputation(tmp_path)
    try:
        rig["payer_envelopes"]["w"] = "cd" * 32
        # Earner claims 30 credits when our recompute says 10 (3×, well
        # outside ±20% tolerance).
        rig["earner_svc"].submit_earned(
            payer_compositor=rig["payer"].pubkey_hex,
            payer_peer_id=rig["payer_bus"].peer_id,
            work_item_id="w",
            icp_envelope_hash="cd" * 32,
            model_identifier="mock",
            tokens_out=100, duration_ms=100,
            amount=30.0,
        )
        time.sleep(0.3)
        # Payer disputes — earner's reputation should be lower than neutral.
        assert rig["payer_rep"].get(rig["earner"].pubkey_hex) < 0.5


    finally:
        rig["payer_svc"].stop()
        rig["earner_svc"].stop()
        rig["payer_bus"].close()
        rig["earner_bus"].close()


def test_envelope_hash_mismatch_bumps_dispute(tmp_path):
    rig = _make_pair_with_reputation(tmp_path)
    try:
        rig["payer_envelopes"]["w"] = "aa" * 32  # what payer knows
        rig["earner_svc"].submit_earned(
            payer_compositor=rig["payer"].pubkey_hex,
            payer_peer_id=rig["payer_bus"].peer_id,
            work_item_id="w",
            icp_envelope_hash="bb" * 32,  # mismatch
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        time.sleep(0.3)
        assert rig["payer_rep"].get(rig["earner"].pubkey_hex) < 0.5
    finally:
        rig["payer_svc"].stop()
        rig["earner_svc"].stop()
        rig["payer_bus"].close()
        rig["earner_bus"].close()


def test_unknown_work_item_does_not_dispute(tmp_path):
    """Unknown work_item_id → silently rejected (could be gossip lag,
    not necessarily a protocol violation). Reputation stays neutral."""
    rig = _make_pair_with_reputation(tmp_path)
    try:
        # NOT seeding payer_envelopes.
        rig["earner_svc"].submit_earned(
            payer_compositor=rig["payer"].pubkey_hex,
            payer_peer_id=rig["payer_bus"].peer_id,
            work_item_id="never-seen",
            icp_envelope_hash="ff" * 32,
            model_identifier="mock",
            tokens_out=10, duration_ms=10,
        )
        time.sleep(0.3)
        # Reputation should remain neutral (no dispute recorded).
        assert rig["payer_rep"].get(rig["earner"].pubkey_hex) == 0.5
    finally:
        rig["payer_svc"].stop()
        rig["earner_svc"].stop()
        rig["payer_bus"].close()
        rig["earner_bus"].close()


def test_forged_payer_cosignature_disputes_payer(tmp_path):
    """Earner-side: forged payer cosignature arrives → reputation of
    the (claimed) payer pubkey is bumped down."""
    rig = _make_pair_with_reputation(tmp_path)
    try:
        # Build an entry with a real earner sig, then a forged payer sig.
        entry = rig["earner_l"].create_entry(
            from_compositor=rig["payer"].pubkey_hex,
            to_compositor=rig["earner"].pubkey_hex,
            amount=1.0, work_item_id="w",
            icp_envelope_hash="33" * 32,
            model_identifier="mock", tokens_out=10, duration_ms=10,
        )
        entry = rig["earner_l"].sign_as_earner(entry)
        entry.from_signature = secrets.token_hex(64)  # forge
        import json as _json
        rig["earner_bus"].inject(_Incoming(
            sender_peer_id=rig["payer_bus"].peer_id,
            sender_pubkey=rig["payer"].pubkey_hex,
            message_type=PAYER_COSIGNED_TYPE,
            payload=_json.dumps(entry.to_dict()).encode("utf-8"),
        ))
        time.sleep(0.3)
        assert rig["earner_rep"].get(rig["payer"].pubkey_hex) < 0.5
    finally:
        rig["payer_svc"].stop()
        rig["earner_svc"].stop()
        rig["payer_bus"].close()
        rig["earner_bus"].close()


_ = LedgerEntry  # keep import alive for test_settlement-style assertions
_ = EARNER_SIGNED_TYPE
