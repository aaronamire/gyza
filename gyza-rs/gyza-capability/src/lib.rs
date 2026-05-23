//! Tier-3 capability attestation — canonical-bytes substrate.
//!
//! This crate ports `gyza.network.capability_protocol` (Python) to Rust
//! with byte-for-byte parity. Both the verifying side and the
//! cryptographic signing operations are present; only the eval-task
//! execution machinery and the top-level orchestration loop remain.
//!
//! What lives here:
//!
//!   - `ChallengePayload` / `Challenge`  — validator → applicant
//!   - `AttestationCertPayload`          — the bytes every validator co-signs
//!   - `ValidatorCosig`                  — one validator's signature
//!   - `AttestationCert`                 — payload + ≥k cosigs
//!   - `EvalResult`                      — one task's eval outcome
//!   - `ChallengeResponsePayload` / `ChallengeResponse` — applicant → validator
//!   - `challenge_canonical_bytes(...)` / `attestation_payload_canonical_bytes(...)`
//!     / `response_canonical_bytes(...)`
//!   - `verify_attestation_cert(...)`    — independent consumer-side
//!     cert verification (schema / applicant / expiry / quorum cosig
//!     check). Cross-language interop: tests deserialize a
//!     Python-signed cert and verify it under this Rust function.
//!   - `Validator` (issue_challenge, cosign, verify_response) /
//!     `Applicant` (sign_response) — the signing + decision side.
//!     Ed25519 is deterministic (RFC 8032), so a Rust validator
//!     co-signing a payload produces the BYTE-IDENTICAL signature Python
//!     produces (tested) — Rust and Python validators are
//!     interchangeable in a quorum, not just mutually verifiable.
//!     `verify_response` performs all the crypto/sanity checks and
//!     co-signs on success; the eval-OUTPUT check is a pluggable
//!     closure (see below).
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
//! What is NOT covered yet (the low-differentiation tail):
//!
//!   - The eval-OUTPUT check that `verify_response` takes as a closure.
//!     Implementing it for real means porting the `EvalTask` ecosystem
//!     from `gyza.capability_eval` (the six deterministic tasks +
//!     their expected-output logic) and verifying each eval ICP
//!     envelope via `gyza-icp`. This crate ports `EvalResult` (the
//!     wire-carried OUTCOME type) but not the task definitions.
//!   - `run_attestation` orchestration (drives a full applicant ⇄
//!     validators round end to end).
//!
//! Cross-references:
//!
//!   - `gyza/network/capability_protocol.py` — Python reference impl
//!   - `gyza-rs/scripts/regenerate_capability_fixtures.py` — parity fixture
//!     generator (run before changing any field semantics).

use std::collections::{BTreeMap, HashSet};

use gyza_crypto::Signer;
use serde::{Deserialize, Serialize};
use serde_json::Value;

// ---------------------------------------------------------------------------
// Protocol constants — mirror gyza/network/capability_protocol.py.
// ---------------------------------------------------------------------------

/// The schema string a Tier-3 cert must carry. Mirrored verbatim.
pub const CERT_SCHEMA: &str = "gyza.attestation.tier3/v1";

/// Wire-format major version used by the Python implementation.
pub const PROTOCOL_VERSION: &str = "v1";

/// Eval-suite version a cert must declare (gyza.capability_eval).
pub const EVAL_VERSION: &str = "v1";

/// Maximum cert lifetime a validator will co-sign (90 days, in ns) —
/// a malicious applicant proposing a 100-year cert shouldn't get a cosig.
pub const MAX_CERT_LIFETIME_NS: i64 = 90 * 24 * 60 * 60 * 1_000_000_000;

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

/// Validator → applicant: the result of verifying a `ChallengeResponse`.
/// `accepted=true` carries a cosig the applicant aggregates into the
/// cert; `accepted=false` carries a short reason for diagnostics.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChallengeOutcome {
    pub accepted: bool,
    pub challenge_id: String,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub cosig: Option<ValidatorCosig>,
    #[serde(default)]
    pub reason: String,
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
// Signing side — Validator + Applicant.
//
// The capability protocol signs the RAW canonical bytes of each
// structure (NOT a BLAKE3 hash of them — that distinguishes it from
// gyza-icp envelopes, which sign the hash). Python:
//   make_seed_signer -> sk.sign(payload).hex()
//   _verify_with     -> pk.verify(sig, payload)
// gyza_crypto::Signer::sign / gyza_crypto::verify operate over the raw
// bytes too, so signatures are interoperable with Python verbatim.
//
// Ed25519 (RFC 8032) is DETERMINISTIC — no per-signature nonce. So for
// a fixed seed and fixed canonical bytes, Rust and Python produce the
// IDENTICAL signature. The tests assert exactly this against the Python
// fixture: a Rust validator and a Python validator are interchangeable
// in a quorum, not merely mutually verifiable.
// ---------------------------------------------------------------------------

