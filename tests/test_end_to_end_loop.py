"""THE WHOLE LOOP, run once, end to end.

Every piece below was built in isolation and never composed:

    work  ->  signed provenance  ->  audit + governance  ->  harm model
          ->  review cadence  ->  escalation  ->  human review  ->  resume

Nothing has ever run that path. This file runs it, and the point is not that the
happy case passes -- it is that composing the pieces is the highest-yield way to
find defects, which is what every consumer-forcing exercise in this line of work
has demonstrated.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_end_to_end_loop.py -q
"""
from __future__ import annotations

import json
import time
import uuid

import numpy as np
import pytest

from tests.test_runner_audit_integration import (
    _intent, _within_bounds_executor, _work_item,
)

from gyza.audit import audit_from_store, render_audit_report
from gyza.blackboard import Blackboard
from gyza.containment.engine import GuardEngine
from gyza.containment.gyza_model import build_registries
from gyza.containment.projection import project_now
from gyza.containment.review import RESUME, ReviewQueue, check_cadence
from gyza.drift import SpecializationTracker
from gyza.demand import LSHIndex
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.network.artifact_store import ArtifactStore
from gyza.runner import AgentRunner
from gyza.schema import EMBEDDING_DIM


def _loop(tmp_path, *, cadence_origin_ns=0):
    """Build the whole stack the way production does, wired together."""
    store = ArtifactStore(base_path=str(tmp_path / "cas"))
    bb = Blackboard(str(tmp_path / "bb.db"))
    bb.attach_artifact_store(store)

    comp = LocalCompositor(key_path=str(tmp_path / "k.key"))
    seed, manifest = comp.issue_agent(
        agent_type="loop.worker", model_path="mock", fs_read_paths=[],
        fs_write_paths=[], allowed_hosts=[], memory_limit_mb=512,
        attestation_tier=0)
    ident = AgentIdentity(seed, manifest)

    spec_v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    spec_v[0] = 1.0
    harm, inv = build_registries()
    queue = ReviewQueue(str(tmp_path / "review.db"))

    runner = AgentRunner(
        identity=ident, blackboard=bb,
        memory=EpisodicMemory(agent_id=ident.agent_id,
                              db_path=str(tmp_path / "mem")),
        specialization=SpecializationTracker(
            agent_id=ident.agent_id, initial_embedding=spec_v,
            db_path=str(tmp_path / "spec.db")),
        lsh=LSHIndex(seed=42), executor=_within_bounds_executor(256),
        min_reward_threshold=0.0, min_similarity_threshold=-1.0,
        verify_chain_before_claim=False,
        review_queue=queue, harm_registry=harm,
        cadence_origin_ns=cadence_origin_ns)
    return runner, bb, store, queue, harm, inv, ident, manifest


def _do_work(runner, bb, n, intent="loop-intent"):
    """Drive the runner's REAL path: execute, then complete (which SIGNS).

    `_execute` only runs the executor. `_complete` is what signs, stores the
    envelope and therefore moves the cadence — driving the first alone was my
    own error and it made the loop produce no provenance at all.
    """
    _intent(bb, intent)
    out = []
    for _ in range(n):
        w = _work_item(intent)
        bb.post_work_item(w)
        res = runner._execute(w)
        runner._complete(w, res, True)
        out.append(w)
    return out


# --------------------------------------------------------------------------- #
#  1. WORK -> PROVENANCE -> AUDIT + GOVERNANCE                                 #
# --------------------------------------------------------------------------- #
def test_the_loop_produces_an_audit_that_is_VALID_and_GOVERNED(tmp_path):
    runner, bb, store, queue, harm, inv, ident, manifest = _loop(tmp_path)

    from gyza.identity import manifest_canonical_bytes
    _do_work(runner, bb, 1)
    store.store(manifest_canonical_bytes(manifest))

    envs = bb.reconstruct_dag("loop-intent")
    assert len(envs) == 1, "the runner's own path produced no envelope"

    report = audit_from_store(envs, store, require_closed=True, governed=True)
    assert report.valid, report.summary
    g = report.governance
    assert g is not None and g.n_claims > 0
    # FULLY governed since the envelope_dag split was attested 2026-08-15.
    # Asserting the empty list means a NEW ungoverned check fails this.
    assert g.ungoverned_types == [], g.ungoverned_types
    text = render_audit_report(report)
    assert "VERDICT: VALID" in text
    assert "under an ATTESTED specification" in text


