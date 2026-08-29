"""
Phase 6B — the verification/generation asymmetry. Is CHECKING cheaper/more
reliable than SOLVING? Cross-model verification on cached route2 MATH: for every
ordered (checker C, claimant M!=M), C checks M's cached answer (VALID/INVALID).
The crux is cell (b): does a checker catch errors on problems it CANNOT solve?

Self-inversion (C=M) is the Phase-5 control (cache_ext). NOT a Route 2 rescue.
Reuses route2 canonicalizer + consistency_experiment metric helpers.
"""
from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
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
CACHE = _HERE / "cache_xverify"
EXT = _HERE / "cache_ext"          # Phase-5 self-inversion
R2_CACHE = _R2 / "route2_cache"
RESULT = _HERE / "asymmetry_result.json"
_LOCK = threading.Lock()


@lru_cache(maxsize=None)
def _eq(a, b):
    return _sym_equal(a, b)


def _problems():
    return {p["id"]: p for p in json.loads((_R2 / "problem_set.json").read_text())["problems"]}


def _cand(model):
    d = json.loads((R2_CACHE / f"{_slug(model)}__COT__s1.json").read_text())
    out = {}
    for pid, v in d.items():
        raw = v.get("0", {}).get("raw", "")
        b = extract_boxed(raw) if not str(raw).startswith("__ERR__") else ""
        if b and not is_non_answer([b]):
            out[pid] = b
    return out


def _cp(checker):
    CACHE.mkdir(exist_ok=True)
    return CACHE / f"{_slug(checker)}__XV__s{SEED}.json"


def _load(checker):
    f = _cp(checker)
    return json.loads(f.read_text()) if f.exists() else {}


def generate_all(verbose=True):
    probs = _problems()
    cand = {m: _cand(m) for m in ROSTER}
    for checker in ROSTER:
        cache = _load(checker)
        tasks = []
        for claimant in ROSTER:
            if claimant == checker:
                continue
            for pid, a in cand[claimant].items():
                key = f"{claimant}|{pid}"
                e = cache.get(key)
                if e is not None and not str(e.get("raw", "")).startswith("__ERR__"):
                    continue
                tasks.append((key, inversion_prompt(probs[pid]["problem"], a)))
        if not tasks:
            if verbose:
                print(f"[gen] checker {checker}: cached", flush=True)
            continue
        backend = Route2Backend(checker, FAM[checker], base_url=BASE_URL, api_key=API_KEY)

        def _one(t):
            key, prompt = t
            try:
                raw = backend.generate(prompt, max_new_tokens=700, temperature=0.0, seed=SEED)
            except Exception as e:  # noqa: BLE001
                raw = f"__ERR__:{type(e).__name__}"
            return key, raw
        done = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            for fut in as_completed([ex.submit(_one, t) for t in tasks]):
                key, raw = fut.result()
                with _LOCK:
                    cache[key] = {"raw": raw}
                    done += 1
                    if done % 40 == 0:
                        _cp(checker).write_text(json.dumps(cache))
        _cp(checker).write_text(json.dumps(cache))
        if verbose:
            print(f"[gen] checker {checker}: +{len(tasks)}", flush=True)


def _verdict(raw):
    if raw is None or str(raw).startswith("__ERR__"):
        return None
    bx = extract_boxed(raw).upper()
    tx = raw.upper()
    if "INVALID" in bx or (bx == "" and "INVALID" in tx):
        return 1
    if "VALID" in bx or "VALID" in tx:
        return 0
    return None      # unparsed


def _metrics(fires, wrongs, seed):
    if not fires:
        return None
    tpr, fpr, firing, J, prec = _youden(fires, wrongs)
    lr = (tpr / fpr) if (fpr and not np.isnan(fpr) and fpr > 0) else ("inf" if tpr else None)
    def rnd(x):
        return None if (x is None or (isinstance(x, float) and np.isnan(x))) else round(float(x), 4)
    return {"n": len(fires), "n_wrong": int(sum(wrongs)), "TPR": rnd(tpr), "FPR": rnd(fpr),
            "firing_rate": rnd(np.mean(fires)), "precision": rnd(prec), "J": rnd(J),
            "J_ci": _boot_J(fires, wrongs, seed), "perm_p": _perm_p(fires, wrongs, seed),
            "LR": (lr if isinstance(lr, str) else (None if lr is None else round(lr, 3)))}


