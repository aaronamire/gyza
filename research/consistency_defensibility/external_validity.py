"""
Phase 5 — external validity. Does the surviving primitive (A2 inversion) detect
NATURAL errors, not just the designed attractor fixtures? Uses the cached round-2
MATH COT answers (4 models x 80 competition-math problems, natural errors, known
ground truth). A2 inversion is the ONLY new generation. Metamorphic {T2,T3,T4} is
EXCLUDED for MATH: competition-math transforms cannot have their declared relation
verified with certainty (not templated), per the strict rule — reported as an
exclusion, not guessed.

NOT a Route 2 rescue; the terminal decision stands.
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
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_R2))
sys.path.insert(0, str(_HERE.parent / "correlated_failure"))

from route2_experiment import Route2Backend, extract_boxed, _sym_equal, _slug  # noqa: E402
import route2_experiment as R2  # noqa: E402
from conditional_independence_null import is_non_answer  # noqa: E402
from consistency_experiment import inversion_prompt, _youden, _boot_J, _perm_p  # noqa: E402

SEED = 1
BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = R2.API_KEY
ROSTER = ["meta-llama/llama-3.1-70b-instruct", "google/gemma-2-27b-it",
          "mistralai/mistral-small-3.2-24b-instruct", "microsoft/phi-4"]
FAM = {"meta-llama/llama-3.1-70b-instruct": "llama", "google/gemma-2-27b-it": "gemma",
       "mistralai/mistral-small-3.2-24b-instruct": "mistral", "microsoft/phi-4": "phi"}
CACHE = _HERE / "cache_ext"
R2_CACHE = _R2 / "route2_cache"
RESULT = _HERE / "external_validity_result.json"
_LOCK = threading.Lock()


def _problems():
    ps = json.loads((_R2 / "problem_set.json").read_text())["problems"]
    return {p["id"]: p for p in ps}


def _cand(model):
    d = json.loads((R2_CACHE / f"{_slug(model)}__COT__s1.json").read_text())
    out = {}
    for pid, v in d.items():
        raw = v.get("0", {}).get("raw", "")
        b = extract_boxed(raw) if not str(raw).startswith("__ERR__") else ""
        if b and not is_non_answer([b]):
            out[pid] = b
    return out


def _cp(m):
    CACHE.mkdir(exist_ok=True)
    return CACHE / f"{_slug(m)}__INV__s{SEED}.json"


def _load(m):
    f = _cp(m)
    return json.loads(f.read_text()) if f.exists() else {}


def generate_all(verbose=True):
    probs = _problems()
    for m in ROSTER:
        cand = _cand(m)
        cache = _load(m)
        todo = [pid for pid in cand
                if pid not in cache or str(cache[pid].get("raw", "")).startswith("__ERR__")]
        if not todo:
            if verbose:
                print(f"[gen] {m}: cached ({len(cand)})", flush=True)
            continue
        backend = Route2Backend(m, FAM[m], base_url=BASE_URL, api_key=API_KEY)

        def _one(pid, backend=backend):
            try:
                raw = backend.generate(inversion_prompt(probs[pid]["problem"], cand[pid]),
                                       max_new_tokens=700, temperature=0.0, seed=SEED)
            except Exception as e:  # noqa: BLE001
                raw = f"__ERR__:{type(e).__name__}"
            return pid, raw
        done = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            for fut in as_completed([ex.submit(_one, pid) for pid in todo]):
                pid, raw = fut.result()
                with _LOCK:
                    cache[pid] = {"raw": raw}
                    done += 1
                    if done % 30 == 0:
                        _cp(m).write_text(json.dumps(cache))
        _cp(m).write_text(json.dumps(cache))
        if verbose:
            print(f"[gen] {m}: +{len(todo)}", flush=True)


def analyze():
    probs = _problems()
    recs = []
    parse_fail = 0
    for m in ROSTER:
        cand = _cand(m)
        inv = _load(m)
        for pid, a in cand.items():
            ref = probs[pid]["ref_raw"]
            wrong = 0 if _sym_equal(a, ref) else 1
            e = inv.get(pid)
            fire = None
            if e and not str(e["raw"]).startswith("__ERR__"):
                bx = extract_boxed(e["raw"]).upper()
                tx = e["raw"].upper()
                if "INVALID" in bx or (bx == "" and "INVALID" in tx):
                    fire = 1
                elif "VALID" in bx or "VALID" in tx:
                    fire = 0
                else:
                    parse_fail += 1
            recs.append({"model": m, "id": pid, "wrong": wrong, "fire": fire})

    def metrics(sub):
        s = [r for r in sub if r["fire"] is not None]
        if not s:
            return None
        f = [r["fire"] for r in s]
        w = [r["wrong"] for r in s]
        tpr, fpr, firing, J, prec = _youden(f, w)
        lr = (tpr / fpr) if (fpr and not np.isnan(fpr) and fpr > 0) else ("inf" if tpr else None)
        def rnd(x):
            return None if (x is None or (isinstance(x, float) and np.isnan(x))) else round(float(x), 4)
        return {"n": len(s), "n_wrong": int(sum(w)), "base_rate_wrong": rnd(np.mean(w)),
                "TPR": rnd(tpr), "FPR": rnd(fpr), "firing_rate": rnd(firing), "precision": rnd(prec),
                "J": rnd(J), "J_ci": _boot_J(f, w, 1), "perm_p": _perm_p(f, w, 1),
                "LR": (lr if isinstance(lr, str) else (None if lr is None else round(lr, 3)))}

    pooled = metrics(recs)
    by_model = {m: metrics([r for r in recs if r["model"] == m]) for m in ROSTER}
    result = {
        "program": "Channel A Phase 5 external validity (A2 inversion on natural MATH errors). NOT a Route 2 rescue.",
        "excluded_metamorphic": ("{T2,T3,T4} metamorphic NOT run on MATH: competition-math "
                                 "transforms cannot have their declared relation verified with "
                                 "certainty (not templated). Excluded per the strict rule, not guessed."),
        "n_records": len(recs), "n_evaluable": sum(1 for r in recs if r["fire"] is not None),
        "parse_fail_verdict": parse_fail,
        "A2_inversion_MATH_pooled": pooled,
        "A2_inversion_MATH_by_model": by_model,
        "fixture_family_comparison": {"A2_surface_J": 0.531, "A2_surface_FPR": 0.0148,
                                      "A2_surface_LR": 36.8, "A2_surface_precision": 0.857},
    }
    RESULT.write_text(json.dumps(result, indent=2, default=str))
    return result


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "analyze"
    if cmd == "generate":
        generate_all()
        return 0
    if cmd == "analyze":
        r = analyze()
        p = r["A2_inversion_MATH_pooled"]
        print("A2 inversion on natural MATH errors (pooled):")
        print(f"  n={p['n']} wrong={p['n_wrong']} base_rate={p['base_rate_wrong']}")
        print(f"  TPR={p['TPR']} FPR={p['FPR']} firing={p['firing_rate']} precision={p['precision']} LR={p['LR']} J={p['J']} {p['J_ci']} perm_p={p['perm_p']}")
        print("  vs fixture family: A2 surface J=0.531 FPR=0.015 LR=36.8 precision=0.857")
        print("  by model:", {m.split('/')[-1]: (v and {'J': v['J'], 'FPR': v['FPR'], 'LR': v['LR'], 'prec': v['precision']}) for m, v in r["A2_inversion_MATH_by_model"].items()})
        return 0
    print("usage: external_validity.py [generate|analyze]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
