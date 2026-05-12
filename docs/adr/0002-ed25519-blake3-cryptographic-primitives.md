# ADR-0002: Ed25519 + BLAKE3 cryptographic primitives

**Status:** Accepted (Phase 1). Migrated to hybrid PQ + classical in
vNext (see ADR-0015 layer 2).

## Context

Phase 1 needed cryptographic primitives for identity, signing, and
hashing. Choices considered: Ed25519, ECDSA-secp256k1,
ECDSA-secp256r1 for signing; SHA-256, SHA-3, BLAKE2, BLAKE3 for
hashing.

The protocol has heavy signing in the runner's hot path (every
completed work item signs an ICP envelope) and heavy hashing in
the attestation pipeline + DHT layer + LSH layer.

## Decision

- **Signing:** Ed25519 (RFC 8032).
- **Hashing:** BLAKE3 (256-bit output).

Reasoning:

Ed25519:
- Standard, well-audited, fast (~70K ops/sec sign, ~25K verify on
  consumer hardware).
- Small keys (32 bytes pubkey, 32 seed → derive privkey, 64 bytes
  signature).
- No nonce-reuse footguns (vs. ECDSA where nonce reuse leaks the
  private key).
- libp2p's standard primitive, so PeerIDs derive naturally from
  Ed25519 keys.

BLAKE3:
- Faster than SHA-256, SHA-3, and BLAKE2 on modern hardware.
- 256-bit output matches Ed25519's security level.
- Tree-mode (bao) enables verifiable random access for future
  multimodal artifacts (Phase 6).
- Single specification, mature reference implementations in
  Go (`github.com/zeebo/blake3`) and Python (`blake3` PyPI).

## Consequences

**Intended:**
- High throughput on the signing hot path.
- Compatible with libp2p PeerID derivation.
- Cross-language byte-for-byte agreement (both Go and Python use
  RFC-standard implementations).

**Accepted costs:**
- Ed25519 is **NOT post-quantum**. Shor's algorithm breaks it on a
  sufficiently large quantum computer. Estimates: 5–20 years.
- BLAKE3 is newer than SHA-256 (2020 vs. 2001). Less battle-tested,
  though no cryptographic weaknesses have been found.
- Migration story for either primitive would require coordinated
  hard fork (constitutional invariants — see CLAUDE.md §8 layer 10).

## Alternatives considered

- **ECDSA-secp256k1.** Rejected: Bitcoin/Ethereum standard, but
  nonce-reuse vulnerability + worse performance than Ed25519.
- **SHA-256 / SHA-3.** Rejected: slower than BLAKE3 on modern
  hardware. SHA-3 is harder to integrate (Keccak vs. Merkle-Damgård).
- **BLAKE2.** Rejected: superseded by BLAKE3 (same author lineage,
  better performance).
- **Hybrid PQ + classical from day one.** Considered for Phase 3
  but deferred — NIST PQC standards still settling, integration
  complexity high. vNext (ADR-0015 layer 2) commits to hybrid.

## References

- `gyza/icp.py` — Ed25519 signing of ICP envelopes
- `netd/internal/identity/` — libp2p PeerID from Ed25519
- `netd/internal/capability/capability.go` — Ed25519 for cosigs
- ADR-0015 (vNext layer 2 — hybrid PQ + threshold sigs)
- CLAUDE.md §8 layer 2 (vNext cryptographic identity)
