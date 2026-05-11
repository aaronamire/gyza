"""
Integration test for #21f — verify-on-fetch in find_agents.

End-to-end smoke that the Go-side AttestationVerifier (exercised
exhaustively in `netd/internal/dht/verifier_test.go`) is wired into
the gRPC FindAgents path on a real daemon. Three real daemons on
loopback. One applicant earns a Tier-3 cert via the existing
attestation orchestrator and publishes a tier-3 advertisement. One
validator publishes a Sybil tier-3 advertisement (same LSH bucket, no
cert). A separate validator queries find_agents(min_tier=3) and must
see ONLY the honest applicant.

Reuses the multi-daemon fixture pattern from test_attestation_bridge.py.
The point of this test is integration wiring, not crypto/cache logic
— that's covered in Go.
"""
from __future__ import annotations

import os
import secrets
import signal
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

NETD_BIN = Path(__file__).resolve().parents[1] / "netd" / "bin" / "gyza-netd"


@pytest.fixture(scope="module")
def netd_binary() -> Path:
    if not NETD_BIN.exists():
        pytest.skip(f"gyza-netd binary not built at {NETD_BIN}")
    return NETD_BIN


def _boot_daemon(name: str, tmp_path: Path, netd_binary: Path):
    """Spawn one daemon. Mirrors test_attestation_bridge.py."""
    from gyza.network.netd_client import NetdClient

    seed = tmp_path / f"{name}.key"
    seed.write_bytes(secrets.token_bytes(32))
    os.chmod(seed, 0o600)
    sock = tmp_path / f"{name}.sock"
    proc = NetdClient.start_daemon(
        socket_path=str(sock),
        binary_path=str(netd_binary),
        key_path=str(seed),
        listen_port=0,
        log_level="info",
        startup_timeout_s=10.0,
        # Force Server mode: ModeAuto stays in Client until AutoNAT
        # confirms reachability, which never happens on a loopback-only
        # mesh — so PutValue from one daemon never reaches another's
        # local datastore, and the consumer's fetch_attestation returns
        # NotFound. Server mode makes the mesh act like a tiny
        # production DHT for the test's purposes.
        dht_mode="server",
    )
    return proc, sock, seed


def _kill(proc) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2.0)


def _deterministic_embedding(seed: int) -> np.ndarray:
    """Unit-norm float32[384] keyed by seed. The two ads in this test
    share an embedding so they land in the same LSH bucket — that way
    a single find_agents query sees both candidates and can prove the
    verifier filters one and admits the other."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(384).astype(np.float32)
    v /= max(float(np.linalg.norm(v)), 1e-9)
    return v


def _wait_for_cert(cap_client, applicant_pubkey: str, timeout_s: float = 8.0) -> None:
    """Poll until the cert is fetchable. The DHT layer's PutValue is
    near-synchronous on a connected loopback mesh, but the receiving
    daemon's view can lag by a few hundred ms while the gossip
    propagation completes. Without this poll, the verifier's first
    fetch races the propagation and times out (250ms default budget),
    leaving us with a false-negative test."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        cert = cap_client.fetch_attestation(applicant_pubkey)
        if cert is not None:
            return
        time.sleep(0.1)
    raise AssertionError(
        f"cert for {applicant_pubkey[:16]}... never reached the consumer's "
        f"DHT view within {timeout_s}s"
    )


