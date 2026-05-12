# ADR-0005: Linear ICP envelope chains for provenance

**Status:** Accepted (Phase 1). Replaced by Merkle DAG provenance
in vNext (ADR-0015 layer 3).

## Context

Phase 1 needed a way to capture the chain of computation that led
to any artifact. "Agent A produced X by combining outputs of agents
B and C; B used the intent's prompt; C used the user's seed file."
This provenance trail is needed for: auditability, dispute
resolution (who did what), capability composition.

The simplest model is a linear chain: each envelope references its
single parent envelope by hash. Multi-parent extensions are awkward
but achievable as a flat list of parent hashes.

## Decision

- Each agent action emits one **ICP envelope** signed by the agent's
  identity (not the compositor's).
- Envelope contains: `agent_pubkey`, `output_hash`,
  `parent_envelope_hashes[]`, `action_id`, `hlc`, `timestamp_ns`,
  `metadata`, `signature`.
- `envelope_hash` = `BLAKE3(canonical_json(envelope_minus_signature))`.
- Chain verification (`gyza/icp.py::verify_chain`) walks the chain
  root-to-leaf, verifying each envelope's signature and that each
  non-root envelope's parents are in the chain.
- The blackboard's `icp_envelopes` table is **append-only.**
- Strict mode (`strict_chain_verification=True`) rejects on missing
  parent; non-strict warns and proceeds.

## Consequences

**Intended:**
- Per-action signing is cheap.
- Chain reconstruction is local (just walk parent hashes).
- Multi-parent extensions work (parent_envelope_hashes is a list).
- Strict-mode flag accommodates gossip lag.

**Accepted costs:**
- Linear chain verification is O(n) — fine for short chains, slow
  for deep ones.
- Multi-parent merge operations don't have a single canonical chain
  representation. The verifier handles them but downstream consumers
  often want a "the chain" as one ordered list.
- Single-key envelopes today; multi-compositor verification exists
  in `verify_chain_multi_compositor` but requires extra plumbing
  (trust registry, artifact store) not present in the runner. Don't
  use it in the runner (CLAUDE.md §16 don't-do).
- Storage grows monotonically. No pruning.
- vNext (ADR-0015 layer 3) replaces with Merkle DAG + MMR for
  log-compressed verification.

## Alternatives considered

- **Merkle DAG (IPLD-style).** Better for multi-parent and pruning,
  but more complex to implement and verify. Deferred to vNext.
- **No provenance.** Rejected: auditability is load-bearing for
  Tier-3+ trust and dispute resolution.
- **Compositor-signed envelopes (no agent identity).** Rejected:
  conflates compositor (durable identity) with agent (ephemeral
  worker). Agent rotation under compositor would require key reuse
  or compositor signature on every action.

## References

- `gyza/icp.py` — envelope + signing + chain verification
- `gyza/blackboard.py::store_envelope`, `reconstruct_chain`
- `gyza/runner.py::_complete` — runner persists envelope
- ADR-0015 (vNext layer 3 — Merkle DAG provenance)
- ADR-0009 (Tier-3 attestation uses ICP envelopes in TaskResults)
- CLAUDE.md §16 (don't use multi-compositor verifier in runner)
