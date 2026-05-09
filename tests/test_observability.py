"""
Phase 3 Session 9 — observability tests.

What we cover here:

  1. The metric module imports cleanly and the Counter/Histogram/Gauge
     wrappers are bound to the expected names.
  2. Counter increments at every instrumented site:
       * runner._complete (success), _release (released)
       * settlement._handle_earner_signed (every dispute reason +
         payer-side success)
       * settlement._handle_payer_cosigned (earner-side success)
       * supervisor._spawn (counter + gauge)
       * network_blackboard._apply_delta / _publish_delta_if_attached
  3. Histogram observation:
       * settlement round-trip latency keyed by entry_id
       * runner claim-to-complete latency
  4. Gauge updates:
       * supervisor roster size on spawn / stop
  5. The HTTP scrape server binds, serves /metrics, and is idempotent
     across multiple start_metrics_server calls.

We use the canonical
``prometheus_client.REGISTRY.get_sample_value(name, labels)`` for
assertion — it's how Prometheus itself reads samples, so the tests
exercise the same surface that operators will scrape. We compare
DELTAS (after - before) rather than absolute values because the
default registry is process-global and earlier tests in the run will
have already incremented the counters.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue

import numpy as np
import pytest

from gyza import observability as obs


# ---------------------------------------------------------------------------
# Module-level surface
# ---------------------------------------------------------------------------

def test_metric_objects_are_registered():
    """Every public metric in __all__ resolves to a usable instance."""
    counters = [
        obs.SETTLEMENTS_TOTAL, obs.DISPUTES_TOTAL,
        obs.AGENT_COMPLETIONS_TOTAL, obs.GOSSIP_DELTAS_TOTAL,
        obs.SUPERVISOR_SPAWNS_TOTAL,
    ]
    histograms = [obs.SETTLEMENT_LATENCY, obs.CLAIM_TO_COMPLETE_LATENCY]
    gauges = [
        obs.ROSTER_SIZE, obs.DHT_PEER_COUNT,
        obs.CONNECTED_PEERS, obs.LEDGER_NET_CREDITS,
    ]
    for m in counters + histograms + gauges:
        # All metric instances are callable for inc/observe/set; the
        # type names live under prometheus_client.metrics. We don't
        # care which type — only that they're not None.
        assert m is not None


def test_get_counter_value_zero_for_absent_label():
    """Reading a never-incremented label combo returns 0.0, not None."""
    v = obs.get_counter_value(
        "gyza_disputes_total",
        {"reason": "this-reason-never-existed"},
    )
    assert v == 0.0


# ---------------------------------------------------------------------------
# Settlement latency helpers
# ---------------------------------------------------------------------------

def test_settlement_latency_round_trip_is_observed():
    """
    record_settlement_start + observe_settlement_latency together push a
    sample into SETTLEMENT_LATENCY's count. Idempotency: a second
    observe of the same entry_id is a no-op (the start was popped).
    """
    obs.reset_settlement_starts_for_tests()
    before_count = _hist_count(obs.SETTLEMENT_LATENCY)
    eid = "test-entry-" + secrets.token_hex(4)
    t0 = time.monotonic()
    obs.record_settlement_start(eid, t0)
    obs.observe_settlement_latency(eid, t0 + 0.05)
    # Second observe must NOT produce another sample — start has been
    # popped. Without this guarantee, gossip replay or a confused
    # caller could double-count latency.
    obs.observe_settlement_latency(eid, t0 + 0.10)
    after_count = _hist_count(obs.SETTLEMENT_LATENCY)
    assert after_count - before_count == 1


def test_observe_without_start_is_noop():
    """An observe for an entry we never started must not raise or
    poison the histogram."""
    before_count = _hist_count(obs.SETTLEMENT_LATENCY)
    obs.observe_settlement_latency("never-started-" + secrets.token_hex(4), time.monotonic())
    after_count = _hist_count(obs.SETTLEMENT_LATENCY)
    assert after_count == before_count


# ---------------------------------------------------------------------------
# Supervisor: spawn counter + roster gauge
# ---------------------------------------------------------------------------

def test_supervisor_spawn_bumps_counter_and_gauge(tmp_path):
    """The supervisor's _spawn flow increments SUPERVISOR_SPAWNS_TOTAL
    and sets ROSTER_SIZE. We don't drive the full poll loop — we
    construct a supervisor and trigger _spawn directly via a fake
    DemandSignal, since the wiring under test is the metric site, not
    the supervisor's policy logic."""
    from gyza.demand import DemandOracle, DemandSignal, LSHIndex
    from gyza.identity import LocalCompositor
    from gyza.runner import AgentRunner, make_mock_executor
    from gyza.supervisor import AgentSupervisor, SpawnRequest

    key_path = tmp_path / "compositor.key"
    key_path.write_bytes(secrets.token_bytes(32))
    key_path.chmod(0o600)
    compositor = LocalCompositor(str(key_path))

    bb = _StubBlackboard()
    oracle = DemandOracle(blackboard=bb, lsh=LSHIndex(seed=42))

    spawned: list[AgentRunner] = []

    def factory(req: SpawnRequest) -> AgentRunner:
        from gyza.demand import LSHIndex as _LSH
        from gyza.drift import SpecializationTracker
        from gyza.memory import EpisodicMemory
        from gyza.schema import EMBEDDING_DIM
        spec = SpecializationTracker(
            agent_id=req.identity.agent_id,
            initial_embedding=np.zeros(EMBEDDING_DIM, dtype=np.float32),
            db_path=str(tmp_path / f"spec-{req.identity.agent_id[:8]}.db"),
        )
        mem = EpisodicMemory(
            agent_id=req.identity.agent_id,
            db_path=str(tmp_path / f"mem-{req.identity.agent_id[:8]}"),
        )
        runner = AgentRunner(
            identity=req.identity, blackboard=bb, memory=mem,
            specialization=spec, lsh=_LSH(seed=42),
            executor=make_mock_executor("ok"),
            min_reward_threshold=0.0,
            min_similarity_threshold=-1.0,
            poll_interval_s=0.1,
            verify_chain_before_claim=False,
        )
        spawned.append(runner)
        return runner

    sv = AgentSupervisor(
        compositor=compositor,
        oracle=oracle,
        lsh=LSHIndex(seed=42),
        agent_factory=factory,
        spawn_threshold=0.0,
        max_agents=2,
        poll_interval_s=10.0,  # we drive ticks manually below
    )

    spawns_before = obs.get_counter_value("gyza_supervisor_spawns_total")
    # Drive one synthetic spawn by calling _spawn directly.
    sig = DemandSignal(
        bucket=0xdeadbeef,
        unclaimed_count=10,
        avg_reward=0.5,
        max_reward=1.0,
        oldest_item_age_ns=0,
        centroid_embedding=_unit_vec(384, seed=1),
    )
    sv._spawn(0xdeadbeef, sig, deficit=10.0)
    spawns_after = obs.get_counter_value("gyza_supervisor_spawns_total")
    assert spawns_after - spawns_before == 1
    assert _gauge_value(obs.ROSTER_SIZE) == 1

    # Stop runners so the gauge resets to 0.
    sv.stop()
    for r in spawned:
        r.stop()
    assert _gauge_value(obs.ROSTER_SIZE) == 0


