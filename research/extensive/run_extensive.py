"""R-E — an extensive bound scored on the SAME trajectory as the ratio.

`research/hierarchy/tree.py` is IMPORTED READ-ONLY. Every route above bounds
concentration, `max/sum <= kappa` -- a scale-invariant RATIO. This scores a
second, EXTENSIVE predicate on the identical trajectory:

    PRESERVE   violation iff total < rho * genesis

Nothing about the dynamics changes. Both verdicts come off one run, so a
difference between them is attributable to the predicate and to nothing else.

WHY THIS ROUTE EXISTS. At delta = 0 with ZERO defectors the fully compliant
population destroys 99.26% of federation value while the ratio never moves. A
ratio bound is blind to how much exists.

BOTH PREDICATES ARE COMPUTED BY THE ENVIRONMENT FROM ENVIRONMENT STATE, never
from guard state -- standing rule #5. `rho` is a constant of the scored
predicate; no guard reads it.
"""
from __future__ import annotations

import pathlib
import random
import sys
from fractions import Fraction as F

_H = pathlib.Path(__file__).resolve().parents[1] / "hierarchy"
_M = pathlib.Path(__file__).resolve().parents[1] / "margin"
for _p in (_H, _M):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tree import (Tree, box_floor_at, ceiling_at, kappa_level,   # noqa: E402
                  level_endowment)

RATIO, PRESERVE = "RATIO", "PRESERVE"
RHO = F(2, 100)          # preregistered in PREREGISTRATION.md §3, BEFORE data

GRID = F(1, 200)         # delta grid, as R-N and R-M1


def run_trial(d: int, f: int, delta: F, eps: int, seed: int,
              rounds: int = 40, flat: bool = False, rho: F = RHO) -> dict:
    """One trajectory, TWO scored predicates.

    `flat=True` disables the internal-node admission checks, leaving only the
    leaf's own box -- the no-hierarchy control R-H1 established.
    """
    rng = random.Random(seed)
    t = Tree(d, f)
    kl = kappa_level(d)
    floors = {lvl: box_floor_at(f, kl, delta, level_endowment(f, lvl - 1))
              for lvl in range(1, d + 1)}

    genesis = sum(t.leaves)
    order = list(range(1, t.n))
    rng.shuffle(order)

    cum_div = [0] * t.n
    hist_div = [list(cum_div)]
    v_ratio = v_preserve = undefined = 0
    min_total = genesis

    for _ in range(rounds):
        v_div = hist_div[max(0, len(hist_div) - 1 - eps)]
        for leaf in order:
            true = t.leaf_total(leaf)
            believed = (t.seen(0, leaf, eps) - (cum_div[leaf] - v_div[leaf])
                        if eps > 0 else true)
            want = believed - floors[1]
            if want <= 0:
                continue
            admitted = True
            if not flat:
                for lvl in range(1, d + 1):
                    idx = leaf // (f ** (lvl - 1))
                    if t.seen(lvl - 1, idx, eps) - want < floors[lvl]:
                        admitted = False
                        break
            if admitted:
                cum_div[leaf] += t.divest(leaf, want)

        t.commit()
        hist_div.append(list(cum_div))

        r = t.concentration_exceeds()
        if r is None:
            undefined += 1
        elif r:
            v_ratio += 1

        # THE EXTENSIVE PREDICATE. Integer comparison against an IMMUTABLE
        # origin: `genesis` is fixed at construction and never reassigned.
        # A cumulative bound whose origin can move is not a bound.
        total = sum(t.leaves)
        min_total = min(min_total, total)
        if total * rho.denominator < genesis * rho.numerator:
            v_preserve += 1

    return {"v_ratio": v_ratio, "v_preserve": v_preserve,
            "undefined_rounds": undefined,
            "retained": F(min_total, genesis)}


def cell(d, f, delta, eps, bound, seeds=3, rounds=40, flat=False,
         rho: F = RHO) -> dict:
    acc = {"v_ratio": 0, "v_preserve": 0, "undefined_rounds": 0}
    worst = F(1)
    for s in range(seeds):
        r = run_trial(d, f, delta, eps, s, rounds, flat, rho)
        for k in ("v_ratio", "v_preserve", "undefined_rounds"):
            acc[k] += r[k]
        worst = min(worst, r["retained"])
    acc["retained"] = worst
    acc["safe"] = acc["v_ratio" if bound == RATIO else "v_preserve"] == 0
    return acc


def delta_star(d, f, eps, bound, seeds=3, rounds=40, flat=False,
               rho: F = RHO):
    """Smallest feasible delta on the grid, or None.

    COVERAGE, per the preregistration: the CEILING is tested first, so an
    INFEASIBLE verdict means 'no delta works including the largest', never
    'the scan stopped early'. R-M1's defect was exactly a stride that never
    tested the feasible band.
    """
    ceil = ceiling_at(f, kappa_level(d))
    # LARGEST grid point strictly below the ceiling. An earlier `- 1` here
    # reported INFEASIBLE at d=1 because it stopped at 0.590 while the ONLY
    # feasible point is 0.595 -- R-M1's stride defect, recurring in code
    # written by someone who had already recorded it. int() alone suffices:
    # ceil is never an exact multiple of GRID, so int(ceil/GRID)*GRID < ceil.
    top = int(ceil / GRID) * GRID
    assert top < ceil, (top, ceil)
    if top <= 0 or not cell(d, f, top, eps, bound, seeds, rounds, flat, rho)["safe"]:
        return None, cell(d, f, max(top, F(0)), eps, bound, seeds, rounds,
                          flat, rho)["retained"]
    lo, hi = F(0), top
    while hi - lo > GRID:
        mid = (int((lo + hi) / 2 / GRID)) * GRID
        if mid <= lo:
            break
        if cell(d, f, mid, eps, bound, seeds, rounds, flat, rho)["safe"]:
            hi = mid
        else:
            lo = mid
    c = cell(d, f, hi, eps, bound, seeds, rounds, flat, rho)
    return hi, c["retained"]


__all__ = ["run_trial", "cell", "delta_star", "RATIO", "PRESERVE", "RHO",
           "GRID"]
