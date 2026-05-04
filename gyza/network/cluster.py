"""
Cluster lifecycle: discovery → transport handshake → cluster join →
Raft formation → NetworkBlackboard activation.

`GyzaCluster.start_local()` runs the node alone with no networking.
`GyzaCluster.start_lan()` brings up QUIC transport + mDNS discovery,
broadcasts cluster-join requests to discovered peers, and once at
least one peer accepts, materializes a Raft cluster and attaches it
to the supplied NetworkBlackboard.

The join protocol is intentionally minimal:

    initiator → cluster_join_request {raft_addr, gyza_version}
    responder → cluster_join_response {accept: bool, raft_addr}

Once `_pending_members` is non-empty after `formation_timeout_s`, we
construct a `GyzaRaftNode` with the agreed partner list and call
`blackboard.attach_raft(...)`. Trade-off: this implementation does not
re-form the Raft cluster as more peers join later — it's one-shot
formation followed by `addNodeToCluster()` for late arrivals (Phase 3).
"""
from __future__ import annotations

import asyncio
import logging
import socket

from gyza.config import GyzaConfig
from gyza.identity import AgentIdentity
from gyza.network.discovery import DiscoveredPeer, GyzaDiscovery
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.network.raft import GyzaRaftNode
from gyza.network.transport import GyzaTransport
from gyza.network.trust_registry import TrustRegistry


LOG = logging.getLogger("gyza.cluster")


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class GyzaCluster:
    def __init__(
        self,
        identity: AgentIdentity,
        blackboard: NetworkBlackboard,
        config: GyzaConfig,
        trust_registry: TrustRegistry | None = None,
    ):
        self.identity = identity
        self._blackboard = blackboard
        self._config = config
        self._trust = trust_registry or TrustRegistry()
        self._transport: GyzaTransport | None = None
        self._discovery: GyzaDiscovery | None = None
        self._raft: GyzaRaftNode | None = None
        self._pending_members: list[dict] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_local(self) -> None:
        LOG.info("[cluster] started in local mode")

    async def start_lan(self, formation_timeout_s: float = 15.0) -> None:
        quic_port = getattr(self._config, "quic_port", 7749)
        self._transport = GyzaTransport(self.identity, listen_port=quic_port)
        await self._transport.start()
        self._transport.register_handler(
            "cluster_join_request", self._handle_join_request,
        )
        self._transport.register_handler(
            "cluster_join_response", self._handle_join_response,
        )
        self._transport.register_handler(
            "compositor_pubkey_exchange", self._handle_compositor_pubkey_exchange,
        )

        self._discovery = GyzaDiscovery(
            self.identity, self._transport, auto_connect=True,
        )
        await self._discovery.start()

        await asyncio.sleep(formation_timeout_s)
        peers = self._discovery.live_peers()
        if peers:
            await self._form_cluster(peers)
        else:
            LOG.info("[cluster] no peers found, running solo on LAN")

    async def leave(self) -> None:
        if self._transport is not None:
            try:
                await self._transport.broadcast(
                    "peer_leaving", {"pubkey": self.identity.pubkey_hex},
                )
            except Exception:
                pass
            await self._transport.stop()
            self._transport = None
        if self._discovery is not None:
            await self._discovery.stop()
            self._discovery = None
        if self._raft is not None:
            try:
                self._raft.destroy()
            except Exception:
                pass
            self._raft = None
            self._blackboard.detach_raft()

    # ------------------------------------------------------------------
    # Formation
    # ------------------------------------------------------------------

    async def _form_cluster(self, peers: list[DiscoveredPeer]) -> None:
        LOG.info("[cluster] forming cluster with %d peers", len(peers))

        raft_port = getattr(self._config, "raft_port", 8749)
        my_raft_addr = f"{_local_ip()}:{raft_port}"

        for peer in peers:
            assert self._transport is not None
            await self._transport.send(
                peer.pubkey,
                "cluster_join_request",
                {"raft_addr": my_raft_addr, "gyza_version": "0.2.0"},
            )

        # Collect responses for up to 10s, then move on with what we have.
        await asyncio.sleep(10.0)

        if not self._pending_members:
            LOG.warning("[cluster] no peers accepted, running solo")
            return

        partner_addrs = [m["raft_addr"] for m in self._pending_members]
        raft_node = GyzaRaftNode(
            self_addr=my_raft_addr,
            partner_addrs=partner_addrs,
            blackboard=self._blackboard,
            identity=self.identity,
            journal_dir=None,
        )
        self._blackboard.attach_raft(raft_node)
        self._raft = raft_node
        LOG.info(
            "[cluster] formed with %d members", len(partner_addrs) + 1,
        )

        # Exchange compositor pubkeys with every peer that joined. The
        # transport handshake already proved each peer controls its
        # pubkey, so add_trusted_compositor() is safe here. Peers do
        # the same in reverse on receipt.
        for member in self._pending_members:
            try:
                self._trust.add_trusted_compositor(
                    pubkey=member["pubkey"],
                    peer_ip=member.get("raft_addr", "").split(":")[0] or "",
                    gyza_version="0.2.0",
                )
            except ValueError as e:
                LOG.warning(
                    "[cluster] refused to trust peer pubkey: %s", e,
                )
            try:
                assert self._transport is not None
                await self._transport.send(
                    member["pubkey"],
                    "compositor_pubkey_exchange",
                    {"pubkey": self.identity.pubkey_hex,
                     "gyza_version": "0.2.0"},
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_join_request(self, sender_pubkey: str, payload: dict) -> None:
        raft_addr_remote = payload.get("raft_addr")
        if not isinstance(raft_addr_remote, str):
            return
        raft_port = getattr(self._config, "raft_port", 8749)
        my_raft_addr = f"{_local_ip()}:{raft_port}"
        assert self._transport is not None
        await self._transport.send(
            sender_pubkey,
            "cluster_join_response",
            {"accept": True, "raft_addr": my_raft_addr},
        )
        self._pending_members.append({
            "raft_addr": raft_addr_remote, "pubkey": sender_pubkey,
        })

    async def _handle_join_response(self, sender_pubkey: str, payload: dict) -> None:
        if not payload.get("accept"):
            return
        raft_addr = payload.get("raft_addr")
        if isinstance(raft_addr, str):
            self._pending_members.append({
                "raft_addr": raft_addr, "pubkey": sender_pubkey,
            })

    async def _handle_compositor_pubkey_exchange(
        self, sender_pubkey: str, payload: dict,
    ) -> None:
        # The transport's hello/hello_ack already proved sender_pubkey
        # owns the connection; the payload's `pubkey` should match.
        # We trust sender_pubkey directly and ignore the payload field
        # if it disagrees (defensive: a confused peer can't widen trust).
        claimed = payload.get("pubkey")
        if claimed and claimed != sender_pubkey:
            LOG.warning(
                "[cluster] pubkey-exchange disagreement: sender=%s, payload=%s",
                sender_pubkey[:8], (claimed or "")[:8],
            )
            return
        version = payload.get("gyza_version", "")
        try:
            self._trust.add_trusted_compositor(
                pubkey=sender_pubkey,
                peer_ip="",
                gyza_version=str(version),
            )
        except ValueError as e:
            LOG.warning("[cluster] refused to trust pubkey: %s", e)


__all__ = ["GyzaCluster"]
