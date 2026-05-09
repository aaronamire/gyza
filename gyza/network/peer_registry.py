"""
Phase 3 Session 7 — peer registry mapping compositor pubkey ↔ libp2p
peer ID.

Why this exists: settlement (Session 6), project formation (this
session), and ICP cross-compositor verification all key off the
compositor pubkey — that's the identity the user signs with. The
network layer (libp2p, MessageService) routes by peer ID.

We need a lookup. The daemon already exposes list_peers() with both
fields, but a chatty caller would issue one gRPC for every routing
decision. The registry caches and rate-limits refreshes.

Design notes:

  * Cache is best-effort. A miss returns None and the caller can
    retry — settlement caller is expected to log and skip; the
    earner's entry stays unsettled in the local ledger until the
    peer becomes reachable or reconciliation happens.

  * Refreshes are rate-limited (default 1s) so a missing pubkey doesn't
    cause a list_peers gRPC storm under repeated lookups.

  * We populate eagerly from connect_peer's verified_pubkey when the
    GlobalCluster establishes a connection, so the common path
    (connect → publish → settle) doesn't require a refresh at all.

  * Thread-safe: the cache is held under a mutex; refresh happens
    OUTSIDE the lock so slow gRPC doesn't block other lookups.
"""
from __future__ import annotations

import logging
import threading
import time

from gyza.network.netd_client import NetdClient


LOG = logging.getLogger("gyza.peer_registry")


class PeerRegistry:
    """
    Caches compositor_pubkey → peer_id, populated from
    NetdClient.list_peers() and from explicit ``add()`` calls during
    connection setup.

    Misses trigger a refresh (rate-limited to one per
    ``refresh_interval_s``). The cache is purely additive — peers
    that disconnect aren't evicted, because we still want to address
    them by pubkey for any in-flight settlement that completes after
    they reconnect. Stale entries are corrected on the next successful
    refresh.
    """

    def __init__(
        self,
        netd: NetdClient,
        refresh_interval_s: float = 1.0,
    ):
        self._netd = netd
        self._refresh_min_s = refresh_interval_s
        self._lock = threading.Lock()
        self._by_pubkey: dict[str, str] = {}
        self._last_refresh = 0.0  # monotonic ns

    def resolve_peer_id(self, compositor_pubkey: str) -> str | None:
        """
        Return the peer ID for ``compositor_pubkey`` or None.

        Cache-hit fast path first. On miss, fetch list_peers() once
        (subject to rate limit), update cache, return the result.
        """
        with self._lock:
            cached = self._by_pubkey.get(compositor_pubkey)
            if cached:
                return cached
            now = time.monotonic()
            if now - self._last_refresh < self._refresh_min_s:
                return None
            self._last_refresh = now

        # Refresh outside the lock so a slow gRPC doesn't stall other
        # lookups. The lock-then-unlock-then-lock pattern is safe:
        # _last_refresh is updated before unlocking, so concurrent
        # callers that arrive during the gRPC see the rate limit and
        # bail out (returning None rather than queuing an extra refresh).
        try:
            peers = self._netd.list_peers()
        except Exception as e:  # noqa: BLE001
            LOG.warning("[peer_registry] list_peers failed: %s", e)
            return None

        with self._lock:
            for p in peers:
                if p.compositor_pubkey:
                    self._by_pubkey[p.compositor_pubkey] = p.peer_id
            return self._by_pubkey.get(compositor_pubkey)

    def add(self, compositor_pubkey: str, peer_id: str) -> None:
        """
        Eagerly insert a known mapping. Called when a connection is
        established and the daemon returns verified_pubkey.

        We trust caller-supplied pubkeys here because the only callers
        are GlobalCluster paths that derived the pubkey from a verified
        gRPC ConnectResult — the daemon performed the libp2p Noise +
        identify exchange. A test passing in a forged pubkey only
        misroutes ITS OWN settlement messages, which is the test's
        problem.
        """
        if not compositor_pubkey or not peer_id:
            return
        with self._lock:
            self._by_pubkey[compositor_pubkey] = peer_id

    def known_pubkeys(self) -> list[str]:
        with self._lock:
            return sorted(self._by_pubkey.keys())

    def refresh(self) -> int:
        """
        Force-refresh from the daemon, ignoring rate limit. Returns the
        number of mappings now in the cache. Used by tests and by the
        settlement reconciliation flow (which wants the freshest view).
        """
        try:
            peers = self._netd.list_peers()
        except Exception as e:  # noqa: BLE001
            LOG.warning("[peer_registry] refresh list_peers failed: %s", e)
            with self._lock:
                return len(self._by_pubkey)
        with self._lock:
            self._last_refresh = time.monotonic()
            for p in peers:
                if p.compositor_pubkey:
                    self._by_pubkey[p.compositor_pubkey] = p.peer_id
            return len(self._by_pubkey)


__all__ = ["PeerRegistry"]
