"""
B1 — elicitation (self-assessment), and B2 — the population-difficulty null.

B1 asks each model, BEFORE any solution attempt and seeing only the problem
statement, for a single integer 0-100: its confidence it would answer
correctly. max_tokens=50, temp 0, no reasoning permitted (GATE 0d).

B2 scores that confidence against a predictor that uses ZERO self-knowledge:
`pop_difficulty(q, M)` = the fraction of the OTHER models that solved q. The
PAIRED DELTA between the two AUROCs is the self-knowledge signal, and it is
the headline. A raw AUROC without it is uninterpretable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import router  # noqa: E402
from data import (  # noqa: E402
    MATH_MODELS, MBPP_MODELS, load_math_items, math_outcomes, mbpp_outcomes,
    pop_difficulty,
)

HERE = Path(__file__).resolve().parent
RESULT = HERE / "r11_result.json"

# Cached solutions were generated with these caps. MATH COT text IS cached, so
# its length is measurable; MBPP program text is NOT cached (R8 GATE 0b), so
# only the cap is available and is reported as an upper BOUND.
MBPP_SOLUTION_TOKEN_CAP = 400
CHARS_PER_TOKEN = 4.0   # disclosed estimate; no tokenizer for the cached text


def _mbpp_prompt_text(it: dict) -> str:
    return it["prompt"]


def elicit_self() -> dict:
    out: dict = {"math": {}, "mbpp": {}, "tokens": {}}

    math_items = load_math_items()
    mbpp_items, _ = mbpp_outcomes()

    tot_calls = 0
    ptok = ctok = 0

    for mid in MATH_MODELS:
        prompts = [router.build_prompt(it["problem"], task="math")
                   for it in math_items]
        e = router.Elicitor(mid)
        tag = f"self_math__{mid.replace('/', '_')}"
        recs = e.run(prompts, tag)
        out["math"][mid] = recs
        tot_calls += e.calls
        ptok += e.prompt_tokens
        ctok += e.completion_tokens
        parsed = sum(1 for r in recs if r["conf"] is not None)
        print(f"[b1] MATH {mid:<42} parsed {parsed}/{len(recs)}", flush=True)

    for mid in MBPP_MODELS:
        prompts = [router.build_prompt(_mbpp_prompt_text(it), task="mbpp")
                   for it in mbpp_items]
        e = router.Elicitor(mid)
        tag = f"self_mbpp__{mid.replace('/', '_')}"
        recs = e.run(prompts, tag)
        out["mbpp"][mid] = recs
        tot_calls += e.calls
        ptok += e.prompt_tokens
        ctok += e.completion_tokens
        parsed = sum(1 for r in recs if r["conf"] is not None)
        print(f"[b1] MBPP {mid:<42} parsed {parsed}/{len(recs)}", flush=True)

    out["tokens"] = {"new_calls": tot_calls, "prompt_tokens": ptok,
                     "completion_tokens": ctok}
    return out


def token_economy(elic: dict) -> dict:
    """Mean prediction tokens vs mean cached solution tokens — first class."""
    _, _, raws = math_outcomes()
    math_sol_chars = [len(r) for m in MATH_MODELS for r in raws[m]]
    mean_sol_tok_math = (sum(math_sol_chars) / len(math_sol_chars)) / CHARS_PER_TOKEN

    pred_ctok, pred_ptok = [], []
    for task in ("math", "mbpp"):
        for _m, recs in elic[task].items():
            pred_ctok += [r.get("ctok", 0) for r in recs]
            pred_ptok += [r.get("ptok", 0) for r in recs]
    mp = sum(pred_ctok) / max(1, len(pred_ctok))
    mpp = sum(pred_ptok) / max(1, len(pred_ptok))
    return {
        "mean_prediction_completion_tokens": round(mp, 2),
        "mean_prediction_prompt_tokens": round(mpp, 2),
        "mean_cached_solution_tokens_MATH_est": round(mean_sol_tok_math, 1),
        "solution_token_estimate_method":
            f"cached COT chars / {CHARS_PER_TOKEN} (no tokenizer for cached text)",
        "mbpp_solution_tokens": f"NOT MEASURABLE — program text not cached "
                                f"(R8 GATE 0b); generation cap was "
                                f"{MBPP_SOLUTION_TOKEN_CAP} (upper bound)",
        "ratio_solution_over_prediction_MATH":
            round(mean_sol_tok_math / mp, 1) if mp else None,
    }


def analyse(elic: dict) -> dict:
    res: dict = {"math": {}, "mbpp": {}}

    math_items = load_math_items()
    _, math_lab, _ = math_outcomes()
    mbpp_items, mbpp_lab = mbpp_outcomes()

    for task, models, labels, n in (
            ("math", MATH_MODELS, math_lab, len(math_items)),
            ("mbpp", MBPP_MODELS, mbpp_lab, len(mbpp_items))):
        for mid in models:
            recs = elic[task][mid]
            conf = [r["conf"] for r in recs]
            lab = labels[mid]

            # exclude UNRESOLVED outcomes and unparseable predictions
            keep = [i for i in range(n)
                    if lab[i] is not None and conf[i] is not None
                    and pop_difficulty(labels, i, mid) is not None]
            c = [float(conf[i]) for i in keep]
            nullv = [pop_difficulty(labels, i, mid) for i in keep]
            y = [bool(lab[i]) for i in keep]

            comb = router.rank_average(c, nullv)
            pd = router.paired_delta_ci(c, nullv, y)
            pd_comb = router.paired_delta_ci(comb, nullv, y)

            from collections import Counter
            dist = Counter(x for x in conf if x is not None)

            res[task][mid] = {
                "n_items": n,
                "parse_rate": round(sum(1 for x in conf if x is not None) / n, 4),
                "n_used": len(keep),
                "base_rate_correct": round(sum(y) / len(y), 4) if y else None,
                "confidence": {
                    "mean": round(sum(c) / len(c), 2) if c else None,
                    "min": min(c) if c else None,
                    "max": max(c) if c else None,
                    "distinct": len(dist),
                    "top5": dist.most_common(5),
                    "DEGENERATE": router.is_degenerate(conf),
                },
                "auroc_self": pd["auroc_self"],
                "auroc_null": pd["auroc_null"],
                "paired_delta": pd["delta"],
                "delta_ci": pd["ci"],
                "combined_vs_null_delta": pd_comb["delta"],
                "combined_vs_null_ci": pd_comb["ci"],
                "economy_self": {
                    str(t): router.economy_at_recall(router.sweep(c, y), t)
                    for t in (0.90, 0.95, 0.99)},
                "economy_null": {
                    str(t): router.economy_at_recall(router.sweep(nullv, y), t)
                    for t in (0.90, 0.95, 0.99)},
            }
    return res


def main() -> int:
    print("=" * 78)
    print("B1 — ELICITATION (self-assessment)   max_tokens=50, temp 0, no CoT")
    print("=" * 78)
    elic = elicit_self()

    print("\n" + "=" * 78)
    print("TOKEN ECONOMY (GATE 0d)")
    print("=" * 78)
    te = token_economy(elic)
    for k, v in te.items():
        print(f"  {k:<45} {v}")

    print("\n" + "=" * 78)
    print("B2 — THE POPULATION-DIFFICULTY NULL")
    print("=" * 78)
    res = analyse(elic)

    for task in ("math", "mbpp"):
        print(f"\n--- {task.upper()} ---")
        print(f"{'model':<42} {'used':>4} {'base':>6} {'conf':>6} {'dst':>4} "
              f"{'DEG':>5} {'self':>6} {'null':>6} {'DELTA':>7} {'95% CI':>18}")
        for mid, r in res[task].items():
            ci = r["delta_ci"]
            cis = f"[{ci[0]:+.3f},{ci[1]:+.3f}]" if ci else "n/a"
            print(f"{mid:<42} {r['n_used']:>4} {r['base_rate_correct']:>6.3f} "
                  f"{r['confidence']['mean'] or 0:>6.1f} "
                  f"{r['confidence']['distinct']:>4} "
                  f"{str(r['confidence']['DEGENERATE']):>5} "
                  f"{r['auroc_self'] if r['auroc_self'] is not None else float('nan'):>6.3f} "
                  f"{r['auroc_null'] if r['auroc_null'] is not None else float('nan'):>6.3f} "
                  f"{r['paired_delta'] if r['paired_delta'] is not None else float('nan'):>+7.3f} "
                  f"{cis:>18}")

    payload = {"b1_tokens": te, "b2": res,
               "elicitation_meta": elic.get("tokens", {})}
    RESULT.write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {RESULT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
