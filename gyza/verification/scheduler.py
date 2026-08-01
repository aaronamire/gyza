"""
The tier-algebra consultation point (K-6's dependency).

K-6 is not built. This is the CONSULTATION POINT it will call, implemented and
tested now so that the scheduler cannot later be written without it -- the
acceptance criterion is that the algebra is consulted BEFORE a deep chain is
permitted, and a rule nobody calls is a rule that is not enforced.

Rules are transcribed from research/TIER_ALGEBRA.md, which SR-3 derived:

  1. any TEST-carried stage      -> tier 3. No side condition rescues it: a
                                    finite sample cannot bound behaviour outside
                                    itself (measured 0.000 detection, n=4).
  2. any tier-3 stage            -> tier 3.
  3. otherwise                   -> min(input tiers); verified fold preserves it.
  4. any CUMULATIVE property     -> must be evaluated at the promotion gate (C7),
                                    regardless of the tier this returns.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gyza.containment.invariants import InvariantClass


@dataclass
class ChainDecision:
    tier: int
    reasons: list[str] = field(default_factory=list)
    requires_promotion_gate: bool = False
    depth_permitted: bool = True


# C14: unverified steps decay as (1-p)^n; at the measured tier depth beyond ~10
# is worthless. Verified claims do not decay.
TIER_DEPTH_CAP = {1: None, 2: 32, 3: 10}


def consult_tier_algebra(carriers: list[str], tiers: list[int],
                         classes: list[InvariantClass] | None = None,
                         depth: int | None = None) -> ChainDecision:
    d = ChainDecision(tier=min(tiers) if tiers else 3)

    if any(c == "TEST" for c in carriers):
        d.tier = 3
        d.reasons.append(
            "a TEST-carried stage is present: a finite sample cannot bound "
            "behaviour outside itself (SR-3 measured 0.000 detection under "
            "every operator). No side condition rescues it.")
    elif any(t == 3 for t in tiers):
        d.tier = 3
        d.reasons.append("a tier-3 stage is present; the chain inherits it")
    else:
        d.reasons.append(
            f"all stages PROOF/SPEC-carried; combined tier = min(input tiers) "
            f"= {d.tier}, preserved under verified fold")

    if classes and any(c is InvariantClass.CUMULATIVE for c in classes):
        d.requires_promotion_gate = True
        d.reasons.append(
            "a CUMULATIVE property is present: no stateless local check bounds "
            "a cumulative quantity (C7), so it must be evaluated at the "
            "serialized promotion gate regardless of tier")

    cap = TIER_DEPTH_CAP.get(d.tier)
    if depth is not None and cap is not None and depth > cap:
        d.depth_permitted = False
        d.reasons.append(
            f"depth {depth} exceeds the tier-{d.tier} cap of {cap} (C14)")
    return d
