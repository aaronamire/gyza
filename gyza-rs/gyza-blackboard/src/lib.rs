//! SQLite-backed blackboard for Gyza.
//!
//! Ports the core surface of `gyza/blackboard.py`. Tables:
//!
//!   - `human_intents` — top-level user-signed goal specs
//!   - `work_items` — agent-claimable units of work
//!   - `icp_envelopes` — append-only signed provenance log
//!
//! Skipped from this port (deferred to a follow-up): `artifacts`,
//! `artifact_files`. The core flow (intent → work item → claim →
//! complete → envelope) is what's needed first.
//!
//! ## Concurrency
//!
//! The Python implementation uses thread-local SQLite connections.
//! In Rust we wrap a single `Connection` in a `Mutex` — SQLite's WAL
//! mode handles concurrent readers fine, but rusqlite's
//! `Connection` isn't `Sync`. Mutex serializes Rust-side access; the
//! WAL writer lock serializes SQLite-side writes. Either way reads
//! are concurrent in practice when we eventually move to a pool.
//!
//! ## Schema compatibility with Python
//!
//! Schema matches `gyza/blackboard.py::_SCHEMA_SQL`. A Rust-written
//! database can be read by Python and vice versa. This is the
//! foundation for v1↔v2 daemon coexistence during the vNext
//! migration.

use gyza_core::{EMBEDDING_DIM, WorkItem};
use gyza_icp::{SignedEnvelope, envelope_hash};
use rusqlite::{Connection, OptionalExtension, params};
use std::path::Path;
use std::sync::Mutex;

