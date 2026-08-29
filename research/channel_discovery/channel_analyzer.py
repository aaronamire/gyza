"""
Route 12 — mechanical channel discovery. AST-only static analysis.

CRITERION (PREREGISTRATION_R12.md §1, verbatim):
    a is a BLIND CHANNEL for (g,h)
    iff  WRITES(a) ∩ READS(h) != {}  AND  WRITES(a) ∩ READS(g) = {}

ONE-SIDED: failing the check proves the guard is blind to that channel; PASSING
IT PROVES NOTHING. This is a screening test, never a certificate.

GATE 0b — NON-CIRCULARITY. This module reads source text only. It must never open
an R9 result or write-up; `FORBIDDEN` names them and `test_non_circularity`
enforces it with an audit hook plus a negative control.

GATE 0c — NO LLM. Extraction is `ast` only. There is no model client on this path
and `test_no_llm_on_analysis_path` pins that. R5 died because an LLM extraction
stage re-imported the competence bound; this analyzer has no such stage.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

FORBIDDEN = ("r9_result.json", "_scripted.json", "_redteam.json",
             "FINDINGS_R9.md", "rt_cache", "r12_result.json")

# --------------------------------------------------------------------------- #
#  A1 — FIELD MODEL                                                            #
# --------------------------------------------------------------------------- #
# Derived from the `State` dataclass field list; property accessors are aliases.
BASE_FIELDS = {"balances", "owner", "objects", "archive", "external_log",
               "caps", "auths", "events",
               # extended-environment fields (PREREGISTRATION_R12.md §3)
               "principal", "escrow", "snapshots"}
ALIASES = {"bal": "balances", "own": "owner", "objs": "objects",
           "capmap": "caps", "esc": "escrow"}


def canon(attr: str) -> str | None:
    a = ALIASES.get(attr, attr)
    return a if a in BASE_FIELDS else None


@dataclass
class Summary:
    """Per-function field access, keyed by the parameter the access hangs off."""
    reads: set[tuple[int, str]] = field(default_factory=set)      # (param idx, field)
    pinned: set[str] = field(default_factory=set)                 # s0-derived reads
    unresolved: int = 0


def _lit_kinds(test: ast.expr) -> set[str] | None:
    """Kinds selected by `a.kind == "x"` / `a.kind in ("x","y")`, else None."""
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        left, op, cmp = test.left, test.ops[0], test.comparators[0]
        if isinstance(left, ast.Attribute) and left.attr == "kind":
            if isinstance(op, ast.Eq) and isinstance(cmp, ast.Constant):
                return {cmp.value}
            if isinstance(op, ast.In) and isinstance(cmp, (ast.Tuple, ast.List)):
                return {e.value for e in cmp.elts if isinstance(e, ast.Constant)}
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        for v in test.values:
            k = _lit_kinds(v)
            if k is not None:
                return k
    return None


def _prune(body: list[ast.stmt], kind: str | None) -> list[ast.stmt]:
    """V2 path-sensitivity: drop `if a.kind == K'` branches unreachable for `kind`."""
    if kind is None:
        return body
    out: list[ast.stmt] = []
    for st in body:
        if isinstance(st, ast.If):
            sel = _lit_kinds(st.test)
            if sel is not None and kind not in sel:
                out.extend(_prune(st.orelse, kind))
                continue
            if sel is not None:
                out.extend(_prune(st.body, kind))
                continue
            out.append(ast.If(test=st.test, body=_prune(st.body, kind),
                              orelse=_prune(st.orelse, kind)))
            continue
        out.append(st)
    return out


class _Collector(ast.NodeVisitor):
    """Collect field accesses hanging off named roots."""

    def __init__(self, params: list[str], pinned_roots: set[str],
                 fnmap: dict, live_only: bool, kind: str | None):
        self.params = params
        self.pinned_roots = pinned_roots
        self.fnmap = fnmap
        self.live_only = live_only
        self.kind = kind
        self.summary = Summary()
        self.bindings: dict[str, tuple[int, str]] = {}   # local name -> (idx, field)
        self.pinned_bind: dict[str, str] = {}
        self.used: set[str] = set()

    # -- helpers ----------------------------------------------------------- #
    def _root(self, node: ast.expr) -> tuple[str | None, bool]:
        """(root parameter name, is_pinned) for an expression, or (None, False)."""
        cur = node
        while True:
            if isinstance(cur, ast.Name):
                if cur.id in self.pinned_roots:
                    return cur.id, True
                return (cur.id, False) if cur.id in self.params else (None, False)
            if isinstance(cur, ast.Attribute):
                if (isinstance(cur.value, ast.Name) and cur.value.id == "self"
                        and cur.attr in self.pinned_roots):
                    return f"self.{cur.attr}", True
                cur = cur.value
                continue
            if isinstance(cur, ast.Call):
                # e.g. apply(s, a): reads of the successor ARE reads of the field
                for arg in cur.args:
                    r, p = self._root(arg)
                    if r is not None:
                        return r, p
                return None, False
            if isinstance(cur, ast.Subscript):
                cur = cur.value
                continue
            return None, False

    def _record(self, root: str, pinned: bool, fld: str, bind: str | None = None):
        if pinned:
            self.summary.pinned.add(fld)
            if bind:
                self.pinned_bind[bind] = fld
            return
        if root not in self.params:
            return
        idx = self.params.index(root)
        if bind is not None and self.live_only:
            self.bindings[bind] = (idx, fld)      # deferred until proven live
        else:
            self.summary.reads.add((idx, fld))

    # -- visits ------------------------------------------------------------ #
    def visit_Attribute(self, node: ast.Attribute):
        fld = canon(node.attr)
        if fld is not None:
            root, pinned = self._root(node.value)
            if root is not None:
                self._record(root, pinned, fld)
            else:
                self.summary.unresolved += 1
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        # `own = s.own` — bind so V2 can drop it if `own` is never used
        if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Attribute)):
            fld = canon(node.value.attr)
            if fld is not None:
                root, pinned = self._root(node.value.value)
                if root is not None:
                    self._record(root, pinned, fld, bind=node.targets[0].id)
                    return                                  # do not double-count
        # tuple unpack: `bal, own, objs = s.bal, s.own, s.objs`
        if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Tuple)
                and isinstance(node.value, ast.Tuple)
                and len(node.targets[0].elts) == len(node.value.elts)):
            handled = True
            for tgt, val in zip(node.targets[0].elts, node.value.elts):
                if not (isinstance(tgt, ast.Name) and isinstance(val, ast.Attribute)
                        and canon(val.attr)):
                    handled = False
                    break
            if handled:
                for tgt, val in zip(node.targets[0].elts, node.value.elts):
                    root, pinned = self._root(val.value)      # type: ignore[union-attr]
                    if root is not None:
                        self._record(root, pinned, canon(val.attr),   # type: ignore[arg-type]
                                     bind=tgt.id)              # type: ignore[union-attr]
                return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load):
            self.used.add(node.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else (
            fn.attr if isinstance(fn, ast.Attribute) else None)
        callee = self.fnmap.get(name)
        if callee is not None:
            sub = summarize(callee, self.fnmap, live_only=self.live_only,
                            kind=self.kind)
            self.summary.pinned |= sub.pinned
            self.summary.unresolved += sub.unresolved
            args = list(node.args)
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) \
                    and fn.value.id == "self":
                args = [ast.Name(id="self", ctx=ast.Load())] + args
            for idx, fld in sub.reads:
                if idx < len(args):
                    root, pinned = self._root(args[idx])
                    if root is not None:
                        self._record(root, pinned, fld)
                    else:
                        self.summary.unresolved += 1
                else:
                    self.summary.unresolved += 1
        self.generic_visit(node)


def summarize(fn: ast.FunctionDef, fnmap: dict, *, live_only: bool = False,
              kind: str | None = None, pinned_roots: set[str] | None = None) -> Summary:
    params = [a.arg for a in fn.args.args]
    roots = set(pinned_roots or set()) | {"s0", "s_0"}
    body = _prune(fn.body, kind) if live_only else fn.body
    c = _Collector(params, roots, fnmap, live_only, kind)
    for st in body:
        c.visit(st)
    s = c.summary
    if live_only:
        for name, (idx, fld) in c.bindings.items():
            if name in c.used:
                s.reads.add((idx, fld))
    else:
        for _name, (idx, fld) in c.bindings.items():
            s.reads.add((idx, fld))
    return s


# --------------------------------------------------------------------------- #
#  Module loading                                                              #
# --------------------------------------------------------------------------- #
class Module:
    def __init__(self, path: Path):
        assert not any(f in str(path) for f in FORBIDDEN), \
            f"NON-CIRCULARITY VIOLATION: analyzer tried to read {path}"
        self.path = path
        self.tree = ast.parse(path.read_text())
        self.functions: dict[str, ast.FunctionDef] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef):
                self.functions[node.name] = node
            elif isinstance(node, ast.ClassDef):
                self.classes[node.name] = node
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        self.functions.setdefault(f"{node.name}.{sub.name}", sub)


# --------------------------------------------------------------------------- #
#  A2 — WRITES(a) from the transition function                                 #
# --------------------------------------------------------------------------- #
WRITE_SINKS = ("_with", "replace")


def _event_tag(stmts: list[ast.stmt]) -> str | None:
    """The literal kind tag an action appends to the event log."""
    for st in stmts:
        for node in ast.walk(st):
            if isinstance(node, ast.Tuple) and node.elts:
                inner = node.elts[0]
                if isinstance(inner, ast.Tuple) and inner.elts and \
                        isinstance(inner.elts[0], ast.Constant) and \
                        isinstance(inner.elts[0].value, str):
                    return inner.elts[0].value
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    return inner.value
    return None


def action_writes(env: Module) -> dict[str, set[str]]:
    """WRITES(a) per action kind: fields named as `_with`/`replace` keywords.

    OVER-approximating (A4): every field mentioned as a sink keyword on any path
    of the branch is included, even when the value is unchanged.
    """
    apply_fn = env.functions["apply"]
    out: dict[str, set[str]] = {}
    for st in apply_fn.body:
        if not isinstance(st, ast.If):
            continue
        kinds = _lit_kinds(st.test)
        if not kinds:
            continue
        flds: set[str] = set()
        for node in ast.walk(ast.Module(body=st.body, type_ignores=[])):
            if isinstance(node, ast.Call):
                fname = node.func.id if isinstance(node.func, ast.Name) else None
                if fname in WRITE_SINKS:
                    for kw in node.keywords:
                        f = canon(kw.arg or "")
                        if f:
                            flds.add(f)
        tag = _event_tag(st.body)
        if "events" in flds and tag:
            flds.discard("events")
            flds.add(f"events:{tag}")
        for k in kinds:
            out[k] = flds
    return out


# --------------------------------------------------------------------------- #
#  A3 — READS(h) and READS(g)                                                  #
# --------------------------------------------------------------------------- #
def _expand_events(fn: ast.FunctionDef, flds: set[str]) -> set[str]:
    """Decompose an `events` read by the constant tag it selects on (declared §3)."""
    if "events" not in flds:
        return flds
    tags = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Subscript):
            for cmp in node.comparators:
                if isinstance(cmp, ast.Constant) and isinstance(cmp.value, str):
                    tags.add(cmp.value)
    out = {f for f in flds if f != "events"}
    out |= {f"events:{t}" for t in tags} if tags else {"events:*"}
    return out


def harm_reads(env: Module, name: str, current_param: int = 1) -> set[str]:
    fn = env.functions[name]
    s = summarize(fn, env.functions)
    flds = {f for i, f in s.reads if i == current_param}
    return _expand_events(fn, flds)


def _pinned_attrs(mod: Module, cls: ast.ClassDef) -> set[str]:
    """Attributes assigned from s_0 in reset(): reads through them are PINNED."""
    out = {"s0"}
    for c in _mro(mod, cls):
        for sub in c.body:
            if isinstance(sub, ast.FunctionDef) and sub.name == "reset":
                for node in ast.walk(sub):
                    if isinstance(node, ast.Assign):
                        for t in node.targets:
                            if isinstance(t, ast.Attribute) and \
                                    isinstance(t.value, ast.Name) and t.value.id == "self":
                                src = ast.dump(node.value)
                                if "s0" in src:
                                    out.add(t.attr)
    return out


def _mro(mod: Module, cls: ast.ClassDef) -> list[ast.ClassDef]:
    chain = [cls]
    for b in cls.bases:
        if isinstance(b, ast.Name) and b.id in mod.classes:
            chain.extend(_mro(mod, mod.classes[b.id]))
    return chain


def guard_reads(gmod: Module, env: Module, gname: str, *,
                variant: str = "V1", kind: str | None = None) -> tuple[set[str], int]:
    cls = gmod.classes[gname]
    admits = None
    for c in _mro(gmod, cls):
        for sub in c.body:
            if isinstance(sub, ast.FunctionDef) and sub.name == "admits":
                admits = sub
                break
        if admits:
            break
    if admits is None:
        return set(), 0
    fnmap = dict(env.functions)
    fnmap.update(gmod.functions)
    for c in _mro(gmod, cls):                 # bind self-methods of this class
        for sub in c.body:
            if isinstance(sub, ast.FunctionDef):
                fnmap.setdefault(sub.name, sub)
    live = variant == "V2"
    s = summarize(admits, fnmap, live_only=live, kind=kind if live else None,
                  pinned_roots=_pinned_attrs(gmod, cls))
    params = [a.arg for a in admits.args.args]
    cur = params.index("s") if "s" in params else 1
    flds = {f for i, f in s.reads if i == cur}
    flds = _expand_events(admits, flds) if "events" in flds else flds
    return flds, s.unresolved


# --------------------------------------------------------------------------- #
#  A5 — the criterion                                                          #
# --------------------------------------------------------------------------- #
@dataclass
class Verdict:
    action: str
    guard: str
    harm: str
    blind: bool
    is_channel: bool                    # WRITES ∩ READS(h) != {}
    witness: list[str]                  # the fields the guard cannot see
    guard_sees: list[str]
    unresolved: int


def classify(writes: set[str], rh: set[str], rg: set[str],
             action: str, guard: str, harm: str, unresolved: int = 0) -> Verdict:
    hit_h = writes & rh
    hit_g = writes & rg
    return Verdict(action, guard, harm, bool(hit_h) and not hit_g, bool(hit_h),
                   sorted(hit_h), sorted(hit_g), unresolved)


def analyze(env_path: Path, guards_path: Path, guard_names: list[str],
            harms: dict[str, str], *, variant: str = "V1",
            conj: dict[str, list[str]] | None = None) -> list[Verdict]:
    env, gmod = Module(env_path), Module(guards_path)
    writes = action_writes(env)
    rh = {hname: harm_reads(env, fn) for hname, fn in harms.items()}
    out: list[Verdict] = []
    for a, w in sorted(writes.items()):
        for g in guard_names:
            parts = (conj or {}).get(g, [g])
            rg: set[str] = set()
            unres = 0
            for p in parts:
                r, u = guard_reads(gmod, env, p, variant=variant, kind=a)
                rg |= r
                unres += u
            for hname in harms:
                out.append(classify(w, rh[hname], rg, a, g, hname, unres))
    return out
