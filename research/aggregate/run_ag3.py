"""AG-3 numerical verification. Deterministic, SEED = 1, zero model calls.

Round semantics are R13's, imported read-only and reproduced here for the
aggregate guards:
  SERIALIZED  -- each guard evaluates against the CURRENT state; admitted
                 actions applied immediately.
  CONCURRENT  -- every guard evaluates against the SAME pre-round state;
                 admitted actions applied in a fixed order; WORST CASE over
                 orders is reported.

Violations are a COUNT over (round, quantity) pairs. R10's per-round binary was
a stated limitation and is not repeated; it is retained separately for
comparability.
"""
from __future__ import annotations

import itertools
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "federation"))

import adversaries_federation as ADV           # noqa: E402  READ-ONLY
import env_aggregate as A                      # noqa: E402
import env_federation as E                     # noqa: E402  READ-ONLY
import guards_aggregate as G                   # noqa: E402

ROUNDS = ADV.ROUNDS
MAX_ORDERS_EXHAUSTIVE = ADV.MAX_ORDERS_EXHAUSTIVE
N_SAMPLED_ORDERS = ADV.N_SAMPLED_ORDERS
CONFIGS = ("F0", "LOCAL", "GLOBAL_READ", "PARTITIONED_READ")
MODES = ("serialized", "concurrent")


@dataclass
class Cell:
    config: str
    adversary: str
    m: int
    n: int
    mode: str
    admitted: int = 0
    blocked: int = 0
    proposals: int = 0
    rounds: int = ROUNDS
    # violation COUNTS over (round, quantity) pairs
    v_instantaneous: int = 0
    v_cumulative: int = 0
    v_path: int = 0
    # R10-comparable per-round binaries, kept separate
    rounds_any_violation: int = 0
    undefined_rounds: int = 0
    max_concentration: float | None = None
    final_cross_drain: float = 0.0
    final_peak: float | None = None
    guard_evals: int = 0
    per_round: list = field(default_factory=list)

    def as_dict(self):
        d = dict(self.__dict__)
        d.pop("per_round")
        d["throughput"] = self.admitted / self.rounds
        return d


def _orders(n, rng):
    idx = list(range(n))
    if n <= MAX_ORDERS_EXHAUSTIVE:
        return list(itertools.permutations(idx))
    return [tuple(rng.sample(idx, n)) for _ in range(N_SAMPLED_ORDERS)]


def _drain_budget(m: int) -> float:
    """Bound on total value permitted to leave the federation.

    Fixed as a fraction of the endowment, chosen in the preregistration's spirit:
    it must be reachable (so a 0 count is not definitional) and not violated at
    s_0. THETA is a per-principal fraction; the joint budget is THETA * initial
    federation total.
    """
    return A.THETA * (E.ACCT_HI + E.ACCT_LO + E.POOL_CONTRIB) * m


def run_cell(config, adversary, m, n, mode, rounds=ROUNDS) -> Cell:
    rng = random.Random(A.SEED)
    ps = E.principals(m)
    s0 = E.arena(m)
    guards = G.make_guards(config, ps)
    for g in guards.values():
        g.reset(s0)
    adv = ADV.ADVERSARIES[adversary]
    fed_guards = {p: __import__("guards_federation").F0(p, A.THETA) for p in ps}

    cell = Cell(config, adversary, m, n, mode, rounds=rounds)
    acc = A.CrossDrainAccumulator(s0, ps)
    peak = A.PeakConcentration(s0, ps)
    budget = _drain_budget(m)
    s = s0

    for r in range(rounds):
        props = []
        for p in ps:
            for _ in range(n):
                a = adv.propose(s, s0, p, ps, fed_guards[p], rng)
                if a is not None:
                    props.append(a)
                    cell.proposals += 1
        if props:
            if mode == "serialized":
                cur = s
                for a in props:
                    cell.guard_evals += 1
                    if E.physically_valid(cur, a) and guards[a.principal].admits(cur, a):
                        cur = E.apply(cur, a)
                        cell.admitted += 1
                    else:
                        cell.blocked += 1
                s = cur
            else:
                ok = []
                for a in props:
                    cell.guard_evals += 1
                    # every guard sees the SAME pre-round state
                    if E.physically_valid(s, a) and guards[a.principal].admits(s, a):
                        ok.append(a)
                    else:
                        cell.blocked += 1
                if ok:
                    worst = None
                    for order in _orders(len(ok), rng):
                        cur = s
                        for i in order:
                            a = ok[i]
                            if E.physically_valid(cur, a):
                                cur = E.apply(cur, a)
                        c = A.concentration(s0, cur, ps)
                        score = (c if c is not None else -1.0,
                                 -A.federation_total(s0, cur, ps))
                        if worst is None or score > worst[0]:
                            worst = (score, cur)
                    s = worst[1]
                    cell.admitted += len(ok)

        # ---- ENVIRONMENT-SIDE measurement (no guard state read) -------------
        c = A.concentration(s0, s, ps)
        acc.observe(s)
        peak.observe(s)
        viol = 0
        if c is None:
            cell.undefined_rounds += 1
        else:
            cell.max_concentration = c if cell.max_concentration is None \
                else max(cell.max_concentration, c)
            if c > A.KAPPA + 1e-9:
                cell.v_instantaneous += 1
                viol += 1
        if acc.total > budget + 1e-9:
            cell.v_cumulative += 1
            viol += 1
        if peak.peak is not None and peak.peak > A.KAPPA + 1e-9:
            cell.v_path += 1
            viol += 1
        cell.rounds_any_violation += 1 if viol else 0
        cell.per_round.append({"r": r, "conc": c, "drain": acc.total,
                               "peak": peak.peak})

    cell.final_cross_drain = acc.total
    cell.final_peak = peak.peak
    return cell


def main():
    cells = []
    for config in CONFIGS:
        for adversary in ADV.ADVERSARIES:
            for m in (2, 3):
                for n in (1, 2, 4):
                    for mode in MODES:
                        cells.append(run_cell(config, adversary, m, n, mode).as_dict())
    out = {
        "preregistration_sha256":
            "6a8644436ed7f26db2672e5d777aee2234f3daff93728aab230768ceb8bbe6e1",
        "kappa": A.KAPPA, "theta": A.THETA, "seed": A.SEED,
        "rounds": ROUNDS, "n_cells": len(cells),
        "box_bounds": {str(m): A.box_bounds(m) for m in (2, 3)},
        "box_sound": {str(m): A.box_is_sound(m) for m in (2, 3)},
        "cells": cells,
    }
    (HERE / "ag3_result.json").write_text(json.dumps(out, indent=1))
    print(f"{len(cells)} cells written")
    return out


if __name__ == "__main__":
    main()
