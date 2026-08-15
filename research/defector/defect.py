"""A2 — defection modes over R-M1's environment.

`env_margin.Fed` is IMPORTED, not copied. R-M1's findings were measured on it,
and a copy is a second frame free to drift from the one the verdict was measured
on -- the rule `guards_reservation.py` follows toward `env_aggregate`, and the
one the escrow route's coupled arena had to state explicitly.

A DEFECTOR IS A PRINCIPAL THAT IGNORES ITS OWN GUARD. Not one that forges a
credential, not one that adapts: the question is whether the aggregate bound
survives principals who simply do not run the check. That is the weakest and
most realistic form of non-compliance -- a node with old software, or none.
"""
from __future__ import annotations

import pathlib
import random
import sys
from fractions import Fraction as F

_MARGIN = pathlib.Path(__file__).resolve().parents[1] / "margin"
if str(_MARGIN) not in sys.path:
    sys.path.insert(0, str(_MARGIN))

from env_margin import (                                        # noqa: E402
    ACCT, CONTRIB, Fed, KAPPA, SCALE, U, box_floor,
)

SHED = "D-SHED"          # ignores the floor entirely
SKEW = "D-SKEW"          # respects L(0) but not L(delta*) -- version skew
HOARD = "D-HOARD"        # withdraws pool beyond its ceiling
BOTH = "D-BOTH"          # k shedders plus one hoarder
COMPLIANT = "COMPLIANT"

MODES = (SHED, SKEW, HOARD, BOTH)


def hoard(fed: Fed, i: int, amount: int) -> int:
    """Withdraw from the shared pool into `i`'s own holdings.

    SUM-CONSERVING, which is why §1b's ceiling is derivable: the withdrawer's
    total rises by `take*(1 - 1/m)` while every other principal's claim falls by
    `take/m`, and those cancel exactly. Returns what was actually taken.
    """
    take = max(0, min(amount, fed.pool))
    fed.pool -= take
    fed.holdings[i] += take
    return take


def run_trial(m: int, delta: F, eps: int, k_defectors: int, mode: str,
              seed: int, rounds: int = 40) -> dict:
    """One trajectory at R-M1's measured margin, with `k_defectors` ignoring it.

    Principal 0 is the held-out target, exactly as in R-M1. Defectors are drawn
    from the non-target principals, fixed for the whole trajectory (roles that
    rotate produce a defect this program already recorded).
    """
    rng = random.Random(seed)
    fed = Fed.fresh(m)
    L_margin = box_floor(m, delta)          # what a COMPLIANT principal obeys
    L_zero = box_floor(m, F(0))             # what a SKEWED principal obeys

    cum_div = [0] * m
    history: list[tuple[list[int], list[int]]] = [(fed.totals(), list(cum_div))]

    others = list(range(1, m))
    rng.shuffle(others)
    defectors = set(others[:k_defectors])
    # D-BOTH: the target itself hoards, on top of k shedders. The target is the
    # max holder, so hoarding there is the O(1) term acting where it can matter.
    hoarder = 0 if mode in (HOARD, BOTH) else None
    if mode == HOARD:
        defectors = set()                   # hoarding ALONE, the derivable control

    violations = undefined = 0
    for _ in range(rounds):
        v_tot, v_div = history[max(0, len(history) - 1 - eps)] if eps > 0 \
            else (None, None)

        if hoarder is not None:
            # take the whole remaining pool: the maximum this mode can do, which
            # is what §1b's ceiling is computed against
            hoard(fed, hoarder, fed.pool)

        for p in others:
            true = fed.total(p)
            seen = (v_tot[p] - (cum_div[p] - v_div[p])) if eps > 0 else true

            if p in defectors:
                floor = 0 if mode in (SHED, BOTH) else L_zero
            else:
                floor = L_margin

            want = seen - floor
            if want <= 0:
                continue
            if seen - want < floor:                  # the local check
                continue
            got = fed.reduce_total(p, want)
            cum_div[p] += got

        history.append((fed.totals(), list(cum_div)))
        v = fed.concentration_exceeds()
        if v is None:
            undefined += 1                           # GATE 0c: excluded
        elif v:
            violations += 1

    totals = fed.totals()
    comp = [totals[p] for p in others if p not in defectors]
    defs_ = [totals[p] for p in defectors]
    return {
        "violations": violations,
        "undefined_rounds": undefined,
        "scored_rounds": rounds - undefined,
        "peak": fed.concentration(),
        # THE COUNTER-METRIC: what defecting actually bought, in nano-units.
        # THE HOARDER COUNTS AS A DEFECTOR HERE. It is the target, so it is not
        # in `defectors`, and the first version left the advantage BLANK for
        # exactly the mode where the incentive question matters most -- an
        # unmeasured cell in the counter-metric is how "we didn't check" comes
        # to look like "there was nothing to see".
        "defector_advantage": (
            ((sum(defs_) + (totals[hoarder] if hoarder is not None else 0))
             / (len(defs_) + (1 if hoarder is not None else 0))
             - sum(comp) / len(comp))
            if (defs_ or hoarder is not None) and comp else None),
        "target_total": totals[0],
        # THE MECHANISM, measured rather than inferred. The defector's damage
        # does not run through its own term in max/sum -- it runs through the
        # SHARED POOL, whose depletion collapses every other principal's claim
        # while the target keeps its account balance. Reporting the pool makes
        # that visible instead of leaving it to be reasoned about.
        "pool_remaining": fed.pool,
        "withdrawn_by_defectors": sum(cum_div[p] for p in defectors),
        "withdrawn_by_compliant": sum(cum_div[p] for p in others
                                      if p not in defectors),
    }


def cell(m, delta, eps, k, mode, seeds=5, rounds=40) -> dict:
    viol = undef = 0
    advs = []
    tgt = pool = 0
    for s in range(seeds):
        r = run_trial(m, delta, eps, k, mode, s, rounds)
        viol += r["violations"]
        undef += r["undefined_rounds"]
        tgt = max(tgt, r["target_total"])
        pool = max(pool, r["pool_remaining"])
        if r["defector_advantage"] is not None:
            advs.append(r["defector_advantage"])
    return {
        "violations": viol,
        "undefined_rounds": undef,
        "breached": viol > 0,
        # 0/0 IS NOT 0: with k=0 there is no defector, so the advantage is
        # UNDEFINED rather than "no advantage".
        "defector_advantage": (sum(advs) / len(advs) / SCALE) if advs else None,
        "target_total": tgt / SCALE,
        "pool_remaining": pool / SCALE,
    }


def critical_k(m, delta, eps, mode, seeds=5, rounds=40) -> dict:
    """Smallest k with ANY violation. Scans upward: k* is the true minimum even
    if the response is non-monotone in k, which has never been checked."""
    curve = []
    for k in range(0, m):
        r = cell(m, delta, eps, k, mode, seeds, rounds)
        curve.append((k, r["violations"], r["defector_advantage"]))
        if r["breached"]:
            return {"k_star": k, "curve": curve,
                    "phi_star": k / (m - 1) if m > 1 else None,
                    "defector_advantage": r["defector_advantage"]}
    return {"k_star": None, "curve": curve, "phi_star": None,
            "defector_advantage": curve[-1][2] if curve else None}


__all__ = ["run_trial", "cell", "critical_k", "hoard", "MODES",
           "SHED", "SKEW", "HOARD", "BOTH", "KAPPA", "SCALE"]
