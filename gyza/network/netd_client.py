"""
Python client for the gyza-netd Go daemon.

The daemon owns all global libp2p networking (DHT, NAT traversal,
gossip). The Python Gyza stack talks to it over a Unix-socket gRPC
channel — one client per Python process, lazy connection.

Why a separate process: see Phase 3 architecture notes. py-libp2p is
unmaintained and won't carry production NAT traversal; go-libp2p will.
The cost is one extra process per node and a gRPC hop for control-plane
calls. Data plane (the actual peer-to-peer bytes) never round-trips
through Python.

Session 1 surface: NodeService.GetNodeInfo / GetStatus, plus a daemon
launcher. Sessions 2–4 fill in the discovery / peer / gossip methods.
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

import grpc
import numpy as np

from gyza.network.proto import netd_pb2, netd_pb2_grpc


LOG = logging.getLogger("gyza.netd_client")


def _resolve(p: str) -> str:
    return os.path.expanduser(p)


# ---------------------------------------------------------------------------
# Plain-Python views of the gRPC types. Callers don't need to deal with
# protobuf-message instances unless they want to; these dataclasses keep
# the boundary clean.
# ---------------------------------------------------------------------------

@dataclass
class NodeInfo:
    peer_id: str
    compositor_pubkey: str
    listen_addrs: list[str]
    gyza_version: str

    @classmethod
    def from_proto(cls, m: "netd_pb2.NodeInfo") -> "NodeInfo":
        return cls(
            peer_id=m.peer_id,
            compositor_pubkey=m.compositor_pubkey,
            listen_addrs=list(m.listen_addrs),
            gyza_version=m.gyza_version,
        )


@dataclass
class NodeStatus:
    connected_peers: int
    dht_routing_table_size: int
    nat_traversal_available: bool
    observed_addr: str
    uptime_seconds: int

    @classmethod
    def from_proto(cls, m: "netd_pb2.NodeStatus") -> "NodeStatus":
        return cls(
            connected_peers=m.connected_peers,
            dht_routing_table_size=m.dht_routing_table_size,
            nat_traversal_available=m.nat_traversal_available,
            observed_addr=m.observed_addr,
            uptime_seconds=m.uptime_seconds,
        )


@dataclass
class ConnectResult:
    success: bool
    peer_id: str
    verified_pubkey: str
    error: str

    @classmethod
    def from_proto(cls, m: "netd_pb2.ConnectResult") -> "ConnectResult":
        return cls(
            success=m.success,
            peer_id=m.peer_id,
            verified_pubkey=m.verified_pubkey,
            error=m.error,
        )


@dataclass
class PeerInfo:
    peer_id: str
    compositor_pubkey: str
    multiaddr: str
    attestation_tier: int
    connected_at: int
    last_seen: int
    messages_sent: int
    messages_received: int

    @classmethod
    def from_proto(cls, m: "netd_pb2.PeerInfo") -> "PeerInfo":
        return cls(
            peer_id=m.peer_id,
            compositor_pubkey=m.compositor_pubkey,
            multiaddr=m.multiaddr,
            attestation_tier=m.attestation_tier,
            connected_at=m.connected_at,
            last_seen=m.last_seen,
            messages_sent=m.messages_sent,
            messages_received=m.messages_received,
        )


@dataclass
class AgentAdvertisement:
    """
    A globally-published advertisement for one agent. The wire format
    keeps the specialization embedding as bytes (float32 little-endian);
    this dataclass exposes it as np.ndarray so callers don't have to
    decode by hand.
    """
    agent_pubkey: str
    compositor_pubkey: str
    capability_manifest_hash: str
    specialization_embedding: np.ndarray  # shape (384,), dtype float32
    lsh_bucket: int                         # uint64-as-int64 (server-computed)
    attestation_tier: int
    reputation_score: float
    compute_credit_balance: int
    last_seen: int                          # ns since epoch
    ttl_seconds: int
    gyza_version: str = ""
    multiaddrs: list[str] = field(default_factory=list)

    @classmethod
    def from_proto(cls, m: "netd_pb2.AgentAdvertisement") -> "AgentAdvertisement":
        emb_bytes = m.specialization_embedding or b""
        if emb_bytes:
            emb = np.frombuffer(emb_bytes, dtype="<f4").astype(np.float32)
        else:
            emb = np.zeros(0, dtype=np.float32)
        return cls(
            agent_pubkey=m.agent_pubkey,
            compositor_pubkey=m.compositor_pubkey,
            capability_manifest_hash=m.capability_manifest_hash,
            specialization_embedding=emb,
            lsh_bucket=m.lsh_bucket,
            attestation_tier=m.attestation_tier,
            reputation_score=m.reputation_score,
            compute_credit_balance=m.compute_credit_balance,
            last_seen=m.last_seen,
            ttl_seconds=m.ttl_seconds,
            gyza_version=m.gyza_version,
            multiaddrs=list(m.multiaddrs),
        )

    def to_proto(self) -> "netd_pb2.AgentAdvertisement":
        emb = np.asarray(self.specialization_embedding, dtype=np.float32)
        if emb.shape != (384,):
            raise ValueError(
                f"specialization_embedding must be shape (384,), got {emb.shape}"
            )
        return netd_pb2.AgentAdvertisement(
            agent_pubkey=self.agent_pubkey,
            compositor_pubkey=self.compositor_pubkey,
            capability_manifest_hash=self.capability_manifest_hash,
            specialization_embedding=emb.astype("<f4").tobytes(),
            # lsh_bucket is recomputed server-side; we don't trust the
            # client-supplied value. Send 0; netd ignores it.
            lsh_bucket=0,
            attestation_tier=self.attestation_tier,
            reputation_score=self.reputation_score,
            compute_credit_balance=self.compute_credit_balance,
            last_seen=self.last_seen,
            ttl_seconds=self.ttl_seconds,
            gyza_version=self.gyza_version,
            multiaddrs=list(self.multiaddrs),
        )


# ---------------------------------------------------------------------------
# NetdClient
# ---------------------------------------------------------------------------

class NetdClient:
    """
    Thin gRPC client over a Unix domain socket.

    The channel is created lazily on first use. We don't try to keep
    the channel "warm" — gRPC reconnects automatically and the daemon
    restart loop relies on tear-down/rebuild semantics anyway.
    """

    def __init__(self, socket_path: str = "~/.gyza/netd.sock"):
        self._socket_path = _resolve(socket_path)
        self._channel: grpc.Channel | None = None

    # -- channel lifecycle ----------------------------------------------------

    def _ensure_channel(self) -> grpc.Channel:
        if self._channel is None:
            self._channel = grpc.insecure_channel(f"unix:{self._socket_path}")
        return self._channel

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
            self._channel = None

    def __enter__(self) -> "NetdClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- NodeService ---------------------------------------------------------

    def get_node_info(self) -> NodeInfo:
        stub = netd_pb2_grpc.NodeServiceStub(self._ensure_channel())
        return NodeInfo.from_proto(stub.GetNodeInfo(netd_pb2.Empty()))

    def get_status(self) -> NodeStatus:
        stub = netd_pb2_grpc.NodeServiceStub(self._ensure_channel())
        return NodeStatus.from_proto(stub.GetStatus(netd_pb2.Empty()))

    def is_running(self) -> bool:
        """
        True iff a gyza-netd is reachable at the configured socket. Used
        by the Python startup path to decide whether to spawn a daemon.
        Catches gRPC StatusErrors broadly — anything that prevents
        GetStatus from succeeding means the daemon is not usable.
        """
        try:
            self.get_status()
            return True
        except Exception:  # noqa: BLE001 — intentionally broad
            return False

    # -- DiscoveryService -----------------------------------------------------

    def publish_agent(self, ad: AgentAdvertisement) -> str:
        """
        Publish the advertisement to the global DHT. Returns the DHT
        key under which the bucket is stored (not the same as the
        agent_pubkey — the key is `/gyza/agents/{lsh_bucket_hex}`).

        Raises grpc.RpcError on transport failures or if the daemon
        rejected the input. A "DHT not reachable" condition (e.g.
        single-node test environment) is NOT an error here: the
        advertisement still lands in the daemon's local cache.
        """
        stub = netd_pb2_grpc.DiscoveryServiceStub(self._ensure_channel())
        result = stub.PublishAgent(ad.to_proto())
        if not result.success:
            raise RuntimeError(f"PublishAgent failed: {result.error}")
        return result.dht_key

    def find_agents(
        self,
        query_embedding: np.ndarray,
        k: int = 10,
        min_tier: int = 0,
        min_reputation: float = 0.0,
        timeout_s: float = 120.0,
    ) -> list[AgentAdvertisement]:
        """
        Stream up to k matching advertisements from the DHT, ordered
        by cosine similarity to query_embedding (descending).

        The query embedding must be float32 of shape (384,). Other
        dtypes are converted; other shapes raise ValueError.

        ``timeout_s`` bounds the entire call (DHT walk + streaming
        response). The daemon's FindAgents collects local-cache
        results AND walks the LSH-Hamming neighbor buckets (137
        keys at radius 2) BEFORE streaming anything to the client,
        so even local-cache hits are gated on the slowest DHT
        lookup. On sparse networks (3-peer mesh, no published
        agents) the worst-case walk plus per-result verify-on-fetch
        can take ~60-90s. Default 120s covers that with margin;
        raise for known-large networks, lower for small private
        ones. Returns whatever results streamed in before the
        deadline (possibly empty); does not raise on timeout.

        TODO: refactor the daemon to stream local-cache results
        immediately, before the DHT walk. Then this timeout could
        drop to ~10s without false negatives. Tracked as a Session
        33 follow-up.
        """
        emb = np.asarray(query_embedding, dtype=np.float32)
        if emb.shape != (384,):
            raise ValueError(
                f"query_embedding must be shape (384,), got {emb.shape}"
            )
        stub = netd_pb2_grpc.DiscoveryServiceStub(self._ensure_channel())
        req = netd_pb2.AgentQuery(
            query_embedding=emb.astype("<f4").tobytes(),
            k=k,
            min_tier=min_tier,
            min_reputation=min_reputation,
        )
        out: list[AgentAdvertisement] = []
        try:
            for proto_ad in stub.FindAgents(req, timeout=timeout_s):
                out.append(AgentAdvertisement.from_proto(proto_ad))
        except grpc.RpcError as e:
            # Deadline exceeded on a sparse-mesh DHT walk is the
            # expected outcome when no agents match the query — surface
            # whatever partial results we did collect rather than
            # raising. Re-raise other RPC errors.
            if e.code() != grpc.StatusCode.DEADLINE_EXCEEDED:
                raise
        return out

    def unpublish_agent(
        self,
        agent_pubkey: str,
        compositor_pubkey: str = "",
        signature: str = "",
    ) -> None:
        """
        Remove the agent from the daemon's local cache and re-publish
        the affected DHT buckets. Signature verification on the
        unpublish request is enforced strictly only after Session 5
        (proof-of-capability).
        """
        stub = netd_pb2_grpc.DiscoveryServiceStub(self._ensure_channel())
        stub.UnpublishAgent(netd_pb2.UnpublishRequest(
            agent_pubkey=agent_pubkey,
            compositor_pubkey=compositor_pubkey,
            signature=signature,
        ))

    # -- PeerService ----------------------------------------------------------

    def connect_peer(
        self,
        multiaddr: str,
        expected_pubkey: str = "",
    ) -> ConnectResult:
        """
        Dial a remote peer at the given multiaddr (e.g.
        ``/ip4/1.2.3.4/udp/7749/quic-v1/p2p/12D3KooW...``). NAT
        traversal is transparent inside gyza-netd: hole-punching and
        circuit-relay fall-back are configured at host construction.

        If ``expected_pubkey`` is non-empty, the daemon refuses to
        record a successful connection unless the peer's libp2p PeerID
        derives from that Ed25519 hex pubkey. This is how Phase 3 work
        guards against connecting to an attacker who has spoofed a
        multiaddr but cannot impersonate the compositor key.
        """
        stub = netd_pb2_grpc.PeerServiceStub(self._ensure_channel())
        result = stub.Connect(netd_pb2.ConnectRequest(
            multiaddr=multiaddr,
            expected_pubkey=expected_pubkey,
        ))
        return ConnectResult.from_proto(result)

    def disconnect_peer(self, peer_id: str) -> None:
        """Close all open connections to the peer. Best-effort."""
        stub = netd_pb2_grpc.PeerServiceStub(self._ensure_channel())
        stub.Disconnect(netd_pb2.DisconnectRequest(peer_id=peer_id))

    def list_peers(self) -> list[PeerInfo]:
        stub = netd_pb2_grpc.PeerServiceStub(self._ensure_channel())
        resp = stub.ListPeers(netd_pb2.Empty())
        return [PeerInfo.from_proto(p) for p in resp.peers]

    def get_peer_info(self, peer_id: str) -> PeerInfo:
        stub = netd_pb2_grpc.PeerServiceStub(self._ensure_channel())
        resp = stub.GetPeerInfo(netd_pb2.PeerInfoRequest(peer_id=peer_id))
        return PeerInfo.from_proto(resp)

    def get_observed_addr(self) -> str:
        """
        Return the externally-observable multiaddr learned via libp2p's
        identify exchange (and AutoNAT confirmation, if reachable).
        Empty string until a peer has identified with us — newly
        started single-node setups will see "" here.
        """
        return self.get_status().observed_addr

    # -- MessageService -------------------------------------------------------

    def send_message(
        self,
        peer_id: str,
        message_type: str,
        payload: bytes,
    ) -> bool:
        """
        Send a single (message_type, payload) frame to ``peer_id``
        via the daemon's libp2p stream protocol. Returns True on
        successful write, False on transport failure (peer offline,
        framing rejected, etc.). Raises grpc.RpcError on Unix-socket
        / gRPC-layer failures.

        Caller is responsible for serializing structured payloads
        (e.g. a ledger entry dict → JSON bytes). The daemon does
        not introspect payload contents.
        """
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError(
                f"payload must be bytes, got {type(payload).__name__}"
            )
        stub = netd_pb2_grpc.MessageServiceStub(self._ensure_channel())
        result = stub.Send(netd_pb2.SendRequest(
            peer_id=peer_id,
            message_type=message_type,
            payload=bytes(payload),
        ))
        if not result.success:
            LOG.warning("[netd_client] send_message %s -> %s failed: %s",
                        message_type, peer_id, result.error)
        return result.success

    def broadcast(
        self,
        message_type: str,
        payload: bytes,
        exclude_peer_ids: list[str] | None = None,
    ) -> int:
        """Send to every connected peer except those in
        ``exclude_peer_ids``. Returns the per-peer success count."""
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError(
                f"payload must be bytes, got {type(payload).__name__}"
            )
        stub = netd_pb2_grpc.MessageServiceStub(self._ensure_channel())
        result = stub.Broadcast(netd_pb2.BroadcastRequest(
            message_type=message_type,
            payload=bytes(payload),
            exclude_peer_ids=list(exclude_peer_ids or []),
        ))
        return result.delivered_count

    def subscribe_messages(
        self,
        message_types: list[str] | None = None,
    ) -> Iterator["netd_pb2.IncomingMessage"]:
        """
        Server-streaming subscription. Yields each incoming message
        whose type is in ``message_types`` (empty/None == all types).
        Returns when the gRPC stream is cancelled — daemon shutdown,
        channel close, or context cancellation.

        Yields raw IncomingMessage protos. Callers that want
        structured types (e.g. a deserialized LedgerEntry) deserialize
        from ``incoming.payload``.
        """
        stub = netd_pb2_grpc.MessageServiceStub(self._ensure_channel())
        req = netd_pb2.SubscribeRequest(
            message_types=list(message_types or []),
        )
        try:
            for incoming in stub.Subscribe(req):
                yield incoming
        except grpc.RpcError as e:
            code = getattr(e, "code", lambda: None)()
            if code in (
                grpc.StatusCode.CANCELLED,
                grpc.StatusCode.UNAVAILABLE,
            ):
                return
            raise

    # -- Daemon lifecycle helpers --------------------------------------------

    @staticmethod
    def start_daemon(
        socket_path: str = "~/.gyza/netd.sock",
        binary_path: str = "~/dev/gyza/netd/bin/gyza-netd",
        listen_port: int = 7749,
        key_path: str = "~/.gyza/compositor.key",
        bootstrap: list[str] | None = None,
        log_level: str = "info",
        startup_timeout_s: float = 5.0,
        stderr_to_stdout: bool = True,
        dht_mode: str | None = None,
        isolated: bool = False,
        mdns: bool = True,
    ) -> subprocess.Popen:
        """
        Launch gyza-netd as a subprocess. Block until the socket file
        appears (up to startup_timeout_s) so callers can immediately
        use the returned client without sleeping.

        binary_path / socket_path / key_path are tilde-expanded. We
        validate the binary exists up front (clearer error than
        FileNotFoundError from execve).

        ``isolated`` (default False) — when True, passes
        ``--bootstrap-domain=""`` and ``--no-fallback-peers`` so the
        spawned daemon does NOT dial the public gyza.network
        bootstrap mesh. Tests + the global-demo (single-machine
        Phase 3) should set this; production daemons (gyza global
        start) leave it False so they join the live mesh.
        """
        binary = _resolve(binary_path)
        if not os.path.isfile(binary):
            # Fall back to PATH lookup (e.g. an installed `gyza-netd`).
            on_path = shutil.which("gyza-netd")
            if on_path:
                binary = on_path
            else:
                raise FileNotFoundError(
                    f"gyza-netd (the Go network daemon) not found at "
                    f"{binary_path} and not on PATH.\n"
                    f"The pip package ships the Python client only. To get "
                    f"the daemon:\n"
                    f"  * from a source checkout: make -C netd build "
                    f"(needs Go)\n"
                    f"  * or put a gyza-netd binary on PATH, or set "
                    f"netd_binary_path in ~/.gyza/config.json\n"
                    f"Local commands (run/exec/audit/bundle/verify) work "
                    f"without it."
                )

        socket = _resolve(socket_path)
        key = _resolve(key_path)
        argv = [
            binary,
            "--socket-path", socket,
            "--listen-port", str(listen_port),
            "--key-path", key,
            "--log-level", log_level,
        ]
        if isolated:
            argv += ["--bootstrap-domain=", "--no-fallback-peers"]
        if not mdns:
            # Off-switch for the partition-simulation path in the demo:
            # on loopback, mDNS re-discovers a disconnected peer in
            # milliseconds and silently re-establishes the link, so any
            # observable "comms blackout" requires mDNS off.
            argv += ["--mdns=false"]
        if bootstrap:
            argv += ["--bootstrap", ",".join(bootstrap)]
        if dht_mode:
            # auto | server | client. Server mode is the right default
            # for integration tests where AutoNAT signaling can't promote
            # a daemon from Client to Server (loopback meshes); production
            # daemons should leave dht_mode=None so the default (auto)
            # adapts to real reachability.
            argv += ["--dht-mode", dht_mode]

        # Make sure a stale socket from a previous crashed daemon doesn't
        # masquerade as "ready". The daemon itself unlinks before bind,
        # but our wait loop polls existence — we want existence to mean
        # the new daemon has bound.
        try:
            if os.path.exists(socket):
                # Only remove if it's really a socket file.
                import stat as _stat
                mode = os.stat(socket).st_mode
                if _stat.S_ISSOCK(mode):
                    os.unlink(socket)
        except OSError:
            pass

        LOG.info("[netd_client] launching %s", " ".join(argv))
        # Detach the daemon so it survives the parent CLI's exit.
        # Pre-fix this used subprocess.PIPE for stdout but never read
        # from it; the daemon's stdout buffer eventually filled, the
        # daemon blocked on write, and when the parent exited the
        # daemon got SIGPIPE on its next log line. Now: stdout/stderr
        # → DEVNULL (production logs go through journald via the
        # systemd unit anyway), and start_new_session=True puts the
        # daemon in its own session so a parent SIGHUP doesn't reach
        # it. stderr_to_stdout is retained for API compatibility but
        # is effectively a no-op when the parent is short-lived.
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )

        deadline = time.monotonic() + startup_timeout_s
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                # Daemon died during startup. Surface what it said.
                out = proc.stdout.read() if proc.stdout else ""
                raise RuntimeError(
                    f"gyza-netd exited during startup (rc={proc.returncode}): {out}"
                )
            if os.path.exists(socket):
                # Quick readiness check via gRPC.
                try:
                    with NetdClient(socket) as c:
                        if c.is_running():
                            return proc
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.05)

        # Time out: kill the partially-started daemon to keep the test
        # environment clean.
        proc.kill()
        out = proc.stdout.read() if proc.stdout else ""
        raise TimeoutError(
            f"gyza-netd did not bind {socket} within {startup_timeout_s}s. "
            f"Output:\n{out}"
        )


# =============================================================================
# Gossip dataclasses — Phase 3 Session 4
# =============================================================================

@dataclass
class IntentRecord:
    intent_id: str
    goal_spec_json: str
    created_at_ns: int

    @classmethod
    def from_proto(cls, m) -> "IntentRecord":
        return cls(
            intent_id=m.intent_id,
            goal_spec_json=m.goal_spec_json,
            created_at_ns=m.created_at_ns,
        )

    def to_proto(self):
        return netd_pb2.IntentRecord(
            intent_id=self.intent_id,
            goal_spec_json=self.goal_spec_json,
            created_at_ns=self.created_at_ns,
        )


@dataclass
class WorkItemRecord:
    """
    Mirror of gyza.schema.WorkItem for the wire. We keep the embedding
    as bytes (float32 little-endian) on the wire and only decode when
    callers ask for an ndarray; that keeps the gossip path zero-allocation
    for the common case where deltas are forwarded without inspection.
    """
    id: str
    lineage_root: str
    parent_id: str
    description: str
    desc_embedding_bytes: bytes
    reward: float
    reward_updated_ns: int
    required_tier: int
    input_hashes_json: str
    output_spec_json: str
    streaming_ok: bool
    created_at_ns: int
    ttl_ns: int

    @classmethod
    def from_proto(cls, m) -> "WorkItemRecord":
        return cls(
            id=m.id,
            lineage_root=m.lineage_root,
            parent_id=m.parent_id,
            description=m.description,
            desc_embedding_bytes=m.desc_embedding,
            reward=m.reward,
            reward_updated_ns=m.reward_updated_ns,
            required_tier=m.required_tier,
            input_hashes_json=m.input_hashes_json,
            output_spec_json=m.output_spec_json,
            streaming_ok=m.streaming_ok,
            created_at_ns=m.created_at_ns,
            ttl_ns=m.ttl_ns,
        )

    def to_proto(self):
        return netd_pb2.WorkItemRecord(
            id=self.id,
            lineage_root=self.lineage_root,
            parent_id=self.parent_id,
            description=self.description,
            desc_embedding=self.desc_embedding_bytes,
            reward=self.reward,
            reward_updated_ns=self.reward_updated_ns,
            required_tier=self.required_tier,
            input_hashes_json=self.input_hashes_json,
            output_spec_json=self.output_spec_json,
            streaming_ok=self.streaming_ok,
            created_at_ns=self.created_at_ns,
            ttl_ns=self.ttl_ns,
        )

    def desc_embedding(self) -> np.ndarray:
        """Decode desc_embedding_bytes as a (384,) float32 ndarray."""
        return np.frombuffer(self.desc_embedding_bytes, dtype="<f4").astype(np.float32)


@dataclass
class ClaimUpdate:
    work_item_id: str
    agent_pubkey: str
    compositor_pubkey: str
    hlc_l: int
    hlc_c: int
    hlc_node: str

    @classmethod
    def from_proto(cls, m) -> "ClaimUpdate":
        return cls(
            work_item_id=m.work_item_id,
            agent_pubkey=m.agent_pubkey,
            compositor_pubkey=m.compositor_pubkey,
            hlc_l=m.hlc_l,
            hlc_c=m.hlc_c,
            hlc_node=m.hlc_node,
        )

    def to_proto(self):
        return netd_pb2.ClaimUpdate(
            work_item_id=self.work_item_id,
            agent_pubkey=self.agent_pubkey,
            compositor_pubkey=self.compositor_pubkey,
            hlc_l=self.hlc_l,
            hlc_c=self.hlc_c,
            hlc_node=self.hlc_node,
        )


@dataclass
class CompletionRecord:
    work_item_id: str
    output_hash: str
    icp_envelope_hash: str
    success: bool
    completed_at_ns: int
    completed_by_compositor_pubkey: str

    @classmethod
    def from_proto(cls, m) -> "CompletionRecord":
        return cls(
            work_item_id=m.work_item_id,
            output_hash=m.output_hash,
            icp_envelope_hash=m.icp_envelope_hash,
            success=m.success,
            completed_at_ns=m.completed_at_ns,
            completed_by_compositor_pubkey=m.completed_by_compositor_pubkey,
        )

    def to_proto(self):
        return netd_pb2.CompletionRecord(
            work_item_id=self.work_item_id,
            output_hash=self.output_hash,
            icp_envelope_hash=self.icp_envelope_hash,
            success=self.success,
            completed_at_ns=self.completed_at_ns,
            completed_by_compositor_pubkey=self.completed_by_compositor_pubkey,
        )


@dataclass
class BlackboardDelta:
    """
    A single cross-cluster blackboard sync unit. The daemon stamps
    sender_compositor_pubkey, sender_seq, timestamp_ns, and
    app_signature on publish — caller-provided values for those fields
    are ignored.
    """
    project_id: str
    sender_compositor_pubkey: str = ""
    sender_seq: int = 0
    timestamp_ns: int = 0
    new_intents: list[IntentRecord] = field(default_factory=list)
    new_items: list[WorkItemRecord] = field(default_factory=list)
    claim_updates: list[ClaimUpdate] = field(default_factory=list)
    completions: list[CompletionRecord] = field(default_factory=list)
    app_signature: bytes = b""

    @classmethod
    def from_proto(cls, m) -> "BlackboardDelta":
        return cls(
            project_id=m.project_id,
            sender_compositor_pubkey=m.sender_compositor_pubkey,
            sender_seq=m.sender_seq,
            timestamp_ns=m.timestamp_ns,
            new_intents=[IntentRecord.from_proto(i) for i in m.new_intents],
            new_items=[WorkItemRecord.from_proto(w) for w in m.new_items],
            claim_updates=[ClaimUpdate.from_proto(c) for c in m.claim_updates],
            completions=[CompletionRecord.from_proto(c) for c in m.completions],
            app_signature=bytes(m.app_signature),
        )

    def to_proto(self):
        return netd_pb2.BlackboardDelta(
            project_id=self.project_id,
            new_intents=[i.to_proto() for i in self.new_intents],
            new_items=[w.to_proto() for w in self.new_items],
            claim_updates=[c.to_proto() for c in self.claim_updates],
            completions=[c.to_proto() for c in self.completions],
        )


# =============================================================================
# GossipClient
# =============================================================================

class GossipClient:
    """
    Stream-friendly client for the GossipService gRPC interface.

    Owns its own gRPC channel — separate from NetdClient's — because
    SubscribeDeltas is a long-lived server-streaming RPC and we don't
    want a request-time NetdClient operation to fight it for the
    channel's HTTP/2 stream budget.
    """

    def __init__(self, socket_path: str = "~/.gyza/netd.sock"):
        self._socket_path = _resolve(socket_path)
        self._channel: grpc.Channel | None = None

    def _ensure(self) -> grpc.Channel:
        if self._channel is None:
            self._channel = grpc.insecure_channel(f"unix:{self._socket_path}")
        return self._channel

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
            self._channel = None

    def __enter__(self) -> "GossipClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def join_project(self, project_id: str) -> int:
        """Subscribe to a project topic. Returns the gossipsub mesh
        peer count at join time (often 0; mesh fills asynchronously)."""
        stub = netd_pb2_grpc.GossipServiceStub(self._ensure())
        result = stub.JoinProject(netd_pb2.JoinProjectRequest(project_id=project_id))
        if not result.success:
            raise RuntimeError(f"JoinProject failed: {result.error}")
        return result.mesh_peers

    def leave_project(self, project_id: str) -> None:
        stub = netd_pb2_grpc.GossipServiceStub(self._ensure())
        stub.LeaveProject(netd_pb2.LeaveProjectRequest(project_id=project_id))

    def list_projects(self) -> list[str]:
        stub = netd_pb2_grpc.GossipServiceStub(self._ensure())
        return list(stub.ListProjects(netd_pb2.Empty()).project_ids)

    def publish_delta(self, delta: BlackboardDelta) -> int:
        """
        Publish a delta. Daemon stamps identity + seq + timestamp +
        signature. Returns the assigned sender_seq.
        """
        stub = netd_pb2_grpc.GossipServiceStub(self._ensure())
        result = stub.PublishDelta(netd_pb2.PublishDeltaRequest(delta=delta.to_proto()))
        if not result.success:
            raise RuntimeError(f"PublishDelta failed: {result.error}")
        return result.sender_seq

    def subscribe_deltas(
        self,
        project_ids: list[str] | None = None,
    ) -> Iterator[BlackboardDelta]:
        """
        Server-streaming subscription. Yields each delta as a
        BlackboardDelta dataclass. Returns when the stream is cancelled
        (by gRPC channel close, daemon shutdown, or context cancel).

        Empty / None project_ids means "all joined projects".
        """
        stub = netd_pb2_grpc.GossipServiceStub(self._ensure())
        req = netd_pb2.SubscribeDeltasRequest(
            project_ids=list(project_ids or []),
        )
        try:
            for proto_delta in stub.SubscribeDeltas(req):
                yield BlackboardDelta.from_proto(proto_delta)
        except grpc.RpcError as e:
            # Treat normal shutdown (CANCELLED / UNAVAILABLE) as end-of-iter
            # rather than an exception. Anything else propagates.
            code = getattr(e, "code", lambda: None)()
            if code in (
                grpc.StatusCode.CANCELLED,
                grpc.StatusCode.UNAVAILABLE,
            ):
                return
            raise


# =============================================================================
# Capability dataclasses + client — Phase 3 Session 5
#
# Pythonside view of the sybil-resistance primitives. The daemon
# performs all signing / verification using the compositor key it
# already holds, so the Python surface is just request-shaped.
# =============================================================================


@dataclass
class Challenge:
    """A signed challenge issued by a Tier-3 validator. Fields mirror
    the proto Challenge; ChallengeBody is flattened into this dataclass
    for ergonomics."""
    challenger_pubkey: str
    applicant_pubkey: str
    task_ids: list[str]
    nonce: bytes
    issued_at_ns: int
    expires_at_ns: int
    challenger_signature: bytes
    raw_proto: object = None  # the underlying netd_pb2.Challenge for round-trips

    @classmethod
    def from_proto(cls, m) -> "Challenge":
        return cls(
            challenger_pubkey=m.body.challenger_pubkey,
            applicant_pubkey=m.body.applicant_pubkey,
            task_ids=list(m.body.task_ids),
            nonce=bytes(m.body.nonce),
            issued_at_ns=m.body.issued_at_ns,
            expires_at_ns=m.body.expires_at_ns,
            challenger_signature=bytes(m.challenger_signature),
            raw_proto=m,
        )


@dataclass
class CoSignature:
    validator_pubkey: str
    signature: bytes
    signed_at_ns: int

    @classmethod
    def from_proto(cls, m) -> "CoSignature":
        return cls(
            validator_pubkey=m.validator_pubkey,
            signature=bytes(m.signature),
            signed_at_ns=m.signed_at_ns,
        )

    def to_proto(self):
        return netd_pb2.CoSignature(
            validator_pubkey=self.validator_pubkey,
            signature=self.signature,
            signed_at_ns=self.signed_at_ns,
        )


@dataclass
class AttestationCert:
    """Decoded view of an AttestationCert. The raw_proto is preserved
    so callers can round-trip back through the gRPC layer without
    hand-rebuilding the body / cosignature shape."""
    applicant_pubkey: str
    issued_at_ns: int
    expires_at_ns: int
    tier_granted: int
    challenge_task_ids: list[str]
    co_signatures: list[CoSignature]
    raw_proto: object = None

    @classmethod
    def from_proto(cls, m) -> "AttestationCert":
        return cls(
            applicant_pubkey=m.body.applicant_pubkey,
            issued_at_ns=m.body.issued_at_ns,
            expires_at_ns=m.body.expires_at_ns,
            tier_granted=m.body.tier_granted,
            challenge_task_ids=list(m.body.challenge_task_ids),
            co_signatures=[CoSignature.from_proto(c) for c in m.co_signatures],
            raw_proto=m,
        )


class CapabilityClient:
    """
    Wraps the gRPC CapabilityService. Stateless — every call is a
    one-shot RPC. No background threads.

    Phase 3 surface only handles the in-process / single-daemon path:
    issue a challenge against a known applicant, verify a response,
    publish/fetch certs from the DHT. The cross-network "applicant
    contacts 3 validators over libp2p streams" orchestration lands
    in Session 7 — at that point the daemon adds a stream protocol
    handler and Python's request_attestation() drives the dance.
    """

    def __init__(self, socket_path: str = "~/.gyza/netd.sock"):
        self._socket_path = _resolve(socket_path)
        self._channel: grpc.Channel | None = None

    def _ensure(self) -> grpc.Channel:
        if self._channel is None:
            self._channel = grpc.insecure_channel(f"unix:{self._socket_path}")
        return self._channel

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
            self._channel = None

    def __enter__(self) -> "CapabilityClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def issue_challenge(
        self,
        applicant_pubkey_hex: str,
        task_ids: list[str] | None = None,
        ttl_seconds: int = 0,
    ) -> Challenge:
        stub = netd_pb2_grpc.CapabilityServiceStub(self._ensure())
        result = stub.IssueChallenge(netd_pb2.IssueChallengeRequest(
            applicant_pubkey=applicant_pubkey_hex,
            task_ids=list(task_ids or []),
            ttl_seconds=ttl_seconds,
        ))
        return Challenge.from_proto(result)

    def verify_response(
        self,
        challenge: Challenge,
        response_proto,  # netd_pb2.ChallengeResponse — caller's responsibility to build
    ) -> tuple[bool, CoSignature | None, str]:
        """
        Submit a response for verification. Returns
        (success, cosignature_or_none, error_message_or_empty).

        Caller builds the response_proto via the dataclass
        construction in tests; production callers will get this
        through the wire-protocol stream handler in Session 7.
        """
        stub = netd_pb2_grpc.CapabilityServiceStub(self._ensure())
        result = stub.VerifyResponse(netd_pb2.VerifyResponseRequest(
            challenge=challenge.raw_proto,
            response=response_proto,
        ))
        cosig = CoSignature.from_proto(result.co_signature) if result.success else None
        return result.success, cosig, result.error

    def publish_attestation(self, cert_proto) -> str:
        """Publish a netd_pb2.AttestationCert. Returns the DHT key on
        success. Raises RuntimeError on rejection."""
        stub = netd_pb2_grpc.CapabilityServiceStub(self._ensure())
        result = stub.PublishAttestation(cert_proto)
        if not result.success:
            raise RuntimeError(f"PublishAttestation failed: {result.error}")
        return result.dht_key

    def fetch_attestation(self, applicant_pubkey_hex: str) -> AttestationCert | None:
        """Returns the cert for the applicant or None if no cert
        exists in the DHT. Raises grpc.RpcError on transport failures."""
        stub = netd_pb2_grpc.CapabilityServiceStub(self._ensure())
        result = stub.FetchAttestation(netd_pb2.FetchAttestationRequest(
            applicant_pubkey=applicant_pubkey_hex,
        ))
        # Daemon returns an empty cert (body=None) for "not found" so
        # callers can distinguish from RPC errors.
        if not result.HasField("body"):
            return None
        return AttestationCert.from_proto(result)

    def verify_attestation(self, cert_proto) -> tuple[bool, int, str]:
        """Returns (valid, cosig_count, reason)."""
        stub = netd_pb2_grpc.CapabilityServiceStub(self._ensure())
        result = stub.VerifyAttestation(cert_proto)
        return result.valid, result.cosig_count, result.reason

    def request_attestation(
        self,
        target_peer_id: str,
        eval_callback: "Callable[[netd_pb2.Challenge], netd_pb2.ChallengeResponse]",
        timeout_s: float = 130.0,
    ) -> tuple[bool, "netd_pb2.CoSignature | None", str]:
        """
        Drive a Tier-3 cross-network attestation against ``target_peer_id``
        through the daemon. The daemon owns the libp2p stream to the
        validator; we own the eval execution. Frames pass through this
        gRPC bidirectional stream.

        ``eval_callback`` receives the validator's Challenge proto and
        must return a fully-signed ChallengeResponse proto. The callback
        is invoked exactly once per call, on whatever thread is running
        the request. It is responsible for:

          - signing each TaskResult's ICP envelope with an agent key
            issued by the applicant compositor,
          - signing the ResponseBody with the COMPOSITOR signing key
            (``LocalCompositor.sign``) — the libp2p PeerID is bound to
            the compositor key by Noise, so the validator verifies
            ApplicantSignature against the compositor pubkey,
          - serializing the body deterministically (proto marshal with
            sort-by-tag, which the Python protobuf library does by
            default for canonical serialization).

        Returns ``(success, cosignature_or_None, error_message_or_empty)``.
        ``timeout_s`` slightly exceeds the daemon's libp2p
        ``StreamTimeout=120s`` so the gRPC layer doesn't preempt the
        underlying flow's clean failure surface.

        Raises ``grpc.RpcError`` on transport failures (daemon down,
        socket dropped). Daemon-side protocol errors (bad target peer
        id, capability_stream not initialized) also surface here as
        RpcError — they're not encoded as outcome frames because they
        occur before the bridge can ferry anything.
        """
        request_q: "queue.Queue[netd_pb2.AttestationApplicantFrame | None]" = queue.Queue()
        request_q.put(netd_pb2.AttestationApplicantFrame(
            start=netd_pb2.AttestationStartRequest(target_peer_id=target_peer_id),
        ))

        def _request_iterator():
            while True:
                # Block forever — the loop body will sentinel-terminate
                # via None when we're done. There's no soft timeout here
                # because the gRPC call's `timeout=` parameter bounds
                # the WHOLE round trip from outside.
                item = request_q.get()
                if item is None:
                    return
                yield item

        stub = netd_pb2_grpc.CapabilityServiceStub(self._ensure())
        response_iter = stub.RequestAttestation(
            _request_iterator(), timeout=timeout_s,
        )

        outcome: "netd_pb2.VerifyResponseResult | None" = None
        try:
            for frame in response_iter:
                which = frame.WhichOneof("body")
                if which == "challenge":
                    # Validator chose tasks; we run them now.
                    response = eval_callback(frame.challenge)
                    if response is None:
                        # eval_callback opted out — close the stream
                        # cleanly. Daemon's libp2p stream will time
                        # out and surface as a "read response" error
                        # in the outcome. We never see it because we
                        # break and tear down.
                        raise RuntimeError(
                            "eval_callback returned None — refusing to send"
                        )
                    request_q.put(netd_pb2.AttestationApplicantFrame(response=response))
                elif which == "outcome":
                    # Final frame. Daemon closes after this; the iter
                    # raises StopIteration on the next pull, which the
                    # for-loop catches.
                    outcome = frame.outcome
                else:
                    # Unknown body — daemon side bug or version skew.
                    # Treat as a structured failure.
                    return False, None, f"unexpected daemon frame: {which!r}"
        finally:
            # Sentinel terminates the request iterator generator,
            # letting the underlying gRPC half-close cleanly. If we're
            # exiting via exception (eval_callback raised), the daemon
            # gets stream-cancelled by gRPC's own machinery — clean.
            request_q.put(None)

        if outcome is None:
            return False, None, "stream closed without outcome"
        if outcome.success:
            return True, outcome.co_signature, ""
        return False, None, outcome.error


__all__ = [
    "NetdClient",
    "NodeInfo",
    "NodeStatus",
    "AgentAdvertisement",
    "ConnectResult",
    "PeerInfo",
    "GossipClient",
    "BlackboardDelta",
    "IntentRecord",
    "WorkItemRecord",
    "ClaimUpdate",
    "CompletionRecord",
    "CapabilityClient",
    "Challenge",
    "CoSignature",
    "AttestationCert",
]
