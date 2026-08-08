"""A1/A5 -- adversarial re-reading of the 98 judgement calls. AUTHORED.

For each judgement call the ADVERSARIAL CASE was written FIRST (the `adv`
string), then the verdict decided. The bar is not "could this be EXOGENOUS"
-- almost anything could under a loose reading. The bar is the frozen
criterion applied honestly: does Q2 fail AND Q3 fail, i.e. is there genuinely
no parameterisation that resolves the referent to repo-plus-test-suite state
without acquiring an outside fact?

A1 direction: toward EXOGENOUS/CONTESTED -- the direction that would overturn
FAVOURABLE.
A5 direction: the reverse, on the 23 EXOGENOUS and 12 CONTESTED, because
reporting only the direction that could hurt the verdict would be selective
stressing.

The criterion is NOT tuned. Where a flip happens it is because the ORIGINAL
application was wrong on that claim, not because the rule changed.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from classify import CLS  # noqa: E402

# A1 -- flips found by adversarial re-reading. index: (new_det, category, adv)
# Only claims whose classification CHANGED are listed; every other judgement
# call was re-argued and HELD.
A1_FLIPS: dict[int, tuple[str, str, str]] = {
    # --- flips that MOVE f (assertive -> EXOGENOUS/CONTESTED) ---
    19:  ("X", "population-of-practice",
          "'often mask' quantifies over real models/datasets, not over anything the repo holds"),
    33:  ("X", "external-referent",
          "'outdated' is relative to matplotlib's CURRENT docs -- a live external page"),
    47:  ("T", "quality-judgement",
          "'simplifies internal code' names no metric and two competent readers could disagree"),
    59:  ("T", "quality-judgement",
          "'difficult to understand' is difficulty FOR SOMEONE; no procedure settles it"),
    82:  ("X", "security-reachability",
          "'not exercisable by untrusted data' is a claim about real-world input distributions"),
    103: ("X", "population-of-practice",
          "'often suboptimal' quantifies over datasets in the world, not held ones"),
    112: ("X", "hardware-dependent",
          "'better for GPU devices' depends on which GPU; no such device is held"),
    124: ("T", "quality-judgement",
          "'the amount of new work is meaningful' names no threshold"),
    146: ("X", "user-expectation",
          "'different from the user's expectations' has its referent in users' heads"),
    147: ("X", "user-expectation",
          "'misunderstood by users' is a claim about users, not about the matrix"),
    161: ("T", "expressive",
          "'I'm not sure if this is a problem' -- an epistemic state, not truth-apt as stated"),
    183: ("X", "user-population",
          "bundles a checkable CI failure with 'negatively impacting ALL USERS'; the "
          "conservative direction binds on the unresolvable conjunct"),
    187: ("T", "quality-judgement",
          "'the warning is quite vague' is a judgement about prose quality"),
    211: ("X", "hardware-dependent",
          "'performance degradation on those architectures' needs the architectures"),
    # --- flips that do NOT move f (INTERNAL -> UNDERDETERMINED) ---
    48:  ("U", "unbuilt-artifact",
          "'NW can make code faster' predicts the speed of code that does not exist yet"),
    104: ("U", "unnamed-criterion",
          "'the optimal number of bins' -- the optimality criterion is in a cited paper, "
          "not in the claim"),
    135: ("U", "unbuilt-artifact",
          "'would provide separate and more explicit control' describes an unbuilt API"),
    163: ("U", "unnamed-referent",
          "'I am now getting this error' -- the claim does not name the error"),
    207: ("U", "no-threshold",
          "'significant Python-level overhead' names no threshold"),
}

# A5 -- the reverse direction. Of the 23 EXOGENOUS and 12 CONTESTED, which
# survive an argument that they are merely UNRESOLVED (i.e. UNDERDETERMINED)?
# Q4 is a CATCH-ALL, so EXOGENOUS absorbed anything unresolved and is an
# UPPER BOUND; this quantifies how much of it is genuinely exogenous.
A5_FLIPS: dict[int, tuple[str, str, str]] = {
    4:   ("U", "resolvable-by-naming",
          "'the RFC ... resolved as of June 2025' -- naming the issue number makes it "
          "checkable against the tracker; I classified X only because I had scoped "
          "'the system' to exclude the tracker"),
    8:   ("U", "resolvable-by-naming",
          "'the upstream change is PR 29469, commit ec65514' NAMES its referent exactly; "
          "a pinned dependency's commit is resolvable"),
    24:  ("U", "resolvable-by-naming",
          "'cropped on firefox' -- naming a viewport width makes it a rendering check"),
    149: ("U", "resolvable-by-naming",
          "'the paper does not appear on the author's page' -- naming the page and date "
          "makes it checkable; it is unresolved, not exogenous"),
    181: ("U", "resolvable-by-naming",
          "'the URL should have been www.openml.org' -- naming both URLs makes it a "
          "two-request check"),
    121: ("U", "resolvable-by-naming",
          "'these objects have all the necessary info specified by the array API standard' "
          "-- the standard is a document; naming the fields resolves it"),
}


def apply(base: dict, flips: dict) -> dict:
    out = dict(base)
    for i, (d, _, _) in flips.items():
        out[i] = (base[i][0], d, base[i][2])
    return out


def f_of(cls: dict) -> tuple[float, int, int]:
    A = [i for i in cls if cls[i][0] == "A"]
    xt = sum(1 for i in A if cls[i][1] in "XT")
    return xt / len(A), xt, len(A)


def main() -> None:
    n_j = sum(1 for i in CLS if CLS[i][2] == "j")
    f0, xt0, na = f_of(CLS)
    print("=" * 76)
    print(f"BASELINE                 f = {xt0}/{na} = {f0:.4f}")
    print(f"judgement calls re-argued: {n_j}")

    # ---- A1 ----
    a1 = apply(CLS, A1_FLIPS)
    f1, xt1, _ = f_of(a1)
    moving = [i for i in A1_FLIPS if CLS[i][0] == "A" and a1[i][1] in "XT"
              and CLS[i][1] not in "XT"]
    print("\n--- A1: adversarial, toward EXOGENOUS/CONTESTED ---")
    print(f"  judgement calls FLIPPED : {len(A1_FLIPS)}/{n_j} = {len(A1_FLIPS)/n_j:.4f}")
    print(f"  judgement calls HELD    : {n_j - len(A1_FLIPS)}")
    print(f"  of the flips, MOVING f  : {len(moving)}")
    print(f"  f AFTER adversarial pass: {xt1}/{na} = {f1:.4f}")
    print(f"  needed for f>=0.50      : {0.50*na:.0f} assertive claims in X+T "
          f"(have {xt1}, short by {0.50*na - xt1:.0f})")
    v1 = ("FAVOURABLE" if f1 < 0.50 else "UNFAVOURABLE" if f1 >= 0.80 else "INTERMEDIATE")
    print(f"  VERDICT                 : CENSUS-{v1}")

    print("\n  A4 -- flip distribution by category:")
    for cat, k in Counter(v[1] for v in A1_FLIPS.values()).most_common():
        print(f"    {k:2}  {cat}")

    # ---- A5 ----
    a5 = apply(CLS, A5_FLIPS)
    f5, xt5, _ = f_of(a5)
    print("\n--- A5: the reverse direction (counter-metric) ---")
    xt_base = sum(1 for i in CLS if CLS[i][0] == "A" and CLS[i][1] in "XT")
    print(f"  EXOGENOUS+CONTESTED at baseline : {xt_base}")
    print(f"  of those, argued merely UNRESOLVED: {len(A5_FLIPS)}")
    print(f"  f AFTER reverse pass            : {xt5}/{na} = {f5:.4f}")

    # ---- both at once ----
    both = apply(apply(CLS, A1_FLIPS), A5_FLIPS)
    fb, xtb, _ = f_of(both)
    print(f"\n--- BOTH directions applied      : f = {xtb}/{na} = {fb:.4f} ---")
    vb = ("FAVOURABLE" if fb < 0.50 else "UNFAVOURABLE" if fb >= 0.80 else "INTERMEDIATE")
    print(f"  VERDICT                         : CENSUS-{vb}")

    json.dump({
        "baseline_f": f0, "a1_f": f1, "a5_f": f5, "both_f": fb,
        "judgement_calls": n_j, "a1_flips": len(A1_FLIPS),
        "a1_flips_moving_f": len(moving), "a5_flips": len(A5_FLIPS),
        "a1_categories": dict(Counter(v[1] for v in A1_FLIPS.values())),
        "verdict_a1": v1, "verdict_both": vb,
    }, open(HERE / "stress_result.json", "w"), indent=1)


if __name__ == "__main__":
    main()
