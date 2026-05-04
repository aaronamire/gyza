from __future__ import annotations

import asyncio
import socket
import time

import pytest
import pytest_asyncio

from gyza.identity import AgentIdentity, LocalCompositor
from gyza.network.transport import GyzaTransport


pytestmark = pytest.mark.asyncio


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
        agent_type=label,
        model_path="mock",
        fs_read_paths=[],
        fs_write_paths=[],
        attestation_tier=1,
    )
    return AgentIdentity(seed, manifest)


@pytest_asyncio.fixture
async def two_nodes(tmp_path):
    a = GyzaTransport(_identity(tmp_path, "a"), listen_port=_free_port(),
                      heartbeat_interval_s=0.2)
    b = GyzaTransport(_identity(tmp_path, "b"), listen_port=_free_port(),
                      heartbeat_interval_s=0.2)
    await a.start()
    await b.start()
    try:
        yield a, b
    finally:
        await a.stop()
        await b.stop()


async def _wait(predicate, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_mutual_auth(two_nodes):
    a, b = two_nodes
    peer = await a.connect(("127.0.0.1", b._listen_port), timeout_s=5.0)
    assert peer is not None, "connect returned None"
    assert peer.remote_pubkey == b.identity.pubkey_hex

    # Wait for the responder side to register the peer too.
    assert await _wait(lambda: a.identity.pubkey_hex in {p.remote_pubkey for p in b.connected_peers()})

    a_peers = a.connected_peers()
    b_peers = b.connected_peers()
    assert any(p.remote_pubkey == b.identity.pubkey_hex for p in a_peers)
    assert any(p.remote_pubkey == a.identity.pubkey_hex for p in b_peers)
    assert a.is_connected(b.identity.pubkey_hex)
    assert b.is_connected(a.identity.pubkey_hex)


async def test_send_receive(two_nodes):
    a, b = two_nodes

    received: list[tuple[str, dict]] = []
    got = asyncio.Event()

    async def handler(sender_pubkey: str, payload: dict) -> None:
        received.append((sender_pubkey, payload))
        got.set()

    b.register_handler("ping", handler)

    peer = await a.connect(("127.0.0.1", b._listen_port), timeout_s=5.0)
    assert peer is not None
    # Wait for both sides to register.
    assert await _wait(lambda: a.identity.pubkey_hex in {p.remote_pubkey for p in b.connected_peers()})

    ok = await a.send(b.identity.pubkey_hex, "ping", {"hello": "world", "n": 42})
    assert ok is True

    await asyncio.wait_for(got.wait(), timeout=3.0)
    assert len(received) == 1
    sender, payload = received[0]
    assert sender == a.identity.pubkey_hex
    assert payload == {"hello": "world", "n": 42}


async def test_broadcast(tmp_path):
    a = GyzaTransport(_identity(tmp_path, "a"), listen_port=_free_port(),
                      heartbeat_interval_s=0.2)
    b = GyzaTransport(_identity(tmp_path, "b"), listen_port=_free_port(),
                      heartbeat_interval_s=0.2)
    c = GyzaTransport(_identity(tmp_path, "c"), listen_port=_free_port(),
                      heartbeat_interval_s=0.2)
    await a.start(); await b.start(); await c.start()
    try:
        b_got = asyncio.Event()
        c_got = asyncio.Event()
        b_msgs: list = []
        c_msgs: list = []

        async def b_handler(sender, payload):
            b_msgs.append((sender, payload))
            b_got.set()

        async def c_handler(sender, payload):
            c_msgs.append((sender, payload))
            c_got.set()

        b.register_handler("ann", b_handler)
        c.register_handler("ann", c_handler)

        assert await a.connect(("127.0.0.1", b._listen_port), timeout_s=5.0) is not None
        assert await a.connect(("127.0.0.1", c._listen_port), timeout_s=5.0) is not None
        assert await _wait(lambda: a.identity.pubkey_hex in {p.remote_pubkey for p in b.connected_peers()})
        assert await _wait(lambda: a.identity.pubkey_hex in {p.remote_pubkey for p in c.connected_peers()})

        sent = await a.broadcast("ann", {"k": "v"})
        assert sent == 2

        await asyncio.wait_for(b_got.wait(), timeout=3.0)
        await asyncio.wait_for(c_got.wait(), timeout=3.0)

        assert len(b_msgs) == 1 and b_msgs[0][1] == {"k": "v"}
        assert len(c_msgs) == 1 and c_msgs[0][1] == {"k": "v"}

        # Exclusion: broadcast skipping b should reach only c.
        c_msgs.clear(); c_got.clear(); b_msgs.clear(); b_got.clear()
        sent = await a.broadcast("ann", {"k": "v2"}, exclude=[b.identity.pubkey_hex])
        assert sent == 1
        await asyncio.wait_for(c_got.wait(), timeout=3.0)
        assert len(c_msgs) == 1
        assert len(b_msgs) == 0
    finally:
        await a.stop(); await b.stop(); await c.stop()


async def test_heartbeat_timeout(tmp_path):
    a = GyzaTransport(_identity(tmp_path, "a"), listen_port=_free_port(),
                      heartbeat_interval_s=0.15)
    b = GyzaTransport(_identity(tmp_path, "b"), listen_port=_free_port(),
                      heartbeat_interval_s=0.15)
    await a.start(); await b.start()
    try:
        peer = await a.connect(("127.0.0.1", b._listen_port), timeout_s=5.0)
        assert peer is not None
        assert a.is_connected(b.identity.pubkey_hex)

        # Drop B abruptly. A's heartbeat loop sees no traffic from B and
        # within 3x interval (~0.45s) decides B is gone.
        await b.stop()

        ok = await _wait(lambda: not a.is_connected(b.identity.pubkey_hex), timeout=4.0)
        assert ok, "A did not evict B after heartbeat timeout"
    finally:
        await a.stop()


async def test_wrong_pubkey_rejected(tmp_path):
    """A peer whose hello carries a fake pubkey + invalid signature is
    dropped at the application-layer handshake."""
    import secrets
    import ssl
    import struct
    import json
    from aioquic.asyncio import connect as quic_connect
    from aioquic.asyncio.protocol import QuicConnectionProtocol
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import HandshakeCompleted, StreamDataReceived

    target = GyzaTransport(_identity(tmp_path, "target"), listen_port=_free_port(),
                           heartbeat_interval_s=10.0)
    await target.start()

    received_app = asyncio.Event()

    async def handler(sender, payload):
        received_app.set()

    target.register_handler("any", handler)

    class _AttackerProto(QuicConnectionProtocol):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._sid: int | None = None
            self._closed = asyncio.Event()
            self._sent_invalid_app = asyncio.Event()

        def quic_event_received(self, event):
            if isinstance(event, HandshakeCompleted):
                # Open a stream; send a hello with a syntactically valid
                # pubkey but an invalid (random) signature in response.
                self._sid = self._quic.get_next_available_stream_id()
                fake_pk = "ab" * 32
                fake_nonce = secrets.token_bytes(32)
                msg = json.dumps({
                    "type": "hello",
                    "pubkey": fake_pk,
                    "nonce": fake_nonce.hex(),
                }).encode("utf-8")
                self._quic.send_stream_data(
                    self._sid, struct.pack(">I", len(msg)) + msg, end_stream=False,
                )
                self.transmit()
            elif isinstance(event, StreamDataReceived):
                # Receive responder's hello with a real signature on
                # OUR nonce. We don't have the real responder key, so
                # we reply with a junk hello_ack — this is what should
                # get rejected.
                if self._sid is None:
                    self._sid = event.stream_id
                # Try sending a malformed hello_ack with bogus signature.
                bad = json.dumps({
                    "type": "hello_ack",
                    "pubkey": "ab" * 32,
                    "response": "00" * 64,  # not a valid Ed25519 sig
                }).encode("utf-8")
                self._quic.send_stream_data(
                    self._sid, struct.pack(">I", len(bad)) + bad, end_stream=False,
                )
                self.transmit()
                # Try sending an unauthenticated app message — must NOT
                # reach the registered handler.
                app = json.dumps({
                    "type": "any",
                    "sender": "ab" * 32,
                    "payload": {"smuggled": True},
                }).encode("utf-8")
                self._quic.send_stream_data(
                    self._sid, struct.pack(">I", len(app)) + app, end_stream=False,
                )
                self.transmit()
                self._sent_invalid_app.set()

    config = QuicConfiguration(is_client=True, alpn_protocols=["gyza/1"])
    config.verify_mode = ssl.CERT_NONE

    try:
        async with quic_connect(
            "127.0.0.1", target._listen_port,
            configuration=config,
            create_protocol=lambda *a, **k: _AttackerProto(*a, **k),
        ) as proto:
            # Give the attack time to run and the responder time to
            # reject. We expect the connection to be dropped without
            # the app handler ever firing.
            await asyncio.sleep(1.0)
    except Exception:
        # Connection drop during attack is fine.
        pass

    assert not received_app.is_set(), (
        "fake-pubkey peer reached app handler — auth was bypassed!"
    )
    # And no entry should have appeared in target's peer table.
    pks = {p.remote_pubkey for p in target.connected_peers()}
    assert "ab" * 32 not in pks

    await target.stop()
