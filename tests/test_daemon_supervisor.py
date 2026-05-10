"""
Tests for DaemonSupervisor (Phase 3 priority #24).

We don't spawn a real ``gyza-netd`` here — those integration paths are
covered by ``tests/test_netd_client.py``. The supervisor's job is the
heartbeat / respawn / backoff / callback lifecycle, which we test by
patching ``NetdClient.start_daemon`` to return a fake subprocess and
overriding ``NetdClient.is_running`` per-tick to script the failure
scenarios we want to exercise.

Knobs to keep timings sane:

  * ``heartbeat_interval_s=0.05`` — fast enough that ``threshold * iv``
    is well under each test's deadline
  * ``BACKOFF_SCHEDULE`` is patched per test where we exercise it,
    so respawn doesn't sleep seconds
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from gyza.network import daemon_supervisor as ds_mod
from gyza.network.daemon_supervisor import DaemonSupervisor
from gyza.network.netd_client import NetdClient


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------

class _FakeProc:
    """
    Mimics ``subprocess.Popen`` to the surface DaemonSupervisor uses:
    ``poll`` / ``terminate`` / ``wait`` / ``kill`` / ``pid``.

    ``alive=True`` means poll() returns None; setting ``alive=False``
    flips poll() to the exit code (default 0).
    """
    _next_pid = 9000

    def __init__(self):
        _FakeProc._next_pid += 1
        self.pid = _FakeProc._next_pid
        self.alive = True
        self.exit_code = 0
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return None if self.alive else self.exit_code

    def terminate(self):
        self.terminate_calls += 1
        self.alive = False

    def kill(self):
        self.kill_calls += 1
        self.alive = False

    def wait(self, timeout: float | None = None):
        # Already-flipped processes return their exit code; living ones
        # would block forever in real Popen but the supervisor only
        # calls wait() after terminate(). We just return the code.
        return self.exit_code


@pytest.fixture
def patched_spawn(monkeypatch):
    """
    Replaces ``NetdClient.start_daemon`` with a recorder that returns
    a fresh ``_FakeProc`` each call. Yields a list of every (kwargs,
    proc) pair launched, so tests can assert on respawn count and
    spawn-arg stability.
    """
    spawned: list[tuple[dict, _FakeProc]] = []

    def fake_start_daemon(**kwargs: Any) -> _FakeProc:
        proc = _FakeProc()
        spawned.append((dict(kwargs), proc))
        return proc

    monkeypatch.setattr(NetdClient, "start_daemon", staticmethod(fake_start_daemon))
    yield spawned


@pytest.fixture
def patched_is_running(monkeypatch):
    """
    Replaces NetdClient.is_running with a deque-driven script. The
    test pushes True/False values onto ``script``; when empty, the
    default is True (healthy steady-state).
    """
    state = {"script": [], "default": True}

    def fake_is_running(self) -> bool:  # noqa: ARG001
        if state["script"]:
            return state["script"].pop(0)
        return state["default"]

    monkeypatch.setattr(NetdClient, "is_running", fake_is_running)
    return state


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _wait_until(predicate, timeout_s: float = 2.0, interval_s: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _make_supervisor(**overrides):
    """Cheap defaults so each test only specifies what it cares about."""
    args = dict(
        socket_path="/tmp/gyza-supervisor-test.sock",
        binary_path="/nonexistent/gyza-netd",
        listen_port=17749,
        key_path="/tmp/gyza-supervisor-test.key",
        heartbeat_interval_s=0.05,
        fail_threshold=3,
    )
    args.update(overrides)
    return DaemonSupervisor(**args)


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------

def test_start_invokes_start_daemon_once(patched_spawn, patched_is_running):
    sup = _make_supervisor()
    sup.start()
    try:
        assert len(patched_spawn) == 1
        assert sup.is_alive()
        assert sup.respawn_count == 0
    finally:
        sup.stop()


def test_stop_terminates_subprocess(patched_spawn, patched_is_running):
    sup = _make_supervisor()
    sup.start()
    proc = patched_spawn[0][1]
    assert proc.alive is True
    sup.stop()
    assert proc.terminate_calls >= 1
    assert proc.alive is False


def test_double_start_is_noop(patched_spawn, patched_is_running):
    sup = _make_supervisor()
    sup.start()
    try:
        sup.start()
        assert len(patched_spawn) == 1
    finally:
        sup.stop()


def test_threshold_failures_trigger_respawn(
    patched_spawn, patched_is_running, monkeypatch,
):
    """
    Three consecutive False from is_running → kill + respawn. Verify:
      * a second start_daemon call landed (respawn happened)
      * the original subprocess was terminated
      * respawn_count == 1
    """
    # Force backoff to zero so test doesn't wait on real seconds.
    monkeypatch.setattr(DaemonSupervisor, "BACKOFF_SCHEDULE", (0.0,))

    sup = _make_supervisor(heartbeat_interval_s=0.02, fail_threshold=3)
    patched_is_running["script"] = [False, False, False]
    patched_is_running["default"] = True  # everything after the script is healthy

    sup.start()
    try:
        original_proc = patched_spawn[0][1]
        ok = _wait_until(lambda: sup.respawn_count >= 1, timeout_s=5.0)
        assert ok, "supervisor never respawned within 5s"
        assert original_proc.terminate_calls >= 1
        assert len(patched_spawn) == 2
        assert sup.is_alive()
    finally:
        sup.stop()


def test_intermittent_failures_below_threshold_do_not_respawn(
    patched_spawn, patched_is_running, monkeypatch,
):
    """
    Two failures then recovery → no respawn. Counter resets on healthy.
    """
    monkeypatch.setattr(DaemonSupervisor, "BACKOFF_SCHEDULE", (0.0,))
    sup = _make_supervisor(heartbeat_interval_s=0.02, fail_threshold=3)
    patched_is_running["script"] = [False, False, True, True, True]
    sup.start()
    try:
        # Wait long enough for the script to drain.
        time.sleep(0.3)
        assert sup.respawn_count == 0
        assert len(patched_spawn) == 1
    finally:
        sup.stop()


def test_subprocess_exit_counts_as_failure(
    patched_spawn, patched_is_running, monkeypatch,
):
    """
    If the subprocess dies on its own, poll() != None. The supervisor
    should respawn even if is_running() never gets called.
    """
    monkeypatch.setattr(DaemonSupervisor, "BACKOFF_SCHEDULE", (0.0,))
    sup = _make_supervisor(heartbeat_interval_s=0.02, fail_threshold=3)
    sup.start()
    try:
        # Kill the subprocess directly — supervisor should detect.
        original = patched_spawn[0][1]
        original.alive = False
        original.exit_code = 137  # SIGKILL-ish
        ok = _wait_until(lambda: sup.respawn_count >= 1, timeout_s=5.0)
        assert ok, "supervisor missed subprocess exit"
    finally:
        sup.stop()


def test_on_respawn_callback_fires_with_client(
    patched_spawn, patched_is_running, monkeypatch,
):
    monkeypatch.setattr(DaemonSupervisor, "BACKOFF_SCHEDULE", (0.0,))
    sup = _make_supervisor(heartbeat_interval_s=0.02, fail_threshold=2)

    callbacks: list[NetdClient] = []
    cb_event = threading.Event()

    def cb(netd: NetdClient) -> None:
        callbacks.append(netd)
        cb_event.set()

    sup.set_on_respawn(cb)
    patched_is_running["script"] = [False, False]

    sup.start()
    try:
        assert cb_event.wait(timeout=5.0), "on_respawn callback never fired"
        assert callbacks == [sup.client], (
            "callback received wrong NetdClient — supervisor should pass "
            "its own stable instance"
        )
    finally:
        sup.stop()


def test_callback_exception_does_not_kill_loop(
    patched_spawn, patched_is_running, monkeypatch,
):
    """
    A bug in the user's on_respawn must NOT cause the supervisor to
    bounce the daemon again — that would mask the real issue and
    produce a respawn storm. The exception is logged and swallowed.
    """
    monkeypatch.setattr(DaemonSupervisor, "BACKOFF_SCHEDULE", (0.0,))
    sup = _make_supervisor(heartbeat_interval_s=0.02, fail_threshold=2)

    sup.set_on_respawn(lambda netd: (_ for _ in ()).throw(RuntimeError("boom")))
    patched_is_running["script"] = [False, False]

    sup.start()
    try:
        ok = _wait_until(lambda: sup.respawn_count >= 1, timeout_s=5.0)
        assert ok
        # Give the heartbeat a few more ticks to potentially misbehave.
        time.sleep(0.3)
        assert sup.respawn_count == 1, (
            "supervisor respawned again after callback exception — should not"
        )
    finally:
        sup.stop()


def test_backoff_schedule_caps_at_60s():
    """
    Direct unit on the backoff helper — at attempt 0 we get 1s, at
    attempt 100 we get 60s (the cap), schedule monotone non-decreasing.
    """
    backoffs = [DaemonSupervisor._backoff_for(i) for i in range(0, 200)]
    assert backoffs[0] == 1.0
    assert backoffs[-1] == 60.0
    # Must be monotone non-decreasing.
    for prev, nxt in zip(backoffs, backoffs[1:]):
        assert nxt >= prev


def test_respawn_uses_same_launch_args(
    patched_spawn, patched_is_running, monkeypatch,
):
    """
    Frozen ``_SpawnArgs`` is the contract — a respawn must dial the
    same socket / port / key, not a mutated version.
    """
    monkeypatch.setattr(DaemonSupervisor, "BACKOFF_SCHEDULE", (0.0,))
    sup = _make_supervisor(
        heartbeat_interval_s=0.02,
        fail_threshold=2,
        listen_port=18749,
        socket_path="/tmp/gyza-respawn-args-test.sock",
    )
    patched_is_running["script"] = [False, False]

    sup.start()
    try:
        ok = _wait_until(lambda: sup.respawn_count >= 1, timeout_s=5.0)
        assert ok
        first_args, _ = patched_spawn[0]
        second_args, _ = patched_spawn[1]
        # Compare each field — bootstrap is normalized to a list, so both
        # pre-and-post-respawn calls should pass `bootstrap=None` since
        # we didn't supply any.
        assert first_args == second_args
    finally:
        sup.stop()


def test_stop_during_respawn_backoff(
    patched_spawn, patched_is_running, monkeypatch,
):
    """
    If we call stop() while the supervisor is inside its backoff
    sleep waiting to retry a failed spawn, stop() returns promptly
    and the heartbeat thread joins cleanly.
    """
    # Make every spawn attempt raise so we land in the backoff loop.
    def always_fails(**_: Any) -> _FakeProc:
        raise RuntimeError("no binary")
    monkeypatch.setattr(NetdClient, "start_daemon", staticmethod(always_fails))
    # Long backoff so we'd notice if stop() didn't preempt it.
    monkeypatch.setattr(DaemonSupervisor, "BACKOFF_SCHEDULE", (5.0,))

    sup = _make_supervisor(heartbeat_interval_s=0.02, fail_threshold=1)
    # First start_daemon happens during start(). It raises, so start()
    # bubbles. We need to instead simulate: spawn ok, then lose health.
    # Let start succeed once.
    successful = {"once": True}
    real_calls = []

    def first_ok_then_fail(**kwargs: Any):
        real_calls.append(kwargs)
        if successful["once"]:
            successful["once"] = False
            return _FakeProc()
        raise RuntimeError("no binary")

    monkeypatch.setattr(NetdClient, "start_daemon", staticmethod(first_ok_then_fail))
    patched_is_running["script"] = [False, False, False]

    sup.start()
    # Wait for the supervisor to reach the backoff loop.
    ok = _wait_until(lambda: len(real_calls) >= 2, timeout_s=2.0)
    assert ok

    t0 = time.monotonic()
    sup.stop()
    elapsed = time.monotonic() - t0
    # Must come back well before the 5s backoff would have completed.
    assert elapsed < 1.0, f"stop() blocked for {elapsed:.2f}s"


# ----------------------------------------------------------------------
# Note: we don't rely on the `ds_mod` re-import at the top, but keep
# it so a future test wanting to monkey-patch a module-level constant
# (LOG, BACKOFF_SCHEDULE on the module rather than the class) has the
# right reference name without re-importing.
# ----------------------------------------------------------------------
_ = ds_mod
