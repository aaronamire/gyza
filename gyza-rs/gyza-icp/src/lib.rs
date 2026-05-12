//! Intent Chain Protocol envelopes — hash-chained Ed25519-signed
//! provenance records.
//!
//! This crate ports `gyza.icp` from Python to Rust with byte-for-byte
//! parity on canonical-JSON serialization. The protocol's correctness
//! depends on Python and Rust producing IDENTICAL bytes for the same
//! logical envelope; any drift breaks signature verification across
//! the language boundary.
//!
//! Canonical-JSON discipline:
//!
//!   - Python: `json.dumps(d, sort_keys=True, separators=(",", ":"))`
//!   - Rust  : `serde_json::to_string(payload)` with the struct's
//!     field order matching alphabetized key order.
//!
//! That second clause is **load-bearing**. The [`EnvelopePayload`]
//! struct lists fields in EXACTLY the order that
//! `sort_keys=True` would produce. Reordering the struct fields breaks
//! the canonical bytes and silently invalidates every signature
//! produced by the Python implementation.
//!
//! ASCII-only invariant: in practice no ICPEnvelope field contains
//! non-ASCII characters (all are UUIDs, hex strings, or identifiers
//! like `"anthropic:claude-sonnet-4-5"`). Python's default
//! `ensure_ascii=True` and Rust's default UTF-8 output are
//! byte-identical for ASCII content. If a future field needs
//! non-ASCII, this needs explicit reconciliation.
//!
//! Signing discipline:
//!
//!   - The signature is `Ed25519(sign_key, BLAKE3(canonical_bytes))`.
//!     We sign the BLAKE3 HASH, not the canonical bytes themselves.
//!     This matches Python's `gyza.icp::sign_envelope`. Don't sign
//!     the raw bytes — that would be a different signature and
//!     verification would fail cross-language.
//!
//! Cross-references:
//!
//!   - `gyza/icp.py` — Python reference implementation
//!   - `docs/invariants.md` § ICP envelope (INV-ICP-1..8)
//!   - `docs/state-machines.md` — envelope flow through runner
//!   - `gyza-rs/scripts/regenerate_icp_fixtures.py` — parity fixture
//!     generator (run before changing any field semantics).

use gyza_crypto::{ED25519_SEED_LEN, Signer, hash, verify};
use serde::{Deserialize, Serialize};

