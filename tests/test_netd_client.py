"""
Cross-language integration test for Phase 3 Session 1:

  Python NetdClient  ──gRPC over Unix socket──>  Go gyza-netd
                  ←  NodeInfo, NodeStatus     ──

Verifies:
  - the Go binary actually built (skip otherwise — tests should pass on
    machines without Go installed too)
  - daemon starts, binds the socket
  - GetNodeInfo returns a non-empty PeerID and the compositor pubkey
    matches the Python-side derivation from the same master seed
  - GetStatus reports uptime ≥ 0
  - clean shutdown removes the socket file
"""
from __future__ import annotations

import os
import secrets
import signal
import subprocess
import time
from pathlib import Path

import pytest

# The marker keeps these tests opt-out via GYZA_SKIP_INTEGRATION=1.
pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[1]
NETD_BIN = REPO_ROOT / "netd" / "bin" / "gyza-netd"


def _expected_compositor_pubkey_hex(master_seed: bytes) -> str:
    """Re-derive the compositor pubkey from a master seed exactly as
    Python's LocalCompositor does. The Go LoadIdentity must produce the
    same hex string for the test to pass — that's the whole point of
    the cross-language identity contract."""
    import blake3
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    # _CTX_COMPOSITOR_SEED + b"|" + b"" — see gyza/identity.py.
    ctx = b"gyza.compositor.ed25519.v1"
    seed = blake3.blake3(ctx + b"|", key=master_seed).digest()
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    return sk.public_key().public_bytes_raw().hex()


@pytest.fixture(scope="module")
def netd_binary() -> Path:
    if not NETD_BIN.exists():
        pytest.skip(f"gyza-netd binary not built at {NETD_BIN}")
    return NETD_BIN


@pytest.fixture
def daemon_setup(tmp_path):
    """Write a 32-byte master seed and yield (key_path, expected_pubkey_hex)."""
    key_path = tmp_path / "compositor.key"
    seed = secrets.token_bytes(32)
    key_path.write_bytes(seed)
    os.chmod(key_path, 0o600)
    return key_path, _expected_compositor_pubkey_hex(seed), tmp_path


def test_daemon_starts_and_returns_node_info(netd_binary, daemon_setup):
    """End-to-end: launch daemon, ask for node info, shut down."""
    from gyza.network.netd_client import NetdClient

    key_path, expected_pubkey, tmp_path = daemon_setup
    socket_path = tmp_path / "netd.sock"

    proc = NetdClient.start_daemon(
            isolated=True,
        socket_path=str(socket_path),
        binary_path=str(netd_binary),
        key_path=str(key_path),
        log_level="debug",
        startup_timeout_s=5.0,
    )
    try:
        assert socket_path.exists(), "daemon did not create socket"

        with NetdClient(str(socket_path)) as client:
            info = client.get_node_info()
            assert info.peer_id, "PeerID must not be empty"
            # libp2p PeerIDs from Ed25519 keys begin with 12D3KooW.
            assert info.peer_id.startswith("12D3KooW"), (
                f"expected libp2p Ed25519 PeerID prefix, got {info.peer_id}"
            )
            assert info.compositor_pubkey == expected_pubkey, (
                "Go compositor pubkey does not match Python derivation — "
                "cross-language identity contract is broken"
            )
            assert info.gyza_version, "gyza_version is empty"

            status = client.get_status()
            assert status.uptime_seconds >= 0
            # Pre-S32 this was always 0 ("nothing wired in S1"). Since
            # S32 the daemon binary's FallbackPeers list dials the
            # production bootstrap nodes (gyza.network) on startup, so
            # connected_peers is typically ≥1 when the test box has
            # internet. The test cares that the field round-trips
            # safely; the exact count isn't load-bearing.
            assert status.connected_peers >= 0
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)

    # Socket must be cleaned up after graceful shutdown.
    deadline = time.monotonic() + 2.0
    while socket_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not socket_path.exists(), "socket file lingered after shutdown"


def test_is_running_false_when_no_daemon(tmp_path):
    """is_running() must return False (not raise) when no daemon listens."""
    from gyza.network.netd_client import NetdClient

    socket_path = tmp_path / "no-such-socket"
    with NetdClient(str(socket_path)) as client:
        assert client.is_running() is False


