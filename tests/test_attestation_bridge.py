"""
Integration test for #21-bridge — Python applicant adapter.

Spawns two real ``gyza-netd`` daemons on loopback (validator +
applicant), connects them, and drives a full Tier-3 attestation flow
from the Python applicant side. Verifies:

  - The bridge ferries Challenge / ChallengeResponse / Outcome frames
    correctly between gRPC and the libp2p ``/gyza/capability-challenge/1.0.0``
    stream.
  - The Python eval orchestrator (``applicant_eval_session``) builds a
    valid ChallengeResponse — TaskResult ICP envelopes verify against
    the applicant agent key, and the ResponseBody signature verifies
    against the applicant compositor key (which is what the validator
    extracts from the libp2p PeerID).
  - The validator returns a CoSignature whose ``validator_pubkey``
    matches the validator's compositor pubkey.
"""
from __future__ import annotations

import os
import secrets
import signal
import subprocess
import time
from pathlib import Path

import pytest

# Mirror test_netd_client.py's binary-discovery convention.
NETD_BIN = Path(__file__).resolve().parents[1] / "netd" / "bin" / "gyza-netd"


@pytest.fixture(scope="module")
def netd_binary() -> Path:
    if not NETD_BIN.exists():
        pytest.skip(f"gyza-netd binary not built at {NETD_BIN}")
    return NETD_BIN


def _boot_daemon(name: str, tmp_path: Path, netd_binary: Path):
    """Spawn one daemon under ``tmp_path/<name>.*`` and return
    ``(proc, sock_path, key_path)``. Caller owns lifecycle."""
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
    )
    return proc, sock, seed


def _kill(proc) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2.0)


def test_request_attestation_two_daemons_end_to_end(netd_binary, tmp_path):
    """
    Full happy path: applicant Python opens the bidi gRPC stream,
    daemon ferries Challenge from validator's libp2p side, Python's
    eval session runs the canonical mock-eval suite, daemon ferries
    response back, validator cosigns. Returns a real CoSignature.
    """
    from gyza.identity import LocalCompositor
    from gyza.network.attestation_adapter import applicant_eval_session
    from gyza.network.netd_client import NetdClient

    validator_proc, validator_sock, validator_key = _boot_daemon(
        "validator", tmp_path, netd_binary
    )
    applicant_proc, applicant_sock, applicant_key = _boot_daemon(
        "applicant", tmp_path, netd_binary
    )

    try:
        with NetdClient(str(validator_sock)) as vc, NetdClient(str(applicant_sock)) as ac:
            v_info = vc.get_node_info()
            a_info = ac.get_node_info()

            # Connect applicant → validator. The libp2p capability stream
            # protocol needs the connection to exist before the gRPC
            # bridge tries to open a stream.
            v_loopback = next(
                m for m in v_info.listen_addrs if m.startswith("/ip4/127.0.0.1/")
            )
            connect = ac.connect_peer(f"{v_loopback}/p2p/{v_info.peer_id}")
            assert connect.success, connect.error

            # Build the eval session using the SAME compositor key
            # the applicant daemon loaded — the validator extracts the
            # applicant pubkey from the libp2p PeerID, which is derived
            # from this key.
            applicant_compositor = LocalCompositor(str(applicant_key))
            assert applicant_compositor.pubkey_hex == a_info.compositor_pubkey

            from gyza.network.netd_client import CapabilityClient

            with applicant_eval_session(applicant_compositor) as eval_cb:
                with CapabilityClient(str(applicant_sock)) as cap:
                    success, cosig, err = cap.request_attestation(
                        target_peer_id=v_info.peer_id,
                        eval_callback=eval_cb,
                        timeout_s=120.0,
                    )

            assert success, f"attestation rejected: {err!r}"
            assert cosig is not None
            assert cosig.validator_pubkey == v_info.compositor_pubkey, (
                f"cosig validator_pubkey={cosig.validator_pubkey[:16]}... "
                f"!= validator daemon pubkey={v_info.compositor_pubkey[:16]}..."
            )
            assert cosig.signature, "cosig signature is empty"
            assert cosig.signed_at_ns > 0
    finally:
        for p in (validator_proc, applicant_proc):
            _kill(p)


