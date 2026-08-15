"""The review path — the missing referent for `H`.

`H`, human review capacity, appears in every equation in the planetary program
and had no mechanism, no measurement and no referent. The figure used throughout
the derivations was an illustration that became load-bearing.

THE PROPERTY THAT MATTERS IS NOT "IT ESCALATES". It is that a RESUME cannot
happen invisibly: advancing the accounting origin is ledger artifact #13, and a
counter that could be silently reset would let a bound be defeated by reaching
it repeatedly. Most of this file is about that.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_review_path.py -q
"""
from __future__ import annotations

import pytest

from gyza.containment.gyza_model import build_registries
from gyza.containment.review import (
    HALT, RESUME, ReviewQueue, check_cadence,
)


def _q(tmp_path, name="r.db") -> ReviewQueue:
    return ReviewQueue(str(tmp_path / name))


# --------------------------------------------------------------------------- #
#  1. A RESUME CANNOT BE ANONYMOUS OR UNEXPLAINED                              #
# --------------------------------------------------------------------------- #
def test_a_RESUME_requires_a_named_reviewer_and_a_reason(tmp_path):
    q = _q(tmp_path)
    e = q.escalate("H6_unsupervised_actions", 10_000, 10_000, "cadence")
    for reviewer, note in (("", "ok"), ("alice", ""), ("  ", "  ")):
        with pytest.raises(ValueError, match="accountable"):
            q.resolve(e.record_id, reviewer, RESUME, note)
    assert q.resume_count() == 0, "a refused resume must not be recorded as one"


def test_a_HALT_needs_neither(tmp_path):
    """Counter-control. If both decisions required justification the check
    would be about paperwork; it is specifically about ORIGIN ADVANCES."""
    q = _q(tmp_path)
    e = q.escalate("H6_unsupervised_actions", 10_000, 10_000, "cadence")
    r = q.resolve(e.record_id, "", HALT, "")
    assert r.decision == HALT
    assert q.resume_count() == 0 and q.pending() == []


def test_every_RESUME_is_COUNTED_so_repeated_waving_through_is_visible(tmp_path):
    """The bound may be waved through a thousand times. What it may not be is
    waved through INVISIBLY."""
    q = _q(tmp_path)
    for i in range(5):
        e = q.escalate("H6_unsupervised_actions", 10_000 * (i + 1), 10_000, "c")
        q.resolve(e.record_id, "alice", RESUME, f"pass {i}")
    assert q.resume_count() == 5
    assert q.summary()["resumes"] == 5


# --------------------------------------------------------------------------- #
#  2. DURABLE AND TAMPER-EVIDENT                                               #
# --------------------------------------------------------------------------- #
def test_the_queue_SURVIVES_A_RESTART(tmp_path):
    """`AppendOnlyLog` is hash-chained and in-memory, so a restart empties it.
    For a review history that is the same defect one layer up."""
    q = _q(tmp_path)
    e = q.escalate("H6_unsupervised_actions", 10_000, 10_000, "cadence")
    q.resolve(e.record_id, "alice", RESUME, "checked")

    fresh = _q(tmp_path)                      # same file, new object
    assert fresh.resume_count() == 1
    assert fresh.summary()["escalations"] == 1


def test_the_chain_DETECTS_a_removed_record(tmp_path):
    """Negative control for the hash chain. Without this, 'chain: intact' would
    be a word rather than a check."""
    q = _q(tmp_path)
    for i in range(3):
        q.escalate("H6_unsupervised_actions", 10_000, 10_000, f"c{i}")
    assert q.verify_chain()[0] is True

    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "r.db"))
    conn.execute("DELETE FROM review_log WHERE seq = 2")
    conn.commit(); conn.close()

    ok, why = _q(tmp_path).verify_chain()
    # Detection fires on the RECOMPUTED HASH of the record after the gap, not on
    # the prev_hash comparison: removing a record makes its successor's hash
    # wrong first. Either is a detection; asserting which one would pin an
    # implementation detail rather than the property.
    assert ok is False, "a deleted record passed the chain check"
    assert "record" in why, why