def test_start_daemon_raises_when_binary_missing(tmp_path):
    """Clear FileNotFoundError if the binary path is bogus and not on PATH."""
    from gyza.network.netd_client import NetdClient

    # Make sure gyza-netd is not on PATH.
    bad = tmp_path / "no-such-binary"
    with pytest.raises(FileNotFoundError):
        NetdClient.start_daemon(
            isolated=True,
            socket_path=str(tmp_path / "x.sock"),
            binary_path=str(bad),
        )


def test_publish_and_find_agent_local(netd_binary, daemon_setup):
    """
    Phase 3 Session 2 contract: Python publishes an AgentAdvertisement
    via gRPC; same daemon's local cache holds it; the same query
    embedding finds it back. This validates the full Python →
    np.ndarray<float32,(384,)>.tobytes() → gRPC → Go decodeF32LE →
    LSH bucket → Go encodeF32LE → gRPC stream → np.frombuffer
    round-trip.

    Single-node DHT puts will warn server-side ("failed to find any
    peer in table") but the publish succeeds because the local cache
    is populated regardless. The search hits the local cache.
    """
    import numpy as np
    from gyza.network.netd_client import (
        AgentAdvertisement,
        NetdClient,
    )

    key_path, _expected_pubkey, tmp_path = daemon_setup
    socket_path = tmp_path / "netd.sock"

    proc = NetdClient.start_daemon(
            isolated=True,
        socket_path=str(socket_path),
        binary_path=str(netd_binary),
        key_path=str(key_path),
        listen_port=0,  # ephemeral port — avoids 7749 conflicts
        log_level="info",
        startup_timeout_s=5.0,
    )
    try:
        # Build an embedding with a stable bucket — same vector for
        # publish and query, so the LSH match is exact (radius 0).
        rng = np.random.default_rng(seed=1234)
        emb = rng.standard_normal(384).astype(np.float32)
        emb /= np.linalg.norm(emb)

        ad = AgentAdvertisement(
            agent_pubkey="ab" * 32,
            compositor_pubkey="cd" * 32,
            capability_manifest_hash="ef" * 16,
            specialization_embedding=emb,
            lsh_bucket=0,  # ignored server-side
            attestation_tier=2,
            reputation_score=0.75,
            compute_credit_balance=42,
            last_seen=0,  # netd will stamp now()
            ttl_seconds=3600,
            gyza_version="test",
            multiaddrs=[],
        )

        with NetdClient(str(socket_path)) as client:
            dht_key = client.publish_agent(ad)
            assert dht_key.startswith("/gyza/agents/"), (
                f"unexpected dht_key {dht_key!r}"
            )

            results = client.find_agents(
                query_embedding=emb, k=5, min_tier=0
            )
            assert len(results) >= 1, "publisher's local cache should answer"
            found = next(
                (r for r in results if r.agent_pubkey == ad.agent_pubkey), None
            )
            assert found is not None, (
                f"agent {ad.agent_pubkey} not in results: "
                f"{[r.agent_pubkey for r in results]}"
            )
            # Round-trip: the embedding bytes must come back identical.
            assert found.specialization_embedding.shape == (384,)
            assert np.allclose(
                found.specialization_embedding, emb, atol=0.0
            ), "embedding bytes lost fidelity in round-trip"
            assert found.attestation_tier == 2
            assert abs(found.reputation_score - 0.75) < 1e-6

            # Filter test: min_tier=3 should hide our tier-2 ad.
            filtered = client.find_agents(
                query_embedding=emb, k=5, min_tier=3
            )
            assert all(r.attestation_tier >= 3 for r in filtered)
            assert ad.agent_pubkey not in [r.agent_pubkey for r in filtered]

            # Unpublish removes the local cache entry.
            client.unpublish_agent(ad.agent_pubkey)
            after = client.find_agents(
                query_embedding=emb, k=5, min_tier=0
            )
            assert ad.agent_pubkey not in [r.agent_pubkey for r in after], (
                "agent still findable after UnpublishAgent"
            )
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)


