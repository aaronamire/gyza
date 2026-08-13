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
    # Architectural debt: this module loads SentenceTransformer
    # independently of ``gyza.embeddings`` — it predates the unified
    # embedder protocol. When ``GYZA_EMBEDDER=stub`` is set the rest
    # of the system uses ``StubEmbedder`` but ``_get_model()`` would
    # still cold-load ST, silently undoing the opt-out and causing a
    # ~10-15s pause on the first ``retrieve_similar`` with non-empty
    # memory (e.g. the 2nd round of demo/single_machine_global.py
    # --fast). Honour the env var explicitly here. The longer-term
    # fix is to delete ``_get_model`` and route through
    # ``gyza.embeddings.default_embedder()``; this hop preserves the
    # existing ``_EmbeddingsUnavailable`` semantics callers depend on.
    if os.environ.get("GYZA_EMBEDDER", "").strip().lower() == "stub":
        from gyza.embeddings import default_embedder
        return default_embedder().embed_batch(texts).astype(np.float32)
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

    def search(self, query_vec: np.ndarray, k: int,
               *, success_only: bool = False) -> list[tuple[Episode, float]]:
        """Top candidates by COSINE over L2-NORMALIZED vectors.

        Two divergences from the SQLite path were fixed here; both were found by
        the respecification verifier (`gyza/verification/respec.py`), which is
        now their regression test.

        D1 -- FILTER BEFORE RANK, not after. The previous version over-fetched
        ``max(4k, 16)`` candidates and let `retrieve_similar` drop the
        unsuccessful ones AFTERWARD. If the nearest 20 episodes were all
        failures, this returned NOTHING while qualifying successes existed --
        silently, and differently from the SQLite path, which scans everything.
        The filter is now pushed into the query as a LanceDB PREFILTER, so the
        over-fetch window contains only rows that can survive it.

        Alternatives considered and rejected (see
        research/respecification/FINDINGS.md §A1): an ADAPTIVE over-fetch that
        widens until k qualify degenerates to a full scan over an
        all-unsuccessful corpus and pays several round trips to get there; an
        EXHAUSTIVE scan is sound but abandons the index, trading a silent wrong
        answer for a silent performance cliff, which is a different bug rather
        than a fix.

        D2 -- SCORE BY THE DECLARED METRIC. The previous version computed
        ``dot(query, stored_vector)`` against the UN-normalized stored vector,
        so magnitude decided the ranking rather than direction: cosine 1.0 at
        norm 0.05 lost to a lower cosine at norm 6.0. `RetrievalClaim` declares
        ``metric = "cosine_unit"``, defined as the dot product of L2-normalized
        vectors, so THE METRIC DEFINITION IS THE ARBITER -- not either
        implementation.

        What is NOT claimed: exactness. This is an approximate-nearest-neighbour
        index and remains one. What is fixed is the SYSTEMATIC under-retrieval,
        where a qualifying result could never be returned regardless of recall.
        """
        if self._table is None:
            return []
        q = _normalize(np.asarray(query_vec, dtype=np.float32))
        query = self._table.search(q.tolist())
        if success_only:
            # D1: prefilter, so the window holds only qualifying rows.
            query = query.where("success = true", prefilter=True)
        df = query.limit(max(k * 4, 16)).to_list()
        results: list[tuple[Episode, float]] = []
        for r in df:
            ep = self._row_to_episode(r)
            cos = float(np.dot(q, _normalize(ep.task_embedding)))   # D2
            results.append((ep, cos))
        # deterministic tie-break by id, matching the verifier's ordering so a
        # tie cannot make a correct implementation look divergent.
        results.sort(key=lambda t: (-t[1], t[0].episode_id))
        return results

    def all_for_agent(self) -> list[Episode]:
        """Full candidate set. Needed ONLY to content-address the corpus
        snapshot for a RetrievalClaim -- it is an O(corpus) scan and is never
        on the retrieval hot path."""
        if self._table is None:
            return []
        return [self._row_to_episode(r) for r in self._table.to_arrow().to_pylist()]

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
        # Set only when retrieve_similar(emit_claim=True) is used; None means
        # NO CLAIM WAS PRODUCED, never "the claim was empty".
        self.last_retrieval_claim = None
        # THE CONSUMER. Optional, and None means claims are recorded nowhere --
        # which is the state this attribute exists to end. A claim stashed on
        # `last_retrieval_claim` and read by nobody is not verification; it is
        # an assertion with a nice type. Attach a `ClaimLedger` and the claim
        # carries the arguments needed to RECHECK it.
        self.claim_ledger = None

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
        emit_claim: bool = False,
    ) -> list[Episode]:
        """Retrieve similar past episodes.

        `emit_claim` -- when True, also build the `RetrievalClaim` describing
        exactly what was returned and stash it on `last_retrieval_claim`.

        WHY IT IS OPT-IN AND OFF BY DEFAULT. Content-addressing the corpus
        snapshot requires enumerating every candidate, which is O(corpus) -- the
        same full scan this module just refused as a fix for D1, where trading a
        silent wrong answer for a silent performance cliff was rejected as "a
        different bug, not a fix". Making the claim mandatory would reintroduce
        that cliff on the retrieval hot path. So verification is O(corpus) and
        retrieval stays O(log corpus): an auditor pays the cost deliberately,
        every query does not.
        """
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
            # D1: the filter must reach the QUERY, not just this loop.
            ranked = self._backend.search(q_vec, k=k, success_only=success_only)
        else:
            ranked = []
            for ep in self._backend.all_for_agent():
                v = _normalize(ep.task_embedding)
                ranked.append((ep, float(np.dot(q_vec, v))))
            ranked.sort(key=lambda t: (-t[1], t[0].episode_id))

        results: list[Episode] = []
        for ep, sim in ranked:
            if sim < min_similarity:
                continue
            if success_only and not ep.success:
                continue
            results.append(ep)
            if len(results) >= k:
                break

        if emit_claim:
            self.last_retrieval_claim = self._build_retrieval_claim(
                results, k, min_similarity, success_only)
            if self.claim_ledger is not None:
                # The claim type comes from the OPERATION, not from classifying
                # the task -- `retrieve_similar` emits this type because that is
                # what it did. (BLOCKED_SR1's "assigning a claim type is itself
                # tier-3" binds decomposition, not emission.)
                self.claim_ledger.emit(
                    "memory_retrieval_relevance",
                    self.last_retrieval_claim,
                    [(e.episode_id, e.task_embedding, bool(e.success))
                     for e in self._backend.all_for_agent()],
                    q_vec,
                    note=f"retrieve_similar k={k} thr={min_similarity}")
        return results

    def _build_retrieval_claim(self, results, k, min_similarity, success_only):
        """Emit the claim carrying the parameters that used to be implicit.

        Every parameter is named: metric, k, threshold, filter and a
        content-addressed corpus snapshot. `RetrievalClaim` rejects an
        incomplete claim at construction, so a producer cannot default one.
        """
        from gyza.verification.respec import (
            FILTER_NONE, FILTER_SUCCESS_ONLY, METRIC_COSINE_UNIT,
            RetrievalClaim, corpus_snapshot_digest,
        )
        corpus = [(e.episode_id, e.task_embedding, bool(e.success))
                  for e in self._backend.all_for_agent()]
        return RetrievalClaim(
            corpus_snapshot=corpus_snapshot_digest(corpus),
            metric=METRIC_COSINE_UNIT,
            k=k,
            threshold=float(min_similarity),
            filter_predicate=FILTER_SUCCESS_ONLY if success_only else FILTER_NONE,
            returned_ids=tuple(e.episode_id for e in results),
        )

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
    # THE PRODUCTION RETRIEVAL PATH (AgentRunner._execute -> here). Emit the
    # claim exactly when a consumer is attached: `retrieve_similar` documents
    # that claim construction is O(corpus) and must not sit on the hot path, so
    # attaching a ledger is the deliberate opt-in that docstring asks for. With
    # no ledger the cost and the behaviour are unchanged.
    episodes = memory.retrieve_similar(
        current_task, k=max_episodes,
        emit_claim=memory.claim_ledger is not None)
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
