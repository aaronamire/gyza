"""
LAN peer discovery via mDNS.

A Gyza node announces a `_gyza._udp.local.` service whose TXT record
carries the compositor pubkey, QUIC port, attestation tier, agent
count, and a freshness timestamp. Other nodes on the same LAN listen
for that service type, dedupe by pubkey, and (optionally) hand the
discovered (ip, port) to `GyzaTransport.connect()` for the
challenge-response auth handshake.

mDNS gets us zero-config discovery. It does NOT get us identity —
the TXT record's pubkey is unverified at this layer. Anyone can
broadcast any pubkey they want. The transport's authentication
handshake is what catches lies; if a node announces pubkey X but
can't sign a nonce as X, the connection is dropped before any
application data flows.

Persistence: `export_peers_json()` writes the known-peer list so a
restarted node can attempt to reconnect immediately without waiting
for the next mDNS announcement cycle.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from zeroconf import IPVersion, ServiceListener
from zeroconf.asyncio import (
    AsyncServiceBrowser,
    AsyncServiceInfo,
    AsyncZeroconf,
)

from gyza.identity import AgentIdentity
from gyza.network.transport import GyzaTransport


LOG = logging.getLogger("gyza.discovery")
SERVICE_TYPE = "_gyza._udp.local."


# ---------------------------------------------------------------------------
# Discovered peer record
# ---------------------------------------------------------------------------

@dataclass
class DiscoveredPeer:
    pubkey: str
    ip: str
    port: int
    tier: int
    agent_count: int
    discovered_at_ns: int
    last_seen_ns: int


# ---------------------------------------------------------------------------
# Listener — forwards zeroconf thread events into our event loop
# ---------------------------------------------------------------------------

class _Listener(ServiceListener):
    """Bridge from zeroconf's internal thread back to the asyncio loop.

    zeroconf invokes `add_service` / `remove_service` / `update_service`
    synchronously from its own thread; we schedule the actual work as a
    coroutine on the loop that owns the GyzaDiscovery instance.
    """

    def __init__(self, discovery: "GyzaDiscovery", loop: asyncio.AbstractEventLoop):
        self._discovery = discovery
        self._loop = loop

    def add_service(self, zc, service_type: str, name: str) -> None:
        asyncio.run_coroutine_threadsafe(
            self._discovery._on_service_added_by_name(service_type, name),
            self._loop,
        )

    def update_service(self, zc, service_type: str, name: str) -> None:
        asyncio.run_coroutine_threadsafe(
            self._discovery._on_service_added_by_name(service_type, name),
            self._loop,
        )

    def remove_service(self, zc, service_type: str, name: str) -> None:
        asyncio.run_coroutine_threadsafe(
            self._discovery._on_service_removed_by_name(name),
            self._loop,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_props(raw: dict[bytes, bytes | None]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        try:
            key = k.decode("utf-8") if isinstance(k, bytes) else str(k)
        except UnicodeDecodeError:
            continue
        if v is None:
            out[key] = ""
        elif isinstance(v, bytes):
            try:
                out[key] = v.decode("utf-8")
            except UnicodeDecodeError:
                out[key] = ""
        else:
            out[key] = str(v)
    return out


def _best_local_ip() -> str:
    """Pick the LAN IP the OS would use to reach the wider network.

    Falls back to 127.0.0.1 if there's no route — the discovery still
    works on loopback for same-host integration tests.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------------------
# GyzaDiscovery
# ---------------------------------------------------------------------------

