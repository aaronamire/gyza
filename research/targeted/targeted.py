"""R-T — an adversary that chooses WHERE to defect, not just how many.

`research/blast/defect_tree.py` is IMPORTED READ-ONLY: its round loop, modes,
regimes and staleness model are the committed environment R-B's k* = 103 was
measured on. **Only the placement rule changes**, so any difference is
attributable to placement and to nothing else.

R-D established that reach and damage are ANTI-correlated with breach and that
only ASYMMETRY predicts it. Every k* in this program was measured against
random placement, which is asymmetry-blind. These four arms vary exactly that.

RANDOM       R-B's shuffled order. The control; must reproduce 103.
SPARE        drawn only from outside the target's cluster.
SPARE_EVEN   same exclusion, round-robin over the 63 non-target clusters so
             none is left undamaged by chance. The strongest arm.
CONCENTRATE  the target's siblings first. The opposite extreme.

THE TARGET IS LEAF 0 and is held out of `order` by the imported environment, so
it never sheds and never defects. Its cluster is cluster 0.
"""
from __future__ import annotations

import pathlib
import random
import sys
from fractions import Fraction as F

_B = pathlib.Path(__file__).resolve().parents[1] / "blast"
_H = pathlib.Path(__file__).resolve().parents[1] / "hierarchy"
_M = pathlib.Path(__file__).resolve().parents[1] / "margin"
for _p in (_B, _H, _M):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from defect_tree import SHED, UNILATERAL                        # noqa: E402
from tree import (Tree, box_floor_at, kappa_level,              # noqa: E402
                  level_endowment)

RANDOM, SPARE, SPARE_EVEN, CONCENTRATE = (
    "RANDOM", "SPARE", "SPARE_EVEN", "CONCENTRATE")

#: NOT PREREGISTERED. Added after the k=103 mechanism check showed SPARE_EVEN
#: peaking at 0.9208 against SPARE's 0.5891 -- the preregistered arms vary TWO
#: factors at once (sparing x evenness) and cannot attribute between them.
#: EVEN_ALL is even placement over ALL 64 clusters INCLUDING the target's, so
#: {RANDOM, SPARE} x {EVEN_ALL, SPARE_EVEN} completes the 2x2. It is a
#: DECOMPOSITION control, not a hypothesis test, and no decision rule reads it.
EVEN_ALL = "EVEN_ALL"
TARGET = 0                       # held out of `order` by the environment