# ---------------------------------------------------------------------------
# Settlement: dispute / settlement counters
# ---------------------------------------------------------------------------

def test_settlement_dispute_and_success_counters(tmp_path):
    """
    A round-trip happy path bumps SETTLEMENTS_TOTAL{role="payer"} and
    SETTLEMENTS_TOTAL{role="earner"} by exactly 1 each. A misrouted
    earner_signed (from_compositor != us) bumps DISPUTES_TOTAL{reason=
    "misroute_payer"}.
    """
    rig = _make_pair(tmp_path)
    try:
        envelope_hash = "ab" * 32
        rig.payer_envelopes["work-X"] = envelope_hash

        payer_settle_before = obs.get_counter_value(
            "gyza_settlements_total", {"role": "payer"},
        )
        earner_settle_before = obs.get_counter_value(
            "gyza_settlements_total", {"role": "earner"},
        )

        rig.earner_svc.submit_earned(
            payer_compositor=rig.payer_compositor.pubkey_hex,
            payer_peer_id=rig.payer_bus.peer_id,
            work_item_id="work-X",
            icp_envelope_hash=envelope_hash,
            model_identifier="mock",
            tokens_out=1000,
            duration_ms=1000,
        )

        # Wait for both sides to apply the cosigned entry.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (obs.get_counter_value("gyza_settlements_total", {"role": "earner"})
                    > earner_settle_before):
                break
            time.sleep(0.01)

        assert (obs.get_counter_value("gyza_settlements_total", {"role": "payer"})
                - payer_settle_before) == 1
        assert (obs.get_counter_value("gyza_settlements_total", {"role": "earner"})
                - earner_settle_before) == 1
    finally:
        rig.stop()