def test_tier3_attestation_quorum_three_validators(netd_binary, tmp_path):
    """
    #21d acceptance test. One applicant + three validator daemons on
    loopback. Applicant connects to all validators, then drives
    request_tier3_attestation against an explicit list of validator
    peer IDs (DHT discovery is a separate test). Expects:

      - quorum_k=2 cosignatures collected across the validator pool
      - all cosignatures sign the SAME proposed AttestationBody
        (Phase A's load-bearing invariant)
      - assembled AttestationCert self-verifies via cap.verify_attestation

    Cosigs from a third validator beyond the quorum are NOT collected
    (orchestrator stops once quorum_k is reached) — verifies the
    early-exit optimization that bounds eval cost in the common case.
    """
    from gyza.identity import LocalCompositor
    from gyza.network.attestation_adapter import request_tier3_attestation
    from gyza.network.netd_client import CapabilityClient, NetdClient

    applicant_proc, applicant_sock, applicant_key = _boot_daemon(
        "applicant", tmp_path, netd_binary
    )
    v_procs = []
    v_socks = []
    for i in range(3):
        proc, sock, _ = _boot_daemon(f"v{i}", tmp_path, netd_binary)
        v_procs.append(proc)
        v_socks.append(sock)

    try:
        applicant_compositor = LocalCompositor(str(applicant_key))

        # Applicant must be libp2p-connected to every validator before
        # request_attestation tries to open a stream. Collect each
        # validator's loopback multiaddr + peer_id, then dial.
        validator_peer_ids: list[str] = []
        with NetdClient(str(applicant_sock)) as ac:
            for vsock in v_socks:
                with NetdClient(str(vsock)) as vc:
                    info = vc.get_node_info()
                loopback = next(
                    m for m in info.listen_addrs
                    if m.startswith("/ip4/127.0.0.1/")
                )
                connect = ac.connect_peer(f"{loopback}/p2p/{info.peer_id}")
                assert connect.success, connect.error
                validator_peer_ids.append(info.peer_id)

            with CapabilityClient(str(applicant_sock)) as cap:
                result = request_tier3_attestation(
                    cap=cap,
                    netd=ac,
                    compositor=applicant_compositor,
                    quorum_k=2,
                    candidate_n=3,
                    explicit_validator_peer_ids=validator_peer_ids,
                    self_verify=True,
                )

        # Quorum met → cert non-None and signed by 2 of 3.
        assert result.cert is not None, (
            f"no cert assembled; per-peer errors: {result.per_peer_errors}"
        )
        assert len(result.cosignatures) == 2, (
            f"expected exactly 2 cosigs (quorum), got {len(result.cosignatures)}"
        )
        # Quorum exit short-circuited the third validator. The
        # orchestrator may have contacted 2 (early-success path, both
        # accepted on first try) or up to 3 (one rejected, retried).
        assert 2 <= len(result.contacted_peer_ids) <= 3
        # All contacted peers were drawn from the validator pool.
        for pid in result.contacted_peer_ids:
            assert pid in validator_peer_ids, (
                f"contacted unknown peer {pid!r}"
            )
        # Cosigs are over distinct validators (no validator-pubkey
        # duplication that would let one Tier-3 node mint a cert).
        validator_pks = [c.validator_pubkey for c in result.cosignatures]
        assert len(set(validator_pks)) == len(validator_pks), (
            f"duplicate validator cosigs: {validator_pks}"
        )
        # The cert's body is the applicant-proposed body — applicant
        # pubkey matches and tier_granted == 3.
        assert result.cert.body.applicant_pubkey == applicant_compositor.pubkey_hex
        assert result.cert.body.tier_granted == 3
        assert result.cert.body.expires_at_ns > result.cert.body.issued_at_ns
    finally:
        for p in (applicant_proc, *v_procs):
            _kill(p)


