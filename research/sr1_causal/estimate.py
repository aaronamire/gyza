"""SR-1 causal — POWER AND COST ESTIMATE. This is an ESTIMATE, not a measurement.

Every number this prints is arithmetic over ASSUMPTIONS, except the base rate,
which is MEASURED (research/corpus/FINDINGS_SR1.md, n=179). The assumptions are
listed with their 2x sensitivity, because an estimate whose total swings by an
order of magnitude under plausible variation is a guess with decoration.

    ~/dev/marshal/.os/bin/python research/sr1_causal/estimate.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---- MEASURED (committed source) ------------------------------------------
BASE_FAIL = 0.1173      # substantive FAIL base rate, FINDINGS_SR1.md (n=179)
FAIL_REVISITING = 0.1273
CONSERVING_PREVALENCE = 0.0782
OBS_RECORDS_NEEDED = 1150   # FINDINGS_SR1.md:167 -- 6.4x the corpus

# ---- ASSUMED (test values for the estimate) --------------------------------
# Token components. Each is a GUESS pending the pilot; the point of listing them
# separately is that the pilot can measure each one independently.
ASSUMPTIONS = {
    "tok_decompose": (3_000, "tokens to produce one decomposition (prompt+output)"),
    "tok_subtask": (12_000, "tokens to execute ONE subtask, incl. context reload"),
    "n_subtask_conserving": (3.0, "subtasks per decomposition, CONSERVING arm "
                                  "(MEASURED-ish: 11/14 conserving were depth 3)"),
    "n_subtask_revisiting": (8.0, "subtasks per decomposition, REVISITING arm "
                                  "(MEASURED: corpus mean 8.0, median 5)"),
    "retry_rate": (0.25, "fraction of subtasks needing one retry"),
    "usd_per_1k_tok": (0.009, "blended in/out price at a frontier tier"),
}


def n_per_arm(p1: float, p2: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Two-proportion, two-sided. Standard normal approximation."""
    z_a = 1.959963985                       # z_{alpha/2}, alpha=0.05
    z_b = 0.8416212336                      # z_beta, power=0.80
    pbar = (p1 + p2) / 2
    a = z_a * math.sqrt(2 * pbar * (1 - pbar))
    b = z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return math.ceil(((a + b) ** 2) / ((p1 - p2) ** 2))


def cost_per_task(arm: str, a: dict) -> float:
    n_sub = a[f"n_subtask_{arm}"]
    tok = a["tok_decompose"] + n_sub * a["tok_subtask"] * (1 + a["retry_rate"])
    return tok / 1000.0 * a["usd_per_1k_tok"]


