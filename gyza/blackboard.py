"""
Local Gyza blackboard — SQLite-backed shared work queue.

Phase 1 scope: a single host, multiple agent processes, no networking.
The blackboard is the durable medium through which agents publish work
items, claim them atomically, and store signed artifacts.

Lineage invariant: every work item must descend from a registered human
intent. `post_work_item` enforces this by foreign-key-checking the
`lineage_root` against `human_intents`. This is the safety boundary
that prevents agents from inventing top-level goals on their own.

Concurrency: each thread gets its own sqlite3 connection (thread-local).
SQLite's WAL mode allows concurrent reads alongside one writer; the
writer-lock serializes claim contention. `try_claim` uses BEGIN IMMEDIATE
so two threads racing for the same item see one winner deterministically.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

from gyza.schema import EMBEDDING_DIM, Artifact, HLC, WorkItem


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS human_intents (
    intent_id       TEXT PRIMARY KEY,
    goal_spec_json  TEXT NOT NULL,
    created_at_ns   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS work_items (
    id                  TEXT PRIMARY KEY,
    lineage_root        TEXT NOT NULL REFERENCES human_intents(intent_id),
    parent_id           TEXT,
    description         TEXT NOT NULL,
    desc_embedding      BLOB NOT NULL,
    reward              REAL NOT NULL,
    reward_updated_ns   INTEGER NOT NULL,
    required_tier       INTEGER NOT NULL,
    input_hashes        TEXT NOT NULL,
    output_spec         TEXT NOT NULL,
    streaming_ok        INTEGER NOT NULL,
    claimed_by          TEXT,
    claimed_at_ns       INTEGER,
    claim_hlc_l         INTEGER NOT NULL DEFAULT 0,
    claim_hlc_c         INTEGER NOT NULL DEFAULT 0,
    claim_hlc_node      TEXT NOT NULL DEFAULT '',
    completed_at_ns     INTEGER,
    output_hash         TEXT,
    icp_envelope_hash   TEXT,
    success             INTEGER,
    created_at_ns       INTEGER NOT NULL,
    ttl_ns              INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wi_unclaimed
    ON work_items(claimed_by, required_tier, reward DESC);
CREATE INDEX IF NOT EXISTS idx_wi_lineage
    ON work_items(lineage_root);

CREATE TABLE IF NOT EXISTS artifacts (
    hash            TEXT PRIMARY KEY,
    data            BLOB NOT NULL,
    signature       TEXT NOT NULL,
    signer_pubkey   TEXT NOT NULL,
    parent_hashes   TEXT NOT NULL,
    timestamp_ns    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS artifact_files (
    hash         TEXT PRIMARY KEY,
    size_bytes   INTEGER NOT NULL,
    stored_at_ns INTEGER NOT NULL
);
"""


def _embedding_to_blob(arr: np.ndarray) -> bytes:
    if arr.dtype != np.float32 or arr.shape != (EMBEDDING_DIM,):
        raise ValueError(
            f"embedding must be float32 shape ({EMBEDDING_DIM},), "
            f"got {arr.dtype} {arr.shape}"
        )
    return arr.tobytes()


def _embedding_from_blob(blob: bytes) -> np.ndarray:
    arr = np.frombuffer(blob, dtype=np.float32)
    if arr.shape != (EMBEDDING_DIM,):
        raise ValueError(f"corrupt embedding blob: shape {arr.shape}")
    # frombuffer returns a read-only view over the bytes; copy so callers
    # can mutate without surprising errors.
    return arr.copy()


def _row_to_work_item(row: sqlite3.Row) -> WorkItem:
    return WorkItem(
        id=row["id"],
        lineage_root=row["lineage_root"],
        parent_id=row["parent_id"],
        description=row["description"],
        desc_embedding=_embedding_from_blob(row["desc_embedding"]),
        reward=row["reward"],
        reward_updated_ns=row["reward_updated_ns"],
        required_tier=row["required_tier"],
        input_hashes=json.loads(row["input_hashes"]),
        output_spec=json.loads(row["output_spec"]),
        streaming_ok=bool(row["streaming_ok"]),
        claimed_by=row["claimed_by"],
        claimed_at_ns=row["claimed_at_ns"],
        claim_hlc_l=row["claim_hlc_l"],
        claim_hlc_c=row["claim_hlc_c"],
        claim_hlc_node=row["claim_hlc_node"],
        completed_at_ns=row["completed_at_ns"],
        output_hash=row["output_hash"],
        icp_envelope_hash=row["icp_envelope_hash"],
        success=None if row["success"] is None else bool(row["success"]),
        created_at_ns=row["created_at_ns"],
        ttl_ns=row["ttl_ns"],
    )


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        hash=row["hash"],
        data=row["data"],
        signature=row["signature"],
        signer_pubkey=row["signer_pubkey"],
        parent_hashes=json.loads(row["parent_hashes"]),
        timestamp_ns=row["timestamp_ns"],
    )


