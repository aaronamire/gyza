"""
V-2 tier router.

A TYPE CHECK and nothing else: does this claim type have a registered verifier
(tier 1), a registered partial spec (tier 2), or neither (tier 3)?

ZERO MODEL CALLS, and that is a hard property rather than an optimization.
R11 measured difficulty-based routing failing even with a LITERAL ORACLE: an
AUROC of 1.000 bought economy 0.320, the same as an AUROC of 0.907, against a
0.40 bar. Economy was not a function of predictor accuracy, so "get a better
router" was never the fix. The replacement has to be structural, statically
decidable, and non-gameable -- an agent cannot argue its way into a higher tier
because nothing is being asked, only looked up.

This module imports nothing that can reach a network or a model. That is
asserted by test, with a negative control proving the test can detect a
violation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from gyza.verification.registry import PartialSpecRegistry, VerifierRegistry

if TYPE_CHECKING:                       # avoids a cycle: authority imports canon
    from gyza.verification.authority import SpecAuthority


class CutoverPolicy(str, Enum):
    """What to do with a claim type that is not yet in the GOVERNED registry.

    THERE IS NO DEFAULT, and that is deliberate. A policy nobody chose is how
    ungoverned entries accumulated in the first place; `TierRouter` raises if an
    authority is supplied without one.

      FAIL_CLOSED  an unattested claim type routes to tier 3 -- treated as
                   having no verifier. The verified tier shrinks to exactly
                   what has been attested, which is the honest size of it.
      DUAL_READ    fall back to the ungoverned registry. Preserves behaviour
                   and defers the forcing function. Every fallback is MARKED in
                   the routing reason and counted by `coverage()`, because a
                   fallback nobody can count is a fallback that never expires.
    """
    FAIL_CLOSED = "FAIL_CLOSED"
    DUAL_READ = "DUAL_READ"


@dataclass(frozen=True)
class Routing:
    claim_type: str
    tier: int
    reason: str
    carrier: str            # PROOF | SPEC | TEST | NONE -- what the check rests on
    governed: bool = False  # did this come from the ATTESTED registry?


class TierRouter:
    """Routes a claim type to a verification tier.

    Reads the GOVERNED registry when one is supplied, and the legacy
    ungoverned registries otherwise. One router class rather than two, because
    two routers over two registries is the same defect this migration exists to
    remove -- they would be free to disagree.
    """

    def __init__(self, verifiers: VerifierRegistry, specs: PartialSpecRegistry,
                 *, authority: "SpecAuthority | None" = None,
                 policy: CutoverPolicy | None = None):
        if authority is not None and policy is None:
            raise ValueError(
                "an authority was supplied with no CutoverPolicy. The choice "
                "between FAIL_CLOSED and DUAL_READ is a policy decision and "
                "must be made at the call site, not defaulted here.")
        self._v = verifiers
        self._s = specs
        self._a = authority
        self._policy = policy

    def route(self, claim_type: str) -> Routing:
        if self._a is not None:
            if claim_type in self._a:
                rec = self._a.get(claim_type)
                tier = 2 if rec.carrier == "SPEC" else 1
                return Routing(
                    claim_type, tier,
                    f"GOVERNED: attested by {rec.attestation.author!r} "
                    f"({rec.attestation.method}), carrier {rec.carrier}, "
                    f"v{rec.version}",
                    rec.carrier, governed=True)
            if self._policy is CutoverPolicy.FAIL_CLOSED:
                return Routing(
                    claim_type, 3,
                    "FAIL_CLOSED: no attested spec in the governed registry; "
                    "an unattested verifier is treated as absent",
                    "NONE")
            legacy = self._route_legacy(claim_type)
            return Routing(
                claim_type, legacy.tier,
                f"UNGOVERNED FALLBACK (DUAL_READ): {legacy.reason}",
                legacy.carrier)
        return self._route_legacy(claim_type)

    def _route_legacy(self, claim_type: str) -> Routing:
        if claim_type in self._v:
            v = self._v.get(claim_type)
            return Routing(claim_type, 1,
                           f"native verifier registered ({v.witness})",
                           v.carrier)
        if claim_type in self._s:
            return Routing(claim_type, 2, "human-authored partial spec registered",
                           "SPEC")
        return Routing(claim_type, 3,
                       "no verifier and no partial spec; containment only",
                       "NONE")

    def governance(self, claim_types: list[str]) -> dict:
        """How much of the routed surface is ATTESTED, and how much is debt.

        THE COUNTER-METRIC TO `coverage()`. Tier coverage says how much is
        verifiable; this says how much of that rests on an attested spec versus
        an ungoverned fallback. Under DUAL_READ the fallback count is the
        migration debt, and reporting it is what stops the fallback becoming
        permanent by going unnoticed.
        """
        rows = [self.route(c) for c in claim_types]
        n = len(rows) or 1
        gov = [r for r in rows if r.governed]
        fell_back = [r for r in rows
                     if not r.governed and r.reason.startswith("UNGOVERNED")]
        closed = [r for r in rows if r.reason.startswith("FAIL_CLOSED")]
        return {
            "n": len(rows),
            "policy": self._policy.value if self._policy else "LEGACY_ONLY",
            "governed": len(gov),
            "fraction_governed": round(len(gov) / n, 4),
            "ungoverned_fallback": len(fell_back),
            "fallback_claim_types": sorted(r.claim_type for r in fell_back),
            "failed_closed": len(closed),
            "failed_closed_claim_types": sorted(r.claim_type for r in closed),
        }

    def coverage(self, claim_types: list[str]) -> dict:
        rows = [self.route(c) for c in claim_types]
        n = len(rows) or 1
        return {
            "n": len(rows),
            "tier_1": sum(1 for r in rows if r.tier == 1),
            "tier_2": sum(1 for r in rows if r.tier == 2),
            "tier_3": sum(1 for r in rows if r.tier == 3),
            "fraction_tier_1": round(sum(1 for r in rows if r.tier == 1) / n, 4),
            "fraction_tier_2": round(sum(1 for r in rows if r.tier == 2) / n, 4),
            "fraction_tier_3": round(sum(1 for r in rows if r.tier == 3) / n, 4),
        }
