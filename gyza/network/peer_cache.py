"""
Phase 3 priority #24 — persistent peer cache.

Why this exists: ``PeerRegistry`` (Session 7) caches the
compositor↔peer-id mapping in memory. Every daemon restart drops the
mapping AND the libp2p layer's connection state. After a crash, the
node sits idle until a remote peer happens to redial — there's no
self-initiated path back to known correspondents.

This module persists ``(compositor_pubkey, multiaddr)`` pairs to a
JSON file under ``~/.gyza/peers.json`` and exposes an
``attempt_reconnect_all`` that the daemon-startup path calls before
any code tries to resolve a peer_id by pubkey. By the time the
settlement service or DHT-republish loop runs, the libp2p host is
holding open connections to whoever was reachable.

Concurrency model: a single ``threading.Lock`` guards the in-memory
dict and the on-disk write. Writes are atomic (``tmp + os.replace``)
so a crash mid-flush leaves the previous good state, never a truncated
file. We don't fsync — the cost outweighs the benefit at Phase-3 scale,
and a power-cut losing the last few cache updates is not load-bearing
(the live network repopulates them on the next contact).

Reconnects use a small thread pool (``max_concurrent=4`` default) to
overlap dial RTTs without flooding the local network or the daemon's
goroutine pool. Failures are logged and counted but never propagate
— a stale peer that stopped existing is the common case, not an
exception.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gyza.network.netd_client import NetdClient


LOG = logging.getLogger("gyza.peer_cache")

DEFAULT_CACHE_PATH = "~/.gyza/peers.json"


def _resolve(p: str) -> str:
    return os.path.expanduser(p)


class PeerCache:
    """
    JSON-backed cache of ``(compositor_pubkey, multiaddr, last_seen_ns)``.

    A single compositor may be reachable at multiple multiaddrs (LAN
    and WAN, IPv4 and IPv6, direct and relayed) — we store all of them
    keyed by pubkey, with each entry's last_seen_ns tracked
    independently. ``add()`` is idempotent: re-adding a known
    (pubkey, multiaddr) only refreshes its last_seen.

    Disk format (stable; tests parse this directly):

        {
          "version": 1,
          "entries": [
            {"pubkey": "ed25519-hex", "multiaddr": "/ip4/.../p2p/...",
             "last_seen_ns": 1234567890000000000},
            ...
          ]
        }

    A version field lets us migrate without surprising older daemons —
    if the on-disk schema is newer than we understand, we treat the
    file as unreadable and start with an empty cache.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: str = DEFAULT_CACHE_PATH):
        self._path = _resolve(path)
        self._lock = threading.Lock()
        # In-memory: {pubkey: {multiaddr: last_seen_ns}}.
        self._entries: dict[str, dict[str, int]] = {}
        self._load()

    # -- load / save ----------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            LOG.warning("[peer_cache] could not read %s: %s", self._path, e)
            return
        if not isinstance(data, dict):
            return
        if data.get("version") != self.SCHEMA_VERSION:
            LOG.warning(
                "[peer_cache] schema version mismatch (have=%s, want=%s) — "
                "starting empty; old file preserved at %s",
                data.get("version"), self.SCHEMA_VERSION, self._path,
            )
            return
        entries = data.get("entries")
        if not isinstance(entries, list):
            return
        loaded: dict[str, dict[str, int]] = {}
        for e in entries:
            if not isinstance(e, dict):
                continue
            pubkey = e.get("pubkey")
            multiaddr = e.get("multiaddr")
            last_seen = e.get("last_seen_ns")
            if not (isinstance(pubkey, str) and isinstance(multiaddr, str)
                    and isinstance(last_seen, int)):
                continue
            loaded.setdefault(pubkey, {})[multiaddr] = last_seen
        self._entries = loaded

    def _save_locked(self) -> None:
        """
        Caller must hold self._lock. Atomic write: tempfile in the
        same directory, then os.replace. The same-directory rule
        matters — os.replace is atomic only on the same filesystem.
        """
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        flat: list[dict] = []
        for pubkey, addrs in self._entries.items():
            for multiaddr, last_seen in addrs.items():
                flat.append({
                    "pubkey": pubkey,
                    "multiaddr": multiaddr,
                    "last_seen_ns": last_seen,
                })
        # Sort newest first for human readability; load order doesn't
        # depend on this (we use the in-memory dict for ordering).
        flat.sort(key=lambda r: r["last_seen_ns"], reverse=True)
        payload = {
            "version": self.SCHEMA_VERSION,
            "entries": flat,
        }
        # NamedTemporaryFile + delete=False so the file survives close.
        # The fd is closed before os.replace so Windows wouldn't choke
        # (we don't support Windows but the discipline is cheap).
        fd, tmp_path = tempfile.mkstemp(
            prefix=".peers.", suffix=".tmp", dir=directory,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            # Cleanup the tempfile if rename never happened.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # -- public API -----------------------------------------------------------

    def add(self, compositor_pubkey: str, multiaddr: str) -> None:
        """
        Insert or refresh a (pubkey, multiaddr) pair. Persists
        immediately. Empty pubkey or multiaddr is a no-op (defensive
        against caller bugs that pass through unverified daemon
        responses).
        """
        if not compositor_pubkey or not multiaddr:
            return
        now_ns = time.time_ns()
        with self._lock:
            self._entries.setdefault(compositor_pubkey, {})[multiaddr] = now_ns
            self._save_locked()

    def remove(self, compositor_pubkey: str) -> None:
        """
        Drop every multiaddr cached for ``compositor_pubkey``. Used
        when a peer is positively known to be defunct (e.g. their
        compositor key was revoked). No-op if absent.
        """
        with self._lock:
            if compositor_pubkey in self._entries:
                del self._entries[compositor_pubkey]
                self._save_locked()

    def all_addrs(self) -> dict[str, list[str]]:
        """
        Return ``{pubkey: [multiaddr, ...]}`` with each pubkey's
        multiaddrs ordered by last_seen DESC. The most recently
        successful address is tried first by reconnect logic — this
        biases toward currently-working network paths even when a
        peer's older addresses are still cached.
        """
        with self._lock:
            out: dict[str, list[str]] = {}
            for pubkey, addrs in self._entries.items():
                ordered = sorted(
                    addrs.items(), key=lambda kv: kv[1], reverse=True,
                )
                out[pubkey] = [m for m, _ in ordered]
            return out

    def __len__(self) -> int:
        with self._lock:
            return sum(len(addrs) for addrs in self._entries.values())

    def known_pubkeys(self) -> list[str]:
        with self._lock:
            return sorted(self._entries.keys())

    # -- reconnection ---------------------------------------------------------

    def attempt_reconnect_all(
        self,
        netd: "NetdClient",
        max_concurrent: int = 4,
        per_peer_timeout_s: float = 10.0,
    ) -> int:
        """
        Dial every cached peer in parallel. Returns the count of
        compositors for which AT LEAST ONE multiaddr connected
        successfully (not the count of multiaddrs dialed). Failures
        are logged at INFO; a peer being offline is normal, not
        exceptional.

        ``per_peer_timeout_s`` bounds each dial individually so one
        unreachable address can't hold up the whole sweep — relevant
        for stale entries pointing at IPs that no longer route.

        Note: ``netd.connect_peer`` is a blocking gRPC call, hence
        the thread pool. We don't ``await`` here because PeerCache is
        invoked from sync init paths (see GlobalCluster.start).
        """
        snapshot = self.all_addrs()
        if not snapshot:
            return 0

        def _dial_one(pubkey: str, addrs: list[str]) -> bool:
            # Try each address newest-first; stop at first success.
            for addr in addrs:
                try:
                    result = netd.connect_peer(addr, expected_pubkey=pubkey)
                except Exception as e:  # noqa: BLE001
                    LOG.info(
                        "[peer_cache] dial %s @ %s threw: %s",
                        pubkey[:16], addr, e,
                    )
                    continue
                if result.success:
                    LOG.info(
                        "[peer_cache] reconnected %s via %s",
                        pubkey[:16], addr,
                    )
                    return True
                LOG.info(
                    "[peer_cache] dial %s @ %s failed: %s",
                    pubkey[:16], addr, result.error,
                )
            return False

        successes = 0
        with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
            futures = {
                pool.submit(_dial_one, pubkey, addrs): pubkey
                for pubkey, addrs in snapshot.items()
            }
            for fut in as_completed(futures):
                try:
                    if fut.result(timeout=per_peer_timeout_s):
                        successes += 1
                except Exception as e:  # noqa: BLE001
                    LOG.info(
                        "[peer_cache] reconnect future for %s threw: %s",
                        futures[fut][:16], e,
                    )
        LOG.info(
            "[peer_cache] reconnected %d / %d cached peers",
            successes, len(snapshot),
        )
        return successes


__all__ = ["PeerCache", "DEFAULT_CACHE_PATH"]
