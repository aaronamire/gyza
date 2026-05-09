"""
Phase 3 Session 7 — GlobalCluster orchestrator tests.

These exercise the orchestration logic (DHT lookup, dedup, NAT-connect,
attestation, gossip topic join, ledger settlement bookkeeping) using
in-process fakes for NetdClient / GossipClient / CapabilityClient. The
end-to-end Python ↔ Go path is covered by the daemon-driven tests
(test_netd_client.py, test_network_blackboard_gossip.py); duplicating
that here would slow the suite without adding coverage.

What we lock in:

  1. publish_agents builds AgentAdvertisements from the agent provider
     and delegates to NetdClient.publish_agent. A failing publish for
     one agent doesn't block the rest.

  2. find_and_collaborate with no DHT hits returns []; no peers are
     contacted, no gossip topic is joined, no project membership is
     recorded.

  3. find_and_collaborate with hits dedups by compositor pubkey,
     connects, exchanges attestations, and joins the gossip topic.

  4. A peer with no attestation cert is treated as Tier 0 (allowed
     into the project, fail-open).

  5. settle_project_ledger emits a per-member reconciliation summary
     and the cumulative balance.
"""
from __future__ import annotations

import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pytest

from gyza.config import GyzaConfig
from gyza.economy.ledger import ComputeLedger, LedgerEntry
from gyza.identity import LocalCompositor
from gyza.network.global_cluster import (
    AgentDescriptor,
    GlobalCluster,
)
from gyza.network.netd_client import (
    AgentAdvertisement,
    BlackboardDelta,
    ConnectResult,
    NodeInfo,
    NodeStatus,
    PeerInfo,
)
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.schema import EMBEDDING_DIM


# ======================================================================
# Helpers
# ======================================================================

