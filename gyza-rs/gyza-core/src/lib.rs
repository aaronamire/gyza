//! Core protocol types for Gyza.
//!
//! Ports `gyza/schema.py` to Rust:
//!
//!   - [`WorkItem`] — agent-claimable unit of work
//!   - [`Artifact`] — signed binary blob with provenance
//!   - [`Hlc`] — thread-safe hybrid logical clock (Kulkarni 2014)
//!
//! ## Why this exists
//!
//! Phase 0 Stream 3 of the vNext migration (CLAUDE.md §8). Once
//! `gyza-blackboard` lands on top of this crate, Rust agents have
//! a complete data + clock + storage layer independent of the
//! Python codebase.
//!
//! ## HLC thread safety
//!
//! The HLC is shared across threads in cluster mode. Two concurrent
//! `now()` callers could otherwise race on read-modify-write of `l`
//! and `c` and produce non-distinct tuples — violating the HLC's
//! uniqueness invariant. We wrap the mutable state in a `Mutex` so
//! `now()` and `recv()` are atomic with respect to each other.
//! Matches Python's Session 8.5 fix (see CLAUDE.md §5e).
//!
//! Cross-references:
//!
//!   - `gyza/schema.py` — Python reference
//!   - `docs/invariants.md` § Cross-cutting INV-X-5 (HLC monotonicity)
//!   - `docs/state-machines.md` § HLC ratchet

use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

/// Specialization embedding dimensionality. Hard-coded; constitutional
/// invariant (CLAUDE.md §16 don't-do). Every advertisement on the DHT
/// is keyed by an LSH bucket computed against 384-dim planes;
/// changing this invalidates all existing global state.
pub const EMBEDDING_DIM: usize = 384;

/// Errors that can arise constructing or validating core types.
#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error("desc_embedding length must be {EMBEDDING_DIM}, got {got}")]
    BadEmbeddingShape { got: usize },
    #[error("reward must be in [0.0, 1.0], got {got}")]
    BadReward { got: f32 },
    #[error("required_tier must be 0..=3, got {got}")]
    BadTier { got: i32 },
}

/// A WorkItem — the agent-claimable unit of work.
///
/// Mirrors Python `gyza.schema.WorkItem`. Pure data; persistence
/// is the blackboard's responsibility; signing is ICP's.
///
/// `desc_embedding` is a `Vec<f32>` of length [`EMBEDDING_DIM`].
/// Validated in [`WorkItem::new_validated`]. We use Vec rather than
/// `[f32; 384]` because serde out-of-the-box supports it; a fixed-
/// size array would require `serde-big-array` for serialization.
/// The length invariant is checked at construction.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WorkItem {
    pub id: String,
    pub lineage_root: String,
    pub parent_id: Option<String>,
    pub description: String,
    pub desc_embedding: Vec<f32>,
    pub reward: f32,
    pub reward_updated_ns: i64,
    pub required_tier: i32,
    pub input_hashes: Vec<String>,
    pub output_spec: serde_json::Value,
    pub streaming_ok: bool,
    pub claimed_by: Option<String>,
    pub claimed_at_ns: Option<i64>,
    pub claim_hlc_l: i64,
    pub claim_hlc_c: i64,
    pub claim_hlc_node: String,
    pub completed_at_ns: Option<i64>,
    pub output_hash: Option<String>,
    pub icp_envelope_hash: Option<String>,
    pub success: Option<bool>,
    pub created_at_ns: i64,
    pub ttl_ns: i64,
}

impl WorkItem {
    /// Construct a WorkItem with all field-level validation that
    /// Python's `__post_init__` runs. Returns CoreError on malformed
    /// inputs.
    #[allow(clippy::too_many_arguments)]
    pub fn new_validated(
        id: String,
        lineage_root: String,
        parent_id: Option<String>,
        description: String,
        desc_embedding: Vec<f32>,
        reward: f32,
        reward_updated_ns: i64,
        required_tier: i32,
        input_hashes: Vec<String>,
        output_spec: serde_json::Value,
        streaming_ok: bool,
        created_at_ns: i64,
        ttl_ns: i64,
    ) -> Result<Self, CoreError> {
        if desc_embedding.len() != EMBEDDING_DIM {
            return Err(CoreError::BadEmbeddingShape {
                got: desc_embedding.len(),
            });
        }
        if !(0.0..=1.0).contains(&reward) {
            return Err(CoreError::BadReward { got: reward });
        }
        if !(0..=3).contains(&required_tier) {
            return Err(CoreError::BadTier { got: required_tier });
        }
        Ok(Self {
            id,
            lineage_root,
            parent_id,
            description,
            desc_embedding,
            reward,
            reward_updated_ns,
            required_tier,
            input_hashes,
            output_spec,
            streaming_ok,
            claimed_by: None,
            claimed_at_ns: None,
            claim_hlc_l: 0,
            claim_hlc_c: 0,
            claim_hlc_node: String::new(),
            completed_at_ns: None,
            output_hash: None,
            icp_envelope_hash: None,
            success: None,
            created_at_ns,
            ttl_ns,
        })
    }

