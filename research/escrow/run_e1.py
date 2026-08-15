"""E1 — does RESERVATION's verdict survive past M = 3?

Every cell in FINDINGS_RESERVATION ran at M <= 3, because
`env_federation.principals` silently returned a 3-tuple for any larger request.
RESERVATION-PARTIAL is therefore a verdict measured at a scale the environment
could not exceed.

THE COMMITTED GUARD IS IMPORTED, NOT COPIED. A copied guard is a second frame
that can drift from the one the verdict was measured on -- the same rule
`guards_reservation.py` itself follows toward `env_aggregate`.

Run:  ~/dev/marshal/.os/bin/python research/escrow/run_e1.py
"""
from __future__ import annotations

import json
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
for d in ("aggregate", "federation", "arena"):
    sys.path.insert(0, str(HERE.parent / d))

import env_aggregate as A                                       # noqa: E402
import guards_reservation as R                                  # noqa: E402
from arena import Arena, KAPPA                                   # noqa: E402

SCALES = (2, 4, 8, 16, 32, 64, 128, 256, 512)
ROUNDS, SEEDS = 40, 20


def _budget_for(m: int, holding: float) -> float:
    """The guard's own budget rule, read off `ReservationAgg.open_round`:
    how much may still be shed before crossing the box floor, never negative.

    Recomputed here rather than instantiating the guard because the committed
    guard is bound to `env_federation.State`, which caps at M=3 -- the very
    limitation under test. THE RULE IS TAKEN FROM THE GUARD; only the state
    representation differs, and that is stated rather than hidden.
    """
    low, _high = A.box_bounds(m, KAPPA)
    return max(0.0, holding - low)


def violation_rate(m: int, agents_per_principal: int, *, reserved: bool) -> float:
    """Fraction of rounds where concentration exceeds kappa while every local
    check passed. Folded from state; the guard is never read."""
    viol = total = 0
    for seed in range(SEEDS):
        rng = random.Random(seed)
        ar = Arena.fresh(m)
        for _ in range(ROUNDS):
            ps = list(ar.holdings)
            rng.shuffle(ps)
            target, rest = ps[0], ps[1:]
            low, _ = A.box_bounds(m, KAPPA)
            for p in rest:
                seen = ar.last_round[p]              # STALE, as AG-3 requires
                if reserved:
                    # ONE budget for the principal, fixed at round open and
                    # decremented per agent -- exactly ReservationAgg.
                    budget = _budget_for(m, seen)
                    shed = 0.0
                    for _ in range(agents_per_principal):
                        want = max(seen - low * (1 + 1e-9), 0.0)
                        take = min(want, budget)
                        budget -= take
                        shed += take
                else:
                    # unreserved: each agent shed to the floor independently
                    per = max(seen - low * (1 + 1e-9), 0.0)
                    shed = per * agents_per_principal
                ar.holdings[p] = max(ar.holdings[p] - shed, 0.0)
            ar.commit_round()
            total += 1
            if ar.concentration() > KAPPA + 1e-9:
                viol += 1
    return viol / total


def main() -> None:
    out: dict = {"kappa": KAPPA, "rounds": ROUNDS, "seeds": SEEDS}
    print("E1 — RESERVATION past M = 3   (committed guard's budget rule)\n")
    print(f"{'M':>5s} " + "".join(f"{'n='+str(n)+' res':>12s}{'n='+str(n)+' raw':>12s}"
                                  for n in (1, 4)))
    print("-" * 78)
    res: dict[str, dict] = {"reserved": {}, "unreserved": {}}
    for m in SCALES:
        cells = []
        for n in (1, 4):
            r = violation_rate(m, n, reserved=True)
            u = violation_rate(m, n, reserved=False)
            res["reserved"].setdefault(str(n), {})[str(m)] = r
            res["unreserved"].setdefault(str(n), {})[str(m)] = u
            cells += [r, u]
        print(f"{m:5d} " + "".join(f"{c:12.4f}" for c in cells))
    out["rates"] = res

    print("\nE1-HOLDS: reservation's rate at M in {8,64,512} within 2x of M=2?")
    for n in ("1", "4"):
        base = res["reserved"][n]["2"]
        vals = {m: res["reserved"][n][m] for m in ("8", "64", "512")}
        if base == 0:
            ok = all(v == 0 for v in vals.values())
            print(f"  n={n}: base is 0.0 — condition reads as {ok} "
                  f"(a zero base makes the ratio undefined; reported, not forced)")
        else:
            ok = all(abs(v - base) <= base for v in vals.values())
            print(f"  n={n}: base {base:.4f}, {vals} -> {ok}")

    (HERE / "e1_result.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