/// Errors that can arise from envelope operations.
#[derive(Debug, thiserror::Error)]
pub enum IcpError {
    #[error("Ed25519 seed must be {expected} bytes, got {got}")]
    BadSeedLength { expected: usize, got: usize },
    #[error("envelope has no signature; cannot verify")]
    Unsigned,
    #[error("signature is malformed (expected hex)")]
    MalformedSignature,
    #[error("agent_pubkey is malformed (expected hex of length {expected_hex_len})")]
    MalformedAgentPubkey { expected_hex_len: usize },
    #[error("signature verification failed")]
    VerificationFailed,
    #[error("canonical-JSON encoding failed: {0}")]
    JsonEncode(#[from] serde_json::Error),
    #[error("crypto error: {0}")]
    Crypto(#[from] gyza_crypto::CryptoError),
    #[error("hex decoding failed: {0}")]
    HexDecode(#[from] hex::FromHexError),
}

/// The payload of an ICP envelope — every field that gets included
/// in the canonical bytes that the signature covers. Excludes the
/// `signature` itself.
///
/// **Field order is load-bearing.** Listed alphabetically so
/// serde_json emits them in the same order Python's
/// `sort_keys=True` does. DO NOT REORDER. If you add a new field,
/// (a) it must land at its alphabetically-correct position, and
/// (b) you must regenerate the parity fixtures and verify they
/// match the Python output exactly.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EnvelopePayload {
    pub action_id: String,
    pub agent_pubkey: String,
    pub capability_manifest_hash: String,
    pub duration_ms: i64,
    pub inference_backend: String,
    pub input_hashes: Vec<String>,
    pub intent_id: String,
    pub model_identifier: String,
    pub output_hash: String,
    /// `null` in JSON when this is the root envelope of a chain.
    pub parent_envelope_hash: Option<String>,
    pub schema_version: i64,
    pub timestamp_ns: i64,
    pub tokens_in: i64,
    pub tokens_out: i64,
}

/// A signed ICP envelope = payload + Ed25519 signature (hex).
///
/// Wire format note: when serializing the WHOLE envelope (including
/// signature) for storage or display, the `signature` field appears
/// AFTER all payload fields by Python's `sort_keys=True` ordering —
/// alphabetically, "signature" comes after "tokens_out". Hence the
/// struct field order here.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignedEnvelope {
    #[serde(flatten)]
    pub payload: EnvelopePayload,
    pub signature: String,
}

/// Compute canonical-JSON bytes of the payload. This is what gets
/// BLAKE3-hashed and signed.
///
/// Python equivalent: `gyza.icp::_payload_bytes(envelope)`.
pub fn canonical_bytes(payload: &EnvelopePayload) -> Result<Vec<u8>, IcpError> {
    Ok(serde_json::to_vec(payload)?)
}

/// BLAKE3-hex of an envelope's canonical bytes — the envelope's
/// stable identifier for chain references.
///
/// Python equivalent: `gyza.icp::compute_envelope_hash(envelope)`.
pub fn envelope_hash(payload: &EnvelopePayload) -> Result<String, IcpError> {
    let bytes = canonical_bytes(payload)?;
    Ok(hex::encode(hash(&bytes)))
}

/// Sign an envelope payload with a 32-byte Ed25519 seed.
///
/// Returns a [`SignedEnvelope`] with the hex-encoded signature
/// attached. The signature covers `BLAKE3(canonical_bytes)`, NOT
/// the canonical bytes directly.
///
/// Python equivalent: `gyza.icp::sign_envelope(env, seed_bytes)`.
pub fn sign_envelope(payload: EnvelopePayload, seed: &[u8]) -> Result<SignedEnvelope, IcpError> {
    if seed.len() != ED25519_SEED_LEN {
        return Err(IcpError::BadSeedLength {
            expected: ED25519_SEED_LEN,
            got: seed.len(),
        });
    }
    let mut seed_array = [0u8; ED25519_SEED_LEN];
    seed_array.copy_from_slice(seed);
    let signer = Signer::from_seed(&seed_array);

    let bytes = canonical_bytes(&payload)?;
    let payload_hash = hash(&bytes);
    let sig_hex = signer.sign_hex(&payload_hash);

    Ok(SignedEnvelope {
        payload,
        signature: sig_hex,
    })
}

/// Verify a signed envelope's signature against a public key.
///
/// The pubkey can be supplied either as raw 32 bytes OR taken from
/// the envelope's `agent_pubkey` field (use [`verify_envelope_self`]
/// for the latter). Both forms exist because the protocol allows
/// verifying against either an externally-supplied pubkey (e.g., the
/// applicant compositor in attestation) or the envelope's claimed
/// signer.
///
/// Python equivalent: `gyza.icp::verify_envelope(env, pubkey_bytes)`.
pub fn verify_envelope(signed: &SignedEnvelope, pubkey: &[u8]) -> Result<(), IcpError> {
    if signed.signature.is_empty() {
        return Err(IcpError::Unsigned);
    }
    let sig_bytes = hex::decode(&signed.signature).map_err(|_| IcpError::MalformedSignature)?;
    let canonical = canonical_bytes(&signed.payload)?;
    let payload_hash = hash(&canonical);
    verify(pubkey, &payload_hash, &sig_bytes).map_err(|_| IcpError::VerificationFailed)
}

/// Verify a signed envelope against the public key claimed in its
/// own `agent_pubkey` field. The common case for chain verification.
pub fn verify_envelope_self(signed: &SignedEnvelope) -> Result<(), IcpError> {
    let pubkey =
        hex::decode(&signed.payload.agent_pubkey).map_err(|_| IcpError::MalformedAgentPubkey {
            expected_hex_len: 64,
        })?;
    verify_envelope(signed, &pubkey)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fixed-input envelope used to validate cross-language byte
    /// parity. The corresponding Python output was generated by
    /// `gyza-rs/scripts/regenerate_icp_fixtures.py`.
    ///
    /// Construction note: agent_pubkey is the deterministic test
    /// pubkey from gyza-crypto's parity tests (compositor key from
    /// the test master seed). Other hex fields are made-up 32-byte
    /// payloads. The integer fields are small to keep canonical
    /// bytes readable.
    fn fixture_payload() -> EnvelopePayload {
        EnvelopePayload {
            action_id: "act-0001".to_string(),
            agent_pubkey: "08ed03d0cb5efe9152a79430ddd86a97286d760bdb5955fea3688e8bb9a13ab9"
                .to_string(),
            capability_manifest_hash:
                "cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1".to_string(),
            duration_ms: 42,
            inference_backend: "local".to_string(),
            input_hashes: vec!["i1".to_string(), "i2".to_string()],
            intent_id: "int-0001".to_string(),
            model_identifier: "mock-eval".to_string(),
            output_hash: "out1out1out1out1out1out1out1out1out1out1out1out1out1out1out1out1"
                .to_string(),
            parent_envelope_hash: None,
            schema_version: 1,
            timestamp_ns: 1_700_000_000_000_000_000,
            tokens_in: 10,
            tokens_out: 20,
        }
    }

    #[test]
    fn canonical_bytes_parity_with_python() {
        let payload = fixture_payload();
        let bytes = canonical_bytes(&payload).expect("canonical_bytes must succeed");
        let actual = String::from_utf8(bytes).expect("UTF-8");
        // Fixture from gyza-rs/scripts/regenerate_icp_fixtures.py
        let expected = "{\"action_id\":\"act-0001\",\"agent_pubkey\":\"08ed03d0cb5efe9152a79430ddd86a97286d760bdb5955fea3688e8bb9a13ab9\",\"capability_manifest_hash\":\"cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1\",\"duration_ms\":42,\"inference_backend\":\"local\",\"input_hashes\":[\"i1\",\"i2\"],\"intent_id\":\"int-0001\",\"model_identifier\":\"mock-eval\",\"output_hash\":\"out1out1out1out1out1out1out1out1out1out1out1out1out1out1out1out1\",\"parent_envelope_hash\":null,\"schema_version\":1,\"timestamp_ns\":1700000000000000000,\"tokens_in\":10,\"tokens_out\":20}";
        assert_eq!(actual, expected);
    }

    #[test]
    fn envelope_hash_parity_with_python() {
        let payload = fixture_payload();
        let hash_hex = envelope_hash(&payload).expect("envelope_hash must succeed");
        // Fixture from regenerate_icp_fixtures.py
        assert_eq!(
            hash_hex,
            "2b69bb3ab0cca91f0a273efc3b4fc83438cf8976aeffd33f45d44175c6662d40",
        );
    }

    #[test]
    fn signature_parity_with_python() {
        use gyza_crypto::derive_seed;
        const TEST_MASTER: [u8; 32] = hex_literal::hex!(
            "0102030405060708090a0b0c0d0e0f10"
            "1112131415161718191a1b1c1d1e1f20"
        );
        let compositor_seed = derive_seed(&TEST_MASTER, b"gyza.compositor.ed25519.v1", b"");
        let payload = fixture_payload();
        let signed = sign_envelope(payload, &compositor_seed).expect("sign");
        // Fixture from regenerate_icp_fixtures.py. Ed25519 is
        // deterministic, so the same seed + message must produce
        // byte-identical signatures across Python and Rust.
        assert_eq!(
            signed.signature,
            "6e7900cb768f2052af12f85059187b5d2b00562437a1a441b7ad8720459b920f\
             cbb837924d29d58396c8e73aaf7b39d01b6f48f1cc60b7d37a3091986f5cc30e",
        );
    }

    #[test]
    fn sign_then_verify_self_roundtrip() {
        use gyza_crypto::derive_seed;
        const TEST_MASTER: [u8; 32] = hex_literal::hex!(
            "0102030405060708090a0b0c0d0e0f10"
            "1112131415161718191a1b1c1d1e1f20"
        );
        let compositor_seed = derive_seed(&TEST_MASTER, b"gyza.compositor.ed25519.v1", b"");

        let payload = fixture_payload();
        let signed = sign_envelope(payload, &compositor_seed).expect("sign");
        verify_envelope_self(&signed).expect("verify must succeed");

        // Tamper with the payload; verify must fail.
        let mut tampered = signed.clone();
        tampered.payload.tokens_out = 999;
        assert!(matches!(
            verify_envelope_self(&tampered),
            Err(IcpError::VerificationFailed),
        ));

        // Tamper with the signature; verify must fail.
        let mut sig_tampered = signed.clone();
        // Flip one hex nibble — last char.
        let mut sig_chars: Vec<char> = sig_tampered.signature.chars().collect();
        let last = sig_chars.last_mut().unwrap();
        *last = if *last == '0' { '1' } else { '0' };
        sig_tampered.signature = sig_chars.into_iter().collect();
        assert!(matches!(
            verify_envelope_self(&sig_tampered),
            Err(IcpError::VerificationFailed),
        ));
    }

    #[test]
    fn verify_rejects_unsigned() {
        let signed = SignedEnvelope {
            payload: fixture_payload(),
            signature: String::new(),
        };
        assert!(matches!(
            verify_envelope_self(&signed),
            Err(IcpError::Unsigned)
        ));
    }

    #[test]
    fn verify_rejects_malformed_signature() {
        let signed = SignedEnvelope {
            payload: fixture_payload(),
            signature: "not-hex-content!!".to_string(),
        };
        assert!(matches!(
            verify_envelope_self(&signed),
            Err(IcpError::MalformedSignature),
        ));
    }

    #[test]
    fn verify_rejects_bad_seed_length() {
        let bad_seed = [0u8; 16];
        let payload = fixture_payload();
        assert!(matches!(
            sign_envelope(payload, &bad_seed),
            Err(IcpError::BadSeedLength {
                expected: 32,
                got: 16
            }),
        ));
    }

    #[test]
    fn distinct_envelopes_have_distinct_hashes() {
        let p1 = fixture_payload();
        let mut p2 = fixture_payload();
        p2.action_id = "act-0002".to_string();
        let h1 = envelope_hash(&p1).unwrap();
        let h2 = envelope_hash(&p2).unwrap();
        assert_ne!(h1, h2, "different envelopes must produce different hashes");
    }
}
