"""R-N — find eps*, the staleness horizon.

eps* is the largest eps for which a feasible delta exists ANYWHERE below the
ceiling. It is defined by an ABSENCE, which makes this exactly the route R-M1's
scan defect would poison: that route published four false INFEASIBLE verdicts
because a stride never covered the ceiling region. Every negative here is
established by refining DOWN from the ceiling first, then filling the interior.

Run:  ~/dev/marshal/.os/bin/python research/horizon/run_horizon.py
"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hierarchy"))
sys.path.insert(0, str(HERE.parent / "margin"))

from tree import ceiling_at, cell, kappa_level                  # noqa: E402

COARSE, FINE = F(1, 40), F(1, 200)
SEEDS, ROUNDS = 5, 40
TOPO = {"flat d=1 f=512": (1, 512), "tree d=3 f=8": (3, 8)}
EPSILONS = (1, 2, 4, 8, 16, 32)


def feasible_delta(d: int, f: int, eps: int) -> tuple[F | None, dict]:
    """Smallest safe delta below the ceiling, or None over the WHOLE range.

    Order matters and is the point: the ceiling region is swept FIRST, because
    that is where a feasible point hides when the interior is hopeless, and it
    is the region R-M1's stride skipped.
    """
    kl = kappa_level(d)
    ceil_ = ceiling_at(f, kl)
    info: dict = {"ceiling": float(ceil_)}

    base = cell(d, f, F(0), eps, SEEDS, ROUNDS)
    info["reachable"] = not base["safe"]
    if base["safe"]:
        # UNREACHABLE is not a horizon: the attack could not move the aggregate,
        # so nothing was measured about margin. Conflating the two is the defect
        # R-B walked into one route after recording it.
        return F(0), info

    # 1. ceiling-down, fine grid
    d_ = ceil_ - FINE
    best = None
    steps = 0
    while d_ > 0 and steps < 40:
        if cell(d, f, d_, eps, SEEDS, ROUNDS)["safe"]:
            best = d_
        else:
            break
        d_ -= FINE
        steps += 1
    if best is None:
        # nothing safe even adjacent to the ceiling -> sweep the interior to be
        # certain, rather than inferring absence from one probe
        d_ = COARSE
        while d_ < ceil_:
            if cell(d, f, d_, eps, SEEDS, ROUNDS)["safe"]:
                best = d_
                break
            d_ += COARSE
        info["swept_interior"] = True
        return best, info

    # 2. walk DOWN from the highest known-safe point to find the true minimum
    lo = best
    d_ = best - FINE
    while d_ > 0:
        if not cell(d, f, d_, eps, SEEDS, ROUNDS)["safe"]:
            break
        lo = d_
        d_ -= FINE
    return lo, info


def main() -> None:
    out: dict = {"seeds": SEEDS, "rounds": ROUNDS, "grid": str(FINE),
                 "cells": []}
    print("R-N — the staleness horizon.  eps* = largest eps with ANY feasible "
          "delta\n")
    print(f"{'topology':>18s}{'eps':>5s}{'ceiling':>9s}{'delta*':>9s}"
          f"{'consumed':>10s}{'reach':>7s}")
    print("-" * 60)
    horizon: dict[str, int | None] = {}
    for name, (d, f) in TOPO.items():
        horizon[name] = None
        for eps in EPSILONS:
            ds, info = feasible_delta(d, f, eps)
            consumed = (float(ds) / info["ceiling"]) if ds is not None else None
            out["cells"].append({
                "topology": name, "d": d, "f": f, "eps": eps,
                "ceiling": info["ceiling"],
                "delta_star": None if ds is None else float(ds),
                "margin_consumed": consumed,
                "reachable": info["reachable"]})
            fmt = (f"{float(ds):9.4f}" if ds is not None else f"{'NONE':>9s}")
            cf = (f"{consumed:10.4f}" if consumed is not None
                  else f"{'-':>10s}")
            print(f"{name:>18s}{eps:5d}{info['ceiling']:9.4f}{fmt}{cf}"
                  f"{('yes' if info['reachable'] else 'NO'):>7s}")
            if ds is None:
                print(f"{'':>18s}      ^^ no feasible margin: eps* = "
                      f"{horizon[name]}")
                break
            horizon[name] = eps
    out["horizon"] = horizon

    print("\n" + "=" * 60)
    flat, tree = horizon["flat d=1 f=512"], horizon["tree d=3 f=8"]
    print(f"eps*(flat) = {flat}    eps*(tree) = {tree}")
    if flat and tree:
        print(f"HORIZON-MOVES (tree >= 4x flat): {tree >= 4 * flat}")
    print(f"HORIZON-FINITE (flat has a horizon <= {EPSILONS[-1]}): "
          f"{flat is not None and flat < EPSILONS[-1]}")

    (HERE / "horizon_result.json").write_text(json.dumps(out, indent=2) + "\n")
    print("\nwrote horizon_result.json")


if __name__ == "__main__":
    main()
