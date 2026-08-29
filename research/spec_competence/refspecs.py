"""
Route 14 — HAND-WRITTEN REFERENCE SPECS (the measured ceiling, GATE 0c).

Written by hand for 18 of the 50 seeded MBPP problems, before any model
generation. Each is a STRUCTURAL/PROPERTY spec in the same form the models are
asked for: `spec(inp, out) -> bool`, where `inp` is the tuple of call arguments
and `out` is the produced output.

DISCIPLINE: none of these recomputes the reference output and compares. They are
deliberately the strongest spec a human can write WITHOUT solving the instance,
because that is the thing whose ceiling this route needs. If a reference spec
embedded an oracle, the measured ceiling would be the oracle's kill rate and
would not bound what a cheap property spec can achieve.

The ceiling is whatever these MEASURE, never a theoretical 1.0 (R13's lesson:
a ceiling computed analytically rather than under the mechanism's own dynamics
is not a ceiling).
"""
from __future__ import annotations

REFERENCE_SPECS: dict[int, str] = {

    0: '''def spec(inp, out):
    m, n = inp[0], inp[1]
    if not isinstance(out, list) or len(out) != m:
        return False
    if any((not isinstance(x, int)) or x % n != 0 for x in out):
        return False
    if out != sorted(out) or len(set(out)) != len(out):
        return False
    return out[0] == n
''',

    2: '''def spec(inp, out):
    src = inp[0]
    if not isinstance(out, list) or len(out) != len(src):
        return False
    for a, b in zip(src, out):
        if not isinstance(b, str):
            return False
        if any(ch.isdigit() for ch in b):
            return False
        if b != "".join(ch for ch in a if not ch.isdigit()):
            return False
    return True
''',

    6: '''def spec(inp, out):
    lst = inp[0]
    if not (isinstance(out, tuple) and len(out) == 2):
        return False
    n, sub = out
    if not isinstance(n, int) or sub not in lst:
        return False
    if len(sub) != n:
        return False
    return all(n <= len(x) for x in lst)
''',

    13: '''def spec(inp, out):
    src = inp[0]
    if not isinstance(out, list) or len(out) != len(src):
        return False
    if sorted(out) != sorted(src):
        return False
    return all(out[i] <= out[i + 1] for i in range(len(out) - 1))
''',

    15: '''def spec(inp, out):
    l1, l2 = inp[0], inp[1]
    if not isinstance(out, list):
        return False
    if any(x in l2 for x in out):
        return False
    if any(x not in l1 for x in out):
        return False
    kept = [x for x in l1 if x not in l2]
    return out == kept
''',

    17: '''def spec(inp, out):
    a, b, c = inp[0], inp[1], inp[2]
    if not isinstance(out, (int, float)) or isinstance(out, bool):
        return False
    if out <= 0:
        return False
    return out > max(a, b, c) and out < 3 * max(a, b, c) + 1
''',

    21: '''def spec(inp, out):
    lst, k = inp[0], inp[1]
    if not isinstance(out, list):
        return False
    if any(len(e) == k for e in out):
        return False
    if any(e not in lst for e in out):
        return False
    return len(out) == sum(1 for e in lst if len(e) != k)
''',

    23: '''def spec(inp, out):
    tup, k = inp[0], inp[1]
    if not isinstance(out, tuple):
        return False
    if len(out) != min(2 * k, len(tup)):
        return False
    if any(x not in tup for x in out):
        return False
    return list(out) == sorted(out)
''',

    24: '''def spec(inp, out):
    s = inp[0]
    if not isinstance(out, int) or isinstance(out, bool):
        return False
    return out == len(s)
''',

    28: '''def spec(inp, out):
    t1, t2 = inp[0], inp[1]
    if not isinstance(out, tuple) or len(out) != min(len(t1), len(t2)):
        return False
    for x, a, b in zip(out, t1, t2):
        if not isinstance(x, int) or isinstance(x, bool):
            return False
        if x + b != a:
            return False
    return True
''',

    33: '''def spec(inp, out):
    s = inp[0]
    if not isinstance(out, dict):
        return False
    if set(out.keys()) != set(s):
        return False
    if sum(out.values()) != len(s):
        return False
    return all(isinstance(v, int) and v > 0 for v in out.values())
''',

    38: '''def spec(inp, out):
    lst = inp[0]
    if not isinstance(out, list) or len(out) != len(lst):
        return False
    if sorted(map(repr, out)) != sorted(map(repr, lst)):
        return False
    if not lst:
        return True
    return out[0] == lst[-1] and out[1:] == lst[:-1]
''',

    42: '''def spec(inp, out):
    s = inp[0]
    if not isinstance(out, str):
        return False
    if len(out) != len(s) // 2:
        return False
    return out == s[1::2]
''',

    44: '''def spec(inp, out):
    l, b = inp[0], inp[1]
    if not isinstance(out, (int, float)) or isinstance(out, bool):
        return False
    if l > 0 and b > 0 and out <= 0:
        return False
    return out >= min(l, b) and out <= l * b + 0
''',

    46: '''def spec(inp, out):
    s = inp[0]
    if not isinstance(out, int) or isinstance(out, bool):
        return False
    return 0 <= out <= len(s)
''',

    48: '''def spec(inp, out):
    nums = inp[0]
    if not isinstance(out, list) or len(out) != max(0, len(nums) - 1):
        return False
    for i, x in enumerate(out):
        if x != nums[i] + nums[i + 1]:
            return False
    return True
''',

    49: '''def spec(inp, out):
    if not isinstance(out, bool):
        return False
    l1, l2 = inp[0], inp[1]
    common = set(l1) & set(l2)
    a = [e for e in l1 if e in common]
    b = [e for e in l2 if e in common]
    return out == (a == b)
''',

    3: '''def spec(inp, out):
    nums = inp[0]
    flat = [x for sub in nums for x in sub]
    try:
        items = dict(out)
    except Exception:
        return False
    if set(items.keys()) != set(flat):
        return False
    if sum(items.values()) != len(flat):
        return False
    return all(items[k] == flat.count(k) for k in items)
''',
}

