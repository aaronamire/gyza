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