def _place(arm: str, order: list[int], k: int, f: int) -> set[int]:
    """Choose k defectors from `order` under the arm's placement rule.

    `order` is already shuffled by the caller, so RANDOM is exactly R-B's rule
    and every other arm is a re-selection over the same shuffled population --
    the seed governs the same randomness in all four.
    """
    tgt_cluster = TARGET // f
    if arm == RANDOM:
        return set(order[:k])

    outside = [p for p in order if p // f != tgt_cluster]
    inside = [p for p in order if p // f == tgt_cluster]

    if arm == SPARE:
        return set(outside[:k])

    if arm == CONCENTRATE:
        return set((inside + outside)[:k])

    if arm in (SPARE_EVEN, EVEN_ALL):
        # round-robin: fill one defector per cluster before any cluster
        # receives a second. Random placement leaves some clusters undamaged
        # by chance; this does not. SPARE_EVEN excludes the target's cluster,
        # EVEN_ALL includes it -- that is the only difference between them.
        source = outside if arm == SPARE_EVEN else order
        by_cluster: dict[int, list[int]] = {}
        for p in source:
            by_cluster.setdefault(p // f, []).append(p)
        chosen: list[int] = []
        depth = 0
        while len(chosen) < k:
            added = False
            for c in sorted(by_cluster):
                if depth < len(by_cluster[c]):
                    chosen.append(by_cluster[c][depth])
                    added = True
                    if len(chosen) == k:
                        break
            if not added:
                break                      # k exceeds the eligible population
            depth += 1
        return set(chosen)

    raise ValueError(arm)


def eligible(arm: str, n: int, f: int) -> int:
    """Size of the arm's defector population -- its k domain, stated in §3."""
    if arm in (SPARE, SPARE_EVEN):
        return n - 1 - (f - 1)           # exclude target AND its f-1 siblings
    return n - 1


def run_trial(d: int, f: int, delta: F, eps: int, k: int, arm: str,
              seed: int, rounds: int = 40) -> dict:
    rng = random.Random(seed)
    t = Tree(d, f)
    kl = kappa_level(d)
    floors = {lvl: box_floor_at(f, kl, delta, level_endowment(f, lvl - 1))
              for lvl in range(1, d + 1)}

    order = list(range(1, t.n))          # leaf 0 is the held-out target
    rng.shuffle(order)
    defectors = _place(arm, order, k, f)

    cum_div = [0] * t.n
    hist_div = [list(cum_div)]
    violations = undefined = 0
    honest_attempts = honest_refused = 0
    peak = F(0)

    for _ in range(rounds):
        v_div = hist_div[max(0, len(hist_div) - 1 - eps)]
        for leaf in order:
            is_def = leaf in defectors
            believed = (t.seen(0, leaf, eps) - (cum_div[leaf] - v_div[leaf])
                        if eps > 0 else t.leaf_total(leaf))
            floor = 0 if is_def else floors[1]        # SHED / UNILATERAL
            want = believed - floor
            if want <= 0:
                continue
            admitted = True
            if not is_def:
                for lvl in range(1, d + 1):
                    idx = leaf // (f ** (lvl - 1))
                    if t.seen(lvl - 1, idx, eps) - want < floors[lvl]:
                        admitted = False
                        break
                honest_attempts += 1
                if not admitted:
                    honest_refused += 1
            if admitted:
                cum_div[leaf] += t.divest(leaf, want)

        t.commit()
        hist_div.append(list(cum_div))
        c = t.concentration()
        if c is None:
            undefined += 1
        else:
            peak = max(peak, c)
            if t.concentration_exceeds():
                violations += 1

    return {"violations": violations, "undefined_rounds": undefined,
            "peak_concentration": peak,
            # MECHANISM CHECK: an arm that claims to spare cluster 0 must be
            # SHOWN to place nothing there. Registering a rule is not evidence
            # that it runs.
            "defectors_in_target_cluster":
                len([p for p in defectors if p // f == TARGET // f]),
            "n_defectors": len(defectors),
            # POST-HOC MEASURE, added after the 2x2 showed evenness rather
            # than sparing carries the effect. It is a MEASURE of the same
            # trajectories, not a decision rule -- no threshold reads it.
            "clusters_covered": len({p // f for p in defectors}),
            "cluster_coverage": F(len({p // f for p in defectors}),
                                  t.n_clusters),
            "honest_attempts": honest_attempts,
            "honest_refused": honest_refused}


def cell(d, f, delta, eps, k, arm, seeds=3, rounds=40) -> dict:
    acc = {"violations": 0, "undefined_rounds": 0, "honest_attempts": 0,
           "honest_refused": 0, "defectors_in_target_cluster": 0,
           "n_defectors": 0, "clusters_covered": 0}
    peak = F(0)
    for s in range(seeds):
        r = run_trial(d, f, delta, eps, k, arm, s, rounds)
        for key in acc:
            acc[key] = max(acc[key], r[key]) if key.startswith(
                ("defectors_in", "n_def", "clusters_cov")) \
                else acc[key] + r[key]
        peak = max(peak, r["peak_concentration"])
    acc["breached"] = acc["violations"] > 0
    acc["peak_concentration"] = peak
    # 0/0 IS NOT 0: with no honest attempts there is no refusal RATE.
    acc["honest_refusal"] = (acc["honest_refused"] / acc["honest_attempts"]
                             if acc["honest_attempts"] else None)
    return acc


def critical_k(d, f, delta, eps, arm, seeds=3, rounds=40) -> dict:
    """Smallest breaching k, or None. Doubling, bisection, FULL-RANGE check.

    COVERAGE: `None` is returned only after the arm's own maximum eligible k
    has been tested. R-M1 published four false INFEASIBLE verdicts from a
    stride that never covered its interval, and R-E repeated the species one
    route ago -- so the top of the range is tested explicitly, never inferred.
    """
    n = f ** d
    top = eligible(arm, n, f)
    curve = []
    hi = 1
    while hi < top:
        r = cell(d, f, delta, eps, hi, arm, seeds, rounds)
        curve.append((hi, r["violations"], float(r["peak_concentration"])))
        if r["breached"]:
            break
        hi *= 2
    else:
        hi = top
    if not cell(d, f, delta, eps, min(hi, top), arm, seeds, rounds)["breached"]:
        cap = cell(d, f, delta, eps, top, arm, seeds, rounds)
        curve.append((top, cap["violations"],
                      float(cap["peak_concentration"])))
        if not cap["breached"]:
            return {"k_star": None, "curve": curve, "eligible": top,
                    "peak_concentration": cap["peak_concentration"],
                    "note": f"no k in [1, {top}] breaches"}
        hi = top
    lo = max(1, hi // 2)
    while lo < hi:
        mid = (lo + hi) // 2
        if cell(d, f, delta, eps, mid, arm, seeds, rounds)["breached"]:
            hi = mid
        else:
            lo = mid + 1
    final = cell(d, f, delta, eps, lo, arm, seeds, rounds)
    return {"k_star": lo, "curve": curve, "eligible": top,
            "clusters_covered": final["clusters_covered"],
            "peak_concentration": final["peak_concentration"],
            "honest_refusal": final["honest_refusal"],
            "defectors_in_target_cluster":
                final["defectors_in_target_cluster"]}


__all__ = ["run_trial", "cell", "critical_k", "eligible", "_place",
           "RANDOM", "SPARE", "SPARE_EVEN", "CONCENTRATE", "EVEN_ALL",
           "TARGET",
           "SHED", "UNILATERAL"]
