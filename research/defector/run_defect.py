"""A2 — how many defectors does a cross-principal aggregate bound survive?

delta* is TAKEN from `research/margin/margin_result.json`, not re-derived: this
route varies compliance, not margin.

Run:  ~/dev/marshal/.os/bin/python research/defector/run_defect.py
"""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "margin"))

from defect import BOTH, HOARD, SHED, SKEW, cell, critical_k   # noqa: E402
from env_margin import KAPPA, SCALE, box_floor                 # noqa: E402

EPS, SEEDS, ROUNDS = 1, 5, 40
SCALES = (8, 64, 512)


def _delta_star() -> dict[int, F]:
    """R-M1's measured margins, read from its result file rather than retyped.
    A retyped constant is a second frame free to drift from the measurement."""
    data = json.loads((HERE.parent / "margin" / "margin_result.json").read_text())
    out: dict[int, F] = {}
    for c in data["cells"]:
        if (c["activity"] == "FIXED_FRACTION" and c["n"] == 1
                and c["eps"] == EPS and c["delta_star"] is not None):
            out[c["M"]] = F(c["delta_star"]).limit_denominator(1000)
    return out


def main() -> None:
    D = _delta_star()
    out: dict = {"kappa": str(KAPPA), "eps": EPS, "seeds": SEEDS,
                 "rounds": ROUNDS, "delta_star": {str(k): float(v)
                                                  for k, v in D.items()},
                 "cells": []}

    print("A2 — defectors against R-M1's measured margin "
          f"(eps={EPS}, n=1, FIXED_FRACTION, kappa={float(KAPPA)})\n")

    # ---- the control, first. If this is not zero, nothing else is readable.
    print("CONTROL (P-A2e): k=0 must be ZERO violations — this is delta* restated")
    for m in SCALES:
        r = cell(m, D[m], EPS, 0, SHED, SEEDS, ROUNDS)
        print(f"  M={m:4d}  delta*={float(D[m]):.3f}  violations={r['violations']}"
              f"   pool_left={r['pool_remaining']:.3f}")
        assert r["violations"] == 0, "control failed; no other cell is readable"

    print(f"\n{'mode':>8s}{'M':>6s}{'k*':>6s}{'phi*':>8s}{'L(0)':>9s}"
          f"{'L(d*)':>9s}{'adv@k*':>10s}{'pool@k*':>10s}")
    print("-" * 66)
    for mode in (SHED, SKEW, BOTH, HOARD):
        for m in SCALES:
            d = D[m]
            r = critical_k(m, d, EPS, mode, SEEDS, ROUNDS)
            ks = r["k_star"]
            adv = pool = None
            if ks is not None:
                c = cell(m, d, EPS, ks, mode, SEEDS, ROUNDS)
                adv, pool = c["defector_advantage"], c["pool_remaining"]
            out["cells"].append({
                "mode": mode, "M": m, "k_star": ks,
                "phi_star": r["phi_star"], "delta_star": float(d),
                "defector_advantage": adv, "pool_remaining": pool,
                "curve": [[k, v] for k, v, _ in r["curve"][:6]]})

            def f(x, w=9, p=4):
                return f"{x:{w}.{p}f}" if x is not None else f"{'-':>{w}s}"
            print(f"{mode:>8s}{m:6d}{(ks if ks is not None else -1):6d}"
                  f"{f(r['phi_star'], 8)}{box_floor(m, F(0)) / SCALE:9.4f}"
                  f"{box_floor(m, d) / SCALE:9.4f}{f(adv, 10)}{f(pool, 10)}")

    (HERE / "defect_result.json").write_text(json.dumps(out, indent=2) + "\n")
    print("\nwrote defect_result.json")


if __name__ == "__main__":
    main()
