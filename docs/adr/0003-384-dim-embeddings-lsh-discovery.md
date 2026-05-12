# ADR-0003: 384-dim embeddings + LSH bucketing for discovery

**Status:** Accepted (Phase 3 / Session 8.5). Replaced by typed
capability negotiation in vNext (ADR-0015 layer 4).

## Context

Phase 3 needed cross-cluster discovery of agents by capability.
"Find me an agent good at Python code." The naive approach — exact
string matching on capability strings — fails at scale (many
synonyms) and doesn't generalize to multi-modal capability.

A semantic embedding representation of capability supports fuzzy
matching, multi-modal extension, and integration with the runner's
specialization drift mechanism.

## Decision

- **Embedding:** `sentence-transformers/all-MiniLM-L6-v2`, 384-dim,
  L2-normalized.
- **Bucketing:** 64-bit LSH (Locality-Sensitive Hashing) with 64
  random hyperplanes. Each bucket bit is `sign(dot(emb, plane_i))`.
- **Discovery:** Hamming-radius-2 neighbor search around the query
  bucket; cosine similarity for ranking within candidates.
- **Cross-language:** Plane seeds shared between Python and Go via
  a generated `scripts/generate_lsh_planes.py` artifact.

## Consequences

**Intended:**
- Discovery composes with the runner's drift mechanism: an agent's
  specialization vector drifts toward the work it completes,
  naturally bucketing it near matching demand.
- LSH gives O(1) bucket lookup; Hamming-radius enumeration gives
  configurable recall-vs-cost tradeoff.
- Cross-language deterministic via shared plane seeds.

**Accepted costs:**
- 384-dim is hardcoded throughout. Changing it invalidates every
  AgentBucket record on the DHT (constitutional invariant — see
  CLAUDE.md §16 don't-do list).
- LSH cosine similarity doesn't compose with typed constraints
  ("input=text AND output=code AND latency<100ms AND jurisdiction=EU").
  String-typed capability is the limit; multi-modal Phase 6 work
  needs a richer matching primitive (see ADR-0015 layer 4).
- Single canonical embedding model. Every node MUST use the same
  `model_id` or LSH buckets disagree byte-for-byte. Phase 4 federated
  learning hasn't broken this yet but Phase 8 substrate diversity
  will (each substrate may produce embeddings in different spaces;
  needs a canonical reference embedding model — see ADR-0015 layer 12).
- Hamming-radius-2 enumerates 2017 neighbor buckets. At larger
  radii the cost balloons.

## Alternatives considered

- **HNSW (Hierarchical Navigable Small World) graph index.** Better
  recall-at-k but harder to distribute across a DHT. The bucket-
  based approach lets each bucket be one DHT record.
- **Learned routing.** ML-augmented match scoring. Deferred to
  vNext phase 2 (ADR-0015 layer 4 lists this as a design surface
  remaining).
- **Pure string-typed capability matching.** Rejected: doesn't
  generalize past keyword exact-match; fragile to wording.

## References

- `gyza/embeddings.py` — Embedder protocol + ST + Stub backends
- `gyza/demand.py::LSHIndex` — Python LSH
- `netd/internal/dht/dht.go::LSHIndex` — Go LSH
- `scripts/generate_lsh_planes.py` — shared plane seeds
- ADR-0015 (vNext layer 4 — typed capability negotiation replaces
  LSH-cosine-only matching)
- CLAUDE.md §3 trip-wires (embedding-dim immutability)