def test_find_agents_verifies_tier3_cert(netd_binary, tmp_path):
    """
    Three daemons:

      - applicant: runs the canonical Tier-3 attestation, publishes
        its cert, then publishes a tier-3 AgentAdvertisement at a
        chosen LSH bucket.
      - v1: cosigns the attestation (Tier-3 from the applicant's
        perspective), also publishes a SYBIL tier-3 advertisement
        at the SAME LSH bucket. v1's compositor has NO published
        cert, so its tier-3 claim is unbacked.
      - v2: cosigns the attestation; acts as the consumer that
        queries find_agents.

    Verifier expectations (the actual #21f contract):

      - find_agents(min_tier=3) from v2 returns the applicant's ad
        and DROPS v1's Sybil ad.
      - find_agents(min_tier=1) from v2 returns BOTH (no verification
        runs at tier<3).
    """
    from gyza.identity import LocalCompositor
    from gyza.network.attestation_adapter import request_tier3_attestation
    from gyza.network.netd_client import (
        AgentAdvertisement,
        CapabilityClient,
        NetdClient,
    )

    applicant_proc, applicant_sock, applicant_key = _boot_daemon(
        "applicant", tmp_path, netd_binary
    )
    v1_proc, v1_sock, _ = _boot_daemon("v1", tmp_path, netd_binary)
    v2_proc, v2_sock, _ = _boot_daemon("v2", tmp_path, netd_binary)

    try:
        applicant_compositor = LocalCompositor(str(applicant_key))

        # Connect applicant → v1, applicant → v2, AND v2 → v1 (so v2
        # can route to v1 for the Sybil-ad bucket lookup). Loopback
        # mesh; no NAT.
        with NetdClient(str(applicant_sock)) as ac, \
                NetdClient(str(v1_sock)) as v1c, \
                NetdClient(str(v2_sock)) as v2c:
            v1_info = v1c.get_node_info()
            v2_info = v2c.get_node_info()
            applicant_info = ac.get_node_info()

            def _loopback(info):
                return next(
                    m for m in info.listen_addrs
                    if m.startswith("/ip4/127.0.0.1/")
                )

            assert ac.connect_peer(
                f"{_loopback(v1_info)}/p2p/{v1_info.peer_id}"
            ).success
            assert ac.connect_peer(
                f"{_loopback(v2_info)}/p2p/{v2_info.peer_id}"
            ).success
            assert v2c.connect_peer(
                f"{_loopback(v1_info)}/p2p/{v1_info.peer_id}"
            ).success
            assert v2c.connect_peer(
                f"{_loopback(applicant_info)}/p2p/{applicant_info.peer_id}"
            ).success

            # Phase A: drive attestation + publish for applicant.
            with CapabilityClient(str(applicant_sock)) as applicant_cap:
                result = request_tier3_attestation(
                    cap=applicant_cap,
                    netd=ac,
                    compositor=applicant_compositor,
                    quorum_k=2,
                    candidate_n=2,
                    explicit_validator_peer_ids=[
                        v1_info.peer_id, v2_info.peer_id,
                    ],
                    self_verify=True,
                )
                assert result.cert is not None, (
                    f"attestation orchestration failed: "
                    f"{result.per_peer_errors}"
                )
                assert len(result.cosignatures) == 2

                # Publish cert to DHT under the applicant compositor.
                dht_key = applicant_cap.publish_attestation(result.cert)
                assert dht_key.startswith("/gyza/attestations/")

            # Phase B: applicant publishes a tier-3 AgentAdvertisement.
            shared_emb = _deterministic_embedding(seed=42)
            honest_ad = AgentAdvertisement(
                agent_pubkey=applicant_info.compositor_pubkey,
                compositor_pubkey=applicant_info.compositor_pubkey,
                capability_manifest_hash="honest-manifest",
                specialization_embedding=shared_emb,
                lsh_bucket=0,  # server-recomputed
                attestation_tier=3,
                reputation_score=0.5,
                compute_credit_balance=0,
                last_seen=time.time_ns(),
                ttl_seconds=3600,
                gyza_version="test",
                multiaddrs=[],
            )
            ac.publish_agent(honest_ad)

            # Phase C: v1 publishes a SYBIL tier-3 ad. Same bucket,
            # different compositor, no cert. This is the lie #21f
            # exists to suppress.
            sybil_ad = AgentAdvertisement(
                agent_pubkey=v1_info.compositor_pubkey,
                compositor_pubkey=v1_info.compositor_pubkey,
                capability_manifest_hash="sybil-manifest",
                specialization_embedding=shared_emb,
                lsh_bucket=0,
                attestation_tier=3,
                reputation_score=0.5,
                compute_credit_balance=0,
                last_seen=time.time_ns(),
                ttl_seconds=3600,
                gyza_version="test",
                multiaddrs=[],
            )
            v1c.publish_agent(sybil_ad)

            # Phase D: poll until v2 can see the cert. Bounds the
            # propagation race we describe in _wait_for_cert.
            with CapabilityClient(str(v2_sock)) as v2_cap:
                _wait_for_cert(v2_cap, applicant_compositor.pubkey_hex)

            # Give bucket records a moment to propagate too — they're
            # written by the publisher but the consumer only learns
            # via Hamming-neighbor lookups in find_agents.
            time.sleep(1.0)

            # Phase E: the test of record.
            results_tier3 = v2c.find_agents(
                shared_emb, k=20, min_tier=3,
            )
            honest_in_tier3 = any(
                r.compositor_pubkey == applicant_info.compositor_pubkey
                for r in results_tier3
            )
            sybil_in_tier3 = any(
                r.compositor_pubkey == v1_info.compositor_pubkey
                for r in results_tier3
            )
            assert honest_in_tier3, (
                "honest attested applicant missing from min_tier=3 — "
                "verifier rejected a valid cert"
            )
            assert not sybil_in_tier3, (
                "Sybil v1 (no cert) appeared in min_tier=3 results — "
                "verify-on-fetch did not filter the unbacked tier-3 claim"
            )

            # Phase F: tier-1 query must see BOTH (verifier doesn't fire).
            results_tier1 = v2c.find_agents(
                shared_emb, k=20, min_tier=1,
            )
            honest_in_tier1 = any(
                r.compositor_pubkey == applicant_info.compositor_pubkey
                for r in results_tier1
            )
            sybil_in_tier1 = any(
                r.compositor_pubkey == v1_info.compositor_pubkey
                for r in results_tier1
            )
            assert honest_in_tier1, "honest ad missing from min_tier=1 results"
            assert sybil_in_tier1, (
                "sybil ad missing from min_tier=1 results — "
                "verifier fired at tier<3 (should have been bypassed)"
            )
    finally:
        for p in (applicant_proc, v1_proc, v2_proc):
            _kill(p)
