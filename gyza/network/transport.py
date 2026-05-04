"""
Authenticated peer-to-peer QUIC transport for Gyza Phase 2.

QUIC requires TLS, so each transport generates a throwaway RSA-2048
self-signed certificate just to satisfy the TLS handshake. Real peer
identity is established by an application-layer challenge-response
above QUIC streams using the compositor Ed25519 key — the same key
that signs ICP envelopes. There is no separate PKI; the compositor
pubkey IS the node identity.

Wire format (single bidirectional stream per connection):
    [4-byte big-endian length][UTF-8 JSON bytes]
Max frame: 4 MiB. Oversize frames close the connection.

Authentication handshake (initiator = client, responder = server):

    initiator → {type:"hello",     pubkey, nonce_i}
    responder → {type:"hello",     pubkey, nonce_r,
                 response: Sign_r(nonce_i)}
    initiator → {type:"hello_ack", pubkey,
                 response: Sign_i(nonce_r)}

After both sides verify the other's Ed25519 signature over their own
nonce, the connection is authenticated. Anything else gets dropped.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import secrets
import ssl
import struct
import tempfile
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from aioquic.asyncio import connect, serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import (
    ConnectionTerminated,
    HandshakeCompleted,
    StreamDataReceived,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.x509.oid import NameOID

from gyza.identity import AgentIdentity


LOG = logging.getLogger("gyza.transport")
ALPN = ["gyza/1"]
MAX_MESSAGE_SIZE = 4 * 1024 * 1024
HANDSHAKE_TIMEOUT_S = 10.0


# ---------------------------------------------------------------------------
# Throwaway TLS certificate
# ---------------------------------------------------------------------------

def _generate_throwaway_cert() -> tuple[bytes, bytes]:
    """RSA-2048 self-signed cert. Real identity lives in the application
    layer; this exists only so QUIC's TLS-1.3 handshake completes."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "gyza-transport-throwaway")]
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(private_key=key, algorithm=hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )


# ---------------------------------------------------------------------------
# Peer connection record
# ---------------------------------------------------------------------------

@dataclass
class PeerConnection:
    remote_pubkey: str
    remote_addr: tuple
    connected_at: int
    last_seen_ns: int
    messages_sent: int = 0
    messages_received: int = 0
    # Internal — not part of the public PeerConnection contract
    _protocol: "GyzaProtocol | None" = field(default=None, repr=False, compare=False)


# ---------------------------------------------------------------------------
# QUIC protocol with auth + framed JSON
# ---------------------------------------------------------------------------

