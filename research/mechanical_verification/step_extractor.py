"""
Route 5 — Stage 1: the extractor is a TRANSCRIBER, not a judge. It transcribes
each (step k -> k+1) transition of a cached trace into a machine-readable form for
the CAS. Its prompt forbids evaluating correctness; any correctness commentary is a
PROTOCOL VIOLATION (logged, rate reported). This separation is what makes the CAS —
not the model — the verifier. NOT a Route 2 rescue.
"""
from __future__ import annotations

import json
import re

_JUDGE = re.compile(r"\b(incorrect|is wrong|error|mistake|invalid|should be|actually|"
                    r"the correct|does not follow|flaw)\b", re.I)


def extract_prompt(problem: str, numbered_steps: str) -> str:
    return (
        "You are a strict TRANSCRIBER, not a judge. Below is a numbered step-by-step "
        "solution to a problem. For each consecutive pair of steps (step k -> step k+1), "
        "transcribe the mathematical transition into JSON — exactly WHAT THE SOLUTION "
        "SAYS, verbatim, EVEN IF IT IS WRONG. You must NOT judge correctness, NOT fix "
        "errors, NOT comment on validity, NOT skip a wrong step. Transcribe faithfully.\n\n"
        "Output ONLY a JSON array. Each element:\n"
        '{"from_step": k, "to_step": k+1, "lhs": "<expr>", "rhs": "<expr>", '
        '"relation": "IDENTITY|SOLUTION_SET|SUBSTITUTION|ASSERTION|NOT_EXTRACTABLE", '
        '"free_vars": ["x"], "assumptions": ["x=3"]}\n\n'
        "relation meanings:\n"
        "- IDENTITY: lhs is claimed algebraically EQUAL to rhs (an expansion, "
        "simplification, factoring, rearrangement). Put the two sides in lhs and rhs.\n"
        "- SOLUTION_SET: an equation-solving move (squaring, multiplying/dividing both "
        "sides, isolating). Put the BEFORE equation in lhs and the AFTER equation in rhs, "
        "each as an expression that equals zero.\n"
        "- SUBSTITUTION: a value is plugged in. Put the expression in lhs, the result in "
        "rhs, and the substitution in assumptions (e.g. \"x=3\").\n"
        "- ASSERTION: invoking a theorem, a case split, a definition, a geometric fact, "
        "or introducing a new variable. Leave lhs/rhs empty.\n"
        "- NOT_EXTRACTABLE: prose with no transcribable math.\n\n"
        "Syntax: use ^ for powers, * for multiplication, sqrt() for roots, pi for pi, "
        "/ for division. No LaTeX, no words inside lhs/rhs.\n\n"
        f"Problem: {problem}\n\nNumbered solution:\n{numbered_steps}\n\nJSON array:")


def parse_extraction(raw: str):
    """Return (transitions:list[dict], protocol_violation:bool, parse_ok:bool)."""
    if raw is None or str(raw).startswith("__ERR__"):
        return [], False, False
    # locate the JSON array
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    txt = m.group(0) if m else raw
    trans = None
    for cand in (txt, raw):
        try:
            v = json.loads(cand)
            if isinstance(v, list):
                trans = v
                break
        except Exception:
            continue
    if trans is None:
        return [], False, False
    clean = []
    proto = False
    for t in trans:
        if not isinstance(t, dict):
            continue
        # protocol violation: a correctness field, or a judgement string in any value
        extra = {k for k in t} - {"from_step", "to_step", "lhs", "rhs", "relation",
                                  "free_vars", "assumptions"}
        if extra & {"valid", "correct", "error", "is_correct", "verdict", "comment"}:
            proto = True
        for k in ("lhs", "rhs", "relation"):
            val = t.get(k)
            if isinstance(val, str) and _JUDGE.search(val):
                proto = True
        clean.append({
            "from_step": t.get("from_step"), "to_step": t.get("to_step"),
            "lhs": t.get("lhs"), "rhs": t.get("rhs"),
            "relation": (t.get("relation") or "NOT_EXTRACTABLE"),
            "free_vars": t.get("free_vars") or [],
            "assumptions": t.get("assumptions") or [],
        })
    # a judgement anywhere in the free prose around the JSON is also a soft signal
    prose = raw.replace(txt, "")
    if _JUDGE.search(prose):
        proto = True
    return clean, proto, True
