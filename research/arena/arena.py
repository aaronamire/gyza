"""An arena that actually expresses M > 3.

WHY THIS EXISTS. `env_federation.principals(m)` returns `("A","B","C")[:m]`, and
Python slicing past the end returns the whole tuple — so every request for M=100
silently yielded 3. That is the Gate 0 stop recorded in FINDINGS_BOX_SCALING,
and it is why every planetary claim in this program is analytic.

THE COMMITTED ENVIRONMENTS ARE NOT TOUCHED. `box_bounds` and `KAPPA` are
IMPORTED from `env_aggregate`, so the property under test is byte-identical to
the one already published. If this file reimplemented the box, the arena would
be grading its own arithmetic.

WHAT IS SIMULATED AND WHAT IS NOT. Principals hold a scalar holding and act
concurrently in rounds. There are no agents, no work, no humans — `h` is a
parameter. The property under test is STRUCTURAL (does a stated predicate hold
under concurrent admission against stale reads) rather than behavioural, which
is what makes a synthetic arena admissible here at all (FINDINGS_BOX_SCALING
§11).
"""
from __future__ import annotations

import pathlib
import random
import sys
from dataclasses import dataclass

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "aggregate"))
sys.path.insert(0, str(HERE.parent / "federation"))

import env_aggregate as A                                       # noqa: E402

KAPPA = A.KAPPA


def principals(m: int) -> tuple[str, ...]:
    """m DISTINCT principals, for any m.

    The one-line fix the Gate 0 stop was waiting on. `env_federation`'s version
    slices a fixed 3-tuple; this generates. A test asserts len == m for large m,
    because the failure it replaces was silent.
    """
    if m < 2:
        raise ValueError(f"a federation needs at least 2 principals, got {m}")
    return tuple(f"P{i:05d}" for i in range(m))


@dataclass
class Arena:
    """Concurrent principals over a scalar holding.

    `holdings` is the per-principal state a local box check reads exactly.
    `last_round` is what each principal can see of the OTHERS — stale by one
    round, which is the condition AG-3 found sufficient to make admission
    unsound.
    """
    m: int
    endowment: float
    holdings: dict[str, float]
    last_round: dict[str, float]

    @classmethod
    def fresh(cls, m: int) -> "Arena":
        U = float(A.E.ACCT_HI + A.E.ACCT_LO + A.E.POOL_CONTRIB)
        ps = principals(m)
        h = {p: U for p in ps}
        return cls(m=m, endowment=U, holdings=dict(h), last_round=dict(h))

    # -- the quantity, computed by the environment ---------------------------
    def concentration(self) -> float:
        tot = sum(self.holdings.values())
        return 0.0 if tot <= 0 else max(self.holdings.values()) / tot

    def commit_round(self) -> None:
        """Publish this round's state as what others will read next round."""
        self.last_round = dict(self.holdings)


def local_box_admits(arena: Arena, p: str, new_holding: float,
                     assumed_m: int | None = None) -> bool:
    """The LOCAL check: may `p` move to `new_holding`?

    Reads ONLY `p`'s own proposed value against the box floor. It does not read
    any other principal's state — that locality is the whole point, and it is
    also why a stale global picture cannot help it.
    """
    low, high = A.box_bounds(assumed_m or arena.m, KAPPA)
    return low <= new_holding <= high


def run_round(arena: Arena, rng: random.Random, *, shed_fraction: float,
              colluding: int, agents_per_principal: int = 1) -> None:
    """One concurrent round — AG-3's MECHANISM, not a weaker one.

    THE DEFECT THIS REPLACES, recorded because it produced an exact 0.0000 at
    every M and I nearly reported it. The first version gave each principal ONE
    actor checking its OWN EXACT state. The box is SOUND by construction in that
    setting -- that is precisely what FINDINGS_BOX_SCALING's 33,000 in-box
    configurations already established -- so no violation was reachable and the
    arena could not reproduce the mechanism it was built to measure.

    AG-3's unsoundness needs `agents_per_principal > 1` racing against a STALE
    read of their own principal's aggregate: each agent's withdrawal is
    individually admissible against the value it read, and their SUM is not.
    Nobody exceeds a bound they can see; the principal still leaves the box.
    """
    # CONCENTRATION IS A RATIO, so symmetric shedding moves it NOT AT ALL --
    # my second failed adversary. max/sum rises when the OTHERS shed, so one
    # principal is held out as the target and the rest shed around it.
    ps = list(arena.holdings)
    rng.shuffle(ps)
    target, rest = ps[0], ps[1:]
    for p in rest[:colluding]:
        # every agent decides against the SAME stale snapshot
        seen = arena.last_round[p]
        # THE OPTIMAL INDIVIDUALLY-ADMISSIBLE WITHDRAWAL. Each agent proposes
        # taking its principal to exactly the box floor, judged against the
        # stale value it read. That is admissible for EVERY agent separately --
        # none can see the others -- and `shed_fraction` scales how hard it
        # pushes, so a weaker adversary remains expressible.
        low, _high = A.box_bounds(arena.m, KAPPA)
        # A MARGIN, because shedding to EXACTLY the floor lands an epsilon
        # below it under float arithmetic and the check refuses -- which
        # produced an isolated 0.000 at M=32 that I first misdiagnosed as a
        # seed effect. A real adversary would not stand on the boundary.
        per_agent = max(seen - low * (1.0 + 1e-9), 0.0) * shed_fraction
        admitted = 0.0
        for _ in range(agents_per_principal):
            if local_box_admits(arena, p, seen - per_agent):
                admitted += per_agent      # individually admissible, jointly not
        arena.holdings[p] = max(arena.holdings[p] - admitted, 0.0)
    arena.commit_round()


__all__ = ["Arena", "principals", "local_box_admits", "run_round", "KAPPA"]