/// A validator identity: holds the Ed25519 signing key and exposes the
/// two signing operations a validator performs.
pub struct Validator {
    signer: Signer,
    pubkey_hex: String,
}

impl Validator {
    /// Build a validator from a 32-byte Ed25519 seed.
    pub fn from_seed(seed: &[u8; 32]) -> Self {
        let signer = Signer::from_seed(seed);
        let pubkey_hex = hex::encode(signer.pubkey_bytes());
        Self { signer, pubkey_hex }
    }

    /// This validator's public key, hex-encoded.
    pub fn pubkey_hex(&self) -> &str {
        &self.pubkey_hex
    }

    /// Issue a signed `Challenge` to an applicant. `validator_pubkey` is
    /// filled from this validator's own key.
    pub fn issue_challenge(
        &self,
        challenge_id: impl Into<String>,
        eval_version: impl Into<String>,
        task_ids: Vec<String>,
        nonce: impl Into<String>,
        issued_at_ns: i64,
        expires_at_ns: i64,
    ) -> Result<Challenge, CapabilityError> {
        let payload = ChallengePayload {
            challenge_id: challenge_id.into(),
            eval_version: eval_version.into(),
            expires_at_ns,
            issued_at_ns,
            nonce: nonce.into(),
            task_ids,
            validator_pubkey: self.pubkey_hex.clone(),
        };
        let bytes = challenge_canonical_bytes(&payload)?;
        let signature = self.signer.sign_hex(&bytes);
        Ok(Challenge { payload, signature })
    }

    /// Co-sign an `AttestationCertPayload`, contributing one cosig toward
    /// quorum. Every validator signs the SAME canonical payload bytes —
    /// that identical-bytes invariant is what lets the quorum aggregate.
    pub fn cosign(
        &self,
        payload: &AttestationCertPayload,
        cosigned_at_ns: i64,
    ) -> Result<ValidatorCosig, CapabilityError> {
        let bytes = attestation_payload_canonical_bytes(payload)?;
        let signature = self.signer.sign_hex(&bytes);
        Ok(ValidatorCosig {
            cosigned_at_ns,
            signature,
            validator_pubkey: self.pubkey_hex.clone(),
        })
    }
}

/// An applicant identity: holds the compositor Ed25519 signing key and
/// signs the `ChallengeResponse` it sends to validators.
pub struct Applicant {
    signer: Signer,
    compositor_pubkey_hex: String,
}

impl Applicant {
    /// Build an applicant from its 32-byte compositor Ed25519 seed.
    pub fn from_compositor_seed(seed: &[u8; 32]) -> Self {
        let signer = Signer::from_seed(seed);
        let compositor_pubkey_hex = hex::encode(signer.pubkey_bytes());
        Self {
            signer,
            compositor_pubkey_hex,
        }
    }

    /// This applicant's compositor public key, hex-encoded.
    pub fn compositor_pubkey_hex(&self) -> &str {
        &self.compositor_pubkey_hex
    }

    /// Sign a fully-formed `ChallengeResponsePayload` and wrap it into
    /// the wire-format `ChallengeResponse`. The caller is responsible for
    /// having set `payload.applicant_compositor_pubkey` to this
    /// applicant's key; in debug builds we assert it.
    pub fn sign_response(
        &self,
        payload: ChallengeResponsePayload,
    ) -> Result<ChallengeResponse, CapabilityError> {
        debug_assert_eq!(
            payload.applicant_compositor_pubkey, self.compositor_pubkey_hex,
            "payload compositor pubkey must match the signing applicant",
        );
        let bytes = response_canonical_bytes(&payload)?;
        let signature = self.signer.sign_hex(&bytes);
        Ok(ChallengeResponse {
            payload,
            applicant_signature: signature,
        })
    }
}

