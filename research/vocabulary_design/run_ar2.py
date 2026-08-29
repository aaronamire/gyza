"""
AR-2 — how much REAL failure mass does a TYPE-LEVEL envelope absorb?

Ground truth is external: MBPP assert verdicts re-executed
(`selection_routes/mbpp_truth.json`). The envelopes are human-authored and
type-level -- nothing problem-specific, because C11's cost model is only
affordable at type granularity.

Deterministic, zero model calls.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = HERE.parents[0] / "selection_routes"
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[0] / "native_verifier"))

SEED = 1

_WORKER = r'''
import ast, json, signal, sys
def _t(s, f): raise TimeoutError()
signal.signal(signal.SIGALRM, _t)
job = json.loads(sys.stdin.read())
fn, calls = job["fn"], job["calls"]

def run(src, budget=8.0):
    ns = {}
    try:
        signal.setitimer(signal.ITIMER_REAL, budget); exec(src, ns)
        signal.setitimer(signal.ITIMER_REAL, 0)
    except BaseException:
        signal.setitimer(signal.ITIMER_REAL, 0); return None
    if fn not in ns: return None
    outs = []
    for c in calls:
        try:
            signal.setitimer(signal.ITIMER_REAL, budget)
            v = eval(c, dict(ns)); signal.setitimer(signal.ITIMER_REAL, 0)
            outs.append(["OK", repr(v), type(v).__name__])
        except BaseException:
            signal.setitimer(signal.ITIMER_REAL, 0); outs.append(["ERR", None, None])
    return outs

a = run(job["src"]); b = run(job["src"])          # repeat, for determinism
r = run(job["ref"])

# ORACLE equality must be computed over VALUES, not over repr strings.
# Comparing reprs made `1` vs `1.0` and dict key-order differences read as
# mismatches, giving the oracle a non-zero FPR against programs that PASS the
# asserts. That is artifact #15's species for the third time; canonicalize (here:
# compare semantically) before comparing.
def values(src, budget=8.0):
    ns = {}
    try:
        signal.setitimer(signal.ITIMER_REAL, budget); exec(src, ns)
        signal.setitimer(signal.ITIMER_REAL, 0)
    except BaseException:
        signal.setitimer(signal.ITIMER_REAL, 0); return None
    if fn not in ns: return None
    out = []
    for c in calls:
        try:
            signal.setitimer(signal.ITIMER_REAL, budget)
            out.append(("OK", eval(c, dict(ns)))); signal.setitimer(signal.ITIMER_REAL, 0)
        except BaseException:
            signal.setitimer(signal.ITIMER_REAL, 0); out.append(("ERR", None))
    return out

va, vr = values(job["src"]), values(job["ref"])
try:
    oracle_ok = bool(va is not None and vr is not None and va == vr)
except BaseException:
    oracle_ok = False
print(json.dumps({"a": a, "b": b, "ref": r, "oracle_ok": oracle_ok}))
'''


def probe(src, ref, fn, calls):
    try:
        p = subprocess.run([sys.executable, "-c", _WORKER],
                           input=json.dumps({"src": src, "ref": ref, "fn": fn,
                                             "calls": calls}),
                           capture_output=True, text=True, timeout=60)
        return json.loads(p.stdout)
    except Exception:
        return {"a": None, "b": None, "ref": None, "oracle_ok": False}


# --------------------------------------------------------------------------- #
#  The three envelopes. TYPE-LEVEL: nothing problem-specific.                  #
# --------------------------------------------------------------------------- #
def env_type_only(pr) -> bool:
    """FLOOR: the program runs and produces an output for every input."""
    a = pr["a"]
    return bool(a) and all(s == "OK" for s, _v, _t in a)


def env_structural(pr) -> bool:
    """floor + deterministic + type-consistent across inputs + non-degenerate."""
    if not env_type_only(pr):
        return False
    a, b = pr["a"], pr["b"]
    if a != b:                                   # deterministic
        return False
    types = {t for _s, _v, t in a}
    if len(types) > 1:                           # consistent output type
        return False
    vals = {v for _s, v, _t in a}
    if len(a) > 1 and len(vals) == 1:            # degenerate: constant output
        return False
    return True


def env_oracle(pr) -> bool:
    """CEILING -- matches the reference BY VALUE. NOT a cheap check: computing
    it requires solving the problem. DEFINITIONAL."""
    return bool(pr.get("oracle_ok"))


ENVELOPES = {"TYPE_ONLY": env_type_only, "STRUCTURAL": env_structural,
             "ORACLE": env_oracle}


def main() -> None:
    import native_verifier as V
    mbpp = V.load_mbpp(n=V.N_CODE, seed=V.SEED)
    truth = json.loads((SC / "mbpp_truth.json").read_text())["truth"]
    cache = {}
    for f in sorted((HERE.parents[0] / "native_verifier" / "nv_cache").glob("prog__*.json")):
        cache[f.name[len("prog__"):-len(".json")].replace("__", "/")] = \
            json.loads(f.read_text())

    rows = []
    for key, correct in truth.items():
        model, idx = key.rsplit("|", 1)
        i = int(idx)
        src = cache[model][i]["source"]
        ref = mbpp[i]["code"]
        fn = V.entry_point(mbpp[i]["test_list"])
        calls = [c for c, _e in V.extract_calls(mbpp[i]["test_list"])]
        pr = probe(src, ref, fn, calls)
        rows.append({"key": key, "correct": bool(correct),
                     **{f"acc_{n}": bool(f(pr)) for n, f in ENVELOPES.items()}})

    n_fail = sum(1 for r in rows if not r["correct"])
    n_ok = sum(1 for r in rows if r["correct"])
    feasible = n_fail >= 30 and n_ok >= 30

    res = {"seed": SEED, "n": len(rows), "n_correct": n_ok, "n_failing": n_fail,
           "feasible": feasible, "envelopes": {}}
    for name in ENVELOPES:
        tp = sum(1 for r in rows if not r["correct"] and not r[f"acc_{name}"])
        fp = sum(1 for r in rows if r["correct"] and not r[f"acc_{name}"])
        res["envelopes"][name] = {
            "TPR": round(tp / n_fail, 4) if n_fail else None,
            "FPR": round(fp / n_ok, 4) if n_ok else None,
            "rejected_failing": tp, "rejected_correct": fp}
    # #14 -- does the headline decompose into a mixture? STRUCTURAL's number
    # includes everything the FLOOR already caught. The decision-relevant
    # quantity is the MARGINAL absorption among programs that actually RAN.
    ran_fail = [r for r in rows if not r["correct"] and r["acc_TYPE_ONLY"]]
    ran_ok = [r for r in rows if r["correct"] and r["acc_TYPE_ONLY"]]
    res["mixture_decomposition"] = {
        "note": ("STRUCTURAL TPR mixes 'the program crashed' (caught by the "
                 "FLOOR) with 'the output looked structurally wrong'. A crash "
                 "is an execution failure, not a respecified semantic claim."),
        "failing_that_ran": len(ran_fail),
        "correct_that_ran": len(ran_ok),
        "marginal_TPR_among_programs_that_ran": (
            round(sum(1 for r in ran_fail if not r["acc_STRUCTURAL"]) / len(ran_fail), 4)
            if ran_fail else None),
        "marginal_FPR_among_programs_that_ran": (
            round(sum(1 for r in ran_ok if not r["acc_STRUCTURAL"]) / len(ran_ok), 4)
            if ran_ok else None),
    }
    res["rows"] = rows
    (HERE / "ar2_result.json").write_text(json.dumps(res, indent=1))

    print(f"n={len(rows)}  correct={n_ok}  failing={n_fail}  "
          f"feasible={'YES' if feasible else 'NO -> NOT-MEASURABLE'}\n")
    print(f"{'envelope':12} {'TPR':>8} {'FPR':>8}   (TPR without FPR is meaningless)")
    for name in ("TYPE_ONLY", "STRUCTURAL", "ORACLE"):
        e = res["envelopes"][name]
        print(f"{name:12} {e['TPR']:>8.4f} {e['FPR']:>8.4f}")
    m = res["mixture_decomposition"]
    print(f"\nMIXTURE (#14): of {m['failing_that_ran']} failing programs that RAN, "
          f"STRUCTURAL rejects {m['marginal_TPR_among_programs_that_ran']}"
          f"  (FPR among {m['correct_that_ran']} correct that ran: "
          f"{m['marginal_FPR_among_programs_that_ran']})")


if __name__ == "__main__":
    main()
