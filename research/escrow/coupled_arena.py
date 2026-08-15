"""An arena that expresses M > 3 *and* carries OTHER-CAUSED change.

WHY A SECOND ARENA. `research/arena/arena.py` reaches M=512 but a principal's
total moves for exactly one reason: its own shedding. Under that structure
reservation's round-open budget is never stale, so it scores 0.0000 at every M
by the box theorem -- not by measurement. The first E1 run produced exactly that
and it is recorded as a null in FINDINGS.md rather than as a result.

`FINDINGS_RESERVATION` §3 located the real mechanism in the environment:
`env_federation.principal_total` reads the CURRENT owner map and adds a pro-rata
POOL CLAIM, so a principal's own total falls when OTHERS drain the pool. That is
the staleness reservation introduces -- it fixes self-caused staleness and takes
on other-caused staleness -- and it is the thing that must be measured at scale.

NEITHER COMMITTED ENVIRONMENT IS MODIFIED. `box_bounds`, `KAPPA` and the pool
arithmetic are imported or transcribed from `env_aggregate` / `env_federation`;
`arena.py` is imported for `principals`. This file adds the coupling and nothing
else, so `research/arena/FINDINGS.md` keeps the frame it was measured on.
"""
from __future__ import annotations

import pathlib
import random
import sys
from dataclasses import dataclass, field

HERE = pathlib.Path(__file__).resolve().parent
for _d in ("aggregate", "federation", "arena"):
    sys.path.insert(0, str(HERE.parent / _d))

import env_aggregate as A                                       # noqa: E402
from arena import principals                                    # noqa: E402

KAPPA = A.KAPPA


@dataclass
class Coupled:
    """M principals over (own holding, shared pool).

    `principal_total` mirrors `env_federation.principal_total`: own holding plus
    a pro-rata claim on what REMAINS of the pool. The claim is the coupling --
    it falls when anyone drains, so p's measured total moves without p acting.
    """
    m: int
    holdings: dict[str, float]
    contrib: dict[str, float]
    pool: float
    funded: float
    last_round: dict[str, float] = field(default_factory=dict)

    @classmethod
    def fresh(cls, m: int) -> "Coupled":
        ps = principals(m)
        acct = float(A.E.ACCT_HI + A.E.ACCT_LO)
        contrib = float(A.E.POOL_CONTRIB)
        c = cls(m=m, holdings={p: acct for p in ps},
                contrib={p: contrib for p in ps},
                pool=contrib * m, funded=contrib * m)
        c.last_round = {p: c.principal_total(p) for p in ps}
        return c

    # -- quantities: computed HERE, never by a guard -------------------------
    def pool_claim(self, p: str) -> float:
        if self.funded <= 0 or self.pool <= 0:
            return 0.0
        return self.contrib[p] * (self.pool / self.funded)

    def principal_total(self, p: str) -> float:
        return self.holdings[p] + self.pool_claim(p)

    def concentration(self) -> float:
        t = {p: self.principal_total(p) for p in self.holdings}
        s = sum(t.values())
        return 0.0 if s <= 0 else max(t.values()) / s

    def drain_pool(self, p: str, amount: float) -> None:
        """p withdraws from the pool into its own holding. NET-NEUTRAL for p
        (claim falls, holding rises) and strictly NEGATIVE for everyone else --
        env_federation's P4 mechanism, which is what makes the coupling bite."""
        take = min(amount, self.pool)
        self.pool -= take
        self.holdings[p] += take

    def commit_round(self) -> None:
        self.last_round = {p: self.principal_total(p) for p in self.holdings}


# --------------------------------------------------------------------------- #
#  The two admission disciplines, as FINDINGS_RESERVATION distinguishes them   #
# --------------------------------------------------------------------------- #
def reduce_total(c: Coupled, p: str, amount: float) -> None:
    """Divest `amount` of p's PRINCIPAL TOTAL, withdrawing the pool claim first
    when the account alone cannot cover it.

    APPARATUS DEFECT #6, and the same species as the arena's first: an adversary
    that could not shed what it owned. The earlier version reduced `holdings`
    only, so every shedder was floored at its pool claim (6.0 against an L of
    4.44 at M=4) and the box looked SOUND at every M >= 4 for reasons that were
    entirely an artifact of the instrument.

    A principal in `env_federation` reaches zero the way anyone does: withdraw
    the claim -- NET-NEUTRAL, claim falls and balance rises -- then divest the
    balance. Withdrawing also shrinks the pool, which lowers EVERY OTHER
    principal's claim. That is the P4 coupling, and it is the whole reason this
    arena exists.
    """
    short = amount - c.holdings[p]
    if short > 0:
        c.drain_pool(p, min(short, c.pool_claim(p)))   # claim -> balance
    c.holdings[p] = max(c.holdings[p] - amount, 0.0)


def shed_reserved(c: Coupled, p: str, n_agents: int, low: float) -> None:
    """RESERVATION: ONE budget, fixed at round open from a value read ONCE,
    decremented per admission. Blind to other-caused change during the round."""
    seen = c.last_round[p]                       # origin, pinned at round open
    budget = max(seen - low * (1.0 + 1e-9), 0.0)
    per = budget / n_agents if n_agents else 0.0
    for _ in range(n_agents):
        take = min(per, budget)
        budget -= take
        reduce_total(c, p, take)


