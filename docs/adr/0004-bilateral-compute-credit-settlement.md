# ADR-0004: Bilateral compute-credit settlement

**Status:** Accepted (Phase 3 / Session 1 of Phase 3). Becomes L0
of a three-layer stack in vNext (ADR-0015 layer 6).

## Context

Phase 3 needed an economic primitive for cross-cluster work
exchange. A node that completes work for another should earn
something redeemable. Options ranged from full BFT consensus
ledger (Ethereum-style) to bilateral records to no settlement at
all.

The protocol's threat model is collaboration between cooperating
peers, not adversarial-from-day-one byzantine actors. Most
interactions are pairwise: peer A asks peer B to do work; B does
it; A pays B in credits.

## Decision

- Settlement is **bilateral.** Each pair (A, B) maintains its own
  ledger of entries between them.
- Each entry is **earner-signed → payer-cosigned → applied.** Earner
  posts after completing work; payer verifies envelope + amount
  tolerance + signature; payer cosigns; earner applies on receiving
  cosig.
- Both peers store byte-identical applied entries.
- No global ledger. No global consensus. No mining.
- Conservation is per-pair, not network-wide.

## Consequences

**Intended:**
- Simplicity. No consensus protocol to operate; no Byzantine
  agreement; no expensive cryptographic primitives.
- Scales infinitely in the trivial sense: every pair is independent.
- Privacy: only the two peers see the entry.
- No regulatory exposure: no tradeable token; just compute-for-
  compute exchange.

**Accepted costs:**
- N-party transactions don't compose cleanly. A supply-chain
  workflow involving 4 peers requires 6 bilateral settlements with
  ad-hoc coordination.
- No global finality. An entry is "applied" between two peers but
  the rest of the network has no way to verify it without their
  cooperation.
- O(N²) ledger state in the limit. Every peer maintains a ledger
  per counterparty.
- Conservation is implicit (both sides apply the same canonical
  entry bytes); no proof against drift if cosigning is bypassed.
  Sessions 9's reconciliation RPC (ADR not written for that —
  see CLAUDE.md §5d) addresses recovery from accidental drift.
- "No token" stance turns out to be the biggest brake on adoption
  (see CLAUDE.md §13). vNext reverses this — see ADR-0015 layer 6
  for multi-token economics.

## Alternatives considered

- **Global consensus ledger (Ethereum/Solana style).** Rejected:
  operational complexity, mining/staking overhead, regulatory
  exposure of a token, latency.
- **Multilateral DAG (IOTA Tangle).** Rejected at Phase 3 scope —
  more moving parts than bilateral; benefits less clear until N-party
  workflows become common.
- **No settlement (reputation-only).** Rejected: reputation alone
  doesn't capture cost; volunteer-only economics doesn't scale.

## References

- `gyza/economy/ledger.py` — bilateral ledger
- `gyza/economy/settlement.py` — settlement service protocol
- `spec/Settlement.tla` — formal spec (Session 19)
- `docs/state-machines.md` § Settlement entry lifecycle
- ADR-0015 (vNext layer 6 — three-layer settlement; bilateral
  becomes L0 of a stack)
- CLAUDE.md §13 (strategic positioning — tokenomics reversal)
