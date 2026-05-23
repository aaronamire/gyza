//! Tier-3 capability attestation — canonical-bytes substrate.
//!
//! This crate ports the data types and canonical-JSON encodings from
//! `gyza.network.capability_protocol` (Python) with byte-for-byte parity.
//! The Validator and Applicant state machines, and the higher-level
//! `run_attestation` / `verify_attestation_cert` flows, are intentionally
//! NOT in this crate yet; they will arrive in a follow-up that depends on
//! `gyza-icp` (for envelope verification) and `gyza-crypto` (for Ed25519
//! sign/verify of cosigs).
//!
//! What lives here:
//!
//!   - `ChallengePayload` / `Challenge`  — validator → applicant
//!   - `AttestationCertPayload`          — the bytes every validator co-signs
//!   - `ValidatorCosig`                  — one validator's signature
//!   - `AttestationCert`                 — payload + ≥k cosigs
//!   - `EvalResult`                      — one task's eval outcome
//!   - `ChallengeResponsePayload` / `ChallengeResponse` — applicant → validator
//!   - `challenge_canonical_bytes(...)`
//!   - `attestation_payload_canonical_bytes(...)`
//!   - `response_canonical_bytes(...)`
//!   - `verify_attestation_cert(...)`    — independent consumer-side
//!     cert verification (schema / applicant / expiry / quorum cosig
//!     check). Cross-language interop: tests deserialize a
//!     Python-signed cert and verify it under this Rust function.
//!
//! Recursive canonical-JSON note (relevant to `EvalResult` and
//! `ChallengeResponse`): the embedded `envelope` and the task-specific
//! `output` dict are typed as `serde_json::Value`. `serde_json::Map`
//! is `BTreeMap`-backed by default (the `preserve_order` feature is
//! OFF in this workspace), so its keys serialize in sorted order
//! recursively. That matches Python's `json.dumps(..., sort_keys=True)`
//! recursively, which is the byte-parity invariant. Typed map fields
//! that need sorted keys use `BTreeMap<String, T>` for the same reason.
//!
//! Canonical-JSON discipline (mirrors `gyza-icp`):
//!
//!   - Python: `json.dumps(d, sort_keys=True, separators=(",", ":"))`
//!   - Rust  : `serde_json::to_string(payload)` with the struct's
//!     field order matching alphabetized key order.
//!
//! That second clause is **load-bearing**. Every payload struct here
//! lists fields in EXACTLY the order Python's `sort_keys=True` would
//! produce. Reordering struct fields silently breaks every signature
//! produced by the Python implementation. DO NOT REORDER.
//!
//! What is NOT covered yet (next session):
//!
//!   - `Validator` / `Applicant` state machines (the *signing* side
//!     of the protocol; the *verifying* side is in this crate).
//!   - `run_attestation` orchestration.
//!   - The full `EvalTask` ecosystem from `gyza.capability_eval` —
//!     this crate only ports `EvalResult` (the OUTCOME type the wire
//!     protocol carries), not the task definitions themselves.
//!
//! Cross-references:
//!
//!   - `gyza/network/capability_protocol.py` — Python reference impl
//!   - `gyza-rs/scripts/regenerate_capability_fixtures.py` — parity fixture
//!     generator (run before changing any field semantics).

use std::collections::{BTreeMap, HashSet};

use serde::{Deserialize, Serialize};
use serde_json::Value;

// ---------------------------------------------------------------------------
// Protocol constants — mirror gyza/network/capability_protocol.py.
// ---------------------------------------------------------------------------

/// The schema string a Tier-3 cert must carry. Mirrored verbatim.
pub const CERT_SCHEMA: &str = "gyza.attestation.tier3/v1";

/// Wire-format major version used by the Python implementation.
pub const PROTOCOL_VERSION: &str = "v1";

/// Default quorum threshold: ≥ k of n validators must co-sign.
pub const DEFAULT_QUORUM_K: usize = 2;

/// Default quorum size n.
pub const DEFAULT_QUORUM_N: usize = 3;

/// Default cert lifetime (30 days, in ns).
pub const DEFAULT_CERT_LIFETIME_NS: i64 = 30 * 24 * 60 * 60 * 1_000_000_000;