impl Validator {
    /// Verify a `ChallengeResponse` against a `Challenge` this validator
    /// issued and, on success, co-sign the cert payload. Mirrors Python
    /// `Validator.verify_response`.
    ///
    /// `eval_check` is the pluggable eval-output verification step
    /// (Python's `verify_eval_results`): given the response, it returns
    /// `Ok(())` if the eval results are valid, or `Err(reason)`. It is a
    /// parameter rather than baked in because it depends on the
    /// `EvalTask` definitions + ICP-envelope verification (separate
    /// ports) — this keeps the crypto-meaningful decision logic here and
    /// the task scaffolding pluggable. A caller with no eval to check
    /// passes `|_| Ok(())`.
    pub fn verify_response<F>(
        &self,
        challenge: &Challenge,
        response: &ChallengeResponse,
        now_ns: i64,
        clock_skew_ns: i64,
        eval_check: F,
    ) -> ChallengeOutcome
    where
        F: FnOnce(&ChallengeResponse) -> Result<(), String>,
    {
        let cid = &challenge.payload.challenge_id;
        let reject = |reason: &str| ChallengeOutcome {
            accepted: false,
            challenge_id: cid.clone(),
            cosig: None,
            reason: reason.to_string(),
        };

        let rp = &response.payload;
        if rp.challenge_id != challenge.payload.challenge_id {
            return reject("response.challenge_id mismatch");
        }
        if rp.nonce_echo != challenge.payload.nonce {
            return reject("nonce_echo mismatch");
        }
        if rp.applicant_compositor_pubkey != rp.cert_payload.applicant_compositor_pubkey {
            return reject(
                "response.applicant_compositor_pubkey != cert_payload.applicant_compositor_pubkey",
            );
        }

        // Applicant signature over the canonical response bytes.
        let sig_ok = match (
            response_canonical_bytes(rp),
            hex::decode(&rp.applicant_compositor_pubkey),
            hex::decode(&response.applicant_signature),
        ) {
            (Ok(bytes), Ok(pk), Ok(sig)) => gyza_crypto::verify(&pk, &bytes, &sig).is_ok(),
            _ => false,
        };
        if !sig_ok {
            return reject("applicant signature invalid");
        }

        // Cert payload sanity.
        let p = &rp.cert_payload;
        if p.schema != CERT_SCHEMA {
            return reject("unsupported cert schema");
        }
        if p.eval_version != EVAL_VERSION {
            return reject("eval_version mismatch");
        }
        if p.issued_at_ns.abs_diff(now_ns) > clock_skew_ns.unsigned_abs() {
            return reject("cert.issued_at_ns outside clock-skew window");
        }
        if p.expires_at_ns <= p.issued_at_ns {
            return reject("cert.expires_at_ns <= issued_at_ns");
        }
        if p.expires_at_ns - p.issued_at_ns > MAX_CERT_LIFETIME_NS {
            return reject("cert lifetime exceeds 90 days");
        }

        // Pluggable eval-output verification (Python: verify_eval_results).
        if let Err(reason) = eval_check(response) {
            return reject(&format!("eval failed: {reason}"));
        }

        // All checks pass — co-sign the cert payload.
        match self.cosign(p, now_ns) {
            Ok(cosig) => ChallengeOutcome {
                accepted: true,
                challenge_id: cid.clone(),
                cosig: Some(cosig),
                reason: String::new(),
            },
            Err(e) => reject(&format!("cosign failed: {e}")),
        }
    }
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

    // ---------------------------------------------------------------
    // Signing side — Validator / Applicant.
    // ---------------------------------------------------------------

    /// The cert payload the Python fixture's three validators co-signed
    /// (matches `cert_payload` in regenerate_capability_fixtures.py's
    /// signed_attestation_cert block).
    fn fixture_cosigned_payload() -> AttestationCertPayload {
        AttestationCertPayload {
            applicant_compositor_pubkey: "aa".repeat(32),
            eval_version: "eval-v1".to_string(),
            expires_at_ns: 1_700_000_300_000_000_000,
            issued_at_ns: 1_700_000_000_000_000_000,
            schema: CERT_SCHEMA.to_string(),
        }
    }

