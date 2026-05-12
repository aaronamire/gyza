# ADR-0012: Applicant-proposed AttestationBody for multi-validator quorum

**Status:** Accepted (Session 14). Load-bearing canonicalization fix.

## Context

ADR-0009 established that a Tier-3 cert is k-of-n cosigs over a
canonical body. ADR-0011 wired the Python applicant to the Go
validator via libp2p. Session 14 tried to scale from 1 validator to
multiple validators and found a critical bug.

The Go validator's `VerifyResponse` was authoring its own
`AttestationBody` per call, with `IssuedAtNs: now.UnixNano()` —
wall-clock, validator-local. Two validators called from the same
applicant within milliseconds of each other produced DIFFERENT body
bytes (different `IssuedAtNs`). Their cosigs signed different
messages → **could not aggregate** into a quorum-verifiable cert.

`AssembleAttestation`'s docstring claimed validators "echo back
identical bodies." The code didn't. The unit test passed only
because it manually constructed ONE body and had every signer sign
that shared bytes — a synthetic setup not matching the network path.

## Decision

Add an `AttestationBody proposed_attestation_body = 3;` field to
`ChallengeResponse`. The applicant proposes ONE body for the
attestation session; every validator signs that proposed body.

- **Applicant side** (`applicant_eval_session`): construct one
  `AttestationBody` at session entry. Include it (via `CopyFrom`
  to avoid reference aliasing) in every `ChallengeResponse` for
  the session. Multi-validator orchestrators that share one session
  are guaranteed quorum-aggregatable cosigs.
- **Validator side** (`verifyProposedAttestationBody`): when an
  applicant supplies a proposed body, prefer it over authoring one.
  Run **6 plausibility checks** to defend against misuse:
  1. `applicant_pubkey` matches the libp2p PeerID's compositor
     pubkey (binding to identity)
  2. `tier_granted == IssuedTier` (3) — no minting non-Tier-3
     certs via this protocol
  3. `issued_at_ns` within ±1h of validator's clock (no past- or
     future-dated certs evading freshness)
  4. Lifetime ≤ `MaxAttestationTTL` (90 days; ~perpetual-cert
     prevention)
  5. Not already expired (`expires_at_ns > now`)
  6. `challenge_task_ids` match THIS validator's challenge (cosig
     misrepresenting what was verified)

Backward-compat: existing single-validator path still authors its
own body when `proposed_attestation_body` is absent. Session 13's
unit tests pass unchanged.

## Consequences

**Intended:**
- Multi-validator quorum cosigs aggregate cleanly. Cert assembles
  and self-verifies.
- 6 attack vectors actively defended at the validator side.
- Applicant has agency over body shape (within plausibility bounds);
  validators don't impose their wall clock.

**Accepted costs:**
- Validator's authority over freshness is now ±1h skew tolerance
  rather than "validator decides." Clock-skew within 1h is allowed.
  Adversarial applicants could try to backdate certs slightly; the
  ±1h bound is the trade-off.
- `AssembleAttestation`'s docstring lingered as "echo back identical
  bodies" before the fix; corrected behavior is now in
  `verifyProposedAttestationBody`. Comment cleanup is a follow-up.

## Trip-wire surfaced

- **`AttestationBody`'s `IssuedAtNs` is wall-clock; capturing it
  once outside a per-subtest loop produces stale timestamps that
  appear out-of-order against fresh challenges.** The
  plausibility-check matrix test had to use `time.Now()` inside the
  per-subtest loop AFTER `IssueChallenge`. Documented in CLAUDE.md
  §5-pre-2.

## Alternatives considered

- **Validator-authored body with a "session id" coordination
  mechanism.** Rejected: requires extra negotiation step; doesn't
  defend against malicious validator authoring inconsistent bodies.
- **Applicant-signed body in addition to cosigs.** Rejected:
  redundant. The applicant's signature on `ResponseBody` already
  binds the response to the applicant; the cosig binds the body to
  the validator.

## References

- `netd/internal/capability/capability.go::verifyProposedAttestationBody`
- `netd/internal/grpc/proto/netd.proto::ChallengeResponse`
- `gyza/network/attestation_adapter.py::applicant_eval_session`
- ADR-0009 (Tier-3 attestation core)
- CLAUDE.md §5-pre-2 (Session 14 narrative)