def shed_partitioned(c: Coupled, p: str, n_agents: int, low: float) -> None:
    """PARTITIONED_READ: re-reads the principal's CURRENT total on every
    admission, so pool drift is seen immediately. The comparison arm."""
    for _ in range(n_agents):
        now = c.principal_total(p)
        reduce_total(c, p, max(now - low * (1.0 + 1e-9), 0.0) / n_agents)


def shed_naive(c: Coupled, p: str, n_agents: int, low: float) -> None:
    """NO reservation: every agent independently sheds to the floor against the
    same stale read. AG-3's original unsound admission, kept as the baseline."""
    seen = c.last_round[p]
    per = max(seen - low * (1.0 + 1e-9), 0.0)
    for _ in range(n_agents):
        reduce_total(c, p, per)


DISCIPLINES = {"reserved": shed_reserved,
               "partitioned": shed_partitioned,
               "naive": shed_naive}


# --------------------------------------------------------------------------- #
#  THE OTHER SIDE OF THE BOX                                                   #
# --------------------------------------------------------------------------- #
# The box is TWO-SIDED: L <= total <= U. Shedding attacks the floor; DRAINING
# the shared pool attacks the ceiling, and it moves the ratio from both ends at
# once -- the drainer's total rises by take*(1 - 1/m) while every other
# principal's falls by take/m.
#
# The first coupled run gated only shedding, so the drain ran ungated and all
# three disciplines scored IDENTICALLY at every M. A guard that governs one end
# of a two-sided bound is the AG-3 defect restated: watching the wrong end of a
# ratio is expensive and inert.
def drain_reserved(c: Coupled, p: str, n_agents: int, high: float) -> None:
    """ONE ceiling budget, pinned at round open, drawn down per admission."""
    seen = c.last_round[p]
    budget = max(high * (1.0 - 1e-9) - seen, 0.0)
    per = budget / n_agents if n_agents else 0.0
    for _ in range(n_agents):
        take = min(per, budget)
        budget -= take
        c.drain_pool(p, take)


def drain_partitioned(c: Coupled, p: str, n_agents: int, high: float) -> None:
    """Re-reads the current total on every admission."""
    for _ in range(n_agents):
        now = c.principal_total(p)
        c.drain_pool(p, max(high * (1.0 - 1e-9) - now, 0.0) / n_agents)


def drain_naive(c: Coupled, p: str, n_agents: int, high: float) -> None:
    """Every agent claims the FULL headroom it read. Individually admissible,
    jointly an n-fold overshoot of the ceiling."""
    seen = c.last_round[p]
    per = max(high * (1.0 - 1e-9) - seen, 0.0)
    for _ in range(n_agents):
        c.drain_pool(p, per)


DRAINS = {"reserved": drain_reserved,
          "partitioned": drain_partitioned,
          "naive": drain_naive}


def run(m: int, discipline: str, *, n_agents: int, rounds: int, seed: int,
        pool_drainers: int = 1) -> dict:
    """One trajectory. Returns environment-computed measures only."""
    rng = random.Random(seed)
    c = Coupled.fresh(m)
    shed = DISCIPLINES[discipline]
    drain = DRAINS[discipline]
    low, high = A.box_bounds(m, KAPPA)
    viol = below_floor = 0
    peak = 0.0

    # THE TARGET IS FIXED FOR THE WHOLE TRAJECTORY, and this is the fifth
    # apparatus defect of this program, found by instrumenting an exact 0.0000.
    # The first version reshuffled every round, so whoever benefited in round r
    # was shed around in round r+1 -- concentration could not ACCUMULATE, and it
    # measured 0.0000 at every M >= 8 in ALL THREE ARMS, naive included.
    # AG-3's mechanism is accumulation: its RESERVATION trajectory sits at 0.50
    # for five rounds and violates from round 6. A rotating beneficiary is the
    # symmetric-shedding defect in TEMPORAL form -- an adversary that undoes its
    # own work. A concentration attacker is persistent by definition.
    ps = list(c.holdings)
    rng.shuffle(ps)
    target, rest = ps[0], ps[1:]

    for _ in range(rounds):
        # OTHER-CAUSED CHANGE FIRST, mid-round: the drain lands after budgets
        # are pinned, which is exactly the window reservation cannot see.
        # It is now ADMITTED under the same discipline, against the ceiling.
        for d in ([target] + rest)[:pool_drainers]:
            drain(c, d, n_agents, high)
        for p in rest:
            shed(c, p, n_agents, low)
        c.commit_round()
        conc = c.concentration()
        peak = max(peak, conc)
        if conc > KAPPA + 1e-9:
            viol += 1
        # did any principal end the round OUTSIDE its own box floor? that is the
        # local-check failure, distinct from the aggregate violation
        if any(c.principal_total(p) < low * (1 - 1e-9) for p in c.holdings):
            below_floor += 1
    return {"violations": viol, "rounds": rounds, "below_floor": below_floor,
            "peak_concentration": peak}


__all__ = ["Coupled", "run", "DISCIPLINES", "KAPPA"]