class GyzaDiscovery:
    def __init__(
        self,
        identity: AgentIdentity,
        transport: GyzaTransport,
        auto_connect: bool = True,
        announce_interval_s: float = 60.0,
    ):
        self.identity = identity
        self._transport = transport
        self._auto_connect = auto_connect
        self._announce_interval_s = announce_interval_s

        self._service_name = f"gyza-{identity.pubkey_hex[:16]}.{SERVICE_TYPE}"
        self._zc: AsyncZeroconf | None = None
        self._service_info: AsyncServiceInfo | None = None
        self._browser: AsyncServiceBrowser | None = None
        self._reannounce_task: asyncio.Task | None = None
        self._known: dict[str, DiscoveredPeer] = {}
        self._connect_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        self._service_info = self._build_service_info()
        await self._zc.async_register_service(self._service_info)

        listener = _Listener(self, self._loop)
        self._browser = AsyncServiceBrowser(
            self._zc.zeroconf, SERVICE_TYPE, listener=listener,
        )
        self._reannounce_task = asyncio.create_task(self._reannounce_loop())
        LOG.info(
            "[discovery] announcing on LAN as %s...", self.identity.pubkey_hex[:8],
        )

    async def stop(self) -> None:
        if self._reannounce_task is not None:
            self._reannounce_task.cancel()
            try:
                await self._reannounce_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reannounce_task = None

        if self._browser is not None:
            try:
                await self._browser.async_cancel()
            except Exception:
                pass
            self._browser = None

        if self._zc is not None:
            try:
                if self._service_info is not None:
                    await self._zc.async_unregister_service(self._service_info)
            except Exception:
                pass
            try:
                await self._zc.async_close()
            except Exception:
                pass
            self._zc = None
            self._service_info = None

    # ------------------------------------------------------------------
    # Public introspection
    # ------------------------------------------------------------------

    def known_peers(self) -> list[DiscoveredPeer]:
        return list(self._known.values())

    def live_peers(self) -> list[DiscoveredPeer]:
        threshold_ns = int(self._announce_interval_s * 3 * 1_000_000_000)
        now = time.time_ns()
        return [
            p for p in self._known.values()
            if (now - p.last_seen_ns) <= threshold_ns
        ]

    # ------------------------------------------------------------------
    # mDNS service info (announcement record)
    # ------------------------------------------------------------------

    def _build_service_info(self) -> AsyncServiceInfo:
        ip = _best_local_ip()
        properties: dict[str, str] = {
            "pubkey": self.identity.pubkey_hex,
            "port": str(self._transport._listen_port),
            "version": "1",
            "tier": str(self.identity.manifest.get("attestation_tier", 1)),
            "agents": str(len(self._transport.connected_peers())),
            "timestamp": str(int(time.time())),
        }
        # Server name must be unique on the LAN; embed pubkey prefix.
        server = f"gyza-{self.identity.pubkey_hex[:16]}.local."
        return AsyncServiceInfo(
            type_=SERVICE_TYPE,
            name=self._service_name,
            addresses=[socket.inet_aton(ip)],
            port=self._transport._listen_port,
            properties=properties,
            server=server,
        )

    # ------------------------------------------------------------------
    # mDNS event handlers
    # ------------------------------------------------------------------

    async def _on_service_added_by_name(self, service_type: str, name: str) -> None:
        if self._zc is None:
            return
        # Resolve TXT + addresses for this service.
        info = AsyncServiceInfo(service_type, name)
        ok = await info.async_request(self._zc.zeroconf, 3000)
        if not ok:
            return

        properties = _decode_props(info.properties or {})
        pubkey = properties.get("pubkey", "")
        if not pubkey:
            return

        # Filter out our own announcement.
        if pubkey == self.identity.pubkey_hex:
            return

        # Resolve IP. async_request populates `info.addresses` with packed
        # bytes; parsed_addresses() converts them to dotted strings.
        addresses = info.parsed_addresses() if hasattr(info, "parsed_addresses") else []
        ip = addresses[0] if addresses else ""
        if not ip and info.addresses:
            try:
                ip = socket.inet_ntoa(info.addresses[0])
            except OSError:
                ip = ""
        if not ip:
            return

        try:
            port = int(properties.get("port", str(info.port or 0)))
            tier = int(properties.get("tier", "1"))
            agent_count = int(properties.get("agents", "0"))
        except ValueError:
            return

        now_ns = time.time_ns()
        existing = self._known.get(pubkey)
        if existing is not None:
            existing.last_seen_ns = now_ns
            existing.ip = ip
            existing.port = port
            existing.agent_count = agent_count
            existing.tier = tier
        else:
            self._known[pubkey] = DiscoveredPeer(
                pubkey=pubkey, ip=ip, port=port, tier=tier,
                agent_count=agent_count,
                discovered_at_ns=now_ns,
                last_seen_ns=now_ns,
            )
            LOG.info(
                "[discovery] found peer %s... at %s:%d", pubkey[:8], ip, port,
            )

        if self._auto_connect and not self._transport.is_connected(pubkey):
            # Serialize connect attempts so two simultaneous announcements
            # don't race the transport's duplicate-connect check.
            async with self._connect_lock:
                if self._transport.is_connected(pubkey):
                    return
                try:
                    await self._transport.connect((ip, port), timeout_s=10.0)
                except Exception as e:  # noqa: BLE001
                    LOG.warning(
                        "[discovery] connect to %s failed: %s", pubkey[:8], e,
                    )

    async def _on_service_removed_by_name(self, name: str) -> None:
        # Service names look like  gyza-{pubkey[:16]}._gyza._udp.local.
        # Match by the 16-char prefix back to our known peers.
        if not name.startswith("gyza-"):
            return
        try:
            prefix = name[5:5 + 16]
        except IndexError:
            return
        for pubkey, peer in list(self._known.items()):
            if pubkey[:16] == prefix:
                peer.last_seen_ns = 0  # force-evict from live_peers
                LOG.info("[discovery] peer %s... left the network", pubkey[:8])
                return

    async def _reannounce_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._announce_interval_s)
            except asyncio.CancelledError:
                return
            if self._zc is None:
                return
            try:
                # Rebuild the service info with current agent count + freshness
                # timestamp, then update the existing announcement in place.
                self._service_info = self._build_service_info()
                await self._zc.async_update_service(self._service_info)
            except Exception as e:  # noqa: BLE001
                LOG.debug("re-announce failed: %s", e)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def export_peers_json(self) -> str:
        return json.dumps(
            [asdict(p) for p in self._known.values()],
            indent=2, sort_keys=True,
        )

    def import_peers_json(self, data: str) -> int:
        try:
            entries = json.loads(data)
        except json.JSONDecodeError:
            return 0
        if not isinstance(entries, list):
            return 0
        n = 0
        for d in entries:
            if not isinstance(d, dict):
                continue
            try:
                p = DiscoveredPeer(**d)
            except TypeError:
                continue
            self._known[p.pubkey] = p
            n += 1
        return n


__all__ = ["GyzaDiscovery", "DiscoveredPeer", "SERVICE_TYPE"]
