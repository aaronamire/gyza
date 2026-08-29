"""
Route 8 — native formal verifier test. Does test-writing require competence?

Stage 1 (test generation) needs model calls and is cached to nv_cache/. Stage 2
(execution) and Stage 3 (metrics) are OFFLINE and pure — zero model calls, they read
only the cache. Importable, no import side effects.

Isolation invariant (asserted in tests): a test-generation prompt contains the problem
statement + entry_point and NEVER the reference solution, the original MBPP asserts, or
any claimant program.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "correlated_failure"))
from codebench import (  # noqa: E402
    entry_point, expected_signature, extract_calls, load_mbpp, run_signature,
)

SEED = 1
N_CODE = 50
CACHE = HERE / "nv_cache"
CHECKERS = [
    ("meta-llama/llama-3.1-70b-instruct", "llama"),
    ("google/gemma-2-27b-it", "gemma"),
    ("microsoft/phi-4", "phi"),
    ("mistralai/mistral-small-24b-instruct-2501", "mistral"),
]
ROUND1_PASS = {"meta-llama/llama-3.1-70b-instruct": 0.40, "google/gemma-2-27b-it": 0.38,
               "microsoft/phi-4": 0.38, "mistralai/mistral-small-24b-instruct-2501": 0.32}


# --------------------------------------------------------------------------- #
#  prompts (isolation-preserving)                                             #
# --------------------------------------------------------------------------- #
def code_prompt(problem, fn):
    """Round-1 code-generation prompt, verbatim (substrate comparability)."""
    name = f" named `{fn}`" if fn else ""
    return (f"Write a Python function{name} for this task:\n{problem['prompt']}\n"
            f"Respond with ONLY the code in a python code block.")


def testgen_prompt(problem, fn, arm):
    """Arm E (example) / Arm P (property) test-generation prompt. Contains ONLY the
    problem statement + function name — never the reference, asserts, or any program."""
    base = (f"named `{fn}` for this task:\n{problem['prompt']}\n")
    if arm == "E":
        return (f"Write exactly 5 Python `assert` statements that test a function {base}"
                "Use concrete example inputs and their correct expected outputs, one per "
                f"line, of the form: assert {fn}(...) == <expected>.\n"
                "Do NOT define the function. Respond with ONLY a python code block "
                "containing the 5 assert statements.")
    if arm == "P":
        return (f"Write exactly 5 Python `assert` statements checking PROPERTIES and "
                f"INVARIANTS that ANY correct implementation of a function {base}"
                "A property must hold for every valid input WITHOUT knowing the expected "
                "return value — for example: the output type or length, order-invariance, "
                f"idempotence {fn}(x)==... , conservation of length or multiset, or a "
                f"relation between {fn}(x) and {fn} of a transformed input. "
                "Do NOT assert a concrete expected return value. Do NOT define the "
                "function. Respond with ONLY a python code block containing the 5 asserts.")
    raise ValueError(arm)


# --------------------------------------------------------------------------- #
#  parsing                                                                    #
# --------------------------------------------------------------------------- #
def _extract_block(text):
    import re
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


def extract_asserts(text):
    """Return the list of top-level `assert` statement sources in the model output.
    Robust to non-assert lines; falls back to line scan if the block won't parse."""
    block = _extract_block(text)
    out = []
    try:
        tree = ast.parse(block)
        for node in tree.body:
            if isinstance(node, ast.Assert):
                seg = ast.get_source_segment(block, node)
                if seg:
                    out.append(seg.strip())
    except SyntaxError:
        for line in block.splitlines():
            if line.strip().startswith("assert "):
                out.append(line.strip())
    return out


def is_smuggled_example(test_src, fn):
    """Arm-P protocol violation: an assert comparing fn(concrete) to a pure literal
    (a smuggled expected output). True => violation."""
    try:
        node = ast.parse(test_src.strip()).body[0]
    except (SyntaxError, IndexError):
        return False
    if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
        return False

    def calls_fn(n):
        return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                   and c.func.id == fn for c in ast.walk(n))

    def is_literal(n):
        return isinstance(n, ast.Constant) or (
            isinstance(n, (ast.List, ast.Tuple, ast.Set)) and
            all(is_literal(e) for e in n.elts)) or (
            isinstance(n, ast.Dict) and all(is_literal(e) for e in (n.keys + n.values)))

    sides = [node.test.left] + list(node.test.comparators)
    has_fn = any(calls_fn(s) for s in sides)
    has_lit = any(is_literal(s) and not calls_fn(s) for s in sides)
    # only flag Eq/NotEq comparisons of fn(...) to a constant literal
    ops_eq = all(isinstance(o, (ast.Eq, ast.NotEq)) for o in node.test.ops)
    return has_fn and has_lit and ops_eq


