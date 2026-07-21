"""
The decisive run — capability-matched cross-family models via Groq, both
batteries, per-pair, per the pre-registration. Resumable (per-model output
cache), deterministic (temperature 0, fixed items).

HONEST SCOPE (fixed by the model menu, not chosen after seeing data):
Groq's chat menu yields at most one *matched* within-family pair, so the
pre-registered within/cross RATIO falsifier (≥3 within pairs) is NOT
evaluable here. This run therefore reports the PRIMARY confound-free
result — cross-family absolute same-bug convergence vs. a permutation null
(code battery) plus tightened TruthfulQA — and states the ratio test as
untested pending more within-family models (OpenRouter).
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
    expected_signature, extract_calls, load_mbpp, run_signature,
    same_bug_convergence,
)

BASE = "https://api.groq.com/openai/v1"
KEY = (Path(__file__).parent / ".env").read_text().split("=", 1)[1].strip()
SEED = 1
N_TQA = 80
N_CODE = 50
BAND = 0.10   # capability band (accuracy points)
MODELS = [  # (id, family) — measure all, compare only the capability band
    ("llama-3.1-8b-instant", "llama"),
    ("llama-3.3-70b-versatile", "llama"),
    ("qwen/qwen3.6-27b", "qwen"),
    ("allam-2-7b", "allam"),
    ("openai/gpt-oss-20b", "gptoss"),
    ("openai/gpt-oss-120b", "gptoss"),
]
CACHE = Path(__file__).parent / "groq_cache"
OUT = Path(__file__).parent / "decisive_result.json"


def _cached(mid: str, kind: str, gen):
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{mid.replace('/', '__')}_{kind}_s{SEED}.json"
    if f.exists():
        return json.loads(f.read_text())
    out = gen()
    f.write_text(json.dumps(out))
    return out


def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


def main() -> int:
    t0 = time.time()
    tqa = load_truthfulqa(n=N_TQA, seed=SEED)
    mbpp = load_mbpp(n=N_CODE, seed=SEED)
    calls = [extract_calls(p["test_list"]) for p in mbpp]
    expected = [expected_signature(c) for c in calls]

    tqa_ans, code_sigs = {}, {}
    for mid, fam in MODELS:
        b = APIBackend(mid, fam, base_url=BASE, api_key=KEY)
        print(f"[run] {mid}: TruthfulQA ...", flush=True)
        tqa_ans[mid] = _cached(mid, "tqa", lambda: [
            _safe(b, "Answer briefly and factually: " + it["question"], 60)
            for it in tqa])
        print(f"[run] {mid}: code ...", flush=True)

        def gen_code():
            sigs = []
            for p, c in zip(mbpp, calls):
                code = _extract_code(_safe(
                    b, f"Write a Python function.\n{p['prompt']}\n"
                       f"Respond with ONLY the code in a python code block.", 400))
                sigs.append(run_signature(code, c) if c else [])
            return sigs
        code_sigs[mid] = _cached(mid, "code", gen_code)
        print(f"[run] {mid}: done ({time.time()-t0:.0f}s)", flush=True)

    emb = Embedder()
    ids = [m for m, _ in MODELS]
    fams = [f for _, f in MODELS]

    # capability: TruthfulQA accuracy + code pass rate
    tqa_acc, code_acc = {}, {}
    for i, mid in enumerate(ids):
        tqa_acc[mid] = float(np.mean([classify_code(a, tqa[q], emb) == "C"
                                      for q, a in enumerate(tqa_ans[mid])]))
        code_acc[mid] = float(np.mean([code_sigs[mid][q] == expected[q]
                                       for q in range(len(expected))]))

    # capability band on each task (models within BAND of the top score)
    def band(acc):
        hi = max(acc.values())
        return [m for m in ids if hi - acc[m] <= BAND]

    tqa_band, code_band = band(tqa_acc), band(code_acc)

    # ---- TruthfulQA tightened convergence over the banded set ----
    bi = [ids.index(m) for m in tqa_band]
    tqa_conv = tightened_convergence([tqa_ans[ids[i]] for i in bi], tqa,
                                     emb, [fams[i] for i in bi], seed=SEED)

    # ---- Code battery same-bug convergence over the banded set + per-pair ----
    ci = [ids.index(m) for m in code_band]
    csig = [code_sigs[ids[i]] for i in ci]
    code_overall = same_bug_convergence(csig, expected, seed=SEED)
    per_pair = []
    for a in range(len(ci)):
        for b_ in range(a + 1, len(ci)):
            r = same_bug_convergence([csig[a], csig[b_]], expected, seed=SEED)
            per_pair.append({"pair": [ids[ci[a]], ids[ci[b_]]],
                             "same_family": fams[ci[a]] == fams[ci[b_]],
                             "same_bug_convergence": r["same_bug_convergence"],
                             "null": r["permutation_null"]})

    out = {
        "config": {"seed": SEED, "n_tqa": N_TQA, "n_code": N_CODE, "band": BAND,
                   "models": ids, "families": fams},
        "capability": {"tqa_accuracy": {m: round(tqa_acc[m], 3) for m in ids},
                       "code_pass_rate": {m: round(code_acc[m], 3) for m in ids},
                       "tqa_band": tqa_band, "code_band": code_band},
        "truthfulqa_tightened": tqa_conv,
        "code_battery": {"overall": code_overall, "per_pair": per_pair},
        "within_family_pairs": sum(p["same_family"] for p in per_pair),
        "cross_family_pairs": sum(not p["same_family"] for p in per_pair),
        "wall_seconds": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(out, indent=2))
    print("\n[run] ===== RESULT =====")
    print(json.dumps(out, indent=2))
    return 0


def _safe(backend, prompt, mx):
    try:
        return backend.generate(prompt, max_new_tokens=mx)
    except Exception as e:
        return f"__ERR__:{type(e).__name__}"


if __name__ == "__main__":
    raise SystemExit(main())
