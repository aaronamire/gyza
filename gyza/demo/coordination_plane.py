"""
Coordination plane — a content-addressed CRDT over ICP envelopes.

WHAT THIS IS, AND WHY IT IS NOT THE EXISTING MERGE
--------------------------------------------------
``gyza.blackboard`` already has ``merge_claim_direct`` /
``merge_completion_direct``, but those resolve conflicts by
**Hybrid-Logical-Clock last-writer-wins**, and the HLC's ``l`` field
is wall-clock milliseconds (``gyza.schema._pt_ms``). For a DDIL
deployment that is the wrong tool: it is AP-correct only if you trust
clocks, and it *discards* the loser of a concurrent edit. This plane
makes two different commitments:

  1. **Ordering is derived from the ICP ``parent_envelope_hash``
     chain, never from timestamps.** BLAKE3 linkage is the ground
     truth for "what came before what".
  2. **Nothing signed is ever discarded.** A partition causes the
     history to *fork* (both sides legitimately extend the last
     shared envelope — this is inherent to an available data plane,
     not a defect). Reconciliation keeps *both* branches, each
     independently verifiable. Adjudicating which fork is canonical
     downstream is a human-on-the-loop decision, not something the
     protocol fakes with a clock.

THE CRDT
--------
A grow-only set (G-Set) of ICP envelopes, keyed by their BLAKE3
envelope hash. We choose a G-Set over an OR-Set deliberately: a
signed action is an immutable historical fact. A claim-release or a
completion is *another* event, never the removal of a prior one, so a
monotone union is the honest model — and it is a join-semilattice, so
Strong Eventual Consistency (Shapiro et al. 2011) follows.

Because the key is a cryptographic content address, ``merge`` is a
*conflict-free* union in the strongest possible sense: two replicas
that hold the same key are guaranteed by BLAKE3 collision-resistance
to hold byte-identical values. There is no "which write wins"
question to answer. ``merge`` is therefore trivially commutative,
associative, and idempotent — the three laws this module's property
tests assert, because they are precisely the laws that make
convergence a theorem rather than a hope.

The state has no signature-verification logic of its own: it is a
transport/convergence substrate. Verification is an *orthogonal*
predicate (``gyza.icp.verify_chain`` for linkage+signatures,
``gyza.economy.delegation.verify_delegation`` for capability
containment) applied to the linear chains this plane reconstructs.
Conflating storage with verification would be a modeling error — the
same separation the delegation module insists on.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from gyza.icp import ICPEnvelope, compute_envelope_hash


class CoordinationState:
    """
    A single replica's view of the coordination plane.

    Internally a ``{envelope_hash: ICPEnvelope}`` map. The map *is* the
    G-Set; the key being a content address is what makes every CRDT law
    hold for free. Instances are cheap to copy and merge.
    """

    __slots__ = ("_envelopes",)

    def __init__(self) -> None:
        self._envelopes: dict[str, ICPEnvelope] = {}

    # ------------------------------------------------------------------
    # Mutation (monotone — only ever grows)
    # ------------------------------------------------------------------

    def add(self, envelope: ICPEnvelope) -> str:
        """
        Insert a signed envelope. Returns its content-address hash.

        Idempotent: re-adding the same envelope is a no-op because the
        key is the content address. Adding a *different* envelope that
        somehow produced the same hash is cryptographically infeasible,
        so we never have to choose between conflicting values.
        """
        h = compute_envelope_hash(envelope)
        # First-writer semantics are irrelevant under content addressing:
        # any value already stored under ``h`` is byte-identical to this
        # one. We keep the existing object to make identity stable.
        self._envelopes.setdefault(h, envelope)
        return h

    def add_all(self, envelopes: "list[ICPEnvelope]") -> None:
        for e in envelopes:
            self.add(e)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._envelopes)

    def __contains__(self, envelope_hash: str) -> bool:
        return envelope_hash in self._envelopes

    def event_hashes(self) -> frozenset[str]:
        """The digest of known events — what gossip compares to find gaps."""
        return frozenset(self._envelopes)

    def get(self, envelope_hash: str) -> ICPEnvelope | None:
        return self._envelopes.get(envelope_hash)

    def envelopes(self) -> "list[ICPEnvelope]":
        """All stored envelopes, in content-address order (deterministic)."""
        return [self._envelopes[h] for h in sorted(self._envelopes)]

    def copy(self) -> "CoordinationState":
        out = CoordinationState()
        out._envelopes = dict(self._envelopes)
        return out

    # ------------------------------------------------------------------
    # Merge — the CRDT join. Commutative, associative, idempotent.
    # ------------------------------------------------------------------

    @staticmethod
    def merge(
        a: "CoordinationState", b: "CoordinationState"
    ) -> "CoordinationState":
        """
        Set union of two replicas' envelope maps.

        Pure: neither argument is mutated; a fresh state is returned, so
        the operation is safe to fold over an arbitrary message order.
        Conflict-free because keys are content addresses (see module
        docstring).
        """
        out = CoordinationState()
        out._envelopes = dict(a._envelopes)
        for h, env in b._envelopes.items():
            out._envelopes.setdefault(h, env)
        return out

    def merge_in(self, other: "CoordinationState") -> None:
        """In-place merge (convenience for gossip apply). Same semantics."""
        for h, env in other._envelopes.items():
            self._envelopes.setdefault(h, env)

    # ------------------------------------------------------------------
    # Deterministic reconstruction — ordering from ICP linkage only.
    # ------------------------------------------------------------------

    def _children_map(self) -> "dict[str | None, list[str]]":
        """
        Map each envelope hash to the hashes of its ICP children.

        An envelope is a *root* (bucketed under ``None``) when its
        ``parent_envelope_hash`` is ``None`` or points outside the set
        we currently hold (a dangling anchor — e.g. a parent that hasn't
        gossiped to us yet). Treating a dangling parent as a root keeps
        reconstruction total even on a partial replica.
        """
        present = set(self._envelopes)
        children: dict[str | None, list[str]] = {}
        for h, env in self._envelopes.items():
            parent = env.parent_envelope_hash
            anchor = parent if (parent is not None and parent in present) else None
            children.setdefault(anchor, []).append(h)
        return children

    def linear_chains(self) -> "list[list[ICPEnvelope]]":
        """
        Every root-to-leaf path through the ICP linkage forest.

        Each returned path is a *linear* ICP chain — exactly the shape
        ``gyza.icp.verify_chain`` validates. A history that forked under
        partition yields multiple paths that share a prefix; an
        un-forked history yields a single path.

        Determinism (the property the demo asserts): ordering *within* a
        path follows ``parent_envelope_hash`` pointers, and wherever a
        node has multiple children the children are visited in
        content-address (hash) order. The list of paths is finally
        sorted by leaf hash. No wall-clock, no insertion order, no HLC
        participates — two replicas holding the same envelope set return
        byte-identical results.
        """
        children = self._children_map()
        chains: list[list[ICPEnvelope]] = []

        def walk(h: str, prefix: "list[ICPEnvelope]") -> None:
            path = prefix + [self._envelopes[h]]
            kids = sorted(children.get(h, []))
            if not kids:
                chains.append(path)
                return
            for k in kids:
                walk(k, path)

        for root in sorted(children.get(None, [])):
            walk(root, [])

        chains.sort(key=lambda c: compute_envelope_hash(c[-1]))
        return chains

    def canonical_bytes(self) -> bytes:
        """
        A byte-identical serialization of the replica's *content*.

        Two replicas converge iff their ``canonical_bytes()`` are equal.
        Built by serializing every envelope (canonical JSON, signature
        included) in content-address order — so it depends only on the
        *set* of envelopes, never on the order they arrived. This is the
        artifact the property tests compare to prove convergence.
        """
        parts = [
            json.dumps(asdict(self._envelopes[h]), sort_keys=True,
                       separators=(",", ":"))
            for h in sorted(self._envelopes)
        ]
        return "\n".join(parts).encode("utf-8")


__all__ = ["CoordinationState"]
