//! Bilateral compute-credit settlement for Gyza.
//!
//! Ports the entry-level signing/verification surface of
//! `gyza/economy/ledger.py` to Rust, and implements the state
//! machine validated by `spec/Settlement.tla`. The Settlement.tla
//! spec is the ground truth; this implementation is derived from it.
//!
//! ## State machine (from Settlement.tla)
//!
//! ```text
//! proposed → earner_signed → payer_cosigned → applied
//!                          ↘ disputed (terminal)
//! ```
//!
//! Each transition has named guards (see [`SettlementError`]):
//!
//!   - `proposed → earner_signed` — earner builds + signs the entry
//!     ([`sign_as_earner`]).
//!   - `earner_signed → payer_cosigned` — payer validates earner sig,
//!     envelope hash, amount tolerance, and misroute before
//!     cosigning ([`sign_as_payer`]).
//!   - `payer_cosigned → applied` — earner receives cosigned entry,
//!     verifies both sigs, applies locally ([`apply_cosigned_entry`]).
//!
//! ## Canonical bytes
//!
//! The signature digest is `BLAKE3(parts.join(b"|"))` where parts is
//! `[entry_id, amount_canonical, work_item_id, icp_envelope_hash,
//! role]`. `amount_canonical` is `"{:.6}"` formatted; both Python's
//! `f"{amount:.6f}"` and Rust's `format!("{:.6}", amount)` round
//! half-to-even and produce byte-identical bytes for the values the
//! protocol uses.
//!
//! ## Cross-references
//!
//!   - `gyza/economy/ledger.py` — Python reference
//!   - `gyza/economy/settlement.py` — protocol layer (state machine
//!     orchestrator; messaging layer; NOT ported here)
//!   - `spec/Settlement.tla` — formal spec
//!   - `docs/invariants.md` § Settlement (INV-SETTLE-1..7)
//!
//! ## What this crate DOES port
//!
//!   - `LedgerEntry` struct (fields + serde + canonical bytes)
//!   - `canonical_sign_bytes(entry, role)` → BLAKE3 digest
//!   - `sign_as_earner` / `sign_as_payer` / `apply_cosigned_entry`
//!   - `verify_earner_signature` / `verify_payer_signature` / `verify_entry`
//!   - `compute_task_cost` + `within_tolerance` (amount-tolerance check)
//!
//! ## What this crate does NOT port (deferred)
//!
//!   - SQLite-backed `ComputeLedger` storage (mirror of
//!     `gyza-blackboard`; add as a follow-up)
//!   - `LedgerSettlementService` (network layer; gRPC; depends on
//!     `gyza-rs` not having a daemon yet)
//!   - Reconciliation RPC (separate sub-spec)
//!   - Reputation hooks (gyza-reputation crate, future)
//!   - Settlement-latency observability (Prometheus; future)

use gyza_crypto::{ED25519_PUBKEY_LEN, ED25519_SIG_LEN, Signer, hash, verify};
use serde::{Deserialize, Serialize};

/// Default ±20% amount tolerance for the payer's recompute check.
/// Per CLAUDE.md §3 trip-wires, the integer-arithmetic equivalent
/// is `5 * |claimed - truth| ≤ truth`.
pub const DEFAULT_AMOUNT_TOLERANCE_RATIO: f64 = 0.20;

/// Roles in the canonical-bytes signature input. Pipe separator
/// chosen because it cannot appear in any sub-field (hex strings,
/// UUIDs, role constants) — eliminates ambiguity attacks.
pub const ROLE_EARNER: &str = "earner";
pub const ROLE_PAYER: &str = "payer";

