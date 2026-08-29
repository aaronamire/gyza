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
import uuid
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
    #: Appended, never rewritten. Excluded from `total_size_bytes` by the
    #: leading dot, along with every other dotfile.
    TOMBSTONE_LOG = ".tombstones.jsonl"

    def __init__(
        self,
        base_path: str = "~/.gyza/artifacts",
        max_bytes: int | None = None,
        evict_when_full: bool = False,
    ):
        self.base_path = Path(os.path.expanduser(base_path))
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes  # None = unlimited
        # EVICTION IS WHAT MAKES H5 A BOUND RATHER THAN A TIMER.
        #
        # Without it `store()` raises once the cap is reached and keeps raising
        # forever: the node stops working permanently at `max_bytes` of
        # cumulative storage. That is a refusal, not a reversal, and R-EVID
        # Part C classifies it as a TIMER -- false-alarm probability 1, firing
        # at ceil(L/b) for any positive write rate.
        #
        # Eviction supplies the compensation term the fold needs, and supplies
        # it at exactly the required rate BY CONSTRUCTION: evicting only enough
        # to fit the incoming write gives r >= b at every step, which is
        # Theorem 6's capacity condition satisfied definitionally rather than
        # by measurement. See `evict_to_fit`.
        #
        # OFF BY DEFAULT because it changes a documented contract:
        # `ArtifactStoreFull` tells callers to treat a full store like ENOSPC.
        # Eviction trades that failure for the loss of the oldest content, and
        # which is correct is a deployment decision, so production opts in.
        self.evict_when_full = bool(evict_when_full)
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
            if projected > self.max_bytes and self.evict_when_full:
                freed = self.evict_to_fit(len(data))
                current = self.total_size_bytes()
                projected = current + len(data)
                if projected > self.max_bytes:
                    raise ArtifactStoreFull(
                        f"artifact store full after evicting {freed} bytes: "
                        f"{current}+{len(data)} > {self.max_bytes} "
                        f"({self.base_path}). A single artifact larger than the "
                        f"whole cap cannot be stored at any eviction rate.")
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
        # Tmp name must be unique per WRITER, and a PID is not.
        #
        # This carried only `os.getpid()`, with a comment stating it was there
        # "so two processes writing the same content at once don't trip over
        # each other's tmp file". True, and it does not cover THREADS: they
        # share a pid, so two threads storing the same bytes built the same tmp
        # path and one os.replace'd it out from under the other, raising
        # FileNotFoundError in the loser. Invisible while every agent was its
        # own OS process; reproduced on the first threaded run, at 50 agents.
        #
        # A documented invariant whose named mechanism does not cover the case
        # is an assumption. The token below is unique per write, so it holds
        # for threads, processes and coroutines alike without needing to know
        # which one the caller used.
        tmp = path.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except BaseException:
            # Never leave a partial temp behind: the store is content-addressed
            # and a stray .tmp is not addressable, so it would leak silently.
            tmp.unlink(missing_ok=True)
            raise
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

    def evict_to_fit(self, incoming_bytes: int) -> int:
        """Delete oldest-first until `incoming_bytes` fits. Returns bytes freed.

        THE DELETION IS AN APPENDED FACT, NOT AN ABSENCE. Each eviction writes a
        tombstone recording the hash, size and time. That is what keeps the
        quantity derivable from append-only state rather than from a `stat` of
        whatever happens to remain: an absence is not attributable, and
        `Wallet.net_balance` already establishes the pattern -- a fold that may
        decrease, where every decrement is an appended, attributable entry.

        WHAT AN EVICTION COSTS, stated because it is real: the artifact's BYTES
        are gone, so its content can no longer be inspected. Chain verification
        is unaffected -- `verify_chain` checks signatures over hashes carried in
        the envelopes, not over stored bytes -- so provenance survives eviction
        and only content inspection does not.

        Oldest-first by mtime. Not LRU: access time is not recorded, and
        inventing a recency signal the store does not have would be a policy
        dressed as a measurement.
        """
        if self.max_bytes is None:
            return 0
        target = self.max_bytes - int(incoming_bytes)
        if target < 0:
            return 0                       # cannot fit at any eviction rate
        files = []
        for p in self.base_path.rglob("*"):
            if p.is_file() and not p.name.startswith(".") and ".tmp." not in p.name:
                try:
                    st = p.stat()
                except OSError:
                    continue
                files.append((st.st_mtime, st.st_size, p))
        files.sort(key=lambda t: t[0])

        total = sum(f[1] for f in files)
        freed = 0
        for _mtime, size, path in files:
            if total <= target:
                break
            try:
                path.unlink()
            except OSError:
                continue
            self._record_tombstone(path.name, size)
            total -= size
            freed += size
        return freed

    def _record_tombstone(self, hash_hex: str, size: int) -> None:
        """Append one eviction record. Best-effort by design: a failure to log
        must not turn a successful eviction into an exception on the write
        path, and the bytes are gone either way -- but it is LOGGED as a
        warning rather than swallowed, because an eviction nobody recorded is
        exactly the unattributable absence this exists to prevent."""
        import json
        import time as _t
        try:
            with (self.base_path / self.TOMBSTONE_LOG).open("a") as fh:
                fh.write(json.dumps({"hash": hash_hex, "bytes": int(size),
                                     "evicted_at_ns": _t.time_ns()}) + "\n")
        except OSError:
            LOG.warning("[artifact_store] eviction of %s was not recorded",
                        hash_hex[:16], exc_info=True)

    def evicted_bytes(self) -> int:
        """Total bytes reclaimed by eviction, folded from the tombstone log."""
        import json
        path = self.base_path / self.TOMBSTONE_LOG
        if not path.exists():
            return 0
        total = 0
        for line in path.read_text().splitlines():
            try:
                total += int(json.loads(line)["bytes"])
            except Exception:                                # noqa: BLE001
                continue
        return total

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
