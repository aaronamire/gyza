"""R-H1 — a d-level tree of local box checks over R-M1's environment.

`env_margin` is IMPORTED, not copied: R-M1's numbers were measured on it and a
copy is a second frame free to drift. Exact integer nano-units throughout; there
is no tolerance parameter anywhere, which is the precondition R-M1 established
after five float-boundary artifacts.

THE TOPOLOGY. Principals are the f**d leaves of a complete tree. Every internal
node runs the SAME local box check its children run, at `kappa_l = kappa**(1/d)`,
so the composition `kappa_global <= prod(kappa_level)` applies by construction.

STALENESS COMPOUNDS BY CONSTRUCTION, NOT BY FIAT. Each level keeps its own
snapshot history and reads its children from it. A level-2 node therefore sees
level-1 sums that were themselves computed from eps-stale leaves. Nothing here
multiplies eps by d -- the compounding, if it happens, emerges from independent
per-level snapshots, which is what an unsynchronised mesh actually does.
"""
from __future__ import annotations

import pathlib
import random
import sys
from fractions import Fraction as F

_MARGIN = pathlib.Path(__file__).resolve().parents[1] / "margin"
if str(_MARGIN) not in sys.path:
    sys.path.insert(0, str(_MARGIN))

from env_margin import ACCT, CONTRIB, KAPPA, SCALE, U          # noqa: E402


def kappa_level(d: int) -> F:
    """Per-level kappa such that the product over d levels is KAPPA.

    Rational d-th root: KAPPA is 3/5, and 3/5**(1/d) is irrational for d>1, so
    it is taken to a fixed rational precision and ROUNDED DOWN. Rounding down
    makes each level STRICTER, so the product stays <= KAPPA. Rounding up would
    let the composed bound exceed the global one by construction -- a safety
    direction chosen deliberately rather than by float default.
    """
    if d == 1:
        return KAPPA
    # THE ROUNDING DIRECTION IS THE SAFETY PROPERTY, AND `limit_denominator`
    # DOES NOT PROVIDE IT. It returns the CLOSEST rational, which may be above
    # the true root -- and the first version of this function used it and
    # produced kappa_l**3 = 0.600000... > 3/5 at d = 3. A per-level kappa that
    # is even slightly too permissive makes the composed bound exceed the
    # global one BY CONSTRUCTION, so the route would have been measuring its
    # own arithmetic error rather than the topology.
    #
    # Fixed denominator, then step DOWN until the product is provably within
    # bound. The post-condition is asserted, not assumed.
    q = 10 ** 6
    lo, hi = 0, q
    while lo < hi:                            # largest p with (p/q)**d <= KAPPA
        mid = (lo + hi + 1) // 2
        if F(mid, q) ** d <= KAPPA:
            lo = mid
        else:
            hi = mid - 1
    kl = F(lo, q)
    assert kl ** d <= KAPPA, (d, kl, kl ** d)
    return kl


