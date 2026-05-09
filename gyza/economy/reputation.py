"""
Phase 3 Session 8.5 — local reputation store.

Before this module:

  * ``AgentDescriptor.reputation_score`` was hardcoded to 1.0
    everywhere it appeared.
  * ``find_agents(... min_reputation=...)`` accepted a filter argument
    that nothing in the system would ever cause to fail — every
    advertisement reported "perfect" reputation.
  * Nothing in the runner or settlement service reflected observed
    outcomes back into discoverability.

This module provides a persistent, locally-computed reputation score
in ``[0, 1]`` keyed by pubkey. The pubkey may be:

  * an agent pubkey (local agents the runner manages), in which case
    the score reflects "what this agent has done on this node," OR
  * a compositor pubkey (remote peers we've transacted with), in
    which case the score reflects "what this peer has done from our
    perspective."

The store doesn't enforce that distinction — it's the caller's job
to use the right pubkey type at the right callsite. The score
formula is identical either way.

Score model
-----------

EWMA over outcome events:

    new = (1 - alpha) * old + alpha * outcome
    outcome ∈ [-1, +1]
    new clamped to [0, 1]

We use ``alpha = 0.05`` so:

  * 14 successes in a row from a neutral start (0.5) bring the score
    above 0.75 — meaningful but not instant.
  * One dispute (outcome=-1) from a perfect score (1.0) pulls the
    score down to ~0.95 — a flag, not a death sentence.
  * After ~60 events of no signal the score decays toward the
    midpoint (well, it doesn't — there's no idle decay). Idle decay
    is left as a Phase 4 concern; the current model is "what we've
    actually observed."

Why no idle decay yet: in a sparse network, an agent with 3 successes
on day 1 and nothing for 30 days shouldn't suddenly look untrusted
just because no one routed it work. Distinguishing "nobody asked"
from "asked and failed" requires either Sybil-resistant uptime
attestation (Phase 4) or correlating with the demand oracle. Both
out of scope here.

Default reputation
------------------

Unknown pubkey → 0.5. Neither perfect nor failed: cautious neutrality.
Callers that want different defaults (e.g. "trust new locals more
than new strangers") wrap ``get`` with their own policy.

Persistence
-----------

SQLite-backed, one row per pubkey. Updates are atomic via UPSERT. The
DB lives at the path the user provides — typically alongside the
ledger DB so the whole "economic + trust state" is co-located on disk.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path


LOG = logging.getLogger("gyza.economy.reputation")


_NEUTRAL_SCORE = 0.5
_DEFAULT_ALPHA = 0.05  # EWMA learning rate

# Outcome constants. Disputes are weighted as a STRONG negative because
# they signal deliberate protocol violation (mismatched cost claim,
# forged signature) rather than benign failure. A regular failure is
# usually "the executor crashed" or "the model returned garbage" —
# noisy, not malicious.
_OUTCOME_SUCCESS = 1.0
_OUTCOME_FAILURE = -0.5
_OUTCOME_DISPUTE = -1.0


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reputation (
    pubkey         TEXT PRIMARY KEY,
    score          REAL NOT NULL,
    event_count    INTEGER NOT NULL DEFAULT 0,
    last_updated_ns INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reputation_score ON reputation(score);
"""


