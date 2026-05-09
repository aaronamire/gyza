"""
Phase 3 Session 8.5 — agent supervisor.

Closes the self-organization loop that the spec called for and Sessions
1-8 left open. Without this module:

  * ``DemandOracle.should_spawn_replica`` existed but had zero callers.
  * ``LocalCompositor.issue_agent`` existed but was only invoked from
    the CLI's ``init`` flow (one agent per node, fixed at startup).
  * The whole "node spawns agents in response to observed demand"
    thesis was a story, not an implementation.

What this module does
---------------------

``AgentSupervisor`` is a control loop that:

  1. Polls ``DemandOracle.all_signals()`` on a configurable cadence.
  2. For each bucket where demand exceeds threshold AND no local agent
     is currently specialized at that bucket, asks the user-provided
     factory to build a runner for the bucket's centroid embedding,
     then starts it.
  3. Tracks the spawned roster, enforces ``max_agents``, and on stop
     halts every runner cleanly.

Bucket-level decisions vs item-level decisions: the oracle's
``should_spawn_replica`` is per-embedding ("would I, with this
specialization, be in a high-demand neighborhood?"). The supervisor
asks a different question: "looking at every bucket where demand
exists, which ones don't yet have a serving agent on this node?" The
distinction matters because a node could have one general-purpose
agent that scores reasonably on many buckets — without the supervisor
explicitly avoiding spawn for buckets it's already serving, every poll
cycle would spawn a duplicate.

Why a factory rather than a built-in builder: spawning a runner
requires choosing an executor (mock vs Anthropic vs llama.cpp), a
memory backend, a specialization tracker, an LSH index — each of
which is a deployment decision. Hard-coding any of them in the
supervisor would make this module either too restrictive or too
opinionated. The factory pattern keeps the policy ("when to spawn,
which bucket") here and the mechanism ("how to spin up a runner")
with the user.

Persistence: spawned agents do not survive supervisor restart in
Phase 3 — each session starts with the user's seed agents only and
re-spawns based on observed demand. Persisting the roster across
restarts is a Phase 4 concern (it requires reattaching memory and
specialization state to a fresh AgentIdentity, which interacts with
the Phase 4 identity-rotation work).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from gyza.demand import DemandOracle, DemandSignal, LSHIndex
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.runner import AgentRunner


LOG = logging.getLogger("gyza.supervisor")


# Observability hooks. Spawn count is a counter; the live roster size
# is a gauge that we set after every roster mutation (spawn now,
# stop later). Fail-closed wrappers keep supervisor functional when
# prometheus_client is missing.
try:
    from gyza.observability import (
        ROSTER_SIZE as _ROSTER_SIZE,
        SUPERVISOR_SPAWNS_TOTAL as _SUPERVISOR_SPAWNS_TOTAL,
    )

    def _obs_spawn() -> None:
        _SUPERVISOR_SPAWNS_TOTAL.inc()

    def _obs_roster(size: int) -> None:
        _ROSTER_SIZE.set(size)
except Exception:  # noqa: BLE001
    def _obs_spawn() -> None:  # type: ignore[misc]
        pass

    def _obs_roster(size: int) -> None:  # type: ignore[misc]
        pass


# Hardcoded for the canonical 64-plane LSH; matches gyza.demand. The
# supervisor's bucket-occupancy check needs the same LSH planes the
# oracle used to compute its signals — passing a divergent LSH would
# silently cause every spawn cycle to compute "no agent serves this
# bucket" because hashes would never coincide.
_DEFAULT_MAX_AGENTS = 4
_DEFAULT_POLL_INTERVAL_S = 10.0
_DEFAULT_SPAWN_THRESHOLD = 5.0


@dataclass
class SpawnRequest:
    """
    What the factory receives when the supervisor decides to spawn.

    The factory is responsible for assembling a runner from these:

      * ``identity`` is already issued by the supervisor's compositor;
        the factory does NOT call ``compositor.issue_agent`` itself.
      * ``specialization_seed`` is the bucket centroid; the factory
        passes it to ``SpecializationTracker(initial_embedding=...)``.
      * ``bucket`` is informational — useful for naming agent home
        directories so spawned-agent SQLite paths don't collide.

    The factory returns an UNSTARTED ``AgentRunner``. The supervisor
    starts it and tracks it for shutdown.
    """
    identity: AgentIdentity
    specialization_seed: np.ndarray  # shape (384,), float32, L2-normalized
    bucket: int
    spawn_reason: str  # human-readable: "demand=8.4 in bucket 0xa7c1..."


@dataclass
class _SpawnedAgent:
    """Internal record of one supervisor-spawned agent."""
    runner: AgentRunner
    identity: AgentIdentity
    specialization_seed: np.ndarray
    bucket: int
    spawned_at_ns: int


class AgentSupervisor:
    """
    Demand-driven agent spawner.

    Threading model: a single background poll thread examines the
    oracle's signals on each tick. Spawn decisions and the agent
    roster are guarded by ``self._lock`` so external readers
    (``list_agents``) don't observe a half-mutated state.

    The supervisor does NOT itself execute work — it only spawns
    runners. Each runner runs its own claim/execute loop on its own
    thread, exactly as if the user had constructed it manually.
    """

    def __init__(
        self,
        compositor: LocalCompositor,
        oracle: DemandOracle,
        lsh: LSHIndex,
        agent_factory: Callable[[SpawnRequest], AgentRunner],
        spawn_threshold: float = _DEFAULT_SPAWN_THRESHOLD,
        max_agents: int = _DEFAULT_MAX_AGENTS,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    ):
        if max_agents < 0:
            raise ValueError(f"max_agents must be >= 0, got {max_agents}")
        self._compositor = compositor
        self._oracle = oracle
        self._lsh = lsh
        self._factory = agent_factory
        self._spawn_threshold = spawn_threshold
        self._max_agents = max_agents
        self._poll_s = poll_interval_s

        # agent_id → _SpawnedAgent
        self._agents: dict[str, _SpawnedAgent] = {}
        self._lock = threading.Lock()

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._spawn_count = 0  # cumulative; tests assert against this

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="gyza-supervisor",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 30.0) -> None:
        """
        Halt the poll loop, then halt every spawned runner. ``timeout_s``
        is the joinwait per-runner; on busy nodes spawned runners may
        be mid-completion when stop fires and we want them to finish
        the in-flight work item rather than abandon it.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_s + 5.0)
            self._thread = None

        with self._lock:
            agents = list(self._agents.values())
            self._agents.clear()
        _obs_roster(0)
        for a in agents:
            try:
                a.runner.stop()
            except Exception as e:  # noqa: BLE001
                LOG.warning(
                    "[supervisor] failed to stop runner %s: %s",
                    a.identity.agent_id[:8], e,
                )

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def spawn_count(self) -> int:
        """Total spawns since start. Cumulative — never decrements on
        stop. Useful for tests asserting "the supervisor saw demand
        and acted on it." """
        return self._spawn_count

    def list_agents(self) -> list[dict]:
        """Snapshot of currently-running supervisor-spawned agents.
        Returns plain dicts so callers don't accidentally hold
        references that prevent runners from being garbage-collected
        after stop."""
        with self._lock:
            return [
                {
                    "agent_id": a.identity.agent_id,
                    "bucket": a.bucket,
                    "spawned_at_ns": a.spawned_at_ns,
                }
                for a in self._agents.values()
            ]

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        # Run once immediately so callers don't have to wait
        # poll_interval_s for the first decision.
        self._tick()
        while not self._stop.wait(self._poll_s):
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001
                LOG.warning("[supervisor] poll tick failed: %s", e)

    def _tick(self) -> None:
        signals = self._oracle.all_signals()
        if not signals:
            return

        # Sort buckets by deficit-relevant signal so we spawn for the
        # highest-pressure bucket first when we're at the cap.
        # Centroid lookup may fail if the oracle's signal carries no
        # centroid (shouldn't with the current implementation, but be
        # defensive).
        ordered = sorted(
            signals.items(),
            key=lambda kv: (
                -kv[1].unclaimed_count,
                -kv[1].max_reward,
            ),
        )
        for bucket, sig in ordered:
            if sig.centroid_embedding is None:
                continue
            with self._lock:
                roster_size = len(self._agents)
            if roster_size >= self._max_agents:
                LOG.info(
                    "[supervisor] at max_agents=%d; not spawning for "
                    "bucket %x (demand=%.2f)",
                    self._max_agents, bucket,
                    self._oracle.compute_deficit(sig.centroid_embedding),
                )
                return

            if self._serving_bucket(bucket):
                continue

            deficit = self._oracle.compute_deficit(sig.centroid_embedding)
            if deficit <= self._spawn_threshold:
                continue

            self._spawn(bucket, sig, deficit)

    def _serving_bucket(self, bucket: int) -> bool:
        """True if any roster member's specialization hashes to
        ``bucket`` under the supervisor's LSH. The check is conservative:
        if an agent's specialization drifts AWAY from a bucket, the
        supervisor will eventually spawn a replica for it — but only
        on the next poll tick, not retroactively. That delay is
        intentional (avoids spawn churn on noisy spec-vector updates)."""
        with self._lock:
            for a in self._agents.values():
                if self._lsh.hash(a.specialization_seed) == bucket:
                    return True
        return False

    def _spawn(self, bucket: int, sig: DemandSignal, deficit: float) -> None:
        """
        Issue a fresh agent identity, build a runner via the factory,
        and start it. Failures at any stage are logged and the
        supervisor moves on — one bad spawn must not stop the loop.
        """
        agent_type = f"replica-bucket-{bucket:016x}"
        try:
            seed, manifest = self._compositor.issue_agent(
                agent_type=agent_type,
                model_path="auto",
                # Conservative defaults: read-only access to the gyza
                # home, no write access. The factory can re-issue with
                # broader caps if its executor needs them.
                fs_read_paths=["~/.gyza"],
                fs_write_paths=[],
                attestation_tier=1,
            )
            ident = AgentIdentity(seed, manifest)
        except Exception as e:  # noqa: BLE001
            LOG.warning(
                "[supervisor] issue_agent for bucket %x failed: %s",
                bucket, e,
            )
            return

        spawn_reason = (
            f"demand={deficit:.2f} (threshold={self._spawn_threshold:.2f}), "
            f"unclaimed={sig.unclaimed_count}, max_reward={sig.max_reward:.2f}"
        )
        # The centroid is the bucket's "what's been observed in this
        # neighborhood" embedding — a good initial specialization for
        # an agent intended to drain that neighborhood.
        spec_seed = np.asarray(sig.centroid_embedding, dtype=np.float32)
        # Defensive copy so the factory mutating it doesn't perturb the
        # oracle's signal storage.
        spec_seed = spec_seed.copy()
        # L2-normalize: SpecializationTracker expects a unit vector.
        norm = float(np.linalg.norm(spec_seed))
        if norm > 0:
            spec_seed /= norm

        request = SpawnRequest(
            identity=ident,
            specialization_seed=spec_seed,
            bucket=bucket,
            spawn_reason=spawn_reason,
        )
        try:
            runner = self._factory(request)
        except Exception as e:  # noqa: BLE001
            LOG.warning(
                "[supervisor] factory failed for bucket %x: %s",
                bucket, e,
            )
            return

        try:
            runner.start()
        except Exception as e:  # noqa: BLE001
            LOG.warning(
                "[supervisor] runner.start failed for bucket %x: %s",
                bucket, e,
            )
            return

        with self._lock:
            self._agents[ident.agent_id] = _SpawnedAgent(
                runner=runner,
                identity=ident,
                specialization_seed=spec_seed,
                bucket=bucket,
                spawned_at_ns=time.time_ns(),
            )
            self._spawn_count += 1
            roster_size = len(self._agents)
        _obs_spawn()
        _obs_roster(roster_size)
        LOG.info(
            "[supervisor] spawned %s for bucket %x (%s)",
            ident.agent_id[:16], bucket, spawn_reason,
        )


__all__ = ["AgentSupervisor", "SpawnRequest"]
