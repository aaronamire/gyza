"""
Route 5 orchestration: Stage 1 extraction (two extractors), Stage 2 offline CAS,
Stage 3 metrics; Q1 coverage, Q2 competence split, Q3 weak-vs-strong extractor,
Q4 MATH-vs-NoOp dissociation; independence ablation (cache-only); cost. NOT a Route
2 rescue.
"""
from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
_R2 = _HERE.parent / "route2_independence"
_R3 = _HERE.parent / "route3_attractor"
_CD = _HERE.parent / "consistency_defensibility"
for p in (_HERE, _R2, _R3, _CD, _HERE.parent / "correlated_failure"):
    sys.path.insert(0, str(p))

from route2_experiment import Route2Backend, extract_boxed, _slug  # noqa: E402
import route2_experiment as R2  # noqa: E402
from canonicalizer_v2 import equal as eq2  # noqa: E402
from witness_experiment import segment, numbered, _c1_fire  # noqa: E402
from consistency_experiment import _youden, _boot_J, _perm_p  # noqa: E402
from step_extractor import extract_prompt, parse_extraction  # noqa: E402
from mechanical_verifier import verify_transition, is_violation, is_checkable  # noqa: E402

SEED = 1
BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = R2.API_KEY
SOURCES = ["meta-llama/llama-3.1-70b-instruct", "google/gemma-2-27b-it",
           "mistralai/mistral-small-3.2-24b-instruct", "microsoft/phi-4"]
EXTRACTORS = {"strong": "microsoft/phi-4", "weak": "google/gemma-2-27b-it"}
FAM = {"microsoft/phi-4": "phi", "google/gemma-2-27b-it": "gemma"}
CACHE = _HERE / "cache_extract"
RESULT = _HERE / "r5_result.json"
R2C = _R2 / "route2_cache"
R3C = _R3 / "route3_cache"
_LOCK = threading.Lock()


def _traces(dataset, model):
    d = json.loads(((R2C if dataset == "MATH" else R3C) / f"{_slug(model)}__COT__s1.json").read_text())
    if dataset == "MATH":
        ids = None
    else:
        items = json.loads((_R3 / "items.json").read_text())["items"]
        ids = {it["item_id"] for it in items if it["category"] == "ii_noop"}
    out = {}
    for pid, v in d.items():
        if ids is not None and pid not in ids:
            continue
        raw = v.get("0", {}).get("raw", "")
        if raw and not str(raw).startswith("__ERR__") and extract_boxed(raw):
            out[pid] = raw
    return out


def _ref(dataset):
    if dataset == "MATH":
        return {p["id"]: p["ref_raw"] for p in json.loads((_R2 / "problem_set.json").read_text())["problems"]}
    return {it["item_id"]: it["true_answer"] for it in json.loads((_R3 / "items.json").read_text())["items"]}


def _prob(dataset):
    if dataset == "MATH":
        return {p["id"]: p["problem"] for p in json.loads((_R2 / "problem_set.json").read_text())["problems"]}
    return {it["item_id"]: it["perturbed_prompt"].split("Give the final answer")[0].strip()
            for it in json.loads((_R3 / "items.json").read_text())["items"]}


# ---------- Stage 1 generation ----------
def _cp(ex_role, dataset, source):
    CACHE.mkdir(exist_ok=True)
    return CACHE / f"{ex_role}__{dataset}__{_slug(source)}__s{SEED}.json"


def _load(ex_role, dataset, source):
    f = _cp(ex_role, dataset, source)
    return json.loads(f.read_text()) if f.exists() else {}


def generate_all(verbose=True):
    for role, ex_model in EXTRACTORS.items():
        backend = Route2Backend(ex_model, FAM[ex_model], base_url=BASE_URL, api_key=API_KEY)
        for dataset in ("MATH", "NoOp"):
            probs = _prob(dataset)
            for source in SOURCES:
                tr = _traces(dataset, source)
                cache = _load(role, dataset, source)
                todo = [(pid, raw) for pid, raw in tr.items()
                        if pid not in cache or str(cache[pid].get("raw", "")).startswith("__ERR__")]
                if not todo:
                    continue

                def _one(t):
                    pid, raw = t
                    steps = segment(raw)
                    try:
                        out = backend.generate(extract_prompt(probs[pid], numbered(steps)),
                                               max_new_tokens=900, temperature=0.0, seed=SEED)
                    except Exception as e:  # noqa: BLE001
                        out = f"__ERR__:{type(e).__name__}"
                    return pid, out, len(steps)
                done = 0
                with ThreadPoolExecutor(max_workers=8) as ex:
                    for fut in as_completed([ex.submit(_one, t) for t in todo]):
                        pid, out, ns = fut.result()
                        with _LOCK:
                            cache[pid] = {"raw": out, "n_steps": ns}
                            done += 1
                            if done % 40 == 0:
                                _cp(role, dataset, source).write_text(json.dumps(cache))
                _cp(role, dataset, source).write_text(json.dumps(cache))
                if verbose:
                    print(f"[gen] {role}({ex_model.split('/')[-1]}) {dataset} {source.split('/')[-1]}: +{len(todo)}", flush=True)


