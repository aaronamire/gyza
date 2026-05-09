"""
Phase 3 Session 8.5 — HLC ratchet correctness.

Two distinct fixes covered here:

  1. **Thread safety.** The pre-Session-8.5 HLC mutated ``self.l``
     and ``self.c`` without a lock. Two concurrent ``now()`` calls
     could produce tuples with the same ``(l, c)`` — violating the
     uniqueness invariant the HLC is supposed to guarantee.

  2. **Cross-cluster ratchet sharing.** The runner used to hold a
     private per-agent HLC. Cross-cluster claim merges advanced
     ``NetworkBlackboard._gossip_hlc`` instead. The two clocks
     diverged. A local claim issued strictly after a merged remote
     claim could produce a tuple lex-smaller than the remote and
     break LWW total order.

These tests aren't in test_blackboard.py because they cross multiple
modules (HLC + Blackboard + AgentRunner + NetworkBlackboard) — they
exercise the *integration* invariant, not any single module's API.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.schema import HLC


# ----------------------------------------------------------------------
# 1. HLC thread safety
# ----------------------------------------------------------------------

def test_hlc_now_unique_under_concurrent_calls():
    """
    N threads each call ``now()`` M times against ONE shared HLC.
    The total set of (l, c, node_id) tuples must equal N*M — every
    event must be uniquely timestamped.

    Pre-fix this test failed with duplicate tuples: two threads
    reading the same ``l_old``, both writing the same ``self.l``,
    both writing ``c = c_old + 1`` produced the same tuple.
    """
    h = HLC(node_id="t")
    N_THREADS = 16
    M_PER_THREAD = 200
    results: list[tuple] = []
    results_lock = threading.Lock()

    def worker():
        local: list[tuple] = []
        for _ in range(M_PER_THREAD):
            local.append(h.now())
        with results_lock:
            results.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == N_THREADS * M_PER_THREAD
    assert len(set(results)) == len(results), (
        f"HLC produced duplicates under concurrency: "
        f"{len(results) - len(set(results))} collisions"
    )


def test_hlc_recv_concurrent_with_now():
    """
    One thread calls ``now()`` repeatedly; another simulates remote
    deltas via ``recv()``. Both must complete without crashing and
    every produced ``now()`` tuple must be lex-greater than the
    one before it.
    """
    h = HLC(node_id="x")
    nows: list[tuple] = []
    stop = threading.Event()

    def now_thread():
        while not stop.is_set():
            nows.append(h.now())

    def recv_thread():
        for i in range(500):
            h.recv(l=10_000_000_000 + i, c=0, node="peer")
            time.sleep(0.0005)

    t1 = threading.Thread(target=now_thread)
    t2 = threading.Thread(target=recv_thread)
    t1.start()
    t2.start()
    t2.join()
    stop.set()
    t1.join()

    # nows must be strictly increasing in lex order.
    for i in range(1, len(nows)):
        assert nows[i] > nows[i - 1], (
            f"nows[{i}]={nows[i]} not > nows[{i-1}]={nows[i-1]}"
        )


def test_hlc_equality_excludes_lock():
    """The lock must be hidden from dataclass equality so two HLCs
    with the same (node_id, l, c) compare equal regardless of which
    Lock instance they hold."""
    a = HLC(node_id="n", l=10, c=2)
    b = HLC(node_id="n", l=10, c=2)
    assert a == b
    assert a._lock is not b._lock  # different lock instances


def test_hlc_snapshot_does_not_advance():
    """snapshot() returns the current state without bumping the
    counter. Two snapshots in a row are identical."""
    h = HLC(node_id="x", l=5, c=3)
    s1 = h.snapshot()
    s2 = h.snapshot()
    assert s1 == s2 == (5, 3, "x")
    # And a now() AFTER snapshot DOES advance.
    n = h.now()
    assert n > s1


# ----------------------------------------------------------------------
# 2. Cross-cluster ratchet — bb.gossip_hlc() observed by local now()
# ----------------------------------------------------------------------

def test_gossip_hlc_advances_on_remote_recv(tmp_path):
    """
    After the gossip recv path absorbs a remote claim with HLC
    (L, c, peer), the same HLC instance's next ``now()`` call must
    produce a tuple lex-greater than (L, c, peer).
    """
    bb = NetworkBlackboard(str(tmp_path / "bb.db"))
    # Manually attach a gossip HLC without standing up the gossip
    # client — we only need the HLC instance for this test.
    bb._gossip_hlc = HLC(node_id="my-pubkey")
    h = bb.gossip_hlc()
    assert h is not None

    # Simulate a remote claim arriving with a large logical time.
    remote = (10_000_000_000, 0, "peer-pubkey")
    h.recv(*remote)

    # Local event — must be lex-greater than the remote.
    local = h.now()
    assert local > remote, (
        f"local {local} did not advance past remote {remote}"
    )


def test_gossip_hlc_shared_across_repeated_recv(tmp_path):
    """A sequence of remote events and local events interleaved must
    produce a strictly increasing local sequence."""
    bb = NetworkBlackboard(str(tmp_path / "bb.db"))
    bb._gossip_hlc = HLC(node_id="self")
    h = bb.gossip_hlc()

    nows: list[tuple] = []
    for i in range(20):
        h.recv(l=1_700_000_000_000 + i * 100, c=0, node="peer")
        nows.append(h.now())

    for i in range(1, len(nows)):
        assert nows[i] > nows[i - 1]


# ----------------------------------------------------------------------
# 3. Runner integration — shared HLC vs private HLC
# ----------------------------------------------------------------------

def test_runner_uses_shared_hlc_when_provided(tmp_path):
    """
    Construct an AgentRunner with hlc=shared. The runner's _hlc
    attribute IS the shared instance — same object identity, not a
    copy.
    """
    from gyza.demand import LSHIndex
    from gyza.drift import SpecializationTracker
    from gyza.identity import LocalCompositor, AgentIdentity
    from gyza.memory import EpisodicMemory
    from gyza.runner import AgentRunner, make_mock_executor
    from gyza.schema import EMBEDDING_DIM
    import secrets

    key_path = tmp_path / "k.key"
    key_path.write_bytes(secrets.token_bytes(32))
    key_path.chmod(0o600)
    comp = LocalCompositor(str(key_path))
    seed, manifest = comp.issue_agent(
        agent_type="t", model_path="mock",
        fs_read_paths=["/tmp"], fs_write_paths=["/tmp"],
        attestation_tier=0,
    )
    ident = AgentIdentity(seed, manifest)
    bb = Blackboard(str(tmp_path / "bb.db"))
    mem = EpisodicMemory(agent_id=ident.agent_id, db_path=str(tmp_path / "mem"))
    spec = SpecializationTracker(
        agent_id=ident.agent_id,
        initial_embedding=np.eye(EMBEDDING_DIM, dtype=np.float32)[0],
        db_path=str(tmp_path / "s.db"),
    )

    shared = HLC(node_id="my-compositor-pubkey")
    runner = AgentRunner(
        identity=ident, blackboard=bb, memory=mem, specialization=spec,
        lsh=LSHIndex(seed=42),
        executor=make_mock_executor("ok"),
        hlc=shared,
    )
    assert runner._hlc is shared, (
        "AgentRunner did not adopt the shared HLC instance"
    )


def test_runner_default_hlc_when_none(tmp_path):
    """No hlc= passed → runner constructs its own keyed on agent_id."""
    from gyza.demand import LSHIndex
    from gyza.drift import SpecializationTracker
    from gyza.identity import LocalCompositor, AgentIdentity
    from gyza.memory import EpisodicMemory
    from gyza.runner import AgentRunner, make_mock_executor
    from gyza.schema import EMBEDDING_DIM
    import secrets

    key_path = tmp_path / "k.key"
    key_path.write_bytes(secrets.token_bytes(32))
    key_path.chmod(0o600)
    comp = LocalCompositor(str(key_path))
    seed, manifest = comp.issue_agent(
        agent_type="t", model_path="mock",
        fs_read_paths=["/tmp"], fs_write_paths=["/tmp"],
        attestation_tier=0,
    )
    ident = AgentIdentity(seed, manifest)
    bb = Blackboard(str(tmp_path / "bb.db"))
    mem = EpisodicMemory(agent_id=ident.agent_id, db_path=str(tmp_path / "mem"))
    spec = SpecializationTracker(
        agent_id=ident.agent_id,
        initial_embedding=np.eye(EMBEDDING_DIM, dtype=np.float32)[0],
        db_path=str(tmp_path / "s.db"),
    )

    runner = AgentRunner(
        identity=ident, blackboard=bb, memory=mem, specialization=spec,
        lsh=LSHIndex(seed=42),
        executor=make_mock_executor("ok"),
    )
    assert runner._hlc.node_id == ident.agent_id


# ----------------------------------------------------------------------
# 4. The actual integration invariant — local claim post-merge has
#    HLC strictly greater than the merged remote claim
# ----------------------------------------------------------------------

def test_local_claim_after_remote_merge_has_greater_hlc(tmp_path):
    """
    The whole point of the ratchet fix.

    Setup: a NetworkBlackboard with a manually-installed gossip HLC.
    A "remote claim" arrives via the HLC's recv(). Then a local agent
    issues a claim using the SAME HLC. The local claim's tuple must be
    lex-greater than the remote — otherwise total-order is broken.

    Pre-Session-8.5 the runner held a private HLC unaffected by recv,
    so its claim could produce a smaller tuple.
    """
    bb = NetworkBlackboard(str(tmp_path / "bb.db"))
    bb._gossip_hlc = HLC(node_id="self-pubkey")
    shared = bb.gossip_hlc()

    # Simulate "remote claim observed via gossip" — this is what
    # NetworkBlackboard._apply_delta does when ``merge_claim_direct``
    # actually changes anything.
    remote_hlc = (1_700_000_000_500, 0, "peer-pubkey")
    shared.recv(*remote_hlc)

    # Now a local event uses the SAME clock.
    local_hlc = shared.now()

    # Lex comparison.
    assert local_hlc > remote_hlc, (
        f"local {local_hlc} should be lex-greater than remote {remote_hlc} "
        f"after sharing the HLC; ratchet appears broken"
    )


_ = pytest  # unused-import suppressor
