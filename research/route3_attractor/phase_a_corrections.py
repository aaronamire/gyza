"""
Phase A corrections (A1 trust-lift confound, A2 CI unit) for the Route 2 /
round-2 (MATH) result. Recomputes from route2_independence's cached data +
machinery; does NOT overwrite route2_result.json. Cache-only; no network.

A1: the reported trust-lift compared P(correct | pair agreed) against the
mechanism's mean single-agent accuracy over ALL problems in the cell. Agreement
concentrates on easier problems, so that comparator is a selection confound.
The corrected comparator restricts single-agent accuracy to the SAME problems
the pair agreed on:
    lift(pair) = P(correct | agreed) - mean_single_agent_acc(over agreed items).

A2: the bootstrap resampled over PAIRS (confirmed). With only 3 pairs
(M3 model-controlled) the over-pairs CI is just the spread of 3 numbers and
understates item-level uncertainty; an item-level pooled bootstrap is added for
the headline cells.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent / "route2_independence"))
import route2_experiment as R  # noqa: E402
from run_openrouter import _ci  # noqa: E402


def _mechanisms(A):
    llama_i = [m for m, _ in R.MODELS].index(R.FIXED_MODEL)
    m3 = [R._det_index(llama_i, j) for j in range(3)]
    band = R._capability_band(A)["band"]
    cot_band = [R._det_index(mi, 0) for mi, (m, _f) in enumerate(R.MODELS)
                if m in band]
    mixed = [(i, j) for i in range(12) for j in range(12)
             if i < j and (i % 3) != (j % 3)]

    def prs(idxs):
        return [(idxs[a], idxs[b]) for a in range(len(idxs))
                for b in range(a + 1, len(idxs))]
    return {
        "M2_cross_family_cot": (prs(cot_band), cot_band),
        "M3_cross_method_llama": (prs(m3), m3),
        "M3_mixed_model_method": (mixed, list(range(12))),
    }


def corrected_lift(sigs, expected, pairs, agents, keep):
    qs = sorted(keep)
    old_terms = [1.0 if (not R.is_non_answer(sigs[a][q]) and sigs[a][q] == expected[q])
                 else 0.0 for a in agents for q in qs]
    old_acc = float(np.mean(old_terms)) if old_terms else None
    per = []
    for (i, j) in pairs:
        agreeQ = [q for q in qs
                  if not R.is_non_answer(sigs[i][q]) and not R.is_non_answer(sigs[j][q])
                  and sigs[i][q] == sigs[j][q]]
        if not agreeQ:
            continue
        prec = np.mean([1.0 if sigs[i][q] == expected[q] else 0.0 for q in agreeQ])
        rterms = [1.0 if (not R.is_non_answer(sigs[a][q]) and sigs[a][q] == expected[q])
                  else 0.0 for a in agents for q in agreeQ]
        racc = float(np.mean(rterms))
        per.append({"pair": [i, j], "n_agree": len(agreeQ),
                    "precision": round(float(prec), 4),
                    "restricted_single_acc": round(racc, 4),
                    "old_lift": round(float(prec) - old_acc, 4),
                    "new_lift": round(float(prec) - racc, 4)})
    return old_acc, per


def item_level_ci(sigs, expected, pairs, keep, seed=0, n=3000):
    """Pooled item-level bootstrap: resample the (pair, agreed-item) correct
    indicators, giving the uncertainty the 3-point over-pairs CI misses."""
    qs = sorted(keep)
    pts = []
    for (i, j) in pairs:
        for q in qs:
            if (not R.is_non_answer(sigs[i][q]) and not R.is_non_answer(sigs[j][q])
                    and sigs[i][q] == sigs[j][q]):
                pts.append(1.0 if sigs[i][q] == expected[q] else 0.0)
    if not pts:
        return (None, None, None, 0)
    v = np.array(pts)
    rng = np.random.default_rng(seed)
    boot = [rng.choice(v, len(v), True).mean() for _ in range(n)]
    return (round(float(v.mean()), 4), round(float(np.percentile(boot, 2.5)), 4),
            round(float(np.percentile(boot, 97.5)), 4), len(v))


def run():
    problems = R.build_problem_set()
    A = R.assemble(problems)
    sigs, expected, card = A["sigs"], A["expected"], A["cardinality"]
    mechs = _mechanisms(A)
    out = {}
    for mech, (pairs, agents) in mechs.items():
        for D in ("ALL", "EASY", "HARD"):
            for S in ("ALL", "CONSTRAINED"):
                keep = R._keep(card, None if D == "ALL" else D,
                               None if S == "ALL" else S)
                old_acc, per = corrected_lift(sigs, expected, pairs, agents, keep)
                if not per:
                    continue
                old = _ci([p["old_lift"] for p in per], seed=1)
                new = _ci([p["new_lift"] for p in per], seed=2)
                cell = {"n_problems": len(keep), "old_comparator_acc": None if old_acc is None else round(old_acc, 4),
                        "old_lift_over_pairs_ci": old, "new_lift_over_pairs_ci": new,
                        "n_pairs": len(per), "per_pair": per}
                if mech == "M3_cross_method_llama":
                    cell["new_lift_item_level_ci"] = item_level_ci(
                        sigs, expected, pairs, keep, seed=3)
                out[f"{mech}|{D}|{S}"] = cell
    return out


if __name__ == "__main__":
    res = run()
    (_HERE / "phase_a_corrected_lift.json").write_text(json.dumps(res, indent=2))
    print("=== A1 corrected trust-lift (OLD over-all-problems vs NEW restricted-to-agreed) ===")
    print(f"{'cell':42s} {'n':>3} {'old_lift':>18} {'new_lift':>18}  shrink")
    for k, c in res.items():
        o = c["old_lift_over_pairs_ci"][0]
        nw = c["new_lift_over_pairs_ci"][0]
        sh = None if (o is None or nw is None) else round(o - nw, 3)
        print(f"{k:42s} {c['n_pairs']:>3} {str(c['old_lift_over_pairs_ci']):>18} "
              f"{str(c['new_lift_over_pairs_ci']):>18}  -{sh}")
    print("\n=== A2: M3 HARD item-level CI (vs 3-point over-pairs) ===")
    for k in ("M3_cross_method_llama|HARD|ALL", "M3_cross_method_llama|ALL|ALL"):
        c = res[k]
        print(f"  {k}: new_lift over-pairs {c['new_lift_over_pairs_ci']} | "
              f"item-level {c['new_lift_item_level_ci']}")