def test_peer_service_connect_and_list(netd_binary, tmp_path):
    """
    Phase 3 Session 3 contract: launch two daemons, instruct daemon-A
    via PeerService.Connect to dial daemon-B's listen multiaddr, and
    verify both directions of ListPeers report the connection.

    NAT manager is enabled in both — nothing to traverse on loopback,
    but exercising the EnableHolePunching + EnableAutoRelay code path
    catches regressions where the libp2p option construction breaks
    host startup.
    """
    import secrets
    from gyza.network.netd_client import NetdClient

    def boot(name: str) -> tuple:
        seed_path = tmp_path / f"{name}.key"
        seed_path.write_bytes(secrets.token_bytes(32))
        os.chmod(seed_path, 0o600)
        sock_path = tmp_path / f"{name}.sock"
        proc = NetdClient.start_daemon(
            isolated=True,
            socket_path=str(sock_path),
            binary_path=str(netd_binary),
            key_path=str(seed_path),
            listen_port=0,
            log_level="info",
            startup_timeout_s=5.0,
        )
        return proc, sock_path

    procA, sockA = boot("a")
    procB, sockB = boot("b")
    try:
        # Pull daemon-B's listen address from its NodeInfo. Pick a
        # loopback /ip4 multiaddr — those are guaranteed to work
        # against a localhost peer regardless of network state.
        with NetdClient(str(sockB)) as cb:
            infoB = cb.get_node_info()
            loopback = next(
                (m for m in infoB.listen_addrs
                 if m.startswith("/ip4/127.0.0.1/")),
                None,
            )
            assert loopback is not None, (
                f"no loopback addr in {infoB.listen_addrs}"
            )
            target = f"{loopback}/p2p/{infoB.peer_id}"

        with NetdClient(str(sockA)) as ca:
            result = ca.connect_peer(target)
            assert result.success, f"connect failed: {result.error}"
            assert result.peer_id == infoB.peer_id

            # Bi-directional view: A and B both see each other.
            peers_a = ca.list_peers()
            assert any(p.peer_id == infoB.peer_id for p in peers_a), (
                f"daemon A peer list missing B: {peers_a}"
            )

        with NetdClient(str(sockB)) as cb:
            with NetdClient(str(sockA)) as ca:
                infoA = ca.get_node_info()
            peers_b = cb.list_peers()
            assert any(p.peer_id == infoA.peer_id for p in peers_b), (
                f"daemon B peer list missing A: {peers_b}"
            )
    finally:
        for p in (procA, procB):
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=2.0)


def test_connect_peer_with_wrong_expected_pubkey_fails(netd_binary, daemon_setup):
    """
    expected_pubkey is the application-level identity guard: if the
    PeerID encoded in the multiaddr doesn't derive from the expected
    Ed25519 pubkey, Connect must refuse with success=False. Catches
    regressions in peerIDMatchesPubkeyHex.
    """
    from gyza.network.netd_client import NetdClient

    key_path, _expected_pubkey, tmp_path = daemon_setup
    socket_path = tmp_path / "netd.sock"
    proc = NetdClient.start_daemon(
            isolated=True,
        socket_path=str(socket_path),
        binary_path=str(netd_binary),
        key_path=str(key_path),
        listen_port=0,
        log_level="info",
        startup_timeout_s=5.0,
    )
    try:
        with NetdClient(str(socket_path)) as client:
            info = client.get_node_info()
            loopback = next(
                (m for m in info.listen_addrs
                 if m.startswith("/ip4/127.0.0.1/")),
                None,
            )
            assert loopback is not None
            # Self-loop dial would normally succeed; with a wrong
            # expected_pubkey we expect a deterministic refusal.
            target = f"{loopback}/p2p/{info.peer_id}"
            wrong_pubkey = "00" * 32
            result = client.connect_peer(target, expected_pubkey=wrong_pubkey)
            assert not result.success
            assert "expected pubkey" in result.error.lower()
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)


