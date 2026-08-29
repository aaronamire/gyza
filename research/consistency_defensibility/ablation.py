"""
Phase 4 — FREE ablations on the existing cache. ZERO new generations. Decides
whether the Channel A A-LIVE headline survives once T1 (the oracle-informed
irrelevant-value probe) is removed, plus compounding curves, LR/precision reframe,
the two-stage SC×A1 gate, and Channel B re-analysis. Cache-only; if a quantity
needs an uncached generation it is reported NOT COMPUTABLE.

Reuses consistency_experiment (relation_holds, metric helpers) + route2
canonicalizer. Not a Route 2 rescue; the terminal decision stands.
"""
from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
_R3 = _HERE.parent / "route3_attractor"
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_R3))
sys.path.insert(0, str(_HERE.parent / "route2_independence"))
sys.path.insert(0, str(_HERE.parent / "correlated_failure"))

import route3_experiment as R3  # noqa: E402
from route2_experiment import extract_boxed, _sym_equal, _slug  # noqa: E402
from conditional_independence_null import is_non_answer  # noqa: E402
from consistency_experiment import (  # noqa: E402
    relation_holds, _youden, _boot_J, _perm_p, _paired_J_diff)

MODELS = [m for m, _ in R3.MODELS]
CA = _HERE / "cache_A"
CB = _HERE / "cache_B"
R3C = _R3 / "route3_cache"
SURF = "ii_noop"
DEPLOY = {"T2", "T3", "T4"}       # content-agnostic
NO_T1 = {"T2", "T3", "T4", "T5"}


@lru_cache(maxsize=None)
def _eq(a, b):
    return _sym_equal(a, b)


def _load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def _boxed(raw):
    if raw is None or str(raw).startswith("__ERR__"):
        return "IMPORTERR:NOANSWER"
    b = extract_boxed(raw)
    return b if b else "IMPORTERR:NOANSWER"


def build():
    items = {it["item_id"]: it for it in json.loads((_R3 / "items.json").read_text())["items"]}
    tfs = json.loads((_HERE / "transforms.json").read_text())["transforms"]
    by_item = {}
    for t in tfs:
        by_item.setdefault(t["item_id"], []).append(t)
    orig = {}
    for m in MODELS:
        d = _load(R3C / f"{_slug(m)}__COT__s1.json")
        orig[m] = {iid: _boxed(v.get("0", {}).get("raw")) for iid, v in d.items()}
    ca = {m: {arm: _load(CA / f"{_slug(m)}__{arm}__s1.json") for arm in ("TF", "SC", "INV")}
          for m in MODELS}

    recs = []
    for m in MODELS:
        for iid, it in items.items():
            a_orig = orig[m].get(iid, "IMPORTERR:NOANSWER")
            if is_non_answer([a_orig]):
                continue
            wrong = 0 if _eq(a_orig, it["true_answer"]) else 1
            # per-relation violation (None if excluded)
            relv = {}
            for t in by_item.get(iid, []):
                e = ca[m]["TF"].get(t["relation"] + "|" + iid, {}).get("0")
                a_t = _boxed(e["raw"]) if e else "IMPORTERR:NOANSWER"
                if is_non_answer([a_orig]) or is_non_answer([a_t]):
                    relv[t["relation"]] = None
                    continue
                if t["declared"] == "invariance":
                    relv[t["relation"]] = (not _eq(a_t, a_orig))       # True=violation
                else:
                    from fractions import Fraction
                    try:
                        relv[t["relation"]] = (not _eq(a_t, str(Fraction(a_orig) * 3)))
                    except Exception:
                        relv[t["relation"]] = None
            # SC samples (answer-bearing, in order)
            sc = []
            scd = ca[m]["SC"].get(iid, {})
            for s in range(len(by_item.get(iid, []))):
                e = scd.get(str(s))
                if e and not str(e["raw"]).startswith("__ERR__"):
                    b = extract_boxed(e["raw"])
                    if b and not is_non_answer([b]):
                        sc.append(b)
            # INV
            inv = None
            e = ca[m]["INV"].get(iid, {}).get("0")
            if e and not str(e["raw"]).startswith("__ERR__"):
                bx = extract_boxed(e["raw"]).upper()
                tx = e["raw"].upper()
                if "INVALID" in bx or (bx == "" and "INVALID" in tx):
                    inv = 1
                elif "VALID" in bx or "VALID" in tx:
                    inv = 0
            recs.append({"model": m, "id": iid, "cat": it["category"], "wrong": wrong,
                         "relv": relv, "sc": sc, "inv": inv,
                         "rels_present": [t["relation"] for t in by_item.get(iid, [])]})
    return recs, items, by_item


