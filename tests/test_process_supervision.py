"""A crashed runner must come back, and a runner that cannot run must not.

Phase 2 of the deployment work, and it could not have landed first: supervision
makes a crash ROUTINE, and until the claim lease existed a runner that died
holding a claim leaked that work item permanently. Restarting crashed runners
on top of that leak would have made the system strictly worse -- so
`tests/test_claim_lease.py` is a prerequisite for this file, not a companion.

Every test here supervises a target whose failure it CONTROLS. Supervising a
real runner and hoping it crashes would test the runner; the subject is the
supervisor.
"""
from __future__ import annotations

import time

import pytest

from gyza.supervisor import RunnerProcessSupervisor, RunnerSpec


def _spec(name: str) -> RunnerSpec:
    return RunnerSpec(
        agent_id=name, agent_state_path="/nonexistent/agent.json",
        blackboard_path="/nonexistent/bb.db",
        memory_path="/nonexistent/mem", spec_db_path="/nonexistent/s.db",
        artifact_store_path="/nonexistent/cas")


# Module-level targets: `spawn` children unpickle their target, so a closure
# or a local function cannot cross the process boundary.
def _target_crash_immediately(spec):
    raise SystemExit(7)


def _target_sleep_forever(spec):
    time.sleep(600)


def _target_exit_clean(spec):
    return None


def _wait(pred, timeout_s=20.0, tick=0.1):
    end = time.time() + timeout_s
    while time.time() < end:
        if pred():
            return True
        time.sleep(tick)
    return False


def test_a_crashed_child_is_RESTARTED():
    sup = RunnerProcessSupervisor(
        [_spec("crasher")], max_restarts=3, backoff_s=0.05,
        poll_interval_s=0.05, target=_target_crash_immediately)
    sup.start()
    try:
        assert _wait(lambda: sup.status()[0]["restarts"] >= 1), sup.status()
    finally:
        sup.stop(timeout_s=10)


def test_a_CRASH_LOOP_is_given_up_on_rather_than_respawned_forever():
    """A supervisor that restarts unconditionally turns a deterministic failure
    into an infinite respawn: it burns a core, floods the log, and shows the
    operator a healthy supervisor in front of a broken agent."""
    sup = RunnerProcessSupervisor(
        [_spec("looper")], max_restarts=2, backoff_s=0.05,
        poll_interval_s=0.05, target=_target_crash_immediately)
    sup.start()
    try:
        assert _wait(lambda: sup.status()[0]["gave_up"]), sup.status()
        st = sup.status()[0]
        assert st["restarts"] == 2, st
        # and it STAYS given up -- no quiet resurrection
        time.sleep(0.5)
        assert sup.status()[0]["restarts"] == 2
        assert sup.status()[0]["last_exit"] == 7
    finally:
        sup.stop(timeout_s=10)


def test_a_HEALTHY_child_is_left_alone():
    """The counter-control. A supervisor that restarted working children would
    be indistinguishable from one that never worked."""
    sup = RunnerProcessSupervisor(
        [_spec("healthy")], max_restarts=3, backoff_s=0.05,
        poll_interval_s=0.05, target=_target_sleep_forever)
    sup.start()
    try:
        assert _wait(lambda: sup.status()[0]["alive"], timeout_s=10)
        time.sleep(1.0)
        st = sup.status()[0]
        assert st["alive"] is True
        assert st["restarts"] == 0, "a living child was restarted"
        assert st["gave_up"] is False
    finally:
        sup.stop(timeout_s=10)


def test_a_CLEAN_EXIT_is_not_treated_as_a_crash():
    """Exit 0 is a decision, not a failure. Restarting it would fight the
    child's own choice to stop."""
    sup = RunnerProcessSupervisor(
        [_spec("finisher")], max_restarts=3, backoff_s=0.05,
        poll_interval_s=0.05, target=_target_exit_clean)
    sup.start()
    try:
        assert _wait(lambda: sup.status()[0]["gave_up"]), sup.status()
        assert sup.status()[0]["restarts"] == 0, "a clean exit was restarted"
        assert sup.status()[0]["last_exit"] == 0
    finally:
        sup.stop(timeout_s=10)


