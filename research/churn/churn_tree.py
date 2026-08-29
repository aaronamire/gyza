"""R-C — commons membership that churns.

`research/hierarchy/tree.py` is IMPORTED READ-ONLY: R-H1, R-B and R-N were all
measured on it. `ChurnTree` subclasses `Tree` and replaces ONE thing -- the
positional pool assignment `leaf // f` -- with an explicit `pool_of` map.

THE TREE'S ADMISSION STRUCTURE IS UNCHANGED. Only commons membership churns,
because the commons is the mechanism under test: R-N's saturation is caused by
a stale reader's error being bounded by ONE cluster's pool. If a principal can
draw on several pools over time, that bound is gone.

THE CLAIM POLICY IS A FRAME DECISION, and it is the reason this file has two of
them rather than a default. `contrib` is what entitles a principal to a share of
a pool; whether it MOVES with the principal decides whether drainage is
repeatable or one-shot.
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

from env_margin import CONTRIB                                  # noqa: E402
from tree import (                                              # noqa: E402
    Tree, box_floor_at, kappa_level, level_endowment,
)

CLAIM_TRAVELS, CLAIM_STAYS = "CLAIM_TRAVELS", "CLAIM_STAYS"
BENIGN, ADVERSARIAL = "BENIGN", "ADVERSARIAL"


class ChurnTree(Tree):
    """A tree whose commons membership can be reassigned."""

    def __init__(self, d: int, f: int):
        # BEFORE super(): Tree.__init__ folds the leaves for its genesis
        # snapshot, and that fold reaches `cluster_of`, which reads this map.
        # Identical to `leaf // f` at construction, so r = 0 is bit-for-bit the
        # environment R-B and R-N were measured on.
        self.pool_of = [i // f for i in range(f ** d)]
        self.touched: list[set[int]] = [{i // f} for i in range(f ** d)]
        super().__init__(d, f)

    def cluster_of(self, leaf: int) -> int:          # overrides Tree
        return self.pool_of[leaf]

    def migrate(self, leaf: int, dest: int, policy: str) -> None:
        src = self.pool_of[leaf]
        if src == dest:
            return
        if policy == CLAIM_TRAVELS:
            # the entitlement moves: the origin's funded total shrinks, the
            # destination's grows. A migrant arrives with a fresh claim on a
            # pool it has not yet drained.
            self.funded[src] -= self.contrib[leaf]
            self.funded[dest] += self.contrib[leaf]
        elif policy == CLAIM_STAYS:
            # the entitlement is a stake in the ORIGIN and does not follow. The
            # migrant holds no claim where it lands, so drainage is one-shot.
            self.funded[src] -= self.contrib[leaf]
            self.contrib[leaf] = 0
        else:
            raise ValueError(policy)
        self.pool_of[leaf] = dest
        self.touched[leaf].add(dest)


def run_trial(d: int, f: int, delta: F, eps: int, k: int, rate: F,
              policy: str, mode: str, seed: int, rounds: int = 40) -> dict:
    """One trajectory with churn. Defectors shed to zero (R-B's SHED,
    UNILATERAL) -- the mode R-B measured k* = 103 on."""
    rng = random.Random(seed)
    t = ChurnTree(d, f)
    kl = kappa_level(d)
    floors = {lvl: box_floor_at(f, kl, delta, level_endowment(f, lvl - 1))
              for lvl in range(1, d + 1)}

    order = list(range(1, t.n))
    rng.shuffle(order)
    defectors = set(order[:k])

    cum_div = [0] * t.n
    hist_div = [list(cum_div)]
    violations = undefined = 0

    for _ in range(rounds):
        # -- churn first, so the round's admissions see the new membership ----
        if rate > 0:
            movers = ([p for p in order if p in defectors] if mode == ADVERSARIAL
                      else order)
            n_move = int(len(movers) * float(rate))
            for p in rng.sample(movers, min(n_move, len(movers))):
                if mode == ADVERSARIAL:
                    # migrate to the FULLEST pool -- the attack the mechanism is
                    # actually exposed to, not a random walk
                    dest = max(range(t.n_clusters), key=lambda c: t.pool[c])
                else:
                    dest = rng.randrange(t.n_clusters)
                t.migrate(p, dest, policy)

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

    pools = ([len(t.touched[p]) for p in defectors] if defectors
             else [len(t.touched[1])])
    return {"violations": violations, "undefined_rounds": undefined,
            "pools_touched": max(pools),
            "mean_pools_touched": sum(pools) / len(pools)}


def cell(d, f, delta, eps, k, rate, policy, mode, seeds=3, rounds=40) -> dict:
    acc = {"violations": 0, "undefined_rounds": 0, "pools_touched": 0}
    mp = []
    for s in range(seeds):
        r = run_trial(d, f, delta, eps, k, rate, policy, mode, s, rounds)
        acc["violations"] += r["violations"]
        acc["undefined_rounds"] += r["undefined_rounds"]
        acc["pools_touched"] = max(acc["pools_touched"], r["pools_touched"])
        mp.append(r["mean_pools_touched"])
    acc["safe"] = acc["violations"] == 0
    acc["mean_pools_touched"] = sum(mp) / len(mp)
    return acc


def critical_k(d, f, delta, eps, rate, policy, mode, seeds=3,
               rounds=40) -> int | None:
    """Smallest k that breaches. Doubling, then bisection, then the FULL range
    before returning None -- R-M1 published four false negatives by not
    covering the range its rule ranged over."""
    n = f ** d
    hi = 1
    while hi < n:
        if cell(d, f, delta, eps, hi, rate, policy, mode, seeds,
                rounds)["violations"] > 0:
            break
        hi *= 2
    else:
        hi = n - 1
    if cell(d, f, delta, eps, min(hi, n - 1), rate, policy, mode, seeds,
            rounds)["violations"] == 0:
        if cell(d, f, delta, eps, n - 1, rate, policy, mode, seeds,
                rounds)["violations"] == 0:
            return None
        hi = n - 1
    lo = max(1, hi // 2)
    while lo < hi:
        mid = (lo + hi) // 2
        if cell(d, f, delta, eps, mid, rate, policy, mode, seeds,
                rounds)["violations"] > 0:
            hi = mid
        else:
            lo = mid + 1
    return lo


__all__ = ["ChurnTree", "run_trial", "cell", "critical_k",
           "CLAIM_TRAVELS", "CLAIM_STAYS", "BENIGN", "ADVERSARIAL"]
