"""
Route 14 Part B — does the containment invariant taxonomy transfer to SPECS?

R13 established that a stateless local check cannot bound a cumulative quantity:
the guard's own state is the conflict set. Part B asks whether the SAME taxonomy
governs specification composition.

12 hand-written 3-stage pipelines (f3 . f2 . f1) over lists of ints. Per stage,
three spec classes:

  CONSERVATION            a quantity is preserved (length / multiset / sum).
  MONOTONE NON-CUMULATIVE a property that, once established, no later stage can
                          destroy (sortedness under a monotone map; type/shape).
  CUMULATIVE              a budget over the WHOLE pipeline (total elements added
                          across stages).

The question is whether the CONJUNCTION of per-stage specs implies the intended
END-TO-END property.

Deterministic. SEED = 1. Zero model calls (B4 adds model-written specs).
"""
from __future__ import annotations

SEED = 1

# Per-stage element-addition allowance used by the CUMULATIVE class. The
# end-to-end budget is deliberately TIGHTER than 3x the per-stage allowance —
# that gap is exactly where a stateless local spec has nothing to say.
PER_STAGE_ADD_MAX = 2
END_TO_END_BUDGET = 4


def _tail(ys, k):
    """Appended elements sit ABOVE the current maximum.

    An earlier construction appended `range(k)`, which placed small values after
    a sort and meant the unmutated pipeline violated its OWN monotone spec — the
    spec and the pipeline were mutually inconsistent. Caught by the base-case
    assertion in run_partb.py before any Part B result existed; fixed here so
    that sortedness, once established, is genuinely preserved by later stages.
    """
    if k <= 0:
        return []
    m = max(ys) if ys else 0
    return [m + 1 + j for j in range(k)]


def _mk(mul, addk, sort_at):
    """Build one 3-stage pipeline. `addk[i]` elements are appended by stage i."""
    def f1(xs):
        ys = [x * mul for x in xs]
        return ys + _tail(ys, addk[0])

    def f2(xs):
        ys = sorted(xs) if sort_at == 2 else [x + 1 for x in xs]
        return ys + _tail(ys, addk[1])

    def f3(xs):
        ys = [x + 1 for x in xs] if sort_at == 2 else sorted(xs)
        return ys + _tail(ys, addk[2])

    return [f1, f2, f3]


# 12 pipelines: multiplier x addition-profile x where the sort happens.
PIPELINES: list[dict] = []
for _mul in (1, 2, 3):
    for _add in ([1, 1, 1], [2, 1, 1], [1, 2, 1], [0, 2, 2]):
        _sort = 2 if (_mul + sum(_add)) % 2 == 0 else 3
        PIPELINES.append({
            "name": f"pl_mul{_mul}_add{''.join(map(str, _add))}_sort{_sort}",
            "mul": _mul, "addk": list(_add), "sort_at": _sort,
            "stages": _mk(_mul, _add, _sort),
        })
assert len(PIPELINES) == 12

INPUT = [5, 3, 9, 1, 7]


# --------------------------------------------------------------------------- #
#  Per-stage specs, by class. Each takes (stage_index, x_in, x_out) -> bool.   #
# --------------------------------------------------------------------------- #
def spec_conservation(pl, i, xin, xout) -> bool:
    """Length is preserved up to this stage's declared additions."""
    return len(xout) == len(xin) + pl["addk"][i]


def spec_monotone(pl, i, xin, xout) -> bool:
    """Sortedness, once established, is preserved; and shape/type always hold.

    The sorting stage must ESTABLISH it; every later stage must PRESERVE it.
    """
    if not all(isinstance(v, int) for v in xout):
        return False
    stage_no = i + 1
    if stage_no < pl["sort_at"]:
        return True
    return all(xout[j] <= xout[j + 1] for j in range(len(xout) - 1))


def spec_cumulative(pl, i, xin, xout) -> bool:
    """The per-stage share of a global budget — the ONLY thing a local, stateless
    spec can express about a cumulative quantity."""
    return (len(xout) - len(xin)) <= PER_STAGE_ADD_MAX


SPEC_CLASSES = {"conservation": spec_conservation,
                "monotone": spec_monotone,
                "cumulative": spec_cumulative}


# --------------------------------------------------------------------------- #
#  End-to-end properties (what the per-stage conjunction is supposed to imply) #
# --------------------------------------------------------------------------- #
def e2e_conservation(pl, xin, xout) -> bool:
    return len(xout) == len(xin) + sum(pl["addk"])


def e2e_monotone(pl, xin, xout) -> bool:
    return all(xout[j] <= xout[j + 1] for j in range(len(xout) - 1))


def e2e_cumulative(pl, xin, xout) -> bool:
    """THE GLOBAL BUDGET. No per-stage spec can see this quantity."""
    return (len(xout) - len(xin)) <= END_TO_END_BUDGET


E2E = {"conservation": e2e_conservation,
       "monotone": e2e_monotone,
       "cumulative": e2e_cumulative}


# --------------------------------------------------------------------------- #
#  Stage mutations                                                             #
# --------------------------------------------------------------------------- #
def mutate_stage(pl, idx, kind):
    """Return a copy of the stage list with stage `idx` mutated."""
    stages = list(pl["stages"])
    orig = stages[idx]

    if kind == "drop":                      # loses an element
        def m(xs, _o=orig):
            r = _o(xs)
            return r[:-1] if r else r
    elif kind == "unsort":                  # destroys ordering
        def m(xs, _o=orig):
            r = _o(xs)
            return list(reversed(r)) if len(r) > 1 else r
    elif kind == "overadd":                 # adds MORE, still within per-stage max
        def m(xs, _o=orig, _i=idx):
            r = _o(xs)
            room = PER_STAGE_ADD_MAX - pl["addk"][_i]
            return r + _tail(r, max(0, room))
    else:
        raise ValueError(kind)

    stages[idx] = m
    return stages


def run(stages, xin):
    x = xin
    trace = []
    for f in stages:
        y = f(x)
        trace.append((x, y))
        x = y
    return x, trace


def per_stage_conjunction(pl, cls, trace) -> bool:
    """Does EVERY per-stage spec of this class accept?"""
    fn = SPEC_CLASSES[cls]
    return all(fn(pl, i, xin, xout) for i, (xin, xout) in enumerate(trace))