def test_gossip_publish_subscribe_two_daemons(netd_binary, tmp_path):
    """
    Phase 3 Session 4 contract: two daemons in the same project topic
    should fan a published delta from A to B via libp2p gossipsub.
    Exercises the full path:

      Python publish_delta → gRPC → Go gossip.PublishDelta → gossipsub
        → mesh fan-out → B's receive loop → fan-out channel
        → gRPC SubscribeDeltas server-stream → Python subscribe_deltas
    """
    import secrets
    import threading
    from gyza.network.netd_client import (
        BlackboardDelta,
        GossipClient,
        IntentRecord,
        NetdClient,
    )

    def boot(name: str) -> tuple:
        seed_path = tmp_path / f"{name}.key"
        seed_path.write_bytes(secrets.token_bytes(32))
        os.chmod(seed_path, 0o600)
        sock_path = tmp_path / f"{name}.sock"
        proc = NetdClient.start_daemon(
            isolated=True,
            socket_path=str(sock_path),
            binary_path=str(netd_binary),
            key_path=str(seed_path),
            listen_port=0,
            log_level="info",
            startup_timeout_s=5.0,
        )
        return proc, sock_path

    procA, sockA = boot("a")
    procB, sockB = boot("b")
    project = "phase3-gossip-test-001"

    try:
        with NetdClient(str(sockA)) as ca, NetdClient(str(sockB)) as cb:
            # Connect A → B at libp2p layer.
            infoB = cb.get_node_info()
            loopbackB = next(
                (m for m in infoB.listen_addrs
                 if m.startswith("/ip4/127.0.0.1/")),
                None,
            )
            assert loopbackB is not None
            connect_result = ca.connect_peer(f"{loopbackB}/p2p/{infoB.peer_id}")
            assert connect_result.success, connect_result.error

        gA = GossipClient(str(sockA))
        gB = GossipClient(str(sockB))
        # Defined out here so the outer finally can always touch it
        # even if join_project / publish raises mid-block.
        stop_after = threading.Event()
        try:
            gA.join_project(project)
            gB.join_project(project)

            # Subscribe on B in a background thread before A publishes —
            # the subscription must be active so the delta isn't lost.
            received: list = []

            def consume() -> None:
                for delta in gB.subscribe_deltas([project]):
                    received.append(delta)
                    if stop_after.is_set() or len(received) >= 1:
                        return

            t = threading.Thread(target=consume, daemon=True)
            t.start()

            # Mesh formation grace — gossipsub needs ≥1 heartbeat for
            # GRAFT/PRUNE to settle. Without this, the first publish
            # often drops before B's mesh entry forms.
            time.sleep(1.5)

            seq = gA.publish_delta(BlackboardDelta(
                project_id=project,
                new_intents=[IntentRecord(
                    intent_id="00000000-0000-4000-8000-000000000abc",
                    goal_spec_json='{"hello": "from A"}',
                    created_at_ns=time.time_ns(),
                )],
            ))
            assert seq == 1

            t.join(timeout=5.0)
            assert len(received) >= 1, "B never received the delta"
            d = received[0]
            assert d.project_id == project
            assert d.sender_seq == 1
            assert len(d.new_intents) == 1
            assert d.new_intents[0].intent_id == "00000000-0000-4000-8000-000000000abc"
            assert d.app_signature, "app_signature should be populated by daemon"
        finally:
            stop_after.set()
            gA.close()
            gB.close()
    finally:
        for p in (procA, procB):
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=2.0)


