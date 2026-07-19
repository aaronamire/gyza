"""
Stage-7 pilot — a FIRST real cross-family error-correlation measurement.

Deterministic from (seed, N, model list). Loads a real benchmark
(ARC-Easy), runs a few small ungated models across two families on CPU
by multiple-choice logprob, and reports within- vs cross-family error
correlation plus the shared-wrong-answer rate.

HONEST SCOPE: this is a PILOT on tiny models (135M–0.5B), not the
decision-gate. Tiny models are weak and may have atypical error
structure; the number here proves the pipeline and gives a first signal,
not a verdict. The real gate wants stronger cross-family models (local
0.5–3B with patience, or free API tiers).

Run:  ~/dev/marshal/.os/bin/python research/correlated_failure/run_pilot.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from rho_measure import HFCausalBackend, Question, measure  # noqa: E402

SEED = 0
N_QUESTIONS = 120
MODELS = [
    ("HuggingFaceTB/SmolLM2-135M-Instruct", "smollm"),
    ("HuggingFaceTB/SmolLM2-360M-Instruct", "smollm"),
    ("Qwen/Qwen2.5-0.5B-Instruct", "qwen"),
]
OUT = Path(__file__).parent / "pilot_result.json"


def load_arc(n: int, seed: int) -> list[Question]:
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq

    path = hf_hub_download(
        repo_id="allenai/ai2_arc",
        filename="ARC-Easy/test-00000-of-00001.parquet", repo_type="dataset",
    )
    rows = pq.read_table(path).to_pylist()
    qs: list[Question] = []
    for r in rows:
        labels = list(r["choices"]["label"])
        texts = list(r["choices"]["text"])
        if r["answerKey"] not in labels:
            continue
        prompt = r["question"] + "\n" + "\n".join(
            f"{lab}. {t}" for lab, t in zip(labels, texts))
        qs.append(Question(r["id"], prompt, tuple(texts), labels.index(r["answerKey"])))
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(qs))[:n]
    return [qs[i] for i in sorted(idx)]


def main() -> int:
    t0 = time.time()
    print(f"[pilot] loading {N_QUESTIONS} ARC-Easy questions (seed={SEED})")
    questions = load_arc(N_QUESTIONS, SEED)
    print(f"[pilot] {len(questions)} questions loaded")

    families = [fam for _, fam in MODELS]
    answers = np.array([q.answer_idx for q in questions])
    cache_dir = Path(__file__).parent / "preds_cache"
    cache_dir.mkdir(exist_ok=True)
    preds_rows = []
    for repo, fam in MODELS:
        safe = repo.replace("/", "__")
        cache = cache_dir / f"{safe}_s{SEED}_n{N_QUESTIONS}.npy"
        if cache.exists():   # resumable: skip a model already predicted
            p = np.load(cache)
            print(f"[pilot]   {repo}: cached  acc={float((p==answers).mean()):.3f}")
            preds_rows.append(p)
            continue
        tm = time.time()
        print(f"[pilot] loading {repo} ...")
        backend = HFCausalBackend(repo, fam)
        print(f"[pilot]   loaded in {time.time()-tm:.0f}s, predicting ...")
        p = backend.predict(questions)
        np.save(cache, p)                      # persist before we can be killed
        preds_rows.append(p)
        print(f"[pilot]   {repo}: acc={float((p==answers).mean()):.3f}  "
              f"({time.time()-tm:.0f}s)")
        # free memory between models on this low-RAM machine
        import gc
        del backend
        gc.collect()

    preds = np.vstack(preds_rows)
    res = measure(preds, families, questions)
    out = {
        "config": {"seed": SEED, "n_questions": len(questions),
                   "models": [m for m, _ in MODELS], "families": families,
                   "benchmark": "ARC-Easy"},
        "result": res.to_dict(),
        "pairwise_corr": [[None if np.isnan(x) else round(float(x), 4)
                           for x in row] for row in res.corr],
        "wall_seconds": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(out, indent=2))
    print("\n[pilot] ===== RESULT =====")
    print(json.dumps(out["result"], indent=2))
    print(f"[pilot] within-family rho={out['result']['mean_within_family_rho']}  "
          f"cross-family rho={out['result']['mean_cross_family_rho']}  "
          f"shared_wrong={out['result']['shared_wrong_rate']}")
    print(f"[pilot] wrote {OUT} in {out['wall_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