# ---------- Stage 2/3 analysis ----------
def _extractor_solved(dataset):
    """extractor model's own correctness per problem (eq2). None if no answer/unresolved."""
    out = {}
    ref = _ref(dataset)
    for role, ex in EXTRACTORS.items():
        d = json.loads(((R2C if dataset == "MATH" else R3C) / f"{_slug(ex)}__COT__s1.json").read_text())
        out[role] = {}
        for pid, v in d.items():
            if pid not in ref:
                continue
            raw = v.get("0", {}).get("raw", "")
            if not raw or str(raw).startswith("__ERR__"):
                continue
            b = extract_boxed(raw)
            if not b:
                continue
            e = eq2(b, ref[pid])
            out[role][pid] = True if e is True else (False if e is False else None)
    return out


def _records(dataset):
    """Per (role, source, item): detector fire, coverage, proto, wrong."""
    ref = _ref(dataset)
    solved = _extractor_solved(dataset)
    recs = []
    reltally = {}
    for role in EXTRACTORS:
        for source in SOURCES:
            cache = _load(role, dataset, source)
            tr = _traces(dataset, source)
            for pid, raw_src in tr.items():
                w = eq2(extract_boxed(raw_src), ref[pid])
                wrong = 1 if w is False else (0 if w is True else None)
                e = cache.get(pid)
                trans, proto, ok = parse_extraction(e["raw"]) if e else ([], False, False)
                verdicts = []
                for t in trans:
                    v, _ = verify_transition(t)
                    verdicts.append(v)
                    reltally[t.get("relation", "?")] = reltally.get(t.get("relation", "?"), 0) + 1
                n_trans = len(trans)
                n_check = sum(1 for v in verdicts if is_checkable(v))
                n_viol = sum(1 for v in verdicts if is_violation(v))
                n_enl = sum(1 for v in verdicts if v == "ENLARGED_UNSAFE")
                fire = 1 if n_viol > 0 else 0
                recs.append({"role": role, "source": source, "pid": pid, "wrong": wrong,
                             "fire": fire, "n_trans": n_trans, "n_check": n_check,
                             "n_viol": n_viol, "n_enl": n_enl, "proto": proto,
                             "parse_ok": ok, "ext_solved": solved[role].get(pid)})
    return recs, reltally


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


def _cell_metrics(recs, seed):
    ev = [r for r in recs if r["wrong"] is not None]
    def mm(sub, s):
        return _metrics([r["fire"] for r in sub], [r["wrong"] for r in sub], s)
    a = [r for r in ev if r["ext_solved"] is True]
    b = [r for r in ev if r["ext_solved"] is False]
    return {"ALL": mm(ev, seed), "cell_a_ext_solved": mm(a, seed + 1),
            "cell_b_ext_failed": mm(b, seed + 2)}