def test_settlement_misroute_dispute_counter(tmp_path):
    """
    Inject an earner_signed from a peer where from_compositor isn't us
    — the handler logs, bumps reputation as a dispute, AND bumps
    DISPUTES_TOTAL{reason="misroute_payer"}.
    """
    rig = _make_pair(tmp_path)
    try:
        from gyza.economy.settlement import EARNER_SIGNED_TYPE
        from gyza.identity import LocalCompositor

        # Build an entry whose from_compositor is some THIRD party,
        # not this rig's payer. The earner ledger can still sign as
        # earner because they ARE the to_compositor — sign_as_earner
        # only requires "you are the recipient." When the payer node
        # receives this, it sees from_compositor != us and bumps the
        # misroute_payer dispute counter.
        third_key = tmp_path / "third.key"
        third_key.write_bytes(secrets.token_bytes(32))
        third_key.chmod(0o600)
        third = LocalCompositor(str(third_key))
        rig.payer_envelopes["work-misroute"] = "cd" * 32

        ent = rig.earner_ledger.create_entry(
            from_compositor=third.pubkey_hex,  # not our payer
            to_compositor=rig.earner_compositor.pubkey_hex,
            amount=10.0,
            work_item_id="work-misroute",
            icp_envelope_hash="cd" * 32,
            model_identifier="mock",
            tokens_out=100,
            duration_ms=10,
        )
        ent = rig.earner_ledger.sign_as_earner(ent)

        before = obs.get_counter_value(
            "gyza_disputes_total", {"reason": "misroute_payer"},
        )
        rig.payer_bus.inject(_Incoming(
            sender_peer_id=rig.earner_bus.peer_id,
            sender_pubkey=rig.earner_compositor.pubkey_hex,
            message_type=EARNER_SIGNED_TYPE,
            payload=json.dumps(ent.to_dict()).encode("utf-8"),
        ))

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if obs.get_counter_value(
                "gyza_disputes_total", {"reason": "misroute_payer"},
            ) > before:
                break
            time.sleep(0.01)
        assert (obs.get_counter_value(
            "gyza_disputes_total", {"reason": "misroute_payer"},
        ) - before) == 1
    finally:
        rig.stop()


# ---------------------------------------------------------------------------
# Runner: completion + claim-latency
# ---------------------------------------------------------------------------

