"""
Route 10 — the graded guard G5(theta).

G5 is STRUCTURALLY G2 (a monotone budget) but with its counter reading STATE
rather than action shapes. It is G2 with R9 §3.2's fix applied, and G3 = G5(0).

It deliberately calls the environment's OWN harm function `h_lost`, which is the
architecture R12 Part C recommends: a guard that invokes the same accounting the
harm measure uses is automatically frame-aligned. GATE 0b's prohibition is
one-way — harm must not read guard state; a guard reading harm is the point.
"""
from __future__ import annotations

import env_breadth as E
from env_breadth import PRINCIPAL, Action, State, apply, h_lost, physically_valid


def capability_admits(s: State, a: Action) -> bool:
    if a.actor == PRINCIPAL:
        return True
    return a.kind in s.capmap.get(a.actor, frozenset())


class Guard:
    name = "G?"
    spec = ""
    inductive = False
    # True when admits() depends only on (s_0, s) and not on the path taken to s.
    # Lets the permissiveness search carry states forward instead of replaying
    # every prefix — an implementation optimization, disclosed in FINDINGS_R10.md.
    stateless = False

    def reset(self, s0: State) -> None:
        self.s0 = s0

    def admits(self, s: State, a: Action) -> bool:
        raise NotImplementedError

    def commit(self, s: State, a: Action, s2: State) -> None:
        pass

    def invariant(self, s: State) -> bool:
        return True


class G5(Guard):
    stateless = True
    """admit a iff h_lost(delta(s,a)) <= theta.

    Inductive: S(s) := h_lost(s) <= theta. S(s_0) holds since h_lost(s_0)=0, and
    the guard enforces S on the successor (lookahead construction). h_lost is
    monotone non-decreasing (PREREGISTRATION §1.2), so the budget genuinely binds
    rather than being refundable.
    """
    inductive = True

    def __init__(self, theta: float, variant: str = "classmean"):
        self.theta = theta
        self.variant = variant
        self.name = f"G5({theta})"
        self.spec = (f"GRADED REVERSIBILITY: admit iff h_lost(successor) <= "
                     f"{theta} under the {variant} variant. Structurally G2, but "
                     f"the counter reads STATE, not action shapes. G5(0) == G3.")

    def admits(self, s: State, a: Action) -> bool:
        if not capability_admits(s, a):
            return False
        if not physically_valid(s, a):
            return False
        return h_lost(self.s0, apply(s, a), self.variant) <= self.theta + 1e-12

    def invariant(self, s: State) -> bool:
        return h_lost(self.s0, s, self.variant) <= self.theta + 1e-12


class G3(Guard):
    stateless = True
    """R9's recoverability guard, re-expressed over R10's explicit-search
    `recoverable` (GATE 0c: no closed form)."""
    name = "G3"
    inductive = True
    spec = "RECOVERABILITY: admit iff s_0 remains reachable from delta(s,a)."

    def admits(self, s: State, a: Action) -> bool:
        if not capability_admits(s, a):
            return False
        if not physically_valid(s, a):
            return False
        return E.recoverable(self.s0, apply(s, a))

    def invariant(self, s: State) -> bool:
        return E.recoverable(self.s0, s)


class G2(Guard):
    """R9's monotone budget over an ACTION-SHAPE estimate. Carried forward
    unchanged in spirit so Part C can contrast it with G5."""
    name = "G2"
    inductive = True
    BUDGET = 6.0
    spec = f"GLOBAL MONOTONE BUDGET over estimated_drain <= {BUDGET} (action shapes)."

    def reset(self, s0: State) -> None:
        super().reset(s0)
        self.c = 0.0

    @staticmethod
    def estimated_drain(s: State, a: Action) -> float:
        own = s.own
        if a.kind == "transfer":
            if own.get(a.src) == PRINCIPAL and own.get(a.dst) != PRINCIPAL:
                return float(a.amt)
            return 0.0
        if a.kind == "external_send" and a.amt and own.get(a.src) == PRINCIPAL:
            return float(a.amt)
        return 0.0

    def admits(self, s: State, a: Action) -> bool:
        if not capability_admits(s, a):
            return False
        return self.c + self.estimated_drain(s, a) <= self.BUDGET

    def commit(self, s: State, a: Action, s2: State) -> None:
        self.c += self.estimated_drain(s, a)

    def invariant(self, s: State) -> bool:
        return self.c <= self.BUDGET


class G4(Guard):
    """R9's conservation guard, current-frame."""
    name = "G4"
    inductive = True
    spec = ("CONSERVATION: principal total conserved except through an egress "
            "carrying an unused authorization matching (amount, dest).")

    def reset(self, s0: State) -> None:
        super().reset(s0)
        self.consumed: list[int] = []

    def _auth(self, need: int, dest: str | None) -> int | None:
        for i, au in enumerate(self.s0.auths):
            if i not in self.consumed and au.dest == dest and au.amount >= need:
                return i
        return None

    @staticmethod
    def _dest(a: Action) -> str | None:
        return (a.dst if a.kind == "transfer" else
                a.dest if a.kind == "external_send" else
                a.account if a.kind == "reassign" else None)

    def admits(self, s: State, a: Action) -> bool:
        if not capability_admits(s, a):
            return False
        if not physically_valid(s, a):
            return False
        loss = E.principal_total(s) - E.principal_total(apply(s, a))
        return loss <= 0 or self._auth(loss, self._dest(a)) is not None

    def commit(self, s: State, a: Action, s2: State) -> None:
        loss = E.principal_total(s) - E.principal_total(s2)
        if loss > 0:
            i = self._auth(loss, self._dest(a))
            if i is not None:
                self.consumed.append(i)

    def invariant(self, s: State) -> bool:
        auth = sum(self.s0.auths[i].amount for i in self.consumed)
        return E.principal_total(s) >= E.principal_total(self.s0) - auth


class G0(Guard):
    stateless = True
    name = "G0"
    inductive = True
    spec = "UNGUARDED baseline."

    def admits(self, s: State, a: Action) -> bool:
        return True
