"""
Channel A — Phase 2: consistency mechanisms (the real test). NOT a Route 2
rescue; the Route 2 terminal decision (UNFALSIFIABLE-IN-PRACTICE) stands. This
tests single-agent CONSISTENCY: does a claim survive semantics-preserving
transformation? — a trust source that needs no independence.

Four mechanisms (A1 metamorphic, A2 inversion, A3 trace-coherence [judge-dep,
reported separately], A4 entailment-net) vs a COST-MATCHED self-consistency
baseline (resample the same item K times, K = #transforms). The audited claim is
each model's cached round-3 COT answer to the item as given; transforms are the
audit. Ground truth (wrong/correct) is used for EVALUATION only, never by a
detector.

REUSE: route3 canonicalizer + sentinel guard; route2 Route2Backend + _sym_equal +
extract_boxed; _ci bootstrap. Cache-only after generation; keyed
(model, arm, key, sample_idx).
"""
from __future__ import annotations

import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from fractions import Fraction
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
_R3 = _HERE.parent / "route3_attractor"
sys.path.insert(0, str(_R3))
sys.path.insert(0, str(_HERE.parent / "route2_independence"))
sys.path.insert(0, str(_HERE.parent / "correlated_failure"))

import route3_experiment as R3  # noqa: E402
from route2_experiment import Route2Backend, extract_boxed, _sym_equal, _slug  # noqa: E402
from conditional_independence_null import is_non_answer  # noqa: E402
from run_openrouter import _ci  # noqa: E402

SEED = 1
BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = R3.API_KEY
MODELS = [m for m, _ in R3.MODELS]
FAM = dict(R3.MODELS)
TRACE_MODEL = "google/gemma-2-27b-it"      # cheap second model for A3 trace-coherence
MAXTOK = 900
CACHE = _HERE / "cache_A"
RESULT = _HERE / "channel_a_result.json"
R3_CACHE = _R3 / "route3_cache"

SURFACE_CATS = {"ii_noop"}                  # surface-keyed (predict DETECTABLE)
CONCEPT_CATS = {"i_classic"}                # concept-keyed (predict UNDETECTABLE)


def load_items():
    return json.loads((_R3 / "items.json").read_text())["items"]


def load_transforms():
    return json.loads((_HERE / "transforms.json").read_text())["transforms"]


# ---- cached round-3 original COT answers (the audited claim) ----
def _r3(model, method):
    return json.loads((R3_CACHE / f"{_slug(model)}__{method}__s1.json").read_text())


def original_answers():
    cot = {m: _r3(m, "COT") for m in MODELS}
    out = {}
    for m in MODELS:
        out[m] = {}
        for iid, d in cot[m].items():
            raw = d.get("0", {}).get("raw", "")
            b = extract_boxed(raw) if not str(raw).startswith("__ERR__") else ""
            out[m][iid] = b if b else "IMPORTERR:NOANSWER"
        # also keep the full trace for A3
    return out


def original_traces():
    cot = {m: _r3(m, "COT") for m in MODELS}
    return {m: {iid: d.get("0", {}).get("raw", "") for iid, d in cot[m].items()} for m in MODELS}


# ==========================================================================
# PROMPTS
# ==========================================================================
def solve_prompt(problem):
    return ("Solve the following problem step by step, then give the final answer "
            "as \\boxed{...} on the last line.\n\n" + problem)


def inversion_prompt(problem_core, candidate):
    return ("You are checking a proposed answer. Here is a problem and a candidate "
            "final answer. Re-read the problem carefully and determine whether the "
            "candidate answer satisfies ALL the conditions stated in the problem. "
            "Respond on the last line with exactly \\boxed{VALID} or \\boxed{INVALID}.\n\n"
            f"Problem: {problem_core}\n\nCandidate answer: {candidate}")


def entailment_prompt(problem_core):
    return ("Read the problem and answer three sub-questions about it. Output ONLY "
            "three lines in exactly this format:\nA: <number>\nB: <number>\nC: <number>\n"
            "where A = the total quantity present at the start, B = the number that are "
            "removed/taken away, and C = the number remaining at the end.\n\n"
            f"Problem: {problem_core}")


def trace_prompt(trace):
    return ("Below is someone's step-by-step reasoning for a math problem (the problem "
            "statement is NOT shown). Based ONLY on the logic of the reasoning, state the "
            "single final numeric answer the reasoning arrives at. Give it as "
            "\\boxed{...} on the last line.\n\nReasoning:\n" + trace[:4000])


