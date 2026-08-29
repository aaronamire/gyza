"""Label each generated program MECHANICALLY, by running MBPP's own asserts.

No model stands anywhere in this path. The label is produced by executing code
in a subprocess with a timeout, which is the one verification channel this
program measured as sound (Tier 1, native execution).

THE CRASH / WRONG DISTINCTION IS THE POINT OF THE PER-ASSERT LOOP. "This
program will raise" is a much easier thing to predict than "this answer is
wrong" -- a probe could reach a respectable AUROC by learning only the former
and would have demonstrated nothing about correctness. Each assert is
therefore run in isolation and its failure mode recorded:

    AssertionError        -> WRONG   (the function ran and returned the wrong value)
    any other exception   -> CRASH   (the function did not produce an answer)
    SyntaxError at exec   -> SYNTAX  (a crash, recorded separately)
    setitimer fires       -> TIMEOUT

CANONICAL COMPARISON. `gyza.canon.values_equal` is the program's named
comparison call site (three artifacts of the repr-vs-value species bought it).
MBPP's asserts use Python `==`, which is ALREADY value equality -- so routing
through the helper cannot loosen the benchmark. The one behaviour it adds is
NaN == NaN, and `--canon-sensitivity` reports exactly how many labels that
changes rather than asserting it changes none.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT_S = 10.0

_WORKER = r'''
import ast, contextlib, io, json, math, os, signal, sys

# THE MEASUREMENT NEEDS ITS OWN CHANNEL. Generated MBPP programs frequently
# print -- debug traces, or a solution that prints instead of returning -- and
# that output lands on the same stdout the worker reports its verdict on,
# making "the program said 2" indistinguishable from "the harness said PASS".
# It is the same species as writing an exception into a measurement channel,
# and it is not hypothetical: it crashed the first labelling pass outright.
# So the verdict goes to a FILE the executed code has no reference to, and
# stdout is captured and discarded for the whole duration of execution.

def _timeout(sig, frm):
    raise TimeoutError("assert timed out")
signal.signal(signal.SIGALRM, _timeout)

# gyza.canon.values_equal, inlined -- the worker runs untrusted generated code
# in a bare interpreter and must not import the package under study.
def values_equal(a, b):
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
    try:
        return bool(a == b)
    except Exception:
        return False

job = json.loads(sys.stdin.read())
ns = {}
res = {"exec": "OK", "asserts": [], "canon_asserts": []}

_sink = io.StringIO()
_cap = contextlib.redirect_stdout(_sink)
_cap.__enter__()

try:
    signal.setitimer(signal.ITIMER_REAL, job["budget"])
    exec(job["setup"] + "\n" + job["program"], ns)
    signal.setitimer(signal.ITIMER_REAL, 0)
except SyntaxError as e:
    signal.setitimer(signal.ITIMER_REAL, 0)
    res["exec"] = "SYNTAX"; res["exec_detail"] = type(e).__name__
except TimeoutError:
    signal.setitimer(signal.ITIMER_REAL, 0); res["exec"] = "TIMEOUT"
except BaseException as e:
    signal.setitimer(signal.ITIMER_REAL, 0)
    res["exec"] = "CRASH"; res["exec_detail"] = type(e).__name__

if res["exec"] == "OK":
    for a in job["asserts"]:
        # Native execution of the assert: this IS the benchmark's definition.
        try:
            signal.setitimer(signal.ITIMER_REAL, job["budget"])
            exec(a, dict(ns))
            signal.setitimer(signal.ITIMER_REAL, 0)
            res["asserts"].append(["PASS", None])
        except AssertionError:
            signal.setitimer(signal.ITIMER_REAL, 0)
            res["asserts"].append(["WRONG", "AssertionError"])
        except TimeoutError:
            signal.setitimer(signal.ITIMER_REAL, 0)
            res["asserts"].append(["TIMEOUT", "TimeoutError"])
        except BaseException as e:
            signal.setitimer(signal.ITIMER_REAL, 0)
            res["asserts"].append(["CRASH", type(e).__name__])

        # The same assert re-evaluated through the named comparison helper,
        # reported only as a sensitivity. `==` and values_equal differ on NaN
        # and nowhere else, so a nonzero delta here is a finding about NaN.
        verdict = "SKIP"
        try:
            node = ast.parse(a, mode="exec").body[0]
            t = node.test
            if (isinstance(node, ast.Assert) and isinstance(t, ast.Compare)
                    and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)):
                signal.setitimer(signal.ITIMER_REAL, job["budget"])
                lv = eval(compile(ast.Expression(t.left), "<l>", "eval"), dict(ns))
                rv = eval(compile(ast.Expression(t.comparators[0]), "<r>", "eval"),
                          dict(ns))
                signal.setitimer(signal.ITIMER_REAL, 0)
                verdict = "PASS" if values_equal(lv, rv) else "WRONG"
        except BaseException:
            signal.setitimer(signal.ITIMER_REAL, 0)
            verdict = "ERR"
        res["canon_asserts"].append(verdict)

_cap.__exit__(None, None, None)
res["stdout_bytes"] = len(_sink.getvalue())
with open(job["verdict_path"], "w") as _out:
    _out.write(json.dumps(res))
'''


def extract_code(completion: str) -> str:
    """Pull the program out of the completion. Fenced block if there is one."""
    if "```" not in completion:
        return completion.strip()
    parts = completion.split("```")
    for i in range(1, len(parts), 2):
        block = parts[i]
        if block.startswith("python"):
            block = block[len("python"):]
        elif block.startswith("py\n"):
            block = block[3:]
        if block.strip():
            return block.strip()
    return ""


def run_one(program: str, setup: str, asserts: list[str]) -> dict:
    with tempfile.TemporaryDirectory() as td:
        vp = str(Path(td) / "verdict.json")
        try:
            subprocess.run([sys.executable, "-c", _WORKER],
                           input=json.dumps({"program": program, "setup": setup,
                                             "asserts": asserts,
                                             "budget": TIMEOUT_S,
                                             "verdict_path": vp}),
                           capture_output=True, text=True,
                           timeout=TIMEOUT_S * (len(asserts) + 2) + 15)
        except subprocess.TimeoutExpired:
            return {"exec": "TIMEOUT", "asserts": [], "canon_asserts": []}
        # A missing verdict file means the worker died before reporting --
        # os._exit, a segfault, a SIGKILL. That is a crash of the generated
        # program, and it is recorded as one rather than silently skipped.
        if not Path(vp).exists():
            return {"exec": "CRASH", "exec_detail": "worker_died",
                    "asserts": [], "canon_asserts": []}
        return json.loads(Path(vp).read_text())


def verdict(res: dict, n_asserts: int) -> tuple[str, str]:
    """(label, failure_mode). PASS requires every assert to pass."""
    if res["exec"] != "OK":
        return "FAIL", res["exec"]
    if len(res["asserts"]) < n_asserts:
        return "FAIL", "TRUNCATED"
    modes = [a[0] for a in res["asserts"]]
    if all(m == "PASS" for m in modes):
        return "PASS", "-"
    # First non-pass decides: a program that raises never reaches the
    # question of whether its answer was wrong.
    return "FAIL", next(m for m in modes if m != "PASS")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", required=True, help="gen_<split> directory")
    args = ap.parse_args()
    gen = Path(args.gen)
    rows = [json.loads(l) for l in (gen / "meta.jsonl").open() if l.strip()]

    out, canon_delta = [], 0
    for n, r in enumerate(rows, 1):
        prog = extract_code(r["completion"])
        if not prog:
            out.append({"task_id": r["task_id"], "label": "FAIL",
                        "mode": "NOCODE", "n_pass": 0})
            continue
        res = run_one(prog, r.get("test_setup_code") or "", r["test_list"])
        lab, mode = verdict(res, len(r["test_list"]))
        ca = res.get("canon_asserts", [])
        canon_lab = ("PASS" if ca and all(v == "PASS" for v in ca)
                     else "PASS" if lab == "PASS" and not ca else "FAIL")
        if canon_lab != lab and all(v != "SKIP" for v in ca) and ca:
            canon_delta += 1
        out.append({"task_id": r["task_id"], "label": lab, "mode": mode,
                    "n_pass": sum(1 for a in res.get("asserts", [])
                                  if a[0] == "PASS"),
                    "assert_modes": [a[0] for a in res.get("asserts", [])],
                    "exec_detail": res.get("exec_detail"),
                    "canon_asserts": ca})
        if n % 50 == 0:
            print(f"  labelled {n}/{len(rows)}", flush=True)

    (gen / "labels.json").write_text(json.dumps(out, indent=1))
    lab = Counter(r["label"] for r in out)
    mode = Counter(r["mode"] for r in out if r["label"] == "FAIL")
    n = len(out)
    print(f"\nn={n}  PASS={lab['PASS']}  FAIL={lab['FAIL']}  "
          f"pass_rate={lab['PASS'] / n:.4f}")
    print("failure modes:", dict(mode))
    crashy = sum(v for k, v in mode.items() if k != "WRONG")
    if lab["FAIL"]:
        print(f"  CRASH-class {crashy}/{lab['FAIL']} = {crashy / lab['FAIL']:.4f}   "
              f"WRONG-ANSWER {mode['WRONG']}/{lab['FAIL']} = "
              f"{mode['WRONG'] / lab['FAIL']:.4f}")
    print(f"canonical-comparison label deltas (== vs values_equal): {canon_delta}")


if __name__ == "__main__":
    main()