# --------------------------------------------------------------------------- #
#  offline execution (zero model calls)                                       #
# --------------------------------------------------------------------------- #
_TEST_HARNESS = '''
import json, sys
_prog = open(sys.argv[1]).read()
_test = open(sys.argv[2]).read()
_ns = {}
try:
    exec(_prog, _ns)
except Exception as e:
    print(json.dumps("IMPORTERR:" + type(e).__name__)); sys.exit()
try:
    exec(_test, _ns)
    print(json.dumps("PASS"))
except AssertionError:
    print(json.dumps("FAIL"))
except Exception as e:
    print(json.dumps("ERR:" + type(e).__name__))
'''


def run_one_test(program_src, test_src, timeout=5.0):
    """PASS | FAIL | ERR:Type | IMPORTERR:Type | TIMEOUT. FAIL = assertion tripped."""
    with tempfile.NamedTemporaryFile("w", suffix="_h.py", delete=False) as fh:
        fh.write(_TEST_HARNESS)
        h = fh.name
    with tempfile.NamedTemporaryFile("w", suffix="_p.py", delete=False) as fp:
        fp.write(program_src)
        pf = fp.name
    with tempfile.NamedTemporaryFile("w", suffix="_t.py", delete=False) as ft:
        ft.write(test_src)
        tf = ft.name
    try:
        p = subprocess.run([sys.executable, h, pf, tf], capture_output=True, text=True,
                           timeout=timeout)
        return json.loads(p.stdout) if p.stdout.strip() else "TIMEOUT"
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return "TIMEOUT"
    finally:
        for x in (h, pf, tf):
            Path(x).unlink(missing_ok=True)


def classify_bug(signature, expected):
    """COMPUTATIONAL (right function, wrong step) vs COMPREHENSION (wrong function,
    misread spec), from the behavioral signature vs expected. None if not a bug.
    Heuristic (hand-validated in Q4): partial correctness OR matching output TYPES =>
    computational (right shape, slips on value); all wrong AND type/shape mismatch =>
    comprehension (produced the wrong kind of thing)."""
    if not signature or signature == expected:
        return None
    if isinstance(signature[0], str) and (signature[0].startswith("TIMEOUT")
                                          or signature[0].startswith("IMPORTERR")):
        return None
    n = len(expected)
    matches = sum(s == e for s, e in zip(signature, expected))
    if matches == n:
        return None
    # a program that CRASHES / never exposes the entry_point on every call is neither a
    # computational nor a comprehension bug — it is a third class (trivially catchable).
    if all(str(s).startswith("ERR") or str(s).startswith("IMPORTERR")
           for s in signature):
        return "CRASH"

    def kind(r):
        try:
            return type(ast.literal_eval(r)).__name__
        except Exception:
            return "ERR" if str(r).startswith("ERR") else "other"

    type_match = sum(kind(s) == kind(e) for s, e in zip(signature, expected))
    if matches > 0:
        return "COMPUTATIONAL"          # gets some calls right -> right function, slips
    if type_match >= (n + 1) // 2:
        return "COMPUTATIONAL"          # right output shape, wrong value
    return "COMPREHENSION"              # wrong shape/type (non-crash) -> misread the task


def program_status(signature, expected, source=None):
    """CORRECT | WRONG | UNRESOLVED. UNRESOLVED = generation failure (__ERR__ source) or
    whole-program timeout/import failure in the original harness — never scored."""
    if source is not None and str(source).startswith("__ERR__"):
        return "UNRESOLVED"             # the API call failed; there is no program
    if not signature:
        return "UNRESOLVED"
    s0 = signature[0]
    if isinstance(s0, str) and (s0.startswith("TIMEOUT") or s0.startswith("IMPORTERR")):
        return "UNRESOLVED"
    return "CORRECT" if signature == expected else "WRONG"


def test_is_valid(test_src, reference_src, timeout=5.0):
    """A test is VALID iff it PASSES the MBPP reference solution (else it is wrong or
    over-strict and is excluded from numerator AND denominator)."""
    return run_one_test(reference_src, test_src, timeout) == "PASS"


def suite_fires(valid_tests, program_src, timeout=5.0):
    """Suite fires iff >=1 VALID test does not PASS on the program under test."""
    for t in valid_tests:
        if run_one_test(program_src, t, timeout) != "PASS":
            return True
    return False


