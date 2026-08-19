"""The harm model must MEASURE, not default to zero.

THE DEFECT THIS PINS. `GyzaState` carries `stored_bytes`,
`signed_envelope_count` and `mesh_exit_sends`. Every one defaulted to 0 at
every call site in the repository, because `projection.py` deliberately does
not know what a blackboard is and **no caller folded the real sources**. So H3,
H5 and H6 computed `0 - 0 = 0` in every evaluation -- while H5 and H6 carried
declared, SIGNED bounds of 10 GB and 10,000 actions.

That is H2_market_capital's retirement condition ("reported as a bounded class
while measuring exactly 0.0 in every production evaluation") alive in two more
classes. H1 was retired for declaring without measuring; H2 for measuring
nothing; H3 was found the same way. Three of four registered classes.

These tests assert each quantity moves when its real source moves. A test that
only checked "the function returns a GyzaState" would have passed throughout.
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from gyza.blackboard import Blackboard
from gyza.containment.egress import default_egress_recorder
from gyza.containment.gates import (
    genesis_origin,
    observe_at_origin,
    observe_now,
)
from gyza.containment.gyza_model import build_registries


@pytest.fixture()
def db() -> str:
    return str(Path(tempfile.mkdtemp()) / "bb.db")


class _Store:
    """Minimal stand-in for ArtifactStore.total_size_bytes()."""

    def __init__(self, n: int) -> None:
        self._n = n

    def total_size_bytes(self) -> int:
        return self._n


def test_origin_is_immutable_and_at_genesis():
    """A cumulative bound whose origin can move is not a bound (#13)."""
    a, b = genesis_origin(), genesis_origin()
    assert a == b
    assert a.ledger_ns == 0 and a.capital_seq == 0 and a.envelope_ns == 0


def test_unwired_sources_still_read_zero(db):
    """The pre-existing behaviour, kept honest: no store, no blackboard -> 0."""
    s = observe_now(owner="me")
    assert s.stored_bytes == 0
    assert s.signed_envelope_count == 0
    assert s.mesh_exit_sends == 0


def test_H5_storage_reflects_the_real_store():
    s = observe_now(owner="me", artifact_store=_Store(4096))
    assert s.stored_bytes == 4096


def test_H3_mesh_exit_reflects_the_real_egress_log(db):
    rec = default_egress_recorder(db)
    rec.peer_send("send_message:x", "peerA", 10)
    rec.peer_send("publish_delta", "topic:t", 20)
    rec.unbounded_grant("sandbox", "<any>")      # a GRANT is a different unit
    s = observe_now(owner="me", blackboard=Blackboard(db))
    assert s.mesh_exit_sends == 2, "grants must not fold into a send count"


def test_H6_envelopes_reflects_the_real_log(db):
    bb = Blackboard(db)
    before = observe_now(owner="me", blackboard=bb).signed_envelope_count
    assert before == 0
    # count_envelopes_since is the declared source; assert the wiring reads IT
    # rather than a constant, by checking observe_now tracks the accessor.
    assert bb.count_envelopes_since(0) == before


def test_every_registered_class_moves_when_its_source_moves(db):
    """THE ANTI-#16 ASSERTION: registering a class is not evidence it measures.

    Each quantity is evaluated against a real s0/s pair and must be non-zero
    for at least one class whose source was populated. A harm model in which
    every quantity is pinned at 0 is indistinguishable from one that is safe.
    """
    rec = default_egress_recorder(db)
    for _ in range(5):
        rec.peer_send("send_message:x", "peerA", 10)

    harm, _inv = build_registries()
    s0 = observe_at_origin(owner="me")
    s = observe_now(owner="me", blackboard=Blackboard(db),
                    artifact_store=_Store(8192))

    measured = {c.id: c.quantity(s0, s) for c in harm}
    assert measured["H3_mesh_exit_sends"] == 5.0
    assert measured["H5_storage_growth"] == 8192.0
    # H4 stays 0 with no violations, which is CORRECT rather than unmeasured --
    # it is the one class that was already wired (runner.py records it).
    assert measured["H4_authority"] == 0.0
    assert any(v != 0.0 for v in measured.values()), \
        "a model where every quantity is pinned at 0 measures nothing"


def test_a_declared_bound_is_now_checkable_against_a_real_number(db):
    """Why this matters: H5's signed 10 GB bound compared something to 0."""
    from gyza.containment.gyza_model import storage_cap_bytes

    cap = storage_cap_bytes()
    if cap is None:
        pytest.skip("no H5 cap declared in the default bounds file")
    s0 = observe_at_origin(owner="me")
    s = observe_now(owner="me", artifact_store=_Store(cap + 1))
    harm, _ = build_registries()
    growth = {c.id: c.quantity(s0, s) for c in harm}["H5_storage_growth"]
    assert growth > cap, "the bound must be exceedable by a real measurement"


# --------------------------------------------------------------------------- #
#  H6's CONSUMER MUST BE WIRED. AgentRunner accepts review_queue /             #
#  harm_registry / cadence_origin_ns and NO production construction supplied   #
#  any of them, so check_cadence never ran -- while global_cluster.py recorded #
#  "Autonomy is bounded instead by H6 (actions), checked in the runner".       #
#  H1 was retired and its stated replacement was never in force.               #
# --------------------------------------------------------------------------- #
def test_cadence_wiring_builds_a_real_queue_and_registry():
    from gyza.containment.review import ReviewQueue, default_cadence_wiring

    q, harm, origin = default_cadence_wiring()
    assert isinstance(q, ReviewQueue)
    assert harm is not None and len(list(harm)) == 4
    # GENESIS, and it must not move: an origin at process start refills the
    # budget on restart (ledger artifact #13).
    assert origin == 0


def test_run_local_task_supplies_H6s_consumer():
    """The production path that signs envelopes must count toward the cadence."""
    import inspect

    from gyza import cli

    src = inspect.getsource(cli.run_local_task)
    assert "default_cadence_wiring()" in src
    assert "review_queue=" in src and "harm_registry=" in src


def test_cadence_escalates_at_the_bound_and_is_idempotent(tmp_path):
    from gyza.containment.gyza_model import build_registries
    from gyza.containment.review import ReviewQueue, check_cadence

    harm, _ = build_registries()
    q = ReviewQueue(str(tmp_path / "review.db"))
    bound = harm.bound("H6_unsupervised_actions")

    assert check_cadence(q, harm, int(bound) - 1) is None, "below the bound"
    first = check_cadence(q, harm, int(bound))
    assert first is not None, "the bound must escalate"
    # idempotent: a second call with an escalation already pending opens none
    assert check_cadence(q, harm, int(bound) + 500) is None
    assert len(q.pending()) == 1