/// Maximum tolerated clock skew between validators (1 hour, in ns).
pub const MAX_CLOCK_SKEW_NS: i64 = 60 * 60 * 1_000_000_000;

/// Errors that can arise from canonical-bytes encoding.
#[derive(Debug, thiserror::Error)]
pub enum CapabilityError {
    #[error("canonical-JSON encoding failed: {0}")]
    JsonEncode(#[from] serde_json::Error),
}

/// Errors returned by `verify_attestation_cert`. Mirrors the reason
/// strings produced by the Python implementation.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum VerifyError {
    #[error("unsupported cert schema: {0}")]
    UnsupportedSchema(String),
    #[error("cert applicant pubkey does not match expected")]
    ApplicantMismatch,
    #[error("cert expired")]
    Expired,
    #[error("cert older than max_age_ns")]
    TooOld,
    #[error("only {valid} valid cosig(s), need {required}")]
    BelowQuorum { valid: usize, required: usize },
    #[error("canonical-JSON encoding failed: {0}")]
    Encode(String),
}

impl From<CapabilityError> for VerifyError {
    fn from(e: CapabilityError) -> Self {
        VerifyError::Encode(e.to_string())
    }
}

// ---------------------------------------------------------------------------
// Challenge — validator → applicant.
// ---------------------------------------------------------------------------

/// The signed-over portion of a `Challenge`. Excludes `signature`.
///
/// **Field order is load-bearing — alphabetical**, so `serde_json` emits
/// the same byte sequence Python's `sort_keys=True` produces. DO NOT
/// REORDER.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChallengePayload {
    pub challenge_id: String,
    pub eval_version: String,
    pub expires_at_ns: i64,
    pub issued_at_ns: i64,
    pub nonce: String,
    pub task_ids: Vec<String>,
    pub validator_pubkey: String,
}

/// A `Challenge` as transmitted on the wire = payload + Ed25519
/// signature (hex). Only the payload is canonicalized for signing; the
/// signature is appended.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Challenge {
    #[serde(flatten)]
    pub payload: ChallengePayload,
    pub signature: String,
}

/// Canonical bytes for the validator's signature on a `Challenge`.
///
/// Python equivalent: `gyza.network.capability_protocol::_challenge_canonical_bytes`.
pub fn challenge_canonical_bytes(payload: &ChallengePayload) -> Result<Vec<u8>, CapabilityError> {
    Ok(serde_json::to_vec(payload)?)
}

// ---------------------------------------------------------------------------
// AttestationCertPayload — the bytes every validator co-signs.
// ---------------------------------------------------------------------------

/// The signed-over portion of an attestation cert. Every validator's
/// cosig is over the canonical bytes of this exact struct — identical
/// bytes across validators is the load-bearing invariant that lets the
/// quorum form.
///
/// **Field order is load-bearing — alphabetical.** DO NOT REORDER.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AttestationCertPayload {
    pub applicant_compositor_pubkey: String,
    pub eval_version: String,
    pub expires_at_ns: i64,
    pub issued_at_ns: i64,
    pub schema: String,
}

/// Canonical bytes that every validator's cosig is over.
///
/// Python equivalent: `gyza.network.capability_protocol::_payload_canonical_bytes`.
pub fn attestation_payload_canonical_bytes(
    payload: &AttestationCertPayload,
) -> Result<Vec<u8>, CapabilityError> {
    Ok(serde_json::to_vec(payload)?)
}

// ---------------------------------------------------------------------------
// EvalResult — one task's outcome carried inside a ChallengeResponse.
// ---------------------------------------------------------------------------

/// Captured outcome of one eval task during applicant-side execution.
///
/// **Field order alphabetical — DO NOT REORDER.** The nested `envelope`
/// and `output` fields are typed as `serde_json::Value` so their
/// internal keys serialize sorted (Python `sort_keys=True` recursively).
/// On the producing side, callers build them via
/// `serde_json::to_value(&signed_icp_envelope)` or
/// `serde_json::to_value(&task_specific_output_struct)`. On verifying
/// side, callers re-deserialize them back to typed structs as needed.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EvalResult {
    pub duration_s: f64,
    /// Optional fully-signed ICP envelope (Python: `ICPEnvelope | None`).
    /// `None` serializes as `null`, matching Python's behavior.
    pub envelope: Option<Value>,
    pub error: String,
    /// Task-specific output dict (Python: `dict | None`).
    pub output: Option<Value>,
    pub output_text: String,
    pub succeeded: bool,
    pub task_id: String,
}

