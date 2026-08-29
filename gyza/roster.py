"""
A FIXED ROSTER OF AGENTS AS THREADS IN ONE PROCESS.

`RunnerProcessSupervisor` gives every agent its own OS process, which is the
right default and the wrong topology past a few dozen agents: the per-process
baseline is ~138 MB (interpreter, numpy/blake3/cryptography, the embedder), so
500 agents cost ~69 GB. The same 500 as threads cost ~0.5 GB, because the
marginal cost of a runner is 0.15-0.27 MB once its process exists.

THREADS ARE THE CORRECT TOPOLOGY HERE, AND THAT WAS MEASURED BEFORE IT WAS
CHOSEN. Subprocess-bound work scales **29.89x at 32 threads**; CPU-bound work
scales **0.66x** (`research/scale/FINDINGS_THREADED_500.md`). An agent spends
~1 s inside bwrap per action and ~0.1 ms in Python, and the GIL is released
across the subprocess call, so the negative-scaling result that governs the
poll path does not govern this one.

## What is isolated, and what is not

`supervisor.py` declines to adopt a threaded roster because "threads share a
fate -- one unhandled exception in one runner takes the whole roster." That is
half right and the half matters:

  * **A Python exception does NOT cross threads.** `AgentRunner.start()` runs
    its loop in its own daemon thread, so an unhandled error kills that thread
    alone. What was missing was anything to NOTICE -- a dead daemon thread
    leaves no trace. This class watches liveness and restarts, which is exactly
    the isolation the objection asks for.
  * **A PROCESS-LEVEL fault genuinely is shared.** An OOM kill, a segfault in a
    C extension, or an `os._exit` takes all 500 agents at once, and no amount
    of care here changes that. That is the real price of the 130x memory
    saving, and it is stated rather than engineered around.

**So: use the process supervisor when agent count is small enough to afford it,
and this when it is not.** They are not competitors; they trade the same two
resources in opposite directions.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from gyza.supervisor import RunnerSpec, _executor_target

LOG = logging.getLogger(__name__)

#: A runner that has claimed work and finished none of it for this long is
#: stalled. Generous relative to a ~1 s sandboxed action, because a slow action
#: is not a fault and restarting a working agent destroys the work in flight.
DEFAULT_STALL_TIMEOUT_S = 120.0


@dataclass
class _Slot:
    spec: RunnerSpec
    runner: object = None
    restarts: int = 0
    gave_up: bool = False
    last_error: str = ""
    completions: int = 0
    last_progress_ns: int = 0
    saw_attempt: bool = False


class RunnerThreadRoster:
    """Start a fixed roster of agents as threads; restart the ones that die or
    stall; stop them all cleanly.

    Shares one `Blackboard`, one `LSHIndex` and one executor across the roster.
    Sharing the blackboard is safe because its connection is THREAD-LOCAL
    (`Blackboard._conn` keys off `self._tls`), so each thread gets its own
    SQLite handle; sharing the LSH is what takes the marginal cost of a runner
    from 9.6 MB to 0.27, because the alternative builds one plane set per agent.
    """

    def __init__(self, specs: "list[RunnerSpec]", *, blackboard,
                 max_restarts: int = 5, poll_interval_s: float = 2.0,
                 stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S) -> None:
        if not specs:
            raise ValueError("a roster needs at least one RunnerSpec")
        self._bb = blackboard
        self._slots = [_Slot(spec=s) for s in specs]
        self._max_restarts = int(max_restarts)
        self._poll_s = float(poll_interval_s)
        self._stall_ns = int(stall_timeout_s * 1e9)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._watch: threading.Thread | None = None

    # -- construction ---------------------------------------------------
    def _build(self, spec: RunnerSpec):
        """One runner. Everything expensive is shared; everything stateful is
        per-agent."""
        import json

        import numpy as np

        from gyza.demand import LSHIndex
        from gyza.drift import SpecializationTracker
        from gyza.identity import AgentIdentity
        from gyza.memory import EpisodicMemory
        from gyza.runner import AgentRunner
        from gyza.schema import EMBEDDING_DIM

        if not hasattr(self, "_lsh"):
            self._lsh = LSHIndex(seed=42)
        state = json.loads(open(spec.agent_state_path).read())
        ident = AgentIdentity(bytes.fromhex(state["seed_hex"]),
                              state["manifest"])

        key = (spec.executor_kind, spec.command_argv, spec.sandboxed)
        cache = getattr(self, "_execs", None)
        if cache is None:
            cache = self._execs = {}
        if key not in cache:
            cache[key] = self._make_executor(spec, ident)
        v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        v[0] = 1.0
        return ident, AgentRunner(
            identity=ident, blackboard=self._bb,
            memory=EpisodicMemory(agent_id=ident.agent_id,
                                  db_path=spec.memory_path),
            specialization=SpecializationTracker(
                agent_id=ident.agent_id, initial_embedding=v,
                db_path=spec.spec_db_path),
            lsh=self._lsh, executor=cache[key],
            min_reward_threshold=spec.min_reward,
            min_similarity_threshold=spec.min_similarity,
            verify_chain_before_claim=False,
            poll_interval_s=spec.poll_interval_s,
            # A SANDBOXED ROSTER REFUSES TO SIGN WITHOUT A BOUNDS-PROOF, on the
            # same trigger the process path uses. An unsandboxed roster does
            # not, and cannot claim containment.
            require_enforcement=bool(spec.sandboxed))

    def _make_executor(self, spec: RunnerSpec, ident):
        inner, init_kwargs = _executor_target(spec)
        if not spec.sandboxed:
            mod, _, fn = inner.partition(":")
            import importlib
            return getattr(importlib.import_module(mod), fn)(**init_kwargs)
        from gyza.sandbox.config import SandboxConfig
        from gyza.sandbox.executor import make_sandboxed_executor
        budget = (ident.manifest.get("capabilities", {})
                  .get("spawn", {}).get("resource_budget", {}) or {})
        return make_sandboxed_executor(
            inner, init_kwargs=init_kwargs,
            config=SandboxConfig(
                ro_paths=[], rw_paths=[], requires_network=False,
                max_memory_mb=int(budget.get("memory_limit_mb", 512) or 512)))

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        for slot in self._slots:
            self._start_slot(slot)
        self._watch = threading.Thread(target=self._watch_loop,
                                       name="gyza-roster-watch", daemon=True)
        self._watch.start()
        LOG.info("[roster] started %d agent thread(s)", len(self._slots))

    def _start_slot(self, slot: _Slot) -> bool:
        """Build and start one agent. A FAILURE HERE IS ISOLATED: it is
        recorded against the slot and the rest of the roster proceeds, because
        one unbuildable agent must not prevent 499 working ones from running."""
        try:
            _ident, runner = self._build(slot.spec)
            runner.start()
            slot.runner = runner
            slot.last_progress_ns = time.time_ns()
            return True
        except Exception as exc:                                # noqa: BLE001
            slot.last_error = f"{type(exc).__name__}: {exc}"[:200]
            slot.gave_up = True
            LOG.warning("[roster] %s failed to start: %s",
                        slot.spec.agent_id[:8], slot.last_error)
            return False

    def stop(self, timeout_s: float = 30.0) -> None:
        self._stop.set()
        for slot in self._slots:
            if slot.runner is not None:
                try:
                    slot.runner.stop()
                except Exception:                               # noqa: BLE001
                    pass
        deadline = time.monotonic() + timeout_s
        for slot in self._slots:
            t = getattr(slot.runner, "_thread", None)
            if t is not None:
                t.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._watch is not None:
            self._watch.join(timeout=5.0)

    def status(self) -> "list[dict]":
        with self._lock:
            return [{"agent_id": s.spec.agent_id, "restarts": s.restarts,
                     "gave_up": s.gave_up, "alive": self._alive(s),
                     "completions": s.completions,
                     "last_error": s.last_error} for s in self._slots]

    def summary(self) -> dict:
        st = self.status()
        return {"agents": len(st),
                "alive": sum(1 for s in st if s["alive"]),
                "gave_up": sum(1 for s in st if s["gave_up"]),
                "restarts": sum(s["restarts"] for s in st)}

    # -- supervision ----------------------------------------------------
    @staticmethod
    def _alive(slot: _Slot) -> bool:
        t = getattr(slot.runner, "_thread", None)
        return bool(t is not None and t.is_alive())

    def _completions_since(self, slot: _Slot, since_ns: int):
        try:
            return int(self._bb.count_agent_envelopes_since(
                slot.spec.agent_id, since_ns))
        except Exception:                                       # noqa: BLE001
            return None

    def _check_progress(self, slot: _Slot, now: int) -> bool:
        """True iff this agent should be restarted for making no progress.

        LIVENESS IS NOT PROGRESS, and the converse trap is real: an agent with
        nothing to do makes no progress and is perfectly healthy. The signal is
        ATTEMPTING -- claiming work and finishing none of it is a fault;
        claiming nothing is a choice. Copied deliberately from the process
        supervisor rather than reinvented, because a negative control caught
        this exact distinction there.
        """
        done = self._completions_since(slot, slot.last_progress_ns)
        if done is None:
            return False
        if done > 0:
            slot.completions += done
            slot.last_progress_ns = now
            return False
        if self._holds_a_claim(slot) is True:
            slot.saw_attempt = True
        if now - slot.last_progress_ns < self._stall_ns:
            return False
        if not slot.saw_attempt:
            slot.last_progress_ns = now
            return False
        slot.saw_attempt = False
        return True

    def _holds_a_claim(self, slot: _Slot):
        try:
            row = self._bb._conn().execute(
                "SELECT 1 FROM work_items WHERE claimed_by=? "
                "AND completed_at_ns IS NULL LIMIT 1",
                (slot.spec.agent_id,)).fetchone()
            return row is not None
        except Exception:                                       # noqa: BLE001
            return None

    def _watch_loop(self) -> None:
        while not self._stop.wait(self._poll_s):
            now = time.time_ns()
            with self._lock:
                for slot in self._slots:
                    if slot.gave_up or slot.runner is None:
                        continue
                    dead = not self._alive(slot)
                    stalled = (not dead) and self._check_progress(slot, now)
                    if not (dead or stalled):
                        continue
                    if stalled:
                        try:
                            slot.runner.stop()
                        except Exception:                       # noqa: BLE001
                            pass
                    slot.restarts += 1
                    if slot.restarts > self._max_restarts:
                        slot.gave_up = True
                        LOG.warning("[roster] %s gave up after %d restart(s)",
                                    slot.spec.agent_id[:8], slot.restarts - 1)
                        continue
                    LOG.info("[roster] restarting %s (%s), attempt %d/%d",
                             slot.spec.agent_id[:8],
                             "stalled" if stalled else "thread died",
                             slot.restarts, self._max_restarts)
                    slot.gave_up = False
                    if not self._start_slot(slot):
                        continue
                    slot.saw_attempt = False
