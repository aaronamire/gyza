"""The review path — what happens when a declared bound is reached.

WHY THIS EXISTS. `H`, human review capacity, appears in every equation in the
planetary program: the scale bound `N <= H*A/eps`, the review cadence, what
happens at a harm bound, the thing amortization amortizes. **It had no
mechanism, no measurement and no referent.** The figure used throughout the
derivations -- ten reviews per principal per day -- was an illustration that
became load-bearing.

So this is not plumbing. It is the missing object, and building it is what makes
four things already shipped actually do something: the settlement gate's records
of what it would have refused, the cadence counter, the harm bounds, and the
escalation term in the scale equation.

THE DANGEROUS PART IS RESUME, NOT ESCALATE. Advancing the accounting origin is
exactly ledger artifact #13 -- a gate that measured from a moving checkpoint
bought unlimited drain. If "resume" silently reset a counter, then reaching the
bound and resuming repeatedly would buy unlimited actions and nothing would
show. So every resume is an APPEND-ONLY, HASH-CHAINED RECORD carrying the origin
it advanced to. The bound can still be raised by a human a thousand times; what
it cannot be is raised *invisibly*.

DURABLE, because `AppendOnlyLog` is not. That class is hash-chained and correct
and lives entirely in `self._events`, so a restart empties it -- which for a
review history is the same defect one layer up.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import blake3

GENESIS = "00" * 32

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_log (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,      -- ESCALATION | REVIEW
    payload     TEXT NOT NULL,
    at_ns       INTEGER NOT NULL,
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_kind ON review_log(kind);
CREATE INDEX IF NOT EXISTS idx_review_rec  ON review_log(record_id);
"""

RESUME = "RESUME"
HALT = "HALT"