    /// An item is currently unclaimed iff (a) no claimed_by, AND
    /// (b) it hasn't aged past its TTL relative to `now_ns`.
    ///
    /// Matches Python's `Blackboard.get_unclaimed`'s filter
    /// `(created_at_ns + ttl_ns) > now_ns AND no claim exists`.
    pub fn is_unclaimed(&self, now_ns: i64) -> bool {
        self.claimed_by.is_none() && (self.created_at_ns + self.ttl_ns) > now_ns
    }
}

/// An Artifact — signed binary blob with provenance.
///
/// Mirrors Python `gyza.schema.Artifact`. The `data` is raw bytes;
/// signing/verification belongs to a higher layer.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Artifact {
    pub hash: String,
    /// Base64 or hex encoding on the wire; in memory this is the
    /// raw bytes. Choice of serialization is the responsibility of
    /// the storage layer.
    #[serde(with = "serde_bytes")]
    pub data: Vec<u8>,
    pub signature: String,
    pub signer_pubkey: String,
    pub parent_hashes: Vec<String>,
    pub timestamp_ns: i64,
}

// Local serde_bytes module since the standard one would require an
// extra crate; for our use case the simple "vec of bytes" serialization
// is fine. JSON will encode this as an array of integers, matching
// Python's `json.dumps(bytes_value)` behavior (which doesn't have a
// natural bytes serialization anyway).
mod serde_bytes {
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S: Serializer>(bytes: &[u8], s: S) -> Result<S::Ok, S::Error> {
        s.serialize_bytes(bytes)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<u8>, D::Error> {
        let v = Vec::<u8>::deserialize(d)?;
        Ok(v)
    }
}

/// Snapshot of an HLC tuple — (l, c, node_id). Used as the return
/// type for `now()` and `snapshot()`.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct HlcTuple {
    pub l: i64,
    pub c: i64,
    pub node_id: String,
}

impl HlcTuple {
    pub fn new(l: i64, c: i64, node_id: impl Into<String>) -> Self {
        Self {
            l,
            c,
            node_id: node_id.into(),
        }
    }
}

/// Thread-safe Hybrid Logical Clock (Kulkarni 2014).
///
/// `l` is millisecond wall time captured at the last event;
/// `c` is the counter that disambiguates events sharing the same `l`.
/// Both move monotonically forward — never reset on backwards wall-
/// clock jumps.
///
/// The mutex makes `now()` and `recv()` atomic so two concurrent
/// `now()` calls cannot produce the same `(l, c)` tuple — the
/// uniqueness invariant the HLC is supposed to guarantee.
///
/// Cross-references:
///
///   - `gyza/schema.py::HLC` — Python reference
///   - INV-X-5 in `docs/invariants.md` (HLC monotonicity)
pub struct Hlc {
    node_id: String,
    state: Mutex<HlcState>,
}

struct HlcState {
    l: i64,
    c: i64,
}

/// Function pointer for the wall-clock millisecond reader. Default
/// is `system_time_ms`; tests can substitute a deterministic clock
/// via [`Hlc::with_clock`].
pub type ClockFn = fn() -> i64;

fn system_time_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time before unix epoch")
        .as_millis() as i64
}

impl Hlc {
    /// Construct an HLC bound to `node_id`, using the system clock.
    pub fn new(node_id: impl Into<String>) -> Self {
        Self::with_initial(node_id.into(), 0, 0)
    }

    /// Construct with explicit initial (l, c). Used in tests and when
    /// resuming from a persisted clock.
    pub fn with_initial(node_id: String, l: i64, c: i64) -> Self {
        Self {
            node_id,
            state: Mutex::new(HlcState { l, c }),
        }
    }