def test_the_chain_DETECTS_an_edited_record(tmp_path):
    q = _q(tmp_path)
    e = q.escalate("H6_unsupervised_actions", 10_000, 10_000, "cadence")
    q.resolve(e.record_id, "alice", RESUME, "checked")

    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "r.db"))
    conn.execute("UPDATE review_log SET payload = ? WHERE kind = 'REVIEW'",
                 ('{"reviewer":"bob","decision":"RESUME","note":"x",'
                  '"new_origin":{}}',))
    conn.commit(); conn.close()

    ok, _why = _q(tmp_path).verify_chain()
    assert ok is False, "an edited review passed the chain check"


# --------------------------------------------------------------------------- #
#  3. THE CADENCE CHECK                                                        #
# --------------------------------------------------------------------------- #
def test_the_cadence_fires_AT_the_bound_and_does_not_flood(tmp_path):
    """A check firing once per call would make `oldest_pending` meaningless and
    hand a reviewer ten thousand identical rows, which they would review none
    of."""
    q = _q(tmp_path)
    harm, _inv = build_registries()

    assert check_cadence(q, harm, 9_999) is None
    assert check_cadence(q, harm, 10_000) is not None
    for n in (10_001, 12_000, 99_999):
        assert check_cadence(q, harm, n) is None, f"flooded at {n}"
    assert len(q.pending()) == 1


def test_the_cadence_can_fire_AGAIN_once_the_first_is_resolved(tmp_path):
    """Idempotence must not become permanent silence."""
    q = _q(tmp_path)
    harm, _inv = build_registries()
    e = check_cadence(q, harm, 10_000)
    q.resolve(e.record_id, "alice", RESUME, "checked")
    assert check_cadence(q, harm, 20_000) is not None, \
        "the cadence went permanently quiet after one review"


def test_an_UNBOUNDED_class_does_not_escalate(tmp_path):
    """An undeclared bound is a separate condition, already reported by
    readiness(). Escalating on it would hide one behind the other."""
    q = _q(tmp_path)
    harm, _inv = build_registries()
    assert check_cadence(q, harm, 10 ** 9, harm_class="H3_irreversible") is None
    assert q.pending() == []


# --------------------------------------------------------------------------- #
#  4. THE CLI IS THE CONSUMER                                                  #
#     A queue nobody can act on is the same defect as a bound nobody reads.     #
# --------------------------------------------------------------------------- #
def test_gyza_review_LISTS_and_RESOLVES(tmp_path, monkeypatch, capsys):
    import argparse

    import gyza.cli as cli
    from gyza.config import GyzaConfig

    cfg = GyzaConfig(review_db_path=str(tmp_path / "r.db"),
                     blackboard_db_path=str(tmp_path / "bb.db"))
    monkeypatch.setattr(cli, "load_config", lambda *a, **k: cfg)

    q = ReviewQueue(cfg.review_db_path)
    harm, _inv = build_registries()
    check_cadence(q, harm, 10_000)

    assert cli.cmd_review(argparse.Namespace(
        escalation_id=None, reviewer=None, note=None, halt=False)) == 0
    out = capsys.readouterr().out
    assert "pending: 1" in out and "H6_unsupervised_actions" in out
    assert "chain: intact" in out

    eid = q.pending()[0].record_id
    # an anonymous resume must be refused BY THE CLI, not only by the store
    assert cli.cmd_review(argparse.Namespace(
        escalation_id=eid, reviewer=None, note=None, halt=False)) == 1

    assert cli.cmd_review(argparse.Namespace(
        escalation_id=eid, reviewer="alice", note="sampled 20", halt=False)) == 0
    assert ReviewQueue(cfg.review_db_path).resume_count() == 1
