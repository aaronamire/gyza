"""
Route 14 — AST mutation harness + spec scoring substrate. Zero model calls.

Mutants are generated from the MBPP REFERENCE solution (never from any model's
program), classified by running the MBPP asserts, and used as the denominator
for the anti-vacuity metric (mutation kill rate).

The dominant failure mode this route exists to catch is VERIFIABLE-BUT-VACUOUS:
`def spec(inp, out): return True` is perfectly valid and worthless. Validity
alone is exactly the metric that hides it, which is why nothing here reports
validity without a kill rate.

Deterministic. SEED = 1.
"""
from __future__ import annotations

import ast
import copy
import json
import random
import subprocess
import sys
from pathlib import Path

SEED = 1
HERE = Path(__file__).resolve().parent
TIMEOUT_S = 5.0
N_MUTANTS_TARGET = 20

# Declared operator set (PREREGISTRATION §A2). Fixed before data.
OPERATORS = ("arith_swap", "cmp_swap", "int_boundary", "bool_negate",
             "return_subst", "loop_bound", "stmt_delete")

_ARITH = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv,
          ast.FloorDiv: ast.Mult, ast.Div: ast.Mult, ast.Mod: ast.Mult,
          ast.Pow: ast.Mult}
_CMP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
        ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}


class _Collect(ast.NodeVisitor):
    """Collect mutable sites as (operator, node) pairs."""

    def __init__(self):
        self.sites: list[tuple[str, ast.AST]] = []

    def visit_BinOp(self, n):
        if type(n.op) in _ARITH:
            self.sites.append(("arith_swap", n))
        self.generic_visit(n)

    def visit_Compare(self, n):
        if len(n.ops) == 1 and type(n.ops[0]) in _CMP:
            self.sites.append(("cmp_swap", n))
        self.generic_visit(n)

    def visit_Constant(self, n):
        if isinstance(n.value, int) and not isinstance(n.value, bool):
            self.sites.append(("int_boundary", n))
        self.generic_visit(n)

    def visit_UnaryOp(self, n):
        if isinstance(n.op, ast.Not):
            self.sites.append(("bool_negate", n))
        self.generic_visit(n)

    def visit_BoolOp(self, n):
        self.sites.append(("bool_negate", n))
        self.generic_visit(n)

    def visit_Return(self, n):
        if n.value is not None:
            self.sites.append(("return_subst", n))
        self.generic_visit(n)

    def visit_Call(self, n):
        if isinstance(n.func, ast.Name) and n.func.id == "range" and n.args:
            self.sites.append(("loop_bound", n))
        self.generic_visit(n)


def _apply(tree: ast.AST, op: str, target: ast.AST, rng: random.Random) -> bool:
    """Mutate `target` in place inside `tree`. Returns False if inapplicable."""
    for node in ast.walk(tree):
        if not _same(node, target):
            continue
        if op == "arith_swap":
            node.op = _ARITH[type(node.op)]()
            return True
        if op == "cmp_swap":
            node.ops = [_CMP[type(node.ops[0])]()]
            return True
        if op == "int_boundary":
            node.value = node.value + rng.choice((1, -1))
            return True
        if op == "bool_negate":
            if isinstance(node, ast.UnaryOp):
                node.op = ast.UAdd() if False else node.op
                return False
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            return True
        if op == "return_subst":
            node.value = ast.Constant(value=rng.choice((None, 0, -1)))
            return True
        if op == "loop_bound":
            a = node.args[0]
            node.args[0] = ast.BinOp(left=a, op=ast.Add(),
                                     right=ast.Constant(value=rng.choice((1, -1))))
            return True
    return False


def _same(a: ast.AST, b: ast.AST) -> bool:
    return (type(a) is type(b)
            and getattr(a, "lineno", -1) == getattr(b, "lineno", -2)
            and getattr(a, "col_offset", -1) == getattr(b, "col_offset", -2))


def _delete_stmt(tree: ast.AST, idx: int) -> bool:
    bodies = []
    for node in ast.walk(tree):
        b = getattr(node, "body", None)
        if isinstance(b, list) and len(b) > 1:
            bodies.append(b)
    if not bodies:
        return False
    b = bodies[idx % len(bodies)]
    del b[idx % len(b)]
    return True


