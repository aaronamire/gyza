# ADR-0011: Python-initiated bidi gRPC for cross-language attestation bridge

**Status:** Accepted (Session 13).

## Context

ADR-0010 shipped the `/gyza/capability-challenge/1.0.0` libp2p
stream protocol. The daemon owns libp2p connections; the Python
applicant owns the AgentRunner that runs the eval suite. The two
need to talk: when a validator's daemon issues a Challenge, the
applicant's daemon needs to forward it to Python; Python runs the
eval; daemon sends the response back to the validator.

The question: which direction does the daemon-Python interface
flow?

Option A: Daemon dials Python. Python registers as a callback
server; daemon calls into it when a Challenge arrives.

Option B: Python initiates. Python opens a bidi gRPC stream;
daemon sends Challenge over the stream when one arrives; Python
returns the Response over the same stream.

## Decision

**Option B: Python-initiated bidirectional streaming gRPC** on
`CapabilityService.RequestAttestation`.

- Python opens the stream, sends `AttestationStartRequest{target_peer_id}`
  as the first frame.
- Daemon opens the libp2p capability-challenge stream to the
  target. Reads Challenge from libp2p, forwards over gRPC.
- Python receives Challenge, runs eval via `applicant_eval_session`,
  sends ChallengeResponse over gRPC.
- Daemon forwards over libp2p, reads VerifyResponseResult, emits
  Outcome over gRPC.
- Stream closes.

3 frames each direction, mirroring the libp2p protocol shape
exactly.

**Validator-side relaxation:** `verifyTaskResult` no longer
requires `agent_pubkey == applicant_pubkey`. ICP envelopes are
signed by AGENT keys (HKDF-derived from compositor seed); response
body is signed by COMPOSITOR. The agent ↔ compositor binding is
the capability manifest's responsibility (documented follow-up).

## Consequences

**Intended:**
- **Per-stream isolation.** Each attestation has its own gRPC
  stream; multi-tenant routing is trivial (whoever opened the
  stream owns the response).
- **HTTP/2 backpressure.** Python's slow eval doesn't pin the
  daemon's libp2p read goroutine. The daemon reads at libp2p
  rate; gRPC stream buffers; Python pulls when ready.
- **Multi-tenant.** Multiple Python clients can each initiate
  attestations; the daemon multiplexes by stream.
- **Graceful failure.** gRPC cancel → daemon's libp2p stream times
  out → daemon emits Outcome with error reason. Python's read loop
  has one uniform shape.

**Accepted costs:**
- Python is the initiator. The daemon doesn't initiate Python work.
  Use cases where the daemon wants to ASK Python something (e.g.,
  "should I cosign this challenge?") need a different mechanism
  (currently none; cosigning happens in-daemon via the Go
  capability package, not Python).
- The Session 11 in-process orchestrator (`run_attestation` in
  `gyza/network/capability_protocol.py`) and the cross-network
  bridge (`attestation_adapter.py`) coexist. They look conceptually
  overlapping but each serves a different scope (Tier-1
  self-attestation in-process vs. Tier-3 cross-network).
- Validator no longer requires agent == applicant. Trust now goes
  through the capability manifest path (documented follow-up,
  CLAUDE.md §6 A — not yet wired).

## Alternatives considered

- **Option A: daemon dials Python.** Rejected because:
  - Inverts gRPC client→server direction unconventionally.
  - Forces Python to expose a server endpoint with multi-callback
    routing.
  - Stalls daemon's libp2p read goroutine on a slow synchronous
    Python callback.
- **Out-of-band signaling (e.g., file system).** Rejected:
  high-latency, brittle, hard to multiplex.

## References

- `netd/internal/grpc/server.go::RequestAttestation` — bridge impl
- `gyza/network/netd_client.py::CapabilityClient.request_attestation`
- `gyza/network/attestation_adapter.py` — Python eval orchestrator
- ADR-0010 (the libp2p protocol this bridges to)
- CLAUDE.md §5-pre (Session 13 narrative)
