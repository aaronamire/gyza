"""R-D — a defector that spreads instead of colliding.

`research/churn/churn_tree.py` is IMPORTED READ-ONLY: it reproduces R-B's
k* = 103 at r = 0, which is the control licensing any comparison here. **Only
the destination rule changes**, so any difference is attributable to dispersal
and to nothing else.

COLLIDE  (R-C's adversary) migrate to the fullest pool. Every defector picks
         the same destination, so they pile into one cluster.
DISPERSE (this route)      migrate to the fullest pool NOT YET VISITED, falling
         back to the fullest overall once all have been seen.
"""
from __future__ import annotations

import pathlib
import random
import sys
from fractions import Fraction as F

_C = pathlib.Path(__file__).resolve().parents[1] / "churn"
_H = pathlib.Path(__file__).resolve().parents[1] / "hierarchy"
_M = pathlib.Path(__file__).resolve().parents[1] / "margin"
for _p in (_C, _H, _M):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from churn_tree import CLAIM_TRAVELS, ChurnTree                 # noqa: E402
from tree import box_floor_at, kappa_level, level_endowment     # noqa: E402

COLLIDE, DISPERSE = "COLLIDE", "DISPERSE"


def run_trial(d: int, f: int, delta: F, eps: int, k: int, routing: str,
              seed: int, rounds: int = 40, rate: F = F(1)) -> dict:
    rng = random.Random(seed)
    t = ChurnTree(d, f)
    kl = kappa_level(d)
    floors = {lvl: box_floor_at(f, kl, delta, level_endowment(f, lvl - 1))
              for lvl in range(1, d + 1)}
    genesis = [sum(t.leaves[c * f:(c + 1) * f]) for c in range(t.n_clusters)]

    order = list(range(1, t.n))
    rng.shuffle(order)
    defectors = set(order[:k])

    cum_div = [0] * t.n
    hist_div = [list(cum_div)]
    violations = undefined = 0

    for _ in range(rounds):
        movers = [p for p in order if p in defectors]
        n_move = int(len(movers) * float(rate))
        for p in rng.sample(movers, min(n_move, len(movers))):
            if routing == COLLIDE:
                dest = max(range(t.n_clusters), key=lambda c: t.pool[c])
            elif routing == DISPERSE:
                # fullest pool this defector has NOT yet drained; once every
                # cluster has been visited, fall back to the fullest overall
                unseen = [c for c in range(t.n_clusters)
                          if c not in t.touched[p]]
                pool = unseen or list(range(t.n_clusters))
                dest = max(pool, key=lambda c: t.pool[c])
            else:
                raise ValueError(routing)
            t.migrate(p, dest, CLAIM_TRAVELS)

        v_div = hist_div[max(0, len(hist_div) - 1 - eps)]
        for leaf in order:
            true = t.leaf_total(leaf)
            believed = (t.seen(0, leaf, eps) - (cum_div[leaf] - v_div[leaf])
                        if eps > 0 else true)
            floor = 0 if leaf in defectors else floors[1]
            want = believed - floor
            if want <= 0:
                continue
            admitted = True
            if leaf not in defectors:
                for lvl in range(1, d + 1):
                    idx = leaf // (f ** (lvl - 1))
                    if t.seen(lvl - 1, idx, eps) - want < floors[lvl]:
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

    now = [sum(t.leaves[c * f:(c + 1) * f]) for c in range(t.n_clusters)]
    # DAMAGE, kept separate from REACH. R-C established these are different
    # quantities and that conflating them is what made reach look load-bearing.
    below_half = sum(1 for a, b in zip(genesis, now) if a > 0 and b < a // 2)
    reach = [len(t.touched[p]) for p in defectors] or [1]
    return {"violations": violations, "undefined_rounds": undefined,
            "pools_touched": max(reach),
            "mean_pools_touched": sum(reach) / len(reach),
            "clusters_below_half": below_half}


def cell(d, f, delta, eps, k, routing, seeds=3, rounds=40, rate=F(1)) -> dict:
    acc = {"violations": 0, "undefined_rounds": 0, "pools_touched": 0,
           "clusters_below_half": 0}
    mp = []
    for s in range(seeds):
        r = run_trial(d, f, delta, eps, k, routing, s, rounds, rate)
        acc["violations"] += r["violations"]
        acc["undefined_rounds"] += r["undefined_rounds"]
        acc["pools_touched"] = max(acc["pools_touched"], r["pools_touched"])
        acc["clusters_below_half"] = max(acc["clusters_below_half"],
                                         r["clusters_below_half"])
        mp.append(r["mean_pools_touched"])
    acc["safe"] = acc["violations"] == 0
    acc["mean_pools_touched"] = sum(mp) / len(mp)
    return acc


def critical_k(d, f, delta, eps, routing, seeds=3, rounds=40,
               rate=F(1)) -> int | None:
    n = f ** d
    hi = 1
    while hi < n:
        if not cell(d, f, delta, eps, hi, routing, seeds, rounds, rate)["safe"]:
            break
        hi *= 2
    else:
        hi = n - 1
    if cell(d, f, delta, eps, min(hi, n - 1), routing, seeds, rounds,
            rate)["safe"]:
        if cell(d, f, delta, eps, n - 1, routing, seeds, rounds, rate)["safe"]:
            return None                       # full range covered before None
        hi = n - 1
    lo = max(1, hi // 2)
    while lo < hi:
        mid = (lo + hi) // 2
        if not cell(d, f, delta, eps, mid, routing, seeds, rounds, rate)["safe"]:
            hi = mid
        else:
            lo = mid + 1
    return lo


__all__ = ["run_trial", "cell", "critical_k", "COLLIDE", "DISPERSE"]
