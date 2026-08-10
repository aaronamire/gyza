"""Part B — the audit frontier at USER-SUPPLIED TEST PARAMETERS.

*** THE PARAMETERS BELOW ARE TEST VALUES FOR A BUILD-AND-TEST INSTANTIATION. ***
*** THEY ARE NOT DERIVED, NOT MEASURED, AND NOT RECOMMENDED FOR DEPLOYMENT.  ***

That banner is repeated in every table this script prints, because the most
likely failure mode of this artifact is that it reads as authoritative simply by
containing numbers. A frontier computed on chosen inputs describes the choice,
not the system.

WHAT IS MEASURED vs ASSUMED, per cell:
  q, f in-competence / out-of-competence  MEASURED (FINDINGS_R6.md:48-49), on a
      cross-model checker over a MATH/reasoning family -- a DIFFERENT population
      from Gyza's claims. Transfer is a JUDGEMENT.
  q for the EIGHT EGRESS types            **NOBODY HAS MEASURED IT.** Any egress
      cell uses an ASSUMED q and is marked ASSUMED.
  epsilon tiers, g/w, B                   TEST VALUES supplied by the user.

    ~/dev/marshal/.os/bin/python research/audit_economics/frontier_test_params.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

BANNER = "TEST VALUES — not derived, not measured, not for deployment"

# ---- MEASURED (committed source cited) ------------------------------------
MEASURED_Q_F = {
    "in-competence":      (0.818, 0.041, 433, "FINDINGS_R6.md:48 (6B cell-a)"),
    "out-of-competence":  (0.556, 0.444, 36,  "FINDINGS_R6.md:49 (6B cell-b)"),
}
# The calibrated model bounds out-of-competence detection by the ACTIONABLE EDGE
# J_out = TPR - FPR, not the raw TPR (MODEL.md:50), and sweeps it because n=36
# with a CI including zero.
J_OUT = MEASURED_Q_F["out-of-competence"][0] - MEASURED_Q_F["out-of-competence"][1]

# ---- TEST VALUES (user-supplied) ------------------------------------------
EPSILON_TIERS = {
    "reversible-by-a-third-party": 1e-2,
    "irreversible-but-recoverable": 1e-4,
    "irreversible-and-consequential": 1e-6,
}
GW_SWEEP = (5.0, 10.0, 20.0)
B_OVER_W = (10.0, 100.0, 1000.0)      # 100 is the stated starting probe


def required_rate(gw: float, q: float, b_over_w: float) -> float:
    """Deterrence: p >= g/(qB). With B = k*w this is (g/w)/(q*k)."""
    return gw / (q * b_over_w)


def participation_cap(f: float, b_over_w: float) -> float:
    """Honest agent stays iff p <= w/(fB) = 1/(f*k)."""
    return 1.0 / (f * b_over_w)


def main() -> None:
    print("=" * 78)
    print(f"  ***  {BANNER}  ***")
    print("=" * 78)

    print("\nB3 — THE MEASURED CONTRAST AT g/w = 10 (checked, not asserted)")
    print("-" * 78)
    rows = []
    for regime, (tpr, fpr, n, cite) in MEASURED_Q_F.items():
        lr = tpr / fpr
        rows.append((regime, lr, n, cite))
        print(f"  {regime:<20} LR = {tpr:.3f}/{fpr:.3f} = {lr:6.2f}   "
              f"{'CLEARS' if lr >= 10 else 'FAILS':<7} g/w=10   n={n}  [{cite}]")
    lr_cal = J_OUT / MEASURED_Q_F["out-of-competence"][1]
    print(f"  {'out (calibrated)':<20} LR = {J_OUT:.3f}/0.444 = {lr_cal:6.2f}   "
          f"{'CLEARS' if lr_cal >= 10 else 'FAILS':<7} g/w=10   [MODEL.md:50]")
    verdict = ("HOLDS" if rows[0][1] >= 10 > rows[1][1] else "DOES NOT HOLD")
    print(f"\n  PATTERN: in-competence clears, out-of-competence fails -> {verdict}")

    # ---- the frontier ------------------------------------------------------
    print("\n" + "=" * 78)
    print(f"B4 — REQUIRED AUDIT RATE p >= (g/w)/(q*(B/w))     [{BANNER}]")
    print("=" * 78)
    print("  M = q MEASURED (different population; transfer is a judgement)")
    print("  A = q ASSUMED  (NOBODY HAS MEASURED q FOR EGRESS)\n")
    qs = [("in-competence", MEASURED_Q_F["in-competence"][0],
           MEASURED_Q_F["in-competence"][1], "M"),
          ("out-of-competence", J_OUT, MEASURED_Q_F["out-of-competence"][1], "M"),
          ("EGRESS (assumed q=0.50)", 0.50, 0.10, "A"),
          ("EGRESS (assumed q=0.20)", 0.20, 0.10, "A")]

    grid = []
    print(f"  {'regime':<26}{'src':>4}{'B/w':>7}{'g/w':>6}"
          f"{'p_required':>12}{'p_cap':>10}  feasible?")
    for name, q, f, src in qs:
        for k in B_OVER_W:
            for gw in GW_SWEEP:
                p = required_rate(gw, q, k)
                cap = participation_cap(f, k)
                ok = p <= cap and p <= 1.0
                grid.append({"regime": name, "q_source": src, "B_over_w": k,
                             "gw": gw, "p_required": p, "p_cap": cap,
                             "feasible": ok})
                if k == 100.0:                      # the stated probe
                    print(f"  {name:<26}{src:>4}{k:>7.0f}{gw:>6.0f}"
                          f"{p:>12.4f}{cap:>10.4f}  "
                          f"{'YES' if ok else 'NO -- ' + ('p>1' if p > 1 else 'p>cap')}")

    print(f"\n  B IS THE DESIGNER'S LEVER (p_required scales as 1/B):")
    for name, q, f, src in qs[:2]:
        line = f"    {name:<22}{src:>3}  g/w=10:  "
        line += "  ".join(f"B={k:>5.0f}w -> p={required_rate(10.0, q, k):.4f}"
                          for k in B_OVER_W)
        print(line)

    # ---- epsilon tiers -----------------------------------------------------
    print("\n" + "=" * 78)
    print(f"B5 — THE EPSILON TIERS AND THE HUMAN-GATE BOUNDARY   [{BANNER}]")
    print("=" * 78)
    print("  R6 measured that epsilon(r) PLATEAUS at 0.219*e0 past r ~ 0.05 and")
    print("  that the residual is entirely out-of-competence + bond-capped")
    print("  undeterrable consequence 'a cheap checker cannot touch at any audit")
    print("  rate; the floor is set by the competence bound, not the budget'")
    print("  (FINDINGS_R6.md). So the reachable floor is a PROPERTY OF q, not of r.\n")
    # CONDITIONAL escape floor: given a lie IS attempted, it escapes with
    # probability (1 - p*q); at p = 1 that is (1 - q). This is NOT epsilon --
    # epsilon is an ABSOLUTE rate, and converting requires e0, the unaudited
    # baseline consequential-error rate. e0 IS ANOTHER UNSET PARAMETER, so the
    # honest form is to report the e0 each tier would require.
    print("  CONDITIONAL escape floor at p = 1, i.e. (1 - q) -- audit EVERY")
    print("  claim and you still miss what the checker cannot detect:")
    for name, q, _f, src in qs:
        print(f"    {name:<26}{src:>3}  (1-q) = {1.0 - q:.4f}")
    print("\n  Epsilon is an ABSOLUTE rate; (1-q) is CONDITIONAL on a lie being")
    print("  attempted. Converting needs e0, the unaudited baseline -- ANOTHER")
    print("  UNSET PARAMETER. R6 measured epsilon plateaus at 0.219*e0, so the")
    print("  reachable floor is 0.219*e0 REGARDLESS OF AUDIT RATE. Hence each")
    print("  tier implies a maximum e0:\n")
    tiers = []
    for tier, eps in EPSILON_TIERS.items():
        e0_max = eps / 0.219
        # A tier is audit-reachable only if the UNAUDITED system is already
        # better than e0_max -- and if it is, the audit is buying almost
        # nothing, which is itself the design signal.
        verdict = ("plausible" if e0_max >= 1e-3 else
                   "requires an already-near-perfect system -> HUMAN GATE")
        tiers.append({"tier": tier, "epsilon_TEST_VALUE": eps,
                      "max_e0_for_audit_to_reach": e0_max, "verdict": verdict})
        print(f"  {tier:<34} eps={eps:.0e}  needs e0 <= {e0_max:.2e}  {verdict}")

    (HERE / "frontier_test_params.json").write_text(json.dumps({
        "PARAMETER_STATUS": BANNER,
        "measured_q_f": {k: {"tpr": v[0], "fpr": v[1], "n": v[2], "cite": v[3]}
                         for k, v in MEASURED_Q_F.items()},
        "j_out_calibrated": J_OUT,
        "epsilon_tiers_TEST_VALUES": EPSILON_TIERS,
        "gw_sweep_TEST_VALUES": list(GW_SWEEP),
        "b_over_w_TEST_VALUES": list(B_OVER_W),
        "grid": grid,
        "tiers": tiers,
    }, indent=1))
    print(f"\nwrote {HERE / 'frontier_test_params.json'}")


if __name__ == "__main__":
    main()
