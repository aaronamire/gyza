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


def check_cadence(queue: "ReviewQueue", cadence_actions, actions_since_origin: int,
                  harm_class: str = "H6_unsupervised_actions") -> Escalation | None:
    """Open an escalation if the review cadence has been reached.

    THE INTERVAL IS A SIGNED POLICY VALUE, NOT A HARM BOUND. Until 2026-08-21
    this read `harm_registry.bound("H6_unsupervised_actions")`, which made the
    cadence a harm class whose "bound" of 10,000 asserted only that the agent
    had not yet run 10,000 actions -- a timer, and R-EVID Part B measured its
    evidence at exactly 0. A timer is precisely what a cadence SHOULD be, so
    the mechanism was always right and only the classification was wrong. The
    interval now comes from the guard configuration's signed `policy` as
    `review_cadence_actions`, still signed by the same authority.

    `cadence_actions` accepts an int, or a registry-like object for
    compatibility with callers that still pass one -- resolved below rather
    than at the call sites, so a stale caller degrades to the old lookup
    instead of silently disabling the cadence.

    IDEMPOTENT BY CONSTRUCTION. If an escalation for this class is already
    pending, none is opened: a check that fired once per call would flood the
    queue and make `oldest_pending` meaningless, and a reviewer facing ten
    thousand identical rows reviews none of them.

    Returns the escalation if one was opened, else None. A missing interval
    returns None -- "no cadence configured" is a separate condition, already
    reported by `readiness()`, and conflating it with "not yet due" would hide
    one behind the other.
    """
    if isinstance(cadence_actions, (int, float)) and not isinstance(
            cadence_actions, bool):
        bound = float(cadence_actions)
    else:
        try:                     # legacy: a harm registry was passed
            bound = float(cadence_actions.bound(harm_class))
        except Exception:        # noqa: BLE001 - unconfigured is reported elsewhere
            return None
    if bound <= 0:
        return None
    if actions_since_origin < bound:
        return None
    if any(e.harm_class == harm_class for e in queue.pending()):
        return None
    return queue.escalate(
        harm_class, float(actions_since_origin), float(bound),
        reason=f"review cadence reached: {actions_since_origin:,} actions "
               f"since the accounting origin, declared cadence {bound:,.0f}")


def _signed_cadence_actions(bounds_file: "str | None" = None) -> "int | None":
    """Read `review_cadence_actions` from the guard configuration's policy.

    Returns None when absent, and the caller treats that as a wiring failure
    rather than a zero -- an absent cadence is "nobody reviews", which must not
    read as "reviewed continuously".
    """
    import json
    from pathlib import Path as _P

    from gyza.config import load_config
    path = bounds_file or load_config().guard_bounds_path
    try:
        doc = json.loads(_P(path).read_text())
    except Exception:                                        # noqa: BLE001
        return None
    cfg = doc.get("config", doc)
    v = (cfg.get("policy") or {}).get("review_cadence_actions")
    return int(v) if isinstance(v, (int, float)) and v > 0 else None


def default_cadence_wiring(review_db_path: "str | None" = None,
                           bounds_file: "str | None" = None):
    """Build H6's consumer for `AgentRunner`, or `(None, None, 0)` if it cannot.

    THIS EXISTS BECAUSE THE CADENCE NEVER RAN. `AgentRunner` accepts
    `review_queue` / `harm_registry` / `cadence_origin_ns`, and **no production
    construction supplied any of them**, so `self._review_queue` was always
    None and `check_cadence` was never called. Meanwhile
    `network/global_cluster.py` records the design decision that followed H1's
    retirement -- *"Autonomy is bounded instead by H6 (actions), checked in the
    runner"* -- which was FALSE IN PRODUCTION for exactly that reason. H1 was
    retired and its stated replacement was never wired, so nothing bounded
    autonomy at all.

    The comment directly above the runner's own cadence check says "the queue
    is the same unconsumed-surface defect one layer up". It anticipated this
    defect and was an instance of it.

    THE ORIGIN IS GENESIS (0) AND MUST STAY THERE. H6 is cumulative, and a
    cumulative bound whose origin can move is not a bound -- an origin at
    process start refills the budget on restart (ledger artifact #13). This
    matches what `gyza status` reports, so the operator's displayed position
    and the runner's enforced position are the SAME number.

    Returns `(None, None, 0)` on any failure: a review path that cannot open
    must not be the reason an agent refuses to run, and the honest state is
    then "cadence not watched", which `readiness()` already reports.
    """
    try:
        from gyza.config import load_config
        from gyza.containment.gyza_model import build_registries

        if review_db_path is None:
            review_db_path = load_config().review_db_path
        # THE INTERVAL COMES FROM THE SIGNED `policy`, not from a harm class.
        # H6 was retired as a harm class on 2026-08-21 (evidence 0); the
        # cadence it drives is unchanged at 10,000 and is still signed.
        cadence = _signed_cadence_actions(bounds_file)
        if cadence is None:
            raise RuntimeError(
                "no review_cadence_actions in the guard configuration's "
                "policy; the cadence would silently never fire")
        return ReviewQueue(review_db_path), cadence, 0
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("gyza.containment.review").warning(
            "[review] cadence not wired; H6 will not escalate", exc_info=True)
        return None, None, 0


__all__ = ["ReviewQueue", "Escalation", "Review", "RESUME", "HALT",
           "default_cadence_wiring",
           "check_cadence"]
