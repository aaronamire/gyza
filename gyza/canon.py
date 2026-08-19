"""
Canonical comparison — the mechanism that replaces a rule people forget.

WHY THIS MODULE EXISTS. Comparing two REPRESENTATIONS of a value instead of the
values themselves has produced three separate defects in this program
(`research/ARTIFACT_LEDGER.md` #7, #15, and #15's third recurrence in AR-2).
`{1: 2, 2: 3}` and `{2: 3, 1: 2}` are the same dict with different reprs;
`(1, 0.0)` and `(1.0, 0.0)` compare equal and print differently.

It did not recur because people forgot the rule. It recurred because a
**defective primitive was written once and reused**:
`research/correlated_failure/codebench.py:95,122` builds an answer "signature"
as `repr(eval(call))`, and `research/native_verifier/native_verifier.py:219`
compares those strings. Every route downstream inherited it.

A discipline item that must be remembered is not a fix. This is the fix: one
named call site, with a test that fails when a comparison bypasses it.

TWO OPERATIONS, AND THEY ARE NOT THE SAME ONE:

  values_equal(a, b)     ASK: are these the same value?  -> never serializes.
  canonical_form(value)  ASK: give me a stable key/hash  -> serializes, but
                         order-normalized so equal values give equal strings.

The bug in every case was using the second where the first was meant.
"""
from __future__ import annotations

import json
import math
from typing import Any


def values_equal(a: Any, b: Any) -> bool:
    """Semantic equality. **Never** compares serialized forms.

    Python's ``==`` is already value equality — `1 == 1.0` is True and dict
    order is irrelevant. The point of naming it is that the call site becomes
    greppable and testable, so `repr(a) == repr(b)` can be mechanically banned.

    NaN is handled explicitly: `float('nan') != float('nan')` under ``==``, but
    two computations that both produced NaN produced the same value, and a
    correctness check that says otherwise is wrong about its own subject.
    """
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
    try:
        return bool(a == b)
    except Exception:                       # noqa: BLE001
        # Uncomparable types are NOT equal, and are not an error either: the
        # question "are these the same value" has an answer even when the
        # objects refuse to be compared.
        return False


def sequences_equal(a, b) -> bool:
    """Element-wise `values_equal` over two sequences."""
    a, b = list(a), list(b)
    if len(a) != len(b):
        return False
    return all(values_equal(x, y) for x, y in zip(a, b))


def canonical_form(value: Any) -> str:
    """An ORDER-STABLE serialization, for hashing, dict keys and storage.

    Safe to compare **only** because it normalizes: dict keys are sorted, and
    an int-valued float is emitted as its integer so `1` and `1.0` agree. Where
    a value is not JSON-representable it falls back to a sorted structural
    rendering rather than `repr`, which is not order-stable for sets.

    If you are reaching for this to answer "are these equal", you want
    `values_equal` instead.
    """
    return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"),
                      default=_fallback, allow_nan=False)


def _normalize(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)                       # 1.0 and 1 must agree
    if isinstance(v, dict):
        return {str(k): _normalize(x) for k, x in v.items()}
    if isinstance(v, (set, frozenset)):
        return {"__set__": sorted(canonical_form(x) for x in v)}
    if isinstance(v, (list, tuple)):
        return [_normalize(x) for x in v]
    return v


def _fallback(v: Any) -> str:
    return f"__obj__:{type(v).__name__}"


__all__ = ["values_equal", "sequences_equal", "canonical_form"]


# --------------------------------------------------------------------------- #
#  THE SECOND MECHANISM: a failure is not an empty value                       #
# --------------------------------------------------------------------------- #
#
# WHY THIS EXISTS, and why it lives beside the comparison helpers. Both halves
# of this module fix the SAME underlying error -- reading something that is not
# a measurement as if it were one:
#
#     a REPRESENTATION read as a value   -> artifacts #7, #15, AR-2
#     an ERROR read as a value           -> artifact #16, and the corpus
#                                           extractor one session later
#
# The fourth recurrence was `gh(...) or []` in `research/corpus/run_partB.py`:
# `gh` returned None on a transport failure, `or []` turned it into an empty
# commit list, and the record was silently scored "this PR has fewer than 3
# commits". A failed API call and a small pull request became the same
# observation, and the drop counter that was supposed to make the corpus
# auditable counted them together.
#
# A rule that has recurred four times is not a discipline problem. It is a
# missing mechanism. The mechanism is this: make the failure value REFUSE to be
# treated as data. `Failure` raises on every operation that would silently
# absorb it -- truthiness, iteration, length, indexing -- so the exact idiom
# that caused the defect (`call() or []`) now raises instead of lying.


class CallFailed(Exception):
    """A `Failure` was used where a value was expected."""


class Failure:
    """The call did not produce a value.

    This is **not** None, **not** empty, and deliberately **not falsy** -- it is
    hostile to every operation that would let it pass as data:

        >>> f = Failure("HTTP 502")
        >>> f or []                     # the idiom that caused the defect
        Traceback (most recent call last):
        CallFailed: ...
        >>> len(f)                      # ... and its neighbours
        Traceback (most recent call last):
        CallFailed: ...

    To proceed anyway you must say so, in a form that greps:

        >>> unwrap_or(f, [])
        []
    """

    __slots__ = ("reason", "where")

    def __init__(self, reason: str, where: str = ""):
        self.reason = str(reason)
        self.where = where

    def _refuse(self, op: str):
        raise CallFailed(
            f"a failed call is being used as a value ({op}). "
            f"reason={self.reason!r} where={self.where!r}. "
            f"Handle the failure, or opt in explicitly with "
            f"gyza.canon.unwrap_or(x, default).")

    def __bool__(self):        self._refuse("truth test / `or` default")
    def __iter__(self):        self._refuse("iteration")
    def __len__(self):         self._refuse("len()")
    def __getitem__(self, k):  self._refuse("indexing")
    def __contains__(self, k): self._refuse("`in`")

    def __repr__(self) -> str:
        return f"Failure(reason={self.reason!r}, where={self.where!r})"


def failed(x: Any) -> bool:
    """True if `x` is a Failure. The only safe way to test one."""
    return isinstance(x, Failure)


def attempt(fn, *args, where: str = "", catching: type[BaseException] | tuple = Exception,
            **kwargs):
    """Run `fn`, returning its value or a `Failure` -- never a stand-in.

    The point is that the caller cannot accidentally continue: the returned
    Failure raises the moment it is used as data.
    """
    try:
        return fn(*args, **kwargs)
    except catching as e:                                     # noqa: BLE001
        return Failure(f"{type(e).__name__}: {e}", where or getattr(fn, "__name__", ""))


def unwrap_or(x: Any, default: Any) -> Any:
    """Explicitly substitute `default` for a failure.

    This is the ONLY sanctioned way to default past a failure. It exists so the
    decision is greppable: `unwrap_or` at a call site is a recorded choice,
    whereas `or []` was an invisible one.
    """
    return default if failed(x) else x