def main() -> None:
    a = {k: v[0] for k, v in ASSUMPTIONS.items()}

    print("=" * 78)
    print("A5 — POWER.  base rate MEASURED at 0.1173 (FINDINGS_SR1.md, n=179)")
    print("=" * 78)
    print(f"  {'effect (abs)':>14}{'p_control':>11}{'p_treat':>9}{'n/arm':>8}"
          f"{'2 arms':>9}{'3 arms':>9}")
    rows = []
    for eff in (0.03, 0.05, 0.08, 0.10, 0.12):
        p1, p2 = FAIL_REVISITING, max(FAIL_REVISITING - eff, 0.001)
        n = n_per_arm(p1, p2)
        rows.append({"effect": eff, "n_per_arm": n, "n_2arm": 2 * n, "n_3arm": 3 * n})
        print(f"  {eff:>14.2f}{p1:>11.4f}{p2:>9.4f}{n:>8}{2*n:>9}{3*n:>9}")

    print("\n  EFFECT SIZE POWERED FOR: 0.08 absolute (12.7% -> 4.7% failure).")
    print("  WHY THAT SIZE: below ~5pp the decision does not move -- the")
    print("  architectural principle already mandates partitioning for")
    print("  CONTAINMENT reasons (blind channels, frame alignment), so a small")
    print("  outcome penalty would not overturn it and a small benefit would")
    print("  not be why it was adopted. An effect too small to change the")
    print("  build is not worth measuring at any n.")

    n_star = n_per_arm(FAIL_REVISITING, FAIL_REVISITING - 0.08)
    print(f"\n  => {n_star} tasks per arm, 2 arms = {2*n_star} executions.")

    print("\n" + "=" * 78)
    print("B — COST MODEL, from components.  ALL COMPONENTS ARE ASSUMED.")
    print("=" * 78)
    for k, (v, why) in ASSUMPTIONS.items():
        print(f"  {k:<26}{v:>10}   {why}")

    c_cons = cost_per_task("conserving", a)
    c_rev = cost_per_task("revisiting", a)
    print(f"\n  cost/task CONSERVING (n_sub={a['n_subtask_conserving']}): ${c_cons:.2f}")
    print(f"  cost/task REVISITING (n_sub={a['n_subtask_revisiting']}): ${c_rev:.2f}")
    total = n_star * (c_cons + c_rev)
    print(f"  TOTAL at {n_star}/arm, 2 arms: ${total:,.0f}")

    print("\n  B2 — SENSITIVITY: each component doubled, alone")
    print(f"  {'component doubled':<26}{'total':>12}{'x baseline':>12}")
    sens = []
    for k in ASSUMPTIONS:
        a2 = dict(a); a2[k] = a[k] * 2
        t2 = n_star * (cost_per_task("conserving", a2) + cost_per_task("revisiting", a2))
        sens.append((k, t2, t2 / total))
        print(f"  {k:<26}{t2:>12,.0f}{t2/total:>12.2f}")
    worst = max(sens, key=lambda x: x[2])
    print(f"\n  WIDTH IS DRIVEN BY: {worst[0]} ({worst[2]:.2f}x when doubled).")

    lo = n_star * (cost_per_task("conserving", {**a, "tok_subtask": a["tok_subtask"]/2})
                   + cost_per_task("revisiting", {**a, "tok_subtask": a["tok_subtask"]/2}))
    hi = n_star * (cost_per_task("conserving", {**a, "tok_subtask": a["tok_subtask"]*2})
                   + cost_per_task("revisiting", {**a, "tok_subtask": a["tok_subtask"]*2}))
    print(f"\n  B4 — RANGE (tok_subtask varied 0.5x..2x): ${lo:,.0f} .. ${hi:,.0f}")

    print("\n" + "=" * 78)
    print("C — THE PILOT (NOT RUN; cost reported for the user's gate)")
    print("=" * 78)
    # To bound a mean within +/-25% at 95% with CV ~ 0.8 (heavy-tailed token
    # counts): n = (1.96*CV/0.25)^2
    cv = 0.8
    n_pilot = math.ceil((1.96 * cv / 0.25) ** 2)
    pilot_cost = n_pilot * (c_cons + c_rev) / 2
    print(f"  n needed to bound mean tokens within +/-25% at 95%, CV=0.8: "
          f"{n_pilot} per arm")
    print(f"  PILOT COST (both arms, {n_pilot} tasks each): ${pilot_cost*2:,.0f}")
    print(f"  as a fraction of the full experiment: {pilot_cost*2/total:.1%}")

    json.dump({
        "_status": "ESTIMATE, not a measurement. Components are ASSUMED.",
        "measured": {"base_fail": BASE_FAIL, "fail_revisiting": FAIL_REVISITING,
                     "conserving_prevalence": CONSERVING_PREVALENCE,
                     "obs_records_needed": OBS_RECORDS_NEEDED,
                     "source": "research/corpus/FINDINGS_SR1.md"},
        "assumptions": {k: {"value": v, "meaning": w}
                        for k, (v, w) in ASSUMPTIONS.items()},
        "power": rows, "n_per_arm_at_0.08": n_star,
        "cost_total_usd": round(total),
        "cost_range_usd": [round(lo), round(hi)],
        "sensitivity": [{"component": k, "total": round(t), "ratio": round(r, 2)}
                        for k, t, r in sens],
        "pilot": {"n_per_arm": n_pilot, "cost_usd": round(pilot_cost * 2)},
    }, open(HERE / "estimate.json", "w"), indent=1)
    print(f"\nwrote {HERE / 'estimate.json'}")


if __name__ == "__main__":
    main()
