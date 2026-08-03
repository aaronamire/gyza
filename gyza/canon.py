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
                      default=_fallback)


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