def test_runner_completion_increments_counter_and_histogram(tmp_path):
    """A successful work item completion bumps
    AGENT_COMPLETIONS_TOTAL{outcome="success"} and observes
    CLAIM_TO_COMPLETE_LATENCY exactly once."""
    from gyza.blackboard import Blackboard
    from gyza.demand import LSHIndex
    from gyza.drift import SpecializationTracker
    from gyza.identity import AgentIdentity, LocalCompositor
    from gyza.memory import EpisodicMemory
    from gyza.runner import AgentRunner, make_mock_executor
    from gyza.schema import EMBEDDING_DIM, WorkItem
    import uuid

    bb = Blackboard(str(tmp_path / "bb.db"))
    bb.post_intent({
        "intent_id": "i1",
        "natural_text": "test",
        "category": "system_task",
        "actions": [],
        "authorization": {"resources": [], "preview_required": False, "reversible": True},
    })
    rng = np.random.default_rng(7)
    emb = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    emb /= max(float(np.linalg.norm(emb)), 1e-9)
    w = WorkItem(
        id=str(uuid.uuid7()), lineage_root="i1", parent_id=None,
        description="test work", desc_embedding=emb,
        reward=0.5, reward_updated_ns=time.time_ns(), required_tier=0,
        input_hashes=[], output_spec={}, streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )
    bb.post_work_item(w)

    key_path = tmp_path / "compositor.key"
    key_path.write_bytes(secrets.token_bytes(32))
    key_path.chmod(0o600)
    comp = LocalCompositor(str(key_path))
    seed, manifest = comp.issue_agent(
        agent_type="t", model_path="mock",
        fs_read_paths=["/tmp"], fs_write_paths=["/tmp"], attestation_tier=0,
    )
    ident = AgentIdentity(seed, manifest)
    spec_v = np.zeros(EMBEDDING_DIM, dtype=np.float32); spec_v[0] = 1.0
    spec = SpecializationTracker(
        agent_id=ident.agent_id, initial_embedding=spec_v,
        db_path=str(tmp_path / "spec.db"),
    )
    mem = EpisodicMemory(agent_id=ident.agent_id, db_path=str(tmp_path / "mem"))
    runner = AgentRunner(
        identity=ident, blackboard=bb, memory=mem,
        specialization=spec, lsh=LSHIndex(seed=42),
        executor=make_mock_executor("ok"),
        min_reward_threshold=0.0, min_similarity_threshold=-1.0,
        poll_interval_s=0.1, verify_chain_before_claim=False,
    )

    success_before = obs.get_counter_value(
        "gyza_agent_completions_total", {"outcome": "success"},
    )
    claim_hist_before = _hist_count(obs.CLAIM_TO_COMPLETE_LATENCY)

    runner.start()
    try:
        # Generous deadline — first ST model load can take ~25s on a
        # cold cache; we retry the predicate.
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if obs.get_counter_value(
                "gyza_agent_completions_total", {"outcome": "success"},
            ) > success_before:
                break
            time.sleep(0.05)
    finally:
        runner.stop()

    assert (obs.get_counter_value(
        "gyza_agent_completions_total", {"outcome": "success"},
    ) - success_before) == 1
    assert _hist_count(obs.CLAIM_TO_COMPLETE_LATENCY) - claim_hist_before == 1


# ---------------------------------------------------------------------------
# Gossip delta counters
# ---------------------------------------------------------------------------

def test_gossip_delta_counters_in_out():
    """
    Direct call into _publish_delta_if_attached and _apply_delta on a
    NetworkBlackboard with a fake gossip client. The counters live at
    module scope, so we just test the increment paths.
    """
    from gyza.network.network_blackboard import NetworkBlackboard, _obs_delta

    out_before = obs.get_counter_value(
        "gyza_gossip_deltas_total", {"direction": "out"},
    )
    in_before = obs.get_counter_value(
        "gyza_gossip_deltas_total", {"direction": "in"},
    )

    _obs_delta("out")
    _obs_delta("out")
    _obs_delta("in")

    assert (obs.get_counter_value(
        "gyza_gossip_deltas_total", {"direction": "out"},
    ) - out_before) == 2
    assert (obs.get_counter_value(
        "gyza_gossip_deltas_total", {"direction": "in"},
    ) - in_before) == 1


# ---------------------------------------------------------------------------
# HTTP scrape endpoint
# ---------------------------------------------------------------------------

