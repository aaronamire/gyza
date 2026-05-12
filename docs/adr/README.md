# Architecture Decision Records (ADRs)

> **Purpose.** Document every load-bearing architectural decision
> with its context, the choice made, the consequences accepted, and
> the alternatives considered. Future sessions / contributors can
> understand *why* the codebase is shaped the way it is, not just
> what it does.
>
> **Audience.** Future Claude sessions; future human maintainers;
> vNext implementers who need to understand v1's commitments before
> migrating.

## Why we have ADRs (Session 20 / Phase 0 Stream 4)

§8 of CLAUDE.md commits to an ADR log as part of Phase 0 of the
vNext migration. Decisions are recorded so:

1. The Rust implementation team in Phase 2 can see *why* v1 looks
   the way it does. Some decisions transfer; others get replaced.
2. Strategic-decision sessions (like Session 17's vNext commitment)
   have a permanent home for their rationale.
3. Future debates ("should we change X?") have a baseline:
   the ADR captures the original tradeoffs.

ADRs 0001 through ~0015 are **retroactive** — they document
decisions made in Sessions 1–17 before the ADR log existed. From
ADR-0016 forward, ADRs are written prospectively as decisions are
made.

## Format

Each ADR is a separate markdown file at `docs/adr/NNNN-slug.md`
where NNNN is a 4-digit zero-padded ID.

Standard sections:

- **Status.** One of: Proposed, Accepted, Deprecated, Superseded.
  Superseded ADRs link to the superseding ADR.
- **Context.** The problem being solved. What state was the project
  in? What constraints existed?
- **Decision.** The choice made. Concrete and specific.
- **Consequences.** What follows from the choice — both intended
  benefits and accepted costs / tradeoffs.
- **Alternatives considered.** Brief; what else was on the table.
- **References.** Code sites, session narratives, related ADRs.

A short ADR is fine. Aim for 30–80 lines. Decisions that took a
whole session deserve more; trivial decisions don't need an ADR
at all.

## When to write an ADR

Required for:

- Any choice that affects ≥2 modules across the codebase
- Wire-format / protocol changes
- Cryptographic primitive selection
- Concurrency model choices
- Strategic commitments (e.g., the vNext architectural commitment)
- Anything that future contributors might want to revisit and
  ask "why this?"

Not required for:

- Local refactors that don't change interfaces
- Bug fixes
- Documentation updates
- Test additions

## ADR index

| ID | Title | Status | Session |
|---|---|---|---|
| [0001](0001-python-go-split-via-grpc.md) | Python + Go split with gRPC bridge | Accepted | Phase 3 / 1 |
| [0002](0002-ed25519-blake3-cryptographic-primitives.md) | Ed25519 + BLAKE3 cryptographic primitives | Accepted | Phase 1 |
| [0003](0003-384-dim-embeddings-lsh-discovery.md) | 384-dim embeddings + LSH bucketing for discovery | Accepted | Phase 3 / 8.5 |
| [0004](0004-bilateral-compute-credit-settlement.md) | Bilateral compute-credit settlement | Accepted | Phase 3 |
| [0005](0005-linear-icp-envelope-chains.md) | Linear ICP envelope chains for provenance | Accepted | Phase 1 |
| [0006](0006-blackboard-coordination-pattern.md) | Blackboard as coordination substrate | Accepted | Phase 1 |
| [0007](0007-kademlia-dht-gyza-1-0-prefix.md) | Kademlia DHT under /gyza/1.0 protocol prefix | Accepted | Phase 3 |
| [0008](0008-bwrap-executor-sandboxing.md) | bwrap-based executor sandboxing | Accepted | Session 10 |
| [0009](0009-tier3-quorum-attestation.md) | Tier-3 attestation with k-of-n quorum cosignatures | Accepted | Session 11 |
| [0010](0010-libp2p-capability-stream.md) | libp2p `/gyza/capability-challenge/1.0.0` for cross-network attestation | Accepted | Session 12 |
| [0011](0011-python-initiated-bidi-grpc-bridge.md) | Python-initiated bidi gRPC for cross-language attestation bridge | Accepted | Session 13 |
| [0012](0012-applicant-proposed-attestation-body.md) | Applicant-proposed AttestationBody for multi-validator quorum | Accepted | Session 14 |
| [0013](0013-verify-on-fetch-cached-verifier.md) | TTL-cached single-flight verify-on-fetch verifier | Accepted | Session 15 |
| [0014](0014-recursive-tier3-trusted-bootstrap.md) | Recursive Tier-3 verification with trusted bootstrap set | Accepted | Session 16 |
| [0015](0015-vnext-architectural-commitment.md) | vNext as the committed architectural target | Accepted | Session 17 |

## Updating the index

When adding a new ADR:

1. Assign the next sequential ID.
2. Create `NNNN-slug.md`.
3. Add an entry to the table above.
4. Reference the ADR from the session narrative in CLAUDE.md §5.

When deprecating or superseding an ADR:

1. Update the superseded ADR's Status field to `Superseded by ADR-NNNN`.
2. Add a deprecation note at the top of the file.
3. Keep the original content for historical reference.
