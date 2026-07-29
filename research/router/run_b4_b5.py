"""
B4 — does self-assessment work OUTSIDE competence? (the recursive question)
B5 — cross-model routing (gameability)

B4 splits by difficulty. If self-assessment works only on EASY problems —
where routing barely matters because the model succeeds anyway — the router
is a mirage in exactly the shape of Route 3's MIRAGE case.

B5 tests the DEPLOYED configuration: a bonded agent claiming competence on
everything is the optimal strategy, so the router that matters is a
DIFFERENT model predicting the claimant's failure. P sees the problem and
M's identity, never M's answer.

Also records the analytic economy ceiling: a perfect router must escalate at
least recall x base_failure_rate of all claims, so economy <= 1 - r*f. Where
that ceiling is below the preregistered 0.40 bar, the bar is infeasible and
the cell cannot establish DEAD on the economy clause.
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
RECALL = 0.95
BAR = 0.40

# preregistered power floor
MIN_N, MIN_CLASS = 25, 8


def _load_self() -> dict:
    """Re-read the B1 elicitation caches (no new calls)."""
    out = {"math": {}, "mbpp": {}}
    for task, models in (("math", MATH_MODELS), ("mbpp", MBPP_MODELS)):
        for mid in models:
            f = HERE / "r11_cache" / f"self_{task}__{mid.replace('/', '_')}.json"
            out[task][mid] = json.loads(f.read_text())
    return out


def _cells(task: str):
    if task == "math":
        items = load_math_items()
        _, lab, _ = math_outcomes()
        return items, MATH_MODELS, lab
    items, lab = mbpp_outcomes()
    return items, MBPP_MODELS, lab


def _prepare(task, mid, conf, lab, labels):
    n = len(lab)
    keep = [i for i in range(n)
            if lab[i] is not None and conf[i] is not None
            and pop_difficulty(labels, i, mid) is not None]
    return (keep,
            [float(conf[i]) for i in keep],
            [pop_difficulty(labels, i, mid) for i in keep],
            [bool(lab[i]) for i in keep])


def _stat(scores, nullv, y):
    pd = router.paired_delta_ci(scores, nullv, y)
    es = router.economy_at_recall(router.sweep(scores, y), RECALL)
    en = router.economy_at_recall(router.sweep(nullv, y), RECALL)
    f = 1 - (sum(y) / len(y)) if y else None
    return {
        "n": len(y), "n_pos": sum(y), "n_neg": len(y) - sum(y),
        "base_failure": round(f, 4) if f is not None else None,
        "economy_ceiling": round(1 - RECALL * f, 4) if f is not None else None,
        "bar_feasible": (1 - RECALL * f) >= BAR if f is not None else None,
        "auroc_self": pd["auroc_self"], "auroc_null": pd["auroc_null"],
        "delta": pd["delta"], "ci": pd["ci"],
        "economy_self": round(es["economy"], 4) if es else None,
        "economy_null": round(en["economy"], 4) if en else None,
        "UNDERPOWERED": len(y) < MIN_N or sum(y) < MIN_CLASS
                        or (len(y) - sum(y)) < MIN_CLASS,
    }


# ======================================================================
# B4 — strata
# ======================================================================

def b4(selfelic: dict) -> dict:
    res: dict = {"math": {}, "mbpp": {}}

    # ---- MATH: the preregistered difficulty field ----
    items, models, labels = _cells("math")
    for mid in models:
        conf = [r["conf"] for r in selfelic["math"][mid]]
        keep, c, nv, y = _prepare("math", mid, conf, labels[mid], labels)
        per = {}
        for stratum in ("EASY", "HARD"):
            idx = [j for j, i in enumerate(keep)
                   if items[i]["difficulty"] == stratum]
            if not idx:
                continue
            per[stratum] = _stat([c[j] for j in idx], [nv[j] for j in idx],
                                 [y[j] for j in idx])
        res["math"][mid] = per

    # ---- MBPP: pop_difficulty tertiles ----
    items, models, labels = _cells("mbpp")
    for mid in models:
        conf = [r["conf"] for r in selfelic["mbpp"][mid]]
        keep, c, nv, y = _prepare("mbpp", mid, conf, labels[mid], labels)
        order = sorted(range(len(keep)), key=lambda j: nv[j])
        t = len(order) // 3
        bands = {"HARD": order[:t], "MID": order[t:2 * t], "EASY": order[2 * t:]}
        per = {}
        for name, idx in bands.items():
            if not idx:
                continue
            per[name] = _stat([c[j] for j in idx], [nv[j] for j in idx],
                              [y[j] for j in idx])
        res["mbpp"][mid] = per
    return res


# ======================================================================
# B5 — cross-model
# ======================================================================

def b5() -> dict:
    res: dict = {"math": {}, "mbpp": {}, "calls": 0}

    for task, models in (("math", MATH_MODELS), ("mbpp", MBPP_MODELS)):
        items, _, labels = _cells(task)
        text = [(it["problem"] if task == "math" else it["prompt"])
                for it in items]
        for claimant in models:
            lab = labels[claimant]
            for predictor in models:
                if predictor == claimant:
                    continue
                prompts = [router.build_prompt(t, task=task, claimant=claimant)
                           for t in text]
                e = router.Elicitor(predictor)
                tag = (f"cross_{task}__P_{predictor.replace('/', '_')}"
                       f"__M_{claimant.replace('/', '_')}")
                recs = e.run(prompts, tag)
                res["calls"] += e.calls
                conf = [r["conf"] for r in recs]
                keep, c, nv, y = _prepare(task, claimant, conf, lab, labels)
                if not y or all(y) or not any(y):
                    continue
                st = _stat(c, nv, y)
                st["degenerate"] = router.is_degenerate(conf)
                st["parse_rate"] = round(
                    sum(1 for x in conf if x is not None) / len(conf), 4)
                res[task][f"{predictor} -> {claimant}"] = st
                print(f"[b5] {task} {predictor[:28]:<28} -> {claimant[:28]:<28} "
                      f"AUROC {st['auroc_self']} econ {st['economy_self']}",
                      flush=True)
    return res


def main() -> int:
    selfelic = _load_self()

    print("=" * 78)
    print("B4 — EASY / HARD STRATA")
    print("=" * 78)
    r4 = b4(selfelic)
    for task in ("math", "mbpp"):
        print(f"\n--- {task.upper()} ---")
        print(f"{'model':<40} {'stratum':<6} {'n':>3} {'+/-':>7} {'self':>6} "
              f"{'null':>6} {'DELTA':>7} {'econ_s':>7} {'ceil':>6} {'UNDERPWR':>9}")
        for mid, per in r4[task].items():
            for s, v in per.items():
                a = v["auroc_self"]
                b = v["auroc_null"]
                d = v["delta"]
                print(f"{mid[:40]:<40} {s:<6} {v['n']:>3} "
                      f"{str(v['n_pos'])+'/'+str(v['n_neg']):>7} "
                      f"{(a if a is not None else float('nan')):>6.3f} "
                      f"{(b if b is not None else float('nan')):>6.3f} "
                      f"{(d if d is not None else float('nan')):>+7.3f} "
                      f"{(v['economy_self'] if v['economy_self'] is not None else float('nan')):>7.3f} "
                      f"{v['economy_ceiling']:>6.3f} "
                      f"{str(v['UNDERPOWERED']):>9}")

    print("\n" + "=" * 78)
    print("B5 — CROSS-MODEL ROUTING")
    print("=" * 78)
    r5 = b5()

    payload = json.loads(RESULT.read_text())
    payload["b4"] = r4
    payload["b5"] = r5
    RESULT.write_text(json.dumps(payload, indent=2))
    print(f"\nnew cross-model calls: {r5['calls']}")
    print(f"wrote {RESULT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