def test_stop_TERMINATES_every_child():
    sup = RunnerProcessSupervisor(
        [_spec(f"a{i}") for i in range(3)], poll_interval_s=0.05,
        target=_target_sleep_forever)
    sup.start()
    assert _wait(lambda: all(s["alive"] for s in sup.status()), timeout_s=15)
    sup.stop(timeout_s=15)
    assert not any(s["alive"] for s in sup.status()), sup.status()


def test_the_roster_is_FIXED_not_demand_driven():
    """Deliberate scope. `AgentSupervisor` spawns on demand and is a different
    mechanism; this one answers only 'are the runners I was told to run,
    running?'. Conflating them would make a restart indistinguishable from a
    scale-up."""
    sup = RunnerProcessSupervisor(
        [_spec("a"), _spec("b")], poll_interval_s=0.05,
        target=_target_sleep_forever)
    sup.start()
    try:
        assert _wait(lambda: len(sup.status()) == 2)
        time.sleep(0.4)
        assert len(sup.status()) == 2, "the roster changed size on its own"
    finally:
        sup.stop(timeout_s=10)


def test_negative_max_restarts_is_REFUSED():
    with pytest.raises(ValueError, match="max_restarts"):
        RunnerProcessSupervisor([_spec("x")], max_restarts=-1)


def test_the_spec_is_PICKLABLE_because_spawn_children_unpickle_it():
    """A factory closure over a live Blackboard cannot cross a process
    boundary. This is why the roster is values and paths, and why a restarted
    child is identical to the one it replaces."""
    import pickle

    s = _spec("p")
    assert pickle.loads(pickle.dumps(s)) == s


# =========================================================================== #
#  LIVENESS IS NOT PROGRESS
#
#  Watching `proc.is_alive()` was not enough, and a real defect proved it:
#  `EpisodicMemory` raised on every write, `_run_loop` caught the error,
#  released the claim and looped, so three agents polled and failed forever
#  while every process stayed alive and this supervisor called them healthy.
#
#  A HEARTBEAT WOULD NOT HAVE CAUGHT IT. The loop was running; it was even
#  doing work. What it was not doing was FINISHING any. Only progress separates
#  those, and progress has a trap of its own -- an agent with nothing to do
#  makes none and is perfectly healthy -- so the signal must be conditional:
#  work was available AND this agent completed none of it.
# =========================================================================== #

def _target_busy_but_useless(spec):
    """Alive, looping, achieving nothing -- defect 1, distilled."""
    while True:
        time.sleep(0.05)


class _FakeBoard:
    """Stands in for the blackboard so a test controls both facts the
    supervisor reads: completions, and whether the agent is ATTEMPTING work.

    `attempting` rather than `work_available`, and my own negative control is
    why: availability convicted an IDLE fleet, because the board held old
    items those agents were never going to take. Claiming-and-not-finishing is
    the defect; claiming nothing is a choice.
    """

    def __init__(self, completions=0, attempting=True):
        self.completions = completions
        self.attempting = attempting


def _install_board(monkeypatch, sup, board):
    monkeypatch.setattr(sup, "_completions_since",
                        lambda spec, since: board.completions)
    monkeypatch.setattr(sup, "_holds_a_claim", lambda spec: board.attempting)


def test_an_ALIVE_but_stalled_agent_is_restarted(monkeypatch):
    board = _FakeBoard(completions=0, attempting=True)
    sup = RunnerProcessSupervisor(
        [_spec("stalled")], max_restarts=5, backoff_s=0.05,
        poll_interval_s=0.05, stall_timeout_s=0.2,
        target=_target_busy_but_useless)
    _install_board(monkeypatch, sup, board)
    sup.start()
    try:
        assert _wait(lambda: sup.status()[0]["stall_restarts"] >= 1), sup.status()
    finally:
        sup.stop(timeout_s=10)


