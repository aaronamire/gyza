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
import multiprocessing as mp
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
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
    #: See StagingArea.NON_ADOPTED for the convention.
    NON_ADOPTED = (
        "A VALUE TYPE OF `AgentSupervisor`, WHICH IS NOT ADOPTED. It is constructed only inside that class, and constructions inside a NON_ADOPTED class deliberately do not count toward the census -- otherwise an unconsumed component could vouch for its own parts. It becomes live in the same commit that removes AgentSupervisor's marker."
    )

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
    #: See StagingArea.NON_ADOPTED for the convention.
    NON_ADOPTED = (
        "A VALUE TYPE OF `AgentSupervisor`, WHICH IS NOT ADOPTED. Private, constructed only inside that class, and covered by the same rule: constructions inside a NON_ADOPTED class do not count, so an unconsumed component cannot vouch for its own parts."
    )

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

    #: See StagingArea.NON_ADOPTED for the convention.
    NON_ADOPTED = (
        "DEMAND-DRIVEN SPAWNING IS AN OPTIMISATION OVER A FIXED ROSTER, and "
        "the fixed roster is what a deployment needs first. Three facts, each "
        "checked rather than assumed: (1) there was nowhere to construct this "
        "-- the only `runner.start()` in the CLI is inside the capability-eval "
        "harness, and `gyza run` executes ONE work item synchronously, so "
        "nothing hosted runners at all; (2) its own dependency `DemandOracle` "
        "has zero production constructors, so wiring this would require "
        "wiring a second unconsumed component beneath it; (3) it spawns "
        "THREADS, which share a fate -- one unhandled exception takes the "
        "whole roster. `RunnerProcessSupervisor` in this module is the adopted "
        "mechanism: a fixed roster, one OS process each, restarted on crash. "
        "When a deployment actually needs autoscaling, this becomes the layer "
        "ABOVE that one and this marker comes off."
    )


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


# =========================================================================== #
#  PROCESS-LEVEL SUPERVISION
#
#  WHY THIS EXISTS AND `AgentSupervisor` DOES NOT SUFFICE. `AgentSupervisor`
#  spawns runners in response to DEMAND, as threads, inside one process. Three
#  things make that the wrong first mechanism for a deployment:
#
#    1. There was nowhere to put it. The only `runner.start()` in the CLI is
#       inside the capability-eval harness; `gyza run` executes ONE work item
#       synchronously and returns. Nothing hosts runners, so "500 agents" had
#       no entry point -- not merely no supervisor.
#    2. Threads share a fate. One unhandled exception in one runner takes the
#       whole roster with it, and a daemon thread that dies leaves no trace.
#    3. Demand-driven spawning is an OPTIMISATION over a fixed roster, and its
#       own dependency (`DemandOracle`) has no production constructor either.
#       Building the optimisation before the thing it optimises is how a
#       component ends up unconsumed.
#
#  THIS COULD NOT HAVE LANDED FIRST. Supervision makes a crash ROUTINE, and
#  until 2026-08-21 a runner that died holding a claim leaked that work item
#  permanently -- `release_claim` has one caller, the in-process failure path,
#  and `get_unclaimed`'s TTL filter only applies to already-unclaimed rows.
#  Restarting crashed runners on top of that would have converted a rare
#  permanent leak into a frequent one: supervision would have made the system
#  strictly worse. The claim lease and the completion ownership check
#  (`Blackboard.reclaim_expired_claims`, `expected_owner`) are what make this
#  safe, and they are prerequisites rather than companions.
# =========================================================================== #

