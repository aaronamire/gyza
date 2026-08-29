"""
PART A — corrected re-analysis of R10 Parts C and D.

Free: no new data, no simulation. Reads `breadth_grading/r10_result.json`
READ-ONLY and re-derives two verdicts whose PREREGISTERED RULES were
defective. Both defects were flagged in FINDINGS_R10.md itself; this
applies the corrections R10 could not apply to its own committed rules.

A1. Part C recorded DOES-NOT-COMPOSE while its own supplementary matrix
    contains a composing cell. The theta* selection rule was trivially
    satisfied for theta>=0.5 and selected theta*=1.0 — a guard admitting
    everything — so the mechanical COMPOSES firing was VACUOUS and the
    rule is INAPPLICABLE, not authoritative.

A2. Part D's TUNABLE rule demanded strict improvement on BOTH axes, which
    is the definition of not-a-frontier: a tradeoff cannot dominate
    itself. Re-evaluated as a Pareto question over EFFECTIVE throughput.
"""
from __future__ import annotations

import json
from pathlib import Path

R10 = Path(__file__).resolve().parent.parent / "breadth_grading" / "r10_result.json"

# Guards that admit everything: the unguarded baseline and the theta=1.0
# graded guard the defective theta* rule selected. A cell running one of
# these is not evidence about composition.
VACUOUS = {"G0", "G5(1.0)"}


def _load() -> dict:
    return json.loads(R10.read_text())


# ----------------------------------------------------------------------
# A1 — Part C
# ----------------------------------------------------------------------

def part_c(d: dict) -> dict:
    cells = list(d["part_c"]["cells"])
    supp = list(d["c_supplementary_non_preregistered"])
    for c in supp:
        c["_supplementary"] = True
    allc = cells + supp

    conc = [c for c in allc if c["mode"] == "concurrent"]
    ser = [c for c in allc if c["mode"] == "serialized"]

    # The control: serialized multi-agent must reproduce R9 (depth composes).
    ser_viol = sum(c["violations"] for c in ser)

    composing = [c for c in conc if c["violations"] == 0]
    nonvac_composing = [c for c in composing if c["guard"] not in VACUOUS]
    nonvac_conc = [c for c in conc if c["guard"] not in VACUOUS]

    return {
        "theta_star_selected": d["part_c"]["theta_star"],
        "theta_star_rule": "INAPPLICABLE — trivially satisfied for theta>=0.5, "
                           "selected a guard that admits everything",
        "n_cells_preregistered": len(cells),
        "n_cells_supplementary": len(supp),
        "serialized_cells": len(ser),
        "serialized_total_violations": ser_viol,
        "concurrent_cells": len(conc),
        "concurrent_nonvacuous_cells": len(nonvac_conc),
        "composing_cells_all": len(composing),
        "composing_cells_nonvacuous": len(nonvac_composing),
        "composing_configs": sorted(
            {(c["guard"], c["storage"], c["accounts"], c["n"])
             for c in nonvac_composing}),
        "violating_configs": sorted(
            {(c["guard"], c["storage"], c["accounts"], c["n"])
             for c in nonvac_conc if c["violations"] > 0}),
        "cells": allc,
    }


# ----------------------------------------------------------------------
# A2 — Part D
# ----------------------------------------------------------------------

def _pareto(points: list[dict]) -> list[dict]:
    """Non-dominated on (harm MIN, effective throughput MAX)."""
    out = []
    for p in points:
        dominated = any(
            q is not p
            and q["max_h_lost"] <= p["max_h_lost"]
            and q["effective_throughput"] >= p["effective_throughput"]
            and (q["max_h_lost"] < p["max_h_lost"]
                 or q["effective_throughput"] > p["effective_throughput"])
            for q in points)
        if not dominated:
            out.append(p)
    return sorted(out, key=lambda z: z["max_h_lost"])


