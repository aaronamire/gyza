"""The two preregistered experiments, sequenced: calibration, then the claim.

Run:  ~/dev/marshal/.os/bin/python research/arena/run_arena.py
"""
from __future__ import annotations

import json
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "aggregate"))

import env_aggregate as A                                       # noqa: E402
from arena import Arena, KAPPA, run_round                       # noqa: E402

SCALES = (2, 4, 8, 16, 32, 64, 128, 256, 512)
ROUNDS = 40
TRIALS = 25


# --------------------------------------------------------------------------- #
#  PART 1 — CALIBRATION: does stale-read unsoundness decay with M?             #
# --------------------------------------------------------------------------- #
def part1_violation_rate(m: int, *, shed=0.9, colluding_frac=1.0, seed=0):
    """Every principal sheds as hard as its LOCAL box allows, concurrently.

    A violation is a round where concentration exceeds kappa while every local
    check passed -- the AG-3 shape. Computed by folding state; the guard is
    never read.
    """
    rng = random.Random(seed)
    violated = rounds = 0
    for t in range(TRIALS):
        ar = Arena.fresh(m)
        k = max(1, int(m * colluding_frac))
        for _ in range(ROUNDS):
            run_round(ar, rng, shed_fraction=shed, colluding=k)
            rounds += 1
            if ar.concentration() > KAPPA + 1e-9:
                violated += 1
    return violated / rounds


def part1_required_shed(m: int) -> float:
    """§4b's analytic prediction: the shed needed to leave the box."""
    low, high = A.box_bounds(m, KAPPA)
    return (high - low) / high


# --------------------------------------------------------------------------- #
#  PART 2 — DOES REVIEW CAPACITY FEDERATE?                                     #
# --------------------------------------------------------------------------- #
def part2_actions_per_review(m: int, *, shared_pool: bool, budget_per=50,
                             rounds=200, seed=1):
    """Actions admitted per escalation.

    PER-PRINCIPAL: each principal has its own budget and its own reviewer, so an
    exhausted budget escalates only that principal.
    SHARED POOL: one global budget for the whole federation -- the C7 shape, a
    cumulative bound over a single pool.
    """
    rng = random.Random(seed)
    ps = [f"P{i:05d}" for i in range(m)]
    actions = reviews = 0
    if shared_pool:
        pool = budget_per * m            # same TOTAL budget, one pool
        for _ in range(rounds):
            for _p in ps:
                if pool <= 0:
                    reviews += 1          # one human decision refills the pool
                    pool = budget_per * m
                pool -= 1
                actions += 1
    else:
        left = {p: budget_per for p in ps}
        for _ in range(rounds):
            for p in ps:
                if left[p] <= 0:
                    reviews += 1          # this principal's OWN reviewer
                    left[p] = budget_per
                left[p] -= 1
                actions += 1
    return actions / max(reviews, 1)


def main() -> None:
    out: dict = {"kappa": KAPPA, "rounds": ROUNDS, "trials": TRIALS}

    print("PART 1 — CALIBRATION: stale-read unsoundness vs M\n")
    print(f"{'M':>5s} {'required shed':>14s} {'violation rate':>15s}")
    print("-" * 38)
    p1 = {}
    for m in SCALES:
        v = part1_violation_rate(m)
        p1[m] = v
        print(f"{m:5d} {part1_required_shed(m):13.1%} {v:15.4f}")
    out["part1_violation_rate"] = p1

    r1 = p1[512] < p1[2] / 2 if p1[2] > 0 else None
    print(f"\n  R-1 (rate at M=512 < half of M=2): {r1}")
    print(f"  P2 (rate at M=2 > 0): {p1[2] > 0}")
    mono = all(p1[a] >= p1[b] - 1e-12 for a, b in zip(SCALES, SCALES[1:]))
    print(f"  P1 (monotone decreasing in M): {mono}")

    print("\n\nPART 2 — DOES REVIEW CAPACITY FEDERATE?\n")
    print(f"{'M':>5s} {'per-principal':>16s} {'shared pool':>14s}")
    print("-" * 38)
    pp, sp = {}, {}
    for m in SCALES:
        a = part2_actions_per_review(m, shared_pool=False)
        b = part2_actions_per_review(m, shared_pool=True)
        pp[m], sp[m] = a, b
        print(f"{m:5d} {a:16.2f} {b:14.2f}")
    out["part2_per_principal"] = pp
    out["part2_shared_pool"] = sp

    spread = max(pp.values()) / min(pp.values())
    fall = sp[2] / sp[512] if sp[512] else float("inf")
    print(f"\n  R-2a (per-principal varies < 2x): {spread < 2.0}  (spread {spread:.3f}x)")
    print(f"  R-2b (shared pool falls >= 10x):  {fall >= 10.0}  (fall {fall:.1f}x)")

    (HERE / "results.json").write_text(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