// ---------------------------------------------------------------------------
// ChallengeResponse — applicant → validator.
// ---------------------------------------------------------------------------

/// The signed-over portion of a `ChallengeResponse`. Excludes
/// `applicant_signature`.
///
/// **Field order alphabetical — DO NOT REORDER.** `eval_results` uses
/// `BTreeMap` so task-id keys serialize in sorted order, matching
/// Python's `sort_keys=True` for the embedded `dict[str, EvalResult]`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ChallengeResponsePayload {
    pub applicant_agent_pubkey: String,
    pub applicant_compositor_pubkey: String,
    pub cert_payload: AttestationCertPayload,
    pub challenge_id: String,
    pub eval_results: BTreeMap<String, EvalResult>,
    pub nonce_echo: String,
}

/// Wire-format `ChallengeResponse` = canonical payload + applicant's
/// Ed25519 signature. Only the payload is canonicalized for signing.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ChallengeResponse {
    #[serde(flatten)]
    pub payload: ChallengeResponsePayload,
    pub applicant_signature: String,
}

/// Canonical bytes for the applicant's signature on a `ChallengeResponse`.
///
/// Python equivalent:
/// `gyza.network.capability_protocol::_response_canonical_bytes`.
pub fn response_canonical_bytes(
    payload: &ChallengeResponsePayload,
) -> Result<Vec<u8>, CapabilityError> {
    Ok(serde_json::to_vec(payload)?)
}

// ---------------------------------------------------------------------------
// ValidatorCosig + AttestationCert
// ---------------------------------------------------------------------------

/// One validator's cosignature on an `AttestationCertPayload`. Each
/// cosig is bound to `validator_pubkey` so a malicious party can't
/// transplant a signature from one validator's identity to another.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ValidatorCosig {
    pub cosigned_at_ns: i64,
    pub signature: String,
    pub validator_pubkey: String,
}

/// Final Tier-3 attestation cert: the canonical payload + ≥k validator
/// cosigs. The cert is JSON-serializable directly; future DHT
/// publication just dumps and stores under a key derived from
/// `payload.applicant_compositor_pubkey`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AttestationCert {
    pub payload: AttestationCertPayload,
    pub validator_cosigs: Vec<ValidatorCosig>,
}

// ---------------------------------------------------------------------------
// verify_attestation_cert — independent consumer-side cert check.
// ---------------------------------------------------------------------------

