"""SR-1 depth-matched analysis, over the EXISTING corpus. Zero API calls.

WHY THIS RUNS BEFORE ANY FETCH. FINDINGS_SR1.md:169 says *"Matching on depth is
the cheaper fix and should come first."* Cheaper means: do it on the records
already held, and let the result decide whether fetching more is worth it. A
matched analysis that starves every stratum at n=181 will starve them at n=1150
too if the arm ratio does not change, and that is knowable now for free.

THE ASYMMETRY, stated because it is easy to carry the wrong rule across:

  OBSERVATIONAL data -- structure was NOT assigned. Task difficulty causes both
    depth and outcome, so depth is a CONFOUNDER and MATCHING ON IT IS RIGHT.
  RANDOMIZED design -- strategy IS assigned, so nothing confounds it. Depth then
    lies on the causal path strategy -> depth -> outcome, making it a MEDIATOR,
    and CONDITIONING ON IT IS WRONG (it blocks the mediated path and opens a
    collider through task difficulty).

Same variable, opposite treatment. The difference is assignment, not the data.

CONSERVATION IS NOT RECOMPUTED HERE. `conservation()` is imported from
`research/corpus/run_sr1.py` so the two analyses cannot drift into two frames.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CORPUS = ROOT / "research/corpus"
sys.path.insert(0, str(CORPUS))

from run_sr1 import conservation                      # noqa: E402


def load():
    recs = json.loads((CORPUS / "decompositions.json").read_text())["records"]
    files_map = json.loads((CORPUS / "commit_files.json").read_text())
    rows = []
    for r in recs:
        cls, _missing = conservation(r, files_map)
        if cls == "UNDEFINED":
            continue
        rows.append({
            "repo": r["repo"], "pr": r["pr_number"],
            "arm": cls,
            # depth = SUBTASK COUNT, exactly as run_sr1.py:128 computes it.
            # `reference_decomposition` is a DICT; len() of it returns its 3
            # top-level keys and reads "depth 3" for every record. Caught by
            # the counter-metric (REVISITING max came back 3 against a
            # committed max of 100) -- the measure-a-representation species.
            "depth": len(r["reference_decomposition"]["subtasks"]),
            # Ground truth from the SOURCE (project CI), never from judgement.
            "fail": r["outcome_substantive"] == "FAIL",
            "outcome": r["outcome_substantive"],
        })
    return rows


def wilson(k: int, n: int, z: float = 1.959963985):
    """CI for a proportion. Wald is wrong at these n and at rates near 0."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main() -> None:
    rows = load()
    n = len(rows)
    arms = Counter(r["arm"] for r in rows)
    print("=" * 78)
    print(f"CORPUS AS HELD: n={n}  CONSERVING={arms['CONSERVING']}  "
          f"REVISITING={arms['REVISITING']}  "
          f"fraction_conserving={arms['CONSERVING']/n:.4f}")
    print("=" * 78)

    # ---- B5a: arm sizes per depth stratum --------------------------------
    strata = defaultdict(lambda: {"CONSERVING": [], "REVISITING": []})
    for r in rows:
        strata[r["depth"]][r["arm"]].append(r)

    print("\nARM SIZES PER DEPTH STRATUM (matching is only possible where BOTH > 0)")
    print(f"  {'depth':>6}{'CONS':>7}{'REVI':>7}   {'matchable?':<12}")
    matchable = []
    for d in sorted(strata):
        c, v = len(strata[d]["CONSERVING"]), len(strata[d]["REVISITING"])
        ok = c > 0 and v > 0
        if ok:
            matchable.append(d)
        if c or v <= 12 or ok:
            print(f"  {d:>6}{c:>7}{v:>7}   {'YES' if ok else 'starved':<12}")
    print(f"  ... strata with CONSERVING=0 omitted above depth 12")

    # ---- the matched comparison -------------------------------------------
    mc = [r for d in matchable for r in strata[d]["CONSERVING"]]
    mv = [r for d in matchable for r in strata[d]["REVISITING"]]
    print(f"\nMATCHED SET: strata {matchable}")
    print(f"  CONSERVING n={len(mc)}  fail={sum(r['fail'] for r in mc)}")
    print(f"  REVISITING n={len(mv)}  fail={sum(r['fail'] for r in mv)}")

    kc, kv = sum(r["fail"] for r in mc), sum(r["fail"] for r in mv)
    pc = kc / len(mc) if mc else float("nan")
    pv = kv / len(mv) if mv else float("nan")
    lo_c, hi_c = wilson(kc, len(mc))
    lo_v, hi_v = wilson(kv, len(mv))
    print(f"\n  fail(CONSERVING) = {pc:.4f}  95% CI [{lo_c:.4f}, {hi_c:.4f}]")
    print(f"  fail(REVISITING) = {pv:.4f}  95% CI [{lo_v:.4f}, {hi_v:.4f}]")
    print(f"  difference       = {pv - pc:+.4f}")
    print(f"  CIs OVERLAP: {not (hi_c < lo_v or hi_v < lo_c)}")

    # ---- B5c: is CONSERVING still nearly-just-SHORT? ----------------------
    dc = [r["depth"] for r in rows if r["arm"] == "CONSERVING"]
    dv = [r["depth"] for r in rows if r["arm"] == "REVISITING"]
    dc_s, dv_s = sorted(dc), sorted(dv)
    med = lambda x: x[len(x) // 2] if x else float("nan")           # noqa: E731
    print(f"\nCOUNTER-METRIC — is CONSERVING still nearly just SHORT?")
    print(f"  CONSERVING depths: {dc_s}")
    print(f"  median depth  CONSERVING={med(dc_s)}  REVISITING={med(dv_s)}"
          f"  (REVISITING max={max(dv_s)})")
    at_min = sum(1 for d in dc if d == 3)
    print(f"  CONSERVING at the corpus MINIMUM depth (3): {at_min}/{len(dc)} "
          f"= {at_min/len(dc):.4f}")

    out = {
        "_status": "MEASURED over the existing corpus. Zero API calls.",
        "n": n, "arms": dict(arms),
        "strata": {str(d): {"CONSERVING": len(strata[d]["CONSERVING"]),
                            "REVISITING": len(strata[d]["REVISITING"])}
                   for d in sorted(strata)},
        "matchable_strata": matchable,
        "matched": {"conserving_n": len(mc), "conserving_fail": kc,
                    "revisiting_n": len(mv), "revisiting_fail": kv,
                    "p_conserving": pc, "p_revisiting": pv,
                    "ci_conserving": [lo_c, hi_c], "ci_revisiting": [lo_v, hi_v],
                    "difference": pv - pc},
        "counter_metric": {"conserving_depths": dc_s,
                           "conserving_at_min_depth_3": at_min,
                           "fraction_at_min": at_min / len(dc) if dc else None},
    }
    (HERE / "matched.json").write_text(json.dumps(out, indent=1))
    print(f"\nwrote {HERE / 'matched.json'}")


if __name__ == "__main__":
    main()