def score_triple(valid_tests, program_src, wrong, timeout=5.0):
    """(fired, wrong) for a (suite, program) pair, or None if the suite has NO valid
    tests (coverage loss — excluded from both TPR and FPR, never counted)."""
    if not valid_tests:
        return None
    return (suite_fires(valid_tests, program_src, timeout), bool(wrong))


# --------------------------------------------------------------------------- #
#  metrics                                                                     #
# --------------------------------------------------------------------------- #
def _boot_ci(items, seed=0, n=3000):
    """Item(problem)-bootstrap CI for Youden J. `items` = list of (fired, wrong) or
    None; resample problems, recompute J = TPR-FPR."""
    rng = np.random.default_rng(seed)
    groups = [g for g in items if g]
    if not groups:
        return (None, None, None)

    def J_of(sample):
        tp = fp = tn = fn = 0
        for grp in sample:
            for fired, wrong in grp:
                if wrong:
                    tp += fired; fn += (not fired)
                else:
                    fp += fired; tn += (not fired)
        tpr = tp / (tp + fn) if (tp + fn) else np.nan
        fpr = fp / (fp + tn) if (fp + tn) else np.nan
        return (tpr - fpr) if not (np.isnan(tpr) or np.isnan(fpr)) else np.nan

    obs = J_of(groups)
    boot = []
    for _ in range(n):
        idx = rng.integers(0, len(groups), len(groups))
        j = J_of([groups[i] for i in idx])
        if not np.isnan(j):
            boot.append(j)
    if not boot:
        return (obs, None, None)
    return (round(float(obs), 4), round(float(np.percentile(boot, 2.5)), 4),
            round(float(np.percentile(boot, 97.5)), 4))


def _perm_p(pairs, seed=0, n=3000):
    """Permutation null for J: shuffle the wrong-labels against fired, empirical p."""
    fired = np.array([f for f, _ in pairs], dtype=float)
    wrong = np.array([w for _, w in pairs], dtype=float)
    if fired.sum() == 0 or wrong.sum() == 0 or wrong.sum() == len(wrong):
        return None

    def J(f, w):
        tp = ((f == 1) & (w == 1)).sum(); fn = ((f == 0) & (w == 1)).sum()
        fp = ((f == 1) & (w == 0)).sum(); tn = ((f == 0) & (w == 0)).sum()
        tpr = tp / (tp + fn) if (tp + fn) else 0.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        return tpr - fpr

    obs = J(fired, wrong)
    rng = np.random.default_rng(seed)
    ge = sum(J(fired, rng.permutation(wrong)) >= obs for _ in range(n))
    return round((ge + 1) / (n + 1), 5)


def metrics_from_pairs(pairs, groups=None, seed=0):
    """pairs = list of (fired:bool, wrong:bool). Returns the full metric block."""
    n = len(pairs)
    if n == 0:
        return dict(n=0)
    tp = sum(f and w for f, w in pairs); fn = sum((not f) and w for f, w in pairs)
    fp = sum(f and (not w) for f, w in pairs); tn = sum((not f) and (not w) for f, w in pairs)
    tpr = tp / (tp + fn) if (tp + fn) else None
    fpr = fp / (fp + tn) if (fp + tn) else None
    j = (tpr - fpr) if (tpr is not None and fpr is not None) else None
    lr = (tpr / fpr) if (tpr is not None and fpr not in (None, 0)) else (
        float("inf") if (tpr not in (None, 0) and fpr == 0) else None)
    prec = tp / (tp + fp) if (tp + fp) else None
    firing = (tp + fp) / n
    jci = _boot_ci(groups, seed=seed) if groups else (j, None, None)
    return dict(n=n, n_wrong=tp + fn, n_correct=fp + tn, tp=tp, fp=fp, tn=tn, fn=fn,
                TPR=round(tpr, 4) if tpr is not None else None,
                FPR=round(fpr, 4) if fpr is not None else None,
                firing_rate=round(firing, 4),
                precision=round(prec, 4) if prec is not None else None,
                LR=(round(lr, 3) if lr not in (None, float("inf")) else lr),
                J=jci[0], J_ci=[jci[1], jci[2]],
                perm_p=_perm_p(pairs, seed=seed))


__all__ = ["CHECKERS", "N_CODE", "SEED", "CACHE", "ROUND1_PASS", "code_prompt",
           "testgen_prompt", "extract_asserts", "is_smuggled_example", "run_one_test",
           "program_status", "test_is_valid", "suite_fires", "score_triple",
           "metrics_from_pairs",
           "load_mbpp", "entry_point", "extract_calls", "expected_signature",
           "run_signature"]
