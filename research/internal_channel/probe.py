"""The probe, and — the part that is actually the experiment — the SPLIT.

THE DESIGN QUESTION, AND WHERE THE OBVIOUS DESIGN BREAKS. 1.E asks whether the
channel transfers OUTSIDE the model's competence: train where the model is
competent, test where it is not. Stated as "train on SOLVED, test on UNSOLVED"
that is not runnable — each partition is single-class, and AUROC is undefined
on a single class. Splitting on the LABEL cannot produce a partition that has
labels to score.

So competence is stratified on an axis that is INDEPENDENT OF THE LABEL and
independent of the model: the syntactic complexity of MBPP's OWN reference
solution (`code`), counted in AST nodes. It is a property of the benchmark,
computed before any generation, and it cannot leak the model's outcome.

    EASY  = reference complexity below the median  -> the competent region
    HARD  = at or above the median                 -> outside it

    TRAIN     = 70% of EASY      (probe never sees TEST-IN or TEST-OUT)
    TEST-IN   = 30% of EASY      in-competence generalisation
    TEST-OUT  = ALL of HARD      out-of-competence transfer  <- the question

Both partitions retain both classes, so AUROC is defined on each, and the
decision rule maps onto them directly: strong on TEST-IN and chance on
TEST-OUT is the competence bound holding internally.

THE STRATIFICATION HAS A PRECONDITION AND IT IS CHECKED, NOT ASSUMED: if the
EASY and HARD pass rates do not differ, the axis is not measuring competence
and the transfer question is unanswerable by it. That check runs first and
reports INCONCLUSIVE if it fails.

WHY THE PROBLEM-LEVEL SPLIT HOLDS BY CONSTRUCTION. Each problem contributes
EXACTLY ONE (activation, label) pair — the final-token state, or the mean over
generated tokens. There is no second example from the same problem that could
land on the other side of the split. That is an architectural guarantee rather
than a discipline item, which is this program's standing preference; it is
asserted anyway in test_split.py, with a negative control showing the
assertion fires when a leak is injected.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
SEED = 1
N_BOOT = 2000
N_PERM = 3000
DIST_FEATURES = ["mean_logprob", "min_logprob", "sum_logprob",
                 "mean_entropy", "max_entropy"]


def make_split(rows: list[dict], seed: int = SEED) -> dict[str, list[dict]]:
    """EASY/HARD by reference complexity, then 70/30 within EASY.

    Extracted so test_split.py exercises THE SAME function the experiment
    runs. A test against a reimplemented split would assert nothing about the
    split that produced the numbers.
    """
    med = float(np.median([r["cx"] for r in rows]))
    easy = [r for r in rows if r["cx"] < med]
    hard = [r for r in rows if r["cx"] >= med]
    idx = np.random.default_rng(seed).permutation(len(easy))
    cut = int(0.7 * len(easy))
    return {"TRAIN": [easy[i] for i in idx[:cut]],
            "TEST-IN": [easy[i] for i in idx[cut:]],
            "TEST-OUT": hard}


def check_split(parts: dict[str, list[dict]], n_total: int) -> None:
    """Raise if any problem id appears in two partitions, or any is lost.

    THE SPLIT IS THE EXPERIMENT: if it leaks, every number downstream measures
    memorisation. This runs at experiment time, not only under pytest.
    """
    ids = {k: {r["task_id"] for r in v} for k, v in parts.items()}
    keys = sorted(ids)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            overlap = ids[a] & ids[b]
            if overlap:
                raise AssertionError(
                    f"LEAK: {a} n {b} share {len(overlap)} problem ids "
                    f"(e.g. {sorted(overlap)[:5]})")
    seen = sum(len(v) for v in ids.values())
    if seen != n_total:
        raise AssertionError(f"partition not exhaustive: {seen} != {n_total}")


def complexity(code: str) -> int:
    """Reference-solution complexity: AST node count. Label-independent."""
    try:
        return sum(1 for _ in ast.walk(ast.parse(code)))
    except SyntaxError:
        return len(code.split())


def load(gen_dir: Path) -> list[dict]:
    meta = {json.loads(l)["task_id"]: json.loads(l)
            for l in (gen_dir / "meta.jsonl").open() if l.strip()}
    labels = {r["task_id"]: r for r in json.loads((gen_dir / "labels.json").read_text())}
    rows = []
    for tid, m in sorted(meta.items()):
        act = gen_dir / f"act_{tid}.npz"
        if tid not in labels or not act.exists() or m["dist"] is None:
            continue
        z = np.load(act)
        rows.append({
            "task_id": tid,
            "y": int(labels[tid]["label"] == "PASS"),
            "mode": labels[tid]["mode"],
            "final": z["final"].astype(np.float32),
            "mean": z["mean"].astype(np.float32),
            "cx": complexity(m["reference_code"]),
            "n_gen": m["n_gen_tokens"],
            **{k: m["dist"][k] for k in DIST_FEATURES},
        })
    return rows


def fit_score(Xtr, ytr, Xte, yte) -> float:
    """AUROC of an L2 logistic probe. Returns nan if a split is single-class."""
    if len(set(ytr)) < 2 or len(set(yte)) < 2:
        return float("nan")
    clf = make_pipeline(StandardScaler(),
                        LogisticRegression(max_iter=2000, C=1.0, random_state=SEED))
    clf.fit(Xtr, ytr)
    return float(roc_auc_score(yte, clf.predict_proba(Xte)[:, 1]))


def scores_of(Xtr, ytr, Xte) -> np.ndarray:
    clf = make_pipeline(StandardScaler(),
                        LogisticRegression(max_iter=2000, C=1.0, random_state=SEED))
    clf.fit(Xtr, ytr)
    return clf.predict_proba(Xte)[:, 1]


def boot_auroc(y, s, rng, n=N_BOOT):
    y, s = np.asarray(y), np.asarray(s)
    out = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))          # resample PROBLEMS
        if len(set(y[idx])) < 2:
            continue
        out.append(roc_auc_score(y[idx], s[idx]))
    return np.percentile(out, [2.5, 97.5]) if out else (float("nan"),) * 2


def boot_paired(y, s_a, s_b, rng, n=N_BOOT):
    """CI of AUROC(a) - AUROC(b) on the SAME resample. The headline statistic."""
    y, s_a, s_b = np.asarray(y), np.asarray(s_a), np.asarray(s_b)
    out = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        if len(set(y[idx])) < 2:
            continue
        out.append(roc_auc_score(y[idx], s_a[idx]) - roc_auc_score(y[idx], s_b[idx]))
    return (float(np.mean(out)), *np.percentile(out, [2.5, 97.5])) if out \
        else (float("nan"),) * 3


def perm_p(y, s, rng, n=N_PERM):
    obs = roc_auc_score(y, s)
    y = np.asarray(y)
    ge = sum(1 for _ in range(n)
             if roc_auc_score(rng.permutation(y), s) >= obs)
    return (ge + 1) / (n + 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", required=True)
    ap.add_argument("--feature", choices=("final", "mean"), default="final")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows = load(Path(args.gen))
    n_layers = rows[0]["final"].shape[0]
    y_all = np.array([r["y"] for r in rows])
    print(f"n={len(rows)}  layers={n_layers}  pass_rate={y_all.mean():.4f}")

    # ---- stratify on the label-independent difficulty axis -----------------
    cx = np.array([r["cx"] for r in rows])
    med = float(np.median(cx))
    easy = [r for r in rows if r["cx"] < med]
    hard = [r for r in rows if r["cx"] >= med]
    pr_e = np.mean([r["y"] for r in easy])
    pr_h = np.mean([r["y"] for r in hard])
    print(f"\nDIFFICULTY AXIS (reference AST nodes, median {med:.0f})")
    print(f"  EASY n={len(easy)} pass={pr_e:.4f}   HARD n={len(hard)} pass={pr_h:.4f}"
          f"   gap={pr_e - pr_h:+.4f}")
    axis_ok = pr_e > pr_h
    print(f"  precondition (EASY pass > HARD pass): "
          f"{'OK' if axis_ok else 'FAILED -> transfer question INCONCLUSIVE'}")

    # ---- the split ---------------------------------------------------------
    parts = make_split(rows, SEED)
    train, test_in, test_out = parts["TRAIN"], parts["TEST-IN"], parts["TEST-OUT"]
    for k, v in parts.items():
        ys = [r["y"] for r in v]
        print(f"  {k:9} n={len(v):4}  pass={np.mean(ys):.4f}  "
              f"pos={sum(ys)} neg={len(ys) - sum(ys)}")

    check_split(parts, len(rows))
    print("  SPLIT ASSERTION: PASS (three-way problem-id disjointness, exhaustive)")

    def M(part, key):
        return np.stack([r[key] for r in part])

    ytr = np.array([r["y"] for r in train])
    y_in = np.array([r["y"] for r in test_in])
    y_out = np.array([r["y"] for r in test_out])

    # ---- layer curve (reported whole; nothing selected on test) ------------
    print(f"\nLAYER CURVE  feature={args.feature}")
    print(f"  {'layer':>5} {'cv(train)':>10} {'TEST-IN':>9} {'TEST-OUT':>9}")
    curve = []
    for L in range(n_layers):
        Xtr = M(train, args.feature)[:, L, :]
        cv = float(np.mean(cross_val_score(
            make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000,
                                                               random_state=SEED)),
            Xtr, ytr, cv=StratifiedKFold(5, shuffle=True, random_state=SEED),
            scoring="roc_auc")))
        a_in = fit_score(Xtr, ytr, M(test_in, args.feature)[:, L, :], y_in)
        a_out = fit_score(Xtr, ytr, M(test_out, args.feature)[:, L, :], y_out)
        curve.append({"layer": L, "cv_train": cv, "test_in": a_in, "test_out": a_out})
        print(f"  {L:>5} {cv:>10.4f} {a_in:>9.4f} {a_out:>9.4f}")

    # LAYER SELECTION RULE, fixed in the preregistration: argmax of TRAIN
    # cross-validated AUROC. Test performance is never consulted.
    best = max(curve, key=lambda c: c["cv_train"])
    L = best["layer"]
    print(f"\n  selected layer {L} by TRAIN cv-AUROC {best['cv_train']:.4f} "
          f"(test never consulted)")

    Xtr = M(train, args.feature)[:, L, :]
    s_in = scores_of(Xtr, ytr, M(test_in, args.feature)[:, L, :])
    s_out = scores_of(Xtr, ytr, M(test_out, args.feature)[:, L, :])

    # ---- baselines ---------------------------------------------------------
    def col(part, keys):
        return np.stack([[float(r[k]) for k in keys] for r in part])

    baselines = {}
    for f in DIST_FEATURES:
        baselines[f] = (col(train, [f]), col(test_in, [f]), col(test_out, [f]))
    baselines["DIST-ALL"] = (col(train, DIST_FEATURES), col(test_in, DIST_FEATURES),
                             col(test_out, DIST_FEATURES))
    baselines["difficulty(cx)"] = (col(train, ["cx"]), col(test_in, ["cx"]),
                                   col(test_out, ["cx"]))
    baselines["n_gen_tokens"] = (col(train, ["n_gen"]), col(test_in, ["n_gen"]),
                                 col(test_out, ["n_gen"]))

    print(f"\nBASELINES  (chance = 0.5; majority TEST-OUT = {max(y_out.mean(), 1 - y_out.mean()):.4f} acc)")
    print(f"  {'baseline':>16} {'TEST-IN':>9} {'TEST-OUT':>9}")
    bl_scores = {}
    for name, (a, b, c) in baselines.items():
        ai = fit_score(a, ytr, b, y_in)
        ao = fit_score(a, ytr, c, y_out)
        bl_scores[name] = {"test_in": ai, "test_out": ao,
                           "s_out": scores_of(a, ytr, c),
                           "s_in": scores_of(a, ytr, b)}
        print(f"  {name:>16} {ai:>9.4f} {ao:>9.4f}")

    dist_only = {k: v for k, v in bl_scores.items()
                 if k in DIST_FEATURES or k == "DIST-ALL"}
    best_dist = max(dist_only, key=lambda k: dist_only[k]["test_out"]
                    if not np.isnan(dist_only[k]["test_out"]) else -1)

    # ---- headline statistics ----------------------------------------------
    res = {"n": len(rows), "pass_rate": float(y_all.mean()), "feature": args.feature,
           "median_cx": med, "easy_pass": float(pr_e), "hard_pass": float(pr_h),
           "axis_ok": bool(axis_ok), "layer_curve": curve, "selected_layer": L,
           "part_n": {k: len(v) for k, v in parts.items()},
           "part_pass": {k: float(np.mean([r["y"] for r in v])) for k, v in parts.items()},
           "baselines": {k: {"test_in": v["test_in"], "test_out": v["test_out"]}
                         for k, v in bl_scores.items()},
           "best_dist_baseline": best_dist}

    for tag, y, s in (("TEST-IN", y_in, s_in), ("TEST-OUT", y_out, s_out)):
        a = float(roc_auc_score(y, s))
        lo, hi = boot_auroc(y, s, np.random.default_rng(SEED))
        p = perm_p(y, s, np.random.default_rng(SEED))
        # TPR/FPR at the operating point that maximises Youden's J on TRAIN.
        s_tr = scores_of(Xtr, ytr, Xtr)
        thr = float(np.percentile(s_tr, 100 * (1 - ytr.mean())))
        pred = s >= thr
        tpr = float(pred[y == 1].mean()) if (y == 1).any() else float("nan")
        fpr = float(pred[y == 0].mean()) if (y == 0).any() else float("nan")
        print(f"\n{tag}: AUROC={a:.4f}  95% CI [{lo:.4f}, {hi:.4f}]  perm p={p:.4f}")
        print(f"    at train-threshold: TPR={tpr:.4f}  FPR={fpr:.4f}")
        res[tag] = {"auroc": a, "ci": [float(lo), float(hi)], "perm_p": float(p),
                    "tpr": tpr, "fpr": fpr}

        m, plo, phi = boot_paired(y, s, bl_scores[best_dist]["s_out" if tag == "TEST-OUT"
                                                            else "s_in"],
                                  np.random.default_rng(SEED))
        print(f"    PAIRED vs {best_dist}: {m:+.4f}  95% CI [{plo:+.4f}, {phi:+.4f}]")
        res[tag]["paired_vs_best_dist"] = {"mean": m, "ci": [float(plo), float(phi)]}

    # ---- crash / wrong-answer decomposition on TEST-OUT --------------------
    modes = [r["mode"] for r in test_out]
    wrong = [i for i, r in enumerate(test_out) if r["y"] == 1 or r["mode"] == "WRONG"]
    if len(wrong) > 10 and len({y_out[i] for i in wrong}) == 2:
        aw = float(roc_auc_score(y_out[wrong], s_out[wrong]))
        print(f"\nWRONG-ANSWER SUBSET of TEST-OUT (crashes dropped): "
              f"n={len(wrong)} AUROC={aw:.4f}")
        res["test_out_wrong_only"] = {"n": len(wrong), "auroc": aw}
    else:
        print(f"\nWRONG-ANSWER SUBSET of TEST-OUT: too small/single-class "
              f"(n={len(wrong)}) -> not reported")
    from collections import Counter
    res["test_out_modes"] = dict(Counter(modes))
    print(f"  TEST-OUT failure modes: {dict(Counter(modes))}")

    out = Path(args.out) if args.out else HERE / f"result_{args.feature}.json"
    out.write_text(json.dumps(res, indent=1, default=float))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
