"""
Byzantine resilience — detect, attribute, and route around a compromised
member of a decentralized collective.

WHERE THIS SITS
---------------
Gyza's cryptographic substrate makes a whole class of attacks
*impossible* rather than merely detectable: a compromised agent cannot
forge another agent's signature (Ed25519), cannot alter sealed history
without breaking every downstream parent link (tamper-evidence), and
cannot produce a valid signed envelope for out-of-bounds work
(refuse-to-sign; ``enforcement_satisfies_manifest``). Those need no
runtime detector — they cannot happen.

What a compromised agent *can* still do, with perfectly valid
signatures, is **equivocate**: sign two contradicting actions for the
same logical step — telling one side of a partition one thing and the
other side another. This is exactly the "colluding compromised agents
and deceptive messages" failure a decentralized collective must survive
without a central referee. Because every action is signed, an
equivocation is not just detectable but *undeniable evidence against its
author*: only the holder of that agent's key could have produced two
distinct signed envelopes for one ``(intent_id, action_id)``.

This module provides the measurement-level detector (find the
equivocation) and the policy-level response (quarantine the author and
recompute the honest sub-history), plus a resilience metric over the
outcome.

SOUNDNESS — WHY AN HONEST PARTITION FORK IS NOT FLAGGED
-------------------------------------------------------
An available data plane legitimately *forks* under partition: both
sides extend the last shared envelope concurrently. That is honest —
and it is authored by *different* agents on *different* action_ids. An
equivocation is the opposite: the *same* agent producing two distinct
envelopes for the *same* ``(intent_id, action_id)``. Keying detection
on ``(agent_pubkey, intent_id, action_id)`` separates the two by
construction: honest concurrency never collides on that key, a
self-contradiction always does.

WHAT THIS DOES NOT DO
---------------------
It cannot judge whether an agent's output is *semantically* wrong — a
compromised agent that stays within its bounds and never contradicts
itself produces well-formed, attributable, but possibly-wrong work.
Catching that is a human-on-the-loop or downstream-eval decision, the
same honest limit the rest of Gyza draws. What this proves is narrower
and real: provable self-contradiction is attributed to its author and
excluded, and the honest remainder still forms a valid provenance DAG.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from gyza.icp import (
    DagVerification,
    ICPEnvelope,
    compute_envelope_hash,
    verify_dag,
)


@dataclass(frozen=True)
class Equivocation:
    """
    Evidence that ``agent_pubkey`` signed more than one distinct envelope
    for a single logical action. Undeniable: the conflicting envelopes
    all verify under the agent's own key.
    """

    agent_pubkey: str
    intent_id: str
    action_id: str
    conflicting_output_hashes: tuple[str, ...]
    envelope_hashes: tuple[str, ...]


def detect_equivocation(envelopes: Iterable[ICPEnvelope]) -> list[Equivocation]:
    """
    Find every provable equivocation in ``envelopes``.

    An honest agent produces exactly one envelope per
    ``(intent_id, action_id)``. Any ``(agent_pubkey, intent_id,
    action_id)`` that maps to two or more *distinct* envelope content
    hashes is a signed self-contradiction — the agent said two different
    things for one action. Returned deterministically (sorted by author
    then action) so two replicas holding the same set report identically.
    """
    # (pubkey, intent, action) -> {envelope_hash: output_hash}
    groups: dict[tuple[str, str, str], dict[str, str]] = {}
    for env in envelopes:
        key = (env.agent_pubkey, env.intent_id, env.action_id)
        eh = compute_envelope_hash(env)
        groups.setdefault(key, {})[eh] = env.output_hash

    out: list[Equivocation] = []
    for (pubkey, intent_id, action_id), seen in groups.items():
        if len(seen) < 2:
            continue  # one envelope for this action — honest
        out.append(
            Equivocation(
                agent_pubkey=pubkey,
                intent_id=intent_id,
                action_id=action_id,
                conflicting_output_hashes=tuple(sorted(set(seen.values()))),
                envelope_hashes=tuple(sorted(seen)),
            )
        )
    out.sort(key=lambda e: (e.agent_pubkey, e.intent_id, e.action_id))
    return out


@dataclass
class QuarantineView:
    """The history split into the part authored by trusted vs. quarantined agents."""

    quarantined_agents: frozenset[str]
    honest_envelopes: list[ICPEnvelope]
    quarantined_envelopes: list[ICPEnvelope]


def quarantine_view(
    envelopes: Iterable[ICPEnvelope],
    quarantined_agents: Iterable[str],
) -> QuarantineView:
    """
    Partition ``envelopes`` by author into honest vs. quarantined.

    Nothing is deleted — the quarantined envelopes are retained so *why*
    an agent was excluded stays auditable. The honest set is what the
    collective routes traffic and trust through after the exclusion.
    """
    q = frozenset(quarantined_agents)
    honest: list[ICPEnvelope] = []
    bad: list[ICPEnvelope] = []
    for env in envelopes:
        (bad if env.agent_pubkey in q else honest).append(env)
    return QuarantineView(q, honest, bad)


@dataclass
class ResilienceReport:
    """Outcome of assessing a collective's history for compromise + recovery."""

    total_envelopes: int
    total_agents: int
    equivocations: list[Equivocation]
    quarantined_agents: frozenset[str]
    honest_envelopes: int
    honest_dag: DagVerification

    @property
    def mission_intact(self) -> bool:
        """True iff, after excluding quarantined agents, the honest remainder
        is non-empty and still forms a valid provenance DAG — i.e. the
        collective routed around the compromise and kept a coherent history."""
        return self.honest_envelopes > 0 and self.honest_dag.valid

    @property
    def honest_fraction(self) -> float:
        """Share of actions preserved after excluding compromised authors."""
        if self.total_envelopes == 0:
            return 1.0
        return self.honest_envelopes / self.total_envelopes

    def summary(self) -> str:
        n_eq = len(self.equivocations)
        return (
            f"{self.total_envelopes} envelopes / {self.total_agents} agents; "
            f"{n_eq} equivocation(s) detected; "
            f"{len(self.quarantined_agents)} agent(s) quarantined; "
            f"honest remainder {self.honest_envelopes} "
            f"({self.honest_fraction:.0%}) — DAG "
            f"{'VALID' if self.honest_dag.valid else 'INVALID'}; "
            f"mission {'INTACT' if self.mission_intact else 'BROKEN'}"
        )


