"""
Route 14 Part A — the conditioning experiment.

Each model, seeing ONLY the problem statement and the entry-point name, writes
`def spec(inp, out) -> bool`. Two arms (PROP restricts to structural/property
assertions; FREE has no restriction). Cells come from R8's cached programs:
(a) the model's own program was CORRECT, (b) it was WRONG.

Deterministic. SEED = 1, temperature 0. Generations are cached.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "native_verifier"))
CACHE = HERE / "sc_cache"
NV_CACHE = HERE.parent / "native_verifier" / "nv_cache"

SEED = 1
MAX_TOKENS = 400
MODELS = ["meta-llama/llama-3.1-70b-instruct", "google/gemma-2-27b-it",
          "microsoft/phi-4", "mistralai/mistral-small-24b-instruct-2501"]
ARMS = ("PROP", "FREE")

_RULES = """
RULES:
- Assert STRUCTURAL and PROPERTY facts only: relationships between `inp` and
  `out` such as length, type, ordering, membership, preserved quantities,
  ranges, or counts.
- You MUST NOT compute the expected output. Do NOT reimplement {fn} inside
  spec() and compare. A spec that recomputes the answer is not acceptable.
"""


def spec_prompt(problem_text: str, fn: str, arm: str) -> str:
    """Verbatim per PREREGISTRATION §3. Contains NO reference solution, NO MBPP
    asserts, and NO model-written program."""
    rules = _RULES.format(fn=fn) if arm == "PROP" else "\n"
    return (
        "You are given a programming problem description and a function name.\n"
        "Write a Python PREDICATE that checks whether a candidate output is "
        "acceptable.\n\n"
        f"PROBLEM: {problem_text}\n"
        f"FUNCTION NAME: {fn}\n\n"
        "Write exactly one function with this signature:\n\n"
        "def spec(inp, out) -> bool:\n"
        f"    # inp is the tuple of arguments passed to {fn}\n"
        f"    # out is the value {fn} returned\n"
        "    # return True iff `out` is an acceptable output for `inp`\n"
        f"{rules}"
        "- Return only the function. No explanation, no tests, no markdown "
        "fences.\n")


def extract_spec(text: str) -> str | None:
    """Pull the `def spec` function out of a completion. Parser only — never
    repairs semantics."""
    if not text:
        return None
    t = text.strip()
    if "```" in t:
        parts = t.split("```")
        for p in parts:
            if "def spec" in p:
                t = p
                if t.startswith("python"):
                    t = t[len("python"):]
                break
    lines = t.splitlines()
    start = next((i for i, l in enumerate(lines) if l.lstrip().startswith("def spec")), None)
    if start is None:
        return None
    base = len(lines[start]) - len(lines[start].lstrip())
    body = [lines[start][base:]]
    for l in lines[start + 1:]:
        if l.strip() and (len(l) - len(l.lstrip())) <= base and not l[base:].startswith((" ", ")")):
            if not l.lstrip().startswith(("#", '"""', "'''")):
                break
        body.append(l[base:] if len(l) > base else l)
    src = "\n".join(body).rstrip()
    for cut in range(len(body), 0, -1):
        cand = "\n".join(body[:cut]).rstrip()
        try:
            ast.parse(cand)
            return cand
        except SyntaxError:
            continue
    return None


# --------------------------------------------------------------------------- #
#  Oracle-embedding detection (PREREGISTRATION §4)                             #
# --------------------------------------------------------------------------- #
def _n_nodes(src: str) -> int:
    try:
        return sum(1 for _ in ast.walk(ast.parse(src)))
    except SyntaxError:
        return 0


