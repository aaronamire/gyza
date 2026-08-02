"""Re-derive MBPP outcomes by EXECUTING the asserts, not by comparing reprs.

R8's cached `status` is `signature == expected` over STRING REPRS
(native_verifier.py:219). That over-reports WRONG whenever a value compares
equal but reprs differ -- dict key order and int/float equality both do. Ground
truth for the corpus must be the SOURCE (the asserts), not a derived label.
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1])); sys.path.insert(0, str(HERE.parents[0] / "native_verifier"))

_W = r'''
import json,signal,sys
def _t(s,f): raise TimeoutError()
signal.signal(signal.SIGALRM,_t)
j=json.loads(sys.stdin.read()); ns={}; ok=True
try:
    signal.setitimer(signal.ITIMER_REAL,8.0); exec(j["src"],ns)
    for t in j["tests"]: exec(t,ns)
    signal.setitimer(signal.ITIMER_REAL,0)
except BaseException:
    signal.setitimer(signal.ITIMER_REAL,0); ok=False
print(json.dumps({"p":ok}))
'''

def run(src, tests):
    try:
        p = subprocess.run([sys.executable,"-c",_W], input=json.dumps({"src":src,"tests":tests}),
                           capture_output=True, text=True, timeout=45)
        return json.loads(p.stdout)["p"]
    except Exception:
        return False

def main():
    import native_verifier as V
    mbpp = V.load_mbpp(n=V.N_CODE, seed=V.SEED)
    out, agree, tot, flips = {}, 0, 0, []
    for f in sorted((HERE.parents[0]/"native_verifier"/"nv_cache").glob("prog__*.json")):
        model = f.name[len("prog__"):-len(".json")].replace("__","/")
        for i, r in enumerate(json.loads(f.read_text())):
            if r["status"] == "UNRESOLVED":
                continue
            truth = run(r["source"], mbpp[i]["test_list"])
            cached = r["status"] == "CORRECT"
            out[f"{model}|{i}"] = truth
            tot += 1; agree += (truth == cached)
            if truth != cached:
                flips.append({"model": model, "idx": i, "cached": r["status"],
                              "asserts_say": "CORRECT" if truth else "WRONG"})
    res = {"n": tot, "agreement_with_cached_label": round(agree/tot, 4),
           "false_wrong": sum(1 for x in flips if x["asserts_say"]=="CORRECT"),
           "false_correct": sum(1 for x in flips if x["asserts_say"]=="WRONG"),
           "flips": flips, "truth": out}
    (HERE/"mbpp_truth.json").write_text(json.dumps(res, indent=1))
    print(f"re-executed {tot} (model,problem) pairs")
    print(f"agreement with R8's cached label: {res['agreement_with_cached_label']:.4f}")
    print(f"  false WRONG (cache said wrong, asserts pass): {res['false_wrong']}")
    print(f"  false CORRECT: {res['false_correct']}")

if __name__ == "__main__":
    main()
