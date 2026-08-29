"""Route 14 Part B — mechanical composition matrix. Zero model calls."""
from __future__ import annotations
import json
import pipelines as P

MUT = {"conservation": "drop", "monotone": "unsort", "cumulative": "overadd"}

def analyse():
    rows = []
    for pl in P.PIPELINES:
        base_out, base_trace = P.run(pl["stages"], P.INPUT)
        for cls in ("conservation", "monotone", "cumulative"):
            # sanity: the UNMUTATED pipeline must satisfy both levels
            assert P.per_stage_conjunction(pl, cls, base_trace), (pl["name"], cls)
            assert P.E2E[cls](pl, P.INPUT, base_out), (pl["name"], cls, "e2e base")
            for kind in ("drop", "unsort", "overadd"):
                for idx in (0, 1, 2):
                    st = P.mutate_stage(pl, idx, kind)
                    out, tr = P.run(st, P.INPUT)
                    local_ok = P.per_stage_conjunction(pl, cls, tr)
                    e2e_ok = P.E2E[cls](pl, P.INPUT, out)
                    rows.append({"pipeline": pl["name"], "cls": cls,
                                 "mutation": kind, "stage": idx,
                                 "local_conjunction_accepts": local_ok,
                                 "end_to_end_holds": e2e_ok,
                                 "MISSED": bool(local_ok and not e2e_ok)})
    return rows

def summarise(rows):
    out = {}
    for cls in ("conservation", "monotone", "cumulative"):
        sub = [r for r in rows if r["cls"] == cls]
        rel = [r for r in sub if r["mutation"] == MUT[cls]]
        viol = [r for r in sub if not r["end_to_end_holds"]]
        missed = [r for r in sub if r["MISSED"]]
        out[cls] = {"cells": len(sub),
                    "e2e_violations": len(viol),
                    "missed_by_local_conjunction": len(missed),
                    "caught": len(viol) - len(missed),
                    "detection_rate": (len(viol) - len(missed)) / len(viol) if viol else None,
                    "own_mutation_cells": len(rel),
                    "own_mutation_missed": sum(1 for r in rel if r["MISSED"]),
                    "COMPOSES": bool(viol) and not missed}
    return out

if __name__ == "__main__":
    rows = analyse()
    s = summarise(rows)
    for cls, v in s.items():
        print(f'{cls:14} e2e_violations={v["e2e_violations"]:3d} '
              f'missed={v["missed_by_local_conjunction"]:3d} '
              f'detection={v["detection_rate"]} COMPOSES={v["COMPOSES"]}')
    json.dump({"rows": rows, "summary": s}, open("partb_result.json", "w"), indent=1)
    print("wrote partb_result.json")
