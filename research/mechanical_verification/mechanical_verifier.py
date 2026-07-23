"""
Route 5 — Stage 2: the MECHANICAL verifier (a CAS, zero model calls). Given a
transcribed transition {lhs, rhs, relation, free_vars, assumptions}, returns a
verdict using sympy only. No LLM is involved here — this is the actual verifier,
and its non-intelligence is the point. NOT a Route 2 rescue.

Verdicts: PASS | VIOLATION | ENLARGED_UNSAFE | UNRESOLVED | UNCHECKABLE.
IDENTITY: random-point evaluation is PRIMARY (robust to simplify() timeouts and
sympy incompleteness); simplify() is confirmatory. Undefined sample points are
SKIPPED. TIMEOUT/exception -> UNRESOLVED (excluded, never a violation or a pass).
"""
from __future__ import annotations

import math
import random
import signal
from fractions import Fraction

import sympy


class _TO(Exception):
    pass


class timeout:
    def __init__(self, sec):
        self.sec = sec
        self.ok = False

    def __enter__(self):
        try:
            if signal.getsignal(signal.SIGALRM) is not None:
                self._old = signal.signal(signal.SIGALRM, self._h)
                signal.setitimer(signal.ITIMER_REAL, self.sec)
                self.ok = True
        except Exception:
            self.ok = False
        return self

    def _h(self, s, f):
        raise _TO()

    def __exit__(self, *a):
        if self.ok:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, self._old)
        return False


_TR = {"^": "**"}


def parse(s):
    if s is None:
        return None
    t = str(s).strip()
    if t == "" or any(x in t for x in ("\\", "$", "matrix", "\n")):
        # light cleanup of common latex residue
        t = (t.replace("\\left", "").replace("\\right", "").replace("$", "")
              .replace("\\cdot", "*").replace("\\times", "*").replace("\\", ""))
    t = t.replace("^", "**")
    if t == "" or "=" in t or "<" in t or ">" in t:
        return None
    try:
        with timeout(3):
            e = sympy.sympify(t, evaluate=True)
        # only scalar expressions are checkable; tuples/lists/relationals -> UNRESOLVED
        return e if isinstance(e, sympy.Expr) else None
    except Exception:
        return None


def _rand_point(rng, syms):
    return {s: sympy.Rational(rng.randint(-9, 9), rng.randint(1, 4)) for s in syms}


def _split_eq(s):
    if s is None:
        return None
    parts = str(s).split("=")
    parts = [p for p in parts if p.strip() != ""]
    return (parts[0], parts[1]) if len(parts) == 2 else None


def verify_identity(lhs, rhs, n_points=30, min_valid=3):
    """Semantically sound routing (a-priori, not FPR-tuned): a transition between
    two EQUATIONS is a solution-preservation move -> check solution-set equivalence
    (REDUCED = VIOLATION); an equation A=B alone is a claimed algebraic identity ->
    check A==B; two EXPRESSIONS -> check lhs==rhs. NOTE: this cannot distinguish a
    false identity (a real error) from a conditional equation the extractor
    MISLABELLED as IDENTITY — that mislabelling shows up as FPR, the honest measure
    of extraction reliability."""
    le, re = _split_eq(lhs), _split_eq(rhs)
    if le is not None and re is not None:
        return verify_solution_set(lhs, rhs)     # equation -> equation: preserve solutions
    if le is not None:
        return _identity_pair(le[0], le[1], n_points, min_valid)
    if re is not None:
        return _identity_pair(re[0], re[1], n_points, min_valid)
    return _identity_pair(lhs, rhs, n_points, min_valid)


