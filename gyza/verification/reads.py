"""What state does a verifier read that its claim does not name?

THE NARROWER QUESTION, AND WHY IT IS WORTH ASKING. Whether an arbitrary
callable RECOMPUTES rather than SAMPLES is a semantic property and is not
decidable — R12 established the shape: closing that gap requires deciding the
question the check was meant to replace. But the carrier rule turns on
something narrower:

    A VERIFIER OF AN UNDERDETERMINED CLAIM CAN ONLY SAMPLE.

If the claim does not name a parameter that moves the verdict, the verifier
supplies a value, and supplying one is choosing a point in a space the claim
left open. "Does this verifier read state the claim does not name" is closer to
a reachability question than a semantic one, and reachability admits a sound
one-sided answer.

WHAT THIS MODULE DECIDES, AND WHAT IT DOES NOT. It reads a function's code
object — free variables, global lookups, dynamic-access opcodes — and partitions
what it touches into CODE (functions, classes, modules: calling a pure function
is not reading ambient state) and DATA (a module-level constant, a mutable
global, a closed-over value: these parameterise the verdict without appearing in
the claim).

THE APPROXIMATION DIRECTION, WHICH IS THE LOAD-BEARING DISCLOSURE:

    unresolvable  ->  treated as UNNAMED DATA  ->  flagged as sampling.

That is the CONSERVATIVE direction. Over-approximating what a verifier reads
makes it look MORE sampling-like and refuses too much — noisy but safe.
Under-approximating would admit a mislabelled PROOF, which SR-3 measured
composing at 0.000 and which stays invisible until depth. Every default taken
is COUNTED and reported (`n_conservative_defaults`), because an approximation
whose firing rate is unknown is not a characterised approximation.

KNOWN LIMITS, enumerated rather than implied:
  * `getattr` / `globals()` / `eval` / `vars` / `__import__` are unresolvable by
    construction -> conservative.
  * Indirection through a dict or a registry is unresolvable -> conservative.
  * Attribute reads on objects PASSED IN are NOT ambient: the object is named by
    the claim, and what it exposes is part of it. `market.capital_entries()` is
    a read of a named parameter, not of unnamed state.
  * Recursion into called functions is bounded by `depth`. Beyond it, reads are
    invisible, and THAT is the one place the analysis is under-approximating —
    disclosed by `truncated_at_depth`, which names every call not followed.
"""
from __future__ import annotations

import builtins
import dis
import inspect
import types
from dataclasses import dataclass, field
from typing import Any, Callable

# Opcodes / names that defeat static resolution. Their presence is conclusive
# evidence that the read set cannot be enumerated, never evidence of its size.
_DYNAMIC_NAMES = frozenset({"getattr", "globals", "locals", "vars", "eval",
                            "exec", "__import__", "setattr", "importlib"})


@dataclass(frozen=True)
class ReadSet:
    """Everything a verifier touches, partitioned. Conservative on failure."""
    fn_name: str
    named_params: frozenset[str]
    closure_data: frozenset[str] = field(default_factory=frozenset)
    global_data: frozenset[str] = field(default_factory=frozenset)
    global_code: frozenset[str] = field(default_factory=frozenset)
    dynamic: frozenset[str] = field(default_factory=frozenset)
    unresolved: frozenset[str] = field(default_factory=frozenset)
    truncated_at_depth: frozenset[str] = field(default_factory=frozenset)
    n_conservative_defaults: int = 0

    @property
    def unnamed_state(self) -> frozenset[str]:
        """State that moves the verdict and is absent from the claim.

        `unresolved` and `dynamic` are INCLUDED. That is the conservative
        default: a read we could not classify is counted against the verifier.
        """
        return self.closure_data | self.global_data | self.dynamic | self.unresolved

    @property
    def reads_unnamed_state(self) -> bool:
        return bool(self.unnamed_state)


def _is_code_like(v: Any) -> bool:
    """Is this a thing you CALL, or a thing you READ?

    Calling a module-level pure function is not reading ambient state — the
    function is code, and code is the same on every call. A module-level
    CONSTANT is different: it parameterises the verdict and the claim does not
    name it. This distinction is the whole analysis, and getting it backwards
    would flag every verifier that imports anything.
    """
    return isinstance(v, (types.FunctionType, types.BuiltinFunctionType,
                          types.ModuleType, type, types.MethodType)) or callable(v)


