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
import logging
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

from gyza.schema import EMBEDDING_DIM, Artifact, HLC, WorkItem

LOG = logging.getLogger(__name__)


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

-- Phase 3 Session 8.5: persistent ICP envelope log.
-- Before this existed, envelope verification was only possible inside
-- the runner that signed them (via the in-memory _last_envelope chain),
-- so verify_chain_multi_compositor was never invoked at runtime against
-- arriving work — the cross-cluster security boundary was decorative.
-- The log lets any subsequent operation (claim verification, audit,
-- dispute reconstruction) walk a chain by looking up envelopes by their
-- BLAKE3 hash.
--
-- payload_json holds the full canonical-JSON serialization of the
-- ICPEnvelope dataclass; verify_envelope re-derives the digest from
-- the stored fields, so corruption inside the JSON is detected at
-- verify time rather than write time.
CREATE TABLE IF NOT EXISTS icp_envelopes (
    envelope_hash         TEXT PRIMARY KEY,
    intent_id             TEXT NOT NULL,
    action_id             TEXT NOT NULL,
    agent_pubkey          TEXT NOT NULL,
    parent_envelope_hash  TEXT,
    payload_json          TEXT NOT NULL,
    timestamp_ns          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_icp_action ON icp_envelopes(action_id);
CREATE INDEX IF NOT EXISTS idx_icp_intent ON icp_envelopes(intent_id);
CREATE INDEX IF NOT EXISTS idx_icp_parent ON icp_envelopes(parent_envelope_hash);

-- H3's measurand. APPEND-ONLY AND DURABLE for the same reason the envelope log
-- is: an in-process send counter resets on restart, and a cumulative bound
-- whose origin can move is not a bound (ledger artifact #13). `egress_class`
-- is stored as text rather than derived at read time because the
-- classification depends on what was known about the destination AT THE MOMENT
-- OF SENDING -- a peer attested later does not retroactively contain a message
-- already sent to it.
CREATE TABLE IF NOT EXISTS egress_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    egress_class   TEXT NOT NULL,
    channel        TEXT NOT NULL,
    destination    TEXT NOT NULL,
    -- NULLABLE ON PURPOSE. A capability grant has no byte count: one
    -- network-shared sandbox permits arbitrarily many sends this process
    -- cannot see. NULL means UNKNOWN; 0 would claim nothing was sent.
    byte_count     INTEGER,
    timestamp_ns   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_egress_ts ON egress_log(timestamp_ns);
CREATE INDEX IF NOT EXISTS idx_egress_class ON egress_log(egress_class);
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


class ClaimLostError(RuntimeError):
    """Raised when a completion names an owner that no longer holds the claim.

    Distinct from a generic failure because the remedy differs: the work ran,
    its envelope is valid, and only the board row belongs to someone else now.
    """


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
        # expanduser() so a config value like "~/.gyza/blackboard.db"
        # resolves to the user's home instead of creating a literal
        # "~" directory relative to CWD. No-op on absolute or
        # relative-without-tilde paths, so existing callers (tests
        # pass tmp_path; daemons pass resolved paths) are unaffected.
        self._db_path = Path(db_path).expanduser()
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

    def try_claim(self, work_item_id: str, agent_pubkey: str, hlc: HLC,
                  claimant_tier: int | None = None) -> bool:
        """Claim a work item.

        `claimant_tier` is ADVISORY AND SELF-REPORTED. It closes the path Arena
        2 walked -- `get_unclaimed` filters by `required_tier` in its WHERE
        clause, so an agent that learns an item id any OTHER way (gossip, a DAG
        parent, a log line) was never filtered at all -- but it is NOT the
        boundary, because a compromised agent simply passes a higher number.
        The boundary is `AgentRunner._require_attested_tier`, which reads the
        COMPOSITOR-SIGNED manifest rather than an argument.

        Saying that plainly is the point. A self-reported check described as an
        authorization boundary would be the same overclaim as the "kernel-
        enforced" sandbox: true-sounding, and load-bearing for nobody.

        `None` means "did not say" and fails closed to tier 0, matching the
        enforcement record's positive-declaration rule.
        """
        l, c, node = hlc.now()
        if self._raft is not None:
            # The tier is checked LOCALLY, before proposing. The Raft state
            # machine replicates the claim, not the claimant's attestation, so
            # a replica cannot re-derive this -- another reason it is advisory.
            if not self._tier_permits(work_item_id, claimant_tier):
                return False
            return bool(self._raft.raft_claim_work_item(
                work_item_id, agent_pubkey, l, c, node,
                self._raft._identity.pubkey_hex,
                sync=True, timeout=10.0,
            ))
        return self.try_claim_direct(work_item_id, agent_pubkey, l, c, node,
                                     claimant_tier=claimant_tier)

    def _tier_permits(self, work_item_id: str,
                      claimant_tier: int | None) -> bool:
        row = self._conn().execute(
            "SELECT required_tier FROM work_items WHERE id=?",
            (work_item_id,),
        ).fetchone()
        if row is None:
            return True          # missing item is the caller's problem, not this check's
        return int(row["required_tier"] or 0) <= int(claimant_tier or 0)

    def try_claim_direct(
        self,
        work_item_id: str,
        agent_pubkey: str,
        hlc_l: int,
        hlc_c: int,
        hlc_node: str,
        claimant_tier: int | None = None,
    ) -> bool:
        # Derive claimed_at_ns from the HLC's millisecond component so
        # every node records the same value when applying the same
        # Raft entry. (Local time would diverge across replicas.)
        claimed_at_ns = int(hlc_l) * 1_000_000
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT claimed_by, required_tier FROM work_items WHERE id=?",
                (work_item_id,),
            ).fetchone()
            if row is None or row["claimed_by"] is not None:
                conn.execute("ROLLBACK")
                return False
            # Advisory tier filter -- see `try_claim`. Inside the same
            # transaction as the claimed_by read so it cannot race it.
            if int(row["required_tier"] or 0) > int(claimant_tier or 0):
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

    def merge_claim_direct(
        self,
        work_item_id: str,
        agent_pubkey: str,
        hlc_l: int,
        hlc_c: int,
        hlc_node: str,
    ) -> bool:
        """
        Idempotently merge a remotely-asserted claim into the local row
        using the HLC total order ``(l, c, node_id)`` as LWW key.

        Differs from ``try_claim_direct`` in two places:

        * Accepts a claim *over* an existing claim if the incoming HLC
          tuple is greater than the current one (cross-cluster gossip
          case where two nodes raced and the loser sees the winner's
          delta after its own apply).
        * Refuses to touch a row that has been completed: completion is
          monotonic and overwriting the claim of a finished item would
          corrupt the historical record. Returns ``False``.

        Returns ``True`` iff the row's claim fields were updated.

        Caller is responsible for advancing its own HLC via
        ``HLC.recv(hlc_l, hlc_c, hlc_node)`` before issuing the next
        local claim — without that step, a subsequent local claim could
        produce an HLC tuple lex-smaller than the just-merged remote
        claim and fail the total-order invariant.
        """
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT claimed_by, claim_hlc_l, claim_hlc_c, claim_hlc_node, "
                "completed_at_ns FROM work_items WHERE id=?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                # Item not present locally — caller should apply the
                # work_item record first (gossip deltas always carry
                # creation alongside claim).
                conn.execute("ROLLBACK")
                return False
            if row["completed_at_ns"] is not None:
                conn.execute("ROLLBACK")
                return False

            # LWW: incoming wins iff its HLC is strictly greater than
            # the current one in lex order. Unclaimed rows have HLC
            # (0, 0, "") which compares smaller than any real HLC.
            cur_l = row["claim_hlc_l"] or 0
            cur_c = row["claim_hlc_c"] or 0
            cur_node = row["claim_hlc_node"] or ""
            if (hlc_l, hlc_c, hlc_node) <= (cur_l, cur_c, cur_node):
                conn.execute("ROLLBACK")
                return False

            claimed_at_ns = int(hlc_l) * 1_000_000
            conn.execute(
                """
                UPDATE work_items
                SET claimed_by=?, claimed_at_ns=?,
                    claim_hlc_l=?, claim_hlc_c=?, claim_hlc_node=?
                WHERE id=?
                """,
                (agent_pubkey, claimed_at_ns,
                 hlc_l, hlc_c, hlc_node, work_item_id),
            )
            conn.execute("COMMIT")
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def merge_completion_direct(
        self,
        work_item_id: str,
        output_hash: str,
        icp_envelope_hash: str,
        success: bool,
        completed_at_ns: int,
    ) -> bool:
        """
        Apply a completion record only if the row is not already
        completed (monotonic — first writer wins on each replica).

        Returns ``True`` iff the row was updated.

        Why first-writer-wins rather than newest-writer-wins: a stale
        node could replay an old completion long after a more recent
        one has been applied. Refusing to overwrite ensures the
        ``completed_at_ns / output_hash / icp_envelope_hash`` triple
        stays stable once any node has accepted a completion.
        Convergence still holds because all nodes are exchanging the
        same set of completion deltas — they will each settle on
        whichever completion was first to arrive locally. Disagreements
        across nodes about *which* completion won are rare (would
        require concurrent independent completions of the same item)
        and resolved at the application layer via ICP-chain reconciliation.
        """
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT completed_at_ns FROM work_items WHERE id=?",
                (work_item_id,),
            ).fetchone()
            if row is None or row["completed_at_ns"] is not None:
                conn.execute("ROLLBACK")
                return False
            conn.execute(
                """
                UPDATE work_items
                SET completed_at_ns=?, output_hash=?, icp_envelope_hash=?, success=?
                WHERE id=? AND completed_at_ns IS NULL
                """,
                (completed_at_ns, output_hash, icp_envelope_hash,
                 int(success), work_item_id),
            )
            conn.execute("COMMIT")
            return True
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
        expected_owner: str | None = None,
    ) -> None:
        """Mark an item complete. `expected_owner` REFUSES a completion by
        anyone else.

        IT USED TO BE `WHERE id=?` AND NOTHING ELSE, so any party could
        complete any item, including one it had never claimed. That is
        harmless while a claim is never taken away -- and it stops being
        harmless the moment claims become LEASES, because a slow-but-alive
        runner whose lease expired could then overwrite the result of whoever
        legitimately reclaimed the item, silently and last-write-wins.
        So this had to land BEFORE the reaper, not alongside it.

        `expected_owner=None` preserves the old behaviour and is what the Raft
        apply path uses: a replica applying a committed completion must not
        re-litigate ownership that consensus already decided.
        """
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
            bool(success), completed_at_ns, expected_owner=expected_owner,
        )

    def complete_work_item_direct(
        self,
        work_item_id: str,
        output_hash: str,
        icp_envelope_hash: str,
        success: bool,
        completed_at_ns: int,
        expected_owner: str | None = None,
    ) -> None:
        if expected_owner is None:
            self._conn().execute(
                """
                UPDATE work_items
                SET completed_at_ns=?, output_hash=?, icp_envelope_hash=?,
                    success=?
                WHERE id=?
                """,
                (completed_at_ns, output_hash, icp_envelope_hash,
                 int(success), work_item_id),
            )
            return
        cur = self._conn().execute(
            """
            UPDATE work_items
            SET completed_at_ns=?, output_hash=?, icp_envelope_hash=?, success=?
            WHERE id=? AND claimed_by=?
            """,
            (completed_at_ns, output_hash, icp_envelope_hash,
             int(success), work_item_id, expected_owner),
        )
        if cur.rowcount != 1:
            # RAISE RATHER THAN RETURN FALSE. A completion that silently did
            # not apply leaves a signed envelope describing work the board does
            # not record, and the caller carries on believing it landed.
            raise ClaimLostError(
                f"refusing to complete {work_item_id}: it is no longer claimed "
                f"by {expected_owner[:16]}. Its lease expired and another "
                f"runner reclaimed it, or the claim was released. The work was "
                f"done and its envelope is valid -- what is refused is "
                f"overwriting whoever holds the item now.")

    #: How long a claim is held before another runner may reclaim it.
    #:
    #: A CLAIM IS A LEASE, NOT A DEED. Before 2026-08-21 it was a deed: a
    #: runner that died holding one leaked its item permanently, because
    #: `release_claim` has exactly one caller (the in-process failure path) and
    #: the TTL filter in `get_unclaimed` only applies to rows that are ALREADY
    #: unclaimed. A claimed row was never served again and never expired.
    #:
    #: That is survivable while a crash is rare and fatal to the node anyway.
    #: It stops being survivable the moment runners are supervised and
    #: restarted, because then a crash is ROUTINE -- so this had to land before
    #: process supervision, not after it.
    #:
    #: SIZED FROM THE LONGEST LEGITIMATE ACTION, not from taste: the sandbox
    #: caps an action at `max_cpu_seconds=300`, so 900 s is three times the
    #: worst case a live runner can present. Too short steals work from slow
    #: runners; too long leaves crashed work unavailable. Three times is the
    #: margin, and it is stated so a future change is a decision rather than a
    #: nudge.
    CLAIM_LEASE_NS = 900 * 1_000_000_000

    def reclaim_expired_claims(self, lease_ns: int | None = None,
                               now_ns: int | None = None) -> list[str]:
        """Release claims whose lease has expired. Returns the ids reclaimed.

        NOT SILENT. Each reclaim is logged at WARNING, because it means work
        somebody claimed is being taken from them -- if that happens routinely
        the lease is mis-sized and an operator needs to see it, and if it never
        happens the log stays empty and costs nothing.

        Completed items are excluded: a finished row keeps its `claimed_by` as
        the record of who did the work, and reclaiming it would erase
        attribution for no benefit.
        """
        lease = int(self.CLAIM_LEASE_NS if lease_ns is None else lease_ns)
        now = int(time.time_ns() if now_ns is None else now_ns)
        cutoff = now - lease
        rows = self._conn().execute(
            """
            SELECT id, claimed_by FROM work_items
            WHERE claimed_by IS NOT NULL
              AND completed_at_ns IS NULL
              AND claimed_at_ns IS NOT NULL
              AND claimed_at_ns < ?
            """,
            (cutoff,),
        ).fetchall()
        reclaimed = []
        for r in rows:
            cur = self._conn().execute(
                """
                UPDATE work_items
                SET claimed_by=NULL, claimed_at_ns=NULL
                WHERE id=? AND claimed_by=? AND completed_at_ns IS NULL
                """,
                (r["id"], r["claimed_by"]),
            )
            if cur.rowcount == 1:
                reclaimed.append(r["id"])
                LOG.warning(
                    "[blackboard] reclaimed %s from %s: claim lease expired "
                    "(%.0fs). The holder crashed, or is slower than the lease.",
                    r["id"][:16], (r["claimed_by"] or "?")[:16],
                    lease / 1e9)
        if reclaimed:
            self._conn().commit()
        return reclaimed

    def get_unclaimed(self, min_reward: float, tier: int,
                      limit: int | None = None) -> list[WorkItem]:
        """Unclaimed, live items at or below `tier`, best-rewarded first.

        `limit` BOUNDS THE FETCH, and the default of None (unbounded) is kept
        only for backwards compatibility -- it is the wrong default for a
        polling loop. Measured 2026-08-23: with no limit, every agent on every
        poll materialises the ENTIRE unclaimed backlog, each row carrying a
        384-float embedding, and then scores all of them. Cost is O(backlog)
        per poll per agent, so system cost is O(agents x backlog) per interval
        and it grows as the backlog grows. That, not lock contention, is what
        capped throughput at ~55 claims/s with a 99% claim win rate -- the
        agents were not fighting, they were each re-reading the whole board.
        """
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
            LIMIT ?
            """,
            (min_reward, tier, now_ns, -1 if limit is None else int(limit)),
        ).fetchall()
        items = [_row_to_work_item(r) for r in rows]

        # DEPENDENCY GATE. A combiner must not be served while any sibling is
        # still outstanding, or it would combine a partial result and sign it.
        # Filtered here rather than in SQL because `output_spec` is JSON; the
        # cost is paid only for rows that actually declare COMBINE_KIND, and
        # combiners are rare relative to leaves.
        ready = []
        for w in items:
            spec = w.output_spec if isinstance(w.output_spec, dict) else {}
            if spec.get("kind") != self.COMBINE_KIND or not w.parent_id:
                ready.append(w)
                continue
            if not self.pending_siblings(w):
                ready.append(w)
        return ready

    def pending_siblings(self, item: WorkItem) -> list[str]:
        """Ids of this item's siblings that have not completed. A combiner
        with a non-empty result is not yet servable."""
        if not item.parent_id:
            return []
        return [c.id for c in self.children_of(item.parent_id)
                if c.id != item.id and c.completed_at_ns is None]

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

    #: `output_spec["kind"]` marking an item that COMBINES its siblings'
    #: results. Such an item is not servable until every other child of its
    #: parent has completed. Carried in `output_spec` rather than a new column
    #: so decomposition needs no schema migration.
    COMBINE_KIND = "combine"

    def get_work_item(self, work_item_id: str) -> WorkItem | None:
        row = self._conn().execute(
            "SELECT * FROM work_items WHERE id=?", (work_item_id,),
        ).fetchone()
        return _row_to_work_item(row) if row is not None else None

    def children_of(self, parent_id: str) -> list[WorkItem]:
        rows = self._conn().execute(
            "SELECT * FROM work_items WHERE parent_id=? ORDER BY created_at_ns",
            (parent_id,),
        ).fetchall()
        return [_row_to_work_item(r) for r in rows]

    def lineage_depth(self, work_item_id: str, cap: int = 64) -> int:
        """Number of parent hops above this item. 0 for a root.

        `cap` is a CYCLE GUARD, not a policy: `parent_id` is written by agents
        now, so a malformed or hostile graph must not be able to hang a walk.
        The policy bound is the caller's.
        """
        depth, cur, seen = 0, self.get_work_item(work_item_id), {work_item_id}
        while cur is not None and cur.parent_id and depth < cap:
            if cur.parent_id in seen:
                break                      # cycle; stop rather than loop
            seen.add(cur.parent_id)
            cur = self.get_work_item(cur.parent_id)
            depth += 1
        return depth

    def get_by_lineage(self, lineage_root: str) -> list[WorkItem]:
        rows = self._conn().execute(
            "SELECT * FROM work_items WHERE lineage_root=? ORDER BY created_at_ns ASC",
            (lineage_root,),
        ).fetchall()
        return [_row_to_work_item(r) for r in rows]

    # ------------------------------------------------------------------
    # ICP envelope log (Phase 3 Session 8.5)
    # ------------------------------------------------------------------
    #
    # Persistent log of every envelope this node has signed (and, when
    # cross-cluster envelope gossip is wired, every envelope it has
    # observed). Stored verbatim as canonical JSON so verify_envelope
    # can re-derive the digest from the same field order that produced
    # the signature.
    #
    # Why a separate table from work_items: work_items.icp_envelope_hash
    # is the *pointer* — useful for cross-referencing — but the actual
    # envelope payload (with signature, agent_pubkey, parent link) is
    # what verification needs. Embedding the payload in work_items would
    # bloat the table and conflate "the work happened" with "the
    # cryptographic proof of it."

    def store_envelope(self, envelope) -> str:
        """
        Persist an ICPEnvelope. Returns the envelope hash. Idempotent
        on hash collision (UPSERT) — re-storing the same envelope is a
        no-op rather than a constraint violation.
        """
        from gyza.icp import compute_envelope_hash
        from dataclasses import asdict
        env_hash = compute_envelope_hash(envelope)
        payload = json.dumps(
            asdict(envelope), sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        self._conn().execute(
            """
            INSERT OR REPLACE INTO icp_envelopes
                (envelope_hash, intent_id, action_id, agent_pubkey,
                 parent_envelope_hash, payload_json, timestamp_ns)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                env_hash, envelope.intent_id, envelope.action_id,
                envelope.agent_pubkey, envelope.parent_envelope_hash,
                payload, envelope.timestamp_ns,
            ),
        )
        return env_hash

    def count_envelopes_since(self, origin_ns: int = 0) -> int:
        """Signed envelopes recorded at or after `origin_ns`.

        H6's measurand, and it is DERIVED rather than counted in memory on
        purpose. An in-process counter resets on restart, which is a cumulative
        bound whose origin moves -- ledger artifact #13, the defect that bought
        unlimited drain. The envelope log is append-only and durable, so folding
        it cannot be reset by restarting the process.
        """
        row = self._conn().execute(
            "SELECT COUNT(*) AS n FROM icp_envelopes WHERE timestamp_ns >= ?",
            (int(origin_ns),),
        ).fetchone()
        return int(row["n"] if row is not None else 0)

    def count_agent_envelopes_since(self, agent_pubkey: str,
                                    origin_ns: int = 0) -> int:
        """Signed envelopes by ONE agent since `origin_ns`.

        `count_envelopes_since` folds the whole node; a per-principal rate cap
        needs the per-principal fold, and using the node-wide count would make
        one busy agent exhaust every other agent's budget. Derived from the
        append-only log for the same reason H6 is: an in-process counter resets
        on restart, and a cumulative bound whose origin can move is not a bound.
        """
        row = self._conn().execute(
            "SELECT COUNT(*) AS n FROM icp_envelopes "
            "WHERE agent_pubkey = ? AND timestamp_ns >= ?",
            (agent_pubkey, int(origin_ns)),
        ).fetchone()
        return int(row["n"] if row is not None else 0)

    def egress_by_channel_since(self, origin_ns: int = 0) -> "dict[str, int]":
        """H3's count split by channel, for the ONE question that decides
        whether an attestation source is worth building.

        Only `send_message` carries a single peer destination. `publish_agent`
        and `publish_attestation` are DHT puts landing on the k closest nodes;
        `publish_delta` fans out to a gossip topic. For those three, "is the
        destination attested?" IS NOT A WELL-FORMED QUESTION at send time, so
        they can never be reclassified out of the exit count no matter how
        complete attestation coverage becomes.

        That makes the peer-addressed share the CEILING on H3's headline
        property -- "the only declared quantity that shrinks as the mesh
        grows". Reporting the ceiling beside the count is the same discipline
        as reporting FPR beside TPR: a property that can only ever apply to a
        fraction of traffic must say which fraction.
        """
        from gyza.containment.egress import EgressClass
        rows = self._conn().execute(
            "SELECT channel, COUNT(*) AS n FROM egress_log "
            "WHERE timestamp_ns >= ? AND egress_class IN (?, ?) "
            "GROUP BY channel",
            (int(origin_ns), *EgressClass.MESH_EXIT),
        ).fetchall()
        return {r["channel"]: int(r["n"]) for r in rows}

    def count_grants_since(self, origin_ns: int = 0) -> int:
        """Capability grants permitting UNCOUNTABLE egress, since `origin_ns`.

        DELIBERATELY SEPARATE from `count_egress_since`. A grant is not a send:
        one network-shared sandbox permits arbitrarily many sends that nothing
        in this process can observe. A single accessor returning grants+sends
        would let a caller add two different units and report the sum as harm.
        """
        from gyza.containment.egress import EgressClass
        row = self._conn().execute(
            "SELECT COUNT(*) AS n FROM egress_log "
            "WHERE timestamp_ns >= ? AND egress_class = ?",
            (int(origin_ns), EgressClass.UNBOUNDED_GRANT),
        ).fetchone()
        return int(row["n"] if row is not None else 0)

    def mesh_exit_bytes_since(self, origin_ns: int = 0,
                              classes: "tuple[str, ...] | list[str] | None" = None
                              ) -> int:
        """Bytes that left via the given egress classes at or after `origin_ns`.

        H3's measurand once the quantity became a RATE. The COUNT of sends is
        mute -- R-EVID measured a benign node and an exfiltrating one emitting
        exactly 1.000 sends per action, so the count carries zero evidence and
        no level over it can separate them. Bytes carry evidence.

        SUMS ONLY NON-NULL byte counts, and that is safe here rather than
        merely convenient: `record_egress` REFUSES a MESH_EXIT row without a
        byte count, so a NULL can only belong to `UNBOUNDED_GRANT`, which is a
        different unit and is excluded by the caller's class filter. If that
        refusal is ever relaxed this sum silently understates disclosure, which
        is the reassuring direction -- hence the assertion below rather than a
        comment.
        """
        cs = list(classes) if classes is not None else None
        sql = ("SELECT COALESCE(SUM(byte_count), 0) AS b, "
               "SUM(byte_count IS NULL) AS nulls "
               "FROM egress_log WHERE timestamp_ns >= ?")
        args: list[object] = [int(origin_ns)]
        if cs is not None:
            if not cs:
                return 0
            sql += f" AND egress_class IN ({','.join('?' * len(cs))})"
            args += cs
        row = self._conn().execute(sql, tuple(args)).fetchone()
        if row["nulls"]:
            raise ValueError(
                f"{row['nulls']} row(s) in this egress class set carry a NULL "
                f"byte_count, so the byte total is UNDEFINED rather than "
                f"{row['b']}. Reading a NULL as zero would understate "
                f"disclosure.")
        return int(row["b"])

    def record_egress(self, egress_class: str, channel: str, destination: str,
                      byte_count: int | None,
                      timestamp_ns: int | None = None) -> None:
        """Append one egress event. Called at the moment of sending.

        `egress_class` is one of `gyza.containment.egress.EgressClass`; it is
        passed in rather than inferred here because the blackboard does not know
        the attestation state of a peer and should not learn it. The caller
        classifies, this records.
        """
        from gyza.containment.egress import EgressClass
        if egress_class not in EgressClass.ALL:
            raise ValueError(
                f"unknown egress class {egress_class!r}; an unclassified send "
                f"is not a measurement (must be one of {sorted(EgressClass.ALL)})")
        ts = int(time.time_ns() if timestamp_ns is None else timestamp_ns)
        # NULL, not 0, when the volume is unknowable. Writing 0 would claim
        # nothing left the machine.
        n = None if byte_count is None else int(byte_count)
        # A MESH_EXIT row with no byte count makes any byte-denominated harm
        # measure UNDEFINED over this log, and the natural repair -- treat the
        # NULL as 0 -- understates disclosure, which is the reassuring
        # direction and therefore the one that does not get questioned.
        #
        # `peer_send` and `outside_send` both annotate `byte_count: int`, and
        # every current caller passes one. That annotation is a type hint, not
        # a check, and this method has always accepted None from anywhere; an
        # unenforced invariant is an assumption. R-H3L needed the sum to be
        # well-defined to measure anything at all, so the assumption becomes a
        # check here. UNBOUNDED_GRANT is exempt by design: its volume is
        # genuinely unknowable and it is excluded from MESH_EXIT for that
        # reason.
        if n is None and egress_class in EgressClass.MESH_EXIT:
            raise ValueError(
                f"MESH_EXIT class {egress_class!r} requires a byte_count: a "
                f"NULL makes byte-denominated harm undefined over this log, "
                f"and reading it as 0 would understate disclosure. Only "
                f"UNBOUNDED_GRANT may omit it.")
        self._conn().execute(
            "INSERT INTO egress_log "
            "(egress_class, channel, destination, byte_count, timestamp_ns) "
            "VALUES (?,?,?,?,?)",
            (egress_class, channel, destination, n, ts),
        )
        self._conn().commit()

    def count_egress_since(self, origin_ns: int = 0,
                           classes: "tuple[str, ...] | list[str] | None" = None) -> int:
        """Egress events at or after `origin_ns`, optionally restricted to
        `classes`. Derived from the append-only log, never counted in memory.

        `classes=None` means EVERY class, which is deliberately NOT the same as
        H3's measurand: H3 excludes sends to attested peers, and a caller that
        wants H3 must say so. A default that silently included them would make
        the federated case indistinguishable from the exit case.
        """
        sql = "SELECT COUNT(*) AS n FROM egress_log WHERE timestamp_ns >= ?"
        args: list[object] = [int(origin_ns)]
        if classes is not None:
            cs = list(classes)
            if not cs:
                return 0
            sql += f" AND egress_class IN ({','.join('?' * len(cs))})"
            args += cs
        row = self._conn().execute(sql, tuple(args)).fetchone()
        return int(row["n"] if row is not None else 0)

    def get_envelope(self, envelope_hash: str):
        """Retrieve an ICPEnvelope by hash, or None if absent."""
        from gyza.icp import ICPEnvelope
        row = self._conn().execute(
            "SELECT payload_json FROM icp_envelopes WHERE envelope_hash=?",
            (envelope_hash,),
        ).fetchone()
        if row is None:
            return None
        d = json.loads(row["payload_json"])
        return ICPEnvelope(**d)

    def get_envelope_for_action(self, action_id: str):
        """Retrieve the envelope that signed the completion of a given
        work item. Returns None if no envelope is logged. Returns the
        most recent envelope if multiple exist (shouldn't happen in
        normal flow, but a re-execution after release could produce
        two; LWW by timestamp is the right policy)."""
        from gyza.icp import ICPEnvelope
        row = self._conn().execute(
            "SELECT payload_json FROM icp_envelopes WHERE action_id=? "
            "ORDER BY timestamp_ns DESC LIMIT 1",
            (action_id,),
        ).fetchone()
        if row is None:
            return None
        return ICPEnvelope(**json.loads(row["payload_json"]))

    def reconstruct_dag(self, intent_id: str) -> "list":
        """
        Return every ICP envelope logged under ``intent_id`` — the node
        set of that workflow's provenance DAG.

        Unlike ``reconstruct_chain`` (which walks ``parent_id`` to a
        single linear path, one envelope per work item), this returns the
        full multi-parent graph's nodes so ``gyza.icp.verify_dag`` can
        rebuild the edges (causal spine + data dependencies) and validate
        fan-out / fork / fan-in as one structure. Storage only — the
        caller verifies, keeping storage and verification separate.

        Uses the ``idx_icp_intent`` index. Order is by ``timestamp_ns``
        for stable iteration; verify_dag re-derives a deterministic
        content-addressed topological order regardless.
        """
        from gyza.icp import ICPEnvelope
        rows = self._conn().execute(
            "SELECT payload_json FROM icp_envelopes WHERE intent_id=? "
            "ORDER BY timestamp_ns ASC",
            (intent_id,),
        ).fetchall()
        return [ICPEnvelope(**json.loads(r["payload_json"])) for r in rows]

    def reconstruct_chain(self, work_item_id: str) -> "tuple[list, str]":
        """
        Walk parent_id back from ``work_item_id`` to its lineage_root,
        collecting one envelope per ancestor. Returns
        ``(envelopes_root_first, missing_action_id_or_empty)``.

        - On full reconstruction, the second element is "" and the
          first is a list of ICPEnvelope ordered root → leaf.
        - If any ancestor has no envelope in the log (e.g. a remote
          envelope that hasn't been gossiped to us, or a parent that
          hasn't completed yet), the second element is that ancestor's
          action_id and the first is the partial chain we DID have.

        Callers that need a strict guarantee should treat
        ``missing != ""`` as verification failure.
        """
        # Walk: find the work item, climb parent_id until None.
        ancestors: list[str] = []
        cursor_id: str | None = work_item_id
        # Bound the climb so a corrupted parent cycle (shouldn't happen
        # under the schema's FK but defense-in-depth) doesn't loop.
        for _ in range(10_000):
            if cursor_id is None:
                break
            row = self._conn().execute(
                "SELECT id, parent_id FROM work_items WHERE id=?",
                (cursor_id,),
            ).fetchone()
            if row is None:
                # Unknown work item in chain — caller should treat as missing.
                return [], cursor_id
            ancestors.append(cursor_id)
            cursor_id = row["parent_id"]
        else:
            raise RuntimeError(
                f"chain walk exceeded depth limit starting at {work_item_id}"
            )
        # ancestors is leaf → root; reverse to get root → leaf.
        ancestors.reverse()
        chain = []
        for action_id in ancestors:
            env = self.get_envelope_for_action(action_id)
            if env is None:
                return chain, action_id
            chain.append(env)
        return chain, ""

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