# ==========================================================================
# GENERATION (cached). Arms: TF (transform solves), INV, ENT, TRACE, SC (self-consistency)
# ==========================================================================
_LOCK = threading.Lock()


def _cp(model, arm):
    CACHE.mkdir(exist_ok=True)
    return CACHE / f"{_slug(model)}__{arm}__s{SEED}.json"


def _load(model, arm):
    f = _cp(model, arm)
    return json.loads(f.read_text()) if f.exists() else {}


def _core(prompt):
    return prompt.split("Give the final answer")[0].strip()


def _gen_arm(model, arm, tasks, temp=0.0, workers=8):
    """tasks: list of (key, prompt, sample_idx). Cache: {key: {sample_idx: {raw}}}."""
    cache = _load(model, arm)

    def _need(k, s):
        e = cache.get(k, {}).get(str(s))
        return e is None or str(e.get("raw", "")).startswith("__ERR__")
    todo = [(k, p, s) for (k, p, s) in tasks if _need(k, s)]
    if not todo:
        return
    backend = Route2Backend(model, FAM.get(model, "?"), base_url=BASE_URL, api_key=API_KEY)

    def _one(t):
        k, p, s = t
        seed = SEED if temp == 0 else SEED * 1000 + s
        try:
            raw = backend.generate(p, max_new_tokens=MAXTOK, temperature=temp, seed=seed)
        except Exception as e:  # noqa: BLE001
            raw = f"__ERR__:{type(e).__name__}"
        return k, s, raw
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(_one, t) for t in todo]):
            k, s, raw = fut.result()
            with _LOCK:
                cache.setdefault(k, {})[str(s)] = {"raw": raw}
                done += 1
                if done % 40 == 0:
                    _cp(model, arm).write_text(json.dumps(cache))
    _cp(model, arm).write_text(json.dumps(cache))


def generate_all(verbose=True):
    items = load_items()
    tfs = load_transforms()
    by_item_tf = {}
    for t in tfs:
        by_item_tf.setdefault(t["item_id"], []).append(t)
    core = {it["item_id"]: _core(it["perturbed_prompt"]) for it in items}
    orig = original_answers()
    traces = original_traces()

    for model in MODELS:
        # TF: solve each transform (temp 0)
        tf_tasks = [(t["relation"] + "|" + t["item_id"], solve_prompt(_core(t["transformed_prompt"])), 0)
                    for t in tfs]
        _gen_arm(model, "TF", tf_tasks)
        # SC self-consistency: resample original item K times (K = #transforms), temp 0.7
        sc_tasks = []
        for it in items:
            K = len(by_item_tf.get(it["item_id"], []))
            for s in range(K):
                sc_tasks.append((it["item_id"], solve_prompt(core[it["item_id"]]), s))
        _gen_arm(model, "SC", sc_tasks, temp=0.7)
        # INV inversion (temp 0): audit the model's OWN original answer
        inv_tasks = [(it["item_id"], inversion_prompt(core[it["item_id"]], orig[model][it["item_id"]]), 0)
                     for it in items if not is_non_answer([orig[model][it["item_id"]]])]
        _gen_arm(model, "INV", inv_tasks)
        # ENT entailment (NoOp only — structured triple)
        ent_tasks = [(it["item_id"], entailment_prompt(core[it["item_id"]]), 0)
                     for it in items if it["category"] == "ii_noop"]
        _gen_arm(model, "ENT", ent_tasks)
        # TRACE (judge-dependent): second model reads THIS model's original trace
        tr_tasks = [(model + "|" + it["item_id"], trace_prompt(traces[model][it["item_id"]]), 0)
                    for it in items if not str(traces[model][it["item_id"]]).startswith("__ERR__")]
        _gen_arm(TRACE_MODEL, "TRACE", tr_tasks)
        if verbose:
            print(f"[gen] {model}: TF {len(tf_tasks)} SC {len(sc_tasks)} INV {len(inv_tasks)} ENT {len(ent_tasks)}", flush=True)


# ==========================================================================
# DETECTION helpers
# ==========================================================================
def _to_frac(s):
    try:
        return Fraction(s)
    except Exception:
        return None


def relation_holds(a_orig, a_trans, declared):
    """None if either side is a non-answer (EXCLUDE). Else True/False."""
    if is_non_answer([a_orig]) or is_non_answer([a_trans]):
        return None
    if declared == "invariance":
        return _sym_equal(a_orig, a_trans)
    # equivariance_k3
    fo = _to_frac(a_orig)
    if fo is None:
        return None
    return _sym_equal(a_trans, str(fo * 3))