@dataclass(frozen=True)
class RunnerSpec:
    """What a child process needs to build one runner. MUST BE PICKLABLE.

    A spec rather than a factory closure, deliberately: `spawn` start-method
    children re-import the module and unpickle their arguments, so a closure
    over a live `Blackboard` or an open socket cannot cross the boundary. Every
    field here is a value or a path, which is also what makes a restarted child
    identical to the one it replaces.
    """
    agent_id: str
    #: ONE file holding `seed_hex` and `manifest`, which is the shape
    #: `_load_or_issue_local_agent` already writes. Two paths would have been a
    #: shape this system does not use.
    agent_state_path: str
    blackboard_path: str
    memory_path: str
    spec_db_path: str
    artifact_store_path: str
    poll_interval_s: float = 1.0
    min_reward: float = 0.0
    min_similarity: float = -1.0
    #: Whether the work runs INSIDE bubblewrap. NOT a callable: a spawn child
    #: unpickles this, and a function object would not survive the boundary.
    #: False by default so an unconfigured host cannot silently run unsandboxed
    #: work believing it is contained -- `serve` sets it explicitly and refuses
    #: to start without bubblewrap.
    sandboxed: bool = False
    #: WHAT the agent actually does: "mock" | "command" | "anthropic".
    #: Separated from `sandboxed` because they are independent questions, and
    #: conflating them is why this shipped able to run only mock work: the
    #: field meant "is it sandboxed" and was read as "what does it do", so a
    #: sandboxed fleet did nothing real and looked production-ready.
    executor_kind: str = "mock"
    #: For executor_kind == "command". A tuple, not a list, because the spec is
    #: frozen and must hash.
    command_argv: "tuple[str, ...] | None" = None
    command_cwd: "str | None" = None
    #: For executor_kind == "anthropic". THE API KEY IS DELIBERATELY ABSENT:
    #: the child reads ANTHROPIC_API_KEY from its environment. A secret in a
    #: dataclass is a secret in a pickle, in a traceback, and in any log that
    #: repr()s the roster.
    model: "str | None" = None


@dataclass
class _Child:
    spec: RunnerSpec
    proc: "object | None" = None
    restarts: int = 0
    last_start_ns: int = 0
    gave_up: bool = False
    last_exit: "int | None" = None
    #: Wall clock of the last observed COMPLETION, or of the last tick at which
    #: this child had nothing to do. Both reset it, because idleness is health.
    last_progress_ns: int = 0
    completions: int = 0
    stall_restarts: int = 0
    #: Did we observe this child holding a claim during the current window?
    saw_attempt: bool = False


