//! Compositor and agent identity for Gyza.
//!
//! This crate ports `gyza.identity` from Python to Rust with
//! byte-for-byte parity on key derivation. Two structs:
//!
//!   - [`LocalCompositor`] — owns a master seed; derives the
//!     compositor signing key; issues agent identities.
//!   - [`AgentIdentity`] — a per-agent signing identity derived
//!     from the compositor's master seed plus a context-specific
//!     info string.
//!
//! Key derivation pipeline:
//!
//! ```text
//! master_seed (32 bytes, stored at ~/.gyza/compositor.key)
//!   │
//!   ├── derive_seed(master, "gyza.compositor.ed25519.v1", "")
//!   │       │
//!   │       ▼
//!   │   compositor_signing_seed (32 bytes)
//!   │       │
//!   │       ▼
//!   │   Ed25519 compositor signing key
//!   │
//!   └── derive_seed(master, "gyza.agent.ed25519.v1", agent_info)
//!           │
//!           ▼
//!       agent_signing_seed (32 bytes)
//!           │
//!           ▼
//!       Ed25519 agent signing key
//! ```
//!
//! The two context strings `"gyza.compositor.ed25519.v1"` and
//! `"gyza.agent.ed25519.v1"` are protocol constants. Don't change
//! them — every existing on-disk master seed depends on them.

use gyza_crypto::{Signer, derive_seed};

/// Context string used to derive the compositor signing key.
/// Protocol constant; bumping the `v1` suffix is a hard fork.
pub const CTX_COMPOSITOR_SEED: &[u8] = b"gyza.compositor.ed25519.v1";

/// Context string used to derive agent signing keys. Protocol
/// constant; bumping the `v1` suffix is a hard fork.
pub const CTX_AGENT_SEED: &[u8] = b"gyza.agent.ed25519.v1";

/// Errors specific to identity operations.
#[derive(Debug, thiserror::Error)]
pub enum IdentityError {
    #[error("master seed must be exactly 32 bytes; got {0}")]
    MalformedMasterSeed(usize),
    #[error("crypto error: {0}")]
    Crypto(#[from] gyza_crypto::CryptoError),
}

/// A long-lived compositor identity. Owns a master seed; derives the
/// compositor signing key; issues per-agent identities on demand.
///
/// This is the Rust port of Python `gyza.identity.LocalCompositor`.
/// The constructor takes the master seed bytes directly rather than
/// reading a file — file I/O is the caller's responsibility (and
/// will be implemented in a follow-up crate for the daemon-side
/// initialization path).
pub struct LocalCompositor {
    master_seed: [u8; 32],
    compositor_signer: Signer,
}

impl LocalCompositor {
    /// Construct from a 32-byte master seed. The compositor signing
    /// key is HKDF-derived immediately.
    pub fn from_master_seed(master_seed: [u8; 32]) -> Self {
        let comp_seed = derive_seed(&master_seed, CTX_COMPOSITOR_SEED, b"");
        let compositor_signer = Signer::from_seed(&comp_seed);
        Self {
            master_seed,
            compositor_signer,
        }
    }

    /// Construct from a master seed of unknown length, validating
    /// it's exactly 32 bytes.
    pub fn from_master_seed_slice(seed: &[u8]) -> Result<Self, IdentityError> {
        if seed.len() != 32 {
            return Err(IdentityError::MalformedMasterSeed(seed.len()));
        }
        let mut arr = [0u8; 32];
        arr.copy_from_slice(seed);
        Ok(Self::from_master_seed(arr))
    }

    /// The compositor's signing key (read-only access).
    pub fn signer(&self) -> &Signer {
        &self.compositor_signer
    }

    /// Hex-encoded compositor public key.
    pub fn pubkey_hex(&self) -> String {
        self.compositor_signer.pubkey_hex()
    }

    /// Sign `data` with the compositor signing key, returning hex.
    /// Equivalent to Python `LocalCompositor.sign(data)`.
    pub fn sign_hex(&self, data: &[u8]) -> String {
        self.compositor_signer.sign_hex(data)
    }

