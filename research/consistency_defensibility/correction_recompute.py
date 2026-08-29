"""
Phase 8 — recompute Phases 5/6B/7 with the hardened conservative canonicalizer.
Cache-only, ZERO new generations. Old (_sym_equal) vs new (canonicalizer_v2.equal)
side by side. UNRESOLVED (None) items are EXCLUDED, never scored. NOT a Route 2
rescue; not a new experiment — a correction.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
_R2 = _HERE.parent / "route2_independence"
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_R2))
sys.path.insert(0, str(_HERE.parent / "correlated_failure"))

from route2_experiment import extract_boxed, _sym_equal, _slug  # noqa: E402
from consistency_experiment import _youden, _boot_J, _perm_p, _paired_J_diff  # noqa: E402
from canonicalizer_v2 import equal as eq2  # noqa: E402
from witness_experiment import segment, _c1_fire, _c2_fire  # noqa: E402

ROSTER = ["meta-llama/llama-3.1-70b-instruct", "google/gemma-2-27b-it",
          "mistralai/mistral-small-3.2-24b-instruct", "microsoft/phi-4"]
R2C = _R2 / "route2_cache"
EXT = _HERE / "cache_ext"
XV = _HERE / "cache_xverify"
WIT = _HERE / "cache_witness"


def _probs():
    return {p["id"]: p for p in json.loads((_R2 / "problem_set.json").read_text())["problems"]}


def _cand(m):
    d = json.loads((R2C / f"{_slug(m)}__COT__s1.json").read_text())
    out = {}
    for pid, v in d.items():
        raw = v.get("0", {}).get("raw", "")
        if raw and not str(raw).startswith("__ERR__"):
            b = extract_boxed(raw)
            if b:
                out[pid] = b
    return out


def _metrics(fires, wrongs, seed):
    if not fires:
        return None
    tpr, fpr, firing, J, prec = _youden(fires, wrongs)
    lr = (tpr / fpr) if (fpr and not np.isnan(fpr) and fpr > 0) else ("inf" if tpr else None)
    def r(x):
        return None if (x is None or (isinstance(x, float) and np.isnan(x))) else round(float(x), 4)
    return {"n": len(fires), "n_wrong": int(sum(wrongs)), "TPR": r(tpr), "FPR": r(fpr),
            "firing_rate": r(np.mean(fires)), "precision": r(prec), "J": r(J),
            "J_ci": _boot_J(fires, wrongs, seed), "perm_p": _perm_p(fires, wrongs, seed),
            "LR": (lr if isinstance(lr, str) else (None if lr is None else round(lr, 3)))}


# ==========================================================================
# 8b — corrected labels + flips + validation
# ==========================================================================
def labels_and_flips():
    probs = _probs()
    cand = {m: _cand(m) for m in ROSTER}
    old = {}
    new = {}          # 'C'/'W'/'U'
    for m in ROSTER:
        for pid, a in cand[m].items():
            ow = (not _sym_equal(a, probs[pid]["ref_raw"]))
            old[(m, pid)] = "W" if ow else "C"
            e = eq2(a, probs[pid]["ref_raw"])
            new[(m, pid)] = "C" if e is True else ("W" if e is False else "U")
    # flips old-WRONG -> new-CORRECT
    flips = {m: 0 for m in ROSTER}
    unres = {m: 0 for m in ROSTER}
    old_wrong = {m: 0 for m in ROSTER}
    n = {m: 0 for m in ROSTER}
    for (m, pid), ov in old.items():
        n[m] += 1
        nv = new[(m, pid)]
        if ov == "W":
            old_wrong[m] += 1
            if nv == "C":
                flips[m] += 1
        if nv == "U":
            unres[m] += 1
    tot = sum(n.values())
    old_wr = sum(old_wrong.values())
    new_wr = sum(1 for k in new if new[k] == "W")
    new_un = sum(1 for k in new if new[k] == "U")
    return {"old": old, "new": new, "cand": cand,
            "flip_by_model": flips, "old_wrong_by_model": old_wrong,
            "unresolved_by_model": unres,
            "old_base_rate_wrong": round(old_wr / tot, 4),
            "new_base_rate_wrong": round(new_wr / (tot - new_un), 4) if (tot - new_un) else None,
            "n_total": tot, "n_flips": sum(flips.values()), "n_unresolved": new_un}


# hand judgments from Phase 7 examination (30-trace seeded sample), for validation
_L = "meta-llama/llama-3.1-70b-instruct"; _G = "google/gemma-2-27b-it"
_M = "mistralai/mistral-small-3.2-24b-instruct"; _P = "microsoft/phi-4"
HAND = {  # (model,pid): 'C'orrect / 'W'rong ; ambiguous omitted
    (_L, "algebra#428"): "C", (_L, "counting_and_probability#459"): "W",
    (_L, "number_theory#84"): "W", (_L, "intermediate_algebra#91"): "W",
    (_L, "prealgebra#4"): "C", (_L, "precalculus#48"): "W",
    (_G, "algebra#428"): "C", (_G, "intermediate_algebra#161"): "C",
    (_G, "intermediate_algebra#689"): "W", (_G, "precalculus#280"): "W",
    (_G, "precalculus#87"): "W", (_G, "algebra#245"): "W",
    (_G, "counting_and_probability#22"): "W", (_G, "counting_and_probability#459"): "W",
    (_G, "algebra#8"): "W", (_G, "intermediate_algebra#389"): "W",
    (_G, "intermediate_algebra#551"): "W", (_G, "prealgebra#335"): "C",
    (_G, "prealgebra#544"): "W", (_G, "precalculus#48"): "W",
    (_M, "algebra#428"): "C", (_M, "prealgebra#544"): "C",
    (_P, "algebra#428"): "C", (_P, "precalculus#280"): "W",
    (_P, "intermediate_algebra#184"): "W", (_P, "prealgebra#335"): "C",
    (_P, "prealgebra#4"): "C",
}


def validate(new):
    agree = tot = 0
    conf = {"hand_C": {"C": 0, "W": 0, "U": 0}, "hand_W": {"C": 0, "W": 0, "U": 0}}
    disagreements = []
    for k, hv in HAND.items():
        nv = new.get(k)
        if nv is None:
            continue
        conf[f"hand_{hv}"][nv] += 1
        tot += 1
        if (hv == nv) or (hv == "W" and nv == "U"):   # U on a hand-wrong = conservative, not a false merge
            agree += 1
        else:
            disagreements.append((k[0].split("/")[-1], k[1], f"hand={hv} new={nv}"))
    return {"n_hand": tot, "agreement": round(agree / tot, 4) if tot else None,
            "confusion": conf, "disagreements": disagreements,
            "note": ("agreement = new matches hand, counting UNRESOLVED-on-hand-wrong as agreement "
                     "(conservative exclusion, not a false merge). A false MERGE (hand=W, new=C) "
                     "is the fatal error and is counted as disagreement.")}


# ==========================================================================
# 8c — recompute the three phases (old vs new)
# ==========================================================================
def _wrong_new(lbl):   # returns 1(wrong)/0(correct)/None(unresolved)
    return 1 if lbl == "W" else (0 if lbl == "C" else None)


def phase5(L):
    probs = _probs()
    new = L["new"]
    cand = L["cand"]
    def one(labelfn, seed):
        fires, wrongs = [], []
        for m in ROSTER:
            invf = EXT / f"{_slug(m)}__INV__s1.json"
            inv = json.loads(invf.read_text()) if invf.exists() else {}
            for pid, a in cand[m].items():
                w = labelfn(m, pid)
                if w is None:
                    continue
                e = inv.get(pid)
                if not e or str(e["raw"]).startswith("__ERR__"):
                    continue
                b = extract_boxed(e["raw"]).upper(); t = e["raw"].upper()
                fire = 1 if ("INVALID" in b or (b == "" and "INVALID" in t)) else (0 if "VALID" in (b or t) else None)
                if fire is None:
                    continue
                fires.append(fire); wrongs.append(w)
        return _metrics(fires, wrongs, seed)
    old_lab = lambda m, pid: (1 if L["old"][(m, pid)] == "W" else 0)
    new_lab = lambda m, pid: _wrong_new(new[(m, pid)])
    return {"old": one(old_lab, 1), "new": one(new_lab, 2)}


def _load(d, m, tag=None):
    if tag:
        f = d / f"{_slug(m)}__{tag}__s1.json"
    else:
        f = d / f"{_slug(m)}__XV__s1.json"
    return json.loads(f.read_text()) if f.exists() else {}


def phase6b(L):
    probs = _probs(); new = L["new"]; cand = L["cand"]
    def solved(m, pid, mode):
        if (m, pid) not in L["old"]:
            return None
        if mode == "old":
            return not (L["old"][(m, pid)] == "W")
        v = new[(m, pid)]
        return True if v == "C" else (False if v == "W" else None)
    def wrong(m, pid, mode):
        if mode == "old":
            return 1 if L["old"][(m, pid)] == "W" else 0
        return _wrong_new(new[(m, pid)])
    def build(mode):
        recs = []
        for checker in ROSTER:
            xc = _load(XV, checker)
            for claimant in ROSTER:
                if claimant == checker:
                    continue
                for pid in cand[claimant]:
                    w = wrong(claimant, pid, mode)
                    cs = solved(checker, pid, mode)
                    if w is None or cs is None:
                        continue
                    e = xc.get(f"{claimant}|{pid}")
                    if not e or str(e["raw"]).startswith("__ERR__"):
                        continue
                    b = extract_boxed(e["raw"]).upper(); t = e["raw"].upper()
                    f = 1 if ("INVALID" in b or (b == "" and "INVALID" in t)) else (0 if "VALID" in (b or t) else None)
                    if f is None:
                        continue
                    recs.append({"fire": f, "wrong": w, "solved": cs})
        a = [r for r in recs if r["solved"]]
        b = [r for r in recs if not r["solved"]]
        return {"cell_a": _metrics([r["fire"] for r in a], [r["wrong"] for r in a], 10),
                "cell_b": _metrics([r["fire"] for r in b], [r["wrong"] for r in b], 20)}
    return {"old": build("old"), "new": build("new")}


def phase7(L):
    probs = _probs(); new = L["new"]; cand = L["cand"]
    seg = {m: {pid: segment(json.loads((R2C / f"{_slug(m)}__COT__s1.json").read_text())[pid]["0"]["raw"])
               for pid in cand[m]} for m in ROSTER}
    def solved(m, pid, mode):
        if (m, pid) not in L["old"]:
            return None
        if mode == "old":
            return not (L["old"][(m, pid)] == "W")
        v = new[(m, pid)]; return True if v == "C" else (False if v == "W" else None)
    def wrong(m, pid, mode):
        return (1 if L["old"][(m, pid)] == "W" else 0) if mode == "old" else _wrong_new(new[(m, pid)])
    def build(mode):
        c0f, c0w, c1f, c1w, c2f, c2w = [], [], [], [], [], []
        pairs_c1, pairs_c0, pairs_w = [], [], []
        for checker in ROSTER:
            c0 = _load(XV, checker); c1 = _load(WIT, checker, "C1"); c2 = _load(WIT, checker, "C2")
            for claimant in ROSTER:
                if claimant == checker:
                    continue
                for pid in cand[claimant]:
                    w = wrong(claimant, pid, mode); cs = solved(checker, pid, mode)
                    if w is None or cs is None or cs:      # cell (b) only
                        continue
                    ns = len(seg[claimant][pid])
                    e0 = c0.get(f"{claimant}|{pid}")
                    f0 = _c2_fire(e0["raw"]) if e0 else None
                    e1 = c1.get(f"{claimant}|{pid}")
                    f1, _ = _c1_fire(e1["raw"], ns) if e1 else (None, None)
                    c2fires = []
                    for k in (1, 2, 3):
                        ek = c2.get(f"{claimant}|{pid}|k{k}")
                        c2fires.append(_c2_fire(ek["raw"]) if ek else None)
                    vv = [x for x in c2fires if x is not None]
                    c2le3 = (1 if any(x == 1 for x in vv) else 0) if vv else None
                    if f0 is not None:
                        c0f.append(f0); c0w.append(w)
                    if f1 is not None:
                        c1f.append(f1); c1w.append(w)
                    if c2le3 is not None:
                        c2f.append(c2le3); c2w.append(w)
                    if f0 is not None and f1 is not None:
                        pairs_c1.append(f1); pairs_c0.append(f0); pairs_w.append(w)
        return {"C0_b": _metrics(c0f, c0w, 30), "C1_b": _metrics(c1f, c1w, 31),
                "C2le3_b": _metrics(c2f, c2w, 32),
                "witness_effect_C1_minus_C0": _paired_J_diff(pairs_c1, pairs_c0, pairs_w, 33),
                "n_paired": len(pairs_w)}
    return {"old": build("old"), "new": build("new")}


def run():
    L = labels_and_flips()
    val = validate(L["new"])
    out = {
        "program": "Phase 8 canonicalization correction (cache-only). NOT a Route 2 rescue / not a new experiment.",
        "validation_8b": val,
        "labels_8b": {k: L[k] for k in ("flip_by_model", "old_wrong_by_model", "unresolved_by_model",
                                        "old_base_rate_wrong", "new_base_rate_wrong",
                                        "n_total", "n_flips", "n_unresolved")},
        "phase5_A2_selfinversion": phase5(L),
        "phase6b_crossverify": phase6b(L),
        "phase7_witness": phase7(L),
    }
    (_HERE / "correction_result.json").write_text(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    r = run()
    v = r["validation_8b"]
    print("VALIDATION: agreement", v["agreement"], "on", v["n_hand"], "hand labels | confusion", v["confusion"])
    if v["disagreements"]:
        print("  disagreements:", v["disagreements"])
    lb = r["labels_8b"]
    print("FLIPS wrong->correct by model:", lb["flip_by_model"], "| total", lb["n_flips"],
          "| unresolved", lb["n_unresolved"])
    print("base rate wrong: old", lb["old_base_rate_wrong"], "-> new", lb["new_base_rate_wrong"])
    p5 = r["phase5_A2_selfinversion"]
    print("\nPhase5 A2: old J", p5["old"]["J"], p5["old"]["LR"], "| new J", p5["new"]["J"], "LR", p5["new"]["LR"], "FPR", p5["new"]["FPR"])
    p6 = r["phase6b_crossverify"]
    print("Phase6B cell(a): old J", p6["old"]["cell_a"]["J"], "-> new J", p6["new"]["cell_a"]["J"])
    print("Phase6B cell(b): old J", p6["old"]["cell_b"]["J"], "-> new J", p6["new"]["cell_b"]["J"], "ci", p6["new"]["cell_b"]["J_ci"])
    p7 = r["phase7_witness"]
    print("Phase7 C1 cell(b): old J", p7["old"]["C1_b"]["J"] if p7["old"]["C1_b"] else None,
          "-> new J", p7["new"]["C1_b"]["J"] if p7["new"]["C1_b"] else None,
          "ci", p7["new"]["C1_b"]["J_ci"] if p7["new"]["C1_b"] else None)
    print("Phase7 witness effect C1-C0 (cell b): old", p7["old"]["witness_effect_C1_minus_C0"],
          "-> new", p7["new"]["witness_effect_C1_minus_C0"])