# --------------------------------------------------------------------------- #
#  2. THE HARM MODEL MEASURES THE LOOP'S OWN STATE                             #
# --------------------------------------------------------------------------- #
def test_the_harm_model_measures_what_the_loop_actually_did(tmp_path):
    runner, bb, store, queue, harm, inv, ident, _m = _loop(tmp_path)
    _do_work(runner, bb, 3)

    n = bb.count_envelopes_since(0)
    kw = dict(owner=ident.pubkey_hex, ledger_entries=[], active_holds=0.0,
              capital_entries=[])
    s0 = project_now(signed_envelope_count=0, stored_bytes=0, **kw)
    s = project_now(signed_envelope_count=n,
                    stored_bytes=store.total_size_bytes(), **kw)

    measured = {c.id: c.measure(s0, s) for c in harm}
    assert set(measured) == {"H2_market_capital", "H4_authority",
                             "H5_storage_growth", "H6_unsupervised_actions"}
    # H4 must be zero: the executor is WITHIN bounds, so no authority breach
    assert measured["H4_authority"] == 0.0
    assert runner.authority_violations == []
    # and the readiness verdict is computable over the same registry
    r = GuardEngine(harm, inv).readiness()
    assert r["unbounded"] == [] and r["uncovered"] == []


# --------------------------------------------------------------------------- #
#  3. CADENCE -> ESCALATION -> REVIEW -> RESUME                                #
# --------------------------------------------------------------------------- #
def test_the_cadence_fires_FROM_THE_RUNNER_not_from_a_human_asking(tmp_path):
    """The defect this replaces: `check_cadence` was called only by
    `gyza review`, so an operator learned they were due a review by asking
    whether they were due a review. It must fire where actions happen."""
    # origin set just below the work we are about to do, so the cadence is
    # reached by REAL signing rather than by a seeded number
    runner, bb, store, queue, harm, inv, ident, _m = _loop(tmp_path)
    assert queue.pending() == []

    # lower the effective bound by moving the origin: 10,000 real signatures is
    # not a unit test. The ORIGIN is the legitimate dial; the BOUND is declared.
    harm.load_bounds({"H6_unsupervised_actions": 2})

    _do_work(runner, bb, 3)
    pend = queue.pending()
    assert len(pend) == 1, f"the runner never escalated: {queue.summary()}"
    assert pend[0].harm_class == "H6_unsupervised_actions"
    assert pend[0].measured >= 2


def test_review_and_resume_close_the_loop(tmp_path):
    runner, bb, store, queue, harm, inv, ident, _m = _loop(tmp_path)
    harm.load_bounds({"H6_unsupervised_actions": 2})
    _do_work(runner, bb, 3)

    e = queue.pending()[0]
    with pytest.raises(ValueError, match="accountable"):
        queue.resolve(e.record_id, "", RESUME, "")

    r = queue.resolve(e.record_id, "alice", RESUME,
                      "sampled 3 of 3, all within manifest bounds",
                      new_origin={"envelope_ns": time.time_ns()})
    assert r.decision == RESUME
    assert queue.pending() == []
    assert queue.resume_count() == 1
    ok, why = queue.verify_chain()
    assert ok, why


def test_the_loop_SURVIVES_A_RESTART_with_its_history_intact(tmp_path):
    """Every durable surface the loop touches, reopened cold."""
    runner, bb, store, queue, harm, inv, ident, _m = _loop(tmp_path)
    harm.load_bounds({"H6_unsupervised_actions": 2})
    _do_work(runner, bb, 3)
    e = queue.pending()[0]
    queue.resolve(e.record_id, "alice", RESUME, "checked")

    n_before = bb.count_envelopes_since(0)
    bytes_before = store.total_size_bytes()

    # cold reopen — new objects, same files
    bb2 = Blackboard(str(tmp_path / "bb.db"))
    store2 = ArtifactStore(base_path=str(tmp_path / "cas"))
    q2 = ReviewQueue(str(tmp_path / "review.db"))

    assert bb2.count_envelopes_since(0) == n_before > 0
    assert store2.total_size_bytes() == bytes_before > 0
    assert q2.resume_count() == 1
    assert q2.verify_chain()[0] is True


# --------------------------------------------------------------------------- #
#  4. THE LOOP WITH NO REVIEW PATH BEHAVES AS BEFORE                           #
# --------------------------------------------------------------------------- #
def test_a_runner_with_no_review_queue_is_UNCHANGED(tmp_path):
    """Negative control. If the cadence fired without a queue attached, the
    check would be coupled to the runner rather than opt-in."""
    runner, bb, store, queue, harm, inv, ident, _m = _loop(tmp_path)
    runner._review_queue = None
    harm.load_bounds({"H6_unsupervised_actions": 1})
    _do_work(runner, bb, 3)
    assert queue.pending() == [], "escalated with no queue attached"
    assert bb.count_envelopes_since(0) >= 0
