"""
Phase 3 priority #24 — daemon supervisor.

A long-lived watcher around ``gyza-netd``. Today, if the daemon
crashes, the Python side notices on its next gRPC attempt and surfaces
``UNAVAILABLE`` to the caller — which is then on its own to decide
what to do. In production this means a single segfault takes a node
offline until manual intervention.

The supervisor closes that loop:

  * spawn the daemon on ``start()``
  * heartbeat every ``heartbeat_interval_s`` (default 5s) via
    ``NetdClient.is_running()``
  * after ``fail_threshold`` consecutive failures (default 3), kill
    any zombie subprocess and respawn from the same launch arguments
  * exponential backoff between respawn attempts: 1, 2, 4, 8, …,
    capped at 60s — saves us from thrashing when (e.g.) the listen
    port is permanently held by a misconfigured peer
  * after each successful respawn, fire a user-supplied ``on_respawn``
    callback so the GlobalCluster can re-publish DHT advertisements,
    re-join its gossip topics, and re-attempt cached peer
    reconnection (see ``PeerCache``)

The supervisor uses **one** stable ``NetdClient`` over the lifetime
of the process. Why: the Unix-socket gRPC channel auto-reconnects,
and reusing the same client object means callers (PeerRegistry,
LedgerSettlementService, the gossip thread) don't have to be aware
that respawns happen at all. The subprocess.Popen handle DOES rotate
each respawn — we own the kill/wait dance internally.

Trip-wire (CLAUDE.md §11): do NOT instantiate this from inside
``gyza global start`` and let it die with the CLI process. Wire it
into ``GlobalCluster``'s lifecycle so it shares the host process's
lifetime, or run it as a foreground long-running command.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from gyza.network.netd_client import NetdClient


LOG = logging.getLogger("gyza.daemon_supervisor")


@dataclass
class _SpawnArgs:
    """
    Frozen launch arguments forwarded to ``NetdClient.start_daemon``
    on every (re)spawn. Stored as a dataclass so respawns can't accidentally
    mutate them mid-flight.
    """
    socket_path: str
    binary_path: str
    listen_port: int
    key_path: str
    bootstrap: list[str] = field(default_factory=list)
    log_level: str = "info"
    startup_timeout_s: float = 10.0


class DaemonSupervisor:
    """
    Spawn-and-watch wrapper around gyza-netd.

    Use:
        sup = DaemonSupervisor(
            socket_path="~/.gyza/netd.sock",
            binary_path="~/dev/gyza/netd/bin/gyza-netd",
            listen_port=7749,
            key_path="~/.gyza/compositor.key",
        )
        sup.set_on_respawn(lambda netd: gc.recover_after_respawn())
        sup.start()
        # ... long-lived process; supervisor's heartbeat thread runs
        sup.stop()

    Attributes you should NOT touch from outside the class:
        _proc, _stop_evt, _consec_failures, _heartbeat_thread.
    The lifecycle is owned by start()/stop() and the heartbeat loop.
    """

    # Backoff schedule (seconds). After exhausting these, the loop holds
    # at the cap until either start() succeeds or stop() is called.
    BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0)

    def __init__(
        self,
        socket_path: str = "~/.gyza/netd.sock",
        binary_path: str = "~/dev/gyza/netd/bin/gyza-netd",
        listen_port: int = 7749,
        key_path: str = "~/.gyza/compositor.key",
        bootstrap: list[str] | None = None,
        log_level: str = "info",
        startup_timeout_s: float = 10.0,
        heartbeat_interval_s: float = 5.0,
        fail_threshold: int = 3,
    ):
        self._args = _SpawnArgs(
            socket_path=socket_path,
            binary_path=binary_path,
            listen_port=listen_port,
            key_path=key_path,
            bootstrap=list(bootstrap or []),
            log_level=log_level,
            startup_timeout_s=startup_timeout_s,
        )
        self._heartbeat_interval_s = heartbeat_interval_s
        self._fail_threshold = max(1, fail_threshold)

        # Stable client reused across respawns — gRPC autoreconnects
        # to the same Unix socket when the daemon comes back.
        self._client: NetdClient = NetdClient(socket_path)

        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()

        self._consec_failures = 0
        self._respawn_count = 0  # for telemetry / tests
        self._stop_evt = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

        self._on_respawn: Callable[[NetdClient], Any] | None = None

    # -- callbacks ------------------------------------------------------------

    def set_on_respawn(self, cb: Callable[[NetdClient], Any] | None) -> None:
        """
        Register a callback fired after every successful respawn. The
        callback receives the (still-the-same-instance) NetdClient and
        runs in the heartbeat thread — keep it short, off-load real work
        to its own scheduler if needed.

        Exceptions raised by the callback are caught and logged; they
        do NOT trigger another respawn (we just successfully respawned;
        bouncing again on a callback bug would mask the real issue).
        """
        self._on_respawn = cb

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """
        Launch the daemon and start the heartbeat thread. Raises on
        initial-spawn failure (caller should see the configuration
        error immediately, not retry forever). Idempotent — calling
        twice is a no-op.
        """
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return

        self._stop_evt.clear()
        self._consec_failures = 0
        proc = self._launch_one_attempt()
        with self._proc_lock:
            self._proc = proc

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="gyza-daemon-supervisor",
            daemon=True,
        )
        self._heartbeat_thread.start()
        LOG.info(
            "[supervisor] started (pid=%s, socket=%s)",
            proc.pid, self._args.socket_path,
        )

    def stop(self, timeout_s: float = 5.0) -> None:
        """
        Stop the heartbeat thread and terminate the daemon. Safe to
        call multiple times.
        """
        self._stop_evt.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=timeout_s)
            self._heartbeat_thread = None

        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is not None:
            self._terminate(proc, timeout_s=timeout_s)

        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass
        LOG.info("[supervisor] stopped")

    # -- introspection --------------------------------------------------------

    def is_alive(self) -> bool:
        """True iff the supervised daemon process is currently running."""
        with self._proc_lock:
            proc = self._proc
        return proc is not None and proc.poll() is None

    @property
    def respawn_count(self) -> int:
        """How many times the daemon has been successfully respawned. 0 on
        a clean run with no crashes. Used by tests."""
        return self._respawn_count

    @property
    def client(self) -> NetdClient:
        """The single NetdClient kept stable across respawns."""
        return self._client

    def current_proc(self) -> subprocess.Popen | None:
        """For callers (mostly tests) that want to inspect or kill the
        current subprocess. Holds no lock — caller takes the snapshot."""
        with self._proc_lock:
            return self._proc

    # -- internal -------------------------------------------------------------

    def _launch_one_attempt(self) -> subprocess.Popen:
        """One spawn attempt. Raises on failure."""
        return NetdClient.start_daemon(
            socket_path=self._args.socket_path,
            binary_path=self._args.binary_path,
            listen_port=self._args.listen_port,
            key_path=self._args.key_path,
            bootstrap=self._args.bootstrap or None,
            log_level=self._args.log_level,
            startup_timeout_s=self._args.startup_timeout_s,
        )

    def _terminate(self, proc: subprocess.Popen, timeout_s: float = 5.0) -> None:
        """Best-effort terminate-then-kill of the supervised subprocess."""
        if proc.poll() is not None:
            return  # already gone
        try:
            proc.terminate()
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            LOG.warning("[supervisor] terminate timed out, killing pid=%s", proc.pid)
            proc.kill()
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                LOG.error("[supervisor] kill timed out for pid=%s", proc.pid)

    def _heartbeat_loop(self) -> None:
        """
        Run every ``heartbeat_interval_s``. Each tick:

          1. If the subprocess has exited (poll() != None) — count as failure.
          2. Else call netd.is_running() — count False as failure.
          3. After ``fail_threshold`` consecutive failures: respawn.

        Stop on ``_stop_evt``.
        """
        while not self._stop_evt.is_set():
            # Use Event.wait for cancelable sleep.
            if self._stop_evt.wait(self._heartbeat_interval_s):
                return

            healthy = self._check_health()
            if healthy:
                self._consec_failures = 0
                continue

            self._consec_failures += 1
            LOG.info(
                "[supervisor] health check failed (%d/%d)",
                self._consec_failures, self._fail_threshold,
            )
            if self._consec_failures < self._fail_threshold:
                continue

            # Threshold exceeded — respawn.
            self._do_respawn()
            self._consec_failures = 0

    def _check_health(self) -> bool:
        with self._proc_lock:
            proc = self._proc
        if proc is None:
            return False
        if proc.poll() is not None:
            # Subprocess exited.
            return False
        try:
            return self._client.is_running()
        except Exception:  # noqa: BLE001
            return False

    def _do_respawn(self) -> None:
        """
        Kill any zombie subprocess and try to respawn with backoff.
        Returns when respawn succeeds or stop_evt is set.
        """
        with self._proc_lock:
            old = self._proc
            self._proc = None
        if old is not None:
            self._terminate(old)

        attempt = 0
        while not self._stop_evt.is_set():
            try:
                proc = self._launch_one_attempt()
            except Exception as e:  # noqa: BLE001
                delay = self._backoff_for(attempt)
                LOG.warning(
                    "[supervisor] respawn attempt %d failed: %s; "
                    "sleeping %.1fs",
                    attempt + 1, e, delay,
                )
                if self._stop_evt.wait(delay):
                    return
                attempt += 1
                continue

            with self._proc_lock:
                self._proc = proc
            self._respawn_count += 1
            LOG.warning(
                "[supervisor] respawned netd (pid=%s, count=%d)",
                proc.pid, self._respawn_count,
            )
            if self._on_respawn is not None:
                try:
                    self._on_respawn(self._client)
                except Exception as e:  # noqa: BLE001
                    LOG.warning("[supervisor] on_respawn callback raised: %s", e)
            return

    @classmethod
    def _backoff_for(cls, attempt: int) -> float:
        idx = min(attempt, len(cls.BACKOFF_SCHEDULE) - 1)
        return cls.BACKOFF_SCHEDULE[idx]


__all__ = ["DaemonSupervisor"]
