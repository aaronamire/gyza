from __future__ import annotations

import asyncio
import os
import socket
import time

import pytest
import pytest_asyncio

from gyza.identity import AgentIdentity, LocalCompositor
from gyza.network.discovery import DiscoveredPeer, GyzaDiscovery
from gyza.network.transport import GyzaTransport


pytestmark = pytest.mark.asyncio


# Skip integration tests entirely if the operator opts out — useful in CI
# environments without LAN multicast (containers, sandboxed runners).
_SKIP_INT = os.environ.get("GYZA_SKIP_INTEGRATION") == "1"
integration = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
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


async def _wait(predicate, timeout=10.0, interval=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Non-integration: pure JSON round-trip (no network)
# ---------------------------------------------------------------------------

async def test_peer_persistence(tmp_path):
    transport = GyzaTransport(
        _identity(tmp_path, "x"), listen_port=_free_port(),
        heartbeat_interval_s=10.0,
    )
    disc = GyzaDiscovery(
        transport.identity, transport,
        auto_connect=False, announce_interval_s=300.0,
    )
    # Inject some known peers without starting mDNS.
    p1 = DiscoveredPeer(
        pubkey="aa" * 32, ip="192.168.1.10", port=7749, tier=1,
        agent_count=2, discovered_at_ns=10**18, last_seen_ns=10**18,
    )
    p2 = DiscoveredPeer(
        pubkey="bb" * 32, ip="192.168.1.11", port=7750, tier=1,
        agent_count=0, discovered_at_ns=10**18, last_seen_ns=10**18,
    )
    disc._known[p1.pubkey] = p1
    disc._known[p2.pubkey] = p2

    blob = disc.export_peers_json()
    assert "aa" in blob and "bb" in blob

    # Round-trip through a fresh instance.
    disc2 = GyzaDiscovery(
        transport.identity, transport,
        auto_connect=False, announce_interval_s=300.0,
    )
    n = disc2.import_peers_json(blob)
    assert n == 2
    out = {p.pubkey: p for p in disc2.known_peers()}
    assert out[p1.pubkey] == p1
    assert out[p2.pubkey] == p2


async def test_export_handles_empty_known_set(tmp_path):
    transport = GyzaTransport(
        _identity(tmp_path, "y"), listen_port=_free_port(),
        heartbeat_interval_s=10.0,
    )
    disc = GyzaDiscovery(transport.identity, transport, auto_connect=False)
    assert disc.export_peers_json() == "[]"
    assert disc.import_peers_json("not json") == 0
    assert disc.import_peers_json('{"not": "list"}') == 0


# ---------------------------------------------------------------------------
# Integration: real mDNS over loopback
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def two_nodes(tmp_path):
    a_t = GyzaTransport(_identity(tmp_path, "ia"), listen_port=_free_port(),
                        heartbeat_interval_s=2.0)
    b_t = GyzaTransport(_identity(tmp_path, "ib"), listen_port=_free_port(),
                        heartbeat_interval_s=2.0)
    await a_t.start()
    await b_t.start()
    a_d = GyzaDiscovery(a_t.identity, a_t, auto_connect=True,
                        announce_interval_s=2.0)
    b_d = GyzaDiscovery(b_t.identity, b_t, auto_connect=True,
                        announce_interval_s=2.0)
    try:
        yield a_t, a_d, b_t, b_d
    finally:
        await a_d.stop()
        await b_d.stop()
        await a_t.stop()
        await b_t.stop()


@integration
@pytest.mark.skipif(_SKIP_INT, reason="GYZA_SKIP_INTEGRATION=1")
async def test_mutual_discovery(two_nodes):
    a_t, a_d, b_t, b_d = two_nodes
    await a_d.start()
    await b_d.start()

    # Within 10s each side should see the other in live_peers().
    a_sees_b = await _wait(
        lambda: any(p.pubkey == b_t.identity.pubkey_hex for p in a_d.live_peers()),
        timeout=10.0,
    )
    b_sees_a = await _wait(
        lambda: any(p.pubkey == a_t.identity.pubkey_hex for p in b_d.live_peers()),
        timeout=10.0,
    )
    assert a_sees_b, "A did not discover B"
    assert b_sees_a, "B did not discover A"


@integration
@pytest.mark.skipif(_SKIP_INT, reason="GYZA_SKIP_INTEGRATION=1")
async def test_auto_connect(two_nodes):
    a_t, a_d, b_t, b_d = two_nodes
    await a_d.start()
    await b_d.start()

    # Auto-connect should land an authenticated peer in transport.
    a_has_b = await _wait(
        lambda: a_t.is_connected(b_t.identity.pubkey_hex), timeout=15.0,
    )
    b_has_a = await _wait(
        lambda: b_t.is_connected(a_t.identity.pubkey_hex), timeout=15.0,
    )
    assert a_has_b, "A did not auto-connect to B's transport"
    assert b_has_a, "B did not auto-connect to A's transport"


@integration
@pytest.mark.skipif(_SKIP_INT, reason="GYZA_SKIP_INTEGRATION=1")
async def test_own_announcement_filtered(tmp_path):
    """A node hearing its own mDNS announcement must not enter it as a
    peer or attempt a self-connection."""
    t = GyzaTransport(_identity(tmp_path, "solo"), listen_port=_free_port(),
                      heartbeat_interval_s=2.0)
    await t.start()
    d = GyzaDiscovery(t.identity, t, auto_connect=True,
                      announce_interval_s=2.0)
    try:
        await d.start()
        # Wait long enough for at least one round of self-multicast.
        await asyncio.sleep(3.0)
        # Solo node knows about no peers other than itself, and certainly
        # never adds itself to the known map.
        assert t.identity.pubkey_hex not in {p.pubkey for p in d.known_peers()}
        assert not t.is_connected(t.identity.pubkey_hex)
    finally:
        await d.stop()
        await t.stop()
