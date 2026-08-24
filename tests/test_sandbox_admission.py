"""Concurrent sandbox runs are bounded.

A sandboxed action is a bubblewrap PROCESS — namespace setup, seccomp filter,
then ~305 ms of work; one core sustains ~3.3 of them. Nothing limited how many
could be in flight, which was survivable only while agents were separate OS
processes. The moment agents become THREADS, 500 of them reach the sandbox
together and ask a 4-core box for 500 simultaneous namespace setups.
"""
from __future__ import annotations

import os
import threading
import time

import pytest

from gyza.sandbox import executor as ex


def _fresh(limit):
    a = ex._Admission.__new__(ex._Admission)
    a._limit = limit
    a._sem = threading.BoundedSemaphore(limit)
    a._lock = threading.Lock()
    a.admitted = 0
    a.wait_s = 0.0
    a.peak_waiting = 0
    a._waiting = 0
    return a


def _hammer(adm, n_threads, hold=0.02):
    """Run n_threads through the gate, tracking true peak concurrency."""
    live = {"now": 0, "peak": 0}
    lk = threading.Lock()

    def worker():
        with adm:
            with lk:
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
            time.sleep(hold)
            with lk:
                live["now"] -= 1

    ts = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in ts: t.start()
    for t in ts: t.join()
    return live["peak"]


def test_concurrency_never_exceeds_the_limit():
    """THE PROPERTY. 200 threads, limit 8 — peak in-flight must be <= 8."""
    adm = _fresh(8)
    assert _hammer(adm, 200) <= 8


def test_it_holds_at_500_threads():
    """The case this exists for: a 500-agent threaded roster."""
    adm = _fresh(8)
    peak = _hammer(adm, 500, hold=0.002)
    assert peak <= 8, f"peak concurrency {peak} exceeded the limit of 8"
    assert adm.stats()["admitted"] == 500, "some threads never ran"


def test_every_thread_is_eventually_admitted():
    """Backpressure, not rejection. A full queue must delay work, never drop
    it — the alternative converts a slow system into a failing one, and the
    caller's only sensible response would be to retry into the same wait."""
    adm = _fresh(2)
    _hammer(adm, 60, hold=0.005)
    assert adm.stats()["admitted"] == 60


def test_the_gate_records_WHERE_THE_TIME_WENT():
    """Without this, "the sandbox is slow" and "we are queued behind other
    agents" are indistinguishable in a throughput number — and those have
    opposite remedies, more cores versus fewer agents."""
    adm = _fresh(2)
    _hammer(adm, 20, hold=0.01)
    st = adm.stats()
    assert st["total_wait_s"] > 0, "queueing happened but was not recorded"
    assert st["peak_waiting"] > 0


def test_an_UNCONTENDED_run_waits_essentially_nothing():
    """Negative control: the gate must not tax the common case."""
    adm = _fresh(8)
    _hammer(adm, 4, hold=0.001)
    assert adm.stats()["total_wait_s"] < 0.05


def test_a_raising_body_still_releases_its_slot():
    """A sandbox that raises must not leak a permit, or the roster deadlocks
    after `limit` failures."""
    adm = _fresh(2)
    for _ in range(10):
        with pytest.raises(ValueError):
            with adm:
                raise ValueError("boom")
    assert _hammer(adm, 8, hold=0.001) <= 2


# --------------------------------------------------------------------------- #
#  Configuration                                                                #
# --------------------------------------------------------------------------- #
def test_the_default_is_twice_the_core_count(monkeypatch):
    monkeypatch.delenv("GYZA_SANDBOX_CONCURRENCY", raising=False)
    assert ex._default_concurrency() == max(2, (os.cpu_count() or 2) * 2)


def test_the_env_override_is_honoured(monkeypatch):
    """So the concurrency/throughput curve can be MEASURED rather than argued."""
    monkeypatch.setenv("GYZA_SANDBOX_CONCURRENCY", "3")
    assert ex._default_concurrency() == 3


def test_a_junk_override_falls_back_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("GYZA_SANDBOX_CONCURRENCY", "not-a-number")
    assert ex._default_concurrency() >= 2


def test_the_sandboxed_executor_ACTUALLY_uses_the_gate():
    """Asserted by source: a limiter nothing calls is the species this project
    keeps rediscovering."""
    import inspect
    src = inspect.getsource(ex.make_sandboxed_executor)
    assert "with ADMISSION:" in src