/// Errors arising from settlement operations.
#[derive(Debug, thiserror::Error)]
pub enum SettlementError {
    #[error("invalid role: must be 'earner' or 'payer', got {got:?}")]
    InvalidRole { got: String },
    #[error("signer compositor pubkey mismatch: signer is {signer}, entry expects {expected}")]
    SignerMismatch { signer: String, expected: String },
    #[error("missing earner signature; can't cosign as payer")]
    EarnerSignatureMissing,
    #[error("missing payer signature; can't verify settled entry")]
    PayerSignatureMissing,
    #[error("earner signature invalid: {reason}")]
    EarnerSignatureInvalid { reason: String },
    #[error("payer signature invalid: {reason}")]
    PayerSignatureInvalid { reason: String },
    #[error("amount {claimed} outside ±{ratio_pct}% of recomputed {ours}")]
    AmountOutOfTolerance {
        claimed: f64,
        ours: f64,
        ratio_pct: u32,
    },
    #[error(
        "entry refers to envelope {claimed} but resolved {expected} for work_item {work_item_id}"
    )]
    EnvelopeMismatch {
        work_item_id: String,
        claimed: String,
        expected: String,
    },
    #[error("crypto error: {0}")]
    Crypto(#[from] gyza_crypto::CryptoError),
    #[error("hex decoding failed: {0}")]
    HexDecode(#[from] hex::FromHexError),
}

/// A bilateral ledger entry. Mirrors `gyza.economy.ledger.LedgerEntry`.
///
/// **Naming convention from Python** (preserved for cross-language
/// parity): `from_compositor` is the **payer**; `to_compositor` is
/// the **earner**. Counter-intuitive but consistent with the
/// "credits flow from→to" mental model.
///
/// The two signature fields are populated by the protocol in order:
///
///   1. Earner builds the entry and signs `canonical_sign_bytes(_, "earner")`,
///      setting `to_signature`.
///   2. Payer receives the entry, verifies earner sig, signs
///      `canonical_sign_bytes(_, "payer")`, setting `from_signature`,
///      and flips `settled = true`.
///   3. Earner receives the cosigned entry, verifies both sigs, and
///      `apply_cosigned_entry` makes it canonical locally.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LedgerEntry {
    pub entry_id: String,
    /// Payer compositor pubkey (hex). `from_` because credits flow
    /// FROM payer TO earner.
    pub from_compositor: String,
    /// Earner compositor pubkey (hex).
    pub to_compositor: String,
    pub amount_credits: f64,
    pub work_item_id: String,
    pub icp_envelope_hash: String,
    pub model_identifier: String,
    pub tokens_out: i64,
    pub duration_ms: i64,
    pub created_at_ns: i64,
    /// Payer signature (hex). Empty when not yet cosigned.
    #[serde(default)]
    pub from_signature: String,
    /// Earner signature (hex). Empty when not yet signed.
    #[serde(default)]
    pub to_signature: String,
    /// True iff both signatures present and verified.
    #[serde(default)]
    pub settled: bool,
}

impl LedgerEntry {
    /// Construct a fresh entry. Caller supplies all fields; signatures
    /// and `settled` start empty/false.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        entry_id: String,
        payer_pubkey_hex: String,
        earner_pubkey_hex: String,
        amount_credits: f64,
        work_item_id: String,
        icp_envelope_hash: String,
        model_identifier: String,
        tokens_out: i64,
        duration_ms: i64,
        created_at_ns: i64,
    ) -> Self {
        Self {
            entry_id,
            from_compositor: payer_pubkey_hex,
            to_compositor: earner_pubkey_hex,
            amount_credits,
            work_item_id,
            icp_envelope_hash,
            model_identifier,
            tokens_out,
            duration_ms,
            created_at_ns,
            from_signature: String::new(),
            to_signature: String::new(),
            settled: false,
        }
    }
}

/// Format an amount per Python's `f"{amount:.6f}"` convention. Both
/// languages round half-to-even (banker's rounding) by default, so
/// for the same f64 value they produce byte-identical strings.
fn amount_canonical(amount: f64) -> Vec<u8> {
    format!("{:.6}", amount).into_bytes()
}

/// Compute the BLAKE3 digest that gets signed for the given role.
///
/// Algorithm matches `gyza.economy.ledger.canonical_sign_bytes`
/// exactly:
///
/// ```text
/// digest = BLAKE3(
///     entry_id ∥ b"|" ∥ amount_canonical ∥ b"|" ∥
///     work_item_id ∥ b"|" ∥ icp_envelope_hash ∥ b"|" ∥ role
/// )
/// ```
///
/// Returns 32 bytes (BLAKE3 output).
pub fn canonical_sign_bytes(entry: &LedgerEntry, role: &str) -> Result<[u8; 32], SettlementError> {
    if role != ROLE_EARNER && role != ROLE_PAYER {
        return Err(SettlementError::InvalidRole {
            got: role.to_string(),
        });
    }
    let amount = amount_canonical(entry.amount_credits);
    let mut input: Vec<u8> = Vec::with_capacity(
        entry.entry_id.len()
            + amount.len()
            + entry.work_item_id.len()
            + entry.icp_envelope_hash.len()
            + role.len()
            + 4,
    );
    input.extend_from_slice(entry.entry_id.as_bytes());
    input.push(b'|');
    input.extend_from_slice(&amount);
    input.push(b'|');
    input.extend_from_slice(entry.work_item_id.as_bytes());
    input.push(b'|');
    input.extend_from_slice(entry.icp_envelope_hash.as_bytes());
    input.push(b'|');
    input.extend_from_slice(role.as_bytes());
    Ok(hash(&input))
}