def assess_resilience(
    envelopes: Iterable[ICPEnvelope],
    *,
    extra_quarantine: Iterable[str] = (),
) -> ResilienceReport:
    """
    Detect equivocation, quarantine the offending authors (plus any
    ``extra_quarantine`` supplied from other evidence, e.g. failed
    attestation), and recompute the honest remainder's provenance DAG.

    The honest sub-DAG is verified with ``require_closed=False``: an
    honest envelope whose parent was authored by a now-quarantined agent
    becomes a root rather than an error — the collective drops the
    compromised contribution without invalidating work that merely
    referenced it.
    """
    envs = list(envelopes)
    equivocations = detect_equivocation(envs)
    quarantined = frozenset(e.agent_pubkey for e in equivocations) | frozenset(
        extra_quarantine
    )
    view = quarantine_view(envs, quarantined)
    honest_dag = verify_dag(view.honest_envelopes, require_closed=False)
    agents = {e.agent_pubkey for e in envs}
    return ResilienceReport(
        total_envelopes=len(envs),
        total_agents=len(agents),
        equivocations=equivocations,
        quarantined_agents=quarantined,
        honest_envelopes=len(view.honest_envelopes),
        honest_dag=honest_dag,
    )


__all__ = [
    "Equivocation",
    "detect_equivocation",
    "QuarantineView",
    "quarantine_view",
    "ResilienceReport",
    "assess_resilience",
]
