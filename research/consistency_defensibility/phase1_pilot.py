"""
Phase 1 — FREE cache pilot (zero new generations). Consistency/Defensibility
program, Channel A plumbing. This is NOT a Route 2 rescue: the Route 2 terminal
decision (UNFALSIFIABLE-IN-PRACTICE) stands. This program tests single-agent
CONSISTENCY (Channel A) and DEFENSIBILITY (Channel B), which need no independence.

CIRCULARITY (stated up front, per 1a): the only base↔perturbed comparison the
cache supports is COT (CONTROL=base/original) vs COT (perturbed). For
competence-mode (NoOp) items the base and perturbed share the SAME true answer,
so conditioned on base-correctness, "answer changed" ⟺ "perturbed wrong" BY
CONSTRUCTION. For memorized-mode items the true answer is DESIGNED to change, so
the relation flips (violation = answer did NOT change). Therefore this pilot
CANNOT validate detection; it computes only the non-circular FALSE-POSITIVE side
and base rates. Real detection is Phase 2 (metamorphic transforms), preregistered.

Reuses route3_experiment's validated canonicalizer (canon_tokens, is_non_answer,
extract_boxed). Cache-only; no network.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
_R3 = _HERE.parent / "route3_attractor"
sys.path.insert(0, str(_R3))
sys.path.insert(0, str(_HERE.parent / "route2_independence"))
sys.path.insert(0, str(_HERE.parent / "correlated_failure"))

import route3_experiment as R3  # noqa: E402
from route3_experiment import canon_tokens  # noqa: E402
from route2_experiment import extract_boxed  # noqa: E402
from conditional_independence_null import is_non_answer  # noqa: E402

R3_CACHE = _R3 / "route3_cache"
MODELS = [m for m, _ in R3.MODELS]


def _load(model, method):
    f = R3_CACHE / f"{R3._slug(model)}__{method}__s1.json"
    assert f.exists(), f"cache missing: {f.name}"
    return json.loads(f.read_text())


def _boxed(entry):
    if entry is None:
        return "IMPORTERR:MISSING"
    raw = entry["raw"]
    if str(raw).startswith("__ERR__"):
        return "IMPORTERR:APICALL"
    b = extract_boxed(raw)
    return b if b else "IMPORTERR:NOANSWER"


def run():
    items = json.loads((_R3 / "items.json").read_text())["items"]
    control = {m: _load(m, "CONTROL") for m in MODELS}     # base / original
    cot = {m: _load(m, "COT") for m in MODELS}              # perturbed

    # per item: cluster [true, attractor] + base_m + pert_m (all models) → tokens
    rows = []
    raw_diff_collapsed = 0    # raw-string differs but canonical merges
    raw_diff_total = 0
    for it in items:
        iid = it["item_id"]
        base_raw = {m: _boxed(control[m].get(iid, {}).get("0")) for m in MODELS}
        pert_raw = {m: _boxed(cot[m].get(iid, {}).get("0")) for m in MODELS}
        allraws = [it["true_answer"], it["attractor_answer"]]
        keys = [("true", None), ("attr", None)]
        for m in MODELS:
            allraws += [base_raw[m], pert_raw[m]]
            keys += [("base", m), ("pert", m)]
        tok = canon_tokens(allraws)
        get = lambda i: tok.get(i)  # noqa: E731
        true_t, attr_t = get(0), get(1)
        for mi, m in enumerate(MODELS):
            bi, pi = 2 + 2 * mi, 3 + 2 * mi
            bt, pt = get(bi), get(pi)
            base_ab = bt is not None
            pert_ab = pt is not None
            if not (base_ab and pert_ab):
                rows.append({"id": iid, "cat": it["category"], "mode": it["control_mode"],
                             "model": m, "excluded": True})
                continue
            # canonical-collapse accounting: raw strings differ but tokens equal
            if base_raw[m] != pert_raw[m]:
                raw_diff_total += 1
                if bt == pt:
                    raw_diff_collapsed += 1
            rows.append({
                "id": iid, "cat": it["category"], "mode": it["control_mode"], "model": m,
                "excluded": False,
                "changed": bt != pt,
                "pert_correct": pt == true_t,
                "pert_wrong": pt != true_t,
                "pert_attractor": pt == attr_t,
                "base_correct_for_mode": (bt == true_t) if it["control_mode"] == "competence"
                                         else (bt == attr_t),
            })
    ok = [r for r in rows if not r["excluded"]]

    def rate(sub, key):
        v = [r[key] for r in sub]
        return round(float(np.mean(v)), 4) if v else None

    # (1c) canonical collapse
    collapse = {"raw_diff_pairs": raw_diff_total, "collapsed_by_canonicalization": raw_diff_collapsed,
                "note": "raw-string differences that vanish under canonical equivalence "
                        "(uncanonicalized comparison would manufacture these as violations)"}

    # (1b) mobility base rate: P(changed), overall / by category / by model
    mobility = {"overall": rate(ok, "changed"),
                "by_category": {c: rate([r for r in ok if r["cat"] == c], "changed")
                                for c in ("ii_noop", "i_classic", "iii_substitution")},
                "by_model": {m: rate([r for r in ok if r["model"] == m], "changed") for m in MODELS}}

    # (1b) FALSE-POSITIVE RATE — non-circular. Relation depends on mode:
    #  competence (invariance): FP = changed while pert_correct.
    #  memorized (change expected): FP = NOT changed while pert_correct.
    comp_correct = [r for r in ok if r["mode"] == "competence" and r["pert_correct"]]
    memo_correct = [r for r in ok if r["mode"] == "memorized" and r["pert_correct"]]
    fpr = {
        "invariance_competence": {
            "n_correct": len(comp_correct),
            "FPR": rate(comp_correct, "changed"),
            "by_model": {m: rate([r for r in comp_correct if r["model"] == m], "changed") for m in MODELS}},
        "change_memorized": {
            "n_correct": len(memo_correct),
            "FPR_no_change": round(float(np.mean([not r["changed"] for r in memo_correct])), 4)
            if memo_correct else None},
    }

    # (1b) UNCONDITIONAL association changed vs perturbed-wrong, per category,
    # with a permutation null over items. Labeled partially definitional.
    def assoc(sub, seed):
        wrong = np.array([r["pert_wrong"] for r in sub], float)
        chg = np.array([r["changed"] for r in sub], float)
        if len(sub) == 0 or wrong.sum() == 0 or (len(sub) - wrong.sum()) == 0:
            return {"n": len(sub), "J": None, "p": None}
        j = chg[wrong == 1].mean() - chg[wrong == 0].mean()
        rng = np.random.default_rng(seed)
        null = []
        for _ in range(3000):
            w = rng.permutation(wrong)
            if w.sum() == 0 or (len(w) - w.sum()) == 0:
                continue
            null.append(chg[w == 1].mean() - chg[w == 0].mean())
        null = np.array(null)
        p = float((np.abs(null) >= abs(j)).mean())
        return {"n": len(sub), "P_change_given_wrong": round(float(chg[wrong == 1].mean()), 4),
                "P_change_given_correct": round(float(chg[wrong == 0].mean()), 4),
                "J": round(float(j), 4), "perm_null_p": round(p, 4)}
    association = {c: assoc([r for r in ok if r["cat"] == c], 10 + i)
                  for i, c in enumerate(("ii_noop", "i_classic", "iii_substitution"))}
    association["ALL"] = assoc(ok, 99)

    n_excluded = sum(1 for r in rows if r["excluded"])
    result = {
        "program": "consistency_defensibility Channel A — Phase 1 FREE cache pilot",
        "not_a_route2_rescue": ("Route 2 terminal decision UNFALSIFIABLE-IN-PRACTICE stands; "
                                "this tests single-agent CONSISTENCY, a different channel."),
        "circularity_1a": ("base↔perturbed change is definitionally tied to perturbed-wrongness "
                           "once conditioned on base-correctness (competence) or under the "
                           "known-change relation (memorized). This pilot validates the "
                           "FALSE-POSITIVE side and base rates ONLY, never detection."),
        "cache_basis": "base=CONTROL(COT/original), perturbed=COT(perturbed); COT-only (DECOMP/CODE have no base).",
        "n_pairs_total": len(rows), "n_excluded_nonanswer": n_excluded, "n_evaluable": len(ok),
        "canonical_collapse_1c": collapse,
        "answer_mobility_1b": mobility,
        "false_positive_rate_1b": fpr,
        "unconditional_association_1b_partially_definitional": association,
    }
    return result


if __name__ == "__main__":
    res = run()
    (_HERE / "phase1_cache_pilot.json").write_text(json.dumps(res, indent=2))
    print("evaluable pairs:", res["n_evaluable"], "| excluded (non-answer):", res["n_excluded_nonanswer"])
    print("canonical collapse:", res["canonical_collapse_1c"]["collapsed_by_canonicalization"],
          "/", res["canonical_collapse_1c"]["raw_diff_pairs"], "raw-diff pairs")
    print("mobility overall:", res["answer_mobility_1b"]["overall"],
          "by cat:", res["answer_mobility_1b"]["by_category"])
    print("FPR (invariance, competence/NoOp):", res["false_positive_rate_1b"]["invariance_competence"]["FPR"],
          "n=", res["false_positive_rate_1b"]["invariance_competence"]["n_correct"])
    print("  by model:", res["false_positive_rate_1b"]["invariance_competence"]["by_model"])
    print("FPR_no_change (memorized):", res["false_positive_rate_1b"]["change_memorized"]["FPR_no_change"],
          "n=", res["false_positive_rate_1b"]["change_memorized"]["n_correct"])
    print("assoc (partially definitional):", {k: (v["J"], v.get("perm_null_p")) for k, v in
                                              res["unconditional_association_1b_partially_definitional"].items()})