def _tf_answer(cache, rel, iid):
    e = cache.get(rel + "|" + iid, {}).get("0")
    if e is None or str(e["raw"]).startswith("__ERR__"):
        return "IMPORTERR:NOANSWER"
    b = extract_boxed(e["raw"])
    return b if b else "IMPORTERR:NOANSWER"


def _sc_changed(cache, iid, K):
    ans = []
    for s in range(K):
        e = cache.get(iid, {}).get(str(s))
        if e and not str(e["raw"]).startswith("__ERR__"):
            b = extract_boxed(e["raw"])
            if b and not is_non_answer([b]):
                ans.append(b)
    if len(ans) < 2:
        return None                       # not enough samples to judge
    # not unanimous under canonical equivalence
    for i in range(1, len(ans)):
        if not _sym_equal(ans[0], ans[i]):
            return True
    return False


# ==========================================================================
# METRICS
# ==========================================================================
def _youden(fires, wrongs):
    """fires, wrongs: parallel 0/1 arrays. Returns (TPR, FPR, firing, J, precision)."""
    f = np.array(fires, float)
    w = np.array(wrongs, float)
    tpr = f[w == 1].mean() if (w == 1).any() else np.nan
    fpr = f[w == 0].mean() if (w == 0).any() else np.nan
    firing = f.mean()
    prec = w[f == 1].mean() if (f == 1).any() else np.nan
    return tpr, fpr, firing, tpr - fpr, prec


def _boot_J(fires, wrongs, seed=0, n=3000):
    f = np.array(fires, float)
    w = np.array(wrongs, float)
    idx = np.arange(len(f))
    rng = np.random.default_rng(seed)
    js = []
    for _ in range(n):
        s = rng.choice(idx, len(idx), True)
        fs, ws = f[s], w[s]
        if (ws == 1).any() and (ws == 0).any():
            js.append(fs[ws == 1].mean() - fs[ws == 0].mean())
    if not js:
        return (None, None, None)
    return (round(float(np.mean(js)), 4), round(float(np.percentile(js, 2.5)), 4),
            round(float(np.percentile(js, 97.5)), 4))


def _perm_p(fires, wrongs, seed=0, n=3000):
    f = np.array(fires, float)
    w = np.array(wrongs, float)
    if not ((w == 1).any() and (w == 0).any()):
        return None
    obs = f[w == 1].mean() - f[w == 0].mean()
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(n):
        wp = rng.permutation(w)
        if (wp == 1).any() and (wp == 0).any():
            null.append(f[wp == 1].mean() - f[wp == 0].mean())
    null = np.array(null)
    return round(float((null >= obs).mean()), 4)


def _paired_J_diff(firesA, firesB, wrongs, seed=0, n=3000):
    """Bootstrap CI over ITEMS for J(A) - J(B), paired (same items)."""
    fa, fb, w = np.array(firesA, float), np.array(firesB, float), np.array(wrongs, float)
    idx = np.arange(len(w))
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(n):
        s = rng.choice(idx, len(idx), True)
        ws = w[s]
        if (ws == 1).any() and (ws == 0).any():
            ja = fa[s][ws == 1].mean() - fa[s][ws == 0].mean()
            jb = fb[s][ws == 1].mean() - fb[s][ws == 0].mean()
            d.append(ja - jb)
    if not d:
        return (None, None, None)
    return (round(float(np.mean(d)), 4), round(float(np.percentile(d, 2.5)), 4),
            round(float(np.percentile(d, 97.5)), 4))


