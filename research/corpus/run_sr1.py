"""SR-1 — does decomposition STRUCTURE predict outcome?

Runs exactly the plan in PREREGISTRATION_SR1.md (sha256 4dd64e7d...), committed
before any structure-outcome association was computed. No tuning after results;
implementation-bug fixes only, disclosed.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from gyza.canon import values_equal            # noqa: E402

MIN_DETECTABLE = 0.167          # the 50/50 ceiling; no smaller threshold is valid
MIN_ARM = 15                    # below this, H1 is NOT-EVALUABLE (prereg §6)


# --------------------------------------------------------------------------- #
#  statistics, dependency-free                                                 #
# --------------------------------------------------------------------------- #
def fisher_exact_two_sided(a, b, c, d):
    """[[a,b],[c,d]] -> two-sided p by summing tables no more probable."""
    n = a + b + c + d
    r1, r2, c1 = a + b, c + d, a + c

    def lc(k):
        return (math.lgamma(r1 + 1) + math.lgamma(r2 + 1) + math.lgamma(c1 + 1)
                + math.lgamma(n - c1 + 1) - math.lgamma(n + 1)
                - math.lgamma(k + 1) - math.lgamma(r1 - k + 1)
                - math.lgamma(c1 - k + 1) - math.lgamma(n - c1 - r1 + k + 1))

    lo, hi = max(0, c1 - r2), min(r1, c1)
    obs = lc(a)
    tot = sum(math.exp(lc(k)) for k in range(lo, hi + 1))
    p = sum(math.exp(lc(k)) for k in range(lo, hi + 1)
            if lc(k) <= obs + 1e-9)
    return min(1.0, p / tot)


def logistic(X, y, iters=60):
    """Newton-Raphson with an intercept. Returns (beta, wald_p)."""
    n, k = len(X), len(X[0]) + 1
    Z = [[1.0] + list(row) for row in X]
    b = [0.0] * k
    cov = None
    for _ in range(iters):
        eta = [sum(bj * zj for bj, zj in zip(b, z)) for z in Z]
        mu = [1 / (1 + math.exp(-min(30, max(-30, e)))) for e in eta]
        g = [sum((y[i] - mu[i]) * Z[i][j] for i in range(n)) for j in range(k)]
        H = [[sum(mu[i] * (1 - mu[i]) * Z[i][j] * Z[i][l] for i in range(n))
              for l in range(k)] for j in range(k)]
        for j in range(k):
            H[j][j] += 1e-8
        cov = _inv(H)
        step = [sum(cov[j][l] * g[l] for l in range(k)) for j in range(k)]
        b = [b[j] + step[j] for j in range(k)]
        if max(abs(s) for s in step) < 1e-10:
            break
    se = [math.sqrt(max(cov[j][j], 0)) for j in range(k)]
    p = [2 * (1 - _norm_cdf(abs(b[j] / se[j]))) if se[j] > 0 else 1.0
         for j in range(k)]
    return b, se, p


def _inv(M):
    k = len(M)
    A = [row[:] + [1.0 if i == j else 0.0 for j in range(k)] for i, row in enumerate(M)]
    for i in range(k):
        pv = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[pv] = A[pv], A[i]
        d = A[i][i]
        A[i] = [v / d for v in A[i]]
        for r in range(k):
            if r != i and A[r][i]:
                f = A[r][i]
                A[r] = [v - f * w for v, w in zip(A[r], A[i])]
    return [row[k:] for row in A]


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# --------------------------------------------------------------------------- #
#  the structural property                                                     #
# --------------------------------------------------------------------------- #
def conservation(record, files_map):
    """CONSERVING iff subtask file sets are pairwise disjoint (a partition).

    Empty-file commits (merges, empty commits) are EXCLUDED from disjointness
    but still counted in depth, per the preregistration. A record with no
    non-empty subtask is UNDEFINED and dropped -- not defaulted to either class.
    """
    sets, missing = [], 0
    for s in record["reference_decomposition"]["subtasks"]:
        f = files_map.get(f"{record['repo']}|{s['sha']}")
        if f is None:
            missing += 1
            continue
        if f:
            sets.append(set(f))
    if not sets:
        return "UNDEFINED", missing
    total = sum(len(s) for s in sets)
    union = len(set().union(*sets))
    return ("CONSERVING" if total == union else "REVISITING"), missing


def main():
    recs = json.loads((HERE / "decompositions.json").read_text())["records"]
    files_map = json.loads((HERE / "commit_files.json").read_text())

    usable = [r for r in recs if r["outcome_substantive"] in ("PASS", "FAIL")]
    n_sub_total = sum(len(r["reference_decomposition"]["subtasks"]) for r in recs)
    n_missing = 0
    rows = []
    for r in usable:
        cls, miss = conservation(r, files_map)
        n_missing += miss
        rows.append({
            "record_id": r["record_id"], "repo": r["repo"],
            "conservation": cls,
            "depth": len(r["reference_decomposition"]["subtasks"]),
            "n_files": r["context"]["n_files"],
            "fail": 1 if values_equal(r["outcome_substantive"], "FAIL") else 0,
        })

    void = {"missing_fraction": round(n_missing / n_sub_total, 4),
            "void_if_over": 0.10}
    void["H1_H3_void"] = void["missing_fraction"] > 0.10

    # ---- H3 (descriptive) --------------------------------------------------
    defined = [r for r in rows if r["conservation"] != "UNDEFINED"]
    cons = [r for r in defined if r["conservation"] == "CONSERVING"]
    revi = [r for r in defined if r["conservation"] == "REVISITING"]
    h3 = {"n_defined": len(defined), "n_conserving": len(cons),
          "fraction_conserving": round(len(cons) / len(defined), 4) if defined else None,
          "n_undefined_dropped": len(rows) - len(defined),
          "prediction": "0.20-0.35"}

    # ---- H1 (primary) ------------------------------------------------------
    def rate(g):
        return sum(r["fail"] for r in g) / len(g) if g else None
    fc, fr = rate(cons), rate(revi)
    h1 = {"n_conserving": len(cons), "n_revisiting": len(revi),
          "fail_conserving": None if fc is None else round(fc, 4),
          "fail_revisiting": None if fr is None else round(fr, 4)}
    if min(len(cons), len(revi)) < MIN_ARM:
        h1["decision"] = "NOT-EVALUABLE"
        h1["why"] = f"an arm has n < {MIN_ARM} (prereg §6)"
    else:
        a = sum(r["fail"] for r in revi); b = len(revi) - a
        c = sum(r["fail"] for r in cons); d = len(cons) - c
        p = fisher_exact_two_sided(a, b, c, d)
        diff = fr - fc
        h1.update({"difference_revisiting_minus_conserving": round(diff, 4),
                   "fisher_p": round(p, 4),
                   "min_detectable": MIN_DETECTABLE})
        if diff >= MIN_DETECTABLE and p < 0.05:
            h1["decision"] = "SUPPORTED"
        elif diff <= -MIN_DETECTABLE and p < 0.05:
            h1["decision"] = "REFUTED"
        else:
            h1["decision"] = "UNDERPOWERED-NULL"

    # ---- H2 (secondary) ----------------------------------------------------
    X = [[math.log2(r["depth"]), math.log10(1 + r["n_files"])] for r in rows]
    y = [r["fail"] for r in rows]
    b, se, pv = logistic(X, y)
    h2 = {"n": len(rows), "events": sum(y),
          "coef_log2_depth": round(b[1], 4), "se": round(se[1], 4),
          "p_log2_depth": round(pv[1], 4),
          "coef_log10_files": round(b[2], 4), "p_log10_files": round(pv[2], 4),
          "decision": ("SUPPORTED" if b[1] > 0 and pv[1] < 0.05 else
                       "REFUTED" if b[1] < 0 and pv[1] < 0.05 else "NULL"),
          "confound": "depth is not randomly assigned; a positive coefficient is "
                      "consistent with task difficulty and is NOT causal evidence"}

    # ---- counter-metrics ---------------------------------------------------
    per_repo = {}
    for repo in sorted({r["repo"] for r in rows}):
        rr = [r for r in defined if r["repo"] == repo]
        cc = [r for r in rr if r["conservation"] == "CONSERVING"]
        vv = [r for r in rr if r["conservation"] == "REVISITING"]
        per_repo[repo] = {
            "n": len(rr), "n_conserving": len(cc), "n_revisiting": len(vv),
            "fail_conserving": None if not cc else round(rate(cc), 4),
            "fail_revisiting": None if not vv else round(rate(vv), 4)}

    def med(v):
        v = sorted(v); return v[len(v) // 2] if v else None
    counter = {
        "per_repo": per_repo,
        "depth_median_conserving": med([r["depth"] for r in cons]),
        "depth_median_revisiting": med([r["depth"] for r in revi]),
        "files_median_conserving": med([r["n_files"] for r in cons]),
        "files_median_revisiting": med([r["n_files"] for r in revi]),
        "note": "if CONSERVING is simply SHORT, H1 and H2 are one finding twice",
    }

    out = {"preregistration_sha256":
           "4dd64e7d795f7c28598f36486b9938dfb86167bdaf2997ae7f93af235a30e6d9",
           "void_checks": void, "H1_primary": h1, "H2_secondary": h2,
           "H3_tertiary": h3, "counter_metrics": counter, "rows": rows}
    (HERE / "sr1_result.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