def embedding_flags(spec_src: str, ref_src: str) -> dict:
    """Declared heuristic. Returns the three criteria plus the node ratio."""
    out = {"cmp_recompute": False, "nested_def": False, "ratio_ge_1": False}
    try:
        tree = ast.parse(spec_src)
    except SyntaxError:
        return {**out, "ratio": 0.0, "embedding": False}

    # Transitive taint from `inp`: a recomputation is usually bound to a local
    # first (`kept = [...]; return out == kept`), so an inline-only check misses
    # it. Fixed point over assignments.
    tainted = {"inp"}
    for _ in range(6):
        grew = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                val = getattr(node, "value", None)
                if val is None:
                    continue
                if not ({x.id for x in ast.walk(val) if isinstance(x, ast.Name)} & tainted):
                    continue
                tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in tgts:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name) and x.id not in tainted:
                            tainted.add(x.id)
                            grew = True
        # loop/comprehension targets over an inp-derived iterable are themselves
        # inp-derived: `for a, b in zip(src, out)` makes `a` a view on inp
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.comprehension)):
                if {x.id for x in ast.walk(node.iter) if isinstance(x, ast.Name)} & tainted:
                    for x in ast.walk(node.target):
                        if isinstance(x, ast.Name) and x.id not in tainted:
                            tainted.add(x.id)
                            grew = True
        if not grew:
            break

    # names bound by iterating `out` — an element-wise recomputation compares
    # those rather than `out` itself
    out_elems = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.comprehension)):
            it = node.iter
            if {x.id for x in ast.walk(it) if isinstance(x, ast.Name)} & {"out"}:
                tgt = node.target
                for x in ast.walk(tgt):
                    if isinstance(x, ast.Name):
                        out_elems.add(x.id)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and \
                isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
            sides = [node.left, node.comparators[0]]
            for i, s in enumerate(sides):
                other = sides[1 - i]
                lhs_is_out = (isinstance(s, ast.Name)
                              and (s.id == "out" or s.id in out_elems))
                if not lhs_is_out:
                    continue
                names = {x.id for x in ast.walk(other) if isinstance(x, ast.Name)}
                if names & tainted:
                    out["cmp_recompute"] = True
        if isinstance(node, (ast.FunctionDef, ast.Lambda)):
            if isinstance(node, ast.FunctionDef) and node.name == "spec":
                continue
            if any(isinstance(x, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp,
                                  ast.SetComp, ast.DictComp)) for x in ast.walk(node)):
                out["nested_def"] = True

    ref_n = _n_nodes(ref_src) or 1
    ratio = _n_nodes(spec_src) / ref_n
    out["ratio_ge_1"] = bool(ratio >= 1.0)
    out["ratio"] = round(ratio, 4)

    # PRE-DATA CORRECTION, disclosed (PREREGISTRATION §4 declared three
    # disjuncts). The third — node ratio >= 1.0 — is DROPPED from the embedding
    # definition because it flagged a HAND-WRITTEN, strictly non-embedding
    # reference spec (problem 15): a thorough property spec routinely exceeds a
    # terse reference solution's node count without recomputing anything. That
    # is a demonstrated false positive, found by a test BEFORE any generation
    # ran. Size is not evidence of an oracle; recompute-and-compare is.
    # The ratio remains a REPORTED first-class quantity, as §4 requires, and
    # `ratio_ge_1` is still recorded per spec so the discarded criterion can be
    # audited from the raw results.
    out["embedding"] = bool(out["cmp_recompute"] or out["nested_def"])
    return out


# --------------------------------------------------------------------------- #
#  Generation (cached)                                                         #
# --------------------------------------------------------------------------- #
def _backend(model: str):
    sys.path.insert(0, str(HERE.parent / "correlated_failure"))
    from rho_measure import APIBackend
    key = [l for l in (HERE.parent / "correlated_failure" / ".env").read_text().splitlines()
           if l.startswith("OPENROUTER")][0].split("=", 1)[1].strip()
    return APIBackend(model, model.split("/")[0],
                      base_url="https://openrouter.ai/api/v1", api_key=key)


def generate(problems: list[dict]) -> None:
    CACHE.mkdir(exist_ok=True)
    for model in MODELS:
        b = None
        for arm in ARMS:
            path = CACHE / f"spec__{model.replace('/', '__')}__{arm}.json"
            if path.exists():
                print(f"  cached {path.name}")
                continue
            if b is None:
                b = _backend(model)
            out = []
            for r in problems:
                p = spec_prompt(r["prompt"], r["fn"], arm)
                try:
                    txt = b.generate(p, max_new_tokens=MAX_TOKENS)
                except Exception as e:                       # noqa: BLE001
                    txt = f"__ERR__ {e}"
                out.append({"i": r["i"], "raw": txt,
                            "spec": extract_spec(txt) if not txt.startswith("__ERR__") else None})
            path.write_text(json.dumps(out, indent=1))
            n_ok = sum(1 for x in out if x["spec"])
            print(f"  wrote {path.name}  parsed {n_ok}/{len(out)}")


def load_cells() -> dict:
    """Cell assignment from R8's cache — `source` and `status` come from the
    SAME dict entry of the SAME run (the GATE 0b lesson)."""
    cells = {}
    for model in MODELS:
        f = NV_CACHE / f"prog__{model.replace('/', '__')}.json"
        d = json.loads(f.read_text())
        cells[model] = [e["status"] for e in d]
    return cells


if __name__ == "__main__":
    probs = json.loads((HERE / "problems.json").read_text())
    generate(probs)