class ReputationStore:
    """
    Per-pubkey reputation score in ``[0, 1]``, EWMA-updated by
    ``record_*`` calls.

    Thread-safety: each thread gets its own SQLite connection via
    threading.local. SQLite WAL handles concurrent reads with one
    writer; the EWMA update is a single UPSERT so the read-modify-write
    is wrapped in a SAVEPOINT.
    """

    def __init__(
        self,
        db_path: str = "~/.gyza/reputation.db",
        alpha: float = _DEFAULT_ALPHA,
    ):
        if not 0 < alpha < 1:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self._db_path = Path(os.path.expanduser(db_path))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._alpha = alpha
        self._tls = threading.local()
        # Single global lock for the read-modify-write update path.
        # SQLite's row-level locking would let UPSERTs race with each
        # other producing reads-of-stale-state for the EWMA math; the
        # lock is cheap and removes the class of bugs.
        self._lock = threading.Lock()
        self._conn().executescript(_SCHEMA_SQL)
        self._conn().commit()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tls, "conn", None)
        if c is not None:
            return c
        c = sqlite3.connect(str(self._db_path), isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=10000")
        self._tls.conn = c
        return c

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, pubkey: str) -> float:
        """
        Return the recorded score, or ``_NEUTRAL_SCORE`` (0.5) if we
        have no observations of this pubkey. Always in ``[0, 1]``.
        """
        row = self._conn().execute(
            "SELECT score FROM reputation WHERE pubkey=?", (pubkey,),
        ).fetchone()
        if row is None:
            return _NEUTRAL_SCORE
        return float(row["score"])

    def event_count(self, pubkey: str) -> int:
        """Number of outcome events recorded for this pubkey. Useful
        for distinguishing "0.7 from one observation" (high uncertainty)
        from "0.7 from a hundred observations" (high confidence)."""
        row = self._conn().execute(
            "SELECT event_count FROM reputation WHERE pubkey=?", (pubkey,),
        ).fetchone()
        if row is None:
            return 0
        return int(row["event_count"])

    def all_known(self) -> list[tuple[str, float, int]]:
        """Snapshot of (pubkey, score, event_count) for every recorded
        pubkey, ordered by score ascending — the lowest-scored first
        because that's usually what an operator wants to inspect."""
        rows = self._conn().execute(
            "SELECT pubkey, score, event_count FROM reputation "
            "ORDER BY score ASC, event_count DESC"
        ).fetchall()
        return [(r["pubkey"], float(r["score"]), int(r["event_count"])) for r in rows]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def record_success(self, pubkey: str) -> float:
        """Record a successful outcome. Returns the new score."""
        return self._update(pubkey, _OUTCOME_SUCCESS)

    def record_failure(self, pubkey: str) -> float:
        """Record an ordinary failure. Returns the new score."""
        return self._update(pubkey, _OUTCOME_FAILURE)

    def record_dispute(self, pubkey: str) -> float:
        """Record a protocol-level dispute (mismatched cost,
        forged signature, envelope-hash mismatch). Disputes carry
        higher weight than ordinary failures — this is a signal
        of deliberate misbehavior, not noise. Returns the new score."""
        return self._update(pubkey, _OUTCOME_DISPUTE)

    def _update(self, pubkey: str, outcome: float) -> float:
        """
        EWMA update:
            new = (1 - alpha) * old + alpha * outcome_normalized
        where outcome_normalized maps [-1, +1] → [0, 1] linearly so a
        +1 outcome pulls toward 1 and a -1 outcome pulls toward 0.

        outcome_normalized = (outcome + 1) / 2

        Result clamped to [0, 1] (defensive — the math should keep us
        in range but float-rounding under repeated extreme inputs
        could nudge us out).
        """
        if not -1.0 <= outcome <= 1.0:
            raise ValueError(f"outcome must be in [-1, 1], got {outcome}")
        outcome_norm = (outcome + 1.0) / 2.0
        with self._lock:
            row = self._conn().execute(
                "SELECT score, event_count FROM reputation WHERE pubkey=?",
                (pubkey,),
            ).fetchone()
            if row is None:
                old = _NEUTRAL_SCORE
                count = 0
            else:
                old = float(row["score"])
                count = int(row["event_count"])
            new = (1.0 - self._alpha) * old + self._alpha * outcome_norm
            # Clamp.
            if new < 0.0:
                new = 0.0
            elif new > 1.0:
                new = 1.0
            self._conn().execute(
                """
                INSERT INTO reputation (pubkey, score, event_count, last_updated_ns)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(pubkey) DO UPDATE SET
                    score = excluded.score,
                    event_count = excluded.event_count,
                    last_updated_ns = excluded.last_updated_ns
                """,
                (pubkey, new, count + 1, time.time_ns()),
            )
            return new

    def reset(self, pubkey: str) -> None:
        """Hard-reset to neutral. Drops the event_count too. Operator
        escape hatch — call when manually clearing a false flag."""
        with self._lock:
            self._conn().execute(
                "DELETE FROM reputation WHERE pubkey=?", (pubkey,),
            )


__all__ = ["ReputationStore"]