def generate_mutants(ref_src: str, n_target: int = N_MUTANTS_TARGET,
                     seed: int = SEED) -> list[dict]:
    """Deterministic mutant set from the REFERENCE solution."""
    rng = random.Random(seed)
    try:
        base = ast.parse(ref_src)
    except SyntaxError:
        return []
    c = _Collect()
    c.visit(base)
    cand = [(op, n) for op, n in c.sites if op in OPERATORS]
    cand.sort(key=lambda x: (x[0], getattr(x[1], "lineno", 0),
                             getattr(x[1], "col_offset", 0)))

    out, seen = [], {ref_src}
    for op, node in cand:
        if len(out) >= n_target:
            break
        tree = ast.parse(ref_src)
        if not _apply(tree, op, node, rng):
            continue
        try:
            src = ast.unparse(ast.fix_missing_locations(tree))
        except Exception:
            continue
        if src in seen:
            continue
        seen.add(src)
        out.append({"op": op, "src": src})

    i = 0
    while len(out) < n_target and i < 12:
        tree = ast.parse(ref_src)
        if _delete_stmt(tree, i):
            try:
                src = ast.unparse(ast.fix_missing_locations(tree))
            except Exception:
                src = None
            if src and src not in seen:
                seen.add(src)
                out.append({"op": "stmt_delete", "src": src})
        i += 1
    return out


# --------------------------------------------------------------------------- #
#  Baseline specs (PREREGISTRATION §A5) — the floor                            #
# --------------------------------------------------------------------------- #
SPEC_TRUE = "def spec(inp, out):\n    return True\n"

# Compares the type NAME rather than injecting a type object: injecting the name
# `Counter` produced a NameError (NONSPEC) on problem 3, which would have
# excluded that problem from the floor rather than scoring it. Pre-data fix.
SPEC_TYPE_ONLY = '''def spec(inp, out):
    if type(out).__name__ != "__ref_type__":
        return False
    try:
        iter(out)
    except TypeError:
        pass
    return True
'''