/// Errors arising from blackboard operations.
#[derive(Debug, thiserror::Error)]
pub enum BlackboardError {
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("json (de)serialization error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("malformed embedding blob: length {got} bytes, expected {expected}")]
    BadEmbeddingBlob { expected: usize, got: usize },
    #[error("envelope encoding error: {0}")]
    Envelope(#[from] gyza_icp::IcpError),
    #[error("work_item.id collision: {id}")]
    WorkItemIdCollision { id: String },
}

/// Schema SQL. Matches `gyza/blackboard.py::_SCHEMA_SQL` for the
/// tables we port in this session.
const SCHEMA_SQL: &str = r#"
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
"#;

/// Encode a 384-element f32 embedding to a 1536-byte little-endian
/// BLOB. Matches Python's `np.ndarray.tobytes()` for float32 LE.
fn embedding_to_blob(emb: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(emb.len() * 4);
    for v in emb {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out
}

/// Decode a 1536-byte BLOB to a 384-element f32 Vec.
fn embedding_from_blob(blob: &[u8]) -> Result<Vec<f32>, BlackboardError> {
    let expected = EMBEDDING_DIM * 4;
    if blob.len() != expected {
        return Err(BlackboardError::BadEmbeddingBlob {
            expected,
            got: blob.len(),
        });
    }
    let mut out = Vec::with_capacity(EMBEDDING_DIM);
    for chunk in blob.chunks_exact(4) {
        let arr: [u8; 4] = chunk.try_into().expect("chunk_exact gives 4 bytes");
        out.push(f32::from_le_bytes(arr));
    }
    Ok(out)
}

/// SQLite-backed blackboard.
///
/// Thread-safe via `Mutex<Connection>`. Open one per process (or per
/// agent); not designed for sharing across processes.
pub struct Blackboard {
    conn: Mutex<Connection>,
}

impl Blackboard {
    /// Open a blackboard at `path`. Creates the file + schema if
    /// missing. Enables WAL mode for concurrent readers.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, BlackboardError> {
        let conn = Connection::open(path)?;
        conn.execute_batch("PRAGMA journal_mode=WAL;")?;
        conn.execute_batch(SCHEMA_SQL)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    /// Open an in-memory blackboard. Useful for tests.
    pub fn open_in_memory() -> Result<Self, BlackboardError> {
        let conn = Connection::open_in_memory()?;
        conn.execute_batch(SCHEMA_SQL)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    /// Post a new top-level intent. Returns the intent_id (caller
    /// supplied — typically a UUID7).
    pub fn post_intent(
        &self,
        intent_id: &str,
        goal_spec: &serde_json::Value,
        created_at_ns: i64,
    ) -> Result<(), BlackboardError> {
        let json = serde_json::to_string(goal_spec)?;
        let conn = self.conn.lock().expect("blackboard mutex");
        conn.execute(
            "INSERT INTO human_intents (intent_id, goal_spec_json, created_at_ns) \
             VALUES (?1, ?2, ?3)",
            params![intent_id, json, created_at_ns],
        )?;
        Ok(())
    }

    /// Post a new work item. Returns `Ok(())` on success;
    /// `WorkItemIdCollision` if an item with this id already exists.
    pub fn post_work_item(&self, w: &WorkItem) -> Result<(), BlackboardError> {
        let conn = self.conn.lock().expect("blackboard mutex");
        let exists: bool = conn
            .query_row(
                "SELECT 1 FROM work_items WHERE id = ?1",
                params![w.id],
                |_| Ok(true),
            )
            .optional()?
            .unwrap_or(false);
        if exists {
            return Err(BlackboardError::WorkItemIdCollision { id: w.id.clone() });
        }
        let emb_blob = embedding_to_blob(&w.desc_embedding);
        let input_hashes_json = serde_json::to_string(&w.input_hashes)?;
        let output_spec_json = serde_json::to_string(&w.output_spec)?;
        conn.execute(
            "INSERT INTO work_items (\
                id, lineage_root, parent_id, description, desc_embedding, \
                reward, reward_updated_ns, required_tier, input_hashes, output_spec, \
                streaming_ok, claimed_by, claimed_at_ns, claim_hlc_l, claim_hlc_c, claim_hlc_node, \
                completed_at_ns, output_hash, icp_envelope_hash, success, \
                created_at_ns, ttl_ns\
             ) VALUES (\
                ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, \
                ?17, ?18, ?19, ?20, ?21, ?22\
             )",
            params![
                w.id,
                w.lineage_root,
                w.parent_id,
                w.description,
                emb_blob,
                w.reward,
                w.reward_updated_ns,
                w.required_tier,
                input_hashes_json,
                output_spec_json,
                w.streaming_ok as i32,
                w.claimed_by,
                w.claimed_at_ns,
                w.claim_hlc_l,
                w.claim_hlc_c,
                w.claim_hlc_node,
                w.completed_at_ns,
                w.output_hash,
                w.icp_envelope_hash,
                w.success.map(|b| b as i32),
                w.created_at_ns,
                w.ttl_ns,
            ],
        )?;
        Ok(())
    }

    /// Claim a work item atomically. Returns `Ok(true)` on success,
    /// `Ok(false)` if another claim won the race.
    pub fn claim_work_item(
        &self,
        work_item_id: &str,
        agent_id: &str,
        claimed_at_ns: i64,
        hlc_l: i64,
        hlc_c: i64,
        hlc_node: &str,
    ) -> Result<bool, BlackboardError> {
        let conn = self.conn.lock().expect("blackboard mutex");
        let affected = conn.execute(
            "UPDATE work_items SET \
                claimed_by = ?1, claimed_at_ns = ?2, \
                claim_hlc_l = ?3, claim_hlc_c = ?4, claim_hlc_node = ?5 \
             WHERE id = ?6 AND claimed_by IS NULL",
            params![
                agent_id,
                claimed_at_ns,
                hlc_l,
                hlc_c,
                hlc_node,
                work_item_id
            ],
        )?;
        Ok(affected == 1)
    }

    /// Mark a work item completed. Returns `Ok(true)` on success,
    /// `Ok(false)` if no row matched (e.g., already completed or
    /// unknown id).
    pub fn complete_work_item(
        &self,
        work_item_id: &str,
        completed_at_ns: i64,
        output_hash: &str,
        icp_envelope_hash: &str,
        success: bool,
    ) -> Result<bool, BlackboardError> {
        let conn = self.conn.lock().expect("blackboard mutex");
        let affected = conn.execute(
            "UPDATE work_items SET \
                completed_at_ns = ?1, output_hash = ?2, \
                icp_envelope_hash = ?3, success = ?4 \
             WHERE id = ?5 AND completed_at_ns IS NULL",
            params![
                completed_at_ns,
                output_hash,
                icp_envelope_hash,
                success as i32,
                work_item_id,
            ],
        )?;
        Ok(affected == 1)
    }

    /// Return all unclaimed work items meeting tier+reward filters
    /// and whose TTL hasn't expired relative to `now_ns`.
    ///
    /// Order: highest reward first (matches Python's
    /// `ORDER BY reward DESC`).
    pub fn get_unclaimed(
        &self,
        min_reward: f32,
        max_tier: i32,
        now_ns: i64,
    ) -> Result<Vec<WorkItem>, BlackboardError> {
        let conn = self.conn.lock().expect("blackboard mutex");
        let mut stmt = conn.prepare(
            "SELECT id, lineage_root, parent_id, description, desc_embedding, \
                    reward, reward_updated_ns, required_tier, input_hashes, output_spec, \
                    streaming_ok, claimed_by, claimed_at_ns, claim_hlc_l, claim_hlc_c, claim_hlc_node, \
                    completed_at_ns, output_hash, icp_envelope_hash, success, \
                    created_at_ns, ttl_ns \
             FROM work_items \
             WHERE claimed_by IS NULL \
               AND reward >= ?1 \
               AND required_tier <= ?2 \
               AND (created_at_ns + ttl_ns) > ?3 \
             ORDER BY reward DESC",
        )?;
        let rows = stmt.query_map(params![min_reward, max_tier, now_ns], row_to_work_item)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r?);
        }
        Ok(out)
    }

    /// Append-only envelope log. Returns the envelope hash on success.
    pub fn store_envelope(&self, env: &SignedEnvelope) -> Result<String, BlackboardError> {
        let hash = envelope_hash(&env.payload)?;
        let payload_json = serde_json::to_string(env)?;
        let conn = self.conn.lock().expect("blackboard mutex");
        // INSERT OR IGNORE: storing the same envelope twice is a
        // no-op (idempotent), not an error. Matches Python's
        // behavior of returning the existing hash.
        conn.execute(
            "INSERT OR IGNORE INTO icp_envelopes (\
                envelope_hash, intent_id, action_id, agent_pubkey, \
                parent_envelope_hash, payload_json, timestamp_ns\
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                hash,
                env.payload.intent_id,
                env.payload.action_id,
                env.payload.agent_pubkey,
                env.payload.parent_envelope_hash,
                payload_json,
                env.payload.timestamp_ns,
            ],
        )?;
        Ok(hash)
    }

    /// Look up a signed envelope by its canonical hash.
    pub fn get_envelope(&self, hash: &str) -> Result<Option<SignedEnvelope>, BlackboardError> {
        let conn = self.conn.lock().expect("blackboard mutex");
        let json_opt: Option<String> = conn
            .query_row(
                "SELECT payload_json FROM icp_envelopes WHERE envelope_hash = ?1",
                params![hash],
                |row| row.get::<_, String>(0),
            )
            .optional()?;
        match json_opt {
            Some(json) => Ok(Some(serde_json::from_str(&json)?)),
            None => Ok(None),
        }
    }

    /// Reconstruct an envelope chain starting from the envelope
    /// referenced by `leaf_hash`, walking parent_envelope_hash links
    /// until we hit a root (parent_envelope_hash IS NULL).
    ///
    /// Returns the chain in root-first order. Returns an empty Vec
    /// if `leaf_hash` is unknown.
    pub fn reconstruct_chain(
        &self,
        leaf_hash: &str,
    ) -> Result<Vec<SignedEnvelope>, BlackboardError> {
        let mut reversed: Vec<SignedEnvelope> = Vec::new();
        let mut next: Option<String> = Some(leaf_hash.to_string());
        while let Some(h) = next.take() {
            match self.get_envelope(&h)? {
                Some(env) => {
                    next = env.payload.parent_envelope_hash.clone();
                    reversed.push(env);
                }
                None => {
                    // Missing link — broken chain. Return what we
                    // have so far in root-first order. Caller can
                    // detect by checking the first envelope's
                    // parent_envelope_hash isn't None.
                    break;
                }
            }
        }
        reversed.reverse();
        Ok(reversed)
    }
}

fn row_to_work_item(row: &rusqlite::Row) -> rusqlite::Result<WorkItem> {
    let emb_blob: Vec<u8> = row.get("desc_embedding")?;
    let desc_embedding = embedding_from_blob(&emb_blob).map_err(|_| {
        rusqlite::Error::FromSqlConversionFailure(
            4, // column index of desc_embedding
            rusqlite::types::Type::Blob,
            Box::new(std::io::Error::other("malformed embedding blob")),
        )
    })?;
    let input_hashes_json: String = row.get("input_hashes")?;
    let output_spec_json: String = row.get("output_spec")?;
    let input_hashes: Vec<String> = serde_json::from_str(&input_hashes_json).map_err(|e| {
        rusqlite::Error::FromSqlConversionFailure(8, rusqlite::types::Type::Text, Box::new(e))
    })?;
    let output_spec: serde_json::Value = serde_json::from_str(&output_spec_json).map_err(|e| {
        rusqlite::Error::FromSqlConversionFailure(9, rusqlite::types::Type::Text, Box::new(e))
    })?;
    let streaming_ok_int: i32 = row.get("streaming_ok")?;
    let success_int: Option<i32> = row.get("success")?;
    Ok(WorkItem {
        id: row.get("id")?,
        lineage_root: row.get("lineage_root")?,
        parent_id: row.get("parent_id")?,
        description: row.get("description")?,
        desc_embedding,
        reward: row.get("reward")?,
        reward_updated_ns: row.get("reward_updated_ns")?,
        required_tier: row.get("required_tier")?,
        input_hashes,
        output_spec,
        streaming_ok: streaming_ok_int != 0,
        claimed_by: row.get("claimed_by")?,
        claimed_at_ns: row.get("claimed_at_ns")?,
        claim_hlc_l: row.get("claim_hlc_l")?,
        claim_hlc_c: row.get("claim_hlc_c")?,
        claim_hlc_node: row.get("claim_hlc_node")?,
        completed_at_ns: row.get("completed_at_ns")?,
        output_hash: row.get("output_hash")?,
        icp_envelope_hash: row.get("icp_envelope_hash")?,
        success: success_int.map(|i| i != 0),
        created_at_ns: row.get("created_at_ns")?,
        ttl_ns: row.get("ttl_ns")?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use gyza_core::EMBEDDING_DIM;
    use gyza_icp::{EnvelopePayload, sign_envelope};

    fn make_embedding(seed: f32) -> Vec<f32> {
        (0..EMBEDDING_DIM)
            .map(|i| seed + i as f32 * 0.001)
            .collect()
    }

    fn make_work_item(id: &str, reward: f32, tier: i32, created_at_ns: i64) -> WorkItem {
        WorkItem::new_validated(
            id.to_string(),
            "int-0001".to_string(),
            None,
            format!("work {id}"),
            make_embedding(0.1),
            reward,
            created_at_ns,
            tier,
            vec![],
            serde_json::json!({"type": "text"}),
            false,
            created_at_ns,
            10_000_000_000_i64, // 10s TTL
        )
        .expect("valid work item")
    }

    #[test]
    fn schema_initializes_on_open() {
        let bb = Blackboard::open_in_memory().expect("open");
        // Inserting into work_items requires the intent to exist
        // (foreign key); attempting without it should fail.
        bb.post_intent("int-0001", &serde_json::json!({"goal": "test"}), 1000)
            .expect("post intent");
    }

    #[test]
    fn post_and_get_work_item() {
        let bb = Blackboard::open_in_memory().expect("open");
        bb.post_intent("int-0001", &serde_json::json!({}), 1000)
            .expect("post intent");
        let w = make_work_item("w1", 0.5, 1, 1000);
        bb.post_work_item(&w).expect("post work item");

        let unclaimed = bb.get_unclaimed(0.0, 3, 1000).expect("get_unclaimed");
        assert_eq!(unclaimed.len(), 1);
        assert_eq!(unclaimed[0].id, "w1");
        assert_eq!(unclaimed[0].desc_embedding.len(), EMBEDDING_DIM);
        assert!((unclaimed[0].desc_embedding[0] - 0.1).abs() < 1e-6);
    }

    #[test]
    fn duplicate_work_item_rejected() {
        let bb = Blackboard::open_in_memory().expect("open");
        bb.post_intent("int-0001", &serde_json::json!({}), 1000)
            .unwrap();
        let w = make_work_item("w1", 0.5, 1, 1000);
        bb.post_work_item(&w).unwrap();
        let err = bb.post_work_item(&w).unwrap_err();
        assert!(matches!(
            err,
            BlackboardError::WorkItemIdCollision { id } if id == "w1"
        ));
    }

    #[test]
    fn get_unclaimed_respects_filters() {
        let bb = Blackboard::open_in_memory().expect("open");
        bb.post_intent("int-0001", &serde_json::json!({}), 1000)
            .unwrap();
        bb.post_work_item(&make_work_item("lo", 0.1, 1, 1000))
            .unwrap();
        bb.post_work_item(&make_work_item("hi", 0.9, 1, 1000))
            .unwrap();
        bb.post_work_item(&make_work_item("tier3", 0.5, 3, 1000))
            .unwrap();

        // Reward threshold filters out "lo".
        let r = bb.get_unclaimed(0.5, 3, 2000).unwrap();
        let ids: Vec<&str> = r.iter().map(|w| w.id.as_str()).collect();
        // Ordered by reward DESC.
        assert_eq!(ids, vec!["hi", "tier3"]);

        // Tier filter excludes tier-3 work for a tier-1 agent.
        let r2 = bb.get_unclaimed(0.0, 1, 2000).unwrap();
        let ids2: Vec<&str> = r2.iter().map(|w| w.id.as_str()).collect();
        assert_eq!(ids2, vec!["hi", "lo"]);
    }

    #[test]
    fn get_unclaimed_excludes_ttl_expired() {
        let bb = Blackboard::open_in_memory().expect("open");
        bb.post_intent("int-0001", &serde_json::json!({}), 1000)
            .unwrap();
        // ttl=10s; created_at=1000; expires at 10_000_001_000.
        bb.post_work_item(&make_work_item("w1", 0.5, 1, 1000))
            .unwrap();
        // Within TTL:
        assert_eq!(bb.get_unclaimed(0.0, 3, 5_000_000_000).unwrap().len(), 1);
        // Past TTL:
        assert_eq!(bb.get_unclaimed(0.0, 3, 100_000_000_000).unwrap().len(), 0);
    }

    #[test]
    fn claim_work_item_is_atomic() {
        let bb = Blackboard::open_in_memory().expect("open");
        bb.post_intent("int-0001", &serde_json::json!({}), 1000)
            .unwrap();
        bb.post_work_item(&make_work_item("w1", 0.5, 1, 1000))
            .unwrap();

        let won = bb
            .claim_work_item("w1", "agent-1", 2000, 1, 0, "node-a")
            .unwrap();
        assert!(won);

        // Second claim attempt should lose.
        let won2 = bb
            .claim_work_item("w1", "agent-2", 2001, 1, 1, "node-b")
            .unwrap();
        assert!(!won2);

        // After claim, item is no longer unclaimed.
        assert!(bb.get_unclaimed(0.0, 3, 2000).unwrap().is_empty());
    }

    #[test]
    fn complete_work_item() {
        let bb = Blackboard::open_in_memory().expect("open");
        bb.post_intent("int-0001", &serde_json::json!({}), 1000)
            .unwrap();
        bb.post_work_item(&make_work_item("w1", 0.5, 1, 1000))
            .unwrap();
        bb.claim_work_item("w1", "agent-1", 2000, 1, 0, "node-a")
            .unwrap();
        let ok = bb
            .complete_work_item("w1", 3000, "out-hash", "env-hash", true)
            .unwrap();
        assert!(ok);

        // Second completion is a no-op (returns false).
        let ok2 = bb
            .complete_work_item("w1", 4000, "out2", "env2", true)
            .unwrap();
        assert!(!ok2);
    }

    fn make_envelope(
        intent: &str,
        action: &str,
        agent_hex: &str,
        parent: Option<String>,
        ts: i64,
    ) -> EnvelopePayload {
        EnvelopePayload {
            action_id: action.to_string(),
            agent_pubkey: agent_hex.to_string(),
            capability_manifest_hash: "cm".repeat(32),
            duration_ms: 10,
            inference_backend: "local".to_string(),
            input_hashes: vec!["in".to_string()],
            intent_id: intent.to_string(),
            model_identifier: "mock".to_string(),
            output_hash: "out".repeat(16),
            parent_envelope_hash: parent,
            schema_version: 1,
            timestamp_ns: ts,
            tokens_in: 1,
            tokens_out: 1,
        }
    }

    #[test]
    fn store_and_get_envelope() {
        let bb = Blackboard::open_in_memory().expect("open");

        // Test seed; consistent with gyza-crypto fixtures.
        const SEED: [u8; 32] = [
            0x07, 0x16, 0xbc, 0x44, 0xed, 0x01, 0xf1, 0xbe, 0x7a, 0x7d, 0x77, 0xc9, 0x2d, 0xdf,
            0xf6, 0x20, 0xd4, 0xb5, 0x3e, 0xf8, 0x2b, 0xda, 0x6f, 0x6e, 0xfc, 0x8d, 0xd9, 0xd6,
            0xcd, 0xfa, 0x3a, 0x47,
        ];
        let payload = make_envelope(
            "int1",
            "a1",
            "08ed03d0cb5efe9152a79430ddd86a97286d760bdb5955fea3688e8bb9a13ab9",
            None,
            1000,
        );
        let signed = sign_envelope(payload, &SEED).expect("sign");

        let stored_hash = bb.store_envelope(&signed).expect("store");
        // Idempotent: storing again returns the same hash without
        // failing.
        let stored_again = bb.store_envelope(&signed).expect("store again");
        assert_eq!(stored_hash, stored_again);

        let fetched = bb.get_envelope(&stored_hash).expect("get").expect("Some");
        assert_eq!(fetched, signed);

        // Unknown hash → None.
        let missing = bb.get_envelope("not-a-real-hash").expect("get");
        assert!(missing.is_none());
    }

    #[test]
    fn reconstruct_chain_walks_parents() {
        let bb = Blackboard::open_in_memory().expect("open");
        const SEED: [u8; 32] = [
            0x07, 0x16, 0xbc, 0x44, 0xed, 0x01, 0xf1, 0xbe, 0x7a, 0x7d, 0x77, 0xc9, 0x2d, 0xdf,
            0xf6, 0x20, 0xd4, 0xb5, 0x3e, 0xf8, 0x2b, 0xda, 0x6f, 0x6e, 0xfc, 0x8d, 0xd9, 0xd6,
            0xcd, 0xfa, 0x3a, 0x47,
        ];
        let pk_hex = "08ed03d0cb5efe9152a79430ddd86a97286d760bdb5955fea3688e8bb9a13ab9";

        // Build a 3-envelope chain: root → child → leaf.
        let root_p = make_envelope("int", "root", pk_hex, None, 100);
        let root = sign_envelope(root_p, &SEED).unwrap();
        let root_hash = bb.store_envelope(&root).unwrap();

        let child_p = make_envelope("int", "child", pk_hex, Some(root_hash.clone()), 200);
        let child = sign_envelope(child_p, &SEED).unwrap();
        let child_hash = bb.store_envelope(&child).unwrap();

        let leaf_p = make_envelope("int", "leaf", pk_hex, Some(child_hash.clone()), 300);
        let leaf = sign_envelope(leaf_p, &SEED).unwrap();
        let leaf_hash = bb.store_envelope(&leaf).unwrap();

        let chain = bb.reconstruct_chain(&leaf_hash).expect("chain");
        assert_eq!(chain.len(), 3);
        // Root-first order.
        assert_eq!(chain[0].payload.action_id, "root");
        assert_eq!(chain[1].payload.action_id, "child");
        assert_eq!(chain[2].payload.action_id, "leaf");
    }

    #[test]
    fn reconstruct_chain_unknown_leaf_returns_empty() {
        let bb = Blackboard::open_in_memory().expect("open");
        let chain = bb.reconstruct_chain("not-a-real-hash").expect("chain");
        assert!(chain.is_empty());
    }

    #[test]
    fn embedding_roundtrip_preserves_bytes() {
        let emb = make_embedding(0.5);
        let blob = embedding_to_blob(&emb);
        assert_eq!(blob.len(), EMBEDDING_DIM * 4);
        let back = embedding_from_blob(&blob).expect("from blob");
        assert_eq!(back.len(), EMBEDDING_DIM);
        for (a, b) in emb.iter().zip(back.iter()) {
            assert_eq!(
                a.to_bits(),
                b.to_bits(),
                "f32 byte roundtrip preserves bits"
            );
        }
    }

    #[test]
    fn embedding_from_bad_blob_rejected() {
        let bad = vec![0u8; 100];
        let err = embedding_from_blob(&bad).unwrap_err();
        assert!(matches!(err, BlackboardError::BadEmbeddingBlob { .. }));
    }
}
