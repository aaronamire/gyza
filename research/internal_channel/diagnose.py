"""Diagnostics the verdict turns on, run after the headline numbers.

Four questions, each of which could overturn or qualify CHANNEL-REDUNDANT:

  D1  Is the result driven by a SINGLE LAYER? The preregistration reports
      INCONCLUSIVE for any cell that is. Counts layers clearing 0.65.
  D2  What would POST-HOC layer selection have reported? The preregistered
      rule selects on TRAIN cv; selecting on test is tuning. This quantifies
      exactly what the rule cost, so the reader can see it was load-bearing.
  D3  Is the probe reading the SAME THING as the logprobs, or something
      different that is merely weaker? Rank correlation of the two score
      vectors, plus the INCREMENTAL test: does DIST-ALL + probe beat DIST-ALL?
      Redundancy and inferiority are different claims and this separates them.
  D4  Does the probe survive dropping crashes? Already reported, re-stated
      here against a matched baseline so the comparison is like-for-like.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from probe import (DIST_FEATURES, SEED, boot_paired, check_split, load,
                   make_split, scores_of)

HERE = Path(__file__).resolve().parent
GEN = HERE / "gen_experiment"


def main() -> None:
    rows = load(GEN)
    parts = make_split(rows, SEED)
    check_split(parts, len(rows))
    train, test_out = parts["TRAIN"], parts["TEST-OUT"]
    ytr = np.array([r["y"] for r in train])
    y_out = np.array([r["y"] for r in test_out])
    out = {}

    for feat in ("final", "mean"):
        res = json.loads((HERE / f"result_{feat}.json").read_text())
        curve = res["layer_curve"]
        sel = res["selected_layer"]

        # D1 -- single layer?
        over = [c["layer"] for c in curve if c["test_out"] > 0.65]
        best_test = max(curve, key=lambda c: c["test_out"])
        print(f"\n{'=' * 70}\nfeature={feat}")
        print(f"D1  layers with TEST-OUT > 0.65: {len(over)}/{len(curve)}  {over}")
        print(f"    -> {'NOT single-layer' if len(over) > 3 else 'SINGLE-LAYER: INCONCLUSIVE'}")

        # D2 -- what post-hoc selection would have bought
        print(f"D2  preregistered (TRAIN cv) layer {sel}: TEST-OUT="
              f"{[c for c in curve if c['layer'] == sel][0]['test_out']:.4f}")
        print(f"    post-hoc best layer {best_test['layer']}: TEST-OUT="
              f"{best_test['test_out']:.4f}   (delta "
              f"{best_test['test_out'] - [c for c in curve if c['layer'] == sel][0]['test_out']:+.4f})")

        def M(part, L):
            return np.stack([r[feat] for r in part])[:, L, :]

        def col(part, keys):
            return np.stack([[float(r[k]) for k in keys] for r in part])

        # The post-hoc layer, taken all the way through the paired test, so
        # the claim "even tuning would not have cleared the bar" is measured.
        Lb = best_test["layer"]
        s_post = scores_of(M(train, Lb), ytr, M(test_out, Lb))
        s_best_dist = scores_of(col(train, ["sum_logprob"]), ytr,
                                col(test_out, ["sum_logprob"]))
        m, lo, hi = boot_paired(y_out, s_post, s_best_dist,
                                np.random.default_rng(SEED))
        print(f"    post-hoc layer paired vs sum_logprob: {m:+.4f} "
              f"95% CI [{lo:+.4f}, {hi:+.4f}]  -> "
              f"{'would clear' if lo > 0 else 'STILL FAILS the paired bar'}")

        # D3 -- same thing, or a different weaker thing?
        s_sel = scores_of(M(train, sel), ytr, M(test_out, sel))
        rho = spearmanr(s_sel, s_best_dist).statistic
        print(f"D3  Spearman(probe, sum_logprob) on TEST-OUT = {rho:+.4f}")

        Xtr_d, Xte_d = col(train, DIST_FEATURES), col(test_out, DIST_FEATURES)
        a_dist = roc_auc_score(y_out, scores_of(Xtr_d, ytr, Xte_d))
        # Concatenating 896 probe dims onto 5 distribution features would let
        # dimensionality alone explain any gain, so the probe enters as its
        # single fitted SCORE -- one column against five.
        s_tr_probe = scores_of(M(train, sel), ytr, M(train, sel))
        comb_tr = np.hstack([Xtr_d, s_tr_probe[:, None]])
        comb_te = np.hstack([Xte_d, s_sel[:, None]])
        clf = make_pipeline(StandardScaler(),
                            LogisticRegression(max_iter=2000, random_state=SEED))
        clf.fit(comb_tr, ytr)
        a_comb = roc_auc_score(y_out, clf.predict_proba(comb_te)[:, 1])
        mi, li, hi2 = boot_paired(y_out, clf.predict_proba(comb_te)[:, 1],
                                  scores_of(Xtr_d, ytr, Xte_d),
                                  np.random.default_rng(SEED))
        print(f"    DIST-ALL alone            = {a_dist:.4f}")
        print(f"    DIST-ALL + probe score    = {a_comb:.4f}")
        print(f"    INCREMENTAL value of the probe: {mi:+.4f} "
              f"95% CI [{li:+.4f}, {hi2:+.4f}]  -> "
              f"{'ADDS information' if li > 0 else 'adds nothing detectable'}")

        # D4 -- wrong answers only, probe vs baseline on the SAME subset
        keep = [i for i, r in enumerate(test_out)
                if r["y"] == 1 or r["mode"] == "WRONG"]
        yk = y_out[keep]
        a_p = roc_auc_score(yk, s_sel[keep])
        a_b = roc_auc_score(yk, s_best_dist[keep])
        md, ld, hd = boot_paired(yk, s_sel[keep], s_best_dist[keep],
                                 np.random.default_rng(SEED))
        print(f"D4  WRONG-ANSWER subset (n={len(keep)}, crashes dropped):")
        print(f"    probe={a_p:.4f}  sum_logprob={a_b:.4f}  "
              f"paired={md:+.4f} 95% CI [{ld:+.4f}, {hd:+.4f}]")

        out[feat] = {
            "layers_over_065": over, "n_layers_over_065": len(over),
            "posthoc_best_layer": Lb, "posthoc_auroc": best_test["test_out"],
            "posthoc_paired": {"mean": m, "ci": [lo, hi]},
            "spearman_probe_vs_sumlogprob": float(rho),
            "dist_all": float(a_dist), "dist_all_plus_probe": float(a_comb),
            "incremental": {"mean": mi, "ci": [li, hi2]},
            "wrong_only": {"n": len(keep), "probe": float(a_p),
                           "sum_logprob": float(a_b),
                           "paired": {"mean": md, "ci": [ld, hd]}},
        }

    (HERE / "diagnostics.json").write_text(json.dumps(out, indent=1, default=float))
    print(f"\nwrote {HERE / 'diagnostics.json'}")


if __name__ == "__main__":
    main()