def analyze():
    probs = _problems()
    cand = {m: _cand(m) for m in ROSTER}
    # solve correctness per (model, problem)
    solved = {m: {pid: _eq(a, probs[pid]["ref_raw"]) for pid, a in cand[m].items()} for m in ROSTER}
    wrongc = {m: {pid: (not _eq(a, probs[pid]["ref_raw"])) for pid, a in cand[m].items()} for m in ROSTER}

    xcache = {c: _load(c) for c in ROSTER}
    ext = {m: (json.loads((EXT / f"{_slug(m)}__INV__s1.json").read_text()) if (EXT / f"{_slug(m)}__INV__s1.json").exists() else {})
           for m in ROSTER}

    recs = []           # cross-model verify records
    parse_fail = 0
    for checker in ROSTER:
        for claimant in ROSTER:
            if claimant == checker:
                continue
            for pid in cand[claimant]:
                e = xcache[checker].get(f"{claimant}|{pid}")
                v = _verdict(e["raw"]) if e else None
                if e and v is None:
                    parse_fail += 1
                recs.append({"checker": checker, "claimant": claimant, "pid": pid,
                             "fire": v, "wrong": 1 if wrongc[claimant][pid] else 0,
                             "checker_solved": solved[checker].get(pid)})

    def cellJ(sub, seed):
        s = [r for r in sub if r["fire"] is not None]
        return _metrics([r["fire"] for r in s], [r["wrong"] for r in s], seed)

    # per checker + (a)/(b) split
    per_checker = {}
    for i, checker in enumerate(ROSTER):
        sub = [r for r in recs if r["checker"] == checker]
        # cell a = checker solved this problem (natively correct); b = failed
        a = [r for r in sub if r["checker_solved"] is True]
        b = [r for r in sub if r["checker_solved"] is False]
        per_checker[checker.split("/")[-1]] = {
            "solve_acc_on_these": round(float(np.mean([1.0 if solved[checker].get(r["pid"]) else 0.0
                                                       for r in sub])), 4),
            "verify_ALL": cellJ(sub, 100 + i),
            "verify_a_checker_SOLVED": cellJ(a, 200 + i),
            "verify_b_checker_FAILED": cellJ(b, 300 + i)}

    pooled = cellJ(recs, 1)
    pooled_a = cellJ([r for r in recs if r["checker_solved"] is True], 2)
    pooled_b = cellJ([r for r in recs if r["checker_solved"] is False], 3)

    # cross vs self (self = Phase 5 cache_ext), per claimant
    cross_vs_self = {}
    for m in ROSTER:
        self_fires, self_wrong = [], []
        for pid, a in cand[m].items():
            e = ext[m].get(pid)
            v = _verdict(e["raw"]) if e else None
            if v is not None:
                self_fires.append(v)
                self_wrong.append(1 if wrongc[m][pid] else 0)
        cross = [r for r in recs if r["claimant"] == m and r["fire"] is not None]
        cross_vs_self[m.split("/")[-1]] = {
            "self_verify": _metrics(self_fires, self_wrong, 400),
            "cross_verify_pooled_over_checkers": _metrics([r["fire"] for r in cross],
                                                          [r["wrong"] for r in cross], 401)}

    # weak-checks-strong: gemma (weak) checking llama/phi; and every pair J
    pair_J = {}
    for checker in ROSTER:
        for claimant in ROSTER:
            if claimant == checker:
                continue
            sub = [r for r in recs if r["checker"] == checker and r["claimant"] == claimant and r["fire"] is not None]
            if sub:
                pair_J[f"{checker.split('/')[-1]} checks {claimant.split('/')[-1]}"] = {
                    k: _metrics([r["fire"] for r in sub], [r["wrong"] for r in sub], 500).get(k)
                    for k in ("n", "n_wrong", "J", "FPR", "LR", "precision")}

    # DECISION (6B-5): cell (b) J>0.20 CI excludes 0 for >=2 checkers
    b_live = [c for c, v in per_checker.items()
              if v["verify_b_checker_FAILED"] and v["verify_b_checker_FAILED"]["J"] is not None
              and v["verify_b_checker_FAILED"]["J"] > 0.20
              and v["verify_b_checker_FAILED"]["J_ci"][1] is not None
              and v["verify_b_checker_FAILED"]["J_ci"][1] > 0]
    a_pos = [c for c, v in per_checker.items()
             if v["verify_a_checker_SOLVED"] and v["verify_a_checker_SOLVED"]["J_ci"][1] is not None
             and v["verify_a_checker_SOLVED"]["J_ci"][1] > 0]
    if len(b_live) >= 2:
        case = "ASYMMETRY_LIVE"
    elif a_pos and not b_live:
        case = "ASYMMETRY_WEAK"
    elif not a_pos and not b_live:
        case = "ASYMMETRY_DEAD"
    else:
        case = "INCONCLUSIVE_OR_MIXED"

    result = {
        "program": "Phase 6B verification/generation asymmetry. NOT a Route 2 rescue.",
        "DECISION": {"case": case, "checkers_with_cellB_J>0.20_CIexcl0": b_live,
                     "pooled_cell_a_SOLVED": pooled_a, "pooled_cell_b_FAILED": pooled_b},
        "adversarial_note": ("cross-model verify does NOT depend on claimant honesty (claimant "
                             "cannot control the checker), unlike A2 self-inversion; it DOES "
                             "depend on checker honesty (a lazy/colluding always-VALID checker "
                             "-> J=0). A2 self-inversion is gameable (always-VALID optimal; "
                             "mistral/phi-4 exhibit it) and is an honest-agent self-audit, not slashing."),
        "parse_fail_verdict": parse_fail,
        "pooled_cross_verify": pooled,
        "per_checker": per_checker,
        "cross_vs_self_by_claimant": cross_vs_self,
        "weak_checks_strong_all_pairs": pair_J,
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
        d = r["DECISION"]
        print("DECISION:", d["case"])
        print("  pooled cell (a) checker SOLVED:", {k: d["pooled_cell_a_SOLVED"][k] for k in ("n", "J", "J_ci", "FPR", "LR")} if d["pooled_cell_a_SOLVED"] else None)
        print("  pooled cell (b) checker FAILED:", {k: d["pooled_cell_b_FAILED"][k] for k in ("n", "J", "J_ci", "FPR", "LR")} if d["pooled_cell_b_FAILED"] else None)
        print("  checkers with cell-b J>0.20 CI>0:", d["checkers_with_cellB_J>0.20_CIexcl0"])
        for c, v in r["per_checker"].items():
            b = v["verify_b_checker_FAILED"]
            print(f"  {c}: solve_acc={v['solve_acc_on_these']} | verify_b J={b['J'] if b else None} ci={b['J_ci'] if b else None} FPR={b['FPR'] if b else None} n={b['n'] if b else 0}")
        return 0
    print("usage: asymmetry_experiment.py [generate|analyze]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