# --------------------------------------------------------------------------- #
#  Sandboxed per-problem worker                                                #
# --------------------------------------------------------------------------- #
_WORKER = r'''
import ast, json, sys, signal

def _timeout(sig, frm): raise TimeoutError()
signal.signal(signal.SIGALRM, _timeout)

job = json.loads(sys.stdin.read())
fn = job["fn"]; calls = job["calls"]; ref = job["ref"]

def run_program(src, calls, budget):
    """Return (ok, outputs) where outputs[i] is [status, value_repr]."""
    ns = {}
    try:
        signal.setitimer(signal.ITIMER_REAL, budget)
        exec(src, ns)
        signal.setitimer(signal.ITIMER_REAL, 0)
    except BaseException:
        signal.setitimer(signal.ITIMER_REAL, 0)
        return False, None
    if fn not in ns:
        return False, None
    outs = []
    for call_src, _exp in calls:
        try:
            signal.setitimer(signal.ITIMER_REAL, budget)
            v = eval(call_src, dict(ns))
            signal.setitimer(signal.ITIMER_REAL, 0)
            outs.append(["OK", v])
        except BaseException:
            signal.setitimer(signal.ITIMER_REAL, 0)
            outs.append(["ERR", None])
    return True, outs

def args_of(call_src):
    node = ast.parse(call_src).body[0].value
    return [ast.literal_eval(a) for a in node.args]

def passes_asserts(src, budget):
    ns = {}
    try:
        signal.setitimer(signal.ITIMER_REAL, budget)
        exec(src, ns)
        for t in job["tests"]:
            exec(t, ns)
        signal.setitimer(signal.ITIMER_REAL, 0)
        return True
    except BaseException:
        signal.setitimer(signal.ITIMER_REAL, 0)
        return False

res = {}
ok_ref, ref_outs = run_program(ref, calls, 5.0)
res["ref_ok"] = ok_ref
if not ok_ref:
    print(json.dumps(res)); sys.exit(0)
res["ref_outs"] = [[s, repr(v)] for s, v in ref_outs]
res["ref_types"] = [type(v).__name__ for s, v in ref_outs if s == "OK"]

# ---- classify mutants -----------------------------------------------------
cls = []
mut_outs = []
for m in job["mutants"]:
    try:
        ast.parse(m["src"])
    except SyntaxError:
        cls.append("DISCARDED"); mut_outs.append(None); continue
    ok, outs = run_program(m["src"], calls, 5.0)
    if not ok:
        cls.append("DISCARDED"); mut_outs.append(None); continue
    cls.append("EQUIVALENT" if passes_asserts(m["src"], 5.0) else "WRONG")
    mut_outs.append(outs)
res["mut_class"] = cls
res["mut_all_err"] = [None if o is None else all(s == "ERR" for s, _ in o)
                      for o in mut_outs]

# ---- score specs ----------------------------------------------------------
ARG = [args_of(c) for c, _ in calls]
scored = []
for spec_src in job["specs"]:
    src = spec_src.replace("__ref_type__",
                           res["ref_types"][0] if res["ref_types"] else "object")
    ns = {}
    try:
        signal.setitimer(signal.ITIMER_REAL, 5.0)
        exec(src, ns)
        signal.setitimer(signal.ITIMER_REAL, 0)
    except BaseException:
        signal.setitimer(signal.ITIMER_REAL, 0)
        scored.append({"status": "NONSPEC", "reason": "exec"}); continue
    if "spec" not in ns or not callable(ns["spec"]):
        scored.append({"status": "NONSPEC", "reason": "no-callable"}); continue
    f = ns["spec"]

    def call_spec(a, o):
        """-> True / False / 'NONBOOL' / 'ERR'"""
        try:
            signal.setitimer(signal.ITIMER_REAL, 5.0)
            r = f(tuple(a), o)
            signal.setitimer(signal.ITIMER_REAL, 0)
        except BaseException:
            signal.setitimer(signal.ITIMER_REAL, 0)
            return "ERR"
        if not isinstance(r, bool):
            return "NONBOOL"
        return r

    # VALIDITY — must accept the reference outputs
    valid, bad = True, None
    for i, (s, v) in enumerate(ref_outs):
        if s != "OK":
            continue
        r = call_spec(ARG[i], v)
        if r in ("ERR", "NONBOOL"):
            valid, bad = None, r; break
        if r is False:
            valid = False
    if valid is None:
        scored.append({"status": "NONSPEC", "reason": bad}); continue
    if not valid:
        scored.append({"status": "INVALID"}); continue

    # KILL RATE over WRONG mutants
    killed, denom, killed_x, denom_x = 0, 0, 0, 0
    for j, m in enumerate(job["mutants"]):
        if cls[j] != "WRONG":
            continue
        denom += 1
        allerr = res["mut_all_err"][j]
        if not allerr:
            denom_x += 1
        hit = False
        for i, (s, v) in enumerate(mut_outs[j]):
            if s != "OK":
                continue
            if call_spec(ARG[i], v) is False:
                hit = True; break
        if hit:
            killed += 1
            if not allerr:
                killed_x += 1
    scored.append({"status": "VALID", "killed": killed, "denom": denom,
                   "killed_x": killed_x, "denom_x": denom_x})

res["specs"] = scored
print(json.dumps(res))
'''


def evaluate_problem(fn: str, calls: list, tests: list[str], ref: str,
                     mutants: list[dict], specs: list[str],
                     timeout: float = 180.0) -> dict:
    """Run one problem's whole evaluation in an isolated subprocess."""
    job = {"fn": fn, "calls": calls, "tests": tests, "ref": ref,
           "mutants": mutants, "specs": specs}
    try:
        p = subprocess.run([sys.executable, "-c", _WORKER],
                           input=json.dumps(job), capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ref_ok": False, "error": "worker-timeout"}
    if p.returncode != 0 or not p.stdout.strip():
        return {"ref_ok": False, "error": f"worker-rc={p.returncode}",
                "stderr": p.stderr[-400:]}
    return json.loads(p.stdout)