def analyze():
    out = {"program": "Route 5 mechanical step verification. NOT a Route 2 rescue."}
    datasets = {}
    for ds in ("MATH", "NoOp"):
        recs, reltally = _records(ds)
        ev = [r for r in recs if r["wrong"] is not None]
        # Q1 coverage
        tot_trans = sum(r["n_trans"] for r in recs)
        tot_check = sum(r["n_check"] for r in recs)
        traces_with_check = sum(1 for r in recs if r["n_check"] >= 1)
        cov = {"relation_distribution": reltally,
               "checkable_fraction_of_transitions": round(tot_check / tot_trans, 4) if tot_trans else None,
               "fraction_traces_with_ge1_checkable": round(traces_with_check / len(recs), 4) if recs else None,
               "mean_transitions_per_trace": round(tot_trans / len(recs), 2) if recs else None,
               "protocol_violation_rate": round(sum(1 for r in recs if r["proto"]) / len(recs), 4) if recs else None,
               "parse_fail_rate": round(sum(1 for r in recs if not r["parse_ok"]) / len(recs), 4) if recs else None}
        # per-extractor metrics + cells
        per_ext = {role: _cell_metrics([r for r in ev if r["role"] == role], 100 + i * 10)
                   for i, role in enumerate(EXTRACTORS)}
        datasets[ds] = {"coverage_Q1": cov, "per_extractor": per_ext,
                        "n_eval": len(ev), "n_wrong": sum(1 for r in ev if r["wrong"] == 1)}
    out["datasets"] = datasets

    # Q3 weak vs strong (MATH), paired over identical (source,item)
    recsM, _ = _records("MATH")
    evM = [r for r in recsM if r["wrong"] is not None]
    by_key = {}
    for r in evM:
        by_key.setdefault((r["source"], r["pid"]), {})[r["role"]] = r
    paired = [(v["strong"], v["weak"]) for v in by_key.values() if "strong" in v and "weak" in v]
    def jf(rs):
        return _metrics([r["fire"] for r in rs], [r["wrong"] for r in rs], 7)
    out["Q3_weak_vs_strong_MATH"] = {
        "n_paired_traces": len(paired),
        "strong": jf([s for s, w in paired]), "weak": jf([w for s, w in paired]),
        "strong_coverage": round(float(np.mean([s["n_check"] / max(1, s["n_trans"]) for s, w in paired])), 4),
        "weak_coverage": round(float(np.mean([w["n_check"] / max(1, w["n_trans"]) for s, w in paired])), 4)}

    # Q4 dissociation table (strong extractor, MATH vs NoOp)
    out["Q4_dissociation"] = {}
    for role in EXTRACTORS:
        out["Q4_dissociation"][role] = {
            ds: {"ALL": datasets[ds]["per_extractor"][role]["ALL"],
                 "cell_b": datasets[ds]["per_extractor"][role]["cell_b_ext_failed"]}
            for ds in ("MATH", "NoOp")}

    # independence ablation (MATH, strong extractor): R5 vs A2 vs C1 (cache-only)
    out["independence_MATH"] = _independence(evM)

    # cost
    out["cost"] = _cost()

    # DECISION (MATH, strong extractor cell b + coverage + weak-vs-strong)
    strong_b = datasets["MATH"]["per_extractor"]["strong"]["cell_b_ext_failed"]
    weak_b = datasets["MATH"]["per_extractor"]["weak"]["cell_b_ext_failed"]
    cov = datasets["MATH"]["coverage_Q1"]["checkable_fraction_of_transitions"] or 0
    q3 = out["Q3_weak_vs_strong_MATH"]
    def clears(m):
        return m and m["J"] is not None and m["J"] > 0.20 and m["J_ci"][1] is not None and m["J_ci"][1] > 0
    gap_small = (q3["strong"] and q3["weak"] and q3["strong"]["J"] is not None and q3["weak"]["J"] is not None
                 and abs(q3["strong"]["J"] - q3["weak"]["J"]) <= 0.10)
    if clears(strong_b) and cov >= 0.30 and gap_small:
        case = "R5_LIVE"
    elif clears(strong_b) and cov < 0.30:
        case = "R5_COVERAGE_BOUND"
    elif clears(strong_b) and not clears(weak_b):
        case = "R5_EXTRACTOR_BOUND"
    elif not clears(strong_b) and not clears(weak_b):
        case = "R5_DEAD"
    else:
        case = "INCONCLUSIVE"
    powered = strong_b and strong_b["n_wrong"] >= 8
    out["DECISION"] = {"case": case, "powered": bool(powered),
                       "note": ("cell-(b) n_wrong=%s -> %s" %
                                (strong_b["n_wrong"] if strong_b else 0,
                                 "adequately powered" if powered else "UNDERPOWERED-NULL if null")),
                       "strong_cell_b": strong_b, "weak_cell_b": weak_b,
                       "coverage": cov, "weak_vs_strong_gap_J": (
                           round(abs(q3["strong"]["J"] - q3["weak"]["J"]), 4)
                           if (q3["strong"] and q3["weak"] and q3["strong"]["J"] is not None and q3["weak"]["J"] is not None) else None)}
    RESULT.write_text(json.dumps(out, indent=2, default=str))
    return out


