"""E1, second pass — RESERVATION at M >> 3, in an arena that carries the
mechanism its PARTIAL verdict was actually about.

Pass 1 (`run_e1.py`) measured 0.0000 at every M and every n. Diagnosed as
DEFINITIONAL: with no other-caused change, reservation's round-open origin is
never stale, so the budget is exact and the box theorem does the rest. Recorded
as a null.

Run:  ~/dev/marshal/.os/bin/python research/escrow/run_e1_coupled.py
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from coupled_arena import KAPPA, run                            # noqa: E402

SCALES = (2, 4, 8, 16, 32, 64, 128, 256, 512)
ROUNDS, SEEDS = 40, 20
ARMS = ("naive", "reserved", "partitioned")


def rate(m: int, disc: str, n: int) -> tuple[float, float, float]:
    v = t = bf = 0
    peak = 0.0
    for s in range(SEEDS):
        r = run(m, disc, n_agents=n, rounds=ROUNDS, seed=s)
        v += r["violations"]
        bf += r["below_floor"]
        t += r["rounds"]
        peak = max(peak, r["peak_concentration"])
    return v / t, bf / t, peak


def main() -> None:
    out: dict = {"kappa": KAPPA, "rounds": ROUNDS, "seeds": SEEDS, "rates": {}}
    for n in (1, 4):
        print(f"\n=== agents per principal n = {n}   (kappa = {KAPPA}) ===")
        print(f"{'M':>5s}" + "".join(f"{a:>14s}" for a in ARMS)
              + f"{'res below-L':>14s}")
        print("-" * 76)
        for m in SCALES:
            row, cells = {}, []
            res_bf = 0.0
            for a in ARMS:
                r, bf, pk = rate(m, a, n)
                row[a] = {"violation_rate": r, "below_floor_rate": bf,
                          "peak": pk}
                cells.append(r)
                if a == "reserved":
                    res_bf = bf
            out["rates"].setdefault(str(n), {})[str(m)] = row
            print(f"{m:5d}" + "".join(f"{c:14.4f}" for c in cells)
                  + f"{res_bf:14.4f}")

    print("\n" + "=" * 76)
    print("E1-HOLDS: reserved rate at M in {8,64,512} within 2x of its M=2 value")
    for n in ("1", "4"):
        g = out["rates"][n]
        base = g["2"]["reserved"]["violation_rate"]
        vals = {m: g[m]["reserved"]["violation_rate"] for m in ("8", "64", "512")}
        if base == 0.0:
            grew = any(v > 0 for v in vals.values())
            verdict = "UNDEFINED (base 0.0)" + (
                "  -- larger M are NOT zero, so the rate GREW FROM NOTHING"
                if grew else "  -- all zero")
        else:
            ok = all(abs(v - base) <= base for v in vals.values())
            verdict = f"{'HOLDS' if ok else 'REFUTED'} (base {base:.4f})"
        print(f"  n={n}: {vals} -> {verdict}")

    (HERE / "e1_coupled_result.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