def _identity_pair(lhs, rhs, n_points=30, min_valid=3):
    L, R = parse(lhs), parse(rhs)
    if L is None or R is None:
        return "UNRESOLVED", {"reason": "parse"}
    syms = sorted(L.free_symbols | R.free_symbols, key=str)
    rng = random.Random(abs(hash((str(lhs), str(rhs)))) % (2 ** 31))
    valid = fails = 0
    for _ in range(n_points * 3):
        if valid >= n_points:
            break
        subs = _rand_point(rng, syms) if syms else {}
        try:
            with timeout(1):
                la = complex(sympy.N(L.subs(subs)))
                rb = complex(sympy.N(R.subs(subs)))
        except Exception:
            continue
        if not (math.isfinite(la.real) and math.isfinite(rb.real)
                and math.isfinite(la.imag) and math.isfinite(rb.imag)):
            continue
        valid += 1
        if abs(la - rb) > 1e-6 * (1 + abs(la)):
            fails += 1
    simp = None
    try:
        with timeout(5):
            d = sympy.simplify(L - R)
            simp = bool(d == 0) or bool(getattr(d, "is_zero", False))
    except Exception:
        simp = None
    detail = {"valid_points": valid, "fail_points": fails, "simplify": simp}
    if valid < min_valid:
        if simp is True:
            return "PASS", detail
        if simp is False:
            return "VIOLATION", detail
        return "UNRESOLVED", detail
    if fails >= 2 and simp is not True:
        return "VIOLATION", detail
    if fails == 0 or simp is True:
        return "PASS", detail
    return "UNRESOLVED", detail          # 1 fail, simplify uncertain -> borderline


def _solset(expr):
    eq = _split_eq(expr)
    if eq is not None:                       # "A=B" -> solve(A-B=0)
        a, b = parse(eq[0]), parse(eq[1])
        e = (a - b) if (a is not None and b is not None) else None
    else:
        e = parse(expr)
    if e is None:
        return None
    syms = sorted(e.free_symbols, key=str)
    if not syms:
        return None
    try:
        with timeout(5):
            sols = sympy.solve(sympy.Eq(e, 0), syms[0])
        return frozenset(sympy.nsimplify(x) if x.free_symbols == set() else x for x in sols)
    except Exception:
        return None


def verify_solution_set(lhs, rhs):
    sl, sr = _solset(lhs), _solset(rhs)
    if sl is None or sr is None:
        return "UNRESOLVED", {"reason": "solve"}
    detail = {"lhs_sols": [str(x) for x in sl], "rhs_sols": [str(x) for x in sr]}
    if sl == sr:
        return "PRESERVED", detail
    if sl <= sr:                     # rhs has all of lhs plus extras
        return "ENLARGED_UNSAFE", detail
    if sr <= sl:                     # rhs dropped some solutions
        return "VIOLATION", detail   # REDUCED
    return "UNRESOLVED", detail      # incomparable


def verify_substitution(lhs, rhs, assumptions):
    """lhs with the assumption substitutions applied should equal rhs."""
    L, R = parse(lhs), parse(rhs)
    if L is None or R is None:
        return "UNRESOLVED", {"reason": "parse"}
    subs = {}
    for a in (assumptions or []):
        if isinstance(a, str) and "=" in a and a.count("=") == 1:
            k, v = a.split("=")
            ks, vp = parse(k.strip()), parse(v.strip())
            if ks is not None and vp is not None and getattr(ks, "is_symbol", False):
                subs[ks] = vp
    try:
        with timeout(5):
            d = sympy.simplify(L.subs(subs) - R)
            eq = bool(d == 0) or bool(getattr(d, "is_zero", False))
        return ("PASS" if eq else "VIOLATION"), {"subs": {str(k): str(v) for k, v in subs.items()}}
    except Exception:
        return "UNRESOLVED", {"reason": "timeout"}


def verify_transition(t: dict):
    """Dispatch on relation. Returns (verdict, detail)."""
    rel = (t.get("relation") or "").upper()
    if rel == "IDENTITY":
        return verify_identity(t.get("lhs"), t.get("rhs"))
    if rel == "SOLUTION_SET":
        return verify_solution_set(t.get("lhs"), t.get("rhs"))
    if rel == "SUBSTITUTION":
        return verify_substitution(t.get("lhs"), t.get("rhs"), t.get("assumptions"))
    if rel in ("ASSERTION", "NOT_EXTRACTABLE"):
        return "UNCHECKABLE", {}
    return "UNCHECKABLE", {"reason": "unknown_relation"}


# A VIOLATION for the primary detector (ENLARGED_UNSAFE excluded from primary).
def is_violation(verdict: str, count_enlarged: bool = False) -> bool:
    if verdict == "VIOLATION":
        return True
    if count_enlarged and verdict == "ENLARGED_UNSAFE":
        return True
    return False


def is_checkable(verdict: str) -> bool:
    return verdict in ("PASS", "VIOLATION", "ENLARGED_UNSAFE")
