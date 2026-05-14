"""
Episodic memory — per-agent retrieval store of past task executions.

Each Episode records what the agent attempted, what it consumed and
produced (by BLAKE3 hash), how it went, and a back-reference to the
ICP envelope hash so the signed chain can be re-walked from any episode.

Storage is LanceDB for ANN search over `task_embedding`. Embeddings come
from `sentence-transformers/all-MiniLM-L6-v2` — the same model marshal's
`rag/store.py` uses, loaded once per process via a module-level cache so
two agent processes don't fight for ~80MB of model weights.

A SQLite fallback is wired up for environments where LanceDB can't load
(e.g., partial wheel install, ARM box without prebuilt). The fallback
does brute-force cosine search; fine for the test scale, slow above
~50k episodes.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_EMBED_DIM = 384
_FLUSH_BATCH = 10
_FEW_SHOT_CHAR_LIMIT = 2000


# Process-wide model cache — avoids reloading 80MB of weights per agent.
_model_lock = threading.Lock()
_model_singleton: object | None = None


class _EmbeddingsUnavailable(Exception):
    """sentence-transformers is not installed in this environment."""


def _get_model():
    global _model_singleton
    with _model_lock:
        if _model_singleton is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                # On hosts that intentionally skip the [embeddings]
                # extra (e.g. the demo agent on a 1 GB VPS), retrieving
                # similar episodes is structurally impossible — there's
                # no encoder. We raise a typed exception so
                # retrieve_similar can degrade gracefully rather than
                # crash mid-execution.
                raise _EmbeddingsUnavailable(
                    "sentence-transformers is not installed; "
                    "EpisodicMemory.retrieve_similar will return []"
                ) from e
            _model_singleton = SentenceTransformer(_EMBED_MODEL_NAME)
        return _model_singleton


def _embed(texts: list[str]) -> np.ndarray:
    model = _get_model()
    arr = model.encode(texts, show_progress_bar=False)
    return np.asarray(arr, dtype=np.float32)


@dataclass
class Episode:
    episode_id: str
    agent_id: str
    task_embedding: np.ndarray
    intent_text: str
    input_hashes: list[str]
    output_hash: str
    action_types: list[str]
    success: bool
    duration_ms: int
    model_identifier: str
    icp_envelope_hash: str
    timestamp_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.task_embedding, np.ndarray):
            raise TypeError("task_embedding must be np.ndarray")
        if self.task_embedding.shape != (_EMBED_DIM,):
            raise ValueError(
                f"task_embedding must be shape ({_EMBED_DIM},), "
                f"got {self.task_embedding.shape}"
            )
        if self.task_embedding.dtype != np.float32:
            self.task_embedding = self.task_embedding.astype(np.float32)


# ---------------------------------------------------------------------------
# Storage backends. The LanceDB backend is the primary path; the SQLite
# backend is selected automatically if LanceDB import fails or initialization
# raises, so test environments still work.
# ---------------------------------------------------------------------------

def _resolve(p: str) -> Path:
    return Path(os.path.expanduser(p))


class _SQLiteBackend:
    """
    Brute-force fallback. Stores episodes in a single table; retrieval
    scans every row and ranks by cosine. Adequate up to a few tens of
    thousands of episodes per agent.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS episodes (
        episode_id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        task_embedding BLOB NOT NULL,
        intent_text TEXT NOT NULL,
        input_hashes TEXT NOT NULL,
        output_hash TEXT NOT NULL,
        action_types TEXT NOT NULL,
        success INTEGER NOT NULL,
        duration_ms INTEGER NOT NULL,
        model_identifier TEXT NOT NULL,
        icp_envelope_hash TEXT NOT NULL,
        timestamp_ns INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ep_agent ON episodes(agent_id);
    CREATE INDEX IF NOT EXISTS idx_ep_ts ON episodes(timestamp_ns DESC);
    """

    def __init__(self, db_path: Path, agent_id: str):
        self._db_path = db_path
        self._agent_id = agent_id
        self._tls = threading.local()
        self._conn().executescript(self.SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tls, "conn", None)
        if c is not None:
            return c
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self._db_path))
        c.row_factory = sqlite3.Row
        c.isolation_level = None
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=10000")
        self._tls.conn = c
        return c

    def add(self, episodes: list[Episode]) -> None:
        rows = [
            (
                e.episode_id, e.agent_id, e.task_embedding.tobytes(),
                e.intent_text, json.dumps(e.input_hashes), e.output_hash,
                json.dumps(e.action_types), int(e.success), e.duration_ms,
                e.model_identifier, e.icp_envelope_hash, e.timestamp_ns,
            )
            for e in episodes
        ]
        self._conn().executemany(
            "INSERT OR REPLACE INTO episodes VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def all_for_agent(self) -> list[Episode]:
        rows = self._conn().execute(
            "SELECT * FROM episodes WHERE agent_id=? ORDER BY timestamp_ns DESC",
            (self._agent_id,),
        ).fetchall()
        out: list[Episode] = []
        for r in rows:
            out.append(Episode(
                episode_id=r["episode_id"],
                agent_id=r["agent_id"],
                task_embedding=np.frombuffer(
                    r["task_embedding"], dtype=np.float32
                ).copy(),
                intent_text=r["intent_text"],
                input_hashes=json.loads(r["input_hashes"]),
                output_hash=r["output_hash"],
                action_types=json.loads(r["action_types"]),
                success=bool(r["success"]),
                duration_ms=r["duration_ms"],
                model_identifier=r["model_identifier"],
                icp_envelope_hash=r["icp_envelope_hash"],
                timestamp_ns=r["timestamp_ns"],
            ))
        return out

    def count(self) -> int:
        row = self._conn().execute(
            "SELECT COUNT(*) AS n FROM episodes WHERE agent_id=?",
            (self._agent_id,),
        ).fetchone()
        return int(row["n"])

    def success_count(self) -> tuple[int, int]:
        row = self._conn().execute(
            "SELECT COUNT(*) AS n, SUM(success) AS s "
            "FROM episodes WHERE agent_id=?",
            (self._agent_id,),
        ).fetchone()
        n = int(row["n"] or 0)
        s = int(row["s"] or 0)
        return s, n


class _LanceBackend:
    def __init__(self, db_path: Path, agent_id: str):
        import lancedb  # noqa: F401 — import-side effect: validates wheel
        self._lance_path = db_path / "lancedb"
        self._lance_path.mkdir(parents=True, exist_ok=True)
        self._agent_id = agent_id
        self._table_name = self._safe_table_name(agent_id)
        self._table = None
        self._db = None
        self._connect()

    @staticmethod
    def _safe_table_name(agent_id: str) -> str:
        # LanceDB table names need to be filesystem-safe. Pubkey hex is
        # already [0-9a-f]; just prefix to make the namespacing explicit.
        return f"episodes_{agent_id}"

    def _connect(self) -> None:
        import lancedb
        self._db = lancedb.connect(str(self._lance_path))
        names = self._db.list_tables() if hasattr(self._db, "list_tables") else self._db.table_names()
        if self._table_name in names:
            self._table = self._db.open_table(self._table_name)

    def _ensure_table(self, sample: Episode) -> None:
        if self._table is not None:
            return
        # Create with one placeholder row, then drop it. LanceDB requires
        # data to infer the schema; the alternative is pyarrow schema
        # construction, which adds a heavy dep we don't otherwise need.
        placeholder = self._episode_to_row(sample)
        placeholder["episode_id"] = "__placeholder__"
        self._table = self._db.create_table(
            self._table_name, data=[placeholder]
        )
        self._table.delete('episode_id = "__placeholder__"')

    @staticmethod
    def _episode_to_row(e: Episode) -> dict:
        return {
            "episode_id": e.episode_id,
            "agent_id": e.agent_id,
            "vector": e.task_embedding.astype(np.float32).tolist(),
            "intent_text": e.intent_text,
            "input_hashes_json": json.dumps(e.input_hashes),
            "output_hash": e.output_hash,
            "action_types_json": json.dumps(e.action_types),
            "success": bool(e.success),
            "duration_ms": int(e.duration_ms),
            "model_identifier": e.model_identifier,
            "icp_envelope_hash": e.icp_envelope_hash,
            "timestamp_ns": int(e.timestamp_ns),
        }

    @staticmethod
    def _row_to_episode(r: dict) -> Episode:
        return Episode(
            episode_id=r["episode_id"],
            agent_id=r["agent_id"],
            task_embedding=np.asarray(r["vector"], dtype=np.float32),
            intent_text=r["intent_text"],
            input_hashes=json.loads(r["input_hashes_json"]),
            output_hash=r["output_hash"],
            action_types=json.loads(r["action_types_json"]),
            success=bool(r["success"]),
            duration_ms=int(r["duration_ms"]),
            model_identifier=r["model_identifier"],
            icp_envelope_hash=r["icp_envelope_hash"],
            timestamp_ns=int(r["timestamp_ns"]),
        )

    def add(self, episodes: list[Episode]) -> None:
        if not episodes:
            return
        if self._table is None:
            self._ensure_table(episodes[0])
        rows = [self._episode_to_row(e) for e in episodes]
        self._table.add(rows)

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[Episode, float]]:
        if self._table is None:
            return []
        # LanceDB returns _distance for L2 by default; we feed normalized
        # vectors so cosine = 1 - L2/2. Either way we re-rank below by
        # exact cosine to keep the API explicit.
        df = (
            self._table
            .search(query_vec.astype(np.float32).tolist())
            .limit(max(k * 4, 16))  # over-fetch, then cosine-rerank
            .to_list()
        )
        results: list[tuple[Episode, float]] = []
        for r in df:
            ep = self._row_to_episode(r)
            cos = float(np.dot(query_vec, ep.task_embedding))
            results.append((ep, cos))
        results.sort(key=lambda t: t[1], reverse=True)
        return results

    def count(self) -> int:
        if self._table is None:
            return 0
        return int(self._table.count_rows())

    def success_count(self) -> tuple[int, int]:
        if self._table is None:
            return 0, 0
        # Avoid to_pandas (pandas not installed in this venv); read via
        # arrow which lancedb already depends on.
        tbl = self._table.to_arrow()
        n = tbl.num_rows
        if n == 0:
            return 0, 0
        col = tbl.column("success").to_pylist()
        s = sum(1 for v in col if v)
        return s, n


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n == 0.0:
        return v.astype(np.float32)
    return (v / n).astype(np.float32)


class EpisodicMemory:
    def __init__(
        self,
        agent_id: str,
        db_path: str = "~/.gyza/memory.db",
    ):
        self._agent_id = agent_id
        self._db_dir = _resolve(db_path)
        self._db_dir.parent.mkdir(parents=True, exist_ok=True)

        self._buffer: list[Episode] = []
        self._buffer_lock = threading.Lock()

        # Try LanceDB first; fall back to SQLite if anything in the
        # initialization path raises (missing wheel, schema mismatch,
        # corrupted store).
        backend: object
        try:
            backend = _LanceBackend(self._db_dir, agent_id)
            self._backend_name = "lancedb"
        except Exception:
            sqlite_path = self._db_dir / f"episodes_{agent_id}.sqlite"
            backend = _SQLiteBackend(sqlite_path, agent_id)
            self._backend_name = "sqlite"
        self._backend = backend

    @property
    def backend(self) -> str:
        return self._backend_name

    def write(self, episode: Episode) -> None:
        with self._buffer_lock:
            self._buffer.append(episode)
            if len(self._buffer) >= _FLUSH_BATCH:
                pending = self._buffer
                self._buffer = []
            else:
                return
        self._backend.add(pending)

    def flush(self) -> None:
        with self._buffer_lock:
            if not self._buffer:
                return
            pending = self._buffer
            self._buffer = []
        self._backend.add(pending)

    def retrieve_similar(
        self,
        task_text: str,
        k: int = 5,
        min_similarity: float = 0.75,
        success_only: bool = True,
    ) -> list[Episode]:
        # Always flush so a just-written episode is searchable.
        self.flush()

        # Short-circuit on empty memory: skip the (expensive) encoder load
        # entirely. A fresh agent's first task should not pay for a 2-3s
        # SentenceTransformer initialization just to prove there's nothing
        # to retrieve.
        if self._backend.count() == 0:
            return []

        # Graceful degradation when sentence-transformers isn't
        # installed (demo agent on small VPSes). Without the encoder
        # we can't compute a query embedding — return empty so the
        # caller falls back to a non-enriched prompt.
        try:
            q_vec = _normalize(_embed([task_text])[0])
        except _EmbeddingsUnavailable:
            return []

        if isinstance(self._backend, _LanceBackend):
            ranked = self._backend.search(q_vec, k=k)
        else:
            ranked = []
            for ep in self._backend.all_for_agent():
                v = _normalize(ep.task_embedding)
                ranked.append((ep, float(np.dot(q_vec, v))))
            ranked.sort(key=lambda t: t[1], reverse=True)

        results: list[Episode] = []
        for ep, sim in ranked:
            if sim < min_similarity:
                continue
            if success_only and not ep.success:
                continue
            results.append(ep)
            if len(results) >= k:
                break
        return results

    def format_as_few_shot(self, episodes: list[Episode]) -> str:
        # Newest-first composition. We then truncate from the *end* (oldest
        # examples) so the freshest, most-relevant context survives the
        # 2000-char ceiling.
        ordered = sorted(episodes, key=lambda e: e.timestamp_ns, reverse=True)
        chunks: list[str] = []
        total = 0
        for i, ep in enumerate(ordered, start=1):
            outcome = "success" if ep.success else "failed"
            block = (
                f"# Past experience #{i}\n"
                f"Task: {ep.intent_text}\n"
                f"Actions: {', '.join(ep.action_types)}\n"
                f"Outcome: {outcome}\n"
                f"Duration: {ep.duration_ms}ms\n\n"
            )
            if total + len(block) > _FEW_SHOT_CHAR_LIMIT:
                break
            chunks.append(block)
            total += len(block)
        return "".join(chunks)

    def episode_count(self) -> int:
        self.flush()
        return self._backend.count()

    def success_rate(self) -> float:
        self.flush()
        s, n = self._backend.success_count()
        if n == 0:
            return 0.0
        return float(s) / float(n)


def build_enriched_prompt(
    base_prompt: str,
    memory: EpisodicMemory,
    current_task: str,
    max_episodes: int = 5,
) -> str:
    episodes = memory.retrieve_similar(current_task, k=max_episodes)
    if not episodes:
        return base_prompt
    few_shot = memory.format_as_few_shot(episodes)
    return (
        "## Relevant past experience\n"
        f"{few_shot}"
        "## Current task\n"
        f"{base_prompt}"
    )


# Convenience helper for callers building Episode objects from an
# (intent_text, ICPEnvelope) pair — mirrors what marshal callers do.
def episode_from_envelope(
    *,
    episode_id: str,
    intent_text: str,
    action_types: list[str],
    success: bool,
    duration_ms: int,
    envelope_agent_pubkey: str,
    envelope_input_hashes: list[str],
    envelope_output_hash: str,
    envelope_model_identifier: str,
    envelope_hash: str,
    timestamp_ns: int,
    task_embedding: np.ndarray | None = None,
) -> Episode:
    if task_embedding is None:
        task_embedding = _embed([intent_text])[0]
    return Episode(
        episode_id=episode_id,
        agent_id=envelope_agent_pubkey,
        task_embedding=task_embedding.astype(np.float32),
        intent_text=intent_text,
        input_hashes=list(envelope_input_hashes),
        output_hash=envelope_output_hash,
        action_types=list(action_types),
        success=success,
        duration_ms=duration_ms,
        model_identifier=envelope_model_identifier,
        icp_envelope_hash=envelope_hash,
        timestamp_ns=timestamp_ns,
    )


__all__ = [
    "Episode",
    "EpisodicMemory",
    "build_enriched_prompt",
    "episode_from_envelope",
]

# Silence: asdict imported for downstream use.
_ = asdict