/// Independent consumer-side check on an aggregated `AttestationCert`.
/// Mirrors `gyza.network.capability_protocol::verify_attestation_cert`.
///
/// Checks, in order:
///
///   1. `payload.schema == CERT_SCHEMA`.
///   2. `expected_applicant_pubkey`, if given, matches the payload.
///   3. Cert hasn't expired vs `now_ns`.
///   4. `max_age_ns`, if given, bounds how old the cert can be.
///   5. Each cosig's Ed25519 signature verifies under its claimed
///      `validator_pubkey`.
///   6. ≥ `min_quorum` distinct valid cosigs (a single validator
///      cannot double-count toward quorum — same dedup semantics as
///      Python: a validator is added to `seen` only on a successful
///      verification, so an invalid attempt does not poison a later
///      valid cosig from the same validator).
///
/// Returns `Ok(())` on success or the most specific `VerifyError`
/// otherwise. The consumer is expected to ALSO verify each
/// `validator_pubkey` is itself Tier-3-attested via DHT lookup — that
/// is a separate concern outside this pure function.
pub fn verify_attestation_cert(
    cert: &AttestationCert,
    expected_applicant_pubkey: Option<&str>,
    min_quorum: usize,
    max_age_ns: Option<i64>,
    now_ns: i64,
) -> Result<(), VerifyError> {
    let p = &cert.payload;
    if p.schema != CERT_SCHEMA {
        return Err(VerifyError::UnsupportedSchema(p.schema.clone()));
    }
    if let Some(expected) = expected_applicant_pubkey
        && p.applicant_compositor_pubkey != expected
    {
        return Err(VerifyError::ApplicantMismatch);
    }
    if p.expires_at_ns < now_ns {
        return Err(VerifyError::Expired);
    }
    if let Some(max_age) = max_age_ns
        && now_ns.saturating_sub(p.issued_at_ns) > max_age
    {
        return Err(VerifyError::TooOld);
    }

    let payload_bytes = attestation_payload_canonical_bytes(p)?;
    let mut seen: HashSet<&str> = HashSet::new();
    let mut valid_count: usize = 0;
    for cosig in &cert.validator_cosigs {
        // Already counted toward quorum — skip.
        if seen.contains(cosig.validator_pubkey.as_str()) {
            continue;
        }
        // Decode + verify; failures don't poison `seen` (intentional —
        // a later valid cosig from the same validator should still
        // count, matching the Python implementation).
        let Ok(pk_bytes) = hex::decode(&cosig.validator_pubkey) else {
            continue;
        };
        let Ok(sig_bytes) = hex::decode(&cosig.signature) else {
            continue;
        };
        if gyza_crypto::verify(&pk_bytes, &payload_bytes, &sig_bytes).is_ok() {
            seen.insert(cosig.validator_pubkey.as_str());
            valid_count += 1;
        }
    }

    if valid_count < min_quorum {
        return Err(VerifyError::BelowQuorum {
            valid: valid_count,
            required: min_quorum,
        });
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Tests — parity against fixtures generated by
// gyza-rs/scripts/regenerate_capability_fixtures.py
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_challenge_payload() -> ChallengePayload {
        ChallengePayload {
            challenge_id: "chal-0001".to_string(),
            eval_version: "eval-v1".to_string(),
            expires_at_ns: 1_700_000_300_000_000_000,
            issued_at_ns: 1_700_000_000_000_000_000,
            nonce: "00112233445566778899aabbccddeeff".to_string(),
            task_ids: vec!["t1".to_string(), "t2".to_string(), "t3".to_string()],
            validator_pubkey: "abcd0000000000000000000000000000000000000000000000000000000000ef"
                .to_string(),
        }
    }

    fn sample_attestation_payload() -> AttestationCertPayload {
        AttestationCertPayload {
            applicant_compositor_pubkey:
                "11220000000000000000000000000000000000000000000000000000000000ff".to_string(),
            eval_version: "eval-v1".to_string(),
            expires_at_ns: 1_700_001_000_000_000_000,
            issued_at_ns: 1_700_000_000_000_000_000,
            schema: "gyza.attestation/1".to_string(),
        }
    }

    /// Byte-parity: Rust canonical_bytes must match Python output exactly.
    /// The expected hex is generated by
    /// gyza-rs/scripts/regenerate_capability_fixtures.py — regenerate
    /// and paste here whenever a payload field is added/renamed.
    #[test]
    fn challenge_canonical_bytes_parity_with_python() {
        let payload = sample_challenge_payload();
        let bytes = challenge_canonical_bytes(&payload).unwrap();
        // Fixture generated by
        // gyza-rs/scripts/regenerate_capability_fixtures.py (281 bytes).
        let expected_hex = concat!(
            "7b226368616c6c656e67655f6964223a226368616c2d30303031222c22657661",
            "6c5f76657273696f6e223a226576616c2d7631222c22657870697265735f6174",
            "5f6e73223a313730303030303330303030303030303030302c22697373756564",
            "5f61745f6e73223a313730303030303030303030303030303030302c226e6f6e",
            "6365223a22303031313232333334343535363637373838393961616262636364",
            "6465656666222c227461736b5f696473223a5b227431222c227432222c227433",
            "225d2c2276616c696461746f725f7075626b6579223a22616263643030303030",
            "3030303030303030303030303030303030303030303030303030303030303030",
            "3030303030303030303030303030303030303030306566227d",
        );
        let expected = hex::decode(expected_hex).expect("test fixture must be valid hex");
        assert_eq!(
            bytes, expected,
            "challenge_canonical_bytes diverged from Python; \
             regenerate fixtures with \
             scripts/regenerate_capability_fixtures.py and paste anew",
        );
    }

    #[test]
    fn attestation_payload_canonical_bytes_parity_with_python() {
        let payload = sample_attestation_payload();
        let bytes = attestation_payload_canonical_bytes(&payload).unwrap();
        // Fixture generated by
        // gyza-rs/scripts/regenerate_capability_fixtures.py (224 bytes).
        let expected_hex = concat!(
            "7b226170706c6963616e745f636f6d706f7369746f725f7075626b6579223a22",
            "3131323230303030303030303030303030303030303030303030303030303030",
            "3030303030303030303030303030303030303030303030303030303030306666",
            "222c226576616c5f76657273696f6e223a226576616c2d7631222c2265787069",
            "7265735f61745f6e73223a313730303030313030303030303030303030302c22",
            "6973737565645f61745f6e73223a313730303030303030303030303030303030",
            "302c22736368656d61223a2267797a612e6174746573746174696f6e2f31227d",
        );
        let expected = hex::decode(expected_hex).expect("test fixture must be valid hex");
        assert_eq!(
            bytes, expected,
            "attestation_payload_canonical_bytes diverged from Python",
        );
    }

    /// Round-trip serde so the Challenge wire format (payload + signature)
    /// deserializes back identically. Catches accidental rename of the
    /// flatten/signature wiring.
    #[test]
    fn challenge_wire_roundtrip() {
        let original = Challenge {
            payload: sample_challenge_payload(),
            signature: "deadbeef".to_string(),
        };
        let json = serde_json::to_string(&original).unwrap();
        let back: Challenge = serde_json::from_str(&json).unwrap();
        assert_eq!(original, back);
    }

    // ---------------------------------------------------------------
    // verify_attestation_cert — cross-language interop tests.
    //
    // SIGNED_CERT_JSON is generated by
    // gyza-rs/scripts/regenerate_capability_fixtures.py. It contains a
    // real AttestationCert: three Ed25519 validator cosigs over the
    // canonical bytes of a real AttestationCertPayload. The Rust
    // verifier must accept it — that is what byte-for-byte parity
    // BUYS us across the Python↔Rust boundary.
    // ---------------------------------------------------------------

    const SIGNED_CERT_JSON: &str = concat!(
        r#"{"payload":{"applicant_compositor_pubkey":""#,
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        r#"","eval_version":"eval-v1","expires_at_ns":1700000300000000000,"#,
        r#""issued_at_ns":1700000000000000000,"#,
        r#""schema":"gyza.attestation.tier3/v1"},"#,
        r#""validator_cosigs":[{"cosigned_at_ns":1700000100000000000,"#,
        r#""signature":""#,
        "28337fcb4d2b4576046cd7699b5d0daba22313b465e2679edbcc17bd703e00f1",
        "839c5fae2a2b2bc9ed0d34c689d32d3740b12c8f1745a9136c6475947f51700b",
        r#"","validator_pubkey":""#,
        "8a88e3dd7409f195fd52db2d3cba5d72ca6709bf1d94121bf3748801b40f6f5c",
        r#""},"#,
        r#"{"cosigned_at_ns":1700000100000000001,"signature":""#,
        "70d67b221c33938d9c035fabc64631d8201facb815f7f90c3c5523fca005dd6b",
        "5eb008302d76138309f61e55b8a2d806d0122e13bef7ec1bf567428225e6b309",
        r#"","validator_pubkey":""#,
        "8139770ea87d175f56a35466c34c7ecccb8d8a91b4ee37a25df60f5b8fc9b394",
        r#""},"#,
        r#"{"cosigned_at_ns":1700000100000000002,"signature":""#,
        "06f79df5c8e27360dcbbe5f18c343616675ed6dd8a66a79d174cec102a671fa1",
        "5ede0fb7807c70ce0b5da0ececc2286376734fde9bb1efb19f1294e642842b0f",
        r#"","validator_pubkey":""#,
        "ed4928c628d1c2c6eae90338905995612959273a5c63f93636c14614ac8737d1",
        r#""}]}"#,
    );

    const APPLICANT_PUBKEY: &str =
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const NOW_INSIDE: i64 = 1_700_000_200_000_000_000; // between issued and expires
    const NOW_AFTER_EXPIRY: i64 = 1_700_000_400_000_000_000;

    fn load_signed_cert() -> AttestationCert {
        serde_json::from_str(SIGNED_CERT_JSON).expect("fixture JSON must parse")
    }

    /// THE killer test — Rust verifier accepts a Python-signed cert.
    #[test]
    fn verify_python_signed_cert_quorum_2() {
        let cert = load_signed_cert();
        let r = verify_attestation_cert(&cert, Some(APPLICANT_PUBKEY), 2, None, NOW_INSIDE);
        assert!(
            r.is_ok(),
            "Rust must accept a Python-signed cert (cross-lang interop): {r:?}",
        );
    }

    /// All three cosigs are valid → quorum=3 also passes.
    #[test]
    fn verify_python_signed_cert_quorum_3() {
        let cert = load_signed_cert();
        let r = verify_attestation_cert(&cert, Some(APPLICANT_PUBKEY), 3, None, NOW_INSIDE);
        assert!(r.is_ok(), "3 valid cosigs must satisfy quorum=3: {r:?}");
    }

    #[test]
    fn quorum_above_n_fails() {
        let cert = load_signed_cert();
        let r = verify_attestation_cert(&cert, Some(APPLICANT_PUBKEY), 4, None, NOW_INSIDE);
        assert_eq!(
            r,
            Err(VerifyError::BelowQuorum {
                valid: 3,
                required: 4
            }),
        );
    }

    #[test]
    fn expired_cert_fails() {
        let cert = load_signed_cert();
        let r = verify_attestation_cert(&cert, Some(APPLICANT_PUBKEY), 2, None, NOW_AFTER_EXPIRY);
        assert_eq!(r, Err(VerifyError::Expired));
    }

    #[test]
    fn applicant_mismatch_fails() {
        let cert = load_signed_cert();
        let wrong = "bb".repeat(32);
        let r = verify_attestation_cert(&cert, Some(&wrong), 2, None, NOW_INSIDE);
        assert_eq!(r, Err(VerifyError::ApplicantMismatch));
    }

    #[test]
    fn tampered_schema_fails() {
        let mut cert = load_signed_cert();
        cert.payload.schema = "evil-schema".to_string();
        let r = verify_attestation_cert(&cert, Some(APPLICANT_PUBKEY), 2, None, NOW_INSIDE);
        assert!(matches!(r, Err(VerifyError::UnsupportedSchema(_))));
    }

    /// Flip a byte in one cosig's signature — that cosig becomes
    /// invalid. With quorum=2 the cert still passes (2 others valid);
    /// with quorum=3 it fails.
    #[test]
    fn tampered_cosig_drops_quorum() {
        let mut cert = load_signed_cert();
        let mut sig = cert.validator_cosigs[0].signature.clone();
        sig.replace_range(0..2, "ff");
        cert.validator_cosigs[0].signature = sig;

        let r2 = verify_attestation_cert(&cert, Some(APPLICANT_PUBKEY), 2, None, NOW_INSIDE);
        assert!(r2.is_ok(), "quorum=2 should still hold: {r2:?}");

        let r3 = verify_attestation_cert(&cert, Some(APPLICANT_PUBKEY), 3, None, NOW_INSIDE);
        assert_eq!(
            r3,
            Err(VerifyError::BelowQuorum {
                valid: 2,
                required: 3
            }),
        );
    }

    /// Tamper a non-schema, non-applicant payload field — all cosigs
    /// now sign over different bytes than the verifier hashes, so all
    /// fail. (We pick `eval_version` because it doesn't trigger the
    /// schema or applicant short-circuits.)
    #[test]
    fn payload_tamper_invalidates_all_cosigs() {
        let mut cert = load_signed_cert();
        cert.payload.eval_version = "tampered".to_string();
        let r = verify_attestation_cert(&cert, None, 2, None, NOW_INSIDE);
        assert_eq!(
            r,
            Err(VerifyError::BelowQuorum {
                valid: 0,
                required: 2
            }),
        );
    }

    // ---------------------------------------------------------------
    // ChallengeResponse + EvalResult byte-parity.
    //
    // Exercises the recursive canonical-JSON paths: BTreeMap key
    // sorting for eval_results, nested serde_json::Value sorting for
    // the embedded ICP envelope + task-specific output dicts, and the
    // Option<Value> → null serialization.
    // ---------------------------------------------------------------

    fn sample_response_payload() -> ChallengeResponsePayload {
        // Embedded ICP envelope matching the Python fixture's
        // ICPEnvelope construction (gyza-rs/scripts/regenerate_capability_fixtures.py).
        let env = serde_json::json!({
            "action_id": "act-0001",
            "agent_pubkey": "bb".repeat(32),
            "capability_manifest_hash": "cc".repeat(32),
            "duration_ms": 100,
            "inference_backend": "mock",
            "input_hashes": ["0".repeat(64)],
            "intent_id": "int-0001",
            "model_identifier": "mock-eval",
            "output_hash": "dd".repeat(32),
            "parent_envelope_hash": serde_json::Value::Null,
            "schema_version": 1,
            "signature": "ee".repeat(64),
            "timestamp_ns": 1_700_000_050_000_000_000_i64,
            "tokens_in": 10,
            "tokens_out": 20,
        });

        let mut eval_results: BTreeMap<String, EvalResult> = BTreeMap::new();
        // Keys deliberately inserted out of sorted order — BTreeMap
        // re-orders them. The byte-parity test catches any HashMap
        // regression on this path.
        eval_results.insert(
            "task_b".to_string(),
            EvalResult {
                duration_s: 0.5,
                envelope: None,
                error: String::new(),
                output: Some(serde_json::json!({
                    "count": 3,
                    "extensions": [".py", ".md"],
                })),
                output_text: "ok".to_string(),
                succeeded: true,
                task_id: "task_b".to_string(),
            },
        );
        eval_results.insert(
            "task_a".to_string(),
            EvalResult {
                duration_s: 1.5,
                envelope: Some(env),
                error: String::new(),
                output: Some(serde_json::json!({
                    "sum": 44,
                    "items": [3, 7, 11, 23],
                })),
                output_text: "computed".to_string(),
                succeeded: true,
                task_id: "task_a".to_string(),
            },
        );

        ChallengeResponsePayload {
            applicant_agent_pubkey: "bb".repeat(32),
            applicant_compositor_pubkey: "cc".repeat(32),
            cert_payload: AttestationCertPayload {
                applicant_compositor_pubkey: "cc".repeat(32),
                eval_version: "v1".to_string(),
                expires_at_ns: 1_700_001_000_000_000_000,
                issued_at_ns: 1_700_000_000_000_000_000,
                schema: CERT_SCHEMA.to_string(),
            },
            challenge_id: "chal-0001".to_string(),
            eval_results,
            nonce_echo: "00112233445566778899aabbccddeeff".to_string(),
        }
    }

    /// Byte-parity: Rust response_canonical_bytes must match Python
    /// _response_canonical_bytes output exactly, including
    /// (a) BTreeMap eval_results sorting, (b) recursive sort_keys on
    /// the embedded envelope + output dicts, (c) None → null.
    /// Fixture from regenerate_capability_fixtures.py (1554 bytes).
    #[test]
    fn response_canonical_bytes_parity_with_python() {
        let payload = sample_response_payload();
        let bytes = response_canonical_bytes(&payload).unwrap();
        let expected_hex = concat!(
            "7b226170706c6963616e745f6167656e745f7075626b6579223a226262626262",
            "6262626262626262626262626262626262626262626262626262626262626262",
            "626262626262626262626262626262626262626262626262626262222c226170",
            "706c6963616e745f636f6d706f7369746f725f7075626b6579223a2263636363",
            "6363636363636363636363636363636363636363636363636363636363636363",
            "63636363636363636363636363636363636363636363636363636363222c2263",
            "6572745f7061796c6f6164223a7b226170706c6963616e745f636f6d706f7369",
            "746f725f7075626b6579223a2263636363636363636363636363636363636363",
            "6363636363636363636363636363636363636363636363636363636363636363",
            "63636363636363636363636363222c226576616c5f76657273696f6e223a2276",
            "31222c22657870697265735f61745f6e73223a31373030303031303030303030",
            "3030303030302c226973737565645f61745f6e73223a31373030303030303030",
            "3030303030303030302c22736368656d61223a2267797a612e61747465737461",
            "74696f6e2e74696572332f7631227d2c226368616c6c656e67655f6964223a22",
            "6368616c2d30303031222c226576616c5f726573756c7473223a7b227461736b",
            "5f61223a7b226475726174696f6e5f73223a312e352c22656e76656c6f706522",
            "3a7b22616374696f6e5f6964223a226163742d30303031222c226167656e745f",
            "7075626b6579223a226262626262626262626262626262626262626262626262",
            "6262626262626262626262626262626262626262626262626262626262626262",
            "626262626262626262222c226361706162696c6974795f6d616e69666573745f",
            "68617368223a2263636363636363636363636363636363636363636363636363",
            "6363636363636363636363636363636363636363636363636363636363636363",
            "63636363636363222c226475726174696f6e5f6d73223a3130302c22696e6665",
            "72656e63655f6261636b656e64223a226d6f636b222c22696e7075745f686173",
            "686573223a5b2230303030303030303030303030303030303030303030303030",
            "3030303030303030303030303030303030303030303030303030303030303030",
            "30303030303030225d2c22696e74656e745f6964223a22696e742d3030303122",
            "2c226d6f64656c5f6964656e746966696572223a226d6f636b2d6576616c222c",
            "226f75747075745f68617368223a226464646464646464646464646464646464",
            "6464646464646464646464646464646464646464646464646464646464646464",
            "646464646464646464646464646464222c22706172656e745f656e76656c6f70",
            "655f68617368223a6e756c6c2c22736368656d615f76657273696f6e223a312c",
            "227369676e6174757265223a2265656565656565656565656565656565656565",
            "6565656565656565656565656565656565656565656565656565656565656565",
            "6565656565656565656565656565656565656565656565656565656565656565",
            "6565656565656565656565656565656565656565656565656565656565656565",
            "65656565656565656565656565222c2274696d657374616d705f6e73223a3137",
            "30303030303035303030303030303030302c22746f6b656e735f696e223a3130",
            "2c22746f6b656e735f6f7574223a32307d2c226572726f72223a22222c226f75",
            "74707574223a7b226974656d73223a5b332c372c31312c32335d2c2273756d22",
            "3a34347d2c226f75747075745f74657874223a22636f6d7075746564222c2273",
            "7563636565646564223a747275652c227461736b5f6964223a227461736b5f61",
            "227d2c227461736b5f62223a7b226475726174696f6e5f73223a302e352c2265",
            "6e76656c6f7065223a6e756c6c2c226572726f72223a22222c226f7574707574",
            "223a7b22636f756e74223a332c22657874656e73696f6e73223a5b222e707922",
            "2c222e6d64225d7d2c226f75747075745f74657874223a226f6b222c22737563",
            "636565646564223a747275652c227461736b5f6964223a227461736b5f62227d",
            "7d2c226e6f6e63655f6563686f223a2230303131323233333434353536363737",
            "38383939616162626363646465656666227d",
        );
        let expected = hex::decode(expected_hex).expect("test fixture must be valid hex");
        assert_eq!(
            bytes.len(),
            expected.len(),
            "length mismatch (rust={}, python={})",
            bytes.len(),
            expected.len(),
        );
        assert_eq!(
            bytes, expected,
            "response_canonical_bytes diverged from Python; \
             regenerate fixtures with scripts/regenerate_capability_fixtures.py",
        );
    }

    /// The full ChallengeResponse (payload + applicant_signature) is a
    /// wire format — its serialization order isn't byte-parity-tested
    /// (only the canonical payload matters for signing). But it must
    /// roundtrip cleanly through serde so deserialization works on the
    /// validator side.
    #[test]
    fn challenge_response_wire_roundtrip() {
        let resp = ChallengeResponse {
            payload: sample_response_payload(),
            applicant_signature: "deadbeef".to_string(),
        };
        let json = serde_json::to_string(&resp).unwrap();
        let back: ChallengeResponse = serde_json::from_str(&json).unwrap();
        assert_eq!(resp, back);
    }

    /// Sanity: cert structure roundtrips with multiple cosigs.
    #[test]
    fn attestation_cert_roundtrip() {
        let cert = AttestationCert {
            payload: sample_attestation_payload(),
            validator_cosigs: vec![
                ValidatorCosig {
                    cosigned_at_ns: 1_700_000_100_000_000_000,
                    signature: "aaaa".to_string(),
                    validator_pubkey: "v1".to_string(),
                },
                ValidatorCosig {
                    cosigned_at_ns: 1_700_000_200_000_000_000,
                    signature: "bbbb".to_string(),
                    validator_pubkey: "v2".to_string(),
                },
            ],
        };
        let json = serde_json::to_string(&cert).unwrap();
        let back: AttestationCert = serde_json::from_str(&json).unwrap();
        assert_eq!(cert, back);
    }
}
