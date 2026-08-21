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
