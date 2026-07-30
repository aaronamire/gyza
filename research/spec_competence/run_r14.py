"""
Route 14 — scoring driver. Produces r14_result.json.

Never reports validity without kill rate; never a kill rate without the
TYPE-ONLY floor and the measured reference ceiling; never a kill rate without
the oracle-embedding rate beside it.
"""
from __future__ import annotations

import json
import os
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "native_verifier"))

import mutations as M                                        # noqa: E402
import spec_experiment as SE                                 # noqa: E402
from refspecs import REFERENCE_SPECS, REFERENCE_SPECS_PROP   # noqa: E402

SEED = 1
PROBS = {r["i"]: r for r in json.loads((HERE / "problems.json").read_text())}


def _boot_ci(vals, seed=SEED, n=3000):
    if not vals:
        return (None, None)
    rng = random.Random(seed)
    m = []
    for _ in range(n):
        s = [vals[rng.randrange(len(vals))] for _ in vals]
        m.append(st.mean(s))
    m.sort()
    return (round(m[int(0.025 * n)], 4), round(m[int(0.975 * n)], 4))


def main() -> None:
    import native_verifier as V

    cells = SE.load_cells()
    gens = {}
    for model in SE.MODELS:
        for arm in SE.ARMS:
            p = SE.CACHE / f"spec__{model.replace('/', '__')}__{arm}.json"
            gens[(model, arm)] = {x["i"]: x for x in json.loads(p.read_text())}

    per_spec, baselines = [], []
    for i, r in sorted(PROBS.items()):
        calls = V.extract_calls(r["tests"])
        muts = M.generate_mutants(r["code"])

        specs, tags = [M.SPEC_TRUE, M.SPEC_TYPE_ONLY], [("__true__", "-"), ("__type__", "-")]
        if i in REFERENCE_SPECS:
            specs += [REFERENCE_SPECS[i], REFERENCE_SPECS_PROP[i]]
            tags += [("__ref_embed__", "-"), ("__ref_prop__", "-")]
        for model in SE.MODELS:
            for arm in SE.ARMS:
                g = gens[(model, arm)].get(i)
                src = g["spec"] if g else None
                specs.append(src if src else "x = 1\n")
                tags.append((model, arm))

        res = M.evaluate_problem(r["fn"], calls, r["tests"], r["code"], muts, specs)
        if not res.get("ref_ok"):
            continue
        nwrong = res["mut_class"].count("WRONG")
        type_kills = None

        for k, (tag, arm) in enumerate(tags):
            s = res["specs"][k]
            row = {"problem": i, "tag": tag, "arm": arm, "status": s["status"],
                   "n_wrong": nwrong}
            if s["status"] == "VALID":
                row["kill"] = s["killed"] / s["denom"] if s["denom"] else None
                row["kill_nocrash"] = (s["killed_x"] / s["denom_x"]
                                       if s["denom_x"] else None)
            if tag == "__type__" and s["status"] == "VALID":
                type_kills = s["killed"]
            if tag.startswith("__"):
                baselines.append(row)
            else:
                g = gens[(tag, arm)].get(i)
                src = g["spec"] if g and g["spec"] else None
                row["parsed"] = bool(src)
                row["cell"] = ("a" if cells[tag][i] == "CORRECT" else
                               "b" if cells[tag][i] == "WRONG" else "unresolved")
                if src:
                    row.update({("emb_" + kk): vv for kk, vv
                                in SE.embedding_flags(src, r["code"]).items()})
                per_spec.append(row)
        _ = type_kills

    out = {"seed": SEED,
           "n_problems": len(PROBS),
           "models": SE.MODELS,
           "baselines": baselines,
           "specs": per_spec}

    # ---- aggregates -------------------------------------------------------
    def agg(rows, key="kill"):
        v = [x[key] for x in rows if x.get(key) is not None]
        return {"n": len(v), "mean": round(st.mean(v), 4) if v else None,
                "ci": _boot_ci(v)}

    floor = agg([b for b in baselines if b["tag"] == "__type__"])
    ceil_e = agg([b for b in baselines if b["tag"] == "__ref_embed__"])
    ceil_p = agg([b for b in baselines if b["tag"] == "__ref_prop__"])
    vac = agg([b for b in baselines if b["tag"] == "__true__"])

    summary = {"floor_type_only": floor, "ceiling_ref_embedding": ceil_e,
               "ceiling_ref_property_only": ceil_p, "vacuity_return_true": vac,
               "by_arm_cell": {}, "by_model": {}, "paired": {}}

    for arm in SE.ARMS:
        for cell in ("a", "b"):
            rows = [x for x in per_spec if x["arm"] == arm and x["cell"] == cell]
            valid = [x for x in rows if x["status"] == "VALID"]
            emb = [x for x in valid if x.get("emb_embedding")]
            summary["by_arm_cell"][f"{arm}/{cell}"] = {
                "n_specs": len(rows),
                "parsed": sum(1 for x in rows if x.get("parsed")),
                "validity": round(len(valid) / len(rows), 4) if rows else None,
                "invalid": sum(1 for x in rows if x["status"] == "INVALID"),
                "nonspec": sum(1 for x in rows if x["status"] == "NONSPEC"),
                "kill": agg(valid),
                "kill_nocrash": agg(valid, "kill_nocrash"),
                "embedding_rate": round(len(emb) / len(valid), 4) if valid else None,
                "kill_embedding": agg(emb),
                "kill_nonembedding": agg([x for x in valid
                                          if not x.get("emb_embedding")]),
                "node_ratio_median": (round(st.median([x["emb_ratio"] for x in valid
                                                       if "emb_ratio" in x]), 4)
                                      if valid else None),
            }

    # paired cell(a) - cell(b) per arm, over PROBLEMS (bootstrap over problems)
    for arm in SE.ARMS:
        pa = [x["kill"] for x in per_spec
              if x["arm"] == arm and x["cell"] == "a" and x.get("kill") is not None]
        pb = [x["kill"] for x in per_spec
              if x["arm"] == arm and x["cell"] == "b" and x.get("kill") is not None]
        rng = random.Random(SEED)
        diffs = []
        for _ in range(3000):
            sa = st.mean([pa[rng.randrange(len(pa))] for _ in pa]) if pa else 0
            sb = st.mean([pb[rng.randrange(len(pb))] for _ in pb]) if pb else 0
            diffs.append(sa - sb)
        diffs.sort()
        summary["paired"][arm] = {
            "cell_a_mean": round(st.mean(pa), 4) if pa else None, "n_a": len(pa),
            "cell_b_mean": round(st.mean(pb), 4) if pb else None, "n_b": len(pb),
            "diff": round((st.mean(pa) - st.mean(pb)), 4) if pa and pb else None,
            "diff_ci": (round(diffs[75], 4), round(diffs[2925], 4)),
        }

    for model in SE.MODELS:
        rows = [x for x in per_spec if x["tag"] == model]
        summary["by_model"][model] = {
            c: agg([x for x in rows if x["cell"] == c and x["status"] == "VALID"])
            for c in ("a", "b")}

    out["summary"] = summary
    (HERE / "r14_result.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(summary, indent=1)[:3000])


if __name__ == "__main__":
    main()