def analyze():
    items = load_items()
    tfs = load_transforms()
    by_item_tf = {}
    for t in tfs:
        by_item_tf.setdefault(t["item_id"], []).append(t)
    orig = original_answers()
    caches = {m: {arm: _load(m, arm) for arm in ("TF", "SC", "INV", "ENT")} for m in MODELS}
    trace_cache = _load(TRACE_MODEL, "TRACE")

    def wrong_of(m, iid, true):
        a = orig[m][iid]
        if is_non_answer([a]):
            return None
        return not _sym_equal(a, true)

    # build per (model,item) records
    recs = []
    for m in MODELS:
        for it in items:
            iid, true, cat = it["item_id"], it["true_answer"], it["category"]
            w = wrong_of(m, iid, true)
            if w is None:
                continue                              # original is a non-answer -> exclude
            a_orig = orig[m][iid]
            # A1 metamorphic
            viol = 0
            evaln = 0
            for t in by_item_tf.get(iid, []):
                a_t = _tf_answer(caches[m]["TF"], t["relation"], iid)
                rh = relation_holds(a_orig, a_t, t["declared"])
                if rh is None:
                    continue
                evaln += 1
                if not rh:
                    viol += 1
            a1_fire = 1 if viol > 0 else 0
            a1_graded = (viol / evaln) if evaln else None
            # self-consistency (cost-matched: K = #transforms for this item)
            K = len(by_item_tf.get(iid, []))
            sc = _sc_changed(caches[m]["SC"], iid, K)
            sc_fire = None if sc is None else (1 if sc else 0)
            # A2 inversion
            inv_e = caches[m]["INV"].get(iid, {}).get("0")
            a2_fire = None
            if inv_e and not str(inv_e["raw"]).startswith("__ERR__"):
                txt = inv_e["raw"].upper()
                b = extract_boxed(inv_e["raw"]).upper()
                if "INVALID" in b or (b == "" and "INVALID" in txt):
                    a2_fire = 1
                elif "VALID" in b or "VALID" in txt:
                    a2_fire = 0
            # A4 entailment (NoOp): C == A - B ?
            a4_fire = None
            if cat == "ii_noop":
                ent_e = caches[m]["ENT"].get(iid, {}).get("0")
                if ent_e and not str(ent_e["raw"]).startswith("__ERR__"):
                    txt = ent_e["raw"]
                    A = re.search(r"A:\s*(-?\d+)", txt)
                    B = re.search(r"B:\s*(-?\d+)", txt)
                    C = re.search(r"C:\s*(-?\d+)", txt)
                    if A and B and C:
                        a4_fire = 0 if (int(C.group(1)) == int(A.group(1)) - int(B.group(1))) else 1
            # A3 trace (judge-dependent)
            a3_fire = None
            tr_e = trace_cache.get(m + "|" + iid, {}).get("0")
            if tr_e and not str(tr_e["raw"]).startswith("__ERR__"):
                concl = extract_boxed(tr_e["raw"])
                if concl and not is_non_answer([concl]) and not is_non_answer([a_orig]):
                    a3_fire = 0 if _sym_equal(concl, a_orig) else 1
            recs.append({"model": m, "id": iid, "cat": cat, "wrong": 1 if w else 0,
                         "A1": a1_fire, "A1_graded": a1_graded, "SC": sc_fire,
                         "A2": a2_fire, "A4": a4_fire, "A3": a3_fire, "n_tf_eval": evaln})

    def metrics(sub, key, seed):
        s = [r for r in sub if r[key] is not None]
        if not s:
            return None
        fires = [r[key] for r in s]
        wrongs = [r["wrong"] for r in s]
        tpr, fpr, firing, J, prec = _youden(fires, wrongs)
        return {"n": len(s), "n_wrong": int(sum(wrongs)),
                "TPR": None if np.isnan(tpr) else round(float(tpr), 4),
                "FPR": None if np.isnan(fpr) else round(float(fpr), 4),
                "firing_rate": round(float(firing), 4),
                "precision": None if np.isnan(prec) else round(float(prec), 4),
                "J": None if np.isnan(J) else round(float(J), 4),
                "J_boot_ci": _boot_J(fires, wrongs, seed),
                "perm_null_p": _perm_p(fires, wrongs, seed)}

    def by_strata(key, seed):
        return {"ALL": metrics(recs, key, seed),
                "surface_noop": metrics([r for r in recs if r["cat"] in SURFACE_CATS], key, seed + 1),
                "concept_classic": metrics([r for r in recs if r["cat"] in CONCEPT_CATS], key, seed + 2),
                "substitution": metrics([r for r in recs if r["cat"] == "iii_substitution"], key, seed + 3),
                "by_model": {m: metrics([r for r in recs if r["model"] == m], key, seed + 10) for m in MODELS}}

    mechanisms = {k: by_strata(k, 100 + i * 10)
                  for i, k in enumerate(["A1", "SC", "A2", "A4", "A3"])}

    # cost-matched paired A1 vs SC on items where both defined (surface_noop is the key cell)
    def paired(sub, seed):
        s = [r for r in sub if r["A1"] is not None and r["SC"] is not None]
        if not s:
            return None
        return {"n": len(s),
                "J_A1": _boot_J([r["A1"] for r in s], [r["wrong"] for r in s], seed)[0],
                "J_SC": _boot_J([r["SC"] for r in s], [r["wrong"] for r in s], seed)[0],
                "paired_J_diff_A1_minus_SC_ci": _paired_J_diff(
                    [r["A1"] for r in s], [r["SC"] for r in s], [r["wrong"] for r in s], seed)}
    cost_matched = {"ALL": paired(recs, 700),
                    "surface_noop": paired([r for r in recs if r["cat"] in SURFACE_CATS], 710),
                    "concept_classic": paired([r for r in recs if r["cat"] in CONCEPT_CATS], 720)}

    # DECISION (2h) — surface-keyed A1
    surf = mechanisms["A1"]["surface_noop"]
    cm = cost_matched["surface_noop"]
    def gt0(ci):
        return ci and ci[1] is not None and ci[1] > 0
    a1_ci = surf["J_boot_ci"] if surf else None
    live = (surf and a1_ci and a1_ci[1] is not None and a1_ci[0] and surf["J"] is not None
            and a1_ci[1] > 0 and surf["J"] > 0.30 and surf["perm_null_p"] is not None
            and surf["perm_null_p"] < 0.05 and cm and gt0(cm["paired_J_diff_A1_minus_SC_ci"]))
    weak = (surf and a1_ci and a1_ci[1] is not None and a1_ci[1] > 0 and not live)
    dead = (surf and (a1_ci is None or a1_ci[1] is None or a1_ci[1] <= 0))
    case = "A_LIVE" if live else ("A_DEAD" if dead else ("A_WEAK" if weak else "INCONCLUSIVE"))

    # data integrity
    integ = {}
    for m in MODELS:
        for arm in ("TF", "SC", "INV", "ENT"):
            c = caches[m][arm]
            e = sum(1 for k in c for s in c[k] if str(c[k][s].get("raw", "")).startswith("__ERR__"))
            n = sum(len(c[k]) for k in c)
            if e:
                integ[f"{m}|{arm}"] = f"{e}/{n}"

    result = {
        "program": "Channel A Phase 2 — consistency mechanisms. NOT a Route 2 rescue.",
        "config": {"seed": SEED, "models": MODELS, "n_items": len(items),
                   "surface_cats": list(SURFACE_CATS), "concept_cats": list(CONCEPT_CATS),
                   "trace_model": TRACE_MODEL},
        "DECISION": {"case": case,
                     "surface_A1_J": surf["J"] if surf else None,
                     "surface_A1_J_ci": a1_ci, "surface_A1_perm_p": surf["perm_null_p"] if surf else None,
                     "concept_A1_J": mechanisms["A1"]["concept_classic"]["J"] if mechanisms["A1"]["concept_classic"] else None,
                     "cost_matched_A1_minus_SC": cm},
        "DISSOCIATION_A1": {"surface_noop": mechanisms["A1"]["surface_noop"],
                            "concept_classic": mechanisms["A1"]["concept_classic"],
                            "substitution": mechanisms["A1"]["substitution"]},
        "mechanisms": mechanisms,
        "cost_matched_A1_vs_selfconsistency": cost_matched,
        "note_A3_judge_dependent": "A3 uses a second model as judge; reported separately, NOT pooled with A1/A2/A4.",
        "data_integrity": integ or "0 failures",
        "n_records": len(recs),
    }
    RESULT.write_text(json.dumps(result, indent=2))
    return result


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "analyze"
    if cmd == "plan":
        items = load_items()
        tfs = load_transforms()
        nt = len(tfs)
        # per model: TF nt + SC nt + INV ~80 + ENT 40 ; TRACE once ~ 80*4
        per = nt + nt + len(items) + 40
        total = per * len(MODELS) + len(items) * len(MODELS)
        print(f"transforms={nt}; est calls ~= {total} (TF+SC {2*nt}/model + INV {len(items)} + ENT 40 + TRACE)")
        return 0
    if cmd == "generate":
        generate_all()
        return 0
    if cmd == "analyze":
        r = analyze()
        d = r["DECISION"]
        print("DECISION:", d["case"])
        print("  surface(NoOp) A1 J:", d["surface_A1_J"], d["surface_A1_J_ci"], "perm_p", d["surface_A1_perm_p"])
        print("  concept(classic) A1 J:", d["concept_A1_J"])
        print("  cost-matched A1-SC:", d["cost_matched_A1_minus_SC"])
        return 0
    print("usage: consistency_experiment.py [plan|generate|analyze]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
