"""The claim ledger — the missing consumer.

WHAT THE GAP ACTUALLY WAS, measured rather than assumed. Two production sites
emit a typed claim (`gyza/memory.py:525` builds a `RetrievalClaim`,
`gyza/network/netd_client.py:165` builds a `SendClaim`). **Nothing reads them.**
`governed_router()` has no runtime caller, `build_registries()` has no
production caller, and the memory claim is stashed on `last_retrieval_claim`
where only tests look at it.

So claims were being written into a void — the exact pattern that got send-claim
emission removed. This module is the reader, and it is deliberately the smallest
thing that can be one.

THE DESIGN DECISION THAT MAKES THIS POSSIBLE, stated because it dissolves a
blocker recorded twice:

    `research/selection_routes/BLOCKED_SR1_SR2_SR4.md` says "assigning a claim
    type to a natural task is itself a tier-3 claim". TRUE FOR TASKS. But a
    claim is not emitted from a task -- it is emitted from an OPERATION, and an
    operation knows its own type by construction. `retrieve_similar` emits
    `memory_retrieval_relevance` because that is what it did, not because
    something classified it.

    So the claim-type blocker binds K-2 (decomposition) and does NOT bind
    emission. Typing happens at the emission site, where the type is a fact
    rather than a judgement.

THREE VERDICTS, NEVER TWO. A verifier that RAISES has not refuted a claim -- it
has failed to evaluate one. Collapsing those is artifact #16's species (an
exception written into a measurement channel), so `verify_all` records
VERIFIED / REFUTED / UNEVALUATED and an UNEVALUATED claim is never counted as
passing.

WHAT WIRING THIS FOUND, recorded because the point of a consumer is that it
finds things no amount of reading the producer would:

  1. `artifact_content_address` VERIFIED ABSENT CONTENT. `blake3.blake3(None)`
     does not raise -- it returns the digest of the EMPTY string -- so the claim
     "this absent content is at af1349b9..." passed, at tier 1, PROOF-carried
     and attested. Guarded in `adapters.py`; pinned with a positive control so
     the guard rejects ABSENCE and not empty content.
  2. `unit_test_execution` REPORTED A BROKEN HARNESS AS A FALSE CLAIM. A blanket
     `except Exception: return False` made a malformed case set indistinguishable
     from a failing test. Narrowed to the per-case call.

Both are the program's recurring species -- an absent thing read as a value --
and both were sitting inside GOVERNED tier-1 verifiers that 785 passing tests
did not reach, because those tests build their own fixtures.

WHAT IS STILL NOT CONSUMED. `verify_all` has no production caller. Emission is
now on the real path (`build_enriched_prompt` -> `retrieve_similar`), but acting
on the verdict -- refusing to sign an envelope whose claim ledger is
inadmissible -- changes when envelopes are produced, and that is a decision
about signed bytes rather than wiring.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from gyza.canon import attempt, failed

VERIFIED = "VERIFIED"
REFUTED = "REFUTED"
UNEVALUATED = "UNEVALUATED"        # the verifier raised, or there is none


@dataclass(frozen=True)
class EmittedClaim:
    """One typed claim, with the arguments its verifier needs to recheck it.

    Carrying `verify_args` is what makes the claim CHECKABLE rather than merely
    recorded. A claim whose evidence is not carried is an assertion.
    """
    claim_type: str
    verify_args: tuple = ()
    verify_kwargs: dict = field(default_factory=dict)
    emitted_at_ns: int = 0
    note: str = ""


@dataclass
class ClaimVerdict:
    claim_type: str
    status: str                    # VERIFIED | REFUTED | UNEVALUATED
    detail: str
    tier: int
    carrier: str
    governed: bool


@dataclass
class LedgerReport:
    """What the ledger concluded. This is the thing a caller acts on."""
    n_claims: int
    verdicts: list[ClaimVerdict]
    chain_tier: int
    chain_reasons: list[str]
    admissible: bool
    counts: dict[str, int]

    @property
    def summary(self) -> str:
        c = self.counts
        return (f"{self.n_claims} claims: {c.get(VERIFIED,0)} verified, "
                f"{c.get(REFUTED,0)} refuted, {c.get(UNEVALUATED,0)} unevaluated "
                f"-> chain tier {self.chain_tier}, "
                f"{'ADMISSIBLE' if self.admissible else 'REFUSED'}")

    # GOVERNANCE COVERAGE IS A SEPARATE AXIS FROM THE VERDICT, and conflating
    # them would be the error this whole layer exists to prevent. A claim can
    # be VERIFIED by a verifier whose SPECIFICATION nobody has attested: the
    # check ran and passed, but what proposition it establishes is not fixed by
    # the registry. That is a weaker thing than an attested pass and must not
    # be reported as the same thing -- nor as a failure.
    @property
    def n_governed(self) -> int:
        return sum(1 for v in self.verdicts if v.governed)

    @property
    def ungoverned_types(self) -> list[str]:
        """Claim types whose spec is not attested, in first-seen order."""
        seen: list[str] = []
        for v in self.verdicts:
            if not v.governed and v.claim_type not in seen:
                seen.append(v.claim_type)
        return seen

    @property
    def fully_governed(self) -> bool:
        return bool(self.verdicts) and not self.ungoverned_types


class ClaimLedger:
    """Collects typed claims and answers what they jointly establish.

    It is the CONSUMER the B5 rule demands: it reads the governed registry, and
    what it does differently is refuse. A ledger containing one REFUTED or
    UNEVALUATED claim is not admissible, and the chain tier it reports is the
    tier algebra's verdict over the carriers it actually saw.
    """

    def __init__(self) -> None:
        self._claims: list[EmittedClaim] = []

    def emit(self, claim_type: str, *verify_args: Any,
             note: str = "", **verify_kwargs: Any) -> EmittedClaim:
        """Record a claim AT THE SITE THAT PERFORMED THE OPERATION."""
        if not claim_type or not isinstance(claim_type, str):
            raise ValueError("a claim must carry its type; an untyped claim "
                             "cannot be routed and must not be recorded")
        c = EmittedClaim(claim_type, verify_args, dict(verify_kwargs),
                         time.time_ns(), note)
        self._claims.append(c)
        return c

    @property
    def claims(self) -> list[EmittedClaim]:
        return list(self._claims)

    def verify_all(self, router, verifiers) -> LedgerReport:
        """Route every claim, recheck it, and report what the set establishes.

        `router` is a TierRouter (governed or legacy); `verifiers` is a
        VerifierRegistry. Both are passed in rather than constructed here so the
        caller's cutover policy governs, and so this module imports no registry.
        """
        verdicts: list[ClaimVerdict] = []
        for c in self._claims:
            routing = router.route(c.claim_type)

            if c.claim_type not in verifiers:
                # No verifier is NOT a passing verdict.
                verdicts.append(ClaimVerdict(
                    c.claim_type, UNEVALUATED,
                    "no registered verifier for this claim type",
                    routing.tier, routing.carrier, routing.governed))
                continue

            fn = verifiers.get(c.claim_type).fn
            # attempt() returns a Failure rather than raising, so "the verifier
            # broke" cannot be read as "the claim is false".
            out = attempt(fn, *c.verify_args, where=c.claim_type,
                          **c.verify_kwargs)
            if failed(out):
                status, detail = UNEVALUATED, f"verifier raised: {out.reason}"
            elif out is True:
                status, detail = VERIFIED, "recomputed and matched"
            elif out is False:
                status, detail = REFUTED, "recomputed and DIVERGED"
            else:
                status, detail = UNEVALUATED, (
                    f"verifier returned {type(out).__name__}, not a bool")

            verdicts.append(ClaimVerdict(c.claim_type, status, detail,
                                         routing.tier, routing.carrier,
                                         routing.governed))

        from gyza.verification.scheduler import consult_tier_algebra
        decision = consult_tier_algebra(
            carriers=[v.carrier for v in verdicts],
            tiers=[v.tier for v in verdicts],
            depth=len(verdicts),
        )
        counts: dict[str, int] = {}
        for v in verdicts:
            counts[v.status] = counts.get(v.status, 0) + 1

        # FAIL CLOSED. One refuted or unevaluated claim sinks the set: a chain
        # is only as good as the weakest link it can actually check.
        admissible = bool(verdicts) and counts.get(VERIFIED, 0) == len(verdicts)

        return LedgerReport(
            n_claims=len(verdicts), verdicts=verdicts,
            chain_tier=decision.tier, chain_reasons=list(decision.reasons),
            admissible=admissible, counts=counts,
        )


__all__ = ["ClaimLedger", "EmittedClaim", "ClaimVerdict", "LedgerReport",
           "VERIFIED", "REFUTED", "UNEVALUATED"]
