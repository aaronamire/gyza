"""R-B — defectors inside a tree. A2's modes composed with R-H1's topology.

`research/hierarchy/tree.py` is IMPORTED READ-ONLY: `Tree`, the floors, and
`kappa_level` are the committed environment R-H1's numbers were measured on. The
round loop is re-implemented here because it needs a defector parameter -- a
variant, not a copy of the environment, and the distinction is stated rather
than assumed.

THE SPLIT THAT FLAT FEDERATION DOES NOT HAVE. A2's defector "ignores its own
guard". In a tree there is something above it, so:

  UNILATERAL  the leaf divests without asking; ancestors cannot stop it.
              Tests whether the TOPOLOGY bounds damage.
  SUPERVISED  the leaf proposes anything, but every ancestor still admits or
              refuses against its own eps-stale box. Tests whether hierarchical
              ENFORCEMENT bounds it.

Flat federation has no supervised case: there is nothing above a principal.
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

from env_margin import CONTRIB, SCALE, U                        # noqa: E402
from tree import (                                              # noqa: E402
    KAPPA, Tree, box_floor_at, kappa_level, level_endowment,
)

SHED, SKEW, HOARD = "SHED", "SKEW", "HOARD"
UNILATERAL, SUPERVISED = "UNILATERAL", "SUPERVISED"


def run_trial(d: int, f: int, delta: F, eps: int, k: int, mode: str,
              regime: str, seed: int, rounds: int = 40) -> dict:
    rng = random.Random(seed)
    t = Tree(d, f)
    kl = kappa_level(d)
    floors = {lvl: box_floor_at(f, kl, delta, level_endowment(f, lvl - 1))
              for lvl in range(1, d + 1)}
    genesis_cluster = [sum(t.leaves[c * f:(c + 1) * f])
                       for c in range(t.n_clusters)]

    order = list(range(1, t.n))                 # leaf 0 is the held-out target
    rng.shuffle(order)
    # DEFECTORS ARE SPREAD, NOT CONCENTRATED. Taking the first k of a shuffled
    # order scatters them across clusters, which is the INDEPENDENT adversary
    # the preregistration scopes. A colluding adversary that piles every
    # defector into one cluster is a different and stronger threat, and is
    # explicitly out of scope (Sec 6.2) rather than silently approximated.
    defectors = set(order[:k])

    cum_div = [0] * t.n
    hist_div = [list(cum_div)]
    violations = undefined = 0
    honest_attempts = honest_refused = 0

    for _ in range(rounds):
        v_div = hist_div[max(0, len(hist_div) - 1 - eps)]
        for leaf in order:
            is_def = leaf in defectors

            if is_def and mode == HOARD:
                # capture this leaf's own CLUSTER pool -- the whole point of
                # the route is that this is the cluster's, not the federation's
                c = t.cluster_of(leaf)
                take = t.pool[c]
                if take > 0:
                    t.pool[c] -= take
                    t.holdings[leaf] += take
                continue

            believed = (t.seen(0, leaf, eps) - (cum_div[leaf] - v_div[leaf])
                        if eps > 0 else t.leaf_total(leaf))
            if is_def:
                floor = 0 if mode == SHED else box_floor_at(
                    f, kl, F(0), level_endowment(f, 0))     # SKEW: obeys L(0)
            else:
                floor = floors[1]
            want = believed - floor
            if want <= 0:
                continue

            admitted = True
            if not is_def or regime == SUPERVISED:
                # a SUPERVISED defector still faces every ancestor's box; a
                # UNILATERAL one faces none. An honest leaf always faces them.
                for lvl in range(1, d + 1):
                    idx = leaf // (f ** (lvl - 1))
                    if t.seen(lvl - 1, idx, eps) - want < floors[lvl]:
                        admitted = False
                        break
            if not is_def:
                honest_attempts += 1
                if not admitted:
                    honest_refused += 1
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
    # BLAST RADIUS IS A DIFFERENTIAL, NOT AN ABSOLUTE.
    #
    # "clusters below half genesis" read 64/64 even at k = 0, because the
    # honest adversarial population already halves every cluster -- the metric
    # was saturated by the baseline and said nothing about the defector. What
    # the route actually asks is whether damage stays where the defector is, so
    # the measure splits clusters into those CONTAINING a defector and those
    # not, and reports each separately.
    dirty = {leaf // f for leaf in defectors}
    def _mean(idxs):
        vals = [now[c] / genesis_cluster[c] for c in idxs
                if genesis_cluster[c] > 0]
        return sum(vals) / len(vals) if vals else None
    frac_dirty = _mean(dirty)
    frac_clean = _mean(set(range(t.n_clusters)) - dirty)
    damaged = len(dirty)
    comp = [t.leaf_total(p) for p in order if p not in defectors]
    defs_ = [t.leaf_total(p) for p in defectors]
    return {
        "violations": violations, "undefined_rounds": undefined,
        "clusters_damaged": damaged, "n_clusters": t.n_clusters,
        "frac_remaining_dirty": frac_dirty, "frac_remaining_clean": frac_clean,
        "honest_attempts": honest_attempts, "honest_refused": honest_refused,
        "hoard_payoff": ((sum(defs_) / len(defs_) - sum(comp) / len(comp))
                         / SCALE if defs_ and comp else None),
        "peak_concentration": t.concentration(),
    }


def cell(d, f, delta, eps, k, mode, regime, seeds=3, rounds=40) -> dict:
    acc = {"violations": 0, "undefined_rounds": 0, "clusters_damaged": 0,
           "honest_attempts": 0, "honest_refused": 0}
    pay, fd, fc = [], [], []
    for s in range(seeds):
        r = run_trial(d, f, delta, eps, k, mode, regime, s, rounds)
        for key in acc:
            acc[key] = (max(acc[key], r[key]) if key == "clusters_damaged"
                        else acc[key] + r[key])
        if r["hoard_payoff"] is not None:
            pay.append(r["hoard_payoff"])
        if r["frac_remaining_dirty"] is not None:
            fd.append(r["frac_remaining_dirty"])
        if r["frac_remaining_clean"] is not None:
            fc.append(r["frac_remaining_clean"])
    acc["breached"] = acc["violations"] > 0
    # 0/0 IS NOT 0: with no honest attempts there is no refusal RATE.
    acc["honest_refusal"] = (acc["honest_refused"] / acc["honest_attempts"]
                             if acc["honest_attempts"] else None)
    acc["payoff"] = sum(pay) / len(pay) if pay else None
    acc["frac_dirty"] = sum(fd) / len(fd) if fd else None
    acc["frac_clean"] = sum(fc) / len(fc) if fc else None
    return acc


def critical_k(d, f, delta, eps, mode, regime, seeds=3, rounds=40) -> dict:
    """Smallest k that breaches. Doubling, then bisection, then a FULL-RANGE
    check before returning None.

    R-M1 published four false INFEASIBLE verdicts because a stride never
    covered the interval its rule ranged over. A negative verdict here is only
    returned after k = M-1 itself is tested.
    """
    n = f ** d
    curve = []
    hi = 1
    while hi < n:
        r = cell(d, f, delta, eps, hi, mode, regime, seeds, rounds)
        curve.append((hi, r["violations"]))
        if r["breached"]:
            break
        hi *= 2
    else:
        hi = n - 1
    if not cell(d, f, delta, eps, min(hi, n - 1), mode, regime,
                seeds, rounds)["breached"]:
        top = cell(d, f, delta, eps, n - 1, mode, regime, seeds, rounds)
        curve.append((n - 1, top["violations"]))
        if not top["breached"]:
            return {"k_star": None, "curve": curve,
                    "note": "no k in [1, M-1] breaches"}
        hi = n - 1
    lo = max(1, hi // 2)
    while lo < hi:                                  # bisect on the true minimum
        mid = (lo + hi) // 2
        if cell(d, f, delta, eps, mid, mode, regime, seeds, rounds)["breached"]:
            hi = mid
        else:
            lo = mid + 1
    return {"k_star": lo, "curve": curve}


__all__ = ["run_trial", "cell", "critical_k", "SHED", "SKEW", "HOARD",
           "UNILATERAL", "SUPERVISED"]