    /// A validator issues a challenge; the signature verifies under the
    /// validator's own pubkey (round trip through canonical bytes).
    #[test]
    fn validator_issue_challenge_roundtrip() {
        let v = Validator::from_seed(&[7u8; 32]);
        let chal = v
            .issue_challenge(
                "c1",
                "eval-v1",
                vec!["t1".to_string(), "t2".to_string()],
                "nonce-abc",
                100,
                200,
            )
            .unwrap();
        assert_eq!(chal.payload.validator_pubkey, v.pubkey_hex());
        let bytes = challenge_canonical_bytes(&chal.payload).unwrap();
        let pk = hex::decode(v.pubkey_hex()).unwrap();
        let sig = hex::decode(&chal.signature).unwrap();
        assert!(
            gyza_crypto::verify(&pk, &bytes, &sig).is_ok(),
            "validator's own challenge signature must verify",
        );
    }

    /// THE strongest cross-language result: a Rust validator co-signing
    /// the same payload as the Python fixture produces the BYTE-IDENTICAL
    /// signature (Ed25519 is deterministic, RFC 8032). This means Rust
    /// and Python validators are *interchangeable* in a quorum, not just
    /// mutually verifiable.
    #[test]
    fn rust_cosig_is_byte_identical_to_python() {
        let payload = fixture_cosigned_payload();
        let v1 = Validator::from_seed(&[1u8; 32]);
        let cosig = v1.cosign(&payload, 1_700_000_100_000_000_000).unwrap();

        // From regenerate_capability_fixtures.py's signed cert, validator 1:
        let py_pubkey = "8a88e3dd7409f195fd52db2d3cba5d72ca6709bf1d94121bf3748801b40f6f5c";
        let py_signature = concat!(
            "28337fcb4d2b4576046cd7699b5d0daba22313b465e2679edbcc17bd703e00f1",
            "839c5fae2a2b2bc9ed0d34c689d32d3740b12c8f1745a9136c6475947f51700b",
        );
        assert_eq!(
            cosig.validator_pubkey, py_pubkey,
            "Rust pubkey from seed [1;32] must match Python's",
        );
        assert_eq!(
            cosig.signature, py_signature,
            "Rust Ed25519 cosig must be byte-identical to Python's \
             (deterministic signing over identical canonical bytes)",
        );
    }

    /// A cert assembled entirely from Rust-signed cosigs passes the Rust
    /// verifier — the signing side feeds the verifying side end to end.
    #[test]
    fn rust_signed_cert_passes_rust_verify() {
        let payload = fixture_cosigned_payload();
        let v1 = Validator::from_seed(&[1u8; 32]);
        let v2 = Validator::from_seed(&[2u8; 32]);
        let cert = AttestationCert {
            payload: payload.clone(),
            validator_cosigs: vec![
                v1.cosign(&payload, 1_700_000_100_000_000_000).unwrap(),
                v2.cosign(&payload, 1_700_000_100_000_000_001).unwrap(),
            ],
        };
        let r = verify_attestation_cert(
            &cert,
            Some(&"aa".repeat(32)),
            2,
            None,
            1_700_000_200_000_000_000,
        );
        assert!(r.is_ok(), "Rust-signed cert must pass Rust verify: {r:?}");
    }

    /// Applicant signs a response; the signature verifies under the
    /// applicant's compositor pubkey.
    #[test]
    fn applicant_sign_response_roundtrip() {
        // Use a seed whose pubkey we then stamp into the payload so the
        // debug_assert in sign_response holds.
        let app = Applicant::from_compositor_seed(&[9u8; 32]);
        let mut payload = sample_response_payload();
        payload.applicant_compositor_pubkey = app.compositor_pubkey_hex().to_string();
        // cert_payload's applicant pubkey is independent; leave as-is.
        let resp = app.sign_response(payload).unwrap();

        let bytes = response_canonical_bytes(&resp.payload).unwrap();
        let pk = hex::decode(app.compositor_pubkey_hex()).unwrap();
        let sig = hex::decode(&resp.applicant_signature).unwrap();
        assert!(
            gyza_crypto::verify(&pk, &bytes, &sig).is_ok(),
            "applicant's own response signature must verify",
        );
    }

    // ---------------------------------------------------------------
    // Validator::verify_response.
    // ---------------------------------------------------------------

