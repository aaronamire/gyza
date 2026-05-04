"""
FastAPI server for content-addressed artifact serving.

Endpoints:

  GET  /health                       — sanity check; no auth
  GET  /artifacts/list               — all locally stored hashes; no auth
  GET  /artifact/{hash}/exists       — bool + size; no auth
  GET  /artifact/{hash}              — bytes; *requires* signed request

The download endpoint is the only one that requires authentication.
The signature is over BLAKE3(hash_hex), signed with the requester's
compositor Ed25519 key — same key that authenticates QUIC connections
and signs ICP envelopes. There's no separate transport TLS for this
HTTP server in Phase 2; we treat the LAN as semi-trusted and use the
signature to prove "this requester knows their own private key" rather
than "this requester is on a particular network."
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from typing import Any

import blake3
import uvicorn
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI, Header, HTTPException, Response

from gyza.identity import AgentIdentity
from gyza.network.artifact_store import ArtifactStore


LOG = logging.getLogger("gyza.artifact_server")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _verify_signed_request(
    hash_hex: str,
    pubkey_hex: str | None,
    sig_hex: str | None,
) -> None:
    if not pubkey_hex or not sig_hex:
        raise HTTPException(status_code=401, detail="missing signature headers")
    try:
        pk_bytes = bytes.fromhex(pubkey_hex)
        sig_bytes = bytes.fromhex(sig_hex)
    except ValueError:
        raise HTTPException(status_code=401, detail="malformed signature headers")
    if len(pk_bytes) != 32:
        raise HTTPException(status_code=401, detail="bad pubkey length")
    payload = blake3.blake3(hash_hex.encode("utf-8")).digest()
    try:
        Ed25519PublicKey.from_public_bytes(pk_bytes).verify(sig_bytes, payload)
    except (InvalidSignature, ValueError):
        raise HTTPException(status_code=401, detail="signature verification failed")


def build_app(store: ArtifactStore, identity: AgentIdentity) -> FastAPI:
    app = FastAPI(title="Gyza Artifact Server")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "pubkey": identity.pubkey_hex,
            "artifact_count": len(store.list_hashes()),
        }

    @app.get("/artifacts/list")
    async def list_artifacts() -> dict[str, Any]:
        hashes = store.list_hashes()
        return {"hashes": hashes, "total_size_bytes": store.total_size_bytes()}

    @app.get("/artifact/{hash_hex}/exists")
    async def check_artifact_exists(hash_hex: str) -> dict[str, Any]:
        if not _HASH_RE.match(hash_hex):
            raise HTTPException(status_code=400, detail="invalid hash format")
        size = store.size_bytes(hash_hex)
        return {"exists": size is not None, "size_bytes": size}

    @app.get("/artifact/{hash_hex}")
    async def get_artifact(
        hash_hex: str,
        x_requester_pubkey: str | None = Header(None),
        x_requester_sig: str | None = Header(None),
    ) -> Response:
        if not _HASH_RE.match(hash_hex):
            raise HTTPException(status_code=400, detail="invalid hash format")
        _verify_signed_request(hash_hex, x_requester_pubkey, x_requester_sig)
        data = store.get(hash_hex)
        if data is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"X-Artifact-Hash": hash_hex},
        )

    return app


def start_artifact_server(
    store: ArtifactStore,
    identity: AgentIdentity,
    port: int = 7750,
    host: str = "127.0.0.1",
) -> tuple[threading.Thread, uvicorn.Server]:
    """
    Run a uvicorn instance in a background thread. Returns (thread, server)
    — call `server.should_exit = True` then `thread.join()` for shutdown.
    """
    app = build_app(store, identity)
    config = uvicorn.Config(
        app, host=host, port=port,
        log_level="warning",
        access_log=False,
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.serve())
        finally:
            try:
                loop.close()
            except Exception:
                pass

    thread = threading.Thread(target=_run, name=f"artifact-server-{port}", daemon=True)
    thread.start()

    # Wait briefly for the server to start accepting connections.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    return thread, server


__all__ = ["build_app", "start_artifact_server"]