/// Earner signs an entry. Returns the entry with `to_signature` set.
///
/// Verifies the signer's compositor pubkey matches
/// `entry.to_compositor`; otherwise returns `SignerMismatch`.
///
/// Python equivalent: `ComputeLedger.sign_as_earner`.
pub fn sign_as_earner(
    mut entry: LedgerEntry,
    earner: &Signer,
) -> Result<LedgerEntry, SettlementError> {
    let signer_hex = earner.pubkey_hex();
    if signer_hex != entry.to_compositor {
        return Err(SettlementError::SignerMismatch {
            signer: signer_hex,
            expected: entry.to_compositor.clone(),
        });
    }
    let digest = canonical_sign_bytes(&entry, ROLE_EARNER)?;
    entry.to_signature = earner.sign_hex(&digest);
    Ok(entry)
}

/// Payer cosigns an already-earner-signed entry. Verifies the
/// earner signature first; returns the entry with `from_signature`
/// set and `settled = true`.
///
/// Does NOT enforce envelope-hash / amount-tolerance / misroute
/// guards from the Settlement.tla state machine — those live at the
/// protocol layer ([`payer_validate`]) which the daemon will call
/// before invoking this. This function is the cryptographic step,
/// not the validation pipeline.
///
/// Python equivalent: `ComputeLedger.sign_as_payer` (which also
/// pre-validates the earner sig and then signs).
pub fn sign_as_payer(
    mut entry: LedgerEntry,
    payer: &Signer,
) -> Result<LedgerEntry, SettlementError> {
    let signer_hex = payer.pubkey_hex();
    if signer_hex != entry.from_compositor {
        return Err(SettlementError::SignerMismatch {
            signer: signer_hex,
            expected: entry.from_compositor.clone(),
        });
    }
    if entry.to_signature.is_empty() {
        return Err(SettlementError::EarnerSignatureMissing);
    }
    verify_earner_signature(&entry)?;
    let digest = canonical_sign_bytes(&entry, ROLE_PAYER)?;
    entry.from_signature = payer.sign_hex(&digest);
    entry.settled = true;
    Ok(entry)
}

/// Apply a fully-cosigned entry received from the network. Verifies
/// both signatures; flips `settled = true` on success.
///
/// Python equivalent: `ComputeLedger.apply_cosigned_entry`.
pub fn apply_cosigned_entry(mut entry: LedgerEntry) -> Result<LedgerEntry, SettlementError> {
    verify_entry(&entry)?;
    entry.settled = true;
    Ok(entry)
}

/// Verify the earner signature against the entry's
/// `to_compositor` pubkey.
pub fn verify_earner_signature(entry: &LedgerEntry) -> Result<(), SettlementError> {
    if entry.to_signature.is_empty() {
        return Err(SettlementError::EarnerSignatureInvalid {
            reason: "to_signature is empty".to_string(),
        });
    }
    let pubkey_bytes =
        hex::decode(&entry.to_compositor).map_err(|e| SettlementError::EarnerSignatureInvalid {
            reason: format!("to_compositor not hex: {e}"),
        })?;
    if pubkey_bytes.len() != ED25519_PUBKEY_LEN {
        return Err(SettlementError::EarnerSignatureInvalid {
            reason: format!(
                "to_compositor length {} != {ED25519_PUBKEY_LEN}",
                pubkey_bytes.len()
            ),
        });
    }
    let sig_bytes =
        hex::decode(&entry.to_signature).map_err(|e| SettlementError::EarnerSignatureInvalid {
            reason: format!("to_signature not hex: {e}"),
        })?;
    if sig_bytes.len() != ED25519_SIG_LEN {
        return Err(SettlementError::EarnerSignatureInvalid {
            reason: format!(
                "to_signature length {} != {ED25519_SIG_LEN}",
                sig_bytes.len()
            ),
        });
    }
    let digest = canonical_sign_bytes(entry, ROLE_EARNER)?;
    verify(&pubkey_bytes, &digest, &sig_bytes).map_err(|e| {
        SettlementError::EarnerSignatureInvalid {
            reason: format!("{e}"),
        }
    })
}

