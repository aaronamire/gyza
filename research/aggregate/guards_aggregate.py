"""AG-3 guards — three read-set disciplines for an aggregate invariant.

Guard-side arithmetic is named `estimated_*`. The environment computes harm;
guards estimate it. Nothing here is imported by `env_aggregate.py`.

THE THREE DISCIPLINES (PREREGISTRATION §5, B4):

  LOCAL            reads ONLY its own principal's state, and compares its own
                   share against a denominator taken from s_0. It cannot see
                   other principals shrinking, which is exactly the movement
                   that raises its share.

  GLOBAL_READ      reads ALL principals' balances from the state it is handed.
                   Under SERIALIZED that state is current; under CONCURRENT it
                   is the shared pre-round snapshot, so the read is CONSISTENT
                   BUT STALE. That distinction is the crux of P3.

  PARTITIONED_READ reads only its own principal's state and a bound PUBLISHED
                   by the others (committed at the previous round boundary,
                   never a live read). It enforces the static box of
                   `env_aggregate.box_bounds`, which is sound without any
                   cross-principal read at all -- and pays for it in throughput.
"""
from __future__ import annotations

import env_aggregate as A
import env_federation as E


class AggGuard:
    name = "base"
    reads_others_live = False

    def __init__(self, p: str, ps: tuple[str, ...], kappa: float = A.KAPPA):
        self.p = p
        self.ps = ps
        self.kappa = kappa
        self.s0: E.State | None = None
        self.published: dict[str, float] = {}

    def reset(self, s0: E.State) -> None:
        self.s0 = s0
        self.published = {q: E.principal_total(s0, s0, q) for q in self.ps}

    def publish(self, s: E.State) -> None:
        """Round-boundary commit. NOT a live read -- it is what other principals
        have already agreed to, available to everyone at the same instant."""
        self.published = {q: E.principal_total(self.s0, s, q) for q in self.ps}

    def admits(self, s: E.State, a: E.Action) -> bool:
        raise NotImplementedError


class F0Agg(AggGuard):
    """No aggregate check. The throughput reference."""
    name = "F0"

    def admits(self, s, a):
        return True


class LocalAgg(AggGuard):
    """Own state only, denominator frozen at s_0."""
    name = "LOCAL"

    def admits(self, s, a):
        if a.principal != self.p:
            return True
        nxt = E.apply(s, a) if E.physically_valid(s, a) else s
        mine = E.principal_total(self.s0, nxt, self.p)
        denom = sum(E.principal_total(self.s0, self.s0, q) for q in self.ps)
        if denom <= 1e-9:
            return False                       # UNDEFINED is not permission
        estimated_share = mine / denom
        return estimated_share <= self.kappa + 1e-9


class GlobalReadAgg(AggGuard):
    """Reads every principal's balance out of the state it is handed."""
    name = "GLOBAL_READ"
    reads_others_live = True

    def admits(self, s, a):
        if a.principal != self.p:
            return True
        nxt = E.apply(s, a) if E.physically_valid(s, a) else s
        estimated_conc = A.concentration(self.s0, nxt, self.ps)
        if estimated_conc is None:
            return False                       # UNDEFINED is not permission
        return estimated_conc <= self.kappa + 1e-9


class PartitionedReadAgg(AggGuard):
    """Own state plus a PUBLISHED (committed) bound. No live cross-principal read.

    Enforces the static box: every principal inside [L, U] implies
    concentration <= kappa, with no principal reading any other's live state.
    """
    name = "PARTITIONED_READ"
    reads_others_live = False

    def admits(self, s, a):
        if a.principal != self.p:
            return True
        nxt = E.apply(s, a) if E.physically_valid(s, a) else s
        mine = E.principal_total(self.s0, nxt, self.p)
        L, U = A.box_bounds(len(self.ps), self.kappa)
        return (mine >= L - 1e-9) and (mine <= U + 1e-9)


CONFIGS = {"F0": F0Agg, "LOCAL": LocalAgg,
           "GLOBAL_READ": GlobalReadAgg, "PARTITIONED_READ": PartitionedReadAgg}


def make_guards(config: str, ps: tuple[str, ...], kappa: float = A.KAPPA) -> dict:
    cls = CONFIGS[config]
    return {p: cls(p, ps, kappa) for p in ps}
