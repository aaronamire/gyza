"""SR-2 — allocation. Deterministic, SEED=1, zero model calls (cached outcomes)."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 1


def main():
    tasks = [t for t in json.loads((HERE / "corpus.json").read_text())
             if "problem_idx" in t]
    # outcome[claim_type][problem][handler] = bool
    by: dict = defaultdict(lambda: defaultdict(dict))
    for t in tasks:
        by[t["claim_type"]][t["problem_idx"]][t["handler"]] = t["outcome"]

    handlers = sorted({t["handler"] for t in tasks})
    results = {}
    for ct, probs in by.items():
        # Restrict to problems where EVERY handler has a recorded outcome; a
        # partial row would make round-robin and oracle incomparable. The
        # exclusion count is reported rather than silently dropped.
        allk = sorted(probs)
        keys = [k for k in allk if len(probs[k]) == len(handlers)]
        dropped = len(allk) - len(keys)
        # FEASIBILITY: is there handler-dependent variance at all?
        varying = sum(1 for k in keys if len(set(probs[k].values())) > 1)
        rr_ok = tr_ok = or_ok = 0
        esc = 0
        for i, k in enumerate(keys):
            outs = probs[k]
            rr = outs[handlers[i % len(handlers)]]          # round-robin
            tr = outs[handlers[0]]                          # type-routed: one
            # handler registered per claim type -> the same handler every time
            best = any(outs.values())
            rr_ok += rr
            tr_ok += tr
            or_ok += best
            esc += (not best)
        n = len(keys)
        results[ct] = {
            "n": n, "dropped_incomplete_rows": dropped, "handlers": len(handlers),
            "problems_with_handler_variance": varying,
            "variance_rate": round(varying / n, 4),
            "round_robin": round(rr_ok / n, 4),
            "type_routed": round(tr_ok / n, 4),
            "oracle": round(or_ok / n, 4),
            "escalation_rate_oracle": round(esc / n, 4),
            "gap_to_oracle_from_type_routed": round((or_ok - tr_ok) / n, 4),
            "type_routed_minus_round_robin": round((tr_ok - rr_ok) / n, 4),
        }
    (HERE / "sr2_result.json").write_text(json.dumps(
        {"seed": SEED, "n_claim_types_in_slice": len(by), "by_claim_type": results},
        indent=1))

    print(f"claim types in the allocable slice: {len(by)}  (P2's taxonomy point)")
    hdr = f"{'claim type':26} {'n':>4} {'var':>6} {'RR':>7} {'type':>7} {'oracle':>7} {'gap':>7} {'t-RR':>7}"
    print(hdr); print("-" * len(hdr))
    for ct, r in results.items():
        print(f"{ct:26} {r['n']:>4} {r['variance_rate']:>6.2f} "
              f"{r['round_robin']:>7.4f} {r['type_routed']:>7.4f} "
              f"{r['oracle']:>7.4f} {r['gap_to_oracle_from_type_routed']:>7.4f} "
              f"{r['type_routed_minus_round_robin']:>7.4f}")


if __name__ == "__main__":
    main()
