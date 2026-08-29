"""Part C — stochastic MBPP outcomes: K=5 samples at temperature 0.7.

SUBSTRATE. The 50 MBPP problems of the decisive run (seed 1), whose verdicts
are EXECUTED asserts, not compared labels -- the same external ground truth
`mbpp_truth.json` re-derived (agreement 0.9439, false_wrong 11, false_correct 0,
one-directional). The generation prompt is imported VERBATIM from
`native_verifier.code_prompt` so this arm is comparable to the temperature-0
arm it extends.

WHY NOT route3_attractor's intact K=4 arm: its `items.json` is program-authored
(hand-perturbed Monty Hall variants with hand-computed answers). Its ground
truth is internal. Using it would reproduce the exact self-authorship trap this
corpus exists to avoid, and that reasoning does not change because credits
turned out to exist.

AN ERROR IS NOT A VALUE. A generation that fails is recorded as `__ERR__` and is
EXCLUDED from the variance profile. It is never counted as a failing sample --
that conflation is artifact #16, where an exception written into the measurement
channel reported 0% against a true 86.7%.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "native_verifier"))
sys.path.insert(0, str(ROOT / "research" / "correlated_failure"))
sys.path.insert(0, str(ROOT / "research" / "selection_routes"))

import native_verifier as V                     # noqa: E402
from codebench import entry_point               # noqa: E402
from mbpp_truth import run as run_asserts       # noqa: E402

MODELS = ["mistralai/mistral-small-24b-instruct-2501", "microsoft/phi-4",
          "meta-llama/llama-3.1-70b-instruct", "google/gemma-2-27b-it"]
K = 5
TEMP = 0.7
BASE = "https://openrouter.ai/api/v1/chat/completions"
CACHE = HERE / "c_cache"
_lock = threading.Lock()
_usage = {"prompt": 0, "completion": 0, "calls": 0, "errors": 0}


def _key() -> str:
    for line in (ROOT / "research" / "correlated_failure" / ".env").read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no OPENROUTER_API_KEY")


def _call(key, model, prompt):
    body = json.dumps({"model": model, "temperature": TEMP, "max_tokens": 600,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        BASE, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            u = d.get("usage") or {}
            with _lock:
                _usage["prompt"] += u.get("prompt_tokens", 0)
                _usage["completion"] += u.get("completion_tokens", 0)
                _usage["calls"] += 1
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code == 402:                    # out of credits -- do not retry
                raise SystemExit("HTTP 402: out of credits mid-run. STOPPING.")
            if e.code in (429, 502, 503, 524) and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            return f"__ERR__:HTTP{e.code}"
        except Exception as ex:                  # noqa: BLE001
            if attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            return f"__ERR__:{type(ex).__name__}"
    return "__ERR__:retries"


def generate():
    key = _key()
    CACHE.mkdir(exist_ok=True)
    mbpp = V.load_mbpp(n=V.N_CODE, seed=V.SEED)
    prompts = [V.code_prompt(p, entry_point(p["test_list"])) for p in mbpp]

    for model in MODELS:
        f = CACHE / (model.replace("/", "__") + f"__K{K}.json")
        cache = json.loads(f.read_text()) if f.exists() else {}
        todo = [(i, k) for i in range(len(mbpp)) for k in range(K)
                if "__ERR__" in cache.get(str(i), {}).get(str(k), "__ERR__:missing")]
        print(f"{model}: {len(todo)} generations to run", flush=True)
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_call, key, model, prompts[i]): (i, k) for i, k in todo}
            for n, fu in enumerate(futs, 1):
                pass
            for fu, (i, k) in futs.items():
                out = fu.result()
                if "__ERR__" in out:
                    with _lock:
                        _usage["errors"] += 1
                cache.setdefault(str(i), {})[str(k)] = out
        f.write_text(json.dumps(cache, indent=1))
        print(f"  cached -> {f.name}", flush=True)


def score():
    """Per-sample outcome, EXECUTED. Never an aggregate -- SR-4's whole question
    is which samples succeeded and which failed."""
    mbpp = V.load_mbpp(n=V.N_CODE, seed=V.SEED)
    records, profile = [], {}
    for model in MODELS:
        f = CACHE / (model.replace("/", "__") + f"__K{K}.json")
        if not f.exists():
            continue
        cache = json.loads(f.read_text())
        for i in range(len(mbpp)):
            outs = []
            for k in range(K):
                raw = cache.get(str(i), {}).get(str(k), "__ERR__:missing")
                if "__ERR__" in raw:
                    outs.append(None)            # error, NOT a failure
                    continue
                src = V._extract_block(raw)
                outs.append(bool(run_asserts(src, mbpp[i]["test_list"])))
            records.append({"model": model, "problem_idx": i, "K": K,
                            "temperature": TEMP,
                            "per_sample_outcome": outs,
                            "n_error": sum(o is None for o in outs),
                            "outcome_source": "MBPP asserts EXECUTED (external)"})
    valid = [r for r in records if r["n_error"] == 0]
    agree = [r for r in valid if len(set(r["per_sample_outcome"])) == 1]
    differ = [r for r in valid if len(set(r["per_sample_outcome"])) > 1]
    profile = {
        "n_task_model_pairs": len(records),
        "n_complete": len(valid),
        "n_dropped_for_error": len(records) - len(valid),
        "all_K_agree": len(agree),
        "samples_differ": len(differ),
        "differing_fraction": round(len(differ) / len(valid), 4) if valid else None,
        "all_agree_all_pass": sum(1 for r in agree if r["per_sample_outcome"][0]),
        "all_agree_all_fail": sum(1 for r in agree if not r["per_sample_outcome"][0]),
    }
    (HERE / "stochastic.json").write_text(json.dumps(
        {"config": {"models": MODELS, "K": K, "temperature": TEMP,
                    "n_problems": len(mbpp), "seed": V.SEED},
         "variance_profile": profile, "records": records}, indent=1))
    return profile


if __name__ == "__main__":
    if "--score-only" not in sys.argv:
        generate()
        print("USAGE:", json.dumps(_usage))
    print("VARIANCE PROFILE:", json.dumps(score(), indent=1))
