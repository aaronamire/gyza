# ADR-0009: Tier-3 attestation with k-of-n quorum cosignatures

**Status:** Accepted (Session 11). Refined in subsequent ADRs
(0010, 0011, 0012, 0013, 0014). Superseded by typed per-domain
tiered attestations in vNext (ADR-0015 layer 7).

## Context

The discovery layer (ADR-0003) lets agents advertise an integer
`attestation_tier`. Without a verifiable proof, this is just a
self-reported claim — a Sybil can advertise tier=3 for free.
Routing decisions that respect `min_tier=3` would be accepting the
lie.

The sybil-resistance design needed: a way for an agent to PROVE
Tier-3 standing via cryptographic attestation from existing Tier-3
peers, fetchable by anyone.

## Decision

- A Tier-3 cert is `AttestationCert {body, co_signatures[]}`.
- `body` is a canonical `AttestationBody` proto.
- ≥ `MinCoSignatures = 2` distinct Tier-3 validators each sign the
  body's canonical bytes via Ed25519.
- Verification = (a) `tier_granted == IssuedTier = 3`, (b)
  freshness (now ∈ [issued_at, expires_at]), (c) ≥ MinCoSignatures
  distinct validators, (d) each cosig is a valid Ed25519 over the
  canonical-marshal body.
- Validator cosigs **dedup by validator_pubkey** — two cosigs from
  the same validator count as one. Prevents single Tier-3 key from
  minting "self-attested" certs.
- Default cert lifetime: 30 days (`DefaultAttestationTTL`).
  Maximum: 90 days (`MaxAttestationTTL`, validator-side plausibility
  check).

## Consequences

**Intended:**
- Sybil resistance via cryptographic proof, not just integer
  comparison.
- Quorum threshold (k=2 of n) tolerates one malicious validator.
- Cosigs from distinct validators required; can't self-attest.
- Time-bounded; expired certs can't be replayed indefinitely.

**Accepted costs:**
- Genesis trust set is undefined. Initial Tier-3 validators have to
  bootstrap from somewhere (Foundation-blessed list — user-owned
  per CLAUDE.md §6 B1).
- Verifying every cosig is O(k) Ed25519 verifies per cert. Cheap
  for k=2; costlier at higher k.
- Cert TTL doesn't include grace for clock skew at issue time.
  Validator plausibility check (Session 14) closes this with a
  ±1h skew tolerance.
- **Self-reported `attestation_tier` field on AgentAdvertisement
  still trustable at face value.** Routing filters that respect
  `min_tier=3` are accepting the lie until verify-on-fetch lands
  (Session 15 / ADR-0013).
- **Validator Tier-3 status not recursively verified.** Any pubkey
  that signs the body is accepted as a "validator." Recursive
  verification with trusted bootstrap is Session 16 / ADR-0014.
- Cross-language canonical bytes for cosig aggregation is load-
  bearing (see ADR-0012 for the load-bearing fix).

## Alternatives considered

- **Single-signature attestation.** Rejected: one compromised
  validator → arbitrary Tier-3 minting.
- **N-of-N (all-validators).** Rejected: any offline validator
  blocks attestation.
- **Stake-based attestation (e.g., proof-of-stake).** Rejected at
  Phase 3 scope — requires token (rejected per ADR-0004). vNext
  reconsiders (ADR-0015 layer 6).

## References

- `netd/internal/capability/capability.go` — IssueChallenge,
  VerifyResponse, AssembleAttestation, VerifyAttestation
- `gyza/capability_eval.py` — applicant eval suite (Tier-1
  self-attestation)
- `gyza/network/capability_protocol.py` — in-process Tier-1 (Session 11)
- ADR-0010, 0011, 0012, 0013, 0014 (subsequent refinements)
- CLAUDE.md §5b (Session 11 narrative)