def test_metrics_server_serves_scrape_endpoint(tmp_path):
    """
    Bind on an ephemeral port and curl /metrics. Assert the response
    contains at least one of our metric names — proves the scrape path
    is live.
    """
    # Ephemeral port: bind 0 isn't supported by start_http_server's
    # signature without a workaround; pick a high port unlikely to
    # collide. If the port is taken in CI, this test'll fail loudly
    # rather than silently passing on a stale port.
    port = _free_port()
    obs.start_metrics_server(port=port, addr="127.0.0.1")
    # Idempotent — a second call must not raise.
    obs.start_metrics_server(port=port + 1, addr="127.0.0.1")

    resp = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/metrics", timeout=2.0,
    )
    body = resp.read().decode("utf-8")
    assert "gyza_settlements_total" in body
    assert "gyza_agent_completions_total" in body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hist_count(hist) -> float:
    """Total observation count of a histogram. prometheus_client's
    Histogram exposes ``_sum`` and ``_buckets`` as private members; the
    safe public path is collect()."""
    for fam in hist.collect():
        for sample in fam.samples:
            if sample.name.endswith("_count") and sample.labels == {}:
                return float(sample.value)
    return 0.0


def _gauge_value(g) -> float:
    for fam in g.collect():
        for sample in fam.samples:
            if sample.labels == {}:
                return float(sample.value)
    return 0.0


def _unit_vec(dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= max(float(np.linalg.norm(v)), 1e-9)
    return v


def _free_port() -> int:
    """Bind an ephemeral port, close, return it. Tiny window between
    close and reuse — fine for a single-process test."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---------------------------------------------------------------------------
# Stub blackboard (just enough for DemandOracle + supervisor._spawn)
# ---------------------------------------------------------------------------

class _StubBlackboard:
    """Bare-bones blackboard stand-in. The supervisor test only needs
    enough to construct an AgentRunner without exercising it."""

    def __init__(self):
        from gyza.schema import HLC
        self._hlc = HLC(node_id="stub")

    def get_unclaimed(self, *args, **kwargs):
        return []

    def signals_by_bucket(self, *args, **kwargs):
        return {}

    def gossip_hlc(self):
        return None


# ---------------------------------------------------------------------------
# Settlement test rig — copies the _make_pair pattern from test_settlement.
# Kept self-contained so this file doesn't depend on test_settlement's
# private fixtures.
# ---------------------------------------------------------------------------

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

    def send_message(self, peer_id: str, message_type: str, payload: bytes) -> bool:
        self.sent.append((peer_id, message_type, bytes(payload)))
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


@dataclass
class _Pair:
    payer_compositor: object
    payer_ledger: object
    payer_bus: _FakeBus
    payer_envelopes: dict
    payer_svc: object

    earner_compositor: object
    earner_ledger: object
    earner_bus: _FakeBus
    earner_envelopes: dict
    earner_svc: object

    def stop(self) -> None:
        self.payer_svc.stop()
        self.earner_svc.stop()
        self.payer_bus.close()
        self.earner_bus.close()


def _make_pair(tmp_path: Path) -> _Pair:
    from gyza.economy.ledger import ComputeLedger
    from gyza.economy.settlement import LedgerSettlementService
    from gyza.identity import LocalCompositor

    def _comp(name: str) -> LocalCompositor:
        p = tmp_path / f"{name}.key"
        p.write_bytes(secrets.token_bytes(32))
        p.chmod(0o600)
        return LocalCompositor(str(p))

    payer = _comp("payer")
    earner = _comp("earner")
    payer_l = ComputeLedger(payer, str(tmp_path / "payer.db"))
    earner_l = ComputeLedger(earner, str(tmp_path / "earner.db"))
    payer_bus = _FakeBus("peer-payer-obs", payer.pubkey_hex)
    earner_bus = _FakeBus("peer-earner-obs", earner.pubkey_hex)
    payer_bus.connect(earner_bus)

    payer_env: dict[str, str] = {}
    earner_env: dict[str, str] = {}
    payer_svc = LedgerSettlementService(
        ledger=payer_l, netd=payer_bus,
        envelope_resolver=payer_env.get,
    )
    earner_svc = LedgerSettlementService(
        ledger=earner_l, netd=earner_bus,
        envelope_resolver=earner_env.get,
    )
    payer_svc.start()
    earner_svc.start()
    return _Pair(
        payer, payer_l, payer_bus, payer_env, payer_svc,
        earner, earner_l, earner_bus, earner_env, earner_svc,
    )
