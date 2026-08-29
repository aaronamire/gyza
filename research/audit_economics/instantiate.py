"""Part B — instantiate Route 6's audit economics against the real vocabulary.

WHAT IS COMPUTED AND WHAT IS REFUSED. Route 6 derived
`LR = q/f >= g/w` as the feasibility condition. Two of its five parameters are
MEASURED in committed findings; three are business decisions nobody has set.
**No value is invented for the three.** The frontier is computed as a function
of the one ratio that actually matters, and the ratio is named as the user's.

THE BOND CANCELS. `PROPOSITIONS.md:295-303` proves feasibility is
`q/f >= g/w` with `B` dividing out of both sides. So B is needed to set the
audit PROBABILITY, never to decide whether a mechanism can exist. That reduces
"four business parameters" to ONE NUMBER the user must choose: g/w.

    ~/dev/marshal/.os/bin/python research/audit_economics/instantiate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

# MEASURED, cited to the committed source. Not restated from memory.
#   research/audit_mechanism/FINDINGS_R6.md:48-49
OPERATING_POINTS = {
    "in-competence": {
        "tpr": 0.818, "fpr": 0.041, "n": 433,
        "cite": "FINDINGS_R6.md:48 (6B cell-a)",
    },
    "out-of-competence": {
        "tpr": 0.556, "fpr": 0.444, "n": 36,
        "cite": "FINDINGS_R6.md:49 (6B cell-b)",
    },
}

PARAMETERS = [
    ("q", "detection probability given audit", "MEASURABLE",
     "0.818 in-competence / 0.556 out (FINDINGS_R6.md:48-49). NOTE the "
     "calibrated model uses q_out = J_out = 0.111, not the raw TPR "
     "(MODEL.md:50), because out-of-competence detection is bounded by the "
     "actionable edge."),
    ("f", "false-conviction rate", "MEASURABLE",
     "0.041 in-competence / 0.444 out (same source)."),
    ("g", "gain to an agent from a false claim", "BUSINESS DECISION",
     "What a lie is worth. Denominated in the same unit as w."),
    ("w", "honest profit per claim", "BUSINESS DECISION",
     "What honest work pays. Only the RATIO g/w enters feasibility."),
    ("B", "bond posted per claim", "BUSINESS DECISION",
     "CANCELS from the feasibility condition (PROPOSITIONS.md:303). Needed "
     "only to convert a feasible region into an audit probability p."),
]


def main() -> None:
    print("=" * 78)
    print("B1 — PARAMETER INVENTORY")
    print("=" * 78)
    for name, meaning, kind, note in PARAMETERS:
        print(f"  {name:<3} {kind:<18} {meaning}")
        print(f"      {note}")
    n_bus = sum(1 for p in PARAMETERS if p[2] == "BUSINESS DECISION")
    print(f"\n  MEASURABLE {5 - n_bus} / BUSINESS {n_bus}  — and because B "
          f"cancels, the user must choose exactly ONE number: g/w.")

    print("\n" + "=" * 78)
    print("B2/B3 — THE FEASIBILITY FRONTIER,  feasible iff  LR = q/f >= g/w")
    print("=" * 78)
    lrs = {}
    for regime, d in OPERATING_POINTS.items():
        lr = d["tpr"] / d["fpr"]
        lrs[regime] = lr
        print(f"  {regime:<20} TPR={d['tpr']:.3f} FPR={d['fpr']:.3f} "
              f"n={d['n']:<4} LR={lr:6.2f}   [{d['cite']}]")
    # The calibrated variant the model actually uses out-of-competence.
    j_out = OPERATING_POINTS["out-of-competence"]["tpr"] - \
        OPERATING_POINTS["out-of-competence"]["fpr"]
    lr_out_cal = j_out / OPERATING_POINTS["out-of-competence"]["fpr"]
    print(f"  {'out (calibrated)':<20} q=J_out={j_out:.3f}  "
          f"f={OPERATING_POINTS['out-of-competence']['fpr']:.3f}       "
          f"LR={lr_out_cal:6.2f}   [MODEL.md:50]")

    print(f"\n  {'g/w':>8}{'in-competence':>18}{'out (raw)':>14}{'out (calibrated)':>20}")
    for gw in (1.0, 1.25, 2.0, 5.0, 10.0, 19.95, 20.0, 50.0):
        row = f"  {gw:>8.2f}"
        for lr in (lrs["in-competence"], lrs["out-of-competence"], lr_out_cal):
            row += f"{('FEASIBLE' if lr >= gw else 'infeasible'):>18}" \
                if lr is lrs["in-competence"] else \
                f"{('FEASIBLE' if lr >= gw else 'infeasible'):>14}" \
                if lr is lrs["out-of-competence"] else \
                f"{('FEASIBLE' if lr >= gw else 'infeasible'):>20}"
        print(row)

    print("\n  IN WORDS: in-competence, a lie may be worth up to ~20x honest")
    print("  profit and the mechanism still works. Out-of-competence it must be")
    print("  worth barely more than honest work (1.25x raw, 0.25x calibrated)")
    print("  -- i.e. effectively no temptation is tolerable.")

    # ---- B4: the residue Part A leaves -----------------------------------
    cov = json.loads((ROOT / "research/reversibility/coverage.json").read_text())
    rows = cov["rows"]
    # AUTHORED MAPPING action type -> whether a governed verifier covers it.
    from gyza.verification.migration import governed_registry, load_attestations
    auth, _ = governed_registry(load_attestations())
    governed = set(auth.claim_types())
    covered_by = {
        "sign_envelope": "envelope_signature",
        "settle_credits": "ledger_entry_signatures",
        "grant_delegation": "delegation_attenuation",
        "external_send": "external_send_content",     # UNGOVERNED (fallback gap)
    }
    residue = []
    for r in rows:
        if r["class"] == "REVERSIBLE_INTERIOR":
            continue
        ct = covered_by.get(r["action"])
        if ct and ct in governed:
            continue
        residue.append(r)

    print("\n" + "=" * 78)
    print("B4 — THE RESIDUE THE AUDIT ECONOMICS ACTUALLY GOVERN")
    print("=" * 78)
    print(f"  action types total                {cov['n_action_types']}")
    print(f"  minus REVERSIBLE_INTERIOR        -{cov['by_type']['REVERSIBLE_INTERIOR']}")
    print(f"  minus covered by a GOVERNED verifier -"
          f"{sum(1 for r in rows if r['class'] != 'REVERSIBLE_INTERIOR' and covered_by.get(r['action']) in governed)}")
    print(f"  = RESIDUE                         {len(residue)}"
          f"   ({len(residue)/cov['n_action_types']:.4f} of the vocabulary)")
    for r in residue:
        print(f"      {r['action']:<24} {r['class']:<22} prod_sites={r['n_production']}")
    res_sites = sum(r["n_production"] for r in residue)
    print(f"\n  RESIDUE BY PRODUCTION CALL SITE: {res_sites} of "
          f"{cov['total_production_sites']} total")

    (HERE / "frontier.json").write_text(json.dumps({
        "operating_points": OPERATING_POINTS,
        "lr_in": lrs["in-competence"], "lr_out_raw": lrs["out-of-competence"],
        "lr_out_calibrated": lr_out_cal,
        "parameters": [{"name": p[0], "meaning": p[1], "kind": p[2],
                        "note": p[3]} for p in PARAMETERS],
        "residue_action_types": [r["action"] for r in residue],
        "residue_n": len(residue),
        "residue_fraction_of_vocabulary": round(len(residue) / cov["n_action_types"], 4),
        "residue_production_call_sites": res_sites,
        "total_production_call_sites": cov["total_production_sites"],
    }, indent=1))
    print(f"\nwrote {HERE / 'frontier.json'}")


if __name__ == "__main__":
    main()
