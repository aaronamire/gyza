"""R-H1 — the hierarchy sweep.

Run:  ~/dev/marshal/.os/bin/python research/hierarchy/run_tree.py
"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "margin"))

from env_margin import SCALE                                   # noqa: E402
from tree import (                                             # noqa: E402
    KAPPA, box_floor_at, ceiling_at, cell, kappa_level, max_fan_in,
)

TOPO = ((1, 512), (2, 23), (3, 8))
COARSE, FINE = F(1, 40), F(1, 200)
SEEDS, ROUNDS = 5, 40


def scan(d, f, eps) -> dict:
    """Reachability FIRST. UNREACHABLE is not delta* = 0 -- conflating them
    produced a delta* of -0.0200 in R-M1, and reporting 0 would read as
    'no margin needed' when the truth is that nothing was measured."""
    kl = kappa_level(d)
    ceil_ = ceiling_at(f, kl)
    base = cell(d, f, F(0), eps, SEEDS, ROUNDS)
    if base["safe"]:
        return {"delta_star": None, "reachable": False, "ceiling": ceil_,
                "curve": [(F(0), 0)]}

    curve = [(F(0), base["violations"])]
    hit = None
    dd = COARSE
    while dd < ceil_:
        r = cell(d, f, dd, eps, SEEDS, ROUNDS)
        curve.append((dd, r["violations"]))
        if r["safe"]:
            hit = dd
            break
        dd += COARSE
    if hit is None:
        # THE COARSE GRID DOES NOT REACH THE CEILING, AND THAT IS HOW R-M1
        # PUBLISHED FOUR FALSE "INFEASIBLE" VERDICTS.
        #
        # Stepping by COARSE from 0, the last point below a 0.5980 ceiling is
        # 0.575; the next step lands at 0.600, the loop exits, and the cell is
        # declared INFEASIBLE without (0.575, 0.598) ever being tested. Every
        # R-M1 cell so labelled is in fact safe at 0.590-0.595.
        #
        # A verdict of "no margin works" must be established over the WHOLE
        # admissible range, not over the part a stride happened to land on.
        dd = ceil_ - FINE
        while dd > (curve[-1][0] if curve else F(0)):
            if cell(d, f, dd, eps, SEEDS, ROUNDS)["safe"]:
                hit = dd
                break
            dd -= FINE
        if hit is None:
            return {"delta_star": None, "reachable": True, "ceiling": ceil_,
                    "curve": curve,
                    "note": "INFEASIBLE over the whole admissible range"}
        return {"delta_star": hit, "reachable": True, "ceiling": ceil_,
                "curve": curve, "note": "found only near the ceiling"}

    ds = hit
    dd = max(F(0), hit - COARSE) + FINE
    while dd < hit:
        if cell(d, f, dd, eps, SEEDS, ROUNDS)["safe"]:
            ds = dd
            break
        dd += FINE
    return {"delta_star": ds, "reachable": True, "ceiling": ceil_,
            "curve": curve}


def main() -> None:
    out: dict = {"kappa": str(KAPPA), "seeds": SEEDS, "rounds": ROUNDS,
                 "grid": str(FINE), "cells": []}
    print("R-H1 — hierarchy.  delta* per level, M ~ 512 at every depth\n")
    print(f"{'d':>3s}{'f':>5s}{'M':>7s}{'kappa_l':>9s}{'ceiling':>9s}"
          f"{'fan_in':>8s}{'eps':>5s}{'delta*':>9s}{'L(d*)':>9s}"
          f"{'below_box':>11s}{'reach':>7s}")
    print("-" * 92)
    for d, f in TOPO:
        kl = kappa_level(d)
        for eps in (1, 2, 4):
            s = scan(d, f, eps)
            ds = s["delta_star"]
            lstar = bx = None
            if ds is not None:
                lstar = box_floor_at(f, kl, ds) / SCALE
                bx = cell(d, f, ds, eps, SEEDS, ROUNDS)["below_box"]
            out["cells"].append({
                "d": d, "f": f, "M": f ** d, "eps": eps,
                "kappa_l": float(kl), "ceiling": float(s["ceiling"]),
                "delta_star": None if ds is None else float(ds),
                "floor_at_delta_star": lstar, "below_box": bx,
                "max_fan_in": max_fan_in(d, f),
                "reachable": s["reachable"], "note": s.get("note"),
                "curve": [[float(a), b] for a, b in s["curve"]]})

            def fmt(x, w=9, p=4):
                return f"{x:{w}.{p}f}" if x is not None else f"{'-':>{w}s}"
            print(f"{d:3d}{f:5d}{f**d:7d}{float(kl):9.4f}"
                  f"{float(s['ceiling']):9.4f}{max_fan_in(d, f):8d}{eps:5d}"
                  f"{fmt(None if ds is None else float(ds))}{fmt(lstar)}"
                  f"{(str(bx) if bx is not None else '-'):>11s}"
                  f"{'yes' if s['reachable'] else 'NO':>7s}")

    print("\n" + "=" * 92)
    by = {(c["d"], c["eps"]): c["delta_star"] for c in out["cells"]}
    g = float(FINE)
    print("H-COMPOUNDS / H-HELPS: delta*(d=3) vs delta*(d=1) + 2g, same eps")
    for eps in (1, 2, 4):
        a, b = by.get((1, eps)), by.get((3, eps))
        if a is None or b is None:
            print(f"  eps={eps}: one side undefined ({a}, {b}) -> UNSCORABLE")
            continue
        v = ("H-COMPOUNDS" if b > a + 2 * g
             else "H-HELPS" if b < a - 2 * g else "H-NEUTRAL")
        print(f"  eps={eps}: d=1 {a:.3f}  d=3 {b:.3f}   -> {v}")

    print("\nP-H1a: does depth behave like d x eps at d=1?")
    for d in (2, 3):
        for eps in (1, 2):
            got, pred = by.get((d, eps)), by.get((1, d * eps))
            print(f"  d={d} eps={eps}: measured {got}   "
                  f"flat-at-{d*eps}x {pred}")

    (HERE / "tree_result.json").write_text(json.dumps(out, indent=2) + "\n")
    print("\nwrote tree_result.json")


if __name__ == "__main__":
    main()