def test_capability_issue_challenge_and_verify_response(netd_binary, daemon_setup):
    """
    Phase 3 Session 5 — end-to-end gRPC exercise of IssueChallenge +
    VerifyResponse. Validates the Python ↔ Go canonical-bytes /
    deterministic-marshal contract: a Python applicant builds a
    ChallengeResponse with proto.SerializeToString(deterministic=True)
    and an Ed25519 signature; the daemon verifies and returns a
    CoSignature. Failure here = the cross-runtime sign/verify pact
    is broken.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from gyza.network.netd_client import (
        CapabilityClient,
        NetdClient,
    )
    from gyza.network.proto import netd_pb2
    import blake3 as _blake3
    import secrets

    key_path, _expected_pubkey, tmp_path = daemon_setup
    socket_path = tmp_path / "netd.sock"
    proc = NetdClient.start_daemon(
            isolated=True,
        socket_path=str(socket_path),
        binary_path=str(netd_binary),
        key_path=str(key_path),
        listen_port=0,
        log_level="info",
        startup_timeout_s=5.0,
    )
    try:
        with NetdClient(str(socket_path)) as nc:
            v_info = nc.get_node_info()
        v_pubkey = v_info.compositor_pubkey

        applicant_priv = Ed25519PrivateKey.from_private_bytes(secrets.token_bytes(32))
        applicant_pubkey = applicant_priv.public_key().public_bytes_raw().hex()

        with CapabilityClient(str(socket_path)) as cap:
            challenge = cap.issue_challenge(applicant_pubkey, ttl_seconds=300)
            assert challenge.challenger_pubkey == v_pubkey
            assert challenge.applicant_pubkey == applicant_pubkey
            assert len(challenge.nonce) == 32

            # Build the response Python-side, sign each ICP envelope.
            results = []
            for tid in challenge.task_ids:
                payload = f"synthetic-icp-payload:{tid}".encode()
                digest = _blake3.blake3(payload).digest()
                sig = applicant_priv.sign(digest)
                results.append(netd_pb2.TaskResult(
                    task_id=tid,
                    output_json=b'{"result":"ok"}',
                    icp_payload_bytes=payload,
                    icp_signature_hex=sig.hex(),
                    icp_agent_pubkey_hex=applicant_pubkey,
                    duration_ms=42,
                ))
            response_body = netd_pb2.ResponseBody(
                applicant_pubkey=applicant_pubkey,
                challenger_pubkey=v_pubkey,
                nonce=challenge.nonce,
                task_results=results,
                completed_at_ns=time.time_ns(),
            )
            body_bytes = response_body.SerializeToString(deterministic=True)
            response_proto = netd_pb2.ChallengeResponse(
                body=response_body,
                applicant_signature=applicant_priv.sign(body_bytes),
            )

            success, cosig, error = cap.verify_response(challenge, response_proto)
            assert success, f"VerifyResponse failed: {error}"
            assert cosig is not None
            assert cosig.validator_pubkey == v_pubkey
            assert len(cosig.signature) == 64
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)


def test_capability_attestation_dht_round_trip(netd_binary, daemon_setup):
    """
    Build a cert from two synthetic validators (any Ed25519 keypair
    qualifies cryptographically), publish it through the daemon's
    DHT, fetch it back, run VerifyAttestation server-side. Tests the
    full Python → gRPC → DHT → gRPC → Python path.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from gyza.network.netd_client import (
        CapabilityClient,
        NetdClient,
    )
    from gyza.network.proto import netd_pb2
    import secrets

    key_path, _expected_pubkey, tmp_path = daemon_setup
    socket_path = tmp_path / "netd.sock"
    proc = NetdClient.start_daemon(
            isolated=True,
        socket_path=str(socket_path),
        binary_path=str(netd_binary),
        key_path=str(key_path),
        listen_port=0,
        log_level="info",
        startup_timeout_s=5.0,
    )
    try:
        applicant_priv = Ed25519PrivateKey.from_private_bytes(secrets.token_bytes(32))
        applicant_pubkey = applicant_priv.public_key().public_bytes_raw().hex()

        # Two synthetic validators sign the same canonical body.
        v1 = Ed25519PrivateKey.from_private_bytes(secrets.token_bytes(32))
        v2 = Ed25519PrivateKey.from_private_bytes(secrets.token_bytes(32))
        v1_pub = v1.public_key().public_bytes_raw().hex()
        v2_pub = v2.public_key().public_bytes_raw().hex()

        now_ns = time.time_ns()
        body = netd_pb2.AttestationBody(
            applicant_pubkey=applicant_pubkey,
            issued_at_ns=now_ns,
            # Session 16 added a 24h minimum-remaining-lifetime floor
            # on PublishAttestation. Use 48h so the test isn't on the
            # boundary.
            expires_at_ns=now_ns + 48 * 3600 * 1_000_000_000,
            tier_granted=3,
            challenge_task_ids=["t1", "t2", "t3"],
        )
        body_bytes = body.SerializeToString(deterministic=True)
        cert = netd_pb2.AttestationCert(
            body=body,
            co_signatures=[
                netd_pb2.CoSignature(
                    validator_pubkey=v1_pub,
                    signature=v1.sign(body_bytes),
                    signed_at_ns=now_ns,
                ),
                netd_pb2.CoSignature(
                    validator_pubkey=v2_pub,
                    signature=v2.sign(body_bytes),
                    signed_at_ns=now_ns,
                ),
            ],
        )

        with CapabilityClient(str(socket_path)) as cap:
            dht_key = cap.publish_attestation(cert)
            assert dht_key == "/gyza/attestations/" + applicant_pubkey

            fetched = cap.fetch_attestation(applicant_pubkey)
            assert fetched is not None
            assert fetched.applicant_pubkey == applicant_pubkey
            assert len(fetched.co_signatures) == 2

            valid, n_cosigs, reason = cap.verify_attestation(cert)
            assert valid, reason
            assert n_cosigs == 2

            # An unattested pubkey returns None, not an error.
            other = cap.fetch_attestation("00" * 32)
            assert other is None

            # PublishAttestation rejects a cert that fails self-verify.
            tampered = netd_pb2.AttestationCert(
                body=netd_pb2.AttestationBody(
                    applicant_pubkey=applicant_pubkey,
                    issued_at_ns=now_ns,
                    expires_at_ns=now_ns + 24 * 3600 * 1_000_000_000,
                    tier_granted=99,  # ← tampered
                    challenge_task_ids=["t1", "t2", "t3"],
                ),
                co_signatures=cert.co_signatures,  # signatures over the original body
            )
            try:
                cap.publish_attestation(tampered)
                pytest.fail("PublishAttestation accepted a tampered cert")
            except RuntimeError as e:
                assert "self-verify" in str(e).lower() or "tier" in str(e).lower(), str(e)
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)


