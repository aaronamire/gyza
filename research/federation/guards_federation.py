"""
Route 13 guards — the four federation configurations (PREREGISTRATION §4).

  F0  UNGUARDED       no checks; baseline harm per principal.
  F1  LOCAL-ONLY      g_i evaluates ONLY h_i. The predicted-blind configuration.
  F2  SIGNATURE-GATED F1 + any action writing principal j's state requires j's
                      signed authorization, checked locally and STATELESSLY.
  F3  GLOBAL          one guard over the conjunction of ALL principals' harm
                      measures AND the joint quantity. Not deployable; included
                      as the containment UPPER BOUND.

GATE 0 direction. These guards CALL the environment's own `h_lost` — the
permitted direction, and the thing that makes them frame-aligned (R12 Part C).
Harm never reads guard state. No guard-side arithmetic estimates a harm, so no
`estimated_*` symbol is needed here; if one is ever added it must carry that
prefix.

R10's design rule. None of these guards carries an ACCUMULATOR across actions —
every one is a pure function of (s_0, s, a). Guard state therefore partitions
along the action axis, which is the property the derivation under test needs.
"""
from __future__ import annotations

import env_federation as E
from env_federation import Action, State, apply, h_lost, physically_valid

EPS = 1e-12


class Guard:
    name = "F?"
    spec = ""
    stateless = True              # no accumulator across actions

    def __init__(self, principal: str, theta: float = E.THETA):
        self.principal = principal
        self.theta = theta

    def reset(self, s0: State) -> None:
        self.s0 = s0

    def admits(self, s: State, a: Action) -> bool:
        raise NotImplementedError

    def commit(self, s: State, a: Action, s2: State) -> None:
        pass

    def invariant(self, s: State) -> bool:
        """The guard's own principal's invariant."""
        return h_lost(self.s0, s, self.principal) <= self.theta + EPS

    # -- READS instrumentation (for the R12 criterion, reported not assumed) --
    def reads_principals(self, s: State, a: Action) -> frozenset[str]:
        return frozenset({self.principal})


class F0(Guard):
    name = "F0"
    spec = "UNGUARDED: admit every physically valid action."

    def admits(self, s: State, a: Action) -> bool:
        return physically_valid(s, a)

    def invariant(self, s: State) -> bool:
        return True

    def reads_principals(self, s: State, a: Action) -> frozenset[str]:
        return frozenset()


class F1(Guard):
    name = "F1"
    spec = ("LOCAL-ONLY: admit iff h_lost[own principal](successor) <= theta. "
            "READS(g_i) = READS(h_i); structurally blind to every other "
            "principal's harm.")

    def admits(self, s: State, a: Action) -> bool:
        if not physically_valid(s, a):
            return False
        return h_lost(self.s0, apply(s, a), self.principal) <= self.theta + EPS


class F2(F1):
    name = "F2"
    spec = ("SIGNATURE-GATED: F1 plus — any action writing principal j's state "
            "requires j's signed authorization. The signature check is a pure "
            "function of the action and the static key table.")

    def admits(self, s: State, a: Action) -> bool:
        if not physically_valid(s, a):
            return False
        if not self.authorized(s, a):
            return False
        return h_lost(self.s0, apply(s, a), self.principal) <= self.theta + EPS

    def authorized(self, s: State, a: Action) -> bool:
        """Determining WHETHER authorization is required reads the ownership
        map (environment state). The authorization CHECK itself is stateless —
        that separation is deliberate and is what T-STATELESS pins."""
        required = E.written_principals(s, a) - {self.principal}
        if not required:
            return True
        supplied = {t.issuer for t in a.auths
                    if E.verify_auth(t) and t.action_key == a.key()}
        return required <= supplied

    def reads_principals(self, s: State, a: Action) -> frozenset[str]:
        # Reads its own harm, plus the IDENTITY (not the state) of the
        # counterparties whose signatures it demands.
        return frozenset({self.principal}) | E.written_principals(s, a)


class F3(Guard):
    name = "F3"
    spec = ("GLOBAL: admit iff EVERY principal's h_lost(successor) <= theta AND "
            "pool_overdraft(successor) == 0. Not deployable — a global checker "
            "is the coordination bottleneck. The containment UPPER BOUND.")

    def __init__(self, principal: str, theta: float = E.THETA,
                 all_principals: tuple[str, ...] = ("A", "B")):
        super().__init__(principal, theta)
        self.all_principals = all_principals

    def admits(self, s: State, a: Action) -> bool:
        if not physically_valid(s, a):
            return False
        t = apply(s, a)
        if E.pool_overdraft(t) > 0:
            return False
        return all(h_lost(self.s0, t, q) <= self.theta + EPS
                   for q in self.all_principals)

    def invariant(self, s: State) -> bool:
        return (E.pool_overdraft(s) == 0
                and all(h_lost(self.s0, s, q) <= self.theta + EPS
                        for q in self.all_principals))

    def reads_principals(self, s: State, a: Action) -> frozenset[str]:
        return frozenset(self.all_principals)


CONFIGS = {"F0": F0, "F1": F1, "F2": F2, "F3": F3}


def make_guards(config: str, ps: tuple[str, ...], theta: float = E.THETA) -> dict:
    """One guard instance per principal. F3's instances all share full
    visibility — it is one logical global checker, replicated for interface
    uniformity."""
    cls = CONFIGS[config]
    if config == "F3":
        return {p: F3(p, theta, ps) for p in ps}
    return {p: cls(p, theta) for p in ps}


# --------------------------------------------------------------------------- #
#  Environment-level invariants (harm-side, NOT guard state)                   #
# --------------------------------------------------------------------------- #
def principal_invariant(s0: State, s: State, p: str,
                        theta: float = E.THETA) -> bool:
    """Principal p's invariant, evaluated by the harness from HARM, so that a
    violation can be detected even when no guard ever looked at it."""
    return h_lost(s0, s, p) <= theta + EPS
