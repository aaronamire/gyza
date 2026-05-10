"""
Tests for PeerCache (Phase 3 priority #24).

Covers:

  * add/remove persistence (atomic write, surviving fresh load)
  * idempotent add — re-adding a known (pubkey, multiaddr) refreshes
    last_seen rather than duplicating
  * all_addrs ordering (LRU first per pubkey, by last_seen DESC)
  * recovery from corrupt / missing / version-mismatched JSON
  * attempt_reconnect_all happy path and address-fallthrough behavior
  * counts: per-peer (not per-multiaddr) success count
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from gyza.network.peer_cache import PeerCache


# ----------------------------------------------------------------------
# Test doubles — minimal NetdClient surface needed by attempt_reconnect_all
# ----------------------------------------------------------------------

@dataclass
class _ConnectResult:
    success: bool
    peer_id: str = ""
    verified_pubkey: str = ""
    error: str = ""


class _FakeNetd:
    """
    Records every connect_peer call. ``responses`` maps multiaddr →
    ConnectResult; default is success=True. ``raise_for`` is a set of
    multiaddrs that raise on dial.
    """

    def __init__(
        self,
        responses: dict[str, _ConnectResult] | None = None,
        raise_for: set[str] | None = None,
    ):
        self.responses = responses or {}
        self.raise_for = raise_for or set()
        self.calls: list[tuple[str, str]] = []

    def connect_peer(self, multiaddr: str, expected_pubkey: str = "") -> _ConnectResult:
        self.calls.append((multiaddr, expected_pubkey))
        if multiaddr in self.raise_for:
            raise RuntimeError(f"synthetic dial failure: {multiaddr}")
        return self.responses.get(
            multiaddr, _ConnectResult(success=True, verified_pubkey=expected_pubkey),
        )


# ----------------------------------------------------------------------
# Tests — persistence
# ----------------------------------------------------------------------

def test_add_persists_atomically_and_reloads(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk_alpha", "/ip4/1.2.3.4/udp/7749/quic-v1/p2p/12D3Aaa")
    # Drop the in-memory cache and reopen from disk.
    fresh = PeerCache(path=str(p))
    assert fresh.all_addrs() == {
        "pk_alpha": ["/ip4/1.2.3.4/udp/7749/quic-v1/p2p/12D3Aaa"],
    }


def test_add_idempotent_refreshes_last_seen(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk_alpha", "/ip4/1.2.3.4/udp/7749/quic-v1/p2p/aaa")
    first_data = json.loads(p.read_text())
    first_ts = first_data["entries"][0]["last_seen_ns"]

    # Force a small monotonic gap so the timestamp can advance.
    time.sleep(0.001)
    cache.add("pk_alpha", "/ip4/1.2.3.4/udp/7749/quic-v1/p2p/aaa")

    second_data = json.loads(p.read_text())
    assert len(second_data["entries"]) == 1, "duplicate entry written"
    assert second_data["entries"][0]["last_seen_ns"] > first_ts


def test_empty_pubkey_or_multiaddr_is_noop(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("", "/ip4/1.2.3.4/udp/7749/quic-v1/p2p/aaa")
    cache.add("pk_alpha", "")
    assert cache.all_addrs() == {}
    assert not p.exists(), "no entries → file should not have been written"


def test_remove_drops_all_addrs_for_pubkey(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk_alpha", "/ip4/1.2.3.4/udp/7749/quic-v1/p2p/aaa")
    cache.add("pk_alpha", "/ip4/5.6.7.8/udp/7749/quic-v1/p2p/aaa")
    cache.add("pk_beta", "/ip4/9.9.9.9/udp/7749/quic-v1/p2p/bbb")
    assert len(cache.all_addrs()) == 2

    cache.remove("pk_alpha")
    assert cache.all_addrs() == {
        "pk_beta": ["/ip4/9.9.9.9/udp/7749/quic-v1/p2p/bbb"],
    }
    # Persisted: re-load and recheck.
    fresh = PeerCache(path=str(p))
    assert fresh.all_addrs() == cache.all_addrs()


def test_all_addrs_orders_per_pubkey_by_last_seen_desc(tmp_path):
    """
    Two multiaddrs for the same pubkey should be returned newest first.
    Reconnect logic depends on this — currently working network paths
    get tried before stale ones.
    """
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk", "/old/addr")
    time.sleep(0.001)
    cache.add("pk", "/new/addr")
    assert cache.all_addrs() == {"pk": ["/new/addr", "/old/addr"]}


# ----------------------------------------------------------------------
# Tests — recovery from bad on-disk state
# ----------------------------------------------------------------------

def test_missing_file_starts_empty(tmp_path):
    p = tmp_path / "does_not_exist.json"
    cache = PeerCache(path=str(p))
    assert cache.all_addrs() == {}
    assert not p.exists()


def test_corrupt_json_starts_empty(tmp_path):
    p = tmp_path / "peers.json"
    p.write_text("{not valid json")
    cache = PeerCache(path=str(p))
    assert cache.all_addrs() == {}
    # add() works fine and overwrites the corrupt file.
    cache.add("pk", "/ip4/1.1.1.1/udp/7749/quic-v1/p2p/x")
    assert json.loads(p.read_text())["entries"]


def test_unknown_schema_version_starts_empty_preserves_file(tmp_path):
    """
    If a future on-disk format appears we don't understand, treat it
    as unreadable and start fresh — but DON'T overwrite the file
    until something forces a write. (Trip-wire: we already overwrite
    on the first add(); that's intentional and tested elsewhere.)
    """
    p = tmp_path / "peers.json"
    payload = {"version": 99, "entries": [{"pubkey": "pk", "multiaddr": "/x", "last_seen_ns": 1}]}
    p.write_text(json.dumps(payload))
    cache = PeerCache(path=str(p))
    assert cache.all_addrs() == {}
    # The original future-version file is still on disk — we didn't touch it.
    assert json.loads(p.read_text()) == payload


def test_atomic_write_leaves_no_tempfile_on_success(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk", "/x")
    # No leftover .peers.*.tmp files.
    leftover = [f for f in os.listdir(tmp_path) if f.startswith(".peers.") and f.endswith(".tmp")]
    assert leftover == []


# ----------------------------------------------------------------------
# Tests — attempt_reconnect_all
# ----------------------------------------------------------------------

def test_reconnect_returns_zero_when_empty(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    netd = _FakeNetd()
    assert cache.attempt_reconnect_all(netd) == 0
    assert netd.calls == []


def test_reconnect_dials_each_known_peer(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk_alpha", "/ip4/1.1.1.1/udp/7749/quic-v1/p2p/aaa")
    cache.add("pk_beta", "/ip4/2.2.2.2/udp/7749/quic-v1/p2p/bbb")
    netd = _FakeNetd()
    n = cache.attempt_reconnect_all(netd, max_concurrent=1)
    assert n == 2
    # Each peer was dialed exactly once.
    dialed_pubkeys = {pk for _, pk in netd.calls}
    assert dialed_pubkeys == {"pk_alpha", "pk_beta"}


def test_reconnect_count_is_per_peer_not_per_addr(tmp_path):
    """
    A peer with two cached multiaddrs that BOTH succeed counts as 1,
    not 2. Documents the contract: count of compositors reachable.
    """
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk", "/ip4/1.1.1.1/udp/7749/quic-v1/p2p/aaa")
    time.sleep(0.001)
    cache.add("pk", "/ip4/2.2.2.2/udp/7749/quic-v1/p2p/aaa")
    netd = _FakeNetd()
    assert cache.attempt_reconnect_all(netd, max_concurrent=1) == 1


def test_reconnect_falls_through_to_alternate_addrs(tmp_path):
    """
    If the newest multiaddr fails, the cache must try the older one
    before giving up on the peer.
    """
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk", "/old/addr")
    time.sleep(0.001)
    cache.add("pk", "/new/addr")
    # /new/addr fails; /old/addr succeeds.
    netd = _FakeNetd(responses={
        "/new/addr": _ConnectResult(success=False, error="no route"),
        "/old/addr": _ConnectResult(success=True, verified_pubkey="pk"),
    })
    assert cache.attempt_reconnect_all(netd, max_concurrent=1) == 1
    # Both addresses were attempted; /new/addr must have been tried first.
    assert [m for m, _ in netd.calls] == ["/new/addr", "/old/addr"]


def test_reconnect_swallows_exceptions(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk", "/raises")
    netd = _FakeNetd(raise_for={"/raises"})
    # Exception in connect_peer should not propagate; just count as failure.
    assert cache.attempt_reconnect_all(netd, max_concurrent=1) == 0


def test_reconnect_partial_success(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk_alpha", "/works")
    cache.add("pk_beta", "/fails")
    netd = _FakeNetd(responses={
        "/works": _ConnectResult(success=True, verified_pubkey="pk_alpha"),
        "/fails": _ConnectResult(success=False, error="dial timeout"),
    })
    assert cache.attempt_reconnect_all(netd, max_concurrent=2) == 1


# ----------------------------------------------------------------------
# Tests — len / known_pubkeys
# ----------------------------------------------------------------------

def test_len_and_known_pubkeys(tmp_path):
    p = tmp_path / "peers.json"
    cache = PeerCache(path=str(p))
    cache.add("pk_alpha", "/a")
    cache.add("pk_alpha", "/b")
    cache.add("pk_beta", "/c")
    assert len(cache) == 3  # multiaddr count
    assert cache.known_pubkeys() == ["pk_alpha", "pk_beta"]