# Problems with a hand-written reference spec (the ceiling sample, >= 15).
CEILING_SAMPLE = sorted(REFERENCE_SPECS.keys())


# --------------------------------------------------------------------------- #
#  PROPERTY-ONLY reference specs — the STRICT ceiling                          #
# --------------------------------------------------------------------------- #
# Several specs above (2, 15, 24, 28, 42, 48, 49, 3) recompute the reference
# output and compare. Those are ORACLE-EMBEDDING: valid and strong, but writing
# one required solving the problem, so their kill rate is NOT a bound on what a
# cheap property spec can achieve. This second set is strictly non-embedding —
# no expression that reconstructs `out` from `inp` — and gives the ceiling the
# claim-space argument actually needs. Both are reported.
REFERENCE_SPECS_PROP: dict[int, str] = {
    0: '''def spec(inp, out):
    m, n = inp[0], inp[1]
    if not isinstance(out, list) or len(out) != m:
        return False
    if any((not isinstance(x, int)) or x % n != 0 for x in out):
        return False
    return out == sorted(out) and len(set(out)) == len(out) and out[0] == n
''',
    2: '''def spec(inp, out):
    src = inp[0]
    if not isinstance(out, list) or len(out) != len(src):
        return False
    for a, b in zip(src, out):
        if not isinstance(b, str) or any(ch.isdigit() for ch in b):
            return False
        if len(b) > len(a) or not set(b) <= set(a):
            return False
    return True
''',
    6: '''def spec(inp, out):
    lst = inp[0]
    if not (isinstance(out, tuple) and len(out) == 2):
        return False
    n, sub = out
    if not isinstance(n, int) or sub not in lst or len(sub) != n:
        return False
    return all(n <= len(x) for x in lst)
''',
    13: '''def spec(inp, out):
    src = inp[0]
    if not isinstance(out, list) or len(out) != len(src):
        return False
    if sorted(out) != sorted(src):
        return False
    return all(out[i] <= out[i + 1] for i in range(len(out) - 1))
''',
    15: '''def spec(inp, out):
    l1, l2 = inp[0], inp[1]
    if not isinstance(out, list):
        return False
    if any(x in l2 for x in out) or any(x not in l1 for x in out):
        return False
    if len(out) > len(l1) or len(set(out)) != len(out):
        return False
    idx = [l1.index(x) for x in out]
    return idx == sorted(idx)
''',
    17: '''def spec(inp, out):
    a, b, c = inp[0], inp[1], inp[2]
    if not isinstance(out, (int, float)) or isinstance(out, bool):
        return False
    return out > max(a, b, c) and out < 3 * max(a, b, c) + 1
''',
    21: '''def spec(inp, out):
    lst, k = inp[0], inp[1]
    if not isinstance(out, list):
        return False
    if any(len(e) == k for e in out) or any(e not in lst for e in out):
        return False
    idx = [lst.index(e) for e in out]
    return idx == sorted(idx)
''',
    23: '''def spec(inp, out):
    tup, k = inp[0], inp[1]
    if not isinstance(out, tuple) or len(out) != min(2 * k, len(tup)):
        return False
    if any(x not in tup for x in out):
        return False
    return list(out) == sorted(out)
''',
    24: '''def spec(inp, out):
    s = inp[0]
    if not isinstance(out, int) or isinstance(out, bool):
        return False
    return 0 <= out and out <= len(s) and (out > 0 or len(s) == 0)
''',
    28: '''def spec(inp, out):
    t1, t2 = inp[0], inp[1]
    if not isinstance(out, tuple) or len(out) != min(len(t1), len(t2)):
        return False
    return all(isinstance(x, int) and not isinstance(x, bool) for x in out)
''',
    33: '''def spec(inp, out):
    s = inp[0]
    if not isinstance(out, dict):
        return False
    if set(out.keys()) != set(s) or sum(out.values()) != len(s):
        return False
    return all(isinstance(v, int) and v > 0 for v in out.values())
''',
    38: '''def spec(inp, out):
    lst = inp[0]
    if not isinstance(out, list) or len(out) != len(lst):
        return False
    if sorted(map(repr, out)) != sorted(map(repr, lst)):
        return False
    return (not lst) or out[0] == lst[-1]
''',
    42: '''def spec(inp, out):
    s = inp[0]
    if not isinstance(out, str) or len(out) != len(s) // 2:
        return False
    return set(out) <= set(s)
''',
    44: '''def spec(inp, out):
    l, b = inp[0], inp[1]
    if not isinstance(out, (int, float)) or isinstance(out, bool):
        return False
    return out >= min(l, b) and out <= l * b
''',
    46: '''def spec(inp, out):
    s = inp[0]
    if not isinstance(out, int) or isinstance(out, bool):
        return False
    return 0 <= out <= len(s)
''',
    48: '''def spec(inp, out):
    nums = inp[0]
    if not isinstance(out, list) or len(out) != max(0, len(nums) - 1):
        return False
    lo, hi = min(nums), max(nums)
    return all(2 * lo <= x <= 2 * hi for x in out)
''',
    49: '''def spec(inp, out):
    return isinstance(out, bool)
''',
    3: '''def spec(inp, out):
    nums = inp[0]
    flat = [x for sub in nums for x in sub]
    try:
        items = dict(out)
    except Exception:
        return False
    if set(items.keys()) != set(flat):
        return False
    return sum(items.values()) == len(flat)
''',
}
