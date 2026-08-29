"""R-D1 — the escalation budget. Derivation + sensitivity.

N <= H*A / [(1-p)(1-c)]

DERIVED, NOT MEASURED. This computes consequences of an inequality whose
assumptions are stated in PROGRAM.md §1.2. It establishes nothing empirical.

THE PROHIBITION FROM PROGRAM.md §1.3 IS HONOURED HERE: our measured p (over
claim types) and our measured harm coverage (over stateful action types) are
different populations, so this NEVER multiplies them. It sweeps the (p, c)
plane and reports where our measurements sit on ONE axis each, separately.
"""
from __future__ import annotations

MEASURED_P = 10 / 18          # PROOF-carried claim types, recomputed from the registry
MEASURED_HARM_COV = 2 / 15    # stateful action types moving a declared quantity
INTERIOR_FRAC = 7 / 19        # REVERSIBLE_INTERIOR share of the action vocabulary


def max_n(h: float, a: float, p: float, c: float) -> float:
    """Actions/time the system may process without exceeding review capacity."""
    slack = (1.0 - p) * (1.0 - c)
    return float("inf") if slack <= 0 else h * a / slack


def required_slack(n: float, h: float, a: float) -> float:
    """(1-p)(1-c) needed to sustain N."""
    return h * a / n


def main() -> None:
    H = 1e4          # human reviews/day -- a generous large-org assumption
    print("R-D1 — THE ESCALATION BUDGET      (derived; assumptions in PROGRAM.md §1.2)")
    print(f"human review capacity H = {H:,.0f}/day\n")

    print("1. WHAT EACH TARGET SCALE REQUIRES  (A = 1, one human decision per action)")
    print(f"   {'target N/day':>14s}  {'required (1-p)(1-c)':>20s}  {'i.e. combined coverage':>24s}")
    for n in (1e4, 1e6, 1e8, 1e9, 1e12):
        s = required_slack(n, H, 1.0)
        print(f"   {n:14,.0f}  {s:20.2e}  {1-s:>23.6%}")

    print("\n2. WHERE OUR MEASUREMENTS SIT — ONE AXIS AT A TIME (never multiplied)")
    print(f"   p (claim types, PROOF-carried)      = {MEASURED_P:.3f}"
          f"   -> (1-p) = {1-MEASURED_P:.3f}")
    print(f"   harm coverage (stateful actions)    = {MEASURED_HARM_COV:.3f}"
          f"   -> (1-c) = {1-MEASURED_HARM_COV:.3f}")
    print("   These are DIFFERENT POPULATIONS. The product is not computed here"
          " (artifact #17).")

    print("\n3. CEILING IF THE OTHER AXIS WERE PERFECT  (upper bounds, A = 1)")
    for label, p, c in (("p as measured, c = 1 (perfect containment)", MEASURED_P, 1.0),
                        ("c as measured, p = 1 (perfect verification)", 1.0, MEASURED_HARM_COV)):
        print(f"   {label:44s} -> N unbounded by THIS term")
    for label, p, c in (("p as measured, c = 0", MEASURED_P, 0.0),
                        ("p = 0,  c as measured", 0.0, MEASURED_HARM_COV)):
        print(f"   {label:44s} -> N <= {max_n(H,1.0,p,c):,.0f}/day")

    print("\n4. THE AMORTIZATION LEVER  (A = actions per human decision)")
    print(f"   {'A':>8s}  {'N/day at p=0.556, c=0.133':>28s}")
    for a in (1, 10, 100, 1e3, 1e4, 1e6):
        print(f"   {a:8,.0f}  {max_n(H,a,MEASURED_P,MEASURED_HARM_COV):28,.0f}")
    print("   (this cell DOES combine the two axes and is therefore ILLUSTRATIVE")
    print("    ONLY -- it assumes they were measured over one population, which")
    print("    they were not. Read the SHAPE, never the number.)")

    print("\n5. WHAT A GIVEN A BUYS AGAINST WHAT A BETTER H BUYS")
    base = max_n(H, 1.0, MEASURED_P, MEASURED_HARM_COV)
    print(f"   baseline (A=1, H=1e4)          : {base:,.0f}/day")
    print(f"   10x human capacity (H=1e5)     : {max_n(1e5,1.0,MEASURED_P,MEASURED_HARM_COV):,.0f}/day")
    print(f"   10x amortization  (A=10)       : {max_n(H,10,MEASURED_P,MEASURED_HARM_COV):,.0f}/day")
    print("   -> identical, as they must be: H and A enter as a product. The")
    print("      asymmetry is that H is bounded by hiring and A by the harm bound.")

    print("\n6. THE REVERSIBLE-INTERIOR LEVER")
    print(f"   {INTERIOR_FRAC:.1%} of action types are REVERSIBLE_INTERIOR, and ZERO have a")
    print("   per-action undo. An action moved inside raises c WITHOUT needing")
    print("   verification -- the only lever that does not pay the competence bound.")
    for c in (MEASURED_HARM_COV, 0.5, 0.9, 0.99):
        print(f"     c = {c:5.3f} -> N <= {max_n(H,1.0,MEASURED_P,c):>14,.0f}/day")


if __name__ == "__main__":
    main()