def analyze(fn: Callable[..., Any], *, depth: int = 1,
            _seen: frozenset[int] | None = None) -> ReadSet:
    """Partition what `fn` reads. Sound in the conservative direction only."""
    seen = _seen or frozenset()
    name = getattr(fn, "__name__", repr(fn))
    try:
        code = fn.__code__                                  # type: ignore[attr-defined]
        glb = fn.__globals__                                # type: ignore[attr-defined]
    except AttributeError:
        # A callable with no inspectable code object: a C builtin, a partial, a
        # class with __call__. Cannot be read at all -> conservative.
        return ReadSet(name, frozenset(), unresolved=frozenset({"<no code object>"}),
                       n_conservative_defaults=1)

    try:
        params = frozenset(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        params = frozenset()

    closure_data: set[str] = set()
    global_data: set[str] = set()
    global_code: set[str] = set()
    dynamic: set[str] = set()
    unresolved: set[str] = set()
    truncated: set[str] = set()
    defaults = 0

    # --- closed-over variables: the shape the rule was derived from ---------
    cells = getattr(fn, "__closure__", None) or ()
    for i, var in enumerate(code.co_freevars):
        try:
            val = cells[i].cell_contents
        except (IndexError, ValueError):
            closure_data.add(var); defaults += 1
            continue
        if _is_code_like(val):
            global_code.add(var)
        else:
            # A closed-over VALUE parameterises the verdict and the claim does
            # not name it. Two closures give two verdicts.
            closure_data.add(var)

    # --- global / attribute name lookups ------------------------------------
    # FUNCTION-LOCAL IMPORTS DEFEAT A LOAD_GLOBAL-ONLY SCAN, and this codebase
    # uses them everywhere: every adapter in `gyza/verification/adapters.py`
    # does `from gyza.icp import verify_envelope` INSIDE the body, which binds
    # a LOCAL. A scan that only followed globals therefore saw the adapter
    # shell and none of the verifier — an UNDER-approximation, i.e. the
    # dangerous direction. It was caught by noticing that every entry reported
    # zero conservative defaults, which no real analysis would.
    imported: dict[str, Any] = {}
    instrs = list(dis.get_instructions(code))
    for i, ins in enumerate(instrs):
        if ins.opname != "IMPORT_NAME":
            continue
        mod_name = ins.argval
        for nxt in instrs[i + 1:]:
            if nxt.opname == "IMPORT_FROM":
                try:
                    import importlib
                    mod = importlib.import_module(mod_name)
                    imported[nxt.argval] = getattr(mod, nxt.argval)
                except (ImportError, AttributeError):
                    unresolved.add(f"{mod_name}.{nxt.argval}"); defaults += 1
            elif nxt.opname in ("STORE_FAST", "STORE_NAME", "STORE_GLOBAL",
                                "IMPORT_NAME"):
                if nxt.opname == "IMPORT_NAME":
                    break
            elif nxt.opname not in ("STORE_FAST", "STORE_NAME", "STORE_GLOBAL"):
                break

    loaded_globals = {ins.argval for ins in instrs
                      if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME")}
    for n in loaded_globals:
        if n in _DYNAMIC_NAMES:
            dynamic.add(n); defaults += 1
            continue
        if n in glb:
            (global_code if _is_code_like(glb[n]) else global_data).add(n)
        elif hasattr(builtins, n):
            global_code.add(n)                    # len, sum, all, isinstance…
        else:
            # Not resolvable at analysis time — an import performed inside the
            # body, or a name bound later. CONSERVATIVE: count it against.
            unresolved.add(n); defaults += 1

    # Function-locally imported callables are delegates and must be followed.
    for n, v in imported.items():
        (global_code if _is_code_like(v) else global_data).add(n)

    # --- bounded recursion into callables this function delegates to --------
    if depth > 0:
        for n in sorted(global_code):
            target = imported.get(n, glb.get(n))
            if not isinstance(target, types.FunctionType):
                continue
            if id(target) in seen:
                continue
            sub = analyze(target, depth=depth - 1, _seen=seen | {id(fn)})
            # A callee's PARAMETERS are supplied by this caller, so they are not
            # ambient; only its own unnamed reads propagate.
            closure_data |= {f"{n}.{x}" for x in sub.closure_data}
            global_data |= {f"{n}.{x}" for x in sub.global_data}
            dynamic |= {f"{n}.{x}" for x in sub.dynamic}
            unresolved |= {f"{n}.{x}" for x in sub.unresolved}
            truncated |= {f"{n}.{x}" for x in sub.truncated_at_depth}
            defaults += sub.n_conservative_defaults
    else:
        truncated |= {n for n in global_code
                      if isinstance(imported.get(n, glb.get(n)),
                                    types.FunctionType)}

    return ReadSet(name, params, frozenset(closure_data), frozenset(global_data),
                   frozenset(global_code), frozenset(dynamic),
                   frozenset(unresolved), frozenset(truncated), defaults)


def unnamed_state_report(fn: Callable[..., Any], *, depth: int = 1) -> dict[str, Any]:
    """`analyze` flattened for reporting and for the retrodiction table."""
    r = analyze(fn, depth=depth)
    return {
        "fn": r.fn_name,
        "named_params": sorted(r.named_params),
        "unnamed_state": sorted(r.unnamed_state),
        "closure_data": sorted(r.closure_data),
        "global_data": sorted(r.global_data),
        "dynamic": sorted(r.dynamic),
        "unresolved": sorted(r.unresolved),
        "truncated_at_depth": sorted(r.truncated_at_depth),
        "n_conservative_defaults": r.n_conservative_defaults,
        "reads_unnamed_state": r.reads_unnamed_state,
    }


__all__ = ["ReadSet", "analyze", "unnamed_state_report"]