    /// Generate a new HLC tuple for a local event. Advances the
    /// clock atomically.
    pub fn now(&self) -> HlcTuple {
        self.now_with_clock(system_time_ms)
    }

    /// Generate a new HLC tuple using a caller-supplied clock. Used
    /// in tests with a deterministic clock.
    pub fn now_with_clock(&self, clock: ClockFn) -> HlcTuple {
        let mut s = self.state.lock().expect("HLC mutex poisoned");
        let pt = clock();
        let l_old = s.l;
        s.l = l_old.max(pt);
        if s.l == l_old {
            s.c += 1;
        } else {
            s.c = 0;
        }
        HlcTuple {
            l: s.l,
            c: s.c,
            node_id: self.node_id.clone(),
        }
    }

    /// Receive a remote HLC event and advance the local clock past
    /// it. Atomic with respect to `now()`.
    pub fn recv(&self, remote: &HlcTuple) {
        self.recv_with_clock(remote, system_time_ms)
    }

    /// Receive with a caller-supplied clock. Used in tests.
    pub fn recv_with_clock(&self, remote: &HlcTuple, clock: ClockFn) {
        let mut s = self.state.lock().expect("HLC mutex poisoned");
        let pt = clock();
        let l_old = s.l;
        let c_old = s.c;
        let l_new = l_old.max(remote.l).max(pt);
        s.c = if l_new == l_old && l_new == remote.l {
            c_old.max(remote.c) + 1
        } else if l_new == l_old {
            c_old + 1
        } else if l_new == remote.l {
            remote.c + 1
        } else {
            0
        };
        s.l = l_new;
    }

    /// Read the current state without advancing the clock. Used for
    /// diagnostics + tests asserting progress.
    pub fn snapshot(&self) -> HlcTuple {
        let s = self.state.lock().expect("HLC mutex poisoned");
        HlcTuple {
            l: s.l,
            c: s.c,
            node_id: self.node_id.clone(),
        }
    }

