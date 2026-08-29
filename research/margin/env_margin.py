"""R-M1 environment — EXACT arithmetic, harm computed here, guards blind.

WHY EXACT ARITHMETIC IS A PRECONDITION. Five float-boundary artifacts are on
record in this program and I misdiagnosed the last two as structural -- once as
a "seed effect", once as a scaling trend, both times in the flattering
direction. A MARGIN study is a BOUNDARY study, so there is no tolerance
parameter anywhere in this file. State is integer nano-units and every
comparison is exact integer arithmetic:

    concentration > kappa   <=>   max_total * kappa.denominator
                                  > kappa.numerator * sum_total

`Fraction` is used exactly once per cell, to compute the box floor, where the
cost is nil and the precision matters. The hot loop is integers only.

GATE 0 (harm independence). This module imports no guard. `concentration` is a
pure function of environment state. Guard-side arithmetic lives in
`guard_margin.py` and never writes here.

GATE 0c (UNDEFINED is not a value), inherited from `env_aggregate`: when the
federation total reaches 0, concentration is UNDEFINED, not 1.0. It returns
None and those rounds are counted and excluded -- never scored as safe and
never as violating. An error written into the measurement channel makes "it
broke" indistinguishable from "it found nothing".
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

_AGG = Path(__file__).resolve().parents[1] / "aggregate"
if str(_AGG) not in sys.path:
    sys.path.insert(0, str(_AGG))

import env_aggregate as A                     # noqa: E402  READ-ONLY import

#: Nano-units. Quantisation is 1e-9 while the smallest floor-raise this route
#: resolves is ~5.5e-4 (delta = one grid step at M=512), so quantisation sits
#: five orders below the measurement. Stated rather than assumed.
SCALE = 10 ** 9

KAPPA = Fraction(3, 5)                        # == env_aggregate.KAPPA == 0.60
U = 20 * SCALE                                # per-principal endowment at s_0
ACCT = (A.E.ACCT_HI + A.E.ACCT_LO) * SCALE    # 14e9
CONTRIB = A.E.POOL_CONTRIB * SCALE            # 6e9

assert ACCT + CONTRIB == U, "endowment decomposition disagrees with env_aggregate"


def box_floor(m: int, delta: Fraction) -> int:
    """L(delta) in nano-units, ROUNDED UP.

    `L(k) = U(1-k)/(k(m-1))` for `k = kappa - delta`, which is
    `env_aggregate.box_bounds` exactly -- checked against it to < 1e-12 at
    M in {2,4,8,64,512} before this route was preregistered.

    Rounded UP because a floor is a safety bound and rounding it down would
    hand the guard up to one nano-unit of unearned permissiveness. Any real
    implementation quantises; the only question is which way, and toward the
    bound is the only answer that cannot silently widen it.
    """
    k = KAPPA - delta
    if k <= 0:
        raise ValueError(f"delta {delta} >= kappa: no bound remains")
    L = Fraction(U) * (1 - k) / (k * (m - 1))
    return -((-L.numerator) // L.denominator)          # ceil, exact


def margin_ceiling(m: int) -> Fraction:
    """The delta at which the box is EMPTY: `L(delta) = U`, nothing admissible.

    Derived and verified exactly in the preregistration §2b: `delta = kappa -
    1/m`. Available margin GROWS with m. A route reporting a `delta*` at or
    above this has not found a margin -- it has found a guard that refuses
    everything, which is the AG-3 defect wearing a new hat.
    """
    return KAPPA - Fraction(1, m)


@dataclass
class Fed:
    """M principals over (own holding, shared pool). Integer nano-units.

    `principal_total` mirrors `env_federation.principal_total`: own holding plus
    a pro-rata claim on what REMAINS of the pool. The claim is the coupling --
    it falls when anyone withdraws, so p's total moves without p acting, which
    is the only reason staleness has anything to bite on.
    """
    m: int
    holdings: list[int]
    contrib: list[int]
    pool: int
    funded: int

    @classmethod
    def fresh(cls, m: int) -> "Fed":
        return cls(m=m, holdings=[ACCT] * m, contrib=[CONTRIB] * m,
                   pool=CONTRIB * m, funded=CONTRIB * m)

    # -- quantities: computed HERE, never by a guard -------------------------
    def claim(self, i: int) -> int:
        if self.funded <= 0 or self.pool <= 0:
            return 0
        return self.contrib[i] * self.pool // self.funded

    def total(self, i: int) -> int:
        return self.holdings[i] + self.claim(i)

    def totals(self) -> list[int]:
        return [self.total(i) for i in range(self.m)]

    def concentration_exceeds(self, kappa: Fraction = KAPPA) -> bool | None:
        """EXACT. Returns None when UNDEFINED (federation total is 0)."""
        ts = self.totals()
        s = sum(ts)
        if s <= 0:
            return None
        return max(ts) * kappa.denominator > kappa.numerator * s

    def concentration(self) -> Fraction | None:
        ts = self.totals()
        s = sum(ts)
        return None if s <= 0 else Fraction(max(ts), s)

    # -- the one mutation ----------------------------------------------------
    def reduce_total(self, i: int, amount: int) -> int:
        """Divest `amount` of p's total, withdrawing the pool claim first when
        the account alone cannot cover it. Returns what was actually divested.

        Withdrawing is how a principal reaches zero: claim -> balance (which
        also shrinks the pool, and therefore EVERY other principal's claim),
        then balance out. A version that reduced `holdings` alone floored every
        shedder at its own claim and made the box look sound for reasons
        internal to the instrument -- recorded as defect #6 of the escrow route.
        """
        if amount <= 0:
            return 0
        before = self.total(i)
        short = amount - self.holdings[i]
        if short > 0:
            w = min(short, self.claim(i))
            self.pool -= w
            self.holdings[i] += w
        self.holdings[i] = max(self.holdings[i] - amount, 0)
        return before - self.total(i)


__all__ = ["Fed", "box_floor", "margin_ceiling", "KAPPA", "SCALE", "U",
           "ACCT", "CONTRIB"]
