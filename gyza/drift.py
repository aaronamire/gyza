"""
Specialization drift — agents nudge their identity-embedding toward
the tasks they succeed at and away from the ones they fail.

Update rule (per task):
    direction = task_emb if success else -0.1 * task_emb
    new      = (1 - DRIFT_RATE) * current + DRIFT_RATE * direction
    return new / ||new||

DRIFT_RATE is small (3%) so identity moves slowly; the L2-normalize at
the end keeps the embedding on the unit sphere where cosine similarity
is the natural metric.

`SpecializationTracker` persists the live embedding in its own SQLite
table so an agent process can crash and resume with intact specialization
history.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

from gyza.schema import EMBEDDING_DIM


DRIFT_RATE = 0.03


def update_specialization(
    current: np.ndarray,
    task_embedding: np.ndarray,
    success: bool,
) -> np.ndarray:
    if current.shape != (EMBEDDING_DIM,) or task_embedding.shape != (EMBEDDING_DIM,):
        raise ValueError(
            f"both embeddings must be shape ({EMBEDDING_DIM},); "
            f"got {current.shape} and {task_embedding.shape}"
        )
    cur = current.astype(np.float32)
    task = task_embedding.astype(np.float32)
    direction = task if success else (-0.1 * task)
    new_emb = (1 - DRIFT_RATE) * cur + DRIFT_RATE * direction
    n = float(np.linalg.norm(new_emb))
    if n == 0.0:
        # Degenerate: drift produced the zero vector (would happen if the
        # update perfectly cancelled, e.g. task = -current/(DRIFT_RATE-1)
        # in failure mode). Fall back to current direction so the agent
        # doesn't lose all identity.
        return cur / max(float(np.linalg.norm(cur)), 1e-9)
    return (new_emb / n).astype(np.float32)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_embeddings (
    agent_id        TEXT PRIMARY KEY,
    embedding       BLOB NOT NULL,
    update_count    INTEGER NOT NULL DEFAULT 0,
    updated_at_ns   INTEGER NOT NULL
);
"""


def _to_blob(arr: np.ndarray) -> bytes:
    if arr.dtype != np.float32 or arr.shape != (EMBEDDING_DIM,):
        raise ValueError(
            f"embedding must be float32 shape ({EMBEDDING_DIM},), "
            f"got {arr.dtype} {arr.shape}"
        )
    return arr.tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    arr = np.frombuffer(blob, dtype=np.float32)
    if arr.shape != (EMBEDDING_DIM,):
        raise ValueError(f"corrupt embedding blob: shape {arr.shape}")
    return arr.copy()


class SpecializationTracker:
    def __init__(
        self,
        agent_id: str,
        initial_embedding: np.ndarray,
        db_path: str,
    ):
        if initial_embedding.shape != (EMBEDDING_DIM,):
            raise ValueError(
                f"initial_embedding shape must be ({EMBEDDING_DIM},), "
                f"got {initial_embedding.shape}"
            )
        self._agent_id = agent_id
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._tls = threading.local()
        self._lock = threading.Lock()

        conn = self._conn()
        conn.executescript(_SCHEMA_SQL)

        # Load prior state if it exists, else seed with caller's initial.
        row = conn.execute(
            "SELECT embedding, update_count FROM agent_embeddings WHERE agent_id=?",
            (agent_id,),
        ).fetchone()
        if row is None:
            init = initial_embedding.astype(np.float32)
            n = float(np.linalg.norm(init))
            if n > 0.0:
                init = init / n
            self._current = init.astype(np.float32)
            self._update_count = 0
            conn.execute(
                "INSERT INTO agent_embeddings "
                "(agent_id, embedding, update_count, updated_at_ns) "
                "VALUES (?, ?, ?, ?)",
                (agent_id, _to_blob(self._current), 0, time.time_ns()),
            )
        else:
            self._current = _from_blob(row["embedding"])
            self._update_count = int(row["update_count"])

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tls, "conn", None)
        if c is not None:
            return c
        c = sqlite3.connect(str(self._db_path))
        c.row_factory = sqlite3.Row
        c.isolation_level = None
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=10000")
        self._tls.conn = c
        return c

    def update(self, task_embedding: np.ndarray, success: bool) -> np.ndarray:
        with self._lock:
            new_emb = update_specialization(self._current, task_embedding, success)
            self._current = new_emb
            self._update_count += 1
            self._conn().execute(
                "UPDATE agent_embeddings "
                "SET embedding=?, update_count=?, updated_at_ns=? "
                "WHERE agent_id=?",
                (_to_blob(new_emb), self._update_count, time.time_ns(), self._agent_id),
            )
            return new_emb

    @property
    def current(self) -> np.ndarray:
        with self._lock:
            return self._current.copy()

    @property
    def update_count(self) -> int:
        with self._lock:
            return self._update_count


__all__ = ["DRIFT_RATE", "update_specialization", "SpecializationTracker"]
