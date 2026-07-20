"""
Free-form verifiable-ground-truth pilot — does same-wrong-answer
convergence show up on REAL models, in the format where it is
identifiable? (2-digit x 2-digit multiplication; answer checked exactly.)

This is the design switch from the multiple-choice pilot: no distractors,
huge answer space, so two models producing the SAME specific wrong product
is a strong ABSOLUTE signal (chance collision ~ 0) — and a UNIVERSAL blind
spot becomes visible, which MC hid.

Capability-matched-ish cross-family pair at ~1.5-1.7B (Qwen2.5-1.5B vs
SmolLM2-1.7B) plus a smaller within-family Qwen. Resumable + memory-safe.
Deterministic from SEED.

Run:  ~/dev/marshal/.os/bin/python research/correlated_failure/run_freeform_pilot.py
"""
from __future__ import annotations

import gc
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from rho_measure import (  # noqa: E402
    HFCausalBackend, parse_int, same_wrong_convergence, within_cross,
)

SEED = 0
# --cached: the detectability pilot on already-downloaded tiny models
# (no download; NOT capability-matched — that is for the gate run below).
CACHED_MODELS = [
    ("HuggingFaceTB/SmolLM2-135M-Instruct", "smollm"),
    ("HuggingFaceTB/SmolLM2-360M-Instruct", "smollm"),
    ("Qwen/Qwen2.5-0.5B-Instruct", "qwen"),
]
# default: capability-matched ~1.5-1.7B cross-family pair (needs download)
MATCHED_MODELS = [
    ("Qwen/Qwen2.5-1.5B-Instruct", "qwen"),
    ("HuggingFaceTB/SmolLM2-1.7B-Instruct", "smollm"),
    ("Qwen/Qwen2.5-0.5B-Instruct", "qwen"),
]
if "--cached" in sys.argv:
    MODELS, N_PROBLEMS = CACHED_MODELS, 40
else:
    MODELS, N_PROBLEMS = MATCHED_MODELS, 60
NO_ANSWER = -999999  # sentinel: a distinct 'no integer produced' outcome
OUT = Path(__file__).parent / (
    "freeform_result_cached.json" if "--cached" in sys.argv
    else "freeform_result.json")


def make_problems(n: int, seed: int):
    rng = np.random.default_rng(seed)
    a = rng.integers(12, 99, n)
    b = rng.integers(12, 99, n)
    prompts = [f"What is {int(x)} * {int(y)}? Reply with only the integer.\nAnswer:"
               for x, y in zip(a, b)]
    answers = np.array([int(x) * int(y) for x, y in zip(a, b)], dtype=np.int64)
    return prompts, answers


def main() -> int:
    t0 = time.time()
    prompts, answers = make_problems(N_PROBLEMS, SEED)
    print(f"[ff] {N_PROBLEMS} multiplication problems (seed={SEED})")
    cache_dir = Path(__file__).parent / "ff_cache"
    cache_dir.mkdir(exist_ok=True)

    families = [f for _, f in MODELS]
    rows = []
    for repo, fam in MODELS:
        safe = repo.replace("/", "__")
        cache = cache_dir / f"{safe}_s{SEED}_n{N_PROBLEMS}.npy"
        if cache.exists():
            p = np.load(cache)
            print(f"[ff]   {repo}: cached  acc={float((p==answers).mean()):.3f}")
            rows.append(p)
            continue
        tm = time.time()
        print(f"[ff] loading {repo} ...")
        backend = HFCausalBackend(repo, fam)
        preds = np.empty(N_PROBLEMS, dtype=np.int64)
        for i, prompt in enumerate(prompts):
            v = parse_int(backend.generate(prompt, max_new_tokens=12))
            preds[i] = NO_ANSWER if v is None else v
        np.save(cache, preds)
        rows.append(preds)
        print(f"[ff]   {repo}: acc={float((preds==answers).mean()):.3f}  "
              f"({time.time()-tm:.0f}s)")
        del backend
        gc.collect()

    preds = np.vstack(rows)
    m = preds.shape[0]
    # Diagnostics that catch the failure modes the pilot exposed: a model
    # that emits no parseable answer, or degenerate low-entropy output,
    # cannot carry the measurement — surface it, never silently score it.
    parse_rate = [round(float((rows[i] != NO_ANSWER).mean()), 3) for i in range(m)]
    distinct = [int(len(np.unique(rows[i][rows[i] != NO_ANSWER]))) for i in range(m)]
    Obs, Null = same_wrong_convergence(preds, answers, seed=SEED, invalid=NO_ANSWER)
    w_o, c_o = within_cross(Obs, families)

    def _od(M):
        v = [M[i, j] for i in range(m) for j in range(i + 1, m)]
        return float(np.nanmean(v)) if not all(np.isnan(v)) else float("nan")
    conv, null = _od(Obs), _od(Null)
    usable = all(p > 0.5 for p in parse_rate) and all(d > N_PROBLEMS // 4 for d in distinct)
    out = {
        "config": {"seed": SEED, "n_problems": N_PROBLEMS,
                   "task": "2-digit x 2-digit multiplication",
                   "models": [r for r, _ in MODELS], "families": families},
        "usable": usable,
        "parse_rate": parse_rate,
        "distinct_outputs": distinct,
        "per_model_acc": [round(float((rows[i] == answers).mean()), 3)
                          for i in range(m)],
        "abs_convergence_mean": None if np.isnan(conv) else round(conv, 4),
        "permutation_null_mean": None if np.isnan(null) else round(null, 4),
        "convergence_minus_null": None if (np.isnan(conv) or np.isnan(null))
        else round(conv - null, 4),
        "within_family_convergence": None if np.isnan(w_o) else round(w_o, 4),
        "cross_family_convergence": None if np.isnan(c_o) else round(c_o, 4),
        "obs_matrix": [[None if np.isnan(x) else round(float(x), 3) for x in r]
                       for r in Obs],
        "wall_seconds": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(out, indent=2))
    print("\n[ff] ===== RESULT =====")
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("obs_matrix",)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
