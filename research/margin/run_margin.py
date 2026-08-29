"""R-M1 — the margin sweep.

Finds delta* = the smallest margin at which a local, stale admission check keeps
`concentration <= kappa` across every seed, and reports what that margin costs.

DELTA* IS FOUND BY SCANNING, NOT BISECTING. Bisection assumes violations are
monotone in delta and NOBODY HAS CHECKED THAT. The full coarse curve is recorded
so the assumption is testable; if it is non-monotone, every bisected result in
this route would be wrong and that is a finding rather than a nuisance. Scanning
returns the true smallest safe grid point either way.

Run:  ~/dev/marshal/.os/bin/python research/margin/run_margin.py
"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from env_margin import KAPPA, SCALE, U, box_floor, margin_ceiling        # noqa: E402
from trial import ADVERSARIAL, FIXED_COUNT, FIXED_FRACTION, HONEST, cell  # noqa: E402

COARSE = F(1, 40)
FINE = F(1, 200)            # the grid resolution g; decision rules use 2g
SEEDS, ROUNDS = 5, 40


def closed_form(m: int, delta_units: F) -> F:
    """PREREGISTRATION §2c:  delta* = D(M-1)k^2 / (U + D(M-1)k).

    On trial with everything else. Derived for a SINGLE admission per principal,
    so it is scored on n=1 only; with n agents the overshoot carries an extra
    (n-1) term the derivation does not cover, and fitting one would be tuning.
    """
    D = delta_units
    num = D * (m - 1) * KAPPA * KAPPA
    den = F(U, SCALE) + D * (m - 1) * KAPPA
    return num / den if den else F(0)


def scan(m, eps, activity, n) -> dict:
    """Full coarse curve, then refine between the last unsafe and first safe.

    REACHABILITY IS CHECKED FIRST AND UNREACHABLE IS NOT delta* = 0. If the
    attack cannot move the aggregate at delta = 0, there is no margin to find
    and reporting 0 would read as "no margin needed" -- the reassuring
    direction -- when the truth is that nothing was measured. It is also what
    produced a delta* of -0.0200 in the first run: with delta = 0 already safe,
    the refinement stepped BELOW zero into negative margin, which is not a
    weaker guard but a stronger one.
    """
    ceil_ = margin_ceiling(m)
    base = cell(m, F(0), eps, activity, ADVERSARIAL, n, SEEDS, ROUNDS)
    if base["safe"]:
        return {"delta_star": None, "curve": [(F(0), 0, base["max_other_caused"])],
                "ceiling": ceil_, "reachable": False,
                "note": "attack unreachable at delta=0; delta* undefined"}

    curve, coarse_hit = [(F(0), base["violations"], base["max_other_caused"])], None
    d = COARSE
    while d < ceil_:
        r = cell(m, d, eps, activity, ADVERSARIAL, n, SEEDS, ROUNDS)
        curve.append((d, r["violations"], r["max_other_caused"]))
        if r["safe"]:
            coarse_hit = d
            break
        d += COARSE

    if coarse_hit is None:
        return {"delta_star": None, "curve": curve, "ceiling": ceil_,
                "reachable": True,
                "note": "INFEASIBLE: no delta below the ceiling was safe"}

    # refine downward from the coarse hit, never below zero
    delta_star = coarse_hit
    d = max(F(0), coarse_hit - COARSE) + FINE
    while d < coarse_hit:
        if cell(m, d, eps, activity, ADVERSARIAL, n, SEEDS, ROUNDS)["safe"]:
            delta_star = d
            break
        d += FINE

    return {"delta_star": delta_star, "curve": curve, "ceiling": ceil_,
            "reachable": True}


def main() -> None:
    out: dict = {"kappa": str(KAPPA), "seeds": SEEDS, "rounds": ROUNDS,
                 "grid": str(FINE), "cells": []}

    print("R-M1 — margin sweep.  delta* = smallest margin with zero violations")
    print(f"kappa = {float(KAPPA)}, grid g = {float(FINE)}, "
          f"seeds = {SEEDS}, rounds = {ROUNDS}\n")

    for activity in (FIXED_FRACTION, FIXED_COUNT):
        print(f"=== activity = {activity} ===")
        print(f"{'M':>5s}{'eps':>5s}{'n':>3s}{'ceiling':>9s}{'delta*':>9s}"
              f"{'Delta':>8s}{'pred':>8s}{'L(0)':>9s}{'L(d*)':>9s}"
              f"{'floor_infl':>11s}{'hon_ref':>9s}{'reach':>7s}")
        print("-" * 96)
        for m in (2, 8, 64, 512):
            for eps in (1, 2, 4):
                for n in (1, 4):
                    s = scan(m, eps, activity, n)
                    ds, ceil_ = s["delta_star"], s["ceiling"]
                    base = cell(m, F(0), eps, activity, ADVERSARIAL, n,
                                SEEDS, ROUNDS)
                    D = F(base["max_other_caused"], SCALE)
                    pred = closed_form(m, D) if n == 1 else None

                    hr = l_star = infl = None
                    l0 = box_floor(m, F(0)) / SCALE
                    if ds is not None:
                        h = cell(m, ds, eps, activity, HONEST, n, SEEDS, ROUNDS)
                        hr = h["refusal_rate"]
                        l_star = box_floor(m, ds) / SCALE
                        infl = l_star / l0

                    rec = {"activity": activity, "M": m, "eps": eps, "n": n,
                           "ceiling": float(ceil_),
                           "delta_star": None if ds is None else float(ds),
                           "Delta": float(D),
                           "closed_form": None if pred is None else float(pred),
                           "floor_L0": l0, "floor_L_star": l_star,
                           "floor_inflation": infl,
                           "honest_refusal": hr,
                           "reachable": s["reachable"],
                           "note": s.get("note"),
                           "curve": [[float(a), b] for a, b, _ in s["curve"]]}
                    out["cells"].append(rec)

                    def f(x, w=9, p=4):
                        return f"{x:{w}.{p}f}" if x is not None else f"{'-':>{w}s}"
                    print(f"{m:5d}{eps:5d}{n:3d}{float(ceil_):9.4f}"
                          f"{f(None if ds is None else float(ds))}"
                          f"{f(float(D), 8)}"
                          f"{f(None if pred is None else float(pred), 8)}"
                          f"{f(l0)}{f(l_star)}{f(infl, 11, 2)}{f(hr)}"
                          f"{'yes' if s['reachable'] else 'NO':>7s}")
        print()

    (HERE / "margin_result.json").write_text(json.dumps(out, indent=2) + "\n")
    print("wrote margin_result.json")


if __name__ == "__main__":
    main()
