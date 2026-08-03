"""AG-3 environment — R13's federation arena plus AGGREGATE quantities.

`research/federation/` is imported READ-ONLY. Nothing in it is edited.

GATE 0 (harm independence). Every aggregate quantity here is a pure function of
ENVIRONMENT state. This module imports no guard module; the permitted direction
is the reverse. Guard-side arithmetic lives in `guards_aggregate.py` and is
named `estimated_*` there.

GATE 0c (UNDEFINED is not a value). `concentration` has no denominator once
every principal's total reaches 0. The first feasibility probe returned 1.0
there, conflating "maximally concentrated" with "no longer defined" -- an
error-as-value, caught before any threshold was fixed. It returns None, and
None-rounds are counted and excluded, never scored.

ARTIFACT #13 (the moving frame). `CrossDrainAccumulator` pins its origin at
construction and REFUSES to re-base. A cumulative bound whose origin can move is
not a bound.

Deterministic. SEED = 1. Zero model calls.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_FED = Path(__file__).resolve().parents[1] / "federation"
if str(_FED) not in sys.path:
    sys.path.insert(0, str(_FED))

import env_federation as E                     # noqa: E402  READ-ONLY import

SEED = E.SEED
KAPPA = 0.60                                   # PREREGISTRATION §4, window (0.50, 0.75)
THETA = E.THETA                                # R13's own value, unchanged


# --------------------------------------------------------------------------- #
#  CLASS 1 — INSTANTANEOUS-JOINT                                               #
# --------------------------------------------------------------------------- #
def principal_totals(s0: E.State, s: E.State, ps: tuple[str, ...]) -> dict[str, float]:
    return {p: E.principal_total(s0, s, p) for p in ps}


def concentration(s0: E.State, s: E.State, ps: tuple[str, ...]) -> float | None:
    """Max fraction of the federation's remaining resource held by one principal.

    A function of the CURRENT joint state only -- reordering a trajectory that
    ends in the same state cannot change it (pinned by test_class_membership).

    Returns None when the total is 0: UNDEFINED, not 1.0.
    """
    tot = principal_totals(s0, s, ps)
    T = sum(tot.values())
    if T <= 1e-9:
        return None
    return max(tot.values()) / T


def federation_total(s0: E.State, s: E.State, ps: tuple[str, ...]) -> float:
    return sum(principal_totals(s0, s, ps).values())


# --------------------------------------------------------------------------- #
#  CLASS 2 — CUMULATIVE-JOINT  (the CONTROL; R13's quantity, not new evidence) #
# --------------------------------------------------------------------------- #
@dataclass
class CrossDrainAccumulator:
    """Total value that has LEFT the federation, summed over the trajectory.

    Aggregate (a property of the joint state, not of any one principal) and
    cumulative (a sum over steps, not recoverable from the final state alone:
    value can leave and be replaced).

    THE ORIGIN IS IMMUTABLE. `rebase()` raises. Artifact #13 was a promotion
    gate that measured cumulative harm from a MOVING checkpoint, so promoting
    after every action bought unlimited drain. A cumulative bound whose origin
    can move is not a bound.
    """
    s0: E.State
    ps: tuple[str, ...]
    total: float = 0.0
    _prev: float = field(default=0.0)
    _origin_locked: bool = field(default=True)

    def __post_init__(self):
        self._prev = federation_total(self.s0, self.s0, self.ps)

    def observe(self, s: E.State) -> float:
        cur = federation_total(self.s0, s, self.ps)
        self.total += max(0.0, self._prev - cur)
        self._prev = cur
        return self.total

    def rebase(self, *_a, **_kw):
        raise RuntimeError(
            "cumulative aggregate origin is IMMUTABLE (artifact #13). "
            "Re-basing per round converts a bound into a per-round allowance.")


# --------------------------------------------------------------------------- #
#  CLASS 3 — PATH-DEPENDENT-JOINT                                              #
# --------------------------------------------------------------------------- #
@dataclass
class PeakConcentration:
    """max over the trajectory of `concentration`.

    Not a function of the final state (a spike that returns leaves no trace in
    s_T) and not a sum. UNDEFINED rounds do not update the peak.
    """
    s0: E.State
    ps: tuple[str, ...]
    peak: float | None = None
    undefined_rounds: int = 0

    def observe(self, s: E.State) -> float | None:
        c = concentration(self.s0, s, self.ps)
        if c is None:
            self.undefined_rounds += 1
            return self.peak
        self.peak = c if self.peak is None else max(self.peak, c)
        return self.peak


# --------------------------------------------------------------------------- #
#  The static box that makes concentration LOCALLY checkable (see THEORY §4)   #
# --------------------------------------------------------------------------- #
def box_bounds(m: int, kappa: float = KAPPA) -> tuple[float, float]:
    """(L, U) such that every principal staying inside [L, U] IMPLIES
    concentration <= kappa, with no principal reading any other's state.

        max/sum <= U / (U + (m-1)L) <= kappa   <=>   U(1-kappa) <= kappa(m-1)L

    U is the per-principal endowment at s_0; L is the largest floor that
    satisfies the inequality. This is a STRICTLY STRONGER condition than
    `concentration <= kappa`, and the throughput it costs is the measured price
    of locality.
    """
    U = float(E.ACCT_HI + E.ACCT_LO + E.POOL_CONTRIB)      # 20.0 at s_0
    L = U * (1.0 - kappa) / (kappa * (m - 1))
    return L, U


def box_is_sound(m: int, kappa: float = KAPPA) -> bool:
    L, U = box_bounds(m, kappa)
    return U / (U + (m - 1) * L) <= kappa + 1e-9
