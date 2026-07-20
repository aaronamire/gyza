"""
TruthfulQA misconception-convergence pilot — the RIGHT task class, real
models. Do DIFFERENT model families converge on the SAME known-false
answer above chance? Resumable (per-model answer cache), deterministic.

--cached: the detectability pilot on already-downloaded small models
(SmolLM 135M/360M + Qwen 0.5B; two families, not capability-matched).
default: capability-matched families (needs download).
"""
from __future__ import annotations

import gc
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from rho_measure import HFCausalBackend  # noqa: E402
from truthful import (  # noqa: E402
    Embedder, code_matrix, load_truthfulqa, measure_misconception_convergence,
)

SEED = 1
CACHED = [("HuggingFaceTB/SmolLM2-135M-Instruct", "smollm"),
          ("HuggingFaceTB/SmolLM2-360M-Instruct", "smollm"),
          ("Qwen/Qwen2.5-0.5B-Instruct", "qwen")]
MATCHED = [("Qwen/Qwen2.5-1.5B-Instruct", "qwen"),
           ("HuggingFaceTB/SmolLM2-1.7B-Instruct", "smollm"),
           ("microsoft/Phi-3.5-mini-instruct", "phi")]
if "--cached" in sys.argv:
    MODELS, N = CACHED, 60
else:
    MODELS, N = MATCHED, 100
OUT = Path(__file__).parent / ("truthful_result_cached.json" if "--cached" in sys.argv
                               else "truthful_result.json")


def main() -> int:
    t0 = time.time()
    items = load_truthfulqa(n=N, seed=SEED)
    print(f"[tq] {len(items)} TruthfulQA items (seed={SEED})")
    cache = Path(__file__).parent / "tq_cache"
    cache.mkdir(exist_ok=True)

    families = [f for _, f in MODELS]
    answers = []
    for repo, fam in MODELS:
        cf = cache / f"{repo.replace('/', '__')}_s{SEED}_n{N}.json"
        if cf.exists():
            a = json.loads(cf.read_text())
            print(f"[tq]   {repo}: cached ({len(a)} answers)")
            answers.append(a)
            continue
        tm = time.time()
        print(f"[tq] loading {repo} ...")
        m = HFCausalBackend(repo, fam)
        a = [m.generate("Answer briefly and factually: " + it["question"],
                        max_new_tokens=40, chat=True).strip().replace("\n", " ")
             for it in items]
        cf.write_text(json.dumps(a))
        answers.append(a)
        print(f"[tq]   {repo}: done ({time.time()-tm:.0f}s)")
        del m
        gc.collect()

    print("[tq] classifying answers with MiniLM ...")
    emb = Embedder()
    preds, ans = code_matrix(answers, items, emb)
    res = measure_misconception_convergence(preds, ans, families, seed=SEED)

    # per-model coherence: correct / misconception / other
    def breakdown(row):
        c = Counter("C" if x == "C" else ("I" if str(x).startswith("I") else "O")
                    for x in row)
        n = len(row)
        return {"correct": round(c["C"]/n, 3), "misconception": round(c["I"]/n, 3),
                "other": round(c["O"]/n, 3)}
    per_model = {MODELS[i][0]: breakdown(preds[i]) for i in range(len(MODELS))}

    out = {"config": {"seed": SEED, "n_items": N, "task": "TruthfulQA-generation",
                      "models": [r for r, _ in MODELS], "families": families},
           "per_model": per_model, "convergence": res,
           "wall_seconds": round(time.time()-t0, 1)}
    OUT.write_text(json.dumps(out, indent=2))
    print("\n[tq] ===== RESULT =====")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
