"""Apply the preregistered discrimination bar. Mechanical given the bar.

The bar is applied EXACTLY as frozen in PREREGISTRATION_1B.md 3 and is not
tuned. The one AUTHORED input is the census speech act, which was frozen before
this route existed -- so the STRONG/WEAK split is mechanical here even though
the underlying speech-act call was judgement.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "research/claims_corpus"))
from classify import CLS  # noqa: E402  (frozen census classifications)

NOW = datetime.fromisoformat("2026-08-09T00:00:00+00:00")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def classify(claim, oc, act):
    """Returns (class, signal_time, n_links). Bar frozen in the preregistration."""
    links = [ts(p["merged_at"]) for p in oc["merged_prs"] if p.get("merged_at")]
    links += [ts(c["at"]) for c in oc["closing_commits"] if c.get("at")]
    links = [t for t in links if t]
    n_links = len(links)

    if n_links:                                   # a code change is linked
        sig = min(links)
        return ("STRONG" if act == "A" else "WEAK"), sig, n_links
    if oc["state"] == "closed" and oc["state_reason"] == "completed":
        return "WEAK", ts(oc["closed_at"]), 0     # done, but nothing links it
    if oc["state"] == "closed":
        return "NONE", ts(oc["closed_at"]), 0     # not_planned / duplicate / bare
    return "UNRESOLVED", None, 0                  # open -- right-censored


def main() -> None:
    claims = json.loads((ROOT / "research/claims_corpus/claims_hand.json").read_text())
    outc = json.loads((HERE / "outcomes.json").read_text())

    rows = []
    for i, c in enumerate(claims):
        act, det, _basis = CLS[i]
        oc = outc[f"{c['repo']}#{c['issue']}"]
        cls, sig, nl = classify(c, oc, act)
        lag = ((sig - ts(oc["created_at"])).days if sig else None)
        rows.append({"id": c["claim_id"], "act": act, "det": det, "cls": cls,
                     "lag": lag, "n_links": nl, "repo": c["repo"],
                     "issue": c["issue"]})

    n = len(rows)
    dist = Counter(r["cls"] for r in rows)
    strong = [r for r in rows if r["cls"] == "STRONG"]
    s = len(strong) / n

    print("=" * 74)
    print(f"PART A -- DISCRIMINATION DISTRIBUTION (n={n}, ALL claims incl. no-outcome)")
    print("=" * 74)
    for k in ("STRONG", "WEAK", "NONE", "UNRESOLVED", "UNSURE"):
        print(f"  {k:12} {dist.get(k,0):4}  {dist.get(k,0)/n:.4f}")
    print(f"\n  >>> s (STRONG fraction) = {len(strong)}/{n} = {s:.4f}")
    print(f"      counter-metric: NONE = {dist.get('NONE',0)/n:.4f}, "
          f"UNRESOLVED = {dist.get('UNRESOLVED',0)/n:.4f}")

    print("\n" + "=" * 74)
    print("A4 -- DETERMINACY CROSS-TAB (frozen census classes)")
    print("=" * 74)
    dets = {"I": "INTERNAL", "U": "UNDERDETERMINED", "X": "EXOGENOUS", "T": "CONTESTED"}
    print(f"  {'':18}{'n':>5}{'STRONG':>9}{'rate':>9}")
    rates = {}
    for d, name in dets.items():
        sub = [r for r in rows if r["det"] == d]
        st = sum(1 for r in sub if r["cls"] == "STRONG")
        rate = st / len(sub) if sub else float("nan")
        rates[d] = (st, len(sub), rate)
        print(f"  {name:18}{len(sub):>5}{st:>9}{rate:>9.4f}")
    xr, ur = rates["X"][2], rates["U"][2]
    print(f"\n  A4 PREDICTION: EXOGENOUS > UNDERDETERMINED ?")
    print(f"    EXOGENOUS {xr:.4f}  vs  UNDERDETERMINED {ur:.4f}  -> "
          f"{'HELD' if xr > ur else 'REFUTED'}")

    print("\n" + "=" * 74)
    print("PART B -- LAG AND CENSORING")
    print("=" * 74)
    cens = dist.get("UNRESOLVED", 0) / n
    print(f"  right-censored (open, no signal): {dist.get('UNRESOLVED',0)}/{n} = {cens:.4f}")
    lags = sorted(r["lag"] for r in strong if r["lag"] is not None)
    if lags:
        q = statistics.quantiles(lags, n=4) if len(lags) > 3 else [None]*3
        print(f"  STRONG lags (days), n={len(lags)}")
        print(f"    median {statistics.median(lags):.1f}   "
              f"Q1 {q[0] if q[0] is None else round(q[0],1)}   "
              f"Q3 {q[2] if q[2] is None else round(q[2],1)}   "
              f"min {min(lags)}  max {max(lags)}")
        for d in (1, 7, 30, 365):
            print(f"    within {d:>3}d: {sum(1 for x in lags if x <= d)/len(lags):.4f}")
    else:
        print("  no STRONG lags to report")

    print("\n" + "=" * 74)
    print("PART C -- ATTRIBUTION")
    print("=" * 74)
    if strong:
        clean = [r for r in strong if r["n_links"] == 1]
        a = len(clean) / len(strong)
        print(f"  STRONG with EXACTLY ONE link (clean): {len(clean)}/{len(strong)} = {a:.4f}")
        print(f"  counter-metric MULTI-link: {1-a:.4f}")
        print(f"  link-count distribution: {dict(Counter(r['n_links'] for r in strong))}")
    else:
        a = float("nan")
        print("  no STRONG signals -- attribution undefined")

    # single-issue / single-repo cell check
    print("\n  cells driven by a single ISSUE or REPO -> INCONCLUSIVE:")
    flagged = False
    for k in ("STRONG", "WEAK", "NONE", "UNRESOLVED"):
        sub = [r for r in rows if r["cls"] == k]
        if not sub:
            continue
        if len({r["issue"] for r in sub}) == 1:
            print(f"    {k}: all from 1 issue -> INCONCLUSIVE"); flagged = True
        if len({r["repo"] for r in sub}) == 1:
            print(f"    {k}: all from 1 repo -> INCONCLUSIVE"); flagged = True
    if not flagged:
        print("    none")

    med = statistics.median(lags) if lags else None
    verdict = ("CONSEQUENCE-DEAD" if (s < 0.15 or (strong and a < 0.40)) else
               "CONSEQUENCE-VIABLE" if (s >= 0.30 and a >= 0.60 and med is not None and med < 30) else
               "CONSEQUENCE-SETTLEMENT-ONLY" if (s >= 0.30 and a >= 0.60) else
               "CONSEQUENCE-INTERMEDIATE")
    print(f"\n>>> DECISION: {verdict}   (s={s:.4f}, a={a:.4f}, median lag={med})")

    json.dump({"n": n, "dist": dict(dist), "s": s, "a": a, "median_lag": med,
               "censored": cens, "det_rates": {k: list(v) for k, v in rates.items()},
               "verdict": verdict,
               "lag_within": {d: (sum(1 for x in lags if x <= d)/len(lags) if lags else None)
                              for d in (1, 7, 30, 365)}},
              open(HERE / "result.json", "w"), indent=1)


if __name__ == "__main__":
    main()
