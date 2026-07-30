"""Route 14 B4 — do MODEL-written per-stage specs compose? (DAFNYCOMP's question)"""
from __future__ import annotations
import inspect, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pipelines as P, spec_experiment as SE

MODELS_B4 = ["microsoft/phi-4", "meta-llama/llama-3.1-70b-instruct"]
CLASS_DESC = {
 "conservation": "CONSERVATION: a quantity is preserved by the stage (length, multiset, or sum).",
 "monotone": "MONOTONE NON-CUMULATIVE: a property that, once established by a stage, cannot be lost by a later stage (e.g. sortedness, type/shape constraints).",
 "cumulative": "CUMULATIVE: a budget over the WHOLE pipeline (the total number of elements added across all three stages must not exceed %d)." % P.END_TO_END_BUDGET,
}

def prompt(pl, cls):
    src = "\n".join(inspect.getsource(f) for f in pl["stages"])
    return ("A 3-stage pipeline runs f3(f2(f1(x))) on a list of ints.\n\n"
            f"STAGE SOURCE:\n{src}\n"
            f"SPEC CLASS -- {CLASS_DESC[cls]}\n\n"
            "Write ONE Python function that checks this class of property for a SINGLE stage:\n\n"
            "def stage_spec(i, xin, xout) -> bool:\n"
            "    # i is the stage index (0, 1, or 2)\n"
            "    # xin is the list entering that stage, xout the list leaving it\n"
            "    # return True iff stage i respects the property\n\n"
            "Return only the function. No explanation, no markdown fences.\n")

def extract(text):
    t = text or ""
    if "```" in t:
        for p in t.split("```"):
            if "def stage_spec" in p:
                t = p[len("python"):] if p.startswith("python") else p
                break
    lines = t.splitlines()
    s = next((i for i,l in enumerate(lines) if l.lstrip().startswith("def stage_spec")), None)
    if s is None: return None
    base = len(lines[s]) - len(lines[s].lstrip())
    body = [lines[s][base:]] + [l[base:] if len(l)>base else l for l in lines[s+1:]]
    import ast
    for cut in range(len(body), 0, -1):
        cand = "\n".join(body[:cut]).rstrip()
        try:
            ast.parse(cand); return cand
        except SyntaxError: continue
    return None

def main():
    cache = HERE / "sc_cache" / "b4.json"
    if cache.exists():
        gens = json.loads(cache.read_text())
    else:
        gens = {}
        for m in MODELS_B4:
            b = SE._backend(m)
            for pl in P.PIPELINES:
                for cls in CLASS_DESC:
                    try: txt = b.generate(prompt(pl, cls), max_new_tokens=400)
                    except Exception as e: txt = f"__ERR__ {e}"
                    gens[f"{m}|{pl['name']}|{cls}"] = txt
        cache.write_text(json.dumps(gens, indent=1))
    rows = []
    for key, txt in gens.items():
        m, name, cls = key.split("|")
        pl = next(p for p in P.PIPELINES if p["name"] == name)
        src = extract(txt)
        if not src:
            rows.append({"model": m, "pipeline": name, "cls": cls, "status": "NOPARSE"}); continue
        ns = {}
        try: exec(src, ns)
        except BaseException: rows.append({"model": m,"pipeline":name,"cls":cls,"status":"EXEC"}); continue
        f = ns.get("stage_spec")
        if not callable(f):
            rows.append({"model": m,"pipeline":name,"cls":cls,"status":"NOFN"}); continue
        def conj(trace):
            try: return all(bool(f(i, a, b)) for i,(a,b) in enumerate(trace))
            except BaseException: return None
        _, base_tr = P.run(pl["stages"], P.INPUT)
        if conj(base_tr) is not True:
            rows.append({"model": m,"pipeline":name,"cls":cls,"status":"REJECTS_BASE"}); continue
        missed = 0; viol = 0
        for kind in ("drop","unsort","overadd"):
            for idx in (0,1,2):
                st_ = P.mutate_stage(pl, idx, kind)
                out, tr = P.run(st_, P.INPUT)
                if P.E2E[cls](pl, P.INPUT, out): continue
                viol += 1
                if conj(tr) is True: missed += 1
        rows.append({"model": m,"pipeline":name,"cls":cls,"status":"OK",
                     "e2e_violations": viol,"missed": missed,
                     "detection": (viol-missed)/viol if viol else None})
    summ = {}
    for cls in CLASS_DESC:
        sub=[r for r in rows if r["cls"]==cls]
        ok=[r for r in sub if r["status"]=="OK" and r["e2e_violations"]]
        summ[cls]={"n_specs":len(sub),"usable":len(ok),
                   "rejects_base":sum(1 for r in sub if r["status"]=="REJECTS_BASE"),
                   "noparse":sum(1 for r in sub if r["status"] in ("NOPARSE","EXEC","NOFN")),
                   "mean_detection": (sum(r["detection"] for r in ok)/len(ok)) if ok else None,
                   "total_violations": sum(r["e2e_violations"] for r in ok),
                   "total_missed": sum(r["missed"] for r in ok)}
    for c,v in summ.items(): print(c, v)
    json.dump({"rows":rows,"summary":summ}, open("b4_result.json","w"), indent=1)


if __name__ == "__main__":
    main()