def test_tier3_attestation_publish_and_fetch(netd_binary, tmp_path):
    """
    #21e acceptance test. Builds on Phase B's quorum flow with the
    full publish-and-fetch round-trip:

      1. Boot 4 daemons (1 applicant + 3 validators), connect mesh.
      2. Drive request_tier3_attestation with explicit peer IDs.
      3. Publish the resulting cert via cap.publish_attestation.
      4. Fetch the cert back from the DHT via cap.fetch_attestation.
      5. Verify the fetched cert via cap.verify_attestation.

    Proves the cert survives the protobuf round-trip through DHT
    storage AND remains valid under VerifyAttestation. This is the
    end-to-end happy path the production CLI ``gyza global attest
    --tier 3`` exercises.
    """
    from gyza.identity import LocalCompositor
    from gyza.network.attestation_adapter import request_tier3_attestation
    from gyza.network.netd_client import CapabilityClient, NetdClient

    applicant_proc, applicant_sock, applicant_key = _boot_daemon(
        "applicant", tmp_path, netd_binary
    )
    v_procs = []
    v_socks = []
    for i in range(3):
        proc, sock, _ = _boot_daemon(f"v{i}", tmp_path, netd_binary)
        v_procs.append(proc)
        v_socks.append(sock)

    try:
        applicant_compositor = LocalCompositor(str(applicant_key))
        validator_peer_ids: list[str] = []
        with NetdClient(str(applicant_sock)) as ac:
            for vsock in v_socks:
                with NetdClient(str(vsock)) as vc:
                    info = vc.get_node_info()
                loopback = next(
                    m for m in info.listen_addrs
                    if m.startswith("/ip4/127.0.0.1/")
                )
                connect = ac.connect_peer(f"{loopback}/p2p/{info.peer_id}")
                assert connect.success, connect.error
                validator_peer_ids.append(info.peer_id)

            with CapabilityClient(str(applicant_sock)) as cap:
                result = request_tier3_attestation(
                    cap=cap,
                    netd=ac,
                    compositor=applicant_compositor,
                    quorum_k=2,
                    candidate_n=3,
                    explicit_validator_peer_ids=validator_peer_ids,
                    self_verify=True,
                )
                assert result.cert is not None, (
                    f"orchestration failed: {result.per_peer_errors}"
                )

                # Publish to DHT via the daemon.
                dht_key = cap.publish_attestation(result.cert)
                assert dht_key.startswith("/gyza/attestations/"), (
                    f"unexpected DHT key shape: {dht_key!r}"
                )

                # Fetch back. Single-daemon DHT cache answers locally.
                # CapabilityClient.fetch_attestation returns a Python
                # AttestationCert dataclass (flattened body fields +
                # raw_proto for round-trip).
                fetched = cap.fetch_attestation(applicant_compositor.pubkey_hex)
                assert fetched is not None, "fetch returned None"
                assert fetched.applicant_pubkey == applicant_compositor.pubkey_hex
                assert fetched.tier_granted == 3
                assert len(fetched.co_signatures) == len(result.cert.co_signatures)
                fetched_pks = sorted(c.validator_pubkey for c in fetched.co_signatures)
                orig_pks = sorted(c.validator_pubkey for c in result.cert.co_signatures)
                assert fetched_pks == orig_pks

                # verify_attestation needs a proto. Use the dataclass's
                # raw_proto carry-through.
                assert fetched.raw_proto is not None
                valid, n, reason = cap.verify_attestation(fetched.raw_proto)
                assert valid, f"fetched cert failed verify: {reason} (n={n})"
                assert n == len(result.cert.co_signatures)
    finally:
        for p in (applicant_proc, *v_procs):
            _kill(p)


def test_request_attestation_invalid_target_peer_id(netd_binary, tmp_path):
    """
    Bridge rejects malformed peer IDs synchronously (before opening a
    libp2p stream). Surfaces as a gRPC InvalidArgument that propagates
    to the Python caller as ``grpc.RpcError``.
    """
    import grpc

    from gyza.network.netd_client import CapabilityClient

    proc, sock, _ = _boot_daemon("invalid-target", tmp_path, netd_binary)
    try:
        with CapabilityClient(str(sock)) as cap:
            def _never_called(challenge):  # pragma: no cover
                raise AssertionError("eval_callback should not be invoked")

            with pytest.raises(grpc.RpcError) as excinfo:
                cap.request_attestation(
                    target_peer_id="not-a-real-peer-id",
                    eval_callback=_never_called,
                    timeout_s=10.0,
                )
            # The bridge surfaces this with InvalidArgument.
            assert "invalid target_peer_id" in str(excinfo.value).lower() or \
                excinfo.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    finally:
        _kill(proc)
