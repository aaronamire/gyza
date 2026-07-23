"""
Hardened, CONSERVATIVE math-answer canonicalizer for Phase 8 (correction to
Phases 5/6B/7). Fixes the ~33% canonicalization false-positives in the MATH
"wrong" set (\\cfrac, \\dfrac, unicode sqrt, \\text{}, brace-less \\frac32, units,
etc.). Does NOT edit route2/route3 committed code.

equal(a, b) -> True | False | None(UNRESOLVED):
  - True  : provably the same value (normalized-string equal, element-wise for
            lists/tuples, or sympy simplifies the difference to 0).
  - False : sympy (or element-wise) provably confirms DIFFERENT values.
  - None  : cannot be resolved -> EXCLUDED from metrics, never silently "wrong".

CONSERVATIVE: never merges two genuinely different values (no numeric coercion of
sqrt/pi to decimals beyond what sympy proves; distinct fractions stay distinct).
"""
from __future__ import annotations

import re
import signal


def _boxed_inner(s: str) -> str:
    m = re.search(r"\\boxed\{", s)
    if not m:
        return s
    k = s.find("{", m.start())
    depth = 0
    for e in range(k, len(s)):
        if s[e] == "{":
            depth += 1
        elif s[e] == "}":
            depth -= 1
            if depth == 0:
                return s[k + 1:e]
    return s


def norm(s: str) -> str:
    """Normalized display string (units/packaging stripped; value-preserving)."""
    if s is None:
        return ""
    s = _boxed_inner(str(s)).strip()
    # kill LaTeX packaging that never changes the value
    s = re.sub(r"\\displaystyle|\\left|\\right|\\!|\\,|\\;|\\:|\\ ", "", s)
    # ordinal superscripts: ^{\mathrm{th}}, ^{th}, ^\mathrm{st} ...
    s = re.sub(r"\^\s*\{?\s*(?:\\mathrm\s*\{)?\s*(?:st|nd|rd|th)\s*\}?\s*\}?", "", s, flags=re.I)
    s = re.sub(r"\\text\s*\{[^{}]*\}", "", s)
    s = re.sub(r"\\mbox\s*\{[^{}]*\}", "", s)
    s = re.sub(r"\\mathrm\s*\{[^{}]*\}", "", s)
    s = re.sub(r"\^\s*\{\s*\}", "", s)          # empty superscript leftover
    s = s.replace("\\$", "").replace("$", "")
    s = s.replace("\\cfrac", "\\frac").replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    # degrees / percent
    s = re.sub(r"\^?\{?\\circ\}?|°|\\%|%", "", s)
    s = re.sub(r"\bdegrees?\b", "", s, flags=re.I)
    # ordinals + common trailing unit words (value is the number)
    s = re.sub(r"\^?\{?(?:st|nd|rd|th)\}?", "", s, flags=re.I)
    s = re.sub(r"\b(minutes?|hours?|seconds?|inches?|feet|foot|meters?|metres?|"
               r"grades?|dollars?|cents?|degrees?|units?|points?|ways?|times?|"
               r"students?|people|coins?|balls?|solutions?|lines?)\b", "", s, flags=re.I)
    # unicode sqrt -> \sqrt{}
    s = re.sub(r"√\s*\{([^{}]*)\}", r"\\sqrt{\1}", s)
    s = re.sub(r"√\s*\(([^()]*)\)", r"\\sqrt{\1}", s)
    s = re.sub(r"√\s*([0-9a-zA-Z]+)", r"\\sqrt{\1}", s)
    # brace-less \sqrt2 -> \sqrt{2}
    s = re.sub(r"\\sqrt\s*([0-9a-zA-Z])", r"\\sqrt{\1}", s)
    # comma thousands: 19,404 -> 19404
    for _ in range(4):
        s = re.sub(r"(\d),(\d{3})\b", r"\1\2", s)
    # brace-less \frac: \frac32 -> \frac{3}{2}; \frac3{4}, \frac{3}4
    def _fracfix(t):
        prev = None
        while prev != t:
            prev = t
            t = re.sub(r"\\frac\s*(\d)\s*(\d)", r"\\frac{\1}{\2}", t)
            t = re.sub(r"\\frac\s*(\d)\s*\{", r"\\frac{\1}{", t, count=1) if re.search(r"\\frac\s*\d\s*\{", t) else t
            t = re.sub(r"\\frac(\{[^{}]+\})\s*(\d)", r"\\frac\1{\2}", t)
        return t
    s = _fracfix(s)
    s = re.sub(r"\s+", "", s)
    s = s.rstrip(".;,")
    while s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    return s.strip()


class _TO(Exception):
    pass


def _to_sympy(ns: str):
    import sympy
    t = ns
    if t == "" or any(x in t for x in ("\\begin", "\\pmatrix", "\\{", "&", "\\text", "=", "<", ">")):
        return None
    # mixed number: 3\frac{1}{2} -> (3+(1)/(2))
    t = re.sub(r"(?<![\d)])(\d+)\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1+(\2)/(\3))", t)
    for _ in range(8):
        nt = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", t)
        if nt == t:
            break
        t = nt
    t = re.sub(r"\\sqrt\[([^\]]+)\]\{([^{}]+)\}", r"((\2)**(1/(\1)))", t)
    t = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", t)
    t = (t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
          .replace("\\pi", "pi").replace("^", "**").replace("{", "(").replace("}", ")")
          .replace("\\", ""))
    t = re.sub(r"(\d)\(", r"\1*(", t)
    t = re.sub(r"(\d)(sqrt|pi|[a-df-zA-DF-Z])", r"\1*\2", t)   # 2sqrt->2*sqrt (not 1e5)
    t = re.sub(r"\)([\(a-zA-Z0-9])", r")*\1", t)
    if not re.search(r"\d|pi|sqrt|[a-zA-Z]", t):
        return None
    try:
        return sympy.sympify(t, evaluate=True)
    except Exception:
        return None


def _split_list(ns: str):
    """('(4,1)' or '4,1' or '[a,b]') -> ['4','1']; else None."""
    t = ns
    if (t.startswith("(") and t.endswith(")")) or (t.startswith("[") and t.endswith("]")):
        t = t[1:-1]
    if "," in t:
        parts = [p.strip() for p in t.split(",")]
        if len(parts) >= 2 and all(parts):
            return parts
    return None


def equal(a: str, b: str):
    """True | False | None(UNRESOLVED). Conservative."""
    na, nb = norm(a), norm(b)
    if na == "" or nb == "":
        return None
    if na == nb:
        return True
    la, lb = _split_list(na), _split_list(nb)
    if la is not None and lb is not None:
        if len(la) != len(lb):
            return False
        res = [equal(x, y) for x, y in zip(la, lb)]
        if any(r is False for r in res):
            return False
        if all(r is True for r in res):
            return True
        return None
    ea, eb = _to_sympy(na), _to_sympy(nb)
    if ea is not None and eb is not None:
        old = None
        use = False
        try:
            use = signal.getsignal(signal.SIGALRM) is not None
        except Exception:
            use = False
        try:
            if use:
                def _h(sig, frm):
                    raise _TO()
                old = signal.signal(signal.SIGALRM, _h)
                signal.setitimer(signal.ITIMER_REAL, 3.0)
            import sympy
            d = sympy.simplify(ea - eb)
            return bool(d == 0) or bool(getattr(d, "is_zero", False))
        except Exception:
            try:
                return bool(ea.equals(eb))
            except Exception:
                return None
        finally:
            if use:
                signal.setitimer(signal.ITIMER_REAL, 0.0)
                if old is not None:
                    signal.signal(signal.SIGALRM, old)
    return None
