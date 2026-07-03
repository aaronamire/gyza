"""
Phase 3 Session 7 — global cluster orchestrator.

GlobalCluster is the top-level Phase 3 object. It owns:

  * the gyza-netd lifecycle (spawn / detect / reconnect)
  * a NetdClient + GossipClient + LedgerSettlementService + PeerRegistry
  * the bridge from local NetworkBlackboard to global gossip
  * the "form a project with strangers" workflow

What GlobalCluster does NOT own:
  * Raft (Phase 2 — GyzaCluster handles LAN consistency)
  * Agent execution loops (AgentRunner)
  * Capability manifest issuance (LocalCompositor)

Project-formation protocol (cross-internet, two strangers):

    A queries DHT for agents matching needed specializations.
    A connects to B's compositor pubkey via NAT-aware PeerService.
    A and B exchange attestation cert hashes.
    A verifies B's attestation (DHT cert + co-signatures).
    A and B both join the gossip topic for the project.
    A posts intent to local blackboard → propagates via gossip.
    B's agents claim and execute → ICP envelopes signed.
    Settlement service exchanges bilateral ledger entries.

Failure modes treated:
  * netd not built / dies → start_daemon raises FileNotFoundError, caller
    can either pre-build or fall back to local-only mode.
  * No DHT peers found for a specialization → empty list, caller decides
    whether to proceed local-only.
  * NAT traversal fails → connect_with_nat returns success=False; we
    skip that peer and continue with the rest.
  * Attestation absent → treated as Tier 0 (still connectable).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from gyza.config import GyzaConfig
from gyza.economy.ledger import ComputeLedger
from gyza.economy.settlement import LedgerSettlementService
from gyza.identity import LocalCompositor
from gyza.network.daemon_supervisor import DaemonSupervisor
from gyza.network.netd_client import (
    AgentAdvertisement,
    GossipClient,
    NetdClient,
)
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.network.peer_cache import PeerCache
from gyza.network.peer_registry import PeerRegistry


LOG = logging.getLogger("gyza.global_cluster")


# Observability hooks for whole-cluster gauges. The peer-count gauges
# are point-in-time samples drawn from netd.get_status; the credit
# gauge is drawn from the local ledger. Refresh is opportunistic (on
# publish_agents) rather than on a timer so we don't add yet another
# background goroutine — the call cadence (TTL/2) is already
# adequate for an operator's dashboard.
try:
    from gyza.observability import (
        CONNECTED_PEERS as _CONNECTED_PEERS,
        DHT_PEER_COUNT as _DHT_PEER_COUNT,
        LEDGER_NET_CREDITS as _LEDGER_NET_CREDITS,
    )

    def _obs_dht_peers(n: int) -> None:
        _DHT_PEER_COUNT.set(n)

    def _obs_connected_peers(n: int) -> None:
        _CONNECTED_PEERS.set(n)

    def _obs_net_credits(v: float) -> None:
        _LEDGER_NET_CREDITS.set(v)
except Exception:  # noqa: BLE001
    def _obs_dht_peers(n: int) -> None:  # type: ignore[misc]
        pass

    def _obs_connected_peers(n: int) -> None:  # type: ignore[misc]
        pass

    def _obs_net_credits(v: float) -> None:  # type: ignore[misc]
        pass


@dataclass
class AgentDescriptor:
    """
    What GlobalCluster needs to know about a locally-running agent
    in order to advertise it on the DHT. Caller (typically the runner
    layer) builds these and feeds them via ``set_agents()``.
    """
    agent_pubkey: str
    capability_manifest_hash: str
    specialization: np.ndarray  # shape (384,), float32, L2-normalized
    attestation_tier: int = 1
    reputation_score: float = 1.0


@dataclass
class ProjectMembership:
    """
    Tracks the per-project state for participants we discovered and
    onboarded via find_and_collaborate. Used by settle_project_ledger
    to know which peers' ledgers to reconcile against.
    """
    project_id: str
    started_at_ns: int = field(default_factory=time.time_ns)
    member_compositor_pubkeys: set[str] = field(default_factory=set)


class GlobalCluster:
    """
    Phase 3 entry point. Wraps the gyza-netd daemon and exposes a
    high-level "find some agents and start collaborating" surface.

    Use:
        gc = GlobalCluster(compositor, config, blackboard)
        await gc.start()
        peers = await gc.find_and_collaborate(
            project_id="alpha",
            required_specializations=[spec_vec],
            min_tier=1,
        )
        # ... post intents, agents claim, etc.
        summary = await gc.settle_project_ledger("alpha")
        await gc.stop()

    Tests inject pre-built NetdClient / GossipClient instances via the
    constructor to avoid spawning a daemon. The orchestration logic is
    independent of how the clients were obtained.
    """

    def __init__(
        self,
        compositor: LocalCompositor,
        config: GyzaConfig,
        blackboard: NetworkBlackboard,
        ledger: ComputeLedger | None = None,
        envelope_resolver: Callable[[str], "str | None"] | None = None,
        # Test seam — when injected, start() skips daemon spawn and
        # uses these clients directly.
        netd_client: NetdClient | None = None,
        gossip_client: GossipClient | None = None,
        # Factory for the attestation client. Defaults to opening a
        # CapabilityClient against the netd socket. Tests inject a
        # mock so attestation calls don't try to reach a daemon.
        capability_client_factory: Callable[[], Any] | None = None,
        # Optional dynamic agent provider. Returns the current set of
        # agents this node is willing to advertise on the DHT. Refreshed
        # on each call to publish_agents — agents that come and go
        # (per-task spawns) need this rather than a static list.
        agents_provider: Callable[[], list[AgentDescriptor]] | None = None,
        # Optional persistent peer cache. When supplied, start() attempts
        # to redial every cached (compositor_pubkey, multiaddr) pair
        # before the first peer-resolution request can race past it,
        # and successful connect_peer calls in find_and_collaborate write
        # back to the cache. Tests pass None to skip filesystem state.
        peer_cache: PeerCache | None = None,
        # Optional daemon supervisor. When supplied, GlobalCluster owns
        # neither the subprocess nor the NetdClient — both come from
        # the supervisor — and the supervisor's on_respawn callback is
        # wired to re-publish DHT advertisements, re-attempt cached
        # peer reconnects, and re-join active project gossip topics
        # whenever the daemon is restarted under us.
        # Mutually exclusive with ``netd_client``.
        supervisor: DaemonSupervisor | None = None,
    ):
        self._compositor = compositor
        self._config = config
        self._blackboard = blackboard
        self._ledger = ledger or ComputeLedger(
            compositor, db_path=config.netd_ledger_db_path,
        )
        # An envelope resolver is required for settlement (the payer
        # needs to know what icp_envelope_hash we recorded for a
        # given work_item_id). Default to NetworkBlackboard's lookup.
        self._envelope_resolver = (
            envelope_resolver or self._default_envelope_resolver
        )

        # Daemon lifecycle.
        if supervisor is not None and netd_client is not None:
            raise ValueError(
                "GlobalCluster: supervisor and netd_client are mutually "
                "exclusive — pick one"
            )
        self._supervisor = supervisor
        self._netd_proc = None
        self._netd_owns_process = (
            netd_client is None and gossip_client is None and supervisor is None
        )
        self._netd: NetdClient | None = netd_client
        self._gossip: GossipClient | None = gossip_client

        # Built in start().
        self._registry: PeerRegistry | None = None
        self._settlement: LedgerSettlementService | None = None

        self._agents_provider = agents_provider or (lambda: [])
        self._capability_client_factory = capability_client_factory
        self._peer_cache = peer_cache
        self._projects: dict[str, ProjectMembership] = {}
        self._started = False
        # Background DHT re-publish loop. Started by start(); stopped
        # by stop(). Period is config-driven so tests can run faster
        # than the 30-minute production default.
        self._republish_interval_s = 1800.0  # TTL/2, default
        self._republish_task: "asyncio.Task | None" = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the daemon (if not already running), open clients, build
        the peer registry + settlement service. Idempotent — calling
        twice is a no-op.
        """
        if self._started:
            return

        # If a supervisor was supplied, it owns the spawn and the
        # NetdClient; we just borrow them.
        if self._supervisor is not None:
            self._supervisor.set_on_respawn(self._on_daemon_respawn)
            self._supervisor.start()
            self._netd = self._supervisor.client

        # If clients weren't injected, spawn the daemon and connect.
        if self._netd is None:
            socket_path = self._config.resolved_paths()["netd_socket_path"]
            # Probe an existing daemon at the configured socket. If the
            # user already has gyza-netd running, we attach to it
            # rather than spawning a competitor (which would trip the
            # "address already in use" failure on listen-port bind).
            probe = NetdClient(socket_path)
            if probe.is_running():
                LOG.info("[global] attaching to existing netd at %s", socket_path)
                self._netd = probe
                self._netd_owns_process = False
            else:
                probe.close()
                LOG.info("[global] spawning netd at %s", socket_path)
                self._netd_proc = NetdClient.start_daemon(
                    socket_path=socket_path,
                    binary_path=self._config.netd_binary_path,
                    listen_port=self._config.netd_listen_port,
                    key_path=self._config.compositor_key_path,
                    bootstrap=self._config.netd_bootstrap_peers,
                    log_level="info",
                    startup_timeout_s=10.0,
                )
                self._netd = NetdClient(socket_path)

        if self._gossip is None:
            socket_path = self._config.resolved_paths()["netd_socket_path"]
            self._gossip = GossipClient(socket_path)

        self._registry = PeerRegistry(self._netd)
        # Audit-before-cosign: active only when the blackboard has a
        # content-addressed store to hold evidence AND the config opts in
        # (default True). Where no store is present (pure-coordination
        # nodes, legacy tests), settlement keeps its historical behavior
        # — the protocol checks alone — so this is additive, not a
        # behavior change for anyone without an artifact store.
        evidence_store = getattr(self._blackboard, "_artifact_store", None)
        acceptance_policy = None
        if evidence_store is not None and getattr(
            self._config, "settlement_audit_before_cosign", True
        ):
            from gyza.economy.settlement import AuditAcceptancePolicy
            acceptance_policy = AuditAcceptancePolicy(
                self._blackboard, evidence_store,
            )
            LOG.info("[global] settlement audit-before-cosign: ENABLED")
        self._settlement = LedgerSettlementService(
            ledger=self._ledger,
            netd=self._netd,
            envelope_resolver=self._envelope_resolver,
            acceptance_policy=acceptance_policy,
            evidence_store=evidence_store,
        )
        self._settlement.start()

        # Sanity: the daemon's compositor pubkey must match ours, else
        # any signing / settlement will desync silently. We're talking
        # to a daemon that holds a DIFFERENT key — almost always a
        # configuration mistake (wrong key_path or stale daemon).
        info = self._netd.get_node_info()
        if info.compositor_pubkey and info.compositor_pubkey != self._compositor.pubkey_hex:
            LOG.warning(
                "[global] netd compositor pubkey %s does not match local %s; "
                "ledger entries may be unsignable",
                info.compositor_pubkey[:16],
                self._compositor.pubkey_hex[:16],
            )

        # Persistent peer cache reconnects BEFORE we mark started=True
        # — anyone calling settlement.send_message must see a
        # peer_id-resolvable correspondent the moment they think the
        # cluster is up. Failures inside the sweep are non-fatal
        # (returns count of redialed peers), so we never block startup
        # behind an offline peer that happens to be in the cache.
        if self._peer_cache is not None:
            try:
                redialed = self._peer_cache.attempt_reconnect_all(self._netd)
                LOG.info(
                    "[global] peer cache: redialed %d peer(s)", redialed,
                )
            except Exception as e:  # noqa: BLE001
                LOG.warning("[global] peer cache reconnect threw: %s", e)

        self._started = True
        LOG.info(
            "[global] started peer_id=%s observed=%s",
            info.peer_id, self._netd.get_status().observed_addr or "(none)",
        )

        # DHT advertisements have a TTL (3600s in publish_agents). The
        # daemon's go-libp2p-kad-dht expires records after their TTL,
        # so without a periodic re-publish, every locally-running agent
        # disappears from the global view 1 hour after start. We
        # re-publish at TTL/2 so a single-cycle miss (network blip,
        # daemon restart on the local node) doesn't drop us off the
        # DHT — there's always a fresh record in flight.
        try:
            self._republish_task = asyncio.create_task(
                self._republish_loop(),
                name="gyza-global-republish",
            )
        except RuntimeError:
            # No running loop (e.g. tests calling start() via asyncio.run).
            # That's fine — the test path doesn't need the loop running
            # for hours. Production callers run inside a long-lived loop.
            self._republish_task = None

    async def stop(self) -> None:
        if not self._started:
            return

        # Cancel the re-publish loop first — its sleeps are awaitable
        # and will wake immediately on cancel. Doing this before
        # closing clients avoids a race where the loop's next tick
        # tries to publish on a closed channel.
        if self._republish_task is not None and not self._republish_task.done():
            self._republish_task.cancel()
            try:
                await self._republish_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._republish_task = None

        # Detach gossip from the blackboard before closing clients —
        # otherwise the receive thread keeps holding a stale channel
        # past channel.close(), waiting for a stream that won't reopen.
        try:
            self._blackboard.detach_gossip()
        except Exception:  # noqa: BLE001
            pass

        if self._settlement is not None:
            self._settlement.stop()
            self._settlement = None

        if self._gossip is not None:
            self._gossip.close()
        if self._supervisor is not None:
            # Supervisor owns the subprocess AND its NetdClient; tearing
            # both down lives in stop(). Don't double-close self._netd
            # below — that's the supervisor's client.
            self._supervisor.stop()
        else:
            if self._netd is not None and self._netd_owns_process:
                self._netd.close()
            if self._netd_proc is not None:
                self._netd_proc.terminate()
                try:
                    self._netd_proc.wait(timeout=5.0)
                except Exception:  # noqa: BLE001
                    self._netd_proc.kill()
        self._started = False
        LOG.info("[global] stopped")

    def _on_daemon_respawn(self, netd: NetdClient) -> None:
        """
        Supervisor callback fired after each successful gyza-netd
        respawn. Runs in the supervisor's heartbeat thread, so we keep
        the work bounded:

          1. Redial the persistent peer cache — settlement and project
             gossip both fail silently against a peer the daemon doesn't
             know about, so this matters BEFORE anyone tries to use the
             freshly restarted daemon.
          2. Re-publish DHT advertisements — the daemon's DHT routing
             table reset on respawn, so cached records elsewhere will
             still find us only if we re-publish promptly.
          3. Re-join the gossip topic for every active project. Without
             this, deltas from peers continue to flow into pubsub but
             land on a dead subscription.

        Each step is wrapped in its own try/except: we want partial
        recovery to ship rather than aborting on the first hiccup.
        Note: ``publish_agents`` is async; we synthesize a one-shot
        event loop because the heartbeat thread has none.
        """
        LOG.info("[global] daemon respawned; running recovery hooks")
        if self._peer_cache is not None:
            try:
                self._peer_cache.attempt_reconnect_all(netd)
            except Exception as e:  # noqa: BLE001
                LOG.warning("[global] post-respawn reconnect failed: %s", e)

        try:
            asyncio.run(self.publish_agents())
        except Exception as e:  # noqa: BLE001
            LOG.warning("[global] post-respawn publish_agents failed: %s", e)

        if self._gossip is not None:
            for project_id in list(self._projects.keys()):
                try:
                    self._gossip.join_project(project_id)
                except Exception as e:  # noqa: BLE001
                    LOG.warning(
                        "[global] post-respawn rejoin %s failed: %s",
                        project_id[:16], e,
                    )

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def netd(self) -> NetdClient:
        if self._netd is None:
            raise RuntimeError("GlobalCluster not started — call start() first")
        return self._netd

    @property
    def gossip(self) -> GossipClient:
        if self._gossip is None:
            raise RuntimeError("GlobalCluster not started — call start() first")
        return self._gossip

    @property
    def settlement(self) -> LedgerSettlementService:
        if self._settlement is None:
            raise RuntimeError("GlobalCluster not started — call start() first")
        return self._settlement

    @property
    def peer_registry(self) -> PeerRegistry:
        if self._registry is None:
            raise RuntimeError("GlobalCluster not started — call start() first")
        return self._registry

    @property
    def ledger(self) -> ComputeLedger:
        return self._ledger

    # ------------------------------------------------------------------
    # DHT publication
    # ------------------------------------------------------------------

    async def publish_agents(self) -> int:
        """
        Re-publish every locally-running agent to the global DHT. Call
        on startup AND every TTL/2 seconds (3600/2 = 1800s by default).

        Returns the count of advertisements successfully published.
        Failures are logged per-agent but don't fail the whole call —
        a transient DHT issue with one bucket shouldn't block updates
        to others.
        """
        # Refresh whole-cluster observability gauges first — a node
        # with no local agents still wants its DHT peer count and
        # connected peer count visible on dashboards.
        try:
            status = self.netd.get_status()
            _obs_dht_peers(int(status.dht_routing_table_size))
            _obs_connected_peers(int(status.connected_peers))
        except Exception:  # noqa: BLE001
            pass

        agents = self._agents_provider()
        if not agents:
            return 0
        # Compute a global credit balance to advertise. Net earnings
        # signal cooperative behavior; net debt signals a free-rider
        # candidate to anyone scoring us.
        global_balance = int(
            self._ledger.get_total_earned() - self._ledger.get_total_spent()
        )
        ok = 0
        for agent in agents:
            ad = AgentAdvertisement(
                agent_pubkey=agent.agent_pubkey,
                compositor_pubkey=self._compositor.pubkey_hex,
                capability_manifest_hash=agent.capability_manifest_hash,
                specialization_embedding=agent.specialization,
                lsh_bucket=0,  # daemon recomputes
                attestation_tier=agent.attestation_tier,
                reputation_score=agent.reputation_score,
                compute_credit_balance=global_balance,
                last_seen=time.time_ns(),
                ttl_seconds=3600,
            )
            try:
                self.netd.publish_agent(ad)
                ok += 1
            except Exception as e:  # noqa: BLE001
                LOG.warning(
                    "[global] publish_agent(%s) failed: %s",
                    agent.agent_pubkey[:16], e,
                )
        LOG.info("[global] published %d/%d agents", ok, len(agents))

        # Net-credits gauge — we already have the balance computed for
        # the advertisement, so reuse it. Cast to float for the gauge.
        _obs_net_credits(float(global_balance))

        return ok

    def set_republish_interval(self, seconds: float) -> None:
        """Adjust the DHT re-publish cadence. Tests use small values;
        production keeps the default (TTL/2 = 1800s)."""
        if seconds <= 0:
            raise ValueError(f"republish interval must be positive, got {seconds}")
        self._republish_interval_s = seconds

    async def _republish_loop(self) -> None:
        """
        Re-publish every locally-running agent on a schedule. Sleeps
        first so the initial publish_agents() call (typically issued
        right after start()) doesn't double up.

        Caught exceptions: a transient publish_agents failure must not
        kill the loop; we log and try again next cycle.
        """
        try:
            while True:
                try:
                    await asyncio.sleep(self._republish_interval_s)
                except asyncio.CancelledError:
                    return
                try:
                    n = await self.publish_agents()
                    LOG.debug("[global] republish: %d agents", n)
                except Exception as e:  # noqa: BLE001
                    LOG.warning("[global] republish failed: %s", e)
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Project formation
    # ------------------------------------------------------------------

    async def find_and_collaborate(
        self,
        project_id: str,
        required_specializations: list[np.ndarray],
        min_tier: int = 1,
        per_spec_k: int = 5,
    ) -> list[str]:
        """
        Locate remote agents whose specialization matches each required
        vector, NAT-connect to their compositors, exchange attestations,
        and join the project's gossip topic.

        Returns the list of compositor pubkeys (hex) we successfully
        onboarded. Returns [] if nothing usable was found — the caller
        can fall back to local-only execution rather than blocking.
        """
        if not required_specializations:
            return []

        # 1. DHT find. We dedup by compositor — a single peer may be
        #    advertising several agents, but we connect to compositors,
        #    not agents.
        candidates: dict[str, AgentAdvertisement] = {}
        for spec in required_specializations:
            try:
                ads = self.netd.find_agents(
                    spec, k=per_spec_k, min_tier=min_tier,
                )
            except Exception as e:  # noqa: BLE001
                LOG.warning(
                    "[global] find_agents failed for one specialization: %s", e,
                )
                continue
            for ad in ads:
                if ad.compositor_pubkey == self._compositor.pubkey_hex:
                    continue  # don't try to collaborate with ourselves
                # Keep the highest-reputation ad per compositor —
                # close enough to "best agent on that node" without
                # second-pass scoring.
                existing = candidates.get(ad.compositor_pubkey)
                if existing is None or ad.reputation_score > existing.reputation_score:
                    candidates[ad.compositor_pubkey] = ad

        if not candidates:
            LOG.info("[global] no remote candidates for project %s", project_id[:16])
            return []

        # 2. Connect (NAT-aware via PeerService.Connect — netd handles
        #    direct → DCUtR → relay fallback).
        connected: list[str] = []
        for pubkey, ad in candidates.items():
            multiaddr = self._best_multiaddr(ad)
            if multiaddr is None:
                LOG.info(
                    "[global] candidate %s has no multiaddrs — skipping",
                    pubkey[:16],
                )
                continue
            try:
                result = self.netd.connect_peer(multiaddr, pubkey)
            except Exception as e:  # noqa: BLE001
                LOG.warning("[global] connect to %s failed: %s", pubkey[:16], e)
                continue
            if not result.success:
                LOG.info(
                    "[global] connect to %s failed: %s",
                    pubkey[:16], result.error,
                )
                continue
            # If the daemon reported a verified pubkey, prefer that —
            # the wire-level identity check beats our advertised assumption.
            verified = result.verified_pubkey or pubkey
            self.peer_registry.add(verified, result.peer_id)
            if self._peer_cache is not None:
                # We pin the cache to verified, not the originally
                # advertised pubkey, so a multiaddr that DCUtR rerouted
                # to a different (still-Noise-authenticated) peer
                # doesn't poison our future redial set.
                self._peer_cache.add(verified, multiaddr)
            connected.append(verified)

        # 3. Attestation cross-check.
        valid_peers: list[str] = []
        for pubkey in connected:
            valid, _tier = await self._verify_peer_attestation(pubkey)
            if valid:
                valid_peers.append(pubkey)
            else:
                LOG.warning(
                    "[global] peer %s failed attestation; excluding from project",
                    pubkey[:16],
                )

        if not valid_peers:
            return []

        # 4. Join gossip topic & wire blackboard.
        try:
            self.gossip.join_project(project_id)
        except Exception as e:  # noqa: BLE001
            LOG.warning("[global] gossip.join_project failed: %s", e)
            # We can still proceed — the user can re-try gossip later.
        try:
            self._blackboard.attach_gossip(
                self.gossip,
                project_id=project_id,
                node_id=self._compositor.pubkey_hex,
            )
        except RuntimeError as e:
            # Already attached — maybe the user invoked find_and_collaborate
            # twice for two projects. We don't currently support multiple
            # gossip topics on one blackboard; log and continue (the
            # second project will share the first's topic, which is
            # incorrect — caller should fix at the application layer).
            LOG.warning("[global] blackboard.attach_gossip refused: %s", e)

        # 5. Track membership for settle_project_ledger.
        self._projects[project_id] = ProjectMembership(
            project_id=project_id,
            member_compositor_pubkeys=set(valid_peers),
        )
        LOG.info(
            "[global] project %s formed with %d remote nodes",
            project_id[:16], len(valid_peers),
        )
        return valid_peers

    async def _verify_peer_attestation(
        self, compositor_pubkey: str,
    ) -> tuple[bool, int]:
        """
        Fetch the peer's attestation cert from the DHT and verify it
        locally via the daemon's CapabilityService.

        Policy: a peer with no published attestation is treated as
        Tier 0 (allowed). This is fail-open by design — strict
        rejection would create a denial-of-service vector for new
        nodes. Any work the peer does for us is signed via ICP and
        settled bilaterally; the attestation gate is a routing /
        prioritization signal, not a security boundary.

        Returns ``(valid, tier)`` where tier is the attested tier or 0.
        """
        if self._capability_client_factory is not None:
            cap = self._capability_client_factory()
        else:
            from gyza.network.netd_client import CapabilityClient
            cap = CapabilityClient(
                self._config.resolved_paths()["netd_socket_path"],
            )
        try:
            cert = cap.fetch_attestation(compositor_pubkey)
            if cert is None:
                return True, 0  # fail-open
            valid, _cosig_count, reason = cap.verify_attestation(cert.raw_proto)
            if not valid:
                LOG.warning(
                    "[global] attestation cert for %s invalid: %s",
                    compositor_pubkey[:16], reason,
                )
                return False, 0
            return True, cert.tier_granted
        except Exception as e:  # noqa: BLE001
            # Daemon-level failure (gRPC error, daemon shutting down).
            # We choose fail-open here too — connectivity issues should
            # not stop project formation.
            LOG.warning(
                "[global] attestation fetch for %s threw: %s",
                compositor_pubkey[:16], e,
            )
            return True, 0
        finally:
            close = getattr(cap, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _best_multiaddr(ad: AgentAdvertisement) -> str | None:
        """
        Pick a public multiaddr from an advertisement. Prefer the first
        non-loopback IPv4 address; fall back to anything else.

        DHT advertisements may carry several listen addresses; some
        will be loopback (useless for cross-network connect), some
        link-local. Without observed-address data we go with first-non-loopback,
        which is usually the public IP.
        """
        if not ad.multiaddrs:
            return None
        for m in ad.multiaddrs:
            if "/127.0.0.1/" in m or "/::1/" in m:
                continue
            return m
        return ad.multiaddrs[0]

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------

    async def settle_project_ledger(self, project_id: str) -> dict:
        """
        Reconcile our ledger view with each project member. Returns:

            {
              "members": [pubkey, ...],
              "per_member": {
                  pubkey: {"agreed": [...], "disputed": [...],
                           "missing_ours": [...], "missing_theirs": [...]},
                  ...
              },
              "self_balance_credits": float,  # net for us across project
            }

        For Phase 3 we generate a LOCAL reconciliation report — Session 8
        adds a request_ledger_reconcile RPC so peers exchange views.
        Right now reconcile_with_peer is called with an empty
        their_entries list, surfacing only ``missing_theirs`` (everything
        we have).

        Why include this stub: the data we DO have is useful for an
        operator running ``gyza credits statement --project=alpha`` —
        they can see what they've earned/spent on this collaboration
        without waiting for the cross-node exchange to land.
        """
        membership = self._projects.get(project_id)
        if membership is None:
            return {
                "members": [],
                "per_member": {},
                "self_balance_credits": 0.0,
                "warning": "no project membership recorded",
            }

        per_member: dict[str, dict] = {}
        net = 0.0
        for pubkey in sorted(membership.member_compositor_pubkeys):
            diff = self._ledger.reconcile_with_peer(pubkey, their_entries=[])
            per_member[pubkey] = diff
            net += self._ledger.get_balance(pubkey)
        return {
            "members": sorted(membership.member_compositor_pubkeys),
            "per_member": per_member,
            "self_balance_credits": net,
        }

    def project_membership(self, project_id: str) -> ProjectMembership | None:
        return self._projects.get(project_id)

    # ------------------------------------------------------------------
    # Runner hook
    # ------------------------------------------------------------------

    def shared_hlc(self):
        """
        Return the per-node HLC instance that local runners should
        share with cross-cluster delta merges. Pass to
        ``AgentRunner(..., hlc=gc.shared_hlc())`` when the blackboard
        is participating in gossip (after ``find_and_collaborate`` or a
        manual ``attach_gossip`` call). Returns ``None`` if no project
        is currently attached — runners should fall back to their
        per-agent HLC in that case.

        Why this method exists: the HLC ratchet invariant requires
        every local claim AND every observed remote claim to advance
        the same logical clock. Pre-Session-8.5 the runner held a
        private HLC; cross-cluster claim merges advanced
        ``bb._gossip_hlc`` instead, producing two clocks that
        diverged. A local claim issued strictly after a merged remote
        claim could produce a tuple lex-smaller than the remote and
        break LWW total order.
        """
        return self._blackboard.gossip_hlc()

    def runner_envelope_hook(
        self,
        *,
        settle: bool = True,
        manifest_bytes: bytes | None = None,
    ) -> Callable[[Any], None]:
        """
        Build a closure for AgentRunner's ``on_envelope_signed`` that
        delivers the result to the submitter and (when ``settle`` is
        True) submits an earner-signed ledger entry for the work.

        ``settle=False`` does result delivery only — no ledger entry,
        no credit transfer. The public demo agents use this: they
        work for free, so a stranger running ``gyza submit`` doesn't
        accrue compute debt and doesn't see a half-completed
        settlement. Bilateral settlement is demonstrated separately
        by ``demo/single_machine_global.py``.

        Decisions made by the hook:

          * Skip local-intent work (creator == us). We're not earning
            from anyone — the work is for our own intent.

          * Skip unknown-creator intents. ``_intent_creator`` is
            populated only when (a) we posted the intent locally or
            (b) we received the originating delta via gossip. If
            neither happened — e.g. a stale work item that survived a
            gossip-link outage — we have no provenance to bill against
            and we silently skip. Reconciliation later may surface
            the gap.

          * Skip when peer routing isn't available. The PeerRegistry
            falls back to None when the creator's compositor isn't in
            our connected-peers set. The earner's ledger keeps no
            local entry — the next call to runner_envelope_hook for
            another item is independent.

        Why this lives here, not in the AgentRunner: the runner is
        Phase 1 code that knows nothing about the economy or the
        peer mesh. Keeping the wiring at the GlobalCluster level lets
        single-node tests run AgentRunner without economy/network
        plumbing and lets Phase 4 swap settlement strategies without
        touching the runner.
        """
        from gyza.icp import compute_envelope_hash

        # Capture only what we need so the closure is independent of
        # GlobalCluster's lifecycle. The settlement service / registry
        # references are bound at start() time.
        if self._settlement is None or self._registry is None:
            raise RuntimeError(
                "runner_envelope_hook called before start() — "
                "settlement / peer registry not initialized"
            )
        settlement = self._settlement
        registry = self._registry
        blackboard = self._blackboard
        my_pubkey = self._compositor.pubkey_hex

        netd = self._netd

        def _deliver_result(envelope, peer_id: str) -> None:
            """
            Push the full signed envelope + result artifact to the
            submitter over the daemon's point-to-point MessageService.
            Without this the submitter only gets gossipped hashes and
            cannot verify the chain or read the result. Best-effort:
            a delivery failure is logged, not raised — the work is
            done and signed regardless.
            """
            from gyza.network.result_delivery import (
                RESULT_DELIVERY_TYPE,
                encode_delivery,
            )
            artifact = blackboard.get_artifact(envelope.output_hash)
            if artifact is None:
                LOG.info(
                    "[global] hook: no artifact for output_hash %s — "
                    "result delivery skipped for action %s",
                    envelope.output_hash[:16], envelope.action_id[:16],
                )
                return
            try:
                payload = encode_delivery(
                    work_item_id=envelope.action_id,
                    envelope=envelope,
                    artifact_bytes=artifact.data,
                    manifest_bytes=manifest_bytes,
                )
                ok = netd.send_message(
                    peer_id=peer_id,
                    message_type=RESULT_DELIVERY_TYPE,
                    payload=payload,
                )
                if not ok:
                    LOG.warning(
                        "[global] hook: result delivery send to %s "
                        "failed for action %s",
                        peer_id, envelope.action_id[:16],
                    )
            except Exception as e:  # noqa: BLE001
                LOG.warning(
                    "[global] hook: result delivery raised for action "
                    "%s: %s", envelope.action_id[:16], e,
                )

        def _hook(envelope) -> None:
            creator = blackboard._intent_creator.get(envelope.intent_id)
            if creator is None or creator == my_pubkey:
                return
            peer_id = registry.resolve_peer_id(creator)
            if peer_id is None:
                LOG.info(
                    "[global] hook: no peer_id for creator %s — "
                    "settlement + delivery skipped for action %s",
                    creator[:16], envelope.action_id[:16],
                )
                return
            # Deliver the result FIRST. The submitter is typically a
            # short-lived `gyza submit` waiting on exactly this; getting
            # the envelope + artifact to it is the user-visible outcome.
            _deliver_result(envelope, peer_id)
            if not settle:
                return
            envelope_hash = compute_envelope_hash(envelope)
            try:
                settlement.submit_earned(
                    payer_compositor=creator,
                    payer_peer_id=peer_id,
                    work_item_id=envelope.action_id,
                    icp_envelope_hash=envelope_hash,
                    model_identifier=envelope.model_identifier,
                    tokens_out=envelope.tokens_out,
                    duration_ms=envelope.duration_ms,
                    # Ship the evidence the payer needs to audit before
                    # paying: the output artifact and the agent manifest.
                    # No-op when this node has no evidence store.
                    evidence_hashes=[
                        envelope.output_hash,
                        envelope.capability_manifest_hash,
                    ],
                )
            except Exception as e:  # noqa: BLE001
                LOG.warning(
                    "[global] hook: submit_earned failed for action %s: %s",
                    envelope.action_id[:16], e,
                )

        return _hook

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    # Maximum seconds the default envelope resolver will wait for a
    # completion delta to land before declaring the work item unknown.
    # Picked to comfortably exceed typical gossipsub propagation on
    # loopback (~100ms) and on intercontinental WAN (~500ms), with
    # enough headroom for slow paths. Tests can override on the
    # GlobalCluster instance via _envelope_resolver_wait_s.
    _envelope_resolver_wait_s: float = 3.0

    def _default_envelope_resolver(self, work_item_id: str):
        """
        Read icp_envelope_hash for a known work item from the local
        blackboard. The settlement service uses this to validate
        incoming earner_signed messages — only entries for work items
        we've actually completed locally are eligible to be cosigned.

        TIMING NOTE — when the executor signs an envelope and submits
        the earner_signed message, that message races with the
        completion delta (gossipsub) over different transports. On
        loopback the message stream is faster (~10ms) than gossipsub
        propagation (~100ms), so the coordinator may receive
        earner_signed before its blackboard has the icp_envelope_hash
        for the work item. We poll briefly to absorb that gap.

        Polling here, in the resolver, is the right layer: the
        settlement service treats the resolver as a black box, and
        the wait window is purely a function of how the local
        blackboard learns about completions (via gossip). Other
        deployments (Raft-replicated cluster, single-node) may want
        zero wait.
        """
        deadline = time.monotonic() + self._envelope_resolver_wait_s
        while True:
            try:
                row = self._blackboard._conn().execute(
                    "SELECT icp_envelope_hash FROM work_items WHERE id=?",
                    (work_item_id,),
                ).fetchone()
            except Exception as e:  # noqa: BLE001
                LOG.warning(
                    "[global] envelope_resolver lookup failed for %s: %s",
                    work_item_id, e,
                )
                return None
            if row is not None and row["icp_envelope_hash"]:
                return row["icp_envelope_hash"]
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.05)


# Avoid asyncio import lint complaints when not yet used. Reserved for
# future async-only flows.
_ = asyncio


__all__ = [
    "GlobalCluster",
    "AgentDescriptor",
    "ProjectMembership",
]