    /// Node id this clock is bound to.
    pub fn node_id(&self) -> &str {
        &self.node_id
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::thread;

    fn make_embedding(seed: f32) -> Vec<f32> {
        (0..EMBEDDING_DIM)
            .map(|i| seed + i as f32 * 0.001)
            .collect()
    }

    #[test]
    fn workitem_construction_validates_embedding_shape() {
        let bad = vec![0.0_f32; 10]; // wrong dim
        let err = WorkItem::new_validated(
            "id".to_string(),
            "root".to_string(),
            None,
            "desc".to_string(),
            bad,
            0.5,
            0,
            1,
            vec![],
            serde_json::json!({}),
            false,
            0,
            1_000_000_000,
        )
        .unwrap_err();
        assert!(matches!(err, CoreError::BadEmbeddingShape { got: 10 }));
    }

    #[test]
    fn workitem_construction_validates_reward_range() {
        let emb = make_embedding(0.1);
        let err = WorkItem::new_validated(
            "id".to_string(),
            "root".to_string(),
            None,
            "desc".to_string(),
            emb,
            1.5, // out of range
            0,
            1,
            vec![],
            serde_json::json!({}),
            false,
            0,
            1_000_000_000,
        )
        .unwrap_err();
        assert!(matches!(err, CoreError::BadReward { .. }));
    }

    #[test]
    fn workitem_construction_validates_tier() {
        let emb = make_embedding(0.1);
        let err = WorkItem::new_validated(
            "id".to_string(),
            "root".to_string(),
            None,
            "desc".to_string(),
            emb,
            0.5,
            0,
            5, // out of range
            vec![],
            serde_json::json!({}),
            false,
            0,
            1_000_000_000,
        )
        .unwrap_err();
        assert!(matches!(err, CoreError::BadTier { got: 5 }));
    }

    #[test]
    fn workitem_is_unclaimed_respects_ttl_and_claim() {
        let mut w = WorkItem::new_validated(
            "id".to_string(),
            "root".to_string(),
            None,
            "desc".to_string(),
            make_embedding(0.1),
            0.5,
            0,
            1,
            vec![],
            serde_json::json!({}),
            false,
            1000,          // created_at_ns
            1_000_000_000, // ttl_ns
        )
        .unwrap();
        // Not yet TTL-expired and unclaimed:
        assert!(w.is_unclaimed(500_000_000));
        // Past TTL → not unclaimed regardless of claim status:
        assert!(!w.is_unclaimed(2_000_000_001));
        // Claimed → not unclaimed even within TTL:
        w.claimed_by = Some("agent-1".to_string());
        assert!(!w.is_unclaimed(500_000_000));
    }

    #[test]
    fn hlc_now_is_monotonic_under_fixed_clock() {
        // With a fixed clock, consecutive now() calls share the
        // same wall-time so the counter must advance.
        let h = Hlc::new("node-a");
        fn clock() -> i64 {
            1_000_000
        }
        let t1 = h.now_with_clock(clock);
        let t2 = h.now_with_clock(clock);
        let t3 = h.now_with_clock(clock);
        // Wall time same; counter strictly increasing.
        assert_eq!(t1.l, 1_000_000);
        assert_eq!(t2.l, 1_000_000);
        assert_eq!(t3.l, 1_000_000);
        assert!(t2.c > t1.c, "{:?} should follow {:?}", t2, t1);
        assert!(t3.c > t2.c);
    }

    #[test]
    fn hlc_now_advances_on_wall_clock_jump() {
        // First call sets l to clock_1. Second call uses a higher
        // clock_2 — l advances; counter resets to 0.
        let h = Hlc::new("node-a");
        fn clock1() -> i64 {
            1_000_000
        }
        fn clock2() -> i64 {
            2_000_000
        }
        let t1 = h.now_with_clock(clock1);
        let t2 = h.now_with_clock(clock2);
        assert_eq!(t1.l, 1_000_000);
        assert_eq!(t2.l, 2_000_000);
        assert_eq!(t2.c, 0);
    }

    #[test]
    fn hlc_recv_ratchets_past_remote() {
        let h = Hlc::new("node-a");
        fn clock_zero() -> i64 {
            0
        }
        // Receive a remote event with l=999, c=5 — we should
        // advance past it.
        let remote = HlcTuple::new(999, 5, "node-b".to_string());
        h.recv_with_clock(&remote, clock_zero);
        let snap = h.snapshot();
        assert_eq!(snap.l, 999);
        assert_eq!(snap.c, 6); // remote.c + 1
    }

    #[test]
    fn hlc_recv_ratchets_past_both_local_and_remote() {
        let h = Hlc::with_initial("node-a".to_string(), 1000, 3);
        fn clock_zero() -> i64 {
            0
        }
        // Remote at same l, lower c → local c advances.
        let remote = HlcTuple::new(1000, 2, "node-b".to_string());
        h.recv_with_clock(&remote, clock_zero);
        let snap = h.snapshot();
        assert_eq!(snap.l, 1000);
        // l_new == l_old == remote.l → c = max(c_old, remote.c) + 1
        // = max(3, 2) + 1 = 4
        assert_eq!(snap.c, 4);
    }

    #[test]
    fn hlc_concurrent_now_produces_distinct_tuples() {
        // The uniqueness invariant from CLAUDE.md INV-X-5. Spawn
        // many threads each calling now() many times under a fixed
        // clock; collect all tuples; assert all distinct.
        let h = Arc::new(Hlc::new("node-a"));
        let n_threads = 8usize;
        let calls_per_thread = 1000usize;
        let mut handles = Vec::new();
        for _ in 0..n_threads {
            let h_clone = Arc::clone(&h);
            handles.push(thread::spawn(move || {
                let mut tuples = Vec::with_capacity(calls_per_thread);
                fn clock() -> i64 {
                    1_000_000
                }
                for _ in 0..calls_per_thread {
                    tuples.push(h_clone.now_with_clock(clock));
                }
                tuples
            }));
        }
        let mut all_tuples: Vec<HlcTuple> = Vec::with_capacity(n_threads * calls_per_thread);
        for h in handles {
            all_tuples.extend(h.join().expect("thread join"));
        }
        let total = all_tuples.len();
        let unique: std::collections::HashSet<_> = all_tuples.into_iter().collect();
        assert_eq!(
            unique.len(),
            total,
            "HLC must produce distinct tuples under concurrent now() calls"
        );
    }

    #[test]
    fn artifact_round_trips_via_serde() {
        let a = Artifact {
            hash: "abc".to_string(),
            data: vec![1, 2, 3, 4],
            signature: "sig".to_string(),
            signer_pubkey: "pk".to_string(),
            parent_hashes: vec!["p1".to_string()],
            timestamp_ns: 12345,
        };
        let json = serde_json::to_string(&a).expect("ser");
        let back: Artifact = serde_json::from_str(&json).expect("de");
        assert_eq!(a, back);
    }
}