def _hash(seq: int, kind: str, payload: dict, at_ns: int, prev: str) -> str:
    body = json.dumps({"seq": seq, "kind": kind, "payload": payload,
                       "at_ns": at_ns, "prev": prev},
                      sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return blake3.blake3(body).hexdigest()


@dataclass(frozen=True)
class Escalation:
    record_id: str
    harm_class: str
    measured: float
    bound: float
    reason: str
    at_ns: int


@dataclass(frozen=True)
class Review:
    record_id: str          # the escalation this resolves
    reviewer: str
    decision: str           # RESUME | HALT
    note: str
    new_origin: dict
    at_ns: int


class ReviewQueue:
    """Durable, append-only, hash-chained record of escalations and reviews.

    There is no `update` and no `delete`, exactly as `AppendOnlyLog` has none:
    a mistaken review is corrected by appending another, never by editing the
    first. The history of how often a bound was waved through is the point.
    """

    def __init__(self, db_path: str = "~/.gyza/review.db"):
        self._path = Path(os.path.expanduser(db_path))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._tls = threading.local()
        self._conn().executescript(_SCHEMA)
        self._conn().commit()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tls, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self._path), check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            self._tls.conn = c
        return c

    # -- the only mutator ---------------------------------------------------
    def _append(self, record_id: str, kind: str, payload: dict) -> str:
        with self._lock:
            conn = self._conn()
            row = conn.execute(
                "SELECT hash FROM review_log ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev = row["hash"] if row else GENESIS
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM review_log"
            ).fetchone()["n"]
            at = time.time_ns()
            h = _hash(seq, kind, payload, at, prev)
            conn.execute(
                "INSERT INTO review_log (seq, record_id, kind, payload, at_ns,"
                " prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                (seq, record_id, kind,
                 json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
                 at, prev, h))
            conn.commit()
            return h

    # -- escalate -----------------------------------------------------------
    def escalate(self, harm_class: str, measured: float, bound: float,
                 reason: str = "") -> Escalation:
        rid = str(uuid.uuid7())
        e = Escalation(rid, harm_class, float(measured), float(bound),
                       reason, time.time_ns())
        self._append(rid, "ESCALATION", {
            "harm_class": harm_class, "measured": float(measured),
            "bound": float(bound), "reason": reason})
        return e

    # -- review -------------------------------------------------------------
    def resolve(self, record_id: str, reviewer: str, decision: str,
                note: str = "", new_origin: dict | None = None) -> Review:
        """Record a human's decision. RESUME advances the accounting origin.

        `reviewer` and `note` are REQUIRED to be non-empty for a RESUME: a
        resume with no named reviewer and no stated reason is an origin advance
        nobody is accountable for, which is the thing this record exists to make
        impossible.
        """
        if decision not in (RESUME, HALT):
            raise ValueError(f"decision must be {RESUME} or {HALT}, got {decision!r}")
        if decision == RESUME and (not reviewer.strip() or not note.strip()):
            raise ValueError(
                "a RESUME requires a named reviewer and a stated reason: it "
                "advances the accounting origin, and an origin advance nobody "
                "is accountable for is how a cumulative bound is defeated "
                "silently (ledger artifact #13)")
        if record_id not in {e.record_id for e in self.pending()}:
            raise KeyError(f"no pending escalation {record_id!r}")
        origin = dict(new_origin or {})
        r = Review(record_id, reviewer, decision, note, origin, time.time_ns())
        self._append(record_id, "REVIEW", {
            "reviewer": reviewer, "decision": decision, "note": note,
            "new_origin": origin})
        return r

    # -- projections (derived, never stored) --------------------------------
    def _rows(self, kind: str | None = None):
        q = "SELECT * FROM review_log"
        args: tuple = ()
        if kind:
            q += " WHERE kind = ?"
            args = (kind,)
        return self._conn().execute(q + " ORDER BY seq ASC", args).fetchall()

    def pending(self) -> list[Escalation]:
        """Escalations with no review. Derived by folding, never a status flag
        that a write could leave stale."""
        reviewed = {r["record_id"] for r in self._rows("REVIEW")}
        out = []
        for r in self._rows("ESCALATION"):
            if r["record_id"] in reviewed:
                continue
            p = json.loads(r["payload"])
            out.append(Escalation(r["record_id"], p["harm_class"], p["measured"],
                                  p["bound"], p.get("reason", ""), r["at_ns"]))
        return out

    def resume_count(self) -> int:
        """How many times a human waved a bound through. The number that makes
        a repeatedly-advanced origin visible instead of silent."""
        return sum(1 for r in self._rows("REVIEW")
                   if json.loads(r["payload"])["decision"] == RESUME)

    def verify_chain(self) -> tuple[bool, str]:
        """Recompute the hash chain. A removed or edited record breaks it."""
        prev = GENESIS
        for r in self._rows():
            h = _hash(r["seq"], r["kind"], json.loads(r["payload"]),
                      r["at_ns"], prev)
            if h != r["hash"]:
                return False, f"record {r['seq']} does not match its hash"
            if r["prev_hash"] != prev:
                return False, f"record {r['seq']} breaks the chain"
            prev = r["hash"]
        return True, "intact"

    def summary(self) -> dict:
        esc = self._rows("ESCALATION")
        pend = self.pending()
        waits = [time.time_ns() - e.at_ns for e in pend]
        return {
            "escalations": len(esc),
            "pending": len(pend),
            "resumes": self.resume_count(),
            "oldest_pending_s": (max(waits) / 1e9) if waits else 0.0,
            "chain": self.verify_chain()[1],
        }


def check_cadence(queue: "ReviewQueue", harm_registry, actions_since_origin: int,
                  harm_class: str = "H6_unsupervised_actions") -> Escalation | None:
    """Open an escalation if the review cadence has been reached.

    IDEMPOTENT BY CONSTRUCTION. If an escalation for this class is already
    pending, none is opened: a check that fired once per call would flood the
    queue and make `oldest_pending` meaningless, and a reviewer facing ten
    thousand identical rows reviews none of them.

    Returns the escalation if one was opened, else None. Never raises on an
    unbounded class -- an undeclared bound is a separate condition, already
    reported by `readiness()`, and conflating them would hide one behind the
    other.
    """
    try:
        bound = harm_registry.bound(harm_class)
    except Exception:  # noqa: BLE001 - unbounded is reported elsewhere
        return None
    if actions_since_origin < bound:
        return None
    if any(e.harm_class == harm_class for e in queue.pending()):
        return None
    return queue.escalate(
        harm_class, float(actions_since_origin), float(bound),
        reason=f"review cadence reached: {actions_since_origin:,} actions "
               f"since the accounting origin, declared cadence {bound:,.0f}")


__all__ = ["ReviewQueue", "Escalation", "Review", "RESUME", "HALT",
           "check_cadence"]