class Blackboard:
    def __init__(self, db_path: str):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._tls = threading.local()
        # When set, all mutating operations route through Raft consensus.
        # Reads stay local. See gyza.network.raft for the wiring.
        self._raft = None
        # Bootstrap schema on a connection that immediately enters tls.
        conn = self._conn()
        conn.executescript(_SCHEMA_SQL)

    def attach_raft(self, raft_node) -> None:
        """Route writes through the supplied Raft node. Reads stay local."""
        self._raft = raft_node

    def attach_artifact_store(self, store) -> None:
        """Wire a content-addressed file store for raw artifact bytes.

        Independent of the Raft / signed-Artifact path — used by
        store_artifact_file / get_artifact_data.
        """
        self._artifact_store = store

    def attach_artifact_client(self, client) -> None:
        """Optional remote-fetch client. get_artifact_data falls back to
        this when the local store doesn't have the requested hash."""
        self._artifact_client = client

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tls, "conn", None)
        if c is not None:
            return c
        c = sqlite3.connect(str(self._db_path))
        c.row_factory = sqlite3.Row
        # Autocommit mode — every method below either issues a single DML
        # (auto-committed) or explicit BEGIN/COMMIT for multi-stmt atomicity.
        c.isolation_level = None
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=10000")
        self._tls.conn = c
        return c

    # ------------------------------------------------------------------
    # Lineage anchor — every work item must root in a registered intent.
    # ------------------------------------------------------------------

    def post_intent(self, goal_spec: dict) -> str:
        intent_id = goal_spec.get("intent_id")
        if not isinstance(intent_id, str) or not intent_id:
            raise ValueError("goal_spec.intent_id must be a non-empty string")
        goal_spec_json = json.dumps(goal_spec)
        created_at_ns = time.time_ns()
        if self._raft is not None:
            self._raft.raft_post_intent(
                intent_id, goal_spec_json, created_at_ns,
                self._raft._identity.pubkey_hex,
                sync=True, timeout=10.0,
            )
            return intent_id
        self.post_intent_direct(intent_id, goal_spec_json, created_at_ns)
        return intent_id

    def post_intent_direct(
        self, intent_id: str, goal_spec_json: str, created_at_ns: int,
    ) -> None:
        # Idempotent on intent_id collision — a concurrent leader-side
        # double-apply during Raft snapshot replay must not crash.
        self._conn().execute(
            "INSERT OR IGNORE INTO human_intents "
            "(intent_id, goal_spec_json, created_at_ns) VALUES (?, ?, ?)",
            (intent_id, goal_spec_json, created_at_ns),
        )

    # ------------------------------------------------------------------
    # Work items
    # ------------------------------------------------------------------

    def post_work_item(self, w: WorkItem) -> bool:
        # Enforce the lineage invariant explicitly. The FK on work_items
        # would also catch this, but raising ValueError up-front gives a
        # clearer error and is what the public contract promises.
        # In Raft mode this check runs on the calling node; the intent
        # was committed by a prior @replicated call so it is guaranteed
        # to be present here.
        row = self._conn().execute(
            "SELECT 1 FROM human_intents WHERE intent_id=?",
            (w.lineage_root,),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"unknown lineage_root: {w.lineage_root!r} not registered "
                f"(call post_intent first)"
            )

        if self._raft is not None:
            from gyza.network.raft import work_item_to_dict
            self._raft.raft_post_work_item(
                work_item_to_dict(w),
                self._raft._identity.pubkey_hex,
                sync=True, timeout=10.0,
            )
            return True

        self.post_work_item_direct(w)
        return True

    def post_work_item_direct(self, w: WorkItem) -> None:
        # Direct path used by Raft apply and by Phase-1 single-node mode.
        # INSERT OR IGNORE keeps the apply idempotent under snapshot replay.
        self._conn().execute(
            """
            INSERT OR IGNORE INTO work_items (
                id, lineage_root, parent_id, description, desc_embedding,
                reward, reward_updated_ns, required_tier, input_hashes,
                output_spec, streaming_ok,
                claimed_by, claimed_at_ns,
                claim_hlc_l, claim_hlc_c, claim_hlc_node,
                completed_at_ns, output_hash, icp_envelope_hash, success,
                created_at_ns, ttl_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                w.id, w.lineage_root, w.parent_id, w.description,
                _embedding_to_blob(w.desc_embedding),
                w.reward, w.reward_updated_ns, w.required_tier,
                json.dumps(w.input_hashes), json.dumps(w.output_spec),
                int(w.streaming_ok),
                w.claimed_by, w.claimed_at_ns,
                w.claim_hlc_l, w.claim_hlc_c, w.claim_hlc_node,
                w.completed_at_ns, w.output_hash, w.icp_envelope_hash,
                None if w.success is None else int(w.success),
                w.created_at_ns, w.ttl_ns,
            ),
        )

    def try_claim(self, work_item_id: str, agent_pubkey: str, hlc: HLC) -> bool:
        l, c, node = hlc.now()
        if self._raft is not None:
            return bool(self._raft.raft_claim_work_item(
                work_item_id, agent_pubkey, l, c, node,
                self._raft._identity.pubkey_hex,
                sync=True, timeout=10.0,
            ))
        return self.try_claim_direct(work_item_id, agent_pubkey, l, c, node)

    def try_claim_direct(
        self,
        work_item_id: str,
        agent_pubkey: str,
        hlc_l: int,
        hlc_c: int,
        hlc_node: str,
    ) -> bool:
        # Derive claimed_at_ns from the HLC's millisecond component so
        # every node records the same value when applying the same
        # Raft entry. (Local time would diverge across replicas.)
        claimed_at_ns = int(hlc_l) * 1_000_000
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT claimed_by FROM work_items WHERE id=?",
                (work_item_id,),
            ).fetchone()
            if row is None or row["claimed_by"] is not None:
                conn.execute("ROLLBACK")
                return False
            cur = conn.execute(
                """
                UPDATE work_items
                SET claimed_by=?, claimed_at_ns=?,
                    claim_hlc_l=?, claim_hlc_c=?, claim_hlc_node=?
                WHERE id=? AND claimed_by IS NULL
                """,
                (agent_pubkey, claimed_at_ns, hlc_l, hlc_c, hlc_node, work_item_id),
            )
            if cur.rowcount == 1:
                conn.execute("COMMIT")
                return True
            conn.execute("ROLLBACK")
            return False
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def complete_work_item(
        self,
        work_item_id: str,
        output_hash: str,
        icp_envelope_hash: str,
        success: bool,
        hlc: HLC,
    ) -> None:
        # Tick the HLC on the calling node for ordering observers.
        hlc.now()
        completed_at_ns = time.time_ns()
        if self._raft is not None:
            self._raft.raft_complete_work_item(
                work_item_id, output_hash, icp_envelope_hash,
                bool(success), completed_at_ns,
                self._raft._identity.pubkey_hex,
                sync=True, timeout=10.0,
            )
            return
        self.complete_work_item_direct(
            work_item_id, output_hash, icp_envelope_hash,
            bool(success), completed_at_ns,
        )

    def complete_work_item_direct(
        self,
        work_item_id: str,
        output_hash: str,
        icp_envelope_hash: str,
        success: bool,
        completed_at_ns: int,
    ) -> None:
        self._conn().execute(
            """
            UPDATE work_items
            SET completed_at_ns=?, output_hash=?, icp_envelope_hash=?, success=?
            WHERE id=?
            """,
            (completed_at_ns, output_hash, icp_envelope_hash,
             int(success), work_item_id),
        )

    def get_unclaimed(self, min_reward: float, tier: int) -> list[WorkItem]:
        # TTL filter: an item whose (created_at_ns + ttl_ns) is in the
        # past is expired and must not be served. We don't garbage-
        # collect here — agents shouldn't pay write latency for
        # expiry sweeps. A future cleanup task can vacuum.
        now_ns = time.time_ns()
        rows = self._conn().execute(
            """
            SELECT * FROM work_items
            WHERE claimed_by IS NULL
              AND reward >= ?
              AND required_tier <= ?
              AND (created_at_ns + ttl_ns) > ?
            ORDER BY reward DESC, created_at_ns ASC
            """,
            (min_reward, tier, now_ns),
        ).fetchall()
        return [_row_to_work_item(r) for r in rows]

    def release_claim(self, work_item_id: str) -> bool:
        """
        Clear the claim on a work item that hasn't completed yet so
        another agent can pick it up. No-op if the item is already
        completed or unclaimed. Returns True iff a claim was cleared.
        """
        cur = self._conn().execute(
            """
            UPDATE work_items
            SET claimed_by=NULL, claimed_at_ns=NULL,
                claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node=''
            WHERE id=? AND claimed_by IS NOT NULL
                  AND completed_at_ns IS NULL
            """,
            (work_item_id,),
        )
        return cur.rowcount == 1

    def get_by_lineage(self, lineage_root: str) -> list[WorkItem]:
        rows = self._conn().execute(
            "SELECT * FROM work_items WHERE lineage_root=? ORDER BY created_at_ns ASC",
            (lineage_root,),
        ).fetchall()
        return [_row_to_work_item(r) for r in rows]

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    def store_artifact(self, a: Artifact) -> None:
        self._conn().execute(
            """
            INSERT OR REPLACE INTO artifacts
                (hash, data, signature, signer_pubkey, parent_hashes, timestamp_ns)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                a.hash, a.data, a.signature, a.signer_pubkey,
                json.dumps(a.parent_hashes), a.timestamp_ns,
            ),
        )

    def get_artifact(self, hash: str) -> Artifact | None:
        row = self._conn().execute(
            "SELECT * FROM artifacts WHERE hash=?", (hash,),
        ).fetchone()
        return _row_to_artifact(row) if row is not None else None

    # ------------------------------------------------------------------
    # Content-addressed file store (Phase-2 artifact exchange path).
    # ------------------------------------------------------------------

    def store_artifact_file(self, data: bytes) -> str:
        """Store raw bytes in the attached ArtifactStore and record a
        bookkeeping row. Returns the BLAKE3 hex hash."""
        store = getattr(self, "_artifact_store", None)
        if store is None:
            raise RuntimeError(
                "no ArtifactStore attached; call attach_artifact_store() first"
            )
        hash_hex = store.store(data)
        size_bytes = store.size_bytes(hash_hex) or len(data)
        self._conn().execute(
            "INSERT OR REPLACE INTO artifact_files "
            "(hash, size_bytes, stored_at_ns) VALUES (?, ?, ?)",
            (hash_hex, size_bytes, time.time_ns()),
        )
        return hash_hex

    def get_artifact_data(self, hash_hex: str) -> bytes | None:
        """Read raw artifact bytes by hash. Falls back to the attached
        ArtifactClient (remote fetch) if the local store doesn't have it."""
        store = getattr(self, "_artifact_store", None)
        if store is not None:
            data = store.get(hash_hex)
            if data is not None:
                return data
        client = getattr(self, "_artifact_client", None)
        if client is None:
            return None
        peer_urls = getattr(self, "_artifact_peer_urls", []) or []
        if not peer_urls:
            return None
        # Synchronous wrapper around the async client. Callers that
        # already live in an event loop should call client.fetch directly.
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # In a running loop — caller should use the async path.
                return None
        except RuntimeError:
            loop = asyncio.new_event_loop()
        return loop.run_until_complete(client.fetch(hash_hex, peer_urls))

    def set_artifact_peer_urls(self, urls: list[str]) -> None:
        self._artifact_peer_urls = list(urls)

    # ------------------------------------------------------------------
    # Internal — used by reward.refresh_rewards
    # ------------------------------------------------------------------

    def _iter_unclaimed_for_refresh(self) -> list[tuple[str, float, int]]:
        rows = self._conn().execute(
            "SELECT id, reward, reward_updated_ns FROM work_items "
            "WHERE claimed_by IS NULL"
        ).fetchall()
        return [(r["id"], r["reward"], r["reward_updated_ns"]) for r in rows]

    def _set_reward(self, work_item_id: str, reward: float, updated_ns: int) -> None:
        self._conn().execute(
            "UPDATE work_items SET reward=?, reward_updated_ns=? WHERE id=?",
            (reward, updated_ns, work_item_id),
        )
