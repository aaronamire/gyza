"""
Decisive run, wider menu — SAME protocol/metrics as run_groq.py, only the
provider and model list changed (config, not methodology). Capability-
matched same-size same-family pairs across 5 families via OpenRouter, both
batteries (tightened TruthfulQA + code battery), per-pair, capability-
banded exactly as pre-registered. Adds bootstrap confidence intervals over
pairs (requested in the report), computed on the existing convergence
numbers — no new convergence metric.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from rho_measure import APIBackend  # noqa: E402
from truthful import (  # noqa: E402
    Embedder, classify_code, load_truthfulqa, tightened_convergence,
)
from codebench import (  # noqa: E402
    entry_point, expected_signature, extract_calls, load_mbpp, run_signature,
    same_bug_convergence,
)

BASE = "https://openrouter.ai/api/v1"
KEY = [l for l in (Path(__file__).parent / ".env").read_text().splitlines()
       if l.startswith("OPENROUTER")][0].split("=", 1)[1].strip()
SEED = 1
N_TQA = 80
N_CODE = 50
BAND = 0.10
MODELS = [
    ("meta-llama/llama-3.1-70b-instruct", "llama"),
    ("meta-llama/llama-3.3-70b-instruct", "llama"),
    ("google/gemma-2-27b-it", "gemma"),
    ("google/gemma-3-27b-it", "gemma"),
    ("mistralai/mistral-small-24b-instruct-2501", "mistral"),
    ("mistralai/mistral-small-3.1-24b-instruct", "mistral"),
    ("mistralai/mistral-small-3.2-24b-instruct", "mistral"),
    ("qwen/qwen-2.5-72b-instruct", "qwen"),
    ("microsoft/phi-4", "phi"),
]
CACHE = Path(__file__).parent / "or_cache"
OUT = Path(__file__).parent / "decisive_result_openrouter.json"


def _cached(mid, kind, gen):
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{mid.replace('/', '__')}_{kind}_s{SEED}.json"
    if f.exists():
        return json.loads(f.read_text())
    out = gen()
    f.write_text(json.dumps(out))
    return out


def _extract_code(text):
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


def _safe(b, prompt, mx):
    try:
        return b.generate(prompt, max_new_tokens=mx)
    except Exception as e:
        return f"__ERR__:{type(e).__name__}"


def _ci(values, seed=0, n=3000):
    v = np.array([x for x in values if x is not None and not np.isnan(x)])
    if len(v) == 0:
        return (None, None, None)
    rng = np.random.default_rng(seed)
    boot = [rng.choice(v, len(v), replace=True).mean() for _ in range(n)]
    return (round(float(v.mean()), 4), round(float(np.percentile(boot, 2.5)), 4),
            round(float(np.percentile(boot, 97.5)), 4))


def main():
    t0 = time.time()
    tqa = load_truthfulqa(n=N_TQA, seed=SEED)
    mbpp = load_mbpp(n=N_CODE, seed=SEED)
    calls = [extract_calls(p["test_list"]) for p in mbpp]
    expected = [expected_signature(c) for c in calls]

    tqa_ans, code_sigs = {}, {}
    for mid, fam in MODELS:
        b = APIBackend(mid, fam, base_url=BASE, api_key=KEY)
        print(f"[or] {mid}: TruthfulQA ...", flush=True)
        tqa_ans[mid] = _cached(mid, "tqa", lambda b=b: [
            _safe(b, "Answer briefly and factually: " + it["question"], 60) for it in tqa])
        print(f"[or] {mid}: code ...", flush=True)

        def gen_code(b=b):
            sigs = []
            for p, c in zip(mbpp, calls):
                fn = entry_point(p["test_list"])
                name = f" named `{fn}`" if fn else ""
                code = _extract_code(_safe(
                    b, f"Write a Python function{name} for this task:\n{p['prompt']}\n"
                       f"Respond with ONLY the code in a python code block.", 400))
                sigs.append(run_signature(code, c) if c else [])
            return sigs
        code_sigs[mid] = _cached(mid, "code", gen_code)
        print(f"[or] {mid}: done ({time.time()-t0:.0f}s)", flush=True)

    emb = Embedder()
    ids = [m for m, _ in MODELS]
    fams = [f for _, f in MODELS]

    tqa_acc = {m: float(np.mean([classify_code(a, tqa[q], emb) == "C"
                                 for q, a in enumerate(tqa_ans[m])])) for m in ids}
    code_acc = {m: float(np.mean([code_sigs[m][q] == expected[q]
                                  for q in range(len(expected))])) for m in ids}

    def band(acc):
        hi = max(acc.values())
        return [m for m in ids if hi - acc[m] <= BAND]
    tqa_band, code_band = band(tqa_acc), band(code_acc)

    # ---- code battery (PRIMARY): per-pair over the banded set ----
    ci_ = [ids.index(m) for m in code_band]
    csig = {i: code_sigs[ids[i]] for i in ci_}
    code_pairs = []
    for a in range(len(ci_)):
        for b_ in range(a + 1, len(ci_)):
            ia, ib = ci_[a], ci_[b_]
            r = same_bug_convergence([csig[ia], csig[ib]], expected, seed=SEED)
            code_pairs.append({"pair": [ids[ia], ids[ib]],
                               "same_family": fams[ia] == fams[ib],
                               "conv": r["same_bug_convergence"], "null": r["permutation_null"]})

    def split(pairs, key):
        w = [p[key] for p in pairs if p["same_family"]]
        c = [p[key] for p in pairs if not p["same_family"]]
        return w, c
    cw, cc = split(code_pairs, "conv")
    nw, nc = split(code_pairs, "null")

    # ---- TruthfulQA (secondary): per-pair verbatim + semantic ----
    tb = [ids.index(m) for m in tqa_band]
    tqa_pairs = []
    for a in range(len(tb)):
        for b_ in range(a + 1, len(tb)):
            ia, ib = tb[a], tb[b_]
            t = tightened_convergence([tqa_ans[ids[ia]], tqa_ans[ids[ib]]], tqa,
                                      emb, [fams[ia], fams[ib]], seed=SEED)
            same = fams[ia] == fams[ib]
            key = "within" if same else "cross"
            tqa_pairs.append({"pair": [ids[ia], ids[ib]], "same_family": same,
                              "verbatim": t["verbatim"][key], "semantic": t["semantic"][key]})
    vw, vc = split(tqa_pairs, "verbatim")
    sw, sc = split(tqa_pairs, "semantic")

    out = {
        "config": {"seed": SEED, "n_tqa": N_TQA, "n_code": N_CODE, "band": BAND,
                   "provider": "openrouter", "models": ids, "families": fams},
        "capability": {"tqa_accuracy": {m: round(tqa_acc[m], 3) for m in ids},
                       "code_pass_rate": {m: round(code_acc[m], 3) for m in ids},
                       "tqa_band": tqa_band, "code_band": code_band},
        "design": {"within_pairs_code": len(cw), "cross_pairs_code": len(cc),
                   "within_pairs_tqa": len(vw), "cross_pairs_tqa": len(vc)},
        "code_battery_PRIMARY": {
            "within_conv_mean_ci": _ci(cw, seed=1), "cross_conv_mean_ci": _ci(cc, seed=2),
            "within_null_mean": round(float(np.mean(nw)), 4) if nw else None,
            "cross_null_mean": round(float(np.mean(nc)), 4) if nc else None,
            "per_pair": code_pairs},
        "truthfulqa_verbatim": {"within_ci": _ci(vw, seed=3), "cross_ci": _ci(vc, seed=4)},
        "truthfulqa_semantic": {"within_ci": _ci(sw, seed=5), "cross_ci": _ci(sc, seed=6)},
        "tqa_per_pair": tqa_pairs,
        "wall_seconds": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(out, indent=2))
    print("\n[or] ===== RESULT =====")
    print(json.dumps({k: v for k, v in out.items() if k not in ("tqa_per_pair",)
                      and not (k == "code_battery_PRIMARY")}, indent=2))
    print("code within CI:", out["code_battery_PRIMARY"]["within_conv_mean_ci"],
          "cross CI:", out["code_battery_PRIMARY"]["cross_conv_mean_ci"],
          "nulls w/c:", out["code_battery_PRIMARY"]["within_null_mean"],
          out["code_battery_PRIMARY"]["cross_null_mean"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
