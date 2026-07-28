"""GATE 0b/0c — cache inventory, corrected base rates, credit gate."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data import (  # noqa: E402
    CF, MATH_MODELS, MBPP_MODELS, math_outcomes, mbpp_outcomes, pop_difficulty,
)

EST_CALLS = 3080
EST_COST_USD = 0.20


def main() -> int:
    report: dict = {"gate": "0b/0c"}
    print("=" * 72)
    print("GATE 0b — CACHE INVENTORY + CORRECTED BASE RATES")
    print("=" * 72)

    # ---- MBPP -------------------------------------------------------
    items, mb = mbpp_outcomes()
    print(f"\nMBPP  (correlated_failure/or_cache)  n_problems={len(items)} "
          f"n_models={len(mb)}")
    print(f"{'model':<45} {'n':>4} {'solved':>7} {'rate':>7}")
    mb_rows = {}
    for m in MBPP_MODELS:
        s = sum(1 for v in mb[m] if v)
        mb_rows[m] = {"n": len(mb[m]), "solved": s, "rate": round(s / len(mb[m]), 4)}
        print(f"{m:<45} {len(mb[m]):>4} {s:>7} {s/len(mb[m]):>7.3f}")
    report["mbpp"] = {"n_problems": len(items), "models": mb_rows}

    # ---- MATH -------------------------------------------------------
    mitems, ml, _ = math_outcomes()
    print(f"\nMATH  (route2_independence/route2_cache)  n_problems={len(mitems)} "
          f"n_models={len(ml)}")
    print("labels via consistency_defensibility/canonicalizer_v2.equal (Phase 8)")
    print(f"{'model':<45} {'n':>4} {'unres':>6} {'used':>5} {'solved':>7} {'rate':>7}")
    ml_rows = {}
    for m in MATH_MODELS:
        lab = ml[m]
        unres = sum(1 for v in lab if v is None)
        used = len(lab) - unres
        s = sum(1 for v in lab if v is True)
        ml_rows[m] = {"n": len(lab), "unresolved": unres, "used": used,
                      "solved": s, "rate": round(s / used, 4) if used else None}
        print(f"{m:<45} {len(lab):>4} {unres:>6} {used:>5} {s:>7} "
              f"{(s/used if used else float('nan')):>7.3f}")
    report["math"] = {"n_problems": len(mitems), "models": ml_rows}

    # ---- difficulty strata (preregistered field) ---------------------
    strata: dict[str, int] = {}
    for it in mitems:
        strata[it["difficulty"]] = strata.get(it["difficulty"], 0) + 1
    print(f"\nMATH difficulty strata (preregistered field): {strata}")
    report["math_strata"] = strata

    # ---- null sanity -------------------------------------------------
    pd_mb = [pop_difficulty(mb, q, MBPP_MODELS[0]) for q in range(len(items))]
    pd_ml = [pop_difficulty(ml, q, MATH_MODELS[0]) for q in range(len(mitems))]
    print(f"\npop_difficulty spot-check (leave-one-out, first model):")
    print(f"  MBPP distinct values={sorted({v for v in pd_mb if v is not None})}")
    print(f"  MATH None count={sum(1 for v in pd_ml if v is None)}")

    # ---- GATE 0c -----------------------------------------------------
    print("\n" + "=" * 72)
    print("GATE 0c — CREDIT GATE")
    print("=" * 72)
    key = [l for l in (CF / ".env").read_text().splitlines()
           if l.startswith("OPENROUTER")][0].split("=", 1)[1].strip()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": "Bearer " + key,
                 "User-Agent": "gyza-research/0.1"})
    c = json.loads(urllib.request.urlopen(req, timeout=60).read())["data"]
    bal = c["total_credits"] - c["total_usage"]
    print(f"  total_credits : ${c['total_credits']:.4f}")
    print(f"  total_usage   : ${c['total_usage']:.4f}")
    print(f"  BALANCE       : ${bal:.4f}")
    print(f"  estimate      : {EST_CALLS} calls @ max_tokens=50  ~= ${EST_COST_USD:.2f}")
    print(f"  gate (2x est) : ${2*EST_COST_USD:.2f}")
    ok = bal >= 2 * EST_COST_USD
    print(f"  VERDICT       : {'PASS' if ok else 'STOP — insufficient balance'}")
    report["credits"] = {"balance": round(bal, 4), "est_calls": EST_CALLS,
                         "est_cost_usd": EST_COST_USD, "pass": ok}

    (Path(__file__).parent / "gate0_report.json").write_text(
        json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
