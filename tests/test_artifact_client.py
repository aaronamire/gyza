from __future__ import annotations

import asyncio
import socket
import threading
import time

import blake3
import httpx
import pytest

from gyza.identity import AgentIdentity, LocalCompositor
from gyza.network.artifact_client import ArtifactClient
from gyza.network.artifact_server import build_app, start_artifact_server
from gyza.network.artifact_store import ArtifactStore


pytestmark = pytest.mark.integration


def _free_tcp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _identity(tmp_path, label: str) -> AgentIdentity:
    compositor = LocalCompositor(key_path=str(tmp_path / f"comp-{label}.key"))
    seed, manifest = compositor.issue_agent(
        agent_type=label, model_path="mock",
        fs_read_paths=[], fs_write_paths=[], attestation_tier=1,
    )
    return AgentIdentity(seed, manifest)


def _wait_up(base: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=1.0).status_code == 200:
                return
        except httpx.RequestError:
            time.sleep(0.05)
    raise RuntimeError(f"server at {base} did not come up")


@pytest.mark.asyncio
async def test_client_fetches_from_peer_a_when_only_a_has_it(tmp_path):
    store_a = ArtifactStore(base_path=str(tmp_path / "store-a"))
    store_b = ArtifactStore(base_path=str(tmp_path / "store-b"))
    ident_server_a = _identity(tmp_path, "srv-a")
    ident_server_b = _identity(tmp_path, "srv-b")

    port_a = _free_tcp_port()
    port_b = _free_tcp_port()
    thread_a, server_a = start_artifact_server(store_a, ident_server_a, port=port_a)
    thread_b, server_b = start_artifact_server(store_b, ident_server_b, port=port_b)
    base_a = f"http://127.0.0.1:{port_a}"
    base_b = f"http://127.0.0.1:{port_b}"

    try:
        _wait_up(base_a); _wait_up(base_b)

        data = b"a-only artifact"
        h = store_a.store(data)
        # store_b deliberately does not have it.

        local_store = ArtifactStore(base_path=str(tmp_path / "local"))
        requester = _identity(tmp_path, "req")
        client = ArtifactClient(local_store, requester)

        # Try peer B first (doesn't have it), then peer A.
        out = await client.fetch(h, peer_urls=[base_b, base_a])
        assert out == data
        # Cached locally now.
        assert local_store.get(h) == data
    finally:
        server_a.should_exit = True
        server_b.should_exit = True
        thread_a.join(timeout=5.0); thread_b.join(timeout=5.0)


@pytest.mark.asyncio
async def test_client_returns_local_when_already_cached(tmp_path):
    local_store = ArtifactStore(base_path=str(tmp_path / "local"))
    data = b"already cached"
    h = local_store.store(data)
    requester = _identity(tmp_path, "req")
    client = ArtifactClient(local_store, requester)
    # No peer URLs provided — local hit is sufficient.
    out = await client.fetch(h, peer_urls=[])
    assert out == data


@pytest.mark.asyncio
async def test_client_returns_none_when_no_peer_has_it(tmp_path):
    store_a = ArtifactStore(base_path=str(tmp_path / "store-a"))
    ident = _identity(tmp_path, "srv")
    port = _free_tcp_port()
    thread, server = start_artifact_server(store_a, ident, port=port)
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_up(base)
        local_store = ArtifactStore(base_path=str(tmp_path / "local"))
        requester = _identity(tmp_path, "req")
        client = ArtifactClient(local_store, requester)
        out = await client.fetch("dd" * 32, peer_urls=[base])
        assert out is None
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


@pytest.mark.asyncio
async def test_client_rejects_lying_peer_and_falls_through(tmp_path):
    """A malicious server claims to have hash X but serves bytes that
    hash to Y. Client must detect the mismatch and try the next peer."""
    # Build a malicious server inline — same shape as build_app, but the
    # /artifact/{hash} endpoint returns content the client didn't ask for.
    import uvicorn
    from fastapi import FastAPI, Header, HTTPException, Response

    target_data = b"the real data"
    target_hash = blake3.blake3(target_data).hexdigest()

    bogus_app = FastAPI()

    @bogus_app.get("/health")
    async def _h():
        return {"status": "ok", "pubkey": "00", "artifact_count": 1}

    @bogus_app.get("/artifact/{hash_hex}/exists")
    async def _exists(hash_hex: str):
        # Lie: claim every hash exists.
        return {"exists": True, "size_bytes": 4}

    @bogus_app.get("/artifact/{hash_hex}")
    async def _get(hash_hex: str,
                   x_requester_pubkey: str | None = Header(None),
                   x_requester_sig: str | None = Header(None)):
        if not x_requester_pubkey or not x_requester_sig:
            raise HTTPException(status_code=401)
        # Always serve junk bytes regardless of requested hash.
        return Response(content=b"JUNK", media_type="application/octet-stream",
                        headers={"X-Artifact-Hash": hash_hex})

    bogus_port = _free_tcp_port()
    bogus_config = uvicorn.Config(
        bogus_app, host="127.0.0.1", port=bogus_port,
        log_level="warning", access_log=False,
    )
    bogus_server = uvicorn.Server(bogus_config)

    def _run_bogus():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bogus_server.serve())

    bogus_thread = threading.Thread(target=_run_bogus, daemon=True)
    bogus_thread.start()
    bogus_base = f"http://127.0.0.1:{bogus_port}"

    # Honest server with the real data.
    honest_store = ArtifactStore(base_path=str(tmp_path / "honest"))
    honest_store.store(target_data)
    honest_ident = _identity(tmp_path, "honest")
    honest_port = _free_tcp_port()
    honest_thread, honest_server = start_artifact_server(
        honest_store, honest_ident, port=honest_port,
    )
    honest_base = f"http://127.0.0.1:{honest_port}"

    try:
        _wait_up(bogus_base)
        _wait_up(honest_base)

        local_store = ArtifactStore(base_path=str(tmp_path / "local"))
        requester = _identity(tmp_path, "req")
        client = ArtifactClient(local_store, requester)

        # Hit the lying peer first; client must reject and fall through.
        out = await client.fetch(target_hash, peer_urls=[bogus_base, honest_base])
        assert out == target_data
        assert local_store.get(target_hash) == target_data
    finally:
        honest_server.should_exit = True
        bogus_server.should_exit = True
        honest_thread.join(timeout=5.0)
        bogus_thread.join(timeout=5.0)


@pytest.mark.asyncio
async def test_client_rejects_invalid_hash_input(tmp_path):
    local_store = ArtifactStore(base_path=str(tmp_path / "local"))
    requester = _identity(tmp_path, "req")
    client = ArtifactClient(local_store, requester)
    with pytest.raises(ValueError):
        await client.fetch("not-a-hash", peer_urls=[])