def test_message_send_subscribe_two_daemons(netd_binary, tmp_path):
    """
    Phase 3 Session 6 contract: Python's send_message / subscribe_messages
    drive the daemon's MessageService through to a real two-daemon
    libp2p stream. Sender opens a stream to the configured PeerID,
    writes one frame, closes; receiver's stream handler dispatches
    to subscribers.
    """
    import secrets
    import threading
    from gyza.network.netd_client import NetdClient

    def boot(name: str) -> tuple:
        seed = tmp_path / f"{name}.key"
        seed.write_bytes(secrets.token_bytes(32))
        os.chmod(seed, 0o600)
        sock = tmp_path / f"{name}.sock"
        proc = NetdClient.start_daemon(
            isolated=True,
            socket_path=str(sock),
            binary_path=str(netd_binary),
            key_path=str(seed),
            listen_port=0,
            log_level="info",
            startup_timeout_s=5.0,
        )
        return proc, sock

    procA, sockA = boot("a")
    procB, sockB = boot("b")
    try:
        with NetdClient(str(sockA)) as ca, NetdClient(str(sockB)) as cb:
            infoB = cb.get_node_info()
            loopbackB = next(
                m for m in infoB.listen_addrs
                if m.startswith("/ip4/127.0.0.1/")
            )
            connect = ca.connect_peer(f"{loopbackB}/p2p/{infoB.peer_id}")
            assert connect.success, connect.error

        # Subscribe on B in a thread before A sends.
        received: list = []
        stop = threading.Event()

        def consumer() -> None:
            with NetdClient(str(sockB)) as cb2:
                for msg in cb2.subscribe_messages(["ledger.test"]):
                    received.append(msg)
                    if stop.is_set() or len(received) >= 1:
                        return

        t = threading.Thread(target=consumer, daemon=True)
        t.start()

        # Subscriptions are accepted immediately, but the gRPC
        # streaming Subscribe RPC takes a few ms to register on the
        # daemon side. A small delay before send avoids a race where
        # the message lands before the subscriber slot exists.
        time.sleep(0.3)

        with NetdClient(str(sockA)) as ca:
            with NetdClient(str(sockB)) as cb:
                infoB = cb.get_node_info()
            ok = ca.send_message(
                peer_id=infoB.peer_id,
                message_type="ledger.test",
                payload=b"the rain in spain falls mainly on the plain",
            )
            assert ok, "send_message returned False"

        t.join(timeout=4.0)
        stop.set()
        assert len(received) >= 1, "subscriber did not receive message"
        msg = received[0]
        assert msg.message_type == "ledger.test"
        assert msg.payload == b"the rain in spain falls mainly on the plain"
        assert msg.sender_peer_id, "sender_peer_id not populated"
        assert msg.sender_pubkey, "sender_pubkey not populated"
    finally:
        for p in (procA, procB):
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=2.0)


def test_publish_agent_rejects_wrong_embedding_shape(netd_binary, daemon_setup):
    """The wire contract is float32[384]. A 256-dim ndarray must fail
    *client-side* with ValueError before any bytes leave the process —
    saves a network round-trip for an obviously bad input."""
    import numpy as np
    from gyza.network.netd_client import AgentAdvertisement

    bad = np.zeros(256, dtype=np.float32)
    with pytest.raises(ValueError, match="384"):
        AgentAdvertisement(
            agent_pubkey="x", compositor_pubkey="y",
            capability_manifest_hash="z",
            specialization_embedding=bad,
            lsh_bucket=0, attestation_tier=0, reputation_score=0.0,
            compute_credit_balance=0, last_seen=0, ttl_seconds=0,
        ).to_proto()
