"""
Content-addressed filesystem store for artifact bytes.

Each artifact lives at `~/.gyza/artifacts/{hash[:2]}/{hash}`. The
two-character prefix shards files across at most 256 directories so a
node holding tens of thousands of artifacts doesn't slow `readdir` to
a crawl. The filename IS the BLAKE3-256 hex hash — content addressing
all the way down. Existence is "file is on disk"; corruption is
detected on every read by recomputing the hash before returning.

Atomicity: writes go to `<path>.tmp` and rename into place. Concurrent
writers of the same content are safe (the rename replaces the tmp file
with itself if the destination already exists by the time we get there;
worst case we waste one tmp write).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import blake3


LOG = logging.getLogger("gyza.artifact_store")


class ArtifactStoreFull(Exception):
    """Raised by ArtifactStore.store() when adding `data` would push the
    on-disk total past `max_bytes`. Callers should treat this like ENOSPC:
    the artifact never lands and the error must surface (not be swallowed
    inside a best-effort write path), or downstream chain verification
    will fail with a missing-input."""


class ArtifactStore:
    def __init__(
        self,
        base_path: str = "~/.gyza/artifacts",
        max_bytes: int | None = None,
    ):
        self.base_path = Path(os.path.expanduser(base_path))
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes  # None = unlimited
        self._warned_at_80pct = False

    def store(self, data: bytes) -> str:
        h = blake3.blake3(data).hexdigest()
        path = self._path(h)
        if path.exists():
            return h
        # Capacity check — only on bytes that would actually land. We
        # already filter out duplicates above so an idempotent store of
        # a known artifact can't push us over budget.
        if self.max_bytes is not None:
            current = self.total_size_bytes()
            projected = current + len(data)
            if projected > self.max_bytes:
                raise ArtifactStoreFull(
                    f"artifact store full: {current}+{len(data)} > "
                    f"{self.max_bytes} bytes ({self.base_path})"
                )
            if (
                not self._warned_at_80pct
                and projected >= int(self.max_bytes * 0.8)
            ):
                LOG.warning(
                    "[artifact_store] %s at 80%% capacity (%d/%d bytes)",
                    self.base_path, projected, self.max_bytes,
                )
                self._warned_at_80pct = True
        path.parent.mkdir(parents=True, exist_ok=True)
        # Tmp name carries the PID so two processes writing the same
        # content at once don't trip over each other's tmp file.
        tmp = path.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return h

    def get(self, hash_hex: str) -> bytes | None:
        path = self._path(hash_hex)
        if not path.exists():
            return None
        data = path.read_bytes()
        actual = blake3.blake3(data).hexdigest()
        if actual != hash_hex:
            LOG.error(
                "[artifact_store] hash mismatch for %s (got %s); deleting",
                hash_hex, actual,
            )
            try:
                path.unlink()
            except OSError:
                pass
            return None
        return data

    def exists(self, hash_hex: str) -> bool:
        return self._path(hash_hex).exists()

    def size_bytes(self, hash_hex: str) -> int | None:
        path = self._path(hash_hex)
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return None

    def list_hashes(self) -> list[str]:
        out: list[str] = []
        for p in self.base_path.rglob("*"):
            if p.is_file() and not p.name.startswith(".") and ".tmp." not in p.name:
                out.append(p.name)
        return out

    def total_size_bytes(self) -> int:
        total = 0
        for p in self.base_path.rglob("*"):
            if p.is_file() and not p.name.startswith(".") and ".tmp." not in p.name:
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        return total

    def _path(self, hash_hex: str) -> Path:
        return self.base_path / hash_hex[:2] / hash_hex


__all__ = ["ArtifactStore", "ArtifactStoreFull"]