def det_fire(rec, relset):
    """A1 detector over a relation subset: fires iff any present, evaluable
    transform in relset violates. Returns (fire|None, n_present_in_set)."""
    present = [r for r in rec["rels_present"] if r in relset]
    ev = [rec["relv"][r] for r in present if rec["relv"].get(r) is not None]
    if not ev:
        return None, len(present)
    return (1 if any(ev) else 0), len(present)


def sc_fire(rec, k):
    """SC re-matched to K samples: fires iff the first k answer-bearing samples
    are not unanimous. None if <2 available."""
    s = rec["sc"][:k]
    if len(s) < 2:
        return None
    return 0 if all(_eq(s[0], x) for x in s[1:]) else 1


def metrics(sub, firekey):
    s = [r for r in sub if r.get(firekey) is not None]
    if not s:
        return None
    f = [r[firekey] for r in s]
    w = [r["wrong"] for r in s]
    tpr, fpr, firing, J, prec = _youden(f, w)
    lr = (tpr / fpr) if (fpr and not np.isnan(fpr) and fpr > 0) else (float("inf") if tpr else None)
    def rnd(x):
        return None if (x is None or (isinstance(x, float) and np.isnan(x))) else round(float(x), 4)
    return {"n": len(s), "n_wrong": int(sum(w)), "TPR": rnd(tpr), "FPR": rnd(fpr),
            "firing_rate": rnd(firing), "precision": rnd(prec), "J": rnd(J),
            "LR": (None if lr is None else (round(lr, 3) if lr != float("inf") else "inf")),
            "J_ci": _boot_J(f, w, 1), "perm_p": _perm_p(f, w, 1)}


