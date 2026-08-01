"""SR-3 measurement driver. Deterministic, SEED=1, zero model calls."""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tier_algebra as T


def spec_checked(s0, sN) -> bool:
    """(b) SPEC-CHECKED MERGE — a registered PARTIAL spec on the result:
    shape and range only. Deliberately weaker than a verifier: it cannot see an
    exact cumulative total or an exact derived value."""
    if any(k != T._h(v) for k, v in sN["artifacts"].items()):
        return False
    if sN["hlc"] < s0["hlc"]:
        return False
    return isinstance(sN["payload"], int) and sN["payload"] >= 0


def contained(s0, sN) -> bool:
    """(c) CONTAINED CONCATENATION — no correctness claim at all."""
    return True


def main():
    rows = []
    # pre-mutation validity (R14 Part B4 lesson) -- assert BEFORE mutating
    base_bad = []
    for p in T.PIPELINES:
        s0, sN, ok = T.run(p)
        if not (ok and T.e2e_holds(p, s0, sN)):
            base_bad.append(p)
    assert not base_bad, f"pipelines fail their OWN spec un-mutated: {base_bad}"

    for p in T.PIPELINES:
        for idx in range(len(p)):
            s0, sN, per_stage_ok = T.run(p, mutate_at=idx)
            e2e = T.e2e_holds(p, s0, sN)
            rows.append({
                "pipeline": "+".join(p), "mutated_stage": p[idx], "at": idx,
                "carrier": T.STAGES[p[idx]].carrier,
                "cls": T.STAGES[p[idx]].cls,
                "tiers": [T.STAGES[n].tier for n in p],
                "e2e_violated": not e2e,
                "verified_fold_rejects": not per_stage_ok,
                "spec_merge_rejects": not spec_checked(s0, sN),
                "contained_rejects": not contained(s0, sN),
            })

    viol = [r for r in rows if r["e2e_violated"]]
    def det(key, subset=None):
        s = subset if subset is not None else viol
        return (sum(1 for r in s if r[key]) / len(s)) if s else None

    # feasibility: neither degenerate
    feas = {"total_mutations": len(rows), "e2e_violations": len(viol),
            "all_caught_by_every_operator": all(
                r["verified_fold_rejects"] and r["spec_merge_rejects"]
                and r["contained_rejects"] for r in viol),
            "none_caught": not any(r["verified_fold_rejects"] for r in viol)}

    by_carrier = {}
    for c in ("PROOF", "TEST", "SPEC", "NONE"):
        sub = [r for r in viol if r["carrier"] == c]
        by_carrier[c] = {"n": len(sub), "verified_fold": det("verified_fold_rejects", sub),
                         "spec_merge": det("spec_merge_rejects", sub),
                         "contained": det("contained_rejects", sub)}
    by_cls = {}
    for c in ("CONSERVATION", "MONOTONE", "CUMULATIVE", "NONE"):
        sub = [r for r in viol if r["cls"] == c]
        by_cls[c] = {"n": len(sub), "verified_fold": det("verified_fold_rejects", sub),
                     "spec_merge": det("spec_merge_rejects", sub),
                     "contained": det("contained_rejects", sub)}

    out = {"seed": T.SEED, "feasibility": feas,
           "overall": {"verified_fold": det("verified_fold_rejects"),
                       "spec_merge": det("spec_merge_rejects"),
                       "contained": det("contained_rejects")},
           "by_carrier": by_carrier, "by_class": by_cls, "rows": rows}
    Path(__file__).with_name("sr3_result.json").write_text(json.dumps(out, indent=1))

    print(f"FEASIBILITY: {len(viol)}/{len(rows)} mutations violate e2e; "
          f"all-caught={feas['all_caught_by_every_operator']} "
          f"none-caught={feas['none_caught']}\n")
    print(f"{'':14} {'n':>3} {'verified_fold':>14} {'spec_merge':>11} {'contained':>10}")
    for label, d in (("BY CARRIER", None),):
        pass
    for c, v in by_carrier.items():
        if not v["n"]:
            continue
        print(f"{c:14} {v['n']:>3} {v['verified_fold']:>14.3f} "
              f"{v['spec_merge']:>11.3f} {v['contained']:>10.3f}")
    print()
    for c, v in by_cls.items():
        if not v["n"]:
            continue
        print(f"{c:14} {v['n']:>3} {v['verified_fold']:>14.3f} "
              f"{v['spec_merge']:>11.3f} {v['contained']:>10.3f}")


if __name__ == "__main__":
    main()
