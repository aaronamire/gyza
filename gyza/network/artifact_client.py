"""
Pull artifacts from peer artifact servers by BLAKE3 hash.

Algorithm: check local store first (free), then poll each peer's
`/artifact/{hash}/exists`, download from the first that has it, verify
hash, cache locally, return. On hash mismatch from a malicious peer:
log + fall through to the next peer. If no peer holds it, return None.

Authentication: every download request carries
  X-Requester-Pubkey: <hex>
  X-Requester-Sig: <Ed25519 over BLAKE3(hash_hex)>

The server's view of "who is asking" is exactly the requester's
compositor pubkey; same key that signs ICP envelopes.
"""
from __future__ import annotations

import logging
import re

import blake3
import httpx

from gyza.identity import AgentIdentity
from gyza.network.artifact_store import ArtifactStore


LOG = logging.getLogger("gyza.artifact_client")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ArtifactClient:
    def __init__(
        self,
        local_store: ArtifactStore,
        identity: AgentIdentity,
        timeout_s: float = 30.0,
    ):
        self._store = local_store
        self._identity = identity
        self._timeout_s = timeout_s

    async def fetch(
        self,
        hash_hex: str,
        peer_urls: list[str],
    ) -> bytes | None:
        if not _HASH_RE.match(hash_hex):
            raise ValueError(f"invalid hash format: {hash_hex!r}")

        # 1. Local cache hit.
        cached = self._store.get(hash_hex)
        if cached is not None:
            return cached

        headers = self._make_auth_headers(hash_hex)
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            for base in peer_urls:
                base = base.rstrip("/")
                # 2. Cheap existence check first; skip peers that don't have it.
                try:
                    r = await client.get(f"{base}/artifact/{hash_hex}/exists")
                    if r.status_code != 200:
                        continue
                    body = r.json()
                    if not body.get("exists"):
                        continue
                except (httpx.RequestError, ValueError):
                    continue

                # 3. Download.
                try:
                    r = await client.get(
                        f"{base}/artifact/{hash_hex}", headers=headers,
                    )
                except httpx.RequestError as e:
                    LOG.warning(
                        "[artifact_client] fetch from %s failed: %s", base, e,
                    )
                    continue

                if r.status_code == 401:
                    LOG.error(
                        "[artifact_client] auth rejected by %s for %s",
                        base, hash_hex[:8],
                    )
                    continue
                if r.status_code != 200:
                    continue

                # 4. Verify the hash before trusting any byte.
                data = r.content
                actual = blake3.blake3(data).hexdigest()
                if actual != hash_hex:
                    LOG.error(
                        "[artifact_client] HASH MISMATCH from %s: claimed %s, got %s",
                        base, hash_hex, actual,
                    )
                    continue

                # 5. Cache and return.
                self._store.store(data)
                return data

        LOG.info(
            "[artifact_client] no peer had artifact %s", hash_hex[:8],
        )
        return None

    def _make_auth_headers(self, hash_hex: str) -> dict[str, str]:
        payload = blake3.blake3(hash_hex.encode("utf-8")).digest()
        sig = self._identity.sign_bytes(payload)
        return {
            "X-Requester-Pubkey": self._identity.pubkey_hex,
            "X-Requester-Sig": sig,
        }


__all__ = ["ArtifactClient"]