def test_an_agent_that_CLAIMS_NOTHING_is_NOT_restarted(monkeypatch):
    """THE COUNTER-CONTROL, and it caught a real false positive in the first
    version of this signal. An idle fleet was restarted because the board held
    unclaimed items those agents were never going to take -- wrong tier, wrong
    specialisation, already failed locally. Declining is not failing."""
    board = _FakeBoard(completions=0, attempting=False)
    sup = RunnerProcessSupervisor(
        [_spec("idle")], max_restarts=5, backoff_s=0.05,
        poll_interval_s=0.05, stall_timeout_s=0.2,
        target=_target_sleep_forever)
    _install_board(monkeypatch, sup, board)
    sup.start()
    try:
        time.sleep(1.5)                  # many stall windows
        st = sup.status()[0]
        assert st["stall_restarts"] == 0, "an idle agent was restarted"
        assert st["alive"] is True
    finally:
        sup.stop(timeout_s=10)


def test_a_PROGRESSING_agent_is_not_restarted_however_slow_the_queue(monkeypatch):
    board = _FakeBoard(completions=1, attempting=True)
    sup = RunnerProcessSupervisor(
        [_spec("working")], max_restarts=5, backoff_s=0.05,
        poll_interval_s=0.05, stall_timeout_s=0.2,
        target=_target_sleep_forever)
    _install_board(monkeypatch, sup, board)
    sup.start()
    try:
        time.sleep(1.0)
        st = sup.status()[0]
        assert st["stall_restarts"] == 0, "a progressing agent was restarted"
        assert st["completions"] > 0
    finally:
        sup.stop(timeout_s=10)


def test_an_UNREADABLE_blackboard_never_convicts(monkeypatch):
    """An unanswerable question must not convict. If the supervisor cannot
    read progress or availability, restarting on that silence would make a
    busy database look like a broken fleet."""
    sup = RunnerProcessSupervisor(
        [_spec("unknown")], max_restarts=5, backoff_s=0.05,
        poll_interval_s=0.05, stall_timeout_s=0.2,
        target=_target_sleep_forever)
    monkeypatch.setattr(sup, "_completions_since", lambda spec, since: None)
    monkeypatch.setattr(sup, "_holds_a_claim", lambda spec: None)
    sup.start()
    try:
        time.sleep(1.0)
        assert sup.status()[0]["stall_restarts"] == 0
    finally:
        sup.stop(timeout_s=10)


def test_a_STALL_LOOP_hits_the_same_ceiling_as_a_crash_loop(monkeypatch):
    """A runner that cannot make progress twice will not make it a third time.
    Hiding that behind restarts is what the ceiling exists to prevent."""
    board = _FakeBoard(completions=0, attempting=True)
    sup = RunnerProcessSupervisor(
        [_spec("hopeless")], max_restarts=2, backoff_s=0.05,
        poll_interval_s=0.05, stall_timeout_s=0.15,
        target=_target_busy_but_useless)
    _install_board(monkeypatch, sup, board)
    sup.start()
    try:
        assert _wait(lambda: sup.status()[0]["gave_up"], timeout_s=25), sup.status()
        assert sup.status()[0]["restarts"] == 2
    finally:
        sup.stop(timeout_s=10)


def test_progress_is_read_from_the_APPEND_ONLY_LOG_not_self_reported():
    """A child that reports its own health can be broken in the reporting path
    and still claim to be fine. The envelope log is durable, per-agent, and
    already what every other part of this system treats as the record."""
    import inspect

    src = inspect.getsource(RunnerProcessSupervisor._completions_since)
    assert "count_agent_envelopes_since" in src
