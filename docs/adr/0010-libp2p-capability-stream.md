# ADR-0010: libp2p `/gyza/capability-challenge/1.0.0` for cross-network attestation

**Status:** Accepted (Session 12).

## Context

Session 11 (ADR-0009) shipped the attestation protocol's
algorithmic core (challenge issuance, response verification, cert
assembly + verification) as in-process Python. To get
**cross-network** attestation, two daemons need to ferry the
Challenge / Response / VerifyResult exchange over the wire.

The codebase already had a `/gyza/message/1.0.0` libp2p stream
protocol for generic application messages (length-prefixed message
type + payload). The attestation flow could in principle ride on
top of that, but it has structured semantics (always 3 frames, all
proto-typed) that warrant a dedicated protocol ID.

A canonicalization question also surfaced: Session 11's Python
implementation used JSON-canonicalized bytes for cosig signing,
while the existing Go `capability` package used
`proto.MarshalOptions{Deterministic: true}`. Different bytes →
non-aggregatable cosigs across languages.

## Decision

- New libp2p protocol: `/gyza/capability-challenge/1.0.0`.
- New package: `netd/internal/capability_stream/`.
- **Wire format:** 3 frames per stream, each `[uvarint_len][marshaled_proto]`.
  Frame 1: validator→applicant Challenge. Frame 2:
  applicant→validator ChallengeResponse. Frame 3: validator→applicant
  VerifyResponseResult.
- **Canonical bytes:** deterministic protobuf marshal everywhere.
  Python's JSON-canonical path (from Session 11) stays as the
  in-process Tier-1 implementation; cross-network uses Go protobuf
  deterministic marshal as the single canonical wire format.
- **Applicant pubkey** extracted from libp2p `RemotePeer` (Noise-
  authenticated PeerID). NOT from a wire-claimed field — that
  would let an applicant claim a different identity than its
  libp2p connection identity.
- **No kickoff frame.** Validator initiates by reading the
  applicant's libp2p identity. Saves a round trip.
- **Per-stream deadline:** `StreamTimeout = 120 s` bounds the whole
  exchange. Long enough for real-LLM eval; short enough that a
  slow/malicious peer can't pin host goroutines.

## Consequences

**Intended:**
- Cross-network attestation works exactly as in-process
  attestation, just over the wire.
- Wire-format isolation: protocol bumps (e.g., to /2.0.0) don't
  affect other libp2p protocols.
- Cross-language byte-identical canonical bytes via deterministic
  protobuf marshal. Python's protobuf library produces the same
  bytes Go does, so Python applicants can sign and Go validators
  can verify.
- Validator rejections wire-encoded as VerifyResponseResult
  {Success=false, Error=<reason>}. Applicant has uniform read
  semantics regardless of error type.

**Accepted costs:**
- Python's Session 11 JSON-canonical implementation can't aggregate
  cosigs with Go validators. It's kept for in-process Tier-1
  attestation only.
- `MalleableSigs`-style defense relies on Noise: a compromised
  Noise handshake would let an attacker claim a different
  compositor pubkey. libp2p Noise is well-audited but worth
  noting.
- Validator's task list is hardcoded to match `gyza/capability_eval.py::EVAL_TASKS`.
  Drift between the two surfaces silently as "missing task result"
  rejection. Keep them in sync manually until task negotiation
  lands (vNext, ADR-0015 layer 7).

## Alternatives considered

- **Reuse `/gyza/message/1.0.0`.** Rejected: attestation has fixed
  3-frame structure with typed protos; warrants its own protocol
  ID for clarity and version-bump independence.
- **Make Python's JSON-canonical the cross-network format.**
  Rejected: Go validators already use deterministic protobuf; Go
  is the libp2p owner; Python's JSON path would need a Go-side
  shim that adds canonicalization complexity.
- **4-frame protocol with applicant kickoff frame.** Rejected:
  redundant (applicant identity is in the libp2p connection) AND
  introduces a misuse vector (applicant could claim a different
  pubkey than its libp2p identity).

## References

- `netd/internal/capability_stream/capability_stream.go`
- `netd/internal/capability/capability.go` — challenge issue/verify
- ADR-0009 (Tier-3 attestation algorithmic core)
- ADR-0011 (Python bridge to this libp2p protocol)
- CLAUDE.md §5a (Session 12 narrative)
