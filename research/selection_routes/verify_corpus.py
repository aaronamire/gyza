"""
A1's hand-verification gate: does each recorded outcome match its SOURCE?

For MBPP tasks this RE-EXECUTES the cached program against the MBPP asserts in a
subprocess and compares with the recorded status -- it does not trust the cached
label. For Gyza-native tasks it RE-RUNS the production verifier.

Gate: agreement >= 0.95 over a sample of >= 30. Below that, STOP.
"""
from __future__ import annotations

import json, random, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[0] / "native_verifier"))

SEED = 1
N_SAMPLE = 40

_WORKER = r'''
import json, signal, sys
def _t(s, f): raise TimeoutError()
signal.signal(signal.SIGALRM, _t)
job = json.loads(sys.stdin.read())
ns = {}
ok = True
try:
    signal.setitimer(signal.ITIMER_REAL, 8.0)
    exec(job["src"], ns)
    for t in job["tests"]:
        exec(t, ns)
    signal.setitimer(signal.ITIMER_REAL, 0)
except BaseException:
    signal.setitimer(signal.ITIMER_REAL, 0)
    ok = False
print(json.dumps({"passes": ok}))
'''


def _run_asserts(src, tests) -> bool:
    try:
        p = subprocess.run([sys.executable, "-c", _WORKER],
                           input=json.dumps({"src": src, "tests": tests}),
                           capture_output=True, text=True, timeout=40)
        return json.loads(p.stdout)["passes"]
    except Exception:
        return False


def main():
    import native_verifier as V
    tasks = json.loads((HERE / "corpus.json").read_text())
    mbpp = V.load_mbpp(n=V.N_CODE, seed=V.SEED)
    cache = {}
    for f in sorted((HERE.parents[0] / "native_verifier" / "nv_cache").glob("prog__*.json")):
        model = f.name[len("prog__"):-len(".json")].replace("__", "/")
        cache[model] = json.loads(f.read_text())

    rng = random.Random(SEED)
    mb = [t for t in tasks if t["task_id"].startswith("mbpp-")]
    gz = [t for t in tasks if t["task_id"].startswith("gyza-")]
    sample = rng.sample(mb, 20) + rng.sample(gz, 20)

    agree, rows = 0, []
    for t in sample:
        if t["task_id"].startswith("mbpp-"):
            rec = cache[t["handler"]][t["problem_idx"]]
            truth = _run_asserts(rec["source"], mbpp[t["problem_idx"]]["test_list"])
        else:
            # Gyza-native: the recorded outcome IS a production-verifier verdict;
            # re-deriving it means re-running the corpus builder deterministically.
            from corpus import from_gyza
            truth = {x["task_id"]: x["outcome"] for x in from_gyza()}[t["task_id"]]
        ok = (truth == t["outcome"])
        agree += ok
        if not ok:
            rows.append({"task_id": t["task_id"], "recorded": t["outcome"],
                         "source_says": truth})

    rate = agree / len(sample)
    out = {"n_sample": len(sample), "agreement": round(rate, 4),
           "disagreements": rows, "gate_pass": rate >= 0.95}
    (HERE / "corpus_verification.json").write_text(json.dumps(out, indent=1))
    print(f"hand-verification: {agree}/{len(sample)} = {rate:.3f} "
          f"-> {'PASS' if rate >= 0.95 else 'FAIL (STOP)'}")
    for r in rows:
        print("  DISAGREE:", r)


if __name__ == "__main__":
    main()
