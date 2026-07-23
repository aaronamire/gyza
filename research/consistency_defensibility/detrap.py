"""
Phase 6A — FREE. Is T2's J=1.0 a de-trapping artifact? Cache-only, zero
generations. Compares the model's accuracy on the ORIGINAL NoOp item vs on the
T2/T3/T4-transformed item (both vs the verified true answer). If transform
accuracy is materially higher, the rephrase is partially REMOVING the trap
("restatement fixes it"), not measuring invariance-instability. NOT a Route 2
rescue. Reuses route2 canonicalizer.
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
_R3 = _HERE.parent / "route3_attractor"
sys.path.insert(0, str(_R3))
sys.path.insert(0, str(_HERE.parent / "route2_independence"))
sys.path.insert(0, str(_HERE.parent / "correlated_failure"))

import route3_experiment as R3  # noqa: E402
from route2_experiment import extract_boxed, _sym_equal, _slug  # noqa: E402
from conditional_independence_null import is_non_answer  # noqa: E402

MODELS = [m for m, _ in R3.MODELS]
CA = _HERE / "cache_A"
R3C = _R3 / "route3_cache"


@lru_cache(maxsize=None)
def _eq(a, b):
    return _sym_equal(a, b)


def _boxed(raw):
    if raw is None or str(raw).startswith("__ERR__"):
        return "IMPORTERR:NOANSWER"
    b = extract_boxed(raw)
    return b if b else "IMPORTERR:NOANSWER"


def _boot_diff(pairs, seed):
    """pairs: list of (acc_trans, acc_orig). Bootstrap CI of mean(trans-orig)."""
    d = np.array([t - o for t, o in pairs], float)
    if len(d) == 0:
        return (None, None, None)
    rng = np.random.default_rng(seed)
    b = [rng.choice(d, len(d), True).mean() for _ in range(3000)]
    return (round(float(d.mean()), 4), round(float(np.percentile(b, 2.5)), 4),
            round(float(np.percentile(b, 97.5)), 4))


def run():
    items = {it["item_id"]: it for it in json.loads((_R3 / "items.json").read_text())["items"]}
    noop = [iid for iid, it in items.items() if it["category"] == "ii_noop"]
    orig = {}
    tf = {}
    for m in MODELS:
        d = json.loads((R3C / f"{_slug(m)}__COT__s1.json").read_text())
        orig[m] = {iid: _boxed(v.get("0", {}).get("raw")) for iid, v in d.items()}
        tf[m] = json.loads((CA / f"{_slug(m)}__TF__s1.json").read_text())

    def tans(m, rel, iid):
        e = tf[m].get(rel + "|" + iid, {}).get("0")
        return _boxed(e["raw"]) if e else "IMPORTERR:NOANSWER"

    out = {"program": "Phase 6A de-trap check (cache-only). NOT a Route 2 rescue.",
           "n_noop": len(noop)}
    per_rel = {}
    for rel in ("T2", "T3", "T4"):
        pooled_pairs = []            # (acc_trans, acc_orig) both answer-bearing
        wrong_orig_fixed = []        # among wrong-original, correct on transform?
        attr_orig = []
        attr_trans = []
        by_model = {}
        for m in MODELS:
            mp = []
            wf = []
            for iid in noop:
                o = orig[m].get(iid, "IMPORTERR:NOANSWER")
                t = tans(m, rel, iid)
                if is_non_answer([o]) or is_non_answer([t]):
                    continue
                true = items[iid]["true_answer"]
                attr = items[iid]["attractor_answer"]
                ao = 1.0 if _eq(o, true) else 0.0
                at = 1.0 if _eq(t, true) else 0.0
                mp.append((at, ao))
                pooled_pairs.append((at, ao))
                attr_orig.append(1.0 if _eq(o, attr) else 0.0)
                attr_trans.append(1.0 if _eq(t, attr) else 0.0)
                if ao == 0.0:
                    fixed = 1.0 if at == 1.0 else 0.0
                    wf.append(fixed)
                    wrong_orig_fixed.append(fixed)
            by_model[m.split("/")[-1]] = {
                "n": len(mp),
                "acc_orig": round(float(np.mean([o for _, o in mp])), 4) if mp else None,
                "acc_trans": round(float(np.mean([t for t, _ in mp])), 4) if mp else None,
                "paired_diff_ci": _boot_diff(mp, 1),
                "n_wrong_orig": len(wf),
                "frac_wrong_orig_fixed_by_transform": round(float(np.mean(wf)), 4) if wf else None}
        per_rel[rel] = {
            "pooled": {
                "n": len(pooled_pairs),
                "acc_orig": round(float(np.mean([o for _, o in pooled_pairs])), 4),
                "acc_trans": round(float(np.mean([t for t, _ in pooled_pairs])), 4),
                "paired_diff_trans_minus_orig_ci": _boot_diff(pooled_pairs, 2),
                "n_wrong_orig": len(wrong_orig_fixed),
                "frac_wrong_orig_fixed_by_transform": round(float(np.mean(wrong_orig_fixed)), 4)
                if wrong_orig_fixed else None,
                "attractor_hit_orig": round(float(np.mean(attr_orig)), 4),
                "attractor_hit_transform": round(float(np.mean(attr_trans)), 4)},
            "by_model": by_model}
    out["per_relation"] = per_rel

    # 6A DECISION on T2
    t2 = per_rel["T2"]["pooled"]
    diff = t2["paired_diff_trans_minus_orig_ci"]
    detrap = diff[1] is not None and diff[1] > 0     # CI excludes 0 on the positive side
    out["6A_DECISION"] = {
        "case": "T2_PARTIALLY_DETRAPPING" if detrap else "T2_GENUINE_INVARIANCE_INSTABILITY",
        "acc_orig": t2["acc_orig"], "acc_trans_T2": t2["acc_trans"],
        "paired_diff_ci": diff,
        "frac_wrong_orig_fixed_by_T2": t2["frac_wrong_orig_fixed_by_transform"],
        "interpretation": (
            "T2 transform accuracy is materially HIGHER than original (CI excludes 0): the "
            "rephrase partially REMOVES the trap. The deployable J=0.94 must be restated as "
            "'clarifying restatement + disagreement detects comprehension error' -- a "
            "NON-content-agnostic claim (requires knowing what to clarify)."
            if detrap else
            "T2 transform accuracy approx equals original: T2 measures genuine "
            "invariance-instability; deployable J=0.94 stands.")}
    (_HERE / "detrap_result.json").write_text(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    r = run()
    print("6A CASE:", r["6A_DECISION"]["case"])
    for rel in ("T2", "T3", "T4"):
        p = r["per_relation"][rel]["pooled"]
        print(f"  {rel}: acc_orig={p['acc_orig']} acc_trans={p['acc_trans']} "
              f"diff={p['paired_diff_trans_minus_orig_ci']} | wrong-orig fixed by transform="
              f"{p['frac_wrong_orig_fixed_by_transform']} (n_wrong={p['n_wrong_orig']}) | "
              f"attractor hit orig={p['attractor_hit_orig']} trans={p['attractor_hit_transform']}")
    print("  T2 by model:", {m: (v["acc_orig"], v["acc_trans"], v["paired_diff_ci"])
                             for m, v in r["per_relation"]["T2"]["by_model"].items()})
