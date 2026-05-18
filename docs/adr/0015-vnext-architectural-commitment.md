# ADR-0015: vNext as the committed architectural target

**Status:** Accepted (Session 17). Strategic-decision ADR.

## Context

Through Phase 3 (Sessions 1–16), the architecture organically
evolved as features landed. Sessions 11–16 closed the #21 cluster
(Tier-3 attestation). At end of Session 16 the §6 priority list
had three open buckets: A-bucket trip-wires (mostly closed),
B-bucket deployment blockers (operational, user-owned), C-bucket
structural directions.

C-bucket included an explicit choice: continue retrofitting the
current architecture, or commit to a vNext rewrite. The
long-horizon target (planet-scale beneficial AI coordination) is
incompatible with the current architecture's structural
commitments. The structural issues catalogued earlier
(bilateral-only settlement, LSH-only discovery, linear ICP chains,
blackboard pattern, single-resource pricing, Ed25519-only
identity, no formal spec, no privacy primitives) can't be
retrofitted at scale — they have to be replaced.

## Decision

vNext is the **committed architectural target.** Not one
trajectory among several — the architecture every future session
works toward.

**14 layers committed at the architectural level:**

1. Formal foundation (TLA+ spec + Coq/Lean proofs + Rust ref impl + ADR log)
2. Cryptographic identity (hybrid PQ + threshold + HD + W3C VC + ZK)
3. Data substrate (IPLD + Merkle Mountain Ranges + erasure-coded + zk-STARKs + VRFs)
4. Network substrate (libp2p + multi-tier discovery + typed capability negotiation + auctions)
5. Coordination substrate (distributed logs + CRDTs + differential dataflow + typed channels)
6. Settlement (three-layer: bilateral L0 / multilateral DAG L1 / BFT L2 + multi-dimensional pricing + multi-token)
7. Capability framework (typed values + linear types + per-domain tiered evals + federated learning)
8. Execution (universal sandboxing + hardware attestation + capability tokens + zk-STARK verifiable)
9. Privacy (encrypted-by-default + onion + ZK + DP + anonymous credentials)
10. Governance (constitutional invariants + quadratic voting + foundation→DAO sunset)
11. Safety architecture (cryptographic capability bounds + typed approval gates + immune system)
12. Substrate diversity (LLM/CPU/GPU/neuromorphic/quantum/sensor/actuator)
13. Distribution (multi-region + mobile/browser/embedded/edge/satellite/mesh)
14. Implementation (Rust core + PyO3 + UniFFI + wasm-bindgen)

**Operational rules for sessions:**

1. **§C1 (TLA+ spec of v1) is the immediate top priority.** Every
   downstream vNext layer depends on a verified spec of what v1
   does.
2. **Phase 3 hardening continues; Phase 4–9 feature work pauses.**
   Bug fixes, security patches, packaging, CI continue on v1. New
   feature work ships on vNext, not v1.
3. **Wire formats from this point forward are forward-compatible.**
   v1↔v2 coexistence during the migration window.
4. **"Retrofit" is not the framing.** §6 C5 items are "migration
   milestones," not retrofits.
5. **Strategic decisions in §13 are partially settled by §8.**
   Multi-token economics, encrypted-by-default privacy, formal-spec
   discipline, Rust core are no longer open questions. Specifics
   (which PQ algorithm, which token mechanics) remain design surface.

**Design surface remaining within the commitment:**

- Specific PQ signature algorithm (waits for NIST PQC standardization)
- Specific zk-proof system (STARK / SNARK / Bulletproofs depending on use case)
- Specific differential-dataflow engine
- Learned routing (research-frontier; vNext phase 2, not day 1)
- Specific token distribution mechanics (with regulatory counsel)
- UCBI activation (political-economic choice, architecturally enabled)
- Specific TEE vendor matrix (evolves with hardware availability)
- Specific governance voting mechanism (within the constitutional fence)
- Cross-AI-network federation (vNext phase 2)

## Consequences

**Intended:**
- A coherent, ambitious architectural target every session is
  working toward.
- Phase 4–9 feature work targets the right substrate (v2), not
  thrown away during migration.
- Strategic decisions partially settled; future sessions don't
  re-litigate.

**Accepted costs:**
- **18–36 months to vNext production-shaped.** During this period,
  the network gets hardened + rewritten, not new features.
- **Python+Go velocity loss to Rust core.** Memory safety +
  formal verifiability worth the trade.
- **TEE hardware requirements at high-trust tiers.** Some consumer
  hardware excluded.
- **Multi-token regulatory complexity.** Reverses current's
  "no token" stance; triggers securities-law, money-transmitter
  rules per jurisdiction.
- **Three-layer settlement complexity.** More moving parts than
  bilateral-only.
- **Phase 4–9 v1 feature work paused for migration duration.**

## Alternatives considered

- **Continue incremental retrofit of v1.** Rejected: structural
  commitments in v1 (bilateral-only, LSH-only, blackboard, linear
  ICP, single-resource pricing) can't be retrofitted to §9 target.
- **Different vNext architecture.** Several coherent alternatives
  exist (process-calculus-first, confidential-computing-first,
  capability-as-channel throughout, blockchain-native L2). vNext
  as defined here is one defensible portfolio of tradeoffs; not
  provably optimal.
- **Defer commitment indefinitely.** Rejected: organic evolution
  was producing structural debt faster than it was being paid
  down. Commitment lets the team align around a target.

## References

- README → "The agentic civilization" (the long-horizon framing
  + honest gradient).
- ADR-0001 through 0014 (decisions superseded or refined by vNext).
- ADR-0016 onwards (forward decisions under the commitment).