    /// Build a (validator, applicant, challenge, signed response) tuple
    /// that should pass verification at `now`. `nonce_echo` and
    /// `cert_issued_at` are overridable so rejection tests can perturb
    /// one field at a time.
    fn verify_fixture(
        now: i64,
        nonce_echo: &str,
        cert_issued_at: i64,
    ) -> (Validator, Challenge, ChallengeResponse) {
        let validator = Validator::from_seed(&[5u8; 32]);
        let applicant = Applicant::from_compositor_seed(&[6u8; 32]);
        let challenge = validator
            .issue_challenge(
                "c1",
                EVAL_VERSION,
                vec!["task_a".to_string()],
                "noncexyz",
                now,
                now + 1_000_000,
            )
            .unwrap();
        let app_pk = applicant.compositor_pubkey_hex().to_string();
        let payload = ChallengeResponsePayload {
            applicant_agent_pubkey: "ab".repeat(32),
            applicant_compositor_pubkey: app_pk.clone(),
            cert_payload: AttestationCertPayload {
                applicant_compositor_pubkey: app_pk,
                eval_version: EVAL_VERSION.to_string(),
                expires_at_ns: cert_issued_at + 1_000_000,
                issued_at_ns: cert_issued_at,
                schema: CERT_SCHEMA.to_string(),
            },
            challenge_id: "c1".to_string(),
            eval_results: BTreeMap::new(),
            nonce_echo: nonce_echo.to_string(),
        };
        let response = applicant.sign_response(payload).unwrap();
        (validator, challenge, response)
    }

    #[test]
    fn verify_response_happy_path_cosigns() {
        let now = 1_700_000_000_000_000_000;
        let (validator, challenge, response) = verify_fixture(now, "noncexyz", now);
        let outcome =
            validator.verify_response(&challenge, &response, now, MAX_CLOCK_SKEW_NS, |_| Ok(()));
        assert!(outcome.accepted, "rejected: {}", outcome.reason);
        let cosig = outcome.cosig.expect("accepted outcome must carry a cosig");
        // The cosig must verify against the cert payload.
        let bytes = attestation_payload_canonical_bytes(&response.payload.cert_payload).unwrap();
        let pk = hex::decode(&cosig.validator_pubkey).unwrap();
        let sig = hex::decode(&cosig.signature).unwrap();
        assert!(gyza_crypto::verify(&pk, &bytes, &sig).is_ok());
        assert_eq!(cosig.validator_pubkey, validator.pubkey_hex());
    }

    #[test]
    fn verify_response_rejects_nonce_mismatch() {
        let now = 1_700_000_000_000_000_000;
        let (validator, challenge, response) = verify_fixture(now, "WRONG-NONCE", now);
        let outcome =
            validator.verify_response(&challenge, &response, now, MAX_CLOCK_SKEW_NS, |_| Ok(()));
        assert!(!outcome.accepted);
        assert_eq!(outcome.reason, "nonce_echo mismatch");
        assert!(outcome.cosig.is_none());
    }

    #[test]
    fn verify_response_rejects_eval_failure() {
        let now = 1_700_000_000_000_000_000;
        let (validator, challenge, response) = verify_fixture(now, "noncexyz", now);
        let outcome =
            validator.verify_response(&challenge, &response, now, MAX_CLOCK_SKEW_NS, |_| {
                Err("task_a output mismatch".to_string())
            });
        assert!(!outcome.accepted);
        assert!(
            outcome.reason.contains("eval failed")
                && outcome.reason.contains("task_a output mismatch"),
            "reason was: {}",
            outcome.reason,
        );
    }

    #[test]
    fn verify_response_rejects_tampered_applicant_signature() {
        let now = 1_700_000_000_000_000_000;
        let (validator, challenge, mut response) = verify_fixture(now, "noncexyz", now);
        // Flip a byte of the applicant signature.
        response.applicant_signature.replace_range(0..2, "ff");
        let outcome =
            validator.verify_response(&challenge, &response, now, MAX_CLOCK_SKEW_NS, |_| Ok(()));
        assert!(!outcome.accepted);
        assert_eq!(outcome.reason, "applicant signature invalid");
    }

    #[test]
    fn verify_response_rejects_clock_skew() {
        let now = 1_700_000_000_000_000_000;
        // Cert issued 2 hours before "now" — outside the 1h skew window.
        let cert_issued = now - 2 * 60 * 60 * 1_000_000_000;
        let (validator, challenge, response) = verify_fixture(now, "noncexyz", cert_issued);
        let outcome =
            validator.verify_response(&challenge, &response, now, MAX_CLOCK_SKEW_NS, |_| Ok(()));
        assert!(!outcome.accepted);
        assert_eq!(
            outcome.reason,
            "cert.issued_at_ns outside clock-skew window"
        );
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
