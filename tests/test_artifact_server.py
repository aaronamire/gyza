from __future__ import annotations

import socket
import time

import blake3
import httpx
import pytest

from gyza.identity import AgentIdentity, LocalCompositor
from gyza.network.artifact_server import start_artifact_server
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


@pytest.fixture
def served_store(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    ident = _identity(tmp_path, "server")
    port = _free_tcp_port()
    thread, server = start_artifact_server(store, ident, port=port)
    base = f"http://127.0.0.1:{port}"

    # Wait for server to actually accept.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base}/health", timeout=1.0)
            if r.status_code == 200:
                break
        except httpx.RequestError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2.0)
        pytest.fail("server didn't come up")

    yield store, ident, base
    server.should_exit = True
    thread.join(timeout=5.0)


def _signed_headers(ident: AgentIdentity, hash_hex: str) -> dict[str, str]:
    payload = blake3.blake3(hash_hex.encode("utf-8")).digest()
    return {
        "X-Requester-Pubkey": ident.pubkey_hex,
        "X-Requester-Sig": ident.sign_bytes(payload),
    }


def test_health_endpoint(served_store):
    _store, ident, base = served_store
    r = httpx.get(f"{base}/health", timeout=2.0)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["pubkey"] == ident.pubkey_hex
    assert body["artifact_count"] == 0


def test_fetch_existing_artifact(tmp_path, served_store):
    store, _ident, base = served_store
    requester = _identity(tmp_path, "req")
    data = b"hello over http"
    h = store.store(data)

    r = httpx.get(f"{base}/artifact/{h}", headers=_signed_headers(requester, h),
                  timeout=2.0)
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["X-Artifact-Hash"] == h
    assert blake3.blake3(r.content).hexdigest() == h


def test_fetch_nonexistent_returns_404(tmp_path, served_store):
    _store, _ident, base = served_store
    requester = _identity(tmp_path, "req")
    h = "00" * 32
    r = httpx.get(f"{base}/artifact/{h}", headers=_signed_headers(requester, h),
                  timeout=2.0)
    assert r.status_code == 404


def test_unauthenticated_request_returns_401(served_store):
    _store, _ident, base = served_store
    h = "00" * 32
    r = httpx.get(f"{base}/artifact/{h}", timeout=2.0)
    assert r.status_code == 401


def test_wrong_signature_returns_401(tmp_path, served_store):
    store, _ident, base = served_store
    requester = _identity(tmp_path, "req")
    h = store.store(b"some bytes")
    bogus_headers = {
        "X-Requester-Pubkey": requester.pubkey_hex,
        # Valid pubkey, but signature is over garbage rather than blake3(h).
        "X-Requester-Sig": requester.sign_bytes(b"not the right payload"),
    }
    r = httpx.get(f"{base}/artifact/{h}", headers=bogus_headers, timeout=2.0)
    assert r.status_code == 401


def test_invalid_hash_format_returns_400(tmp_path, served_store):
    _store, _ident, base = served_store
    requester = _identity(tmp_path, "req")
    bad = "not-a-hash"
    r = httpx.get(f"{base}/artifact/{bad}",
                  headers=_signed_headers(requester, bad), timeout=2.0)
    assert r.status_code == 400


def test_exists_endpoint_correct_bool(served_store):
    store, _ident, base = served_store
    data = b"existence check"
    h = store.store(data)
    r = httpx.get(f"{base}/artifact/{h}/exists", timeout=2.0)
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["size_bytes"] == len(data)

    r = httpx.get(f"{base}/artifact/{'0'*64}/exists", timeout=2.0)
    body = r.json()
    assert body["exists"] is False
    assert body["size_bytes"] is None


def test_list_artifacts_endpoint(served_store):
    store, _ident, base = served_store
    h1 = store.store(b"a")
    h2 = store.store(b"bb")
    r = httpx.get(f"{base}/artifacts/list", timeout=2.0)
    assert r.status_code == 200
    body = r.json()
    assert set(body["hashes"]) == {h1, h2}
    assert body["total_size_bytes"] == 3