class RunnerProcessSupervisor:
    """Runs a FIXED roster of runners, one OS process each, and restarts them.

    Not a scheduler and not an autoscaler. It answers one question -- "are the
    runners I was told to run, running?" -- and its whole value is that the
    answer survives a crash.

    THE CRASH-LOOP CEILING IS THE POINT, not a detail. A supervisor that
    restarts unconditionally turns a deterministic failure into an infinite
    respawn that burns a core and floods the log, and the operator sees a
    running supervisor rather than a broken agent. After `max_restarts` inside
    `restart_window_s` a child is GIVEN UP ON and reported, because a component
    that cannot run is a fact an operator needs, not one to hide behind
    retries.
    """

    def __init__(
        self,
        roster: "list[RunnerSpec]",
        *,
        max_restarts: int = 5,
        restart_window_s: float = 300.0,
        backoff_s: float = 1.0,
        poll_interval_s: float = 0.5,
        stall_timeout_s: float = 900.0,
        target: "Callable[[RunnerSpec], None] | None" = None,
    ):
        if max_restarts < 0:
            raise ValueError(f"max_restarts must be >= 0, got {max_restarts}")
        self._children = [_Child(spec=s) for s in roster]
        self._max_restarts = int(max_restarts)
        self._restart_window_ns = int(restart_window_s * 1e9)
        self._backoff_s = float(backoff_s)
        self._poll_s = float(poll_interval_s)
        #: LIVENESS IS NOT PROGRESS, and this is the number that separates them.
        #:
        #: Watching `proc.is_alive()` was not enough, and a real defect proved
        #: it: `EpisodicMemory` raised on every write, `_run_loop` caught the
        #: error, released the claim and looped, so three agents polled and
        #: failed forever while every process stayed alive and this supervisor
        #: reported them healthy. A heartbeat would not have caught it either
        #: -- the loop WAS running. Only progress distinguishes the two.
        #:
        #: SIZED ABOVE THE LONGEST LEGITIMATE ACTION, like the claim lease and
        #: for the same reason: the sandbox caps an action at 300 s, so a
        #: shorter window would restart an agent that is simply working.
        self._stall_timeout_ns = int(stall_timeout_s * 1e9)
        #: Injectable so a test can supervise a process whose failure it
        #: controls. Production passes None and gets `run_runner_process`.
        self._target = target or run_runner_process
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- #
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        with self._lock:
            now = time.time_ns()
            for c in self._children:
                c.last_progress_ns = now
                c.saw_attempt = False
                self._spawn(c)
        self._thread = threading.Thread(
            target=self._watch_loop, name="gyza-proc-supervisor", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 30.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        with self._lock:
            for c in self._children:
                p = c.proc
                if p is None or not p.is_alive():
                    continue
                p.terminate()
        deadline = time.time() + timeout_s
        with self._lock:
            for c in self._children:
                p = c.proc
                if p is None:
                    continue
                p.join(timeout=max(0.0, deadline - time.time()))
                if p.is_alive():
                    p.kill()
                    p.join(timeout=2.0)

    def status(self) -> "list[dict]":
        with self._lock:
            return [{
                "agent_id": c.spec.agent_id,
                "alive": bool(c.proc is not None and c.proc.is_alive()),
                "pid": getattr(c.proc, "pid", None),
                "restarts": c.restarts,
                "stall_restarts": c.stall_restarts,
                "completions": c.completions,
                "gave_up": c.gave_up,
                "last_exit": c.last_exit,
            } for c in self._children]

    # ---------------------------------------------------------------- #
    def _spawn(self, c: _Child) -> None:
        ctx = mp.get_context("spawn")
        c.proc = ctx.Process(target=self._target, args=(c.spec,),
                             name=f"gyza-runner-{c.spec.agent_id[:8]}",
                             daemon=True)
        c.proc.start()
        c.last_start_ns = time.time_ns()

    def _holds_a_claim(self, spec: "RunnerSpec") -> "bool | None":
        """Is this agent holding work right now? `None` means unanswerable,
        which is NOT 'no' and must not convict.

        THIS REPLACED "is work available", AND MY OWN NEGATIVE CONTROL IS WHY.
        Availability convicts the wrong agent: a board can hold unclaimed items
        this agent will never take -- wrong tier, wrong specialisation, or
        already in its local failed set -- and an idle fleet was restarted for
        work that was never its to do.

        ATTEMPTING is the precise signal. An agent that claims and finishes
        nothing is broken; an agent that claims nothing is choosing, and
        choosing is not failing. Sampled rather than integrated because a claim
        is transient -- the failure loop claims, fails, releases, and claims
        again -- so a single tick may miss it while a window will not.
        """
        try:
            from gyza.blackboard import Blackboard
            row = Blackboard(spec.blackboard_path)._conn().execute(
                "SELECT 1 FROM work_items WHERE claimed_by=? "
                "AND completed_at_ns IS NULL LIMIT 1",
                (spec.agent_id,),
            ).fetchone()
            return row is not None
        except Exception:                                    # noqa: BLE001
            return None

    def _completions_since(self, spec: "RunnerSpec", since_ns: int) -> "int | None":
        """Completions read from the APPEND-ONLY ENVELOPE LOG, not from a
        channel the child reports on.

        A child that reports its own health is a child that can lie about it by
        being broken in the reporting path -- and the log is already durable,
        already per-agent, and already the thing every other part of this
        system treats as the record of what happened.
        """
        try:
            from gyza.blackboard import Blackboard
            return int(Blackboard(spec.blackboard_path)
                       .count_agent_envelopes_since(spec.agent_id, since_ns))
        except Exception:                                    # noqa: BLE001
            return None

    def _check_progress(self, c: "_Child", now: int) -> bool:
        """True iff `c` should be restarted for making no progress."""
        done = self._completions_since(c.spec, c.last_progress_ns)
        if done is None:
            return False                    # cannot tell: never restart on it
        if done > 0:
            c.completions += done
            c.last_progress_ns = now
            return False
        if self._holds_a_claim(c.spec) is True:
            c.saw_attempt = True
        if now - c.last_progress_ns < self._stall_timeout_ns:
            return False
        if not c.saw_attempt:
            # IDLE IS HEALTHY, and so is DECLINING. An agent that claimed
            # nothing in the window either had nothing to do or wanted none of
            # what was there; neither is a fault, and restarting it would be a
            # supervisor that punishes a quiet queue or a specialised agent.
            c.last_progress_ns = now
            return False
        # It held work and finished none of it, for a window longer than the
        # sandbox can legitimately take. That is the defect this exists for.
        c.saw_attempt = False
        return True

    def _watch_loop(self) -> None:
        while not self._stop.wait(self._poll_s):
            with self._lock:
                for c in self._children:
                    if c.gave_up or c.proc is None:
                        continue
                    if c.proc.is_alive():
                        if not self._check_progress(c, time.time_ns()):
                            continue
                        # Alive and not progressing while work waits. Treated
                        # exactly like a crash from here down, including the
                        # crash-loop ceiling -- a runner that cannot make
                        # progress twice will not make it a third time, and
                        # hiding that behind restarts is what the ceiling is
                        # for.
                        c.stall_restarts += 1
                        LOG.error(
                            "[supervisor] %s is ALIVE but has completed "
                            "nothing for %.0fs while work is available; "
                            "restarting. Liveness is not progress.",
                            c.spec.agent_id[:8],
                            self._stall_timeout_ns / 1e9)
                        c.proc.terminate()
                        c.proc.join(timeout=10.0)
                        if c.proc.is_alive():
                            c.proc.kill()
                            c.proc.join(timeout=2.0)
                        c.last_progress_ns = time.time_ns()
                        c.saw_attempt = False
                    c.last_exit = c.proc.exitcode
                    # A clean exit is not a crash. A runner that returns 0 has
                    # finished; restarting it would fight its own decision.
                    if c.last_exit == 0:
                        c.gave_up = True
                        LOG.info("[supervisor] %s exited cleanly",
                                  c.spec.agent_id[:8])
                        continue
                    now = time.time_ns()
                    if now - c.last_start_ns > self._restart_window_ns:
                        c.restarts = 0      # outside the window: a fresh budget
                    if c.restarts >= self._max_restarts:
                        c.gave_up = True
                        LOG.error(
                            "[supervisor] %s crashed %d times within %.0fs "
                            "(last exit %s); GIVING UP. A component that "
                            "cannot run is a fact, not something to hide "
                            "behind retries. Its claims return to the pool "
                            "when their lease expires.",
                            c.spec.agent_id[:8], c.restarts,
                            self._restart_window_ns / 1e9, c.last_exit)
                        continue
                    c.restarts += 1
                    LOG.warning(
                        "[supervisor] %s died (exit %s); restart %d/%d",
                        c.spec.agent_id[:8], c.last_exit, c.restarts,
                        self._max_restarts)
                    time.sleep(self._backoff_s * c.restarts)
                    self._spawn(c)


def _executor_target(spec: "RunnerSpec") -> "tuple[str, dict]":
    """Map `executor_kind` to the factory the sandbox should instantiate.

    Returned as a DOTTED PATH plus kwargs rather than a callable, because
    `make_sandboxed_executor` builds the executor INSIDE bwrap -- so the
    command, or the Anthropic client, inherits the sandbox's namespaces and
    rlimits rather than merely being wrapped by something that does.
    """
    if spec.executor_kind == "mock":
        return "gyza.executors:make_mock_executor", {
            "response": f"[{spec.agent_id[:8]}] done"}
    if spec.executor_kind == "command":
        if not spec.command_argv:
            raise ValueError(
                "executor_kind='command' requires command_argv")
        return "gyza.executors:make_command_executor", {
            "argv": list(spec.command_argv), "cwd": spec.command_cwd}
    if spec.executor_kind == "anthropic":
        return "gyza.runner:make_anthropic_executor", {
            "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "model": spec.model or "claude-sonnet-4-5"}
    raise ValueError(f"unknown executor_kind {spec.executor_kind!r}")


def run_runner_process(spec: "RunnerSpec") -> None:
    """Child entry point: build one runner from a spec and poll until killed.

    MODULE-LEVEL AND PICKLABLE-ARGUMENTED because `spawn` children re-import
    this module rather than forking a live heap. It opens its OWN blackboard
    handle -- sqlite connections do not cross a process boundary, and
    process-level claim exclusion is what makes several of them safe
    (`tests/test_claim_across_processes.py`, mutation-checked).
    """
    import json as _json

    import numpy as _np

    from gyza.blackboard import Blackboard as _BB
    from gyza.demand import LSHIndex as _LSH
    from gyza.drift import SpecializationTracker as _Spec
    from gyza.identity import AgentIdentity as _Ident
    from gyza.memory import EpisodicMemory as _Mem
    from gyza.network.artifact_store import ArtifactStore as _Store
    from gyza.runner import AgentRunner as _Runner, make_mock_executor
    from gyza.schema import EMBEDDING_DIM as _DIM

    saved = _json.loads(Path(spec.agent_state_path).read_text())
    ident = _Ident(bytes.fromhex(saved["seed_hex"]), saved["manifest"])

    inner, init_kwargs = _executor_target(spec)
    if spec.sandboxed:
        from gyza.containment.egress import default_egress_recorder
        from gyza.sandbox.config import sandbox_config_from_manifest
        from gyza.sandbox.executor import make_sandboxed_executor
        scfg = sandbox_config_from_manifest(ident.manifest)
        if spec.executor_kind == "anthropic":
            # The key crosses into the sandbox as an env var, exactly as
            # `gyza run` does it, and is read from THIS process's environment
            # rather than carried in the spec.
            import dataclasses as _dc
            key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not key:
                raise RuntimeError(
                    "executor_kind='anthropic' needs ANTHROPIC_API_KEY in the "
                    "environment; it is deliberately not carried in RunnerSpec")
            scfg = _dc.replace(scfg, env_set={"ANTHROPIC_API_KEY": key})
        executor = make_sandboxed_executor(
            inner, init_kwargs=init_kwargs, config=scfg,
            egress_recorder=default_egress_recorder(spec.blackboard_path),
        )
    else:
        from gyza.runner import make_mock_executor
        if spec.executor_kind != "mock":
            raise RuntimeError(
                f"executor_kind={spec.executor_kind!r} without a sandbox is "
                f"refused: real work outside bubblewrap carries no "
                f"bounds-proof, and an agent doing it would sign envelopes "
                f"that imply containment it never had")
        executor = make_mock_executor()

    bb = _BB(spec.blackboard_path)
    bb.attach_artifact_store(_Store(base_path=spec.artifact_store_path))
    v = _np.zeros(_DIM, dtype=_np.float32)
    v[0] = 1.0
    runner = _Runner(
        identity=ident, blackboard=bb,
        memory=_Mem(agent_id=ident.agent_id, db_path=spec.memory_path),
        specialization=_Spec(agent_id=ident.agent_id, initial_embedding=v,
                             db_path=spec.spec_db_path),
        lsh=_LSH(seed=42), executor=executor,
        min_reward_threshold=spec.min_reward,
        min_similarity_threshold=spec.min_similarity,
        poll_interval_s=spec.poll_interval_s,
        verify_chain_before_claim=False,
        # A sandboxed child stamps an enforcement record, so it can and must
        # refuse to sign without one. An unsandboxed one cannot.
        require_enforcement=spec.sandboxed,
    )
    runner.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop()