def _spec(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    v /= max(np.linalg.norm(v), 1e-9)
    return v


def _compositor(tmp_path: Path, name: str) -> LocalCompositor:
    p = tmp_path / f"{name}.key"
    p.write_bytes(secrets.token_bytes(32))
    p.chmod(0o600)
    return LocalCompositor(str(p))


# ======================================================================
# Fakes
# ======================================================================

@dataclass
class _Status:
    connected_peers: int = 0
    dht_routing_table_size: int = 0
    nat_traversal_available: bool = False
    observed_addr: str = ""
    uptime_seconds: int = 0


class _FakeNetd:
    """
    Stand-in for NetdClient. Captures every call we care about and
    returns canned responses. publish_agent + find_agents + connect_peer
    + list_peers + send_message + subscribe_messages.
    """

    def __init__(self, *, our_pubkey: str = "self" * 16):
        self.published: list[AgentAdvertisement] = []
        self.connected: list[tuple[str, str]] = []
        self.find_responses: dict[bytes, list[AgentAdvertisement]] = {}
        self.connect_responses: dict[str, ConnectResult] = {}
        self.peers: list[PeerInfo] = []
        self.our_pubkey = our_pubkey
        self.publish_should_raise: set[str] = set()

    def get_node_info(self) -> NodeInfo:
        return NodeInfo(
            peer_id="peer-self",
            compositor_pubkey=self.our_pubkey,
            listen_addrs=[],
            gyza_version="phase3-test",
        )

    def get_status(self) -> NodeStatus:
        return NodeStatus(
            connected_peers=len(self.peers),
            dht_routing_table_size=0,
            nat_traversal_available=False,
            observed_addr="",
            uptime_seconds=1,
        )

    def is_running(self) -> bool:
        return True

    def publish_agent(self, ad: AgentAdvertisement) -> str:
        if ad.agent_pubkey in self.publish_should_raise:
            raise RuntimeError("synthetic publish failure")
        self.published.append(ad)
        return f"/gyza/agents/{ad.lsh_bucket:016x}"

    def find_agents(
        self,
        query_embedding: np.ndarray,
        k: int = 10,
        min_tier: int = 0,
        min_reputation: float = 0.0,
    ) -> list[AgentAdvertisement]:
        # Look up by exact byte match — caller passes the same vector
        # they queued the response with.
        key = query_embedding.astype("<f4").tobytes()
        return list(self.find_responses.get(key, []))

    def connect_peer(self, multiaddr: str, expected_pubkey: str = "") -> ConnectResult:
        self.connected.append((multiaddr, expected_pubkey))
        if expected_pubkey in self.connect_responses:
            return self.connect_responses[expected_pubkey]
        # Default: success, daemon-verified pubkey echoes the expected.
        return ConnectResult(
            success=True,
            peer_id=f"peer-{expected_pubkey[:8]}",
            verified_pubkey=expected_pubkey,
            error="",
        )

    def list_peers(self) -> list[PeerInfo]:
        return list(self.peers)

    def get_peer_info(self, peer_id: str) -> PeerInfo:
        for p in self.peers:
            if p.peer_id == peer_id:
                return p
        return PeerInfo(
            peer_id=peer_id, compositor_pubkey="", multiaddr="",
            attestation_tier=0, connected_at=0, last_seen=0,
            messages_sent=0, messages_received=0,
        )

    def get_observed_addr(self) -> str:
        return ""

    # MessageService surface used by LedgerSettlementService.
    def send_message(
        self, peer_id: str, message_type: str, payload: bytes,
    ) -> bool:
        return True

    def subscribe_messages(
        self, message_types=None,
    ) -> Iterator:
        # Yield nothing — settlement loop blocks here. Tests that exercise
        # settlement use the real protocol via tests/test_settlement.py.
        if False:
            yield  # pragma: no cover

    def close(self) -> None:
        pass


class _FakeGossip:
    def __init__(self):
        self.joined: list[str] = []
        self.left: list[str] = []
        self.deltas: list[BlackboardDelta] = []
        self._closed = False

    def join_project(self, project_id: str) -> int:
        self.joined.append(project_id)
        return 0

    def leave_project(self, project_id: str) -> None:
        self.left.append(project_id)

    def list_projects(self) -> list[str]:
        return list(self.joined)

    def publish_delta(self, delta: BlackboardDelta) -> int:
        self.deltas.append(delta)
        return len(self.deltas)

    def subscribe_deltas(self, project_ids=None) -> Iterator:
        # No deltas for test purposes — the receive thread blocks here.
        if False:
            yield  # pragma: no cover

    def close(self) -> None:
        self._closed = True


@dataclass
class _FakeAttestationCert:
    """Stand-in for AttestationCert. Only the fields GlobalCluster reads."""
    applicant_pubkey: str
    tier_granted: int
    raw_proto: Any = None


class _FakeCapability:
    """
    Configurable fake for the CapabilityClient. ``certs[pubkey]``
    controls fetch_attestation; ``verify_results[pubkey]`` controls
    verify_attestation. Missing pubkey → fetch returns None (Tier 0
    fail-open).
    """
    def __init__(
        self,
        certs: dict[str, _FakeAttestationCert] | None = None,
        verify_results: dict[str, tuple[bool, int, str]] | None = None,
    ):
        self.certs = certs or {}
        self.verify_results = verify_results or {}
        self.fetched: list[str] = []

    def fetch_attestation(self, pubkey: str):
        self.fetched.append(pubkey)
        return self.certs.get(pubkey)

    def verify_attestation(self, raw_proto):
        # Find the pubkey by matching raw_proto.
        for pk, cert in self.certs.items():
            if cert.raw_proto is raw_proto:
                return self.verify_results.get(pk, (True, 1, ""))
        return (False, 0, "no cert")

    def close(self):
        pass


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def cluster(tmp_path):
    """
    Build a GlobalCluster wired to a fresh tmp dir, fake clients, fake
    capability factory. start() is sync since we skip daemon spawn.
    """
    comp = _compositor(tmp_path, "self")
    cfg = GyzaConfig(
        compositor_key_path=str(tmp_path / "self.key"),
        netd_socket_path=str(tmp_path / "netd.sock"),
        netd_ledger_db_path=str(tmp_path / "ledger.db"),
        blackboard_db_path=str(tmp_path / "bb.db"),
    )
    bb = NetworkBlackboard(str(tmp_path / "bb.db"))
    netd = _FakeNetd(our_pubkey=comp.pubkey_hex)
    gossip = _FakeGossip()
    cap = _FakeCapability()
    ledger = ComputeLedger(comp, str(tmp_path / "ledger.db"))

    gc = GlobalCluster(
        compositor=comp,
        config=cfg,
        blackboard=bb,
        ledger=ledger,
        netd_client=netd,
        gossip_client=gossip,
        capability_client_factory=lambda: cap,
    )
    return gc, netd, gossip, cap, comp, bb, ledger


def _start(gc):
    """Sync start helper — start() is async but does no awaits in the
    injected-client path. Python 3.14 dropped implicit event-loop
    creation in get_event_loop(), so we use asyncio.run per call."""
    import asyncio
    asyncio.run(gc.start())


def _run(coro):
    import asyncio
    return asyncio.run(coro)


# ======================================================================
# Tests
# ======================================================================

def test_publish_agents_delegates_and_aggregates_balance(cluster):
    gc, netd, _gossip, _cap, comp, _bb, ledger = cluster

    # Seed a tiny earnings history so the advertised balance isn't 0.
    # Build a settled ledger entry by hand: peer paid us 5 credits.
    peer_key_path = Path(ledger._db_path).parent / "peer.key"
    peer_key_path.write_bytes(secrets.token_bytes(32))
    peer_key_path.chmod(0o600)
    peer = LocalCompositor(str(peer_key_path))
    entry = ledger.create_entry(
        from_compositor=peer.pubkey_hex,
        to_compositor=comp.pubkey_hex,
        amount=5.0,
        work_item_id="w",
        icp_envelope_hash="aa" * 32,
        model_identifier="mock", tokens_out=10, duration_ms=10,
    )
    entry = ledger.sign_as_earner(entry)
    # Forge payer cosignature without actually verifying — we just want
    # the entry settled in the DB to exercise the balance aggregation.
    entry.from_signature = "00" * 64
    entry.settled = True
    ledger._save_entry(entry)
    ledger._update_balance_cache(entry)

    spec_v = _spec(1)
    agents = [
        AgentDescriptor(
            agent_pubkey="a1" * 16,
            capability_manifest_hash="m1" * 16,
            specialization=spec_v,
            attestation_tier=2,
            reputation_score=0.9,
        ),
        AgentDescriptor(
            agent_pubkey="a2" * 16,
            capability_manifest_hash="m2" * 16,
            specialization=_spec(2),
            attestation_tier=1,
        ),
    ]
    gc._agents_provider = lambda: agents

    _start(gc)
    n = _run(gc.publish_agents())
    assert n == 2
    assert len(netd.published) == 2
    # Verify field plumbing on the first ad.
    ad = netd.published[0]
    assert ad.agent_pubkey == "a1" * 16
    assert ad.compositor_pubkey == comp.pubkey_hex
    assert ad.attestation_tier == 2
    assert np.allclose(ad.specialization_embedding, spec_v)
    # Balance reflects earnings (the 5.0 settled entry → +5 credits).
    # compute_credit_balance is int(earned - spent). earned=5, spent=0.
    assert ad.compute_credit_balance == 5

    _run(gc.stop())


def test_publish_agents_continues_past_individual_failure(cluster):
    gc, netd, *_ = cluster
    netd.publish_should_raise = {"bad" * 11}  # 33 chars, padded; doesn't matter
    bad = AgentDescriptor(
        agent_pubkey="bad" * 11,
        capability_manifest_hash="m" * 32,
        specialization=_spec(1),
    )
    good = AgentDescriptor(
        agent_pubkey="good" * 8,
        capability_manifest_hash="m" * 32,
        specialization=_spec(2),
    )
    gc._agents_provider = lambda: [bad, good]
    _start(gc)
    n = _run(gc.publish_agents())
    # One succeeded, one raised; aggregate is 1.
    assert n == 1
    # The good one was sent; the bad one is in publish_should_raise so
    # it never appended.
    assert any(a.agent_pubkey == "good" * 8 for a in netd.published)
    assert not any(a.agent_pubkey == "bad" * 11 for a in netd.published)
    _run(gc.stop())


def test_find_and_collaborate_no_peers(cluster):
    gc, netd, gossip, _cap, *_ = cluster
    _start(gc)
    spec_v = _spec(7)
    # No find_responses seeded → DHT returns []
    peers = _run(gc.find_and_collaborate(
        project_id="empty-project",
        required_specializations=[spec_v],
        min_tier=1,
    ))
    assert peers == []
    assert netd.connected == []
    assert gossip.joined == []
    assert gc.project_membership("empty-project") is None
    _run(gc.stop())


def test_find_and_collaborate_with_peers_dedups_and_attests(cluster, tmp_path):
    gc, netd, gossip, cap, comp, _bb, _ledger = cluster

    # Two peer compositors. Three candidate ads: peer-A advertises two
    # agents under the same compositor pubkey (dedup expected); peer-B
    # advertises one. Plus an "ourselves" ad to verify self-skip.
    peer_a = _compositor(tmp_path, "peer-a")
    peer_b = _compositor(tmp_path, "peer-b")
    spec_v = _spec(11)
    ad_a1 = AgentAdvertisement(
        agent_pubkey="a1" * 16,
        compositor_pubkey=peer_a.pubkey_hex,
        capability_manifest_hash="mh" * 16,
        specialization_embedding=spec_v,
        lsh_bucket=0, attestation_tier=1, reputation_score=0.7,
        compute_credit_balance=10, last_seen=time.time_ns(),
        ttl_seconds=3600, gyza_version="x",
        multiaddrs=["/ip4/10.0.0.1/udp/7749/quic-v1"],
    )
    ad_a2 = AgentAdvertisement(
        agent_pubkey="a2" * 16,
        compositor_pubkey=peer_a.pubkey_hex,  # same compositor → dedup
        capability_manifest_hash="mh" * 16,
        specialization_embedding=spec_v,
        lsh_bucket=0, attestation_tier=1, reputation_score=0.95,  # higher
        compute_credit_balance=10, last_seen=time.time_ns(),
        ttl_seconds=3600, gyza_version="x",
        multiaddrs=["/ip4/10.0.0.1/udp/7749/quic-v1"],
    )
    ad_b = AgentAdvertisement(
        agent_pubkey="b1" * 16,
        compositor_pubkey=peer_b.pubkey_hex,
        capability_manifest_hash="mh" * 16,
        specialization_embedding=spec_v,
        lsh_bucket=0, attestation_tier=1, reputation_score=0.5,
        compute_credit_balance=0, last_seen=time.time_ns(),
        ttl_seconds=3600, gyza_version="x",
        multiaddrs=["/ip4/10.0.0.2/udp/7749/quic-v1"],
    )
    self_ad = AgentAdvertisement(
        agent_pubkey="own" * 11,
        compositor_pubkey=comp.pubkey_hex,  # ourselves → must be skipped
        capability_manifest_hash="mh" * 16,
        specialization_embedding=spec_v,
        lsh_bucket=0, attestation_tier=1, reputation_score=1.0,
        compute_credit_balance=0, last_seen=time.time_ns(),
        ttl_seconds=3600, gyza_version="x",
        multiaddrs=["/ip4/127.0.0.1/udp/7749/quic-v1"],
    )

    netd.find_responses[spec_v.astype("<f4").tobytes()] = [
        self_ad, ad_a1, ad_a2, ad_b,
    ]

    # Both peers have valid attestations.
    cap.certs[peer_a.pubkey_hex] = _FakeAttestationCert(
        applicant_pubkey=peer_a.pubkey_hex, tier_granted=3,
        raw_proto=object(),
    )
    cap.verify_results[peer_a.pubkey_hex] = (True, 2, "")
    cap.certs[peer_b.pubkey_hex] = _FakeAttestationCert(
        applicant_pubkey=peer_b.pubkey_hex, tier_granted=3,
        raw_proto=object(),
    )
    cap.verify_results[peer_b.pubkey_hex] = (True, 2, "")

    _start(gc)
    peers = _run(gc.find_and_collaborate(
        project_id="proj-1",
        required_specializations=[spec_v],
        min_tier=1,
    ))
    # Self skipped, peer-A deduped to one entry, peer-B included.
    assert sorted(peers) == sorted([peer_a.pubkey_hex, peer_b.pubkey_hex])
    # Connected to exactly two compositors.
    pubkeys_connected = sorted(p for _, p in netd.connected)
    assert pubkeys_connected == sorted([peer_a.pubkey_hex, peer_b.pubkey_hex])
    # Gossip topic joined.
    assert gossip.joined == ["proj-1"]
    # Membership recorded.
    mship = gc.project_membership("proj-1")
    assert mship is not None
    assert mship.member_compositor_pubkeys == set(peers)
    # Peer registry populated for both peers (lookup must hit cache).
    for pk in peers:
        assert gc.peer_registry.resolve_peer_id(pk) is not None
    _run(gc.stop())


def test_attestation_absent_treated_as_tier0(cluster, tmp_path):
    """A peer with no published cert is fail-open — included in the project."""
    gc, netd, gossip, cap, comp, *_ = cluster
    peer = _compositor(tmp_path, "no-attest")
    spec_v = _spec(13)
    ad = AgentAdvertisement(
        agent_pubkey="x" * 32,
        compositor_pubkey=peer.pubkey_hex,
        capability_manifest_hash="m" * 32,
        specialization_embedding=spec_v,
        lsh_bucket=0, attestation_tier=0, reputation_score=0.5,
        compute_credit_balance=0, last_seen=time.time_ns(),
        ttl_seconds=3600, gyza_version="x",
        multiaddrs=["/ip4/10.1.1.1/udp/7749/quic-v1"],
    )
    netd.find_responses[spec_v.astype("<f4").tobytes()] = [ad]
    # Deliberately do NOT add a cert for this peer.
    _start(gc)
    peers = _run(gc.find_and_collaborate(
        project_id="open",
        required_specializations=[spec_v],
        min_tier=0,
    ))
    assert peers == [peer.pubkey_hex]
    assert peer.pubkey_hex in cap.fetched  # we did try to fetch
    assert gossip.joined == ["open"]
    _run(gc.stop())


def test_attestation_invalid_excludes_peer(cluster, tmp_path):
    gc, netd, gossip, cap, *_ = cluster
    peer = _compositor(tmp_path, "bad-attest")
    spec_v = _spec(17)
    ad = AgentAdvertisement(
        agent_pubkey="y" * 32,
        compositor_pubkey=peer.pubkey_hex,
        capability_manifest_hash="m" * 32,
        specialization_embedding=spec_v,
        lsh_bucket=0, attestation_tier=3, reputation_score=0.5,
        compute_credit_balance=0, last_seen=time.time_ns(),
        ttl_seconds=3600, gyza_version="x",
        multiaddrs=["/ip4/10.2.2.2/udp/7749/quic-v1"],
    )
    netd.find_responses[spec_v.astype("<f4").tobytes()] = [ad]
    cap.certs[peer.pubkey_hex] = _FakeAttestationCert(
        applicant_pubkey=peer.pubkey_hex, tier_granted=3,
        raw_proto=object(),
    )
    cap.verify_results[peer.pubkey_hex] = (False, 0, "tampered")
    _start(gc)
    peers = _run(gc.find_and_collaborate(
        project_id="strict",
        required_specializations=[spec_v],
        min_tier=1,
    ))
    # Peer was connected (we don't refuse connection on attestation),
    # but excluded from the project.
    assert peers == []
    assert gc.project_membership("strict") is None
    # Gossip topic NOT joined when no peers pass attestation.
    assert gossip.joined == []
    _run(gc.stop())


def test_settle_project_ledger_summary(cluster, tmp_path):
    gc, _netd, _gossip, _cap, comp, _bb, ledger = cluster
    _start(gc)

    # Synthesize a project membership directly so we don't need to
    # round-trip find_and_collaborate's setup.
    peer1 = _compositor(tmp_path, "peer-l1")
    peer2 = _compositor(tmp_path, "peer-l2")
    from gyza.network.global_cluster import ProjectMembership
    gc._projects["bookkeep"] = ProjectMembership(
        project_id="bookkeep",
        member_compositor_pubkeys={peer1.pubkey_hex, peer2.pubkey_hex},
    )

    # Settle 8 credits earned from peer1; 3 credits owed to peer2.
    def _settle_into(local_ledger, payer_pk, earner_pk, amount):
        e = local_ledger.create_entry(
            from_compositor=payer_pk, to_compositor=earner_pk,
            amount=amount, work_item_id=f"w{amount}",
            icp_envelope_hash="dd" * 32,
            model_identifier="mock", tokens_out=10, duration_ms=10,
        )
        e.to_signature = "11" * 64
        e.from_signature = "22" * 64
        e.settled = True
        local_ledger._save_entry(e)
        local_ledger._update_balance_cache(e)

    _settle_into(ledger, peer1.pubkey_hex, comp.pubkey_hex, 8.0)
    _settle_into(ledger, comp.pubkey_hex, peer2.pubkey_hex, 3.0)

    summary = _run(gc.settle_project_ledger("bookkeep"))
    assert sorted(summary["members"]) == sorted([
        peer1.pubkey_hex, peer2.pubkey_hex,
    ])
    # Net = +8 (peer1 owes us) − 3 (we owe peer2) = +5
    assert abs(summary["self_balance_credits"] - 5.0) < 1e-9
    # Per-member reconciliation: with empty their_entries, every entry
    # we have shows up in missing_theirs.
    p1_diff = summary["per_member"][peer1.pubkey_hex]
    p2_diff = summary["per_member"][peer2.pubkey_hex]
    assert len(p1_diff["missing_theirs"]) == 1
    assert len(p2_diff["missing_theirs"]) == 1
    assert p1_diff["agreed"] == [] and p1_diff["disputed"] == []
    _run(gc.stop())


def test_settle_unknown_project_returns_warning(cluster):
    gc, *_ = cluster
    _start(gc)
    summary = _run(gc.settle_project_ledger("never-formed"))
    assert summary["members"] == []
    assert summary["per_member"] == {}
    assert summary["self_balance_credits"] == 0.0
    assert "warning" in summary
    _run(gc.stop())


def test_runner_envelope_hook_routes_to_settlement(cluster, tmp_path):
    """
    The hook must:
      - skip local-creator intents (no settlement),
      - skip unknown-creator intents (no settlement),
      - submit_earned for remote-creator intents with a resolvable peer.

    We patch settlement.submit_earned to capture calls without
    actually hitting the wire (it would call netd.send_message —
    safe with our fake but adds noise).
    """
    gc, _netd, _gossip, _cap, comp, bb, _ledger = cluster
    _start(gc)

    # Mock settlement.submit_earned to capture calls.
    calls = []
    original = gc.settlement.submit_earned
    def _capture(**kwargs):
        calls.append(kwargs)
        return type("E", (), {"entry_id": "fake"})()
    gc.settlement.submit_earned = _capture  # type: ignore[assignment]

    # Three intent provenance scenarios:
    me = comp.pubkey_hex
    peer = "peer" * 16  # 64 hex chars
    bb._intent_creator["intent-local"] = me
    bb._intent_creator["intent-remote"] = peer
    # "intent-unknown" deliberately not registered.

    # Register peer -> peer_id in the registry so resolution succeeds.
    gc.peer_registry.add(peer, "peer-id-xyz")

    hook = gc.runner_envelope_hook()

    # Build three envelopes (only the fields the hook reads matter).
    @dataclass
    class _Env:
        intent_id: str
        action_id: str
        model_identifier: str = "mock"
        tokens_out: int = 100
        duration_ms: int = 100
        # The rest of ICPEnvelope's fields — compute_envelope_hash needs
        # them all, so we provide defaults.
        agent_pubkey: str = "a" * 64
        capability_manifest_hash: str = "m" * 64
        input_hashes: list = field(default_factory=lambda: ["i" * 64])
        output_hash: str = "o" * 64
        parent_envelope_hash: Any = None
        timestamp_ns: int = 0
        inference_backend: str = "mock"
        tokens_in: int = 0
        schema_version: int = 1
        signature: str = ""

    hook(_Env(intent_id="intent-local", action_id="w-1"))
    hook(_Env(intent_id="intent-unknown", action_id="w-2"))
    hook(_Env(intent_id="intent-remote", action_id="w-3"))

    # Only the remote-creator case produced a call.
    assert len(calls) == 1
    assert calls[0]["payer_compositor"] == peer
    assert calls[0]["payer_peer_id"] == "peer-id-xyz"
    assert calls[0]["work_item_id"] == "w-3"
    assert calls[0]["model_identifier"] == "mock"
    assert calls[0]["tokens_out"] == 100

    gc.settlement.submit_earned = original  # type: ignore[assignment]
    _run(gc.stop())


def test_runner_envelope_hook_skips_when_peer_unresolvable(cluster):
    """Unknown peer in registry → no settlement call, no crash."""
    gc, _netd, *_, bb, _ = cluster
    _start(gc)

    calls = []
    gc.settlement.submit_earned = lambda **kw: calls.append(kw)  # type: ignore[assignment]

    bb._intent_creator["intent-x"] = "stranger" * 8  # 64 chars
    # Do NOT add stranger to peer registry.

    hook = gc.runner_envelope_hook()

    @dataclass
    class _Env:
        intent_id: str = "intent-x"
        action_id: str = "w-1"
        model_identifier: str = "mock"
        tokens_out: int = 1
        duration_ms: int = 1
        agent_pubkey: str = "a" * 64
        capability_manifest_hash: str = "m" * 64
        input_hashes: list = field(default_factory=lambda: ["i" * 64])
        output_hash: str = "o" * 64
        parent_envelope_hash: Any = None
        timestamp_ns: int = 0
        inference_backend: str = "mock"
        tokens_in: int = 0
        schema_version: int = 1
        signature: str = ""

    hook(_Env())
    assert calls == []  # peer unresolvable → skipped silently
    _run(gc.stop())


def test_start_idempotent(cluster):
    gc, *_ = cluster
    _start(gc)
    assert gc.is_started
    _start(gc)  # second call is a no-op
    assert gc.is_started
    _run(gc.stop())
    assert not gc.is_started


# Pyright noise — keep imports in scope.
_ = LedgerEntry
_ = sys