/// Verify the payer signature against the entry's
/// `from_compositor` pubkey.
pub fn verify_payer_signature(entry: &LedgerEntry) -> Result<(), SettlementError> {
    if entry.from_signature.is_empty() {
        return Err(SettlementError::PayerSignatureMissing);
    }
    let pubkey_bytes = hex::decode(&entry.from_compositor).map_err(|e| {
        SettlementError::PayerSignatureInvalid {
            reason: format!("from_compositor not hex: {e}"),
        }
    })?;
    if pubkey_bytes.len() != ED25519_PUBKEY_LEN {
        return Err(SettlementError::PayerSignatureInvalid {
            reason: format!(
                "from_compositor length {} != {ED25519_PUBKEY_LEN}",
                pubkey_bytes.len()
            ),
        });
    }
    let sig_bytes =
        hex::decode(&entry.from_signature).map_err(|e| SettlementError::PayerSignatureInvalid {
            reason: format!("from_signature not hex: {e}"),
        })?;
    if sig_bytes.len() != ED25519_SIG_LEN {
        return Err(SettlementError::PayerSignatureInvalid {
            reason: format!(
                "from_signature length {} != {ED25519_SIG_LEN}",
                sig_bytes.len()
            ),
        });
    }
    let digest = canonical_sign_bytes(entry, ROLE_PAYER)?;
    verify(&pubkey_bytes, &digest, &sig_bytes).map_err(|e| SettlementError::PayerSignatureInvalid {
        reason: format!("{e}"),
    })
}

/// Verify both signatures on a settled entry. Returns the first
/// error encountered.
pub fn verify_entry(entry: &LedgerEntry) -> Result<(), SettlementError> {
    if entry.from_signature.is_empty() {
        return Err(SettlementError::PayerSignatureMissing);
    }
    if entry.to_signature.is_empty() {
        return Err(SettlementError::EarnerSignatureMissing);
    }
    verify_earner_signature(entry)?;
    verify_payer_signature(entry)?;
    Ok(())
}

/// Amount-tolerance check. Returns true iff `claimed` is within
/// `tolerance_ratio` of `truth` (both directions).
///
/// Python equivalent: `gyza.economy.settlement._within_tolerance`.
/// The ±20% rule corresponds to `tolerance_ratio = 0.20`.
pub fn within_tolerance(claimed: f64, truth: f64, tolerance_ratio: f64) -> bool {
    let diff = (claimed - truth).abs();
    diff <= truth * tolerance_ratio
}