def part_d(d: dict) -> dict:
    cells = d["part_d"]["cells"]
    res = {}
    for storage in ("mutable", "append-only"):
        pts = [c for c in cells if c["storage"] == storage]
        front = _pareto(pts)
        res[storage] = {
            "points": [{"k": c["k"], "harm": round(c["max_h_lost"], 6),
                        "nominal_throughput": round(c["throughput"], 4),
                        "effective_throughput": round(c["effective_throughput"], 4),
                        "rollbacks": c["rollbacks"],
                        "checkpoint_checks": c["checkpoint_checks"]}
                       for c in pts],
            "pareto_k": [c["k"] for c in front],
            "frontier_exists": len(front) >= 2,
        }
    k1 = [c for c in cells if c["k"] == 1]
    res["k1_degenerate"] = [
        {"storage": c["storage"], "rollbacks": f"{c['rollbacks']}/{c['rounds']}",
         "nominal_throughput": c["throughput"],
         "effective_throughput": round(c["effective_throughput"], 4)}
        for c in k1]
    # Is rollback effective under a mutable archive?
    res["rollback_under_mutable_archive"] = {
        "k1_harm_mutable": round(
            [c for c in k1 if c["storage"] == "mutable"][0]["max_h_lost"], 6),
        "k1_harm_append_only": round(
            [c for c in k1 if c["storage"] == "append-only"][0]["max_h_lost"], 6),
    }
    return res


def main() -> int:
    d = _load()
    c, dd = part_c(d), part_d(d)

    print("=" * 78)
    print("PART A1 — R10 PART C, CORRECTED")
    print("=" * 78)
    print(f"theta* selected by the defective rule : {c['theta_star_selected']}  "
          f"-> {c['theta_star_rule']}")
    print(f"\nCONTROL (depth): {c['serialized_cells']} serialized cells, "
          f"{c['serialized_total_violations']} total violations")
    print(f"concurrent cells {c['concurrent_cells']} "
          f"({c['concurrent_nonvacuous_cells']} non-vacuous); "
          f"composing {c['composing_cells_all']} "
          f"({c['composing_cells_nonvacuous']} non-vacuous)")

    print("\n--- CONCURRENT MATRIX (non-vacuous guards only) ---")
    hdr = f"{'guard':<10} {'N':>2} {'accounts':<12} {'storage':<12} {'viol':>4} {'thru':>6} {'maxH':>7} {'recov':>6}"
    print(hdr); print("-" * len(hdr))
    for cell in sorted([x for x in c["cells"]
                        if x["mode"] == "concurrent" and x["guard"] not in VACUOUS],
                       key=lambda z: (z["guard"], z["n"], z["accounts"], z["storage"])):
        print(f"{cell['guard']:<10} {cell['n']:>2} {cell['accounts']:<12} "
              f"{cell['storage']:<12} {cell['violations']:>4} "
              f"{cell['throughput']:>6.2f} {cell['max_h_lost']:>7.3f} "
              f"{str(cell['final_recoverable']):>6}")

    print(f"\nCOMPOSING non-vacuous configs (guard, storage, accounts, N):")
    for g in c["composing_configs"]:
        print("   ", g)
    print(f"VIOLATING non-vacuous configs: {len(c['violating_configs'])}")

    print("\n" + "=" * 78)
    print("PART A2 — R10 PART D, CORRECTED (EFFECTIVE throughput)")
    print("=" * 78)
    for storage in ("mutable", "append-only"):
        r = dd[storage]
        print(f"\n--- {storage} ---")
        print(f"{'k':>5} {'harm':>8} {'nominal':>8} {'EFFECTIVE':>10} {'rollbacks':>10}")
        for p in r["points"]:
            print(f"{str(p['k']):>5} {p['harm']:>8.4f} {p['nominal_throughput']:>8.2f} "
                  f"{p['effective_throughput']:>10.2f} {p['rollbacks']:>10}")
        print(f"  PARETO SET (k) : {r['pareto_k']}")
        print(f"  FRONTIER-EXISTS: {r['frontier_exists']}")

    print("\n  k=1 degenerate case:")
    for z in dd["k1_degenerate"]:
        print(f"    {z['storage']:<12} rollbacks {z['rollbacks']:>6}  "
              f"nominal {z['nominal_throughput']:.2f} -> EFFECTIVE "
              f"{z['effective_throughput']:.2f}")
    rb = dd["rollback_under_mutable_archive"]
    print(f"\n  rollback under mutable archive: k=1 harm {rb['k1_harm_mutable']:.4f} "
          f"vs append-only {rb['k1_harm_append_only']:.4f}")

    out = Path(__file__).parent / "part_a_result.json"
    out.write_text(json.dumps({"part_c": c, "part_d": dd}, indent=2))
    print(f"\nwrote {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