def _independence(evM):
    # R5 fire (strong extractor) per (source,item)
    r5 = {(r["source"], r["pid"]): r["fire"] for r in evM if r["role"] == "strong"}
    wrong = {(r["source"], r["pid"]): r["wrong"] for r in evM if r["role"] == "strong"}
    # A2 self-inversion (cache_ext), per (source,item)
    a2 = {}
    for source in SOURCES:
        f = _CD / "cache_ext" / f"{_slug(source)}__INV__s1.json"
        if not f.exists():
            continue
        for pid, e in json.loads(f.read_text()).items():
            if str(e["raw"]).startswith("__ERR__"):
                continue
            b = extract_boxed(e["raw"]).upper(); t = e["raw"].upper()
            a2[(source, pid)] = 1 if ("INVALID" in b or (b == "" and "INVALID" in t)) else (0 if "VALID" in (b or t) else None)
    # C1 trace-check: any cross-model checker flags this source trace (cache_witness)
    c1 = {}
    from witness_experiment import segment as _seg
    for checker in SOURCES:
        f = _CD / "cache_witness" / f"{_slug(checker)}__C1__s1.json"
        if not f.exists():
            continue
        cc = json.loads(f.read_text())
        for key, e in cc.items():
            claimant, pid = key.split("|")
            if str(e["raw"]).startswith("__ERR__"):
                continue
            src_raw = json.loads((R2C / f"{_slug(claimant)}__COT__s1.json").read_text()).get(pid, {}).get("0", {}).get("raw", "")
            ns = len(_seg(src_raw)) if src_raw else 1
            fv, _ = _c1_fire(e["raw"], ns)
            if fv is None:
                continue
            c1[(claimant, pid)] = max(c1.get((claimant, pid), 0), fv)
    keys = [k for k in r5 if k in a2 and a2[k] is not None and k in c1]
    if not keys:
        return {"n": 0}
    R = np.array([r5[k] for k in keys]); A = np.array([a2[k] for k in keys]); C = np.array([c1[k] for k in keys])
    W = np.array([wrong[k] for k in keys])
    def phi(x, y):
        n = len(x); sx, sy = x.sum(), y.sum()
        num = (x * y).sum() * n - sx * sy
        den = (sx * (n - sx) * sy * (n - sy)) ** 0.5
        return round(float(num / den), 4) if den else None
    def J(f):
        m = _metrics(list(f), list(W), 9); return m["J"] if m else None
    return {"n": len(keys), "n_wrong": int(W.sum()),
            "phi_R5_A2": phi(R, A), "phi_R5_C1": phi(R, C), "phi_A2_C1": phi(A, C),
            "J_R5": J(R), "J_A2": J(A), "J_C1": J(C),
            "J_OR_all": J(((R + A + C) > 0).astype(int)),
            "J_AND_all": J(((R * A * C) > 0).astype(int)),
            "note": "cache-only; all three signals on identical (source,item) MATH traces."}


def _cost():
    gen, ext = [], []
    for source in SOURCES:
        d = json.loads((R2C / f"{_slug(source)}__COT__s1.json").read_text())
        for v in d.values():
            raw = v.get("0", {}).get("raw", "")
            if raw and not str(raw).startswith("__ERR__"):
                gen.append(len(raw) / 4)
    for role in EXTRACTORS:
        for source in SOURCES:
            for v in _load(role, "MATH", source).values():
                if not str(v.get("raw", "")).startswith("__ERR__"):
                    ext.append(len(v["raw"]) / 4)
    g = float(np.mean(gen)) if gen else None
    e = float(np.mean(ext)) if ext else None
    return {"gen_solution_out_tok": round(g, 1) if g else None,
            "extraction_out_tok": round(e, 1) if e else None,
            "CAS_model_tokens": 0,
            "ratio_extraction_over_gen": round(e / g, 3) if (e and g) else None,
            "note": "the CAS check has ZERO marginal model cost (structural difference vs prior "
                    "mechanisms); but the extraction step still pays model tokens."}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "analyze"
    if cmd == "plan":
        n = sum(len(_traces(ds, s)) for ds in ("MATH", "NoOp") for s in SOURCES) * len(EXTRACTORS)
        print(f"extraction calls ~= {n} ({len(EXTRACTORS)} extractors x traces)")
        return 0
    if cmd == "generate":
        generate_all()
        return 0
    if cmd == "analyze":
        r = analyze()
        d = r["DECISION"]
        print("DECISION:", d["case"], "| powered:", d["powered"], "|", d["note"])
        print("coverage (MATH checkable frac):", d["coverage"])
        sb = d["strong_cell_b"]
        print("strong extractor cell (b):", {k: sb[k] for k in ("n", "n_wrong", "J", "J_ci", "FPR", "LR")} if sb else None)
        print("weak-vs-strong gap J:", d["weak_vs_strong_gap_J"])
        for role in EXTRACTORS:
            for ds in ("MATH", "NoOp"):
                m = r["Q4_dissociation"][role][ds]["ALL"]
                print(f"  Q4 {role} {ds} ALL: J={m['J'] if m else None} FPR={m['FPR'] if m else None} n={m['n'] if m else 0} nwrong={m['n_wrong'] if m else 0}")
        print("independence:", {k: r["independence_MATH"].get(k) for k in ("n", "phi_R5_A2", "phi_R5_C1", "J_R5", "J_OR_all")})
        return 0
    print("usage: r5_experiment.py [plan|generate|analyze]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