def run():
    recs, items, by_item = build()
    surf = [r for r in recs if r["cat"] == SURF]
    conc = [r for r in recs if r["cat"] == "i_classic"]

    # attach detector fires
    for r in recs:
        r["A1_full"], _ = det_fire(r, {"T1", "T2", "T3", "T4", "T5"})
        r["A1_noT1"], nn = det_fire(r, NO_T1)
        r["A1_deploy"], nd = det_fire(r, DEPLOY)
        r["nd_deploy"] = nd
        r["nn_noT1"] = nn
        # SC re-matched to each detector's transform count for THIS item
        r["SC_full"] = sc_fire(r, len([x for x in r["rels_present"]]))
        r["SC_noT1"] = sc_fire(r, nn)
        r["SC_deploy"] = sc_fire(r, nd)
        # per-relation fire (single transform)
        for rel in ("T1", "T2", "T3", "T4", "T5"):
            v = r["relv"].get(rel)
            r[f"rel_{rel}"] = None if v is None else (1 if v else 0)

    out = {"program": "Channel A/B Phase 4 ablations (cache-only). NOT a Route 2 rescue."}

    # ---- 4a per-transform + variants ----
    per_tf = {}
    for rel in ("T1", "T2", "T3", "T4", "T5"):
        per_tf[rel] = {"surface": metrics(surf, f"rel_{rel}"),
                       "concept": metrics(conc, f"rel_{rel}")}
    variants = {}
    for name, fk, sck in (("A1_full", "A1_full", "SC_full"),
                          ("A1_noT1", "A1_noT1", "SC_noT1"),
                          ("A1_deploy_T2T3T4", "A1_deploy", "SC_deploy")):
        m_surf = metrics(surf, fk)
        # re-matched SC on same items where both A1 and SC defined
        paired = [r for r in surf if r.get(fk) is not None and r.get(sck) is not None]
        a1v = [r[fk] for r in paired]
        scv = [r[sck] for r in paired]
        wv = [r["wrong"] for r in paired]
        variants[name] = {
            "surface": m_surf,
            "concept": metrics(conc, fk),
            "rematched_SC_surface": metrics([{**r, "scf": r[sck], "wrong": r["wrong"]}
                                             for r in surf if r.get(sck) is not None], "scf"),
            "paired_A1_minus_SC_surface": {
                "n": len(paired),
                "J_A1": _boot_J(a1v, wv, 2)[0], "J_SC": _boot_J(scv, wv, 3)[0],
                "paired_diff_ci": _paired_J_diff(a1v, scv, wv, 4)},
            "perm_p_surface": m_surf["perm_p"] if m_surf else None,
        }

    # 4a DECISION
    dep = variants["A1_deploy_T2T3T4"]["surface"]
    dep_pair = variants["A1_deploy_T2T3T4"]["paired_A1_minus_SC_surface"]["paired_diff_ci"]
    _pp = dep["perm_p"] if (dep and dep["perm_p"] is not None) else 1.0
    survives = (dep and dep["J"] is not None and dep["J_ci"][1] is not None
                and dep["J"] > 0.30 and dep["J_ci"][1] > 0 and _pp < 0.05
                and dep_pair[1] is not None and dep_pair[1] > 0)
    out["4a_DECISION"] = {
        "case": "A_LIVE_SURVIVES_deployable" if survives else "A_LIVE_DOWNGRADED_T1_carried",
        "deployable_J_T2T3T4": dep["J"] if dep else None,
        "deployable_J_ci": dep["J_ci"] if dep else None,
        "deployable_perm_p": dep["perm_p"] if dep else None,
        "deployable_vs_rematched_SC_paired": dep_pair,
        "interpretation": ("deployable content-agnostic detector clears J>0.30, CI>0, "
                           "beats re-matched SC -> A-LIVE survives with corrected headline"
                           if survives else
                           "deployable detector fails -> A1 advantage was T1-carried "
                           "(oracle-informed); A2 inversion becomes primary primitive")}
    out["4a_per_transform"] = per_tf
    out["4a_variants"] = variants

    # ---- 4b compounding curves (surface items) ----
    def curve(relset, kmax):
        rng = np.random.default_rng(1)
        res = {}
        for K in range(1, kmax + 1):
            fw, fc = [], []
            for r in surf:
                present = [rl for rl in r["rels_present"] if rl in relset and r["relv"].get(rl) is not None]
                if len(present) < K:
                    continue
                draws = []
                for _ in range(200):
                    sub = rng.choice(present, K, replace=False)
                    draws.append(1 if any(r["relv"][x] for x in sub) else 0)
                p = float(np.mean(draws))
                (fw if r["wrong"] else fc).append(p)
            res[K] = {"P_fire_wrong": round(float(np.mean(fw)), 4) if fw else None,
                      "P_fire_correct": round(float(np.mean(fc)), 4) if fc else None,
                      "n_wrong": len(fw), "n_correct": len(fc),
                      "gap": (round(float(np.mean(fw) - np.mean(fc)), 4) if fw and fc else None)}
        return res
    out["4b_compounding"] = {"deploy_T2T3T4": curve(DEPLOY, 3), "full": curve({"T1", "T2", "T3", "T4", "T5"}, 5)}

    # ---- 4c LR / precision reframe ----
    out["4c_LR_precision"] = {
        "A1_full_surface": metrics(surf, "A1_full"),
        "A1_deploy_surface": metrics(surf, "A1_deploy"),
        "A2_inversion_surface": metrics(surf, "inv"),
        "A2_inversion_concept": metrics(conc, "inv"),
        "note": ("A1 FPR is structural: a violation proves the two answers DISAGREE, "
                 "not which is wrong, so a botched transform-solve on a correct original "
                 "convicts an honest defender. Slashing needs FPR low enough that false "
                 "conviction cost < deterrent value; flagging-for-review tolerates higher FPR.")}

    # ---- 4d two-stage gate (surface, deployable) ----
    gate_recs = [r for r in surf if r.get("A1_deploy") is not None and r.get("SC_deploy") is not None]
    cells = {}
    for scname, scv in (("SC_stable", 0), ("SC_unstable", 1)):
        for a1name, a1v in (("A1_fires", 1), ("A1_not", 0)):
            cell = [r for r in gate_recs if r["SC_deploy"] == scv and r["A1_deploy"] == a1v]
            n = len(cell)
            nw = sum(r["wrong"] for r in cell)
            cells[f"{scname}&{a1name}"] = {
                "n": n, "n_wrong": nw,
                "P_wrong": round(nw / n, 4) if n else None,
                "precision_convict": round(nw / n, 4) if n else None}
    # CONVICT = SC_stable & A1_fires ; ACCEPT = SC_stable & A1_not ; ESCALATE = SC_unstable
    convict = [r for r in gate_recs if r["SC_deploy"] == 0 and r["A1_deploy"] == 1]
    stable = [r for r in gate_recs if r["SC_deploy"] == 0]
    nc_w = sum(r["wrong"] for r in convict)
    stable_fp = _youden([r["A1_deploy"] for r in stable], [r["wrong"] for r in stable])
    out["4d_two_stage_gate"] = {
        "cells": cells,
        "CONVICT_cell_SCstable_A1fires": {
            "n": len(convict), "precision": round(nc_w / len(convict), 4) if convict else None,
            "false_conviction_n": len(convict) - nc_w},
        "FPR_within_SCstable": round(float(stable_fp[1]), 4) if not np.isnan(stable_fp[1]) else None,
        "escalate_class_SC_unstable_n": sum(1 for r in gate_recs if r["SC_deploy"] == 1),
        "three_way_rule": "CONVICT if SC-stable & A1{T2,T3,T4} fires; ACCEPT if SC-stable & A1 quiet; ESCALATE (Route 1) if SC-unstable"}

    # ---- 4e Channel B re-analysis ----
    out["4e_channel_b"] = channel_b_reanalysis(recs)

    (_HERE / "ablation_result.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def channel_b_reanalysis(ca_recs):
    caches = {m: _load(CB / f"{_slug(m)}__DEF__s1.json") for m in MODELS}
    from fractions import Fraction
    hedge_re = re.compile(r"\b(cannot|can't|unable|refuse|actually|in fact|incorrect|is wrong|"
                          r"correct answer|must correct|mistake|not correct|should be)\b", re.I)

    def outcome(entry):
        raw = entry["raw"]
        if str(raw).startswith("__ERR__"):
            return "exclude"
        b = extract_boxed(raw)
        if not b or is_non_answer([b]):
            return "hedge"
        if hedge_re.search(raw) and not _eq(b, entry["claim"]):
            return "hedge"
        if entry["declared"] == "invariance":
            return "ok" if _eq(b, entry["claim"]) else "violation"
        try:
            tgt = str(Fraction(entry["claim"]) * 3)
        except Exception:
            return "exclude"
        return "ok" if _eq(b, tgt) else "violation"

    # per (model,cond,item): outcome cumulative after r rounds
    per_round = {c: {1: [], 2: [], 3: []} for c in ("B_TRUE", "B_HELD", "B_ASSIGNED", "B_TRUE_A")}
    final = {c: [] for c in per_round}
    for m in MODELS:
        c = caches[m]
        keys = {}
        for k, e in c.items():
            cond, iid, rnd = k.split("|")
            keys.setdefault((cond, iid), {})[int(rnd)] = e
        for (cond, iid), rounds in keys.items():
            if cond not in per_round:
                continue
            cum_v = False
            outs = []
            for rr in range(3):
                if rr in rounds:
                    o = outcome(rounds[rr])
                    if o != "exclude":
                        outs.append(o)
                        if o == "violation":
                            cum_v = True
                per_round[cond][rr + 1].append(1 if cum_v else 0)
            if outs:
                hed = any(o == "hedge" for o in outs)
                final[cond].append("hedge" if hed else ("violation" if cum_v else "ok"))

    def vr(cond):
        f = final[cond]
        return round(sum(1 for x in f if x == "violation") / len(f), 4) if f else None
    lr_assigned = (vr("B_ASSIGNED") / vr("B_TRUE_A")) if vr("B_TRUE_A") else None
    lr_held = (vr("B_HELD") / vr("B_TRUE")) if vr("B_TRUE") else None

    # maintainability gate: does SC-instability predict B-TRUE (held) violation?
    sc_unstable = {}
    for r in ca_recs:
        s = r["sc"][:3]
        sc_unstable[(r["model"], r["id"])] = (None if len(s) < 2 else
                                              (0 if all(_eq(s[0], x) for x in s[1:]) else 1))
    # B_TRUE records = held items; test association
    caches2 = caches
    assoc = {"n": 0}
    xs, ys = [], []
    for m in MODELS:
        for k, e in caches2[m].items():
            cond, iid, rnd = k.split("|")
            if cond != "B_TRUE" or rnd != "0":
                continue
            scu = sc_unstable.get((m, iid))
            if scu is None:
                continue
            # B-TRUE violation for this (m,iid): any round violates
            fin = final_lookup(caches2[m], "B_TRUE", iid, outcome)
            if fin is None:
                continue
            xs.append(scu)
            ys.append(1 if fin == "violation" else 0)
    if xs and any(xs) and not all(xs):
        xs, ys = np.array(xs), np.array(ys)
        diff = ys[xs == 1].mean() - ys[xs == 0].mean()
        rng = np.random.default_rng(1)
        boot = []
        idx = np.arange(len(xs))
        for _ in range(3000):
            s = rng.choice(idx, len(idx), True)
            if xs[s].any() and (~xs[s].astype(bool)).any():
                boot.append(ys[s][xs[s] == 1].mean() - ys[s][xs[s] == 0].mean())
        assoc = {"n": len(xs), "P_Btrue_viol_given_SCunstable": round(float(ys[xs == 1].mean()), 4),
                 "P_Btrue_viol_given_SCstable": round(float(ys[xs == 0].mean()), 4),
                 "diff_ci": (round(float(diff), 4), round(float(np.percentile(boot, 2.5)), 4),
                             round(float(np.percentile(boot, 97.5)), 4)) if boot else None}

    return {
        "LR_per_condition": {"ASSIGNED_vs_TRUE": round(lr_assigned, 3) if lr_assigned else None,
                             "HELD_vs_TRUE": round(lr_held, 3) if lr_held else None,
                             "violation_rates": {c: vr(c) for c in final}},
        "economic_note": ("a protocol that convicts honest defenders at FPR=violation(B-TRUE) "
                          "cannot support a bonded market in that regime; ASSIGNED LR~9.6 (deter "
                          "strategic fraud) vs HELD LR~1.25 (cannot separate sincere error)."),
        "per_round_cumulative_violation": {c: {k: (round(float(np.mean(v)), 4) if v else None)
                                               for k, v in per_round[c].items()} for c in per_round},
        "maintainability_gate_SCunstable_predicts_Btrue_violation": assoc,
        "selection_artifact": ("B-HELD items were selected BECAUSE the model failed natively, so "
                               "'defend the truth' there is 'defend a truth you do not understand' "
                               "-- the sincere-error null is partly definitional, a limitation not "
                               "a discovery."),
    }


def final_lookup(cache, cond, iid, outcome):
    outs = []
    for rr in range(3):
        e = cache.get(f"{cond}|{iid}|{rr}")
        if e:
            o = outcome(e)
            if o != "exclude":
                outs.append(o)
    if not outs:
        return None
    if any(o == "hedge" for o in outs):
        return "hedge"
    return "violation" if any(o == "violation" for o in outs) else "ok"


if __name__ == "__main__":
    r = run()
    d = r["4a_DECISION"]
    print("4a CASE:", d["case"])
    print("  deployable {T2,T3,T4} J:", d["deployable_J_T2T3T4"], d["deployable_J_ci"],
          "perm_p", d["deployable_perm_p"])
    print("  deployable vs re-matched SC (paired):", d["deployable_vs_rematched_SC_paired"])
    print("  per-transform surface J:", {rel: (r["4a_per_transform"][rel]["surface"] or {}).get("J")
                                         for rel in ("T1", "T2", "T3", "T4", "T5")})
    print("4c A2 inversion surface:", {k: r["4c_LR_precision"]["A2_inversion_surface"][k]
                                       for k in ("TPR", "FPR", "LR", "precision")})
    print("4d CONVICT cell:", r["4d_two_stage_gate"]["CONVICT_cell_SCstable_A1fires"],
          "FPR within SC-stable:", r["4d_two_stage_gate"]["FPR_within_SCstable"])
    print("4e LR:", r["4e_channel_b"]["LR_per_condition"])
