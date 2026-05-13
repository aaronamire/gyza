# Attestation invariants — `INV-ATT-N` cross-reference

> Cross-walks the canonical `INV-ATT-N` IDs in `docs/invariants.md`
> §5 to their formalization (or deferred-to-companion-sub-spec
> status) in `Attestation.tla` and friends. Companion to
> `Settlement_invariants.md`.

The Attestation surface is split across four §C1 sub-specs.
`Attestation.tla` covers the cert format itself; the wire
protocol, DHT publish/fetch, and recursive verification are
companion specs.

## Mapping

| Canonical ID | Spec | Predicate / Status |
|---|---|---|
| INV-ATT-1 (MinCoSignatures=2) | `Attestation.tla` | `INV_ATT_1_MinCoSignatures` ✓ |
| INV-ATT-2 (IssuedTier=3) | `Attestation.tla` | `INV_ATT_2_TierFixed` ✓ |
| INV-ATT-3 (lifetime ≤ MaxAttestationTTL) | `Attestation.tla` | `INV_ATT_3_LifetimeBound` ✓ |
| INV-ATT-4 (default 30d TTL) | — | client-side default; not a safety invariant |
| INV-ATT-5 (cert verifies under VerifyAttestation) | `Attestation.tla` | `INV_ATT_5_Verifiable` (composite) ✓ |
| INV-ATT-6 (cosig dedup by validator) | `Attestation.tla` | `INV_ATT_6_DistinctValidators` ✓ |
| INV-ATT-7 (all cosigs same body) | `Attestation.tla` | `INV_ATT_7_AllCosignSameBody` ✓ |
| INV-ATT-8 (body plausibility) | `Attestation.tla` | `INV_ATT_8_BodyPlausible` ✓ |
| INV-ATT-9 (challenger sig before eval) | `CapabilityStream.tla` (pending) | ◯ |
| INV-ATT-10 (validator-chosen nonce, replay defense) | `CapabilityStream.tla` (pending) | ◯ |
| INV-ATT-11 (applicant signs response with compositor key) | `CapabilityStream.tla` (pending) | ◯ |
| INV-ATT-12 (ICP envelope verification) | — | orthogonal, lives in ICP layer |
| INV-ATT-13 (3-frame wire protocol) | `CapabilityStream.tla` (pending) | ◯ |
| INV-ATT-14 (varint framing) | `CapabilityStream.tla` (pending) | ◯ |
| INV-ATT-15 (publish-side 24h floor) | `AttestationDHT.tla` (pending) | ◯ |
| INV-ATT-16 (validator-side 5min grace) | `AttestationDHT.tla` (pending) | ◯ |
| INV-ATT-17 (DHT key shape) | `AttestationDHT.tla` (pending) | ◯ |
| INV-ATT-18 (verify-on-fetch in FindAgents) | `AttestationDHT.tla` (pending) | ◯ |
| INV-ATT-19 (verifier cache TTLs) | `AttestationDHT.tla` (pending) | ◯ |
| INV-ATT-20 (1h expiry slack) | `AttestationDHT.tla` (pending) | ◯ |
| INV-ATT-21 (verifier single-flight) | `AttestationDHT.tla` (pending) | ◯ |
| INV-ATT-22 (verifier keys by compositor) | `AttestationDHT.tla` (pending) | ◯ |
| INV-ATT-23 (TrustedBootstrap non-empty) | `AttestationRecursive.tla` (pending) | ◯ |
| INV-ATT-24 (validator-pubkey trusted-or-recursive) | `AttestationRecursive.tla` (pending) | ◯ |
| INV-ATT-25 (cycle detection) | `AttestationRecursive.tla` (pending) | ◯ |
| INV-ATT-26 (depth bound MaxDepth=5) | `AttestationRecursive.tla` (pending) | ◯ |
| INV-ATT-27 (substitution defense) | `AttestationRecursive.tla` (pending) | ◯ |
| INV-ATT-28 (positive-only cache) | `AttestationRecursive.tla` (pending) | ◯ |

## What `Attestation.tla` proves and doesn't

**Proves:** for the cert as a data structure plus the
`AssembleAttestation` / `VerifyAttestation` algorithms, the cert
format invariants hold under any interleaving of honest validator
cosigns + adversarial bad-sig or wrong-body cosigns. Specifically:
no adversarial cosig (forged signature or non-canonical body)
enters a valid cert; cosigs always dedup by validator; cert body
satisfies tier + lifetime bounds.

**Does NOT prove:** that the wire protocol delivers a cosig from
the validator that actually ran the eval (that's INV-ATT-9..14
in `CapabilityStream.tla`). The spec abstracts the wire by
assuming `HonestCosign` corresponds to a successful
challenge-response handshake; if the wire layer's invariants were
violated, you could end up with cosigs from validators who didn't
do the work. That's the wire spec's job to rule out.

## Test of soundness

Removing the `cs.sig_valid` filter from `AssembleCert` should
allow adversarial bad-sig cosigs to enter certs, violating
`INV_ATT_1_MinCoSignatures` (count of valid cosigs drops below
MinCoSignatures even though the cert has ≥ MinCoSignatures
cosigs). Confirming this in TLC validates that the filter is
the load-bearing defense.