def box_floor_at(f: int, kl: F, delta: F, endowment: int = U) -> int:
    """L(delta) in nano-units for a node with `f` children, ROUNDED UP.

    THE ENDOWMENT IS A PARAMETER, AND THE FIRST VERSION HARDCODED IT. A level-k
    node's children are level-(k-1) nodes each holding `f**(k-1) * U`, so the
    floor must scale with the level. Using the leaf endowment at every level
    gave level-2 and level-3 checks a floor ~f and ~f**2 times too small --
    a guard that admits almost anything, reported as a guard.

    Rounded UP because a floor is a safety bound; rounding down hands the guard
    unearned permissiveness.
    """
    k = kl - delta
    if k <= 0:
        raise ValueError(f"delta {delta} >= kappa_level {kl}")
    L = F(endowment) * (1 - k) / (k * (f - 1))
    return -((-L.numerator) // L.denominator)


def level_endowment(f: int, level: int) -> int:
    """Genesis value of ONE node at `level` (0 = leaf)."""
    return U * (f ** level)


def ceiling_at(f: int, kl: F) -> F:
    """delta at which the node's box is EMPTY (L = U)."""
    return kl - F(1, f)


class Tree:
    """Complete tree, fanout f, depth d. Leaves hold value; nodes hold sums.

    `leaves` is the only mutable state. Every node value is a FOLD over its
    subtree, computed on demand -- never stored -- so a node and its children
    are structurally unable to disagree about the frame (C3).
    """

    def __init__(self, d: int, f: int):
        self.d, self.f = d, f
        self.n = f ** d
        self.holdings = [ACCT] * self.n
        # ONE COMMONS PER CLUSTER, and this is the whole point of the topology.
        #
        # Without a shared pool a leaf knows itself exactly, nothing causes
        # other-caused change, and the box is sound BY DEFINITION -- the first
        # version measured 0 violations at delta=0 in every topology, which is
        # the same null R-M1's uncoupled arena produced. A2 then established
        # that the commons IS the mechanism: a defector's damage travels
        # through the shared pool, not through its own term.
        #
        # Giving each level-1 cluster its own pool asks the question that makes
        # hierarchy interesting: does a drain stay CONFINED to one cluster?
        self.n_clusters = f ** (d - 1) if d >= 1 else 1
        self.pool = [CONTRIB * f] * self.n_clusters
        self.funded = [CONTRIB * f] * self.n_clusters
        self.contrib = [CONTRIB] * self.n
        self.history: list[list[list[int]]] = [
            [self.level_values(l)] for l in range(d + 1)]

    # -- folds: the environment's own arithmetic -----------------------------
    def cluster_of(self, leaf: int) -> int:
        return leaf // self.f

    def claim(self, leaf: int) -> int:
        c = self.cluster_of(leaf)
        if self.funded[c] <= 0 or self.pool[c] <= 0:
            return 0
        return self.contrib[leaf] * self.pool[c] // self.funded[c]

    def leaf_total(self, leaf: int) -> int:
        return self.holdings[leaf] + self.claim(leaf)

    @property
    def leaves(self) -> list[int]:
        return [self.leaf_total(i) for i in range(self.n)]

    def divest(self, leaf: int, amount: int) -> int:
        """Reduce a leaf's total, withdrawing its pool claim first.

        Withdrawing shrinks the CLUSTER's pool and therefore every sibling's
        claim -- other-caused change, contained inside one cluster by
        construction. Returns what was actually divested.
        """
        if amount <= 0:
            return 0
        before = self.leaf_total(leaf)
        short = amount - self.holdings[leaf]
        if short > 0:
            c = self.cluster_of(leaf)
            w = min(short, self.claim(leaf))
            self.pool[c] -= w
            self.holdings[leaf] += w
        self.holdings[leaf] = max(self.holdings[leaf] - amount, 0)
        return before - self.leaf_total(leaf)

    def level_values(self, level: int) -> list[int]:
        """Node values at `level` (0 = leaves, d = root). A pure fold."""
        lv = self.leaves
        if level == 0:
            return lv
        step = self.f ** level
        return [sum(lv[i:i + step]) for i in range(0, self.n, step)]

    def concentration_exceeds(self) -> bool | None:
        """EXACT global check. None when UNDEFINED (total 0) -- GATE 0c."""
        lv = self.leaves
        s = sum(lv)
        if s <= 0:
            return None
        return max(lv) * KAPPA.denominator > KAPPA.numerator * s

    def concentration(self) -> F | None:
        lv = self.leaves
        s = sum(lv)
        return None if s <= 0 else F(max(lv), s)

    def commit(self) -> None:
        for l in range(self.d + 1):
            self.history[l].append(self.level_values(l))

    def seen(self, level: int, idx: int, eps: int) -> int:
        """What a node at `level` believes about sibling `idx`, eps rounds old.

        Reading level L's OWN history -- and that history was itself built from
        leaf state at the time, which the level below was already stale about.
        The compounding is in the data, not in a multiplier.
        """
        h = self.history[level]
        return h[max(0, len(h) - 1 - eps)][idx]


def run_trial(d: int, f: int, delta: F, eps: int, seed: int,
              rounds: int = 40) -> dict:
    """One trajectory. ONLY LEAVES HOLD VALUE AND ONLY LEAVES ACT.

    Internal nodes are pure ADMISSION CONTROLLERS: a leaf proposes to divest,
    and every ancestor must admit it against that ancestor's own box, judged
    from an eps-stale view of its own subtree sum. Staleness compounds because a
    level-k node's view is stale about level-(k-1) sums that were themselves
    moving while it looked.

    THREE APPARATUS DEFECTS THIS REPLACES, all found by controls before data.

    1. AMNESIA. The first version had leaves re-shed `believed - L` every round
       against a stale view of THEIR OWN value, so every leaf drained to zero
       and d=1 came out INFEASIBLE at every epsilon -- contradicting R-M1, which
       measured delta* = 0.295 at M = 512. R-M1's `trial.py` had already fixed
       exactly this ("staleness is OTHER-caused only") and the fix did not
       transfer to a new instrument built on the same environment. A leaf knows
       its own writes; what it cannot see is its siblings.

    2. A PARENT DIVESTING THROUGH ITS CHILDREN'S FLOORS. Divestment was drained
       leaf-by-leaf from the front of a subtree, taking individual leaves to 0
       regardless of their own boxes -- so `below_box` read 200/200 in every
       cell. Divestment now originates at a leaf and is admitted upward, which
       is the only direction that respects every box on the path.

    3. AN UNSCALED FLOOR (see `box_floor_at`).
    """
    rng = random.Random(seed)
    t = Tree(d, f)
    kl = kappa_level(d)
    # per-level floor, over that level's OWN endowment
    floors = {lvl: box_floor_at(f, kl, delta, level_endowment(f, lvl - 1))
              for lvl in range(1, d + 1)}

    violations = undefined = below_box = 0
    order = list(range(1, t.n))          # leaf 0 is the held-out target
    rng.shuffle(order)

    cum_div = [0] * t.n
    hist_div = [list(cum_div)]

    for _ in range(rounds):
        v_div = hist_div[max(0, len(hist_div) - 1 - eps)]
        for leaf in order:
            # A LEAF KNOWS ITS OWN WRITES AND NOTHING ELSE.
            #
            # belief = eps-old snapshot MINUS its own divestment since then, so
            # the residual error is purely OTHER-caused: siblings draining the
            # shared cluster pool. This is R-M1's `trial.py` mechanism ported
            # faithfully. The previous version handed the leaf its exact current
            # total, which made the guard exact and the attack UNREACHABLE --
            # 0 violations at delta=0 in every topology, the same definitional
            # null R-M1's uncoupled arena produced.
            believed = (t.seen(0, leaf, eps) - (cum_div[leaf] - v_div[leaf])
                        if eps > 0 else t.leaf_total(leaf))
            want = believed - floors[1]
            if want <= 0:
                continue
            # EVERY ANCESTOR ADMITS, AND EACH CHECKS ITS OWN CHILD.
            #
            # A level-`lvl` node enforces the box on its CHILDREN, which live at
            # level `lvl-1`. So the value under test is the level-(lvl-1) node
            # on this leaf's path, read from that level's own eps-stale history
            # -- which is where compounding enters: level 2 reads level-1 sums
            # that were themselves moving while it looked.
            admitted = True
            for lvl in range(1, d + 1):
                child_lvl = lvl - 1
                idx = leaf // (f ** child_lvl)
                if t.seen(child_lvl, idx, eps) - want < floors[lvl]:
                    admitted = False
                    break
            if admitted:
                cum_div[leaf] += t.divest(leaf, want)

        t.commit()
        hist_div.append(list(cum_div))
        v = t.concentration_exceeds()
        if v is None:
            undefined += 1
        elif v:
            violations += 1
        # H-SOUND's second clause: did any node end outside ITS OWN box?
        for lvl in range(1, d + 1):
            vals = t.level_values(lvl - 1)
            if any(x < floors[lvl] for i, x in enumerate(vals) if i != 0):
                below_box += 1
                break

    return {"violations": violations, "undefined_rounds": undefined,
            "below_box": below_box, "scored_rounds": rounds - undefined,
            "peak": t.concentration()}


def cell(d, f, delta, eps, seeds=5, rounds=40) -> dict:
    acc = {"violations": 0, "undefined_rounds": 0, "below_box": 0}
    for s in range(seeds):
        r = run_trial(d, f, delta, eps, s, rounds)
        for k in acc:
            acc[k] += r[k]
    acc["safe"] = acc["violations"] == 0
    return acc


def max_fan_in(d: int, f: int) -> int:
    """Largest number of peers any ONE node must read in a round.

    Flat (d=1) is f-1 = M-1: every principal reads every other. A tree is f-1
    at every level regardless of population. This is the quantity that decides
    whether 100K agents is tractable, and reporting delta* without it would
    hide the actual reason hierarchy is worth anything.
    """
    return f - 1


__all__ = ["Tree", "run_trial", "cell", "kappa_level", "box_floor_at",
           "ceiling_at", "max_fan_in", "KAPPA", "SCALE"]
