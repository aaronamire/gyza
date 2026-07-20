"""
Code battery — the confound-free test of the shared-blind-spot claim.

Neither confound of the TruthfulQA measurement applies here: there is no
curated wrong-answer list to collapse onto, and no topic-similarity
inflation. The "wrong answer" is a program's BEHAVIOR — its actual
outputs on the test inputs — an effectively infinite space. Two models
from different families producing the SAME specific wrong outputs is a
shared bug that nobody can attribute to measurement artifact.

Signal: among problems where >=2 models produce a FAILING program, do
their behavioral signatures (the tuple of outputs on the test inputs)
match, above a permutation null? That is same-bug convergence.

Execution is sandboxed in a subprocess with a wall-clock timeout. (In
production this is exactly what Gyza's bwrap sandbox is for — running
untrusted generated code with a signed bounds-proof; here a timeout
subprocess suffices for the study.)

Needs models that can code — the tiny local models cannot, so the real
run is the capability-matched / API run. This file builds and VALIDATES
the instrument on synthetic programs with known same/different bugs.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


def load_mbpp(n: "int | None" = None, seed: int = 0) -> list[dict]:
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq
    path = hf_hub_download(repo_id="google-research-datasets/mbpp",
                           filename="full/test-00000-of-00001.parquet",
                           repo_type="dataset")
    rows = pq.read_table(path).to_pylist()
    items = [{"prompt": r["text"], "code": r["code"], "test_list": list(r["test_list"])}
             for r in rows]
    if n is not None:
        idx = np.random.default_rng(seed).permutation(len(items))[:n]
        items = [items[i] for i in sorted(idx)]
    return items


def extract_calls(test_list: list[str]) -> list[tuple[str, str]]:
    """From each ``assert <call> == <expected>`` return (call_src, expected_src)."""
    out = []
    for t in test_list:
        try:
            node = ast.parse(t.strip()).body[0]
            if (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)
                    and len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.Eq)):
                call = ast.get_source_segment(t, node.test.left)
                exp = ast.get_source_segment(t, node.test.comparators[0])
                if call and exp:
                    out.append((call, exp))
        except SyntaxError:
            continue
    return out


_HARNESS = '''
import json, sys
_code = sys.stdin.read()
_calls = json.loads(sys.argv[1])
_ns = {{}}
sig = []
try:
    exec(_code, _ns)
except Exception as e:
    print(json.dumps(["IMPORTERR:" + type(e).__name__] * len(_calls))); sys.exit()
for call, _exp in _calls:
    try:
        sig.append(repr(eval(call, _ns)))
    except Exception as e:
        sig.append("ERR:" + type(e).__name__)
print(json.dumps(sig))
'''


def run_signature(code: str, calls: list[tuple[str, str]], *,
                  timeout: float = 5.0) -> list[str]:
    """Behavioral signature: repr of each call's output (or ERR:type),
    executed in a timeout-bounded subprocess. A crash/timeout yields a
    sentinel signature so it never spuriously matches a real output."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(_HARNESS.format())
        harness = f.name
    try:
        p = subprocess.run([sys.executable, harness, json.dumps(calls)],
                           input=code, capture_output=True, text=True,
                           timeout=timeout)
        return json.loads(p.stdout) if p.stdout.strip() else ["TIMEOUT"] * len(calls)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return ["TIMEOUT"] * len(calls)
    finally:
        Path(harness).unlink(missing_ok=True)


def expected_signature(calls: list[tuple[str, str]]) -> list[str]:
    return [repr(eval(exp, {})) for _call, exp in calls]


def same_bug_convergence(signatures: list[list[list[str]]], expected: list[list[str]],
                         *, n_perms: int = 30, seed: int = 0) -> dict:
    """
    ``signatures[model][problem]`` is a behavioral signature (list[str]).
    A program is WRONG if its signature != the expected. Among problems
    where two models are both wrong, convergence = they have the IDENTICAL
    wrong signature. Permutation null shuffles one model's signatures
    across problems (chance collision in the behavior space ~ 0).
    """
    rng = np.random.default_rng(seed)
    m = len(signatures)
    n = len(expected)
    wrong = [[signatures[i][q] != expected[q] for q in range(n)] for i in range(m)]

    def rate(i, j, perm):
        d = same = 0
        for q in range(n):
            qj = perm[q]
            if wrong[i][q] and wrong[j][qj]:
                d += 1
                same += (signatures[i][q] == signatures[j][qj])
        return (same / d, d) if d else (np.nan, 0)

    ident = list(range(n))
    obs, null = [], []
    for i in range(m):
        for j in range(i + 1, m):
            r, _ = rate(i, j, ident)
            if not np.isnan(r):
                obs.append(r)
            for _ in range(n_perms):
                pr, _ = rate(i, j, list(rng.permutation(n)))
                if not np.isnan(pr):
                    null.append(pr)
    return {
        "same_bug_convergence": round(float(np.mean(obs)), 4) if obs else None,
        "permutation_null": round(float(np.mean(null)), 4) if null else None,
    }


__all__ = ["load_mbpp", "extract_calls", "run_signature", "expected_signature",
           "same_bug_convergence"]