class GyzaProtocol(QuicConnectionProtocol):
    def __init__(self, *args, gyza: "GyzaTransport", is_initiator: bool, **kwargs):
        super().__init__(*args, **kwargs)
        self._gyza = gyza
        self._is_initiator = is_initiator
        self._stream_id: int | None = None
        self._buffer = b""
        self._authenticated = False
        self._auth_event = asyncio.Event()
        self._closed_event = asyncio.Event()
        self._remote_pubkey: str | None = None
        self._remote_pubkey_pending: str | None = None
        self._our_nonce = secrets.token_bytes(32)

    # -- aioquic event hook --------------------------------------------

    def quic_event_received(self, event):
        if isinstance(event, HandshakeCompleted):
            if self._is_initiator:
                # Client opens the stream and fires the first hello.
                self._stream_id = self._quic.get_next_available_stream_id()
                self._send_frame({
                    "type": "hello",
                    "pubkey": self._gyza.identity.pubkey_hex,
                    "nonce": self._our_nonce.hex(),
                })
        elif isinstance(event, StreamDataReceived):
            if self._stream_id is None:
                # Server-side: adopt whatever stream the client opened.
                self._stream_id = event.stream_id
            self._buffer += event.data
            self._drain_frames()
            if event.end_stream:
                self._close_with(reason="stream end")
        elif isinstance(event, ConnectionTerminated):
            self._auth_event.set()
            self._closed_event.set()
            if self._remote_pubkey is not None:
                self._gyza._on_peer_disconnected(self._remote_pubkey)

    # -- framing --------------------------------------------------------

    def _send_frame(self, msg: dict) -> bool:
        if self._stream_id is None:
            return False
        body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_MESSAGE_SIZE:
            LOG.warning("[transport] refusing to send oversize frame %d", len(body))
            return False
        try:
            self._quic.send_stream_data(
                self._stream_id, struct.pack(">I", len(body)) + body, end_stream=False,
            )
            self.transmit()
        except Exception as e:
            LOG.warning("[transport] send failed: %s", e)
            return False
        return True

    def _drain_frames(self) -> None:
        while len(self._buffer) >= 4:
            (size,) = struct.unpack(">I", self._buffer[:4])
            if size > MAX_MESSAGE_SIZE:
                LOG.warning("[transport] oversize frame %d, closing", size)
                self._close_with(reason="oversize")
                return
            if len(self._buffer) < 4 + size:
                return
            payload = self._buffer[4:4 + size]
            self._buffer = self._buffer[4 + size:]
            try:
                msg = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                LOG.warning("[transport] malformed JSON, closing")
                self._close_with(reason="malformed")
                return
            if not isinstance(msg, dict) or "type" not in msg:
                self._close_with(reason="bad shape")
                return
            self._dispatch(msg)

    def _close_with(self, reason: str) -> None:
        if not self._closed_event.is_set():
            try:
                self._quic.close(error_code=0, reason_phrase=reason[:100])
                self.transmit()
            except Exception:
                pass
            self._auth_event.set()
            self._closed_event.set()

    # -- dispatch -------------------------------------------------------

    def _dispatch(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "hello":
            self._handle_hello(msg)
            return
        if t == "hello_ack":
            self._handle_hello_ack(msg)
            return

        if not self._authenticated:
            LOG.warning(
                "[transport] rejected unauthenticated peer (got %s before auth)", t,
            )
            self._close_with(reason="unauthenticated")
            return

        # Authenticated app message.
        self._gyza._touch_peer(self._remote_pubkey, received=True)
        sender = msg.get("sender") or self._remote_pubkey
        payload = msg.get("payload", {})
        if not isinstance(payload, dict):
            payload = {"_raw": payload}
        asyncio.ensure_future(
            self._gyza._dispatch_app_message(t, sender, payload)
        )

    def _handle_hello(self, msg: dict) -> None:
        pubkey_hex = msg.get("pubkey")
        nonce_hex = msg.get("nonce")
        if not isinstance(pubkey_hex, str) or not isinstance(nonce_hex, str):
            LOG.warning("[transport] rejected unauthenticated peer (bad hello shape)")
            self._close_with(reason="bad hello"); return
        try:
            pk_bytes = bytes.fromhex(pubkey_hex)
            their_nonce = bytes.fromhex(nonce_hex)
        except ValueError:
            LOG.warning("[transport] rejected unauthenticated peer (bad hex)")
            self._close_with(reason="bad hello hex"); return
        if len(pk_bytes) != 32 or len(their_nonce) != 32:
            LOG.warning("[transport] rejected unauthenticated peer (bad sizes)")
            self._close_with(reason="bad hello sizes"); return
        if pubkey_hex == self._gyza.identity.pubkey_hex:
            LOG.warning("[transport] rejected unauthenticated peer (self loopback)")
            self._close_with(reason="self loopback"); return

        if self._is_initiator:
            # Initiator already sent its hello; this is the responder's
            # hello with response = Sign(initiator_nonce).
            response_hex = msg.get("response")
            if not isinstance(response_hex, str):
                LOG.warning("[transport] rejected unauthenticated peer (missing response)")
                self._close_with(reason="missing response"); return
            try:
                sig = bytes.fromhex(response_hex)
                Ed25519PublicKey.from_public_bytes(pk_bytes).verify(sig, self._our_nonce)
            except Exception:
                LOG.warning(
                    "[transport] rejected unauthenticated peer %s (bad sig)",
                    pubkey_hex[:8],
                )
                self._close_with(reason="bad sig"); return
            # Auth succeeds for the initiator.
            self._remote_pubkey = pubkey_hex
            self._authenticated = True
            self._send_frame({
                "type": "hello_ack",
                "pubkey": self._gyza.identity.pubkey_hex,
                "response": self._gyza.identity.sign_bytes(their_nonce),
            })
            self._gyza._on_peer_authenticated(self, pubkey_hex)
            self._auth_event.set()
        else:
            # Responder: sign initiator's nonce and emit our hello.
            self._remote_pubkey_pending = pubkey_hex
            self._send_frame({
                "type": "hello",
                "pubkey": self._gyza.identity.pubkey_hex,
                "nonce": self._our_nonce.hex(),
                "response": self._gyza.identity.sign_bytes(their_nonce),
            })

    def _handle_hello_ack(self, msg: dict) -> None:
        if self._is_initiator:
            LOG.warning("[transport] rejected unauthenticated peer (unexpected ack)")
            self._close_with(reason="unexpected hello_ack"); return
        if self._remote_pubkey_pending is None:
            LOG.warning("[transport] rejected unauthenticated peer (ack without hello)")
            self._close_with(reason="ack without hello"); return
        response_hex = msg.get("response")
        if not isinstance(response_hex, str):
            LOG.warning("[transport] rejected unauthenticated peer (missing ack response)")
            self._close_with(reason="missing ack response"); return
        try:
            sig = bytes.fromhex(response_hex)
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(self._remote_pubkey_pending)
            ).verify(sig, self._our_nonce)
        except Exception:
            LOG.warning(
                "[transport] rejected unauthenticated peer %s (bad ack sig)",
                self._remote_pubkey_pending[:8],
            )
            self._close_with(reason="bad ack sig"); return
        self._remote_pubkey = self._remote_pubkey_pending
        self._authenticated = True
        self._gyza._on_peer_authenticated(self, self._remote_pubkey)
        self._auth_event.set()

    # -- public-ish API used by GyzaTransport --------------------------

    async def wait_authenticated(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._auth_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return self._authenticated

    def send_app(self, msg_type: str, payload: dict) -> bool:
        if not self._authenticated or self._closed_event.is_set():
            return False
        ok = self._send_frame({
            "type": msg_type,
            "sender": self._gyza.identity.pubkey_hex,
            "timestamp_ns": time.time_ns(),
            "payload": payload,
        })
        if ok:
            self._gyza._touch_peer(self._remote_pubkey, sent=True)
        return ok


# ---------------------------------------------------------------------------
# Outbound connection holder
# ---------------------------------------------------------------------------

class _OutboundConnection:
    def __init__(self, host: str, port: int, config: QuicConfiguration, factory):
        self._host = host
        self._port = port
        self._config = config
        self._factory = factory
        self._proto: GyzaProtocol | None = None
        self._proto_ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            async with connect(
                self._host, self._port,
                configuration=self._config,
                create_protocol=self._factory,
            ) as proto:
                self._proto = proto
                self._proto_ready.set()
                # Hold the context manager open until either we're told
                # to stop or the connection terminates on its own.
                stop_wait = asyncio.create_task(self._stop.wait())
                close_wait = asyncio.create_task(proto._closed_event.wait())
                done, pending = await asyncio.wait(
                    [stop_wait, close_wait], return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
        except Exception as e:
            LOG.warning("[transport] outbound connection failed: %s", e)
        finally:
            self._proto_ready.set()  # unblock waiters even on failure

    async def wait_ready(self, timeout: float) -> GyzaProtocol | None:
        try:
            await asyncio.wait_for(self._proto_ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return self._proto

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                self._task.cancel()


# ---------------------------------------------------------------------------
# GyzaTransport
# ---------------------------------------------------------------------------

class GyzaTransport:
    def __init__(
        self,
        identity: AgentIdentity,
        listen_port: int = 7749,
        heartbeat_interval_s: float = 5.0,
    ):
        self.identity = identity
        self._listen_port = listen_port
        self._heartbeat_interval_s = heartbeat_interval_s
        self._peers: dict[str, PeerConnection] = {}
        self._handlers: dict[str, Callable[[str, dict], Awaitable[None]]] = {}
        self._outbound: dict[str, _OutboundConnection] = {}
        self._server = None
        self._heartbeat_task: asyncio.Task | None = None
        self._stopped = False

        self._cert_pem, self._key_pem = _generate_throwaway_cert()
        self._tmpdir = tempfile.TemporaryDirectory(prefix="gyza-transport-")
        self._cert_path = os.path.join(self._tmpdir.name, "cert.pem")
        self._key_path = os.path.join(self._tmpdir.name, "key.pem")
        with open(self._cert_path, "wb") as f:
            f.write(self._cert_pem)
        with open(self._key_path, "wb") as f:
            f.write(self._key_pem)
        os.chmod(self._key_path, 0o600)

        # Heartbeat handler — registered last so user handlers can override.
        self._handlers["heartbeat"] = self._handle_heartbeat

    # -- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        config = QuicConfiguration(
            is_client=False, alpn_protocols=ALPN, max_datagram_frame_size=65536,
        )
        config.load_cert_chain(self._cert_path, self._key_path)
        config.verify_mode = ssl.CERT_NONE

        gyza = self

        def factory(*args, **kwargs):
            return GyzaProtocol(*args, gyza=gyza, is_initiator=False, **kwargs)

        self._server = await serve(
            host="0.0.0.0",
            port=self._listen_port,
            configuration=config,
            create_protocol=factory,
        )
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        self._stopped = True
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None

        # Close outbound holders first.
        for holder in list(self._outbound.values()):
            await holder.close()
        self._outbound.clear()

        # Close inbound peers.
        for peer in list(self._peers.values()):
            if peer._protocol is not None:
                peer._protocol._close_with(reason="shutdown")
        self._peers.clear()

        if self._server is not None:
            self._server.close()
            self._server = None

        try:
            self._tmpdir.cleanup()
        except OSError:
            pass

    # -- outbound -------------------------------------------------------

    async def connect(
        self, addr: tuple, timeout_s: float = 10.0,
    ) -> PeerConnection | None:
        host, port = addr
        config = QuicConfiguration(
            is_client=True, alpn_protocols=ALPN, max_datagram_frame_size=65536,
        )
        config.verify_mode = ssl.CERT_NONE

        gyza = self

        def factory(*args, **kwargs):
            return GyzaProtocol(*args, gyza=gyza, is_initiator=True, **kwargs)

        holder = _OutboundConnection(host, port, config, factory)
        holder.start()

        proto = await holder.wait_ready(timeout=timeout_s)
        if proto is None:
            await holder.close()
            return None

        ok = await proto.wait_authenticated(timeout=timeout_s)
        if not ok or proto._remote_pubkey is None:
            await holder.close()
            return None

        remote_pk = proto._remote_pubkey
        existing = self._peers.get(remote_pk)
        if existing is not None and existing._protocol is not proto:
            # We already had a connection; drop the duplicate and return
            # the original.
            await holder.close()
            return existing

        self._outbound[remote_pk] = holder
        # _on_peer_authenticated has already populated self._peers; refresh
        # the address since the holder owns the actual remote.
        if remote_pk in self._peers:
            self._peers[remote_pk].remote_addr = (host, port)
        return self._peers.get(remote_pk)

    # -- send -----------------------------------------------------------

    async def send(self, remote_pubkey: str, message_type: str, payload: dict) -> bool:
        peer = self._peers.get(remote_pubkey)
        if peer is None or peer._protocol is None:
            return False
        return peer._protocol.send_app(message_type, payload)

    async def broadcast(
        self, message_type: str, payload: dict, exclude: list[str] | None = None,
    ) -> int:
        excluded = set(exclude or ())
        sent = 0
        for pk, peer in list(self._peers.items()):
            if pk in excluded or peer._protocol is None:
                continue
            if peer._protocol.send_app(message_type, payload):
                sent += 1
        return sent

    # -- handlers -------------------------------------------------------

    def register_handler(
        self,
        message_type: str,
        handler: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        if message_type in ("hello", "hello_ack"):
            raise ValueError(f"reserved message type: {message_type}")
        self._handlers[message_type] = handler

    # -- introspection --------------------------------------------------

    def connected_peers(self) -> list[PeerConnection]:
        return list(self._peers.values())

    def is_connected(self, remote_pubkey: str) -> bool:
        return remote_pubkey in self._peers

    # -- internal callbacks --------------------------------------------

    def _on_peer_authenticated(self, proto: GyzaProtocol, remote_pubkey: str) -> None:
        # If we already had a record (e.g., outbound auth completed
        # before .connect() returned), keep it and just update.
        existing = self._peers.get(remote_pubkey)
        addr = ("?", 0)
        try:
            sock = proto._transport.get_extra_info("peername")
            if sock:
                addr = (sock[0], sock[1])
        except Exception:
            pass
        now = time.time_ns()
        if existing is None:
            self._peers[remote_pubkey] = PeerConnection(
                remote_pubkey=remote_pubkey,
                remote_addr=addr,
                connected_at=now,
                last_seen_ns=now,
                _protocol=proto,
            )
        else:
            existing._protocol = proto
            existing.last_seen_ns = now
            existing.remote_addr = addr

    def _on_peer_disconnected(self, remote_pubkey: str) -> None:
        self._peers.pop(remote_pubkey, None)
        holder = self._outbound.pop(remote_pubkey, None)
        if holder is not None:
            holder._stop.set()

    def _touch_peer(self, remote_pubkey: str | None, *, sent: bool = False, received: bool = False) -> None:
        if remote_pubkey is None:
            return
        peer = self._peers.get(remote_pubkey)
        if peer is None:
            return
        peer.last_seen_ns = time.time_ns()
        if sent:
            peer.messages_sent += 1
        if received:
            peer.messages_received += 1

    async def _dispatch_app_message(self, msg_type: str, sender: str, payload: dict) -> None:
        handler = self._handlers.get(msg_type)
        if handler is None:
            LOG.debug("[transport] no handler for %s from %s", msg_type, sender[:8])
            return
        try:
            await handler(sender, payload)
        except Exception as e:
            LOG.exception("[transport] handler for %s raised: %s", msg_type, e)

    # -- heartbeat ------------------------------------------------------

    async def _handle_heartbeat(self, sender: str, payload: dict) -> None:
        # Touch already happened in _dispatch; nothing else to do.
        return None

    async def _heartbeat_loop(self) -> None:
        timeout_ns = int(self._heartbeat_interval_s * 3 * 1_000_000_000)
        while not self._stopped:
            try:
                await asyncio.sleep(self._heartbeat_interval_s)
            except asyncio.CancelledError:
                return
            now = time.time_ns()
            await self.broadcast("heartbeat", {"sent_at_ns": now})
            for pk, peer in list(self._peers.items()):
                if now - peer.last_seen_ns > timeout_ns:
                    LOG.warning("[transport] lost peer %s...", pk[:8])
                    if peer._protocol is not None:
                        peer._protocol._close_with(reason="heartbeat timeout")
                    self._peers.pop(pk, None)
                    holder = self._outbound.pop(pk, None)
                    if holder is not None:
                        await holder.close()


__all__ = ["GyzaTransport", "PeerConnection"]
