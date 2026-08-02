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

from gyza.verification.registry import PartialSpecRegistry, VerifierRegistry


@dataclass(frozen=True)
class Routing:
    claim_type: str
    tier: int
    reason: str
    carrier: str            # PROOF | SPEC | NONE -- what the check rests on


class TierRouter:
    def __init__(self, verifiers: VerifierRegistry, specs: PartialSpecRegistry):
        self._v = verifiers
        self._s = specs

    def route(self, claim_type: str) -> Routing:
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
