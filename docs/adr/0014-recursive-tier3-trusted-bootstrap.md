# ADR-0014: Recursive Tier-3 verification with trusted bootstrap set

**Status:** Accepted (Session 16, library only). Integration into
`DHTAttestationVerifier` pending (CLAUDE.md §6 A5; blocked on
trusted-bootstrap set configuration).

## Context

Standard `VerifyAttestation` (ADR-0009) accepts a cert if ≥
MinCoSignatures distinct pubkeys produce valid Ed25519 signatures
over the canonical body. It does NOT check that those pubkeys are
themselves Tier-3 attested.

A Sybil controlling N keys can mint a cert that passes
`VerifyAttestation` by having the keys cosign each other. The
attack: spin up 2+ fresh keys, have them cosign each other's
certs, advertise tier=3. Standard verifier accepts.

The defense: bottom out validator trust at a manually-pinned
"trusted bootstrap set" of pubkeys known to be Tier-3 out of band
(Foundation-blessed initial validators). Recursively verify that
any non-bootstrap signer has its own valid Tier-3 cert whose
cosigners are in turn either bootstrap members or recursively
verifiable.

## Decision

New `netd/internal/capability/recursive.go::RecursiveVerifier`
(pure logic; not yet wired into the production verifier).

**Algorithm:**

1. Standard well-formedness + freshness + tier checks on the cert.
2. For each cosig:
   - Verify Ed25519 signature over canonical body.
   - **Then verify the signer's pubkey is Tier-3:**
     - **Base case:** pubkey in `TrustedBootstrap` → accept.
     - **Recursive case:** fetch validator's own cert; recurse on
       it with `depth+1` and `seen ∪ {pubkey}`.
3. Count cosigs whose signer is Tier-3-verified. ≥ MinCoSignatures
   → cert accepted.

**Three guards on the recursion:**

- **Trusted bootstrap set** (required non-empty). Empty bootstrap
  → all certs rejected (no base case).
- **Cycle detection** via path-tracking `seen` set. A pubkey in
  the current recursion path is treated as non-Tier-3. Without
  this, A→B→A mutual-validation farm passes.
- **Depth bound** (`MaxDepth = 5`). Hard cap on recursive cert
  fetches per chain. Prevents pathological chains.

**Substitution defense.** Fetched cert's `ApplicantPubkey` MUST
equal the queried pubkey. Otherwise reject. A malicious DHT peer
could serve someone else's legitimate cert in response to a fetch
for a non-Tier-3 pubkey; without this check, the recursion would
accept.

**Positive-only cache.** Negative results NOT cached at this layer.
Fetch failures can be transient; sticky-negatives would hide
validators that become Tier-3 later.

## Consequences

**Intended:**
- Validator pubkeys are now provably Tier-3, not just
  cryptographically valid signers.
- Bootstrap-set design lets the Foundation curate initial trust;
  subsequent validators bootstrap from them.
- Sybil farm with mutual-validation collapses under cycle
  detection.

**Accepted costs:**
- Recursive verification involves O(MaxDepth × cosig_count) DHT
  fetches per top-level verify. Much slower than the standard
  verifier's pure-crypto path.
- Requires configured trusted bootstrap set. Without it, no certs
  verify. This is a deployment dependency (CLAUDE.md §11), not a
  code task.
- **NOT yet wired into `DHTAttestationVerifier`** (verify-on-fetch
  in `find_agents`). Library ships; integration is the follow-up.
  Blocked on bootstrap-set config.
- Substitution-defense check requires the fetched cert to specify
  its applicant_pubkey; we enforce this is consistent with the
  queried pubkey.

## Alternatives considered

- **Trust every cosigner's pubkey by default.** Rejected: this is
  the status quo and the attack vector.
- **Stake-based validator trust.** Rejected at Phase 3 scope —
  requires token (per ADR-0004 deferral). Reconsidered in vNext
  (ADR-0015 layer 6).
- **Foundation-signed certificate of validator authority (PKI-style).**
  Considered but rejected: less decentralized; reintroduces a
  central CA. Trusted-bootstrap set is the equivalent without a
  signing authority — just a published pubkey list.

## References

- `netd/internal/capability/recursive.go` — RecursiveVerifier
- `netd/internal/capability/recursive_test.go` — 11 unit tests
- ADR-0013 (verify-on-fetch — wiring target for this verifier)
- CLAUDE.md §5-pre-4 (Session 16 narrative)
- CLAUDE.md §6 A5 (open follow-up: wire into find_agents)
