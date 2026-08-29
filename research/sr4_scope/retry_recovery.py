"""SR-4's core question, answered from CACHED data. ZERO CREDITS, no generation.

THE QUESTION SR-4 ASKS (research/BUILD_PLAN.md:232-238): does retry recover
failures, or burn budget on reproducible errors? Variants (a) no retry vs
(b) bounded retry, decision rule "equivalence bound 3 percentage points on
recovery rate; if (b) is not meaningfully better than (a), pick (a)."

WHY THIS IS COMPUTABLE FOR FREE. The Channel-A self-consistency cache holds
**2 independent samples per item per model** at temperature 0.7, and
`route3_attractor/items.json` holds `true_answer` for all 80 items. That is
exactly variant (b) at k=1: sample 0 is the first attempt, sample 1 is the
retry. Recovery rate = P(sample 1 correct | sample 0 wrong).

SCORING IS IMPORTED, NOT REIMPLEMENTED. `extract_boxed` and `_sym_equal` come
from route2, and they are the same functions Channel A scored with. This session
already produced three defects from restating a reduction instead of calling it;
this file does not add a fourth.

THE STRATIFICATION IS PREDICTED, NOT CHOSEN AFTER THE FACT. Channel A measured
surface-keyed (ii_noop) errors as RESAMPLE-STABLE and concept-keyed (i_classic)
errors as unstable under resampling. So the prediction, stated before the
number is read: recovery near 0 on surface, above 0 on concept.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CD = ROOT / "research/consistency_defensibility"
R3 = ROOT / "research/route3_attractor"
sys.path.insert(0, str(CD))
sys.path.insert(0, str(ROOT / "research/route2_independence"))

from route2_experiment import _slug, _sym_equal, extract_boxed   # noqa: E402

SURFACE = "ii_noop"
CONCEPT = "i_classic"


def correct(raw: str, true: str) -> bool | None:
    """None = the sample produced no extractable answer. An ERROR IS NOT A
    VALUE: a non-answer is not a wrong answer and is counted separately."""
    if not raw or str(raw).startswith("__ERR__"):
        return None
    b = extract_boxed(raw)
    if not b:
        return None
    try:
        return bool(_sym_equal(b, true))
    except Exception:                                   # noqa: BLE001
        return None


def main() -> None:
    items = {i["item_id"]: i for i in json.loads((R3 / "items.json").read_text())["items"]}
    caches = sorted((CD / "cache_A").glob("*__SC__s1.json"))
    print("=" * 76)
    print("SR-4 variant (b) at k=1, from CACHED self-consistency samples. 0 credits.")
    print("=" * 76)

    agg = {}
    for cf in caches:
        model = cf.name.split("__")[0]
        d = json.loads(cf.read_text())
        for iid, samples in d.items():
            it = items.get(iid)
            if it is None or len(samples) < 2:
                continue
            cat = it["category"]
            a0 = correct(samples.get("0", {}).get("raw", ""), it["true_answer"])
            a1 = correct(samples.get("1", {}).get("raw", ""), it["true_answer"])
            agg.setdefault(cat, []).append((model, iid, a0, a1))

    print(f"\n  {'stratum':<20}{'n':>5}{'attempt0 wrong':>16}{'RECOVERED':>11}"
          f"{'recovery rate':>15}{'newly broken':>14}")
    rows = {}
    for cat in sorted(agg):
        recs = agg[cat]
        # Non-answers are excluded from the DENOMINATOR and counted separately;
        # "it broke" and "it was wrong" are different observations.
        usable = [(m, i, a, b) for m, i, a, b in recs if a is not None and b is not None]
        wrong0 = [r for r in usable if r[2] is False]
        recovered = [r for r in wrong0 if r[3] is True]
        right0 = [r for r in usable if r[2] is True]
        broke = [r for r in right0 if r[3] is False]
        rate = len(recovered) / len(wrong0) if wrong0 else float("nan")
        rows[cat] = {"n_usable": len(usable), "n_nonanswer": len(recs) - len(usable),
                     "attempt0_wrong": len(wrong0), "recovered": len(recovered),
                     "recovery_rate": rate,
                     "attempt0_right": len(right0), "newly_broken": len(broke),
                     "break_rate": len(broke) / len(right0) if right0 else float("nan")}
        print(f"  {cat:<20}{len(usable):>5}{len(wrong0):>16}{len(recovered):>11}"
              f"{rate:>15.4f}{len(broke):>14}")

    print("\n  PREDICTED BEFORE READING (from Channel A's resample-stability):")
    print("    surface  (ii_noop)   RESAMPLE-STABLE   -> recovery near 0")
    print("    concept  (i_classic) resample-UNSTABLE -> recovery above 0")

    s, c = rows.get(SURFACE), rows.get(CONCEPT)
    if s and c:
        print(f"\n  MEASURED: surface {s['recovery_rate']:.4f}  "
              f"concept {c['recovery_rate']:.4f}  "
              f"difference {c['recovery_rate'] - s['recovery_rate']:+.4f}")
        print(f"  SR-4's decision rule: equivalence bound 3pp on recovery rate.")
        print(f"  NET benefit of retry = recovered - newly broken, per stratum:")
        for cat, r in rows.items():
            net = r["recovered"] - r["newly_broken"]
            print(f"    {cat:<20} +{r['recovered']} recovered  "
                  f"-{r['newly_broken']} broken  = NET {net:+d}")

    (HERE / "retry_recovery.json").write_text(json.dumps(
        {"_status": "MEASURED from cached samples. Zero credits, no generation.",
         "source": "consistency_defensibility/cache_A/*__SC__s1.json (2 samples "
                   "per item per model, temp 0.7) + route3_attractor/items.json",
         "k": 1, "strata": rows}, indent=1))
    print(f"\nwrote {HERE / 'retry_recovery.json'}")


if __name__ == "__main__":
    main()