    /// Issue an agent identity for the given `agent_info` context.
    ///
    /// The agent's signing key is HKDF-derived from the master seed
    /// plus the info string. Same info ⇒ same key (deterministic
    /// across runs and across language implementations).
    ///
    /// Python equivalent: `LocalCompositor.issue_agent(...)` with the
    /// info derived from the agent_type / model_path / etc. fields.
    /// We take the raw info bytes here — the caller is responsible
    /// for constructing the appropriate canonical info string.
    pub fn issue_agent(&self, agent_info: &[u8]) -> AgentIdentity {
        let agent_seed = derive_seed(&self.master_seed, CTX_AGENT_SEED, agent_info);
        AgentIdentity {
            signer: Signer::from_seed(&agent_seed),
        }
    }
}

/// A per-agent signing identity. Derived from a compositor's master
/// seed + an agent_info string.
pub struct AgentIdentity {
    signer: Signer,
}

impl AgentIdentity {
    /// Hex-encoded agent public key.
    pub fn pubkey_hex(&self) -> String {
        self.signer.pubkey_hex()
    }

    /// Sign `data` with the agent signing key, returning hex.
    pub fn sign_hex(&self, data: &[u8]) -> String {
        self.signer.sign_hex(data)
    }

    /// Direct signer access.
    pub fn signer(&self) -> &Signer {
        &self.signer
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use hex_literal::hex;

    /// Fixed test master seed — matches the one in
    /// gyza-crypto's test module. Used for parity assertions
    /// against `gyza-rs/scripts/regenerate_crypto_fixtures.py`
    /// output.
    const TEST_MASTER: [u8; 32] = hex!(
        "0102030405060708090a0b0c0d0e0f10"
        "1112131415161718191a1b1c1d1e1f20"
    );

    #[test]
    fn compositor_pubkey_parity() {
        let comp = LocalCompositor::from_master_seed(TEST_MASTER);
        // Fixture from regenerate_crypto_fixtures.py.
        assert_eq!(
            comp.pubkey_hex(),
            "08ed03d0cb5efe9152a79430ddd86a97286d760bdb5955fea3688e8bb9a13ab9",
        );
    }

    #[test]
    fn compositor_signature_parity() {
        let comp = LocalCompositor::from_master_seed(TEST_MASTER);
        // Fixture from regenerate_crypto_fixtures.py.
        assert_eq!(
            comp.sign_hex(b"hello gyza"),
            "cee3aece6183b50b280bc41ad879abc95e9bafa5039a2d3bccb6e4598e3765ac\
             38c61d99cc4584f491b33436fd2592ba5cc921fa9baab6e19e4326582a91f507",
        );
    }

    #[test]
    fn agent_pubkey_parity() {
        let comp = LocalCompositor::from_master_seed(TEST_MASTER);
        let agent = comp.issue_agent(b"agent-0001");
        // Fixture from regenerate_crypto_fixtures.py.
        assert_eq!(
            agent.pubkey_hex(),
            "dc2ee2f90f5efe92c15ef3b80bb3c5417ab72a3dc1ef7e90d1106bb4b042a949",
        );
    }

    #[test]
    fn agent_signature_parity() {
        let comp = LocalCompositor::from_master_seed(TEST_MASTER);
        let agent = comp.issue_agent(b"agent-0001");
        // Fixture from regenerate_crypto_fixtures.py.
        assert_eq!(
            agent.sign_hex(b"hello gyza"),
            "7105f29404f01d0c08937f5ed254e7c885569e441c148c6e677ede735ae91770\
             b4692648029cefc975c3210419d9e4a660a5ca642c49ebcd29091e4ccd4a2900",
        );
    }

    #[test]
    fn distinct_agents_have_distinct_keys() {
        let comp = LocalCompositor::from_master_seed(TEST_MASTER);
        let a1 = comp.issue_agent(b"agent-0001");
        let a2 = comp.issue_agent(b"agent-0002");
        assert_ne!(a1.pubkey_hex(), a2.pubkey_hex());
    }

    #[test]
    fn agent_key_differs_from_compositor_key() {
        let comp = LocalCompositor::from_master_seed(TEST_MASTER);
        let agent = comp.issue_agent(b"some-agent");
        assert_ne!(comp.pubkey_hex(), agent.pubkey_hex());
    }

    #[test]
    fn malformed_master_seed_rejected() {
        let bad = [0u8; 16];
        assert!(matches!(
            LocalCompositor::from_master_seed_slice(&bad),
            Err(IdentityError::MalformedMasterSeed(16))
        ));
    }
}