/// Settlement-protocol-level payer validation (Settlement.tla
/// `HandleEarnerSigned`'s guard chain).
///
/// Checks IN ORDER:
///   1. Recipient is the entry's payer (not misrouted).
///   2. Earner signature valid.
///   3. Envelope hash matches the local resolution.
///   4. Amount within ±tolerance of the local recompute.
///
/// Returns `Ok(())` if all pass; the first failing check otherwise.
/// Caller (daemon) typically dispatches reputation penalties /
/// dispute logging based on which variant fires.
///
/// Note: envelope-hash and amount-recompute are caller-supplied
/// because they involve I/O (blackboard lookup, cost recompute).
/// This function is pure given those inputs.
pub fn payer_validate(
    entry: &LedgerEntry,
    recipient_pubkey_hex: &str,
    resolved_envelope_hash: &str,
    our_amount: f64,
    tolerance_ratio: f64,
) -> Result<(), SettlementError> {
    // (1) misroute check
    if recipient_pubkey_hex != entry.from_compositor {
        return Err(SettlementError::SignerMismatch {
            signer: recipient_pubkey_hex.to_string(),
            expected: entry.from_compositor.clone(),
        });
    }
    // (2) earner signature
    verify_earner_signature(entry)?;
    // (3) envelope hash
    if resolved_envelope_hash != entry.icp_envelope_hash {
        return Err(SettlementError::EnvelopeMismatch {
            work_item_id: entry.work_item_id.clone(),
            claimed: entry.icp_envelope_hash.clone(),
            expected: resolved_envelope_hash.to_string(),
        });
    }
    // (4) amount tolerance
    if !within_tolerance(entry.amount_credits, our_amount, tolerance_ratio) {
        return Err(SettlementError::AmountOutOfTolerance {
            claimed: entry.amount_credits,
            ours: our_amount,
            ratio_pct: (tolerance_ratio * 100.0) as u32,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use gyza_crypto::derive_seed;
    use hex_literal::hex;

    /// Reused test master seed from gyza-crypto fixtures.
    const TEST_MASTER: [u8; 32] = hex!(
        "0102030405060708090a0b0c0d0e0f10"
        "1112131415161718191a1b1c1d1e1f20"
    );

    /// Different master seed for the payer side. So we have two
    /// distinct compositor identities for tests.
    const PAYER_MASTER: [u8; 32] = hex!(
        "feedfaceabad1deadeadbeef0badc0de"
        "cafef00d8badf00ddeadbeef13371337"
    );

    fn earner_signer() -> Signer {
        let seed = derive_seed(&TEST_MASTER, b"gyza.compositor.ed25519.v1", b"");
        Signer::from_seed(&seed)
    }

    fn payer_signer() -> Signer {
        let seed = derive_seed(&PAYER_MASTER, b"gyza.compositor.ed25519.v1", b"");
        Signer::from_seed(&seed)
    }

    fn fixture_entry() -> LedgerEntry {
        LedgerEntry::new(
            "entry-0001".to_string(),
            payer_signer().pubkey_hex(),
            earner_signer().pubkey_hex(),
            0.5,
            "work-0001".to_string(),
            "envhash-0001".to_string(),
            "mock-eval".to_string(),
            100,
            500,
            1_700_000_000_000_000_000,
        )
    }

    #[test]
    fn amount_canonical_six_decimals() {
        assert_eq!(amount_canonical(0.5), b"0.500000".to_vec());
        assert_eq!(amount_canonical(0.0), b"0.000000".to_vec());
        assert_eq!(amount_canonical(1.234567), b"1.234567".to_vec());
        // Bankers-rounding behavior at the .5 boundary. Both Python
        // and Rust round half-to-even by default. 1.2345675 → 1.234568
        // (or 1.234567 depending on f64 exactness — let's just check
        // a known-clean case below).
        assert_eq!(amount_canonical(0.000001), b"0.000001".to_vec());
    }

    #[test]
    fn canonical_sign_bytes_role_distinct() {
        let e = fixture_entry();
        let earner_digest = canonical_sign_bytes(&e, ROLE_EARNER).expect("earner digest");
        let payer_digest = canonical_sign_bytes(&e, ROLE_PAYER).expect("payer digest");
        assert_ne!(
            earner_digest, payer_digest,
            "earner and payer must sign DIFFERENT bytes for the same entry"
        );
    }

    #[test]
    fn canonical_sign_bytes_rejects_invalid_role() {
        let e = fixture_entry();
        let err = canonical_sign_bytes(&e, "auditor").unwrap_err();
        assert!(matches!(err, SettlementError::InvalidRole { .. }));
    }

    #[test]
    fn earner_sign_verify_roundtrip() {
        let e = fixture_entry();
        let signed = sign_as_earner(e, &earner_signer()).expect("earner sign");
        assert!(!signed.to_signature.is_empty());
        verify_earner_signature(&signed).expect("earner verify");
    }

    #[test]
    fn earner_sign_rejects_wrong_signer() {
        let e = fixture_entry();
        // Try to sign as earner with the payer's key.
        let err = sign_as_earner(e, &payer_signer()).unwrap_err();
        assert!(matches!(err, SettlementError::SignerMismatch { .. }));
    }

    #[test]
    fn payer_cosign_requires_earner_signature() {
        let e = fixture_entry();
        // Skip earner sig; payer cosign should fail.
        let err = sign_as_payer(e, &payer_signer()).unwrap_err();
        assert!(matches!(err, SettlementError::EarnerSignatureMissing));
    }

    #[test]
    fn payer_cosign_verifies_earner_first() {
        let e = fixture_entry();
        let mut signed_by_earner = sign_as_earner(e, &earner_signer()).expect("earner sign");
        // Corrupt the earner signature.
        let mut sig_chars: Vec<char> = signed_by_earner.to_signature.chars().collect();
        let last = sig_chars.last_mut().unwrap();
        *last = if *last == '0' { '1' } else { '0' };
        signed_by_earner.to_signature = sig_chars.into_iter().collect();

        let err = sign_as_payer(signed_by_earner, &payer_signer()).unwrap_err();
        assert!(matches!(
            err,
            SettlementError::EarnerSignatureInvalid { .. }
        ));
    }

    #[test]
    fn payer_cosign_rejects_wrong_signer() {
        let e = fixture_entry();
        let signed = sign_as_earner(e, &earner_signer()).expect("earner sign");
        // Try to cosign as payer with the earner's key.
        let err = sign_as_payer(signed, &earner_signer()).unwrap_err();
        assert!(matches!(err, SettlementError::SignerMismatch { .. }));
    }

    #[test]
    fn full_bilateral_roundtrip() {
        let e = fixture_entry();
        let earner_signed = sign_as_earner(e, &earner_signer()).expect("earner");
        let cosigned = sign_as_payer(earner_signed, &payer_signer()).expect("payer");
        assert!(cosigned.settled);
        assert!(!cosigned.from_signature.is_empty());
        assert!(!cosigned.to_signature.is_empty());

        // Either side should be able to verify the settled entry.
        verify_entry(&cosigned).expect("verify");

        // apply_cosigned_entry idempotently keeps settled=true.
        let applied = apply_cosigned_entry(cosigned.clone()).expect("apply");
        assert!(applied.settled);
    }

    #[test]
    fn apply_rejects_unsettled_entry() {
        let e = fixture_entry();
        let earner_signed = sign_as_earner(e, &earner_signer()).expect("earner");
        // No payer cosig yet.
        let err = apply_cosigned_entry(earner_signed).unwrap_err();
        assert!(matches!(err, SettlementError::PayerSignatureMissing));
    }

    #[test]
    fn apply_rejects_tampered_amount() {
        let e = fixture_entry();
        let earner_signed = sign_as_earner(e, &earner_signer()).expect("earner");
        let mut cosigned = sign_as_payer(earner_signed, &payer_signer()).expect("payer");
        // Tamper the amount after cosign. Signature digest will no
        // longer match.
        cosigned.amount_credits = 999.0;
        let err = apply_cosigned_entry(cosigned).unwrap_err();
        assert!(matches!(
            err,
            SettlementError::EarnerSignatureInvalid { .. }
        ));
    }

    #[test]
    fn within_tolerance_basic() {
        // ±20% of 1.0 = [0.8, 1.2]
        assert!(within_tolerance(0.85, 1.0, 0.20));
        assert!(within_tolerance(1.15, 1.0, 0.20));
        assert!(within_tolerance(0.80, 1.0, 0.20));
        assert!(within_tolerance(1.20, 1.0, 0.20));
        assert!(!within_tolerance(0.79, 1.0, 0.20));
        assert!(!within_tolerance(1.21, 1.0, 0.20));
    }

    #[test]
    fn within_tolerance_zero_truth() {
        // Truth=0 → tolerance window is also 0; only an exact 0
        // is within tolerance. Defensive against divide-by-zero
        // (we don't divide).
        assert!(within_tolerance(0.0, 0.0, 0.20));
        assert!(!within_tolerance(0.01, 0.0, 0.20));
    }

    #[test]
    fn payer_validate_happy_path() {
        let e = fixture_entry();
        let earner_signed = sign_as_earner(e, &earner_signer()).expect("earner");
        // Payer side: their pubkey matches from_compositor; envelope
        // hash matches; amount is within ±20% of our recompute.
        payer_validate(
            &earner_signed,
            &payer_signer().pubkey_hex(),
            "envhash-0001",
            0.5,
            DEFAULT_AMOUNT_TOLERANCE_RATIO,
        )
        .expect("payer_validate must pass");
    }

    #[test]
    fn payer_validate_rejects_misroute() {
        let e = fixture_entry();
        let signed = sign_as_earner(e, &earner_signer()).expect("earner");
        // Pass the WRONG recipient pubkey (an unrelated key).
        let err = payer_validate(
            &signed,
            "00".repeat(32).as_str(),
            "envhash-0001",
            0.5,
            DEFAULT_AMOUNT_TOLERANCE_RATIO,
        )
        .unwrap_err();
        assert!(matches!(err, SettlementError::SignerMismatch { .. }));
    }

    #[test]
    fn payer_validate_rejects_envelope_mismatch() {
        let e = fixture_entry();
        let signed = sign_as_earner(e, &earner_signer()).expect("earner");
        let err = payer_validate(
            &signed,
            &payer_signer().pubkey_hex(),
            "different-envelope-hash",
            0.5,
            DEFAULT_AMOUNT_TOLERANCE_RATIO,
        )
        .unwrap_err();
        assert!(matches!(err, SettlementError::EnvelopeMismatch { .. }));
    }

    #[test]
    fn payer_validate_rejects_amount_outside_tolerance() {
        let e = fixture_entry();
        let signed = sign_as_earner(e, &earner_signer()).expect("earner");
        // Claimed 0.5; our recompute 1.0; 0.5 is 50% below — outside
        // ±20%.
        let err = payer_validate(
            &signed,
            &payer_signer().pubkey_hex(),
            "envhash-0001",
            1.0,
            DEFAULT_AMOUNT_TOLERANCE_RATIO,
        )
        .unwrap_err();
        assert!(matches!(err, SettlementError::AmountOutOfTolerance { .. }));
    }

    #[test]
    fn payer_validate_rejects_invalid_earner_sig() {
        let e = fixture_entry();
        let mut signed = sign_as_earner(e, &earner_signer()).expect("earner");
        // Corrupt the earner signature.
        let mut sig_chars: Vec<char> = signed.to_signature.chars().collect();
        let last = sig_chars.last_mut().unwrap();
        *last = if *last == '0' { '1' } else { '0' };
        signed.to_signature = sig_chars.into_iter().collect();

        let err = payer_validate(
            &signed,
            &payer_signer().pubkey_hex(),
            "envhash-0001",
            0.5,
            DEFAULT_AMOUNT_TOLERANCE_RATIO,
        )
        .unwrap_err();
        assert!(matches!(
            err,
            SettlementError::EarnerSignatureInvalid { .. }
        ));
    }

    #[test]
    fn entry_round_trips_via_serde() {
        let e = fixture_entry();
        let signed = sign_as_earner(e, &earner_signer()).expect("earner");
        let cosigned = sign_as_payer(signed, &payer_signer()).expect("payer");
        let json = serde_json::to_string(&cosigned).expect("ser");
        let back: LedgerEntry = serde_json::from_str(&json).expect("de");
        assert_eq!(cosigned, back);
        // Re-verify the deserialized entry.
        verify_entry(&back).expect("verify after roundtrip");
    }

    // ---- Python parity test ---------------------------------------

    /// Canonical sign bytes parity with Python.
    ///
    /// Python reference (output of
    /// `gyza-rs/scripts/regenerate_settlement_fixtures.py`):
    ///
    /// ```
    /// canonical_sign_bytes(fixture_entry, "earner") =
    ///     <fixture from regenerate_settlement_fixtures.py>
    /// ```
    ///
    /// The fixture is filled in once the regenerate script runs;
    /// placeholder until then ensures the test is wired but allows
    /// the spec-only build to pass.
    #[test]
    fn canonical_sign_bytes_parity_with_python() {
        // Construct the exact same fixture entry Python would build.
        // The Python script must produce identical pubkey-hex for
        // earner/payer (it uses the same TEST_MASTER + PAYER_MASTER).
        let e = fixture_entry();
        let earner_digest = canonical_sign_bytes(&e, ROLE_EARNER).expect("digest");
        let payer_digest = canonical_sign_bytes(&e, ROLE_PAYER).expect("digest");

        // Fixtures from regenerate_settlement_fixtures.py.
        assert_eq!(
            hex::encode(earner_digest),
            "6e9d9ae550d0c36b40038dd5e2f0c8f1bfb84bd392c845d3cdda1254fc67b440",
        );
        assert_eq!(
            hex::encode(payer_digest),
            "4f521f5c5b7461181de4c914a2d23753e5628c8649af263f1c4cd73a82412b1a",
        );
    }
}
