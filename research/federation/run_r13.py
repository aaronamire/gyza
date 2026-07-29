"""
Route 13 measurement driver. Produces r13_result.json.

Cells: M in {2,3} x N in {1,2,4} x {serialized, concurrent} x {F0,F1,F2,F3}
       x {A1-salami, A2-ratchet, A3-cross, A4-pool, mixed}

Deterministic, SEED = 1, zero model calls.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import adversaries_federation as A            # noqa: E402
import env_federation as E                    # noqa: E402
from env_federation import Action, apply      # noqa: E402

CONFIGS = ("F0", "F1", "F2", "F3")
ADVERSARIES = ("A1-salami", "A2-ratchet", "A3-cross", "A4-pool", "mixed")
MS = (2, 3)
NS = (1, 2, 4)
MODES = ("serialized", "concurrent")


def blind_goal_agreement() -> dict:
    """GATE 0c — agreement between the DEFINITION and the optimization,
    reported as a first-class number, never assumed."""
    out = {"probes": 0, "agree": 0, "disagreements": []}
    for m in MS:
        s0 = E.arena(m)
        probes = [
            [],
            [Action("transfer", principal="A", src="A:a0", dst="A:a1", amt=2)],
            [Action("delete", principal="A", obj="A:o4")],
            [Action("delete", principal="A", obj="A:o0")],
            [Action("delete", principal="A", obj="A:o1"),
             Action("delete", principal="A", obj="A:o2")],
            [Action("reassign", principal="A", account="A:a1",
                    new_owner=E.EXTERNAL)],
            [Action("withdraw_pool", principal="A", dst="A:a0", amt=4)],
        ]
        for seq in probes:
            s = s0
            for a in seq:
                s = apply(s, a)
            b = E.reachable_blind_p(s0, s, "A", max_depth=6, node_cap=1500)
            g = E.reachable_goal_p(s0, s, "A")
            out["probes"] += 1
            if b == g:
                out["agree"] += 1
            else:
                out["disagreements"].append({"m": m, "seq": [repr(x) for x in seq],
                                             "blind": b, "goal": g})
    out["rate"] = out["agree"] / out["probes"] if out["probes"] else None
    return out


def main() -> None:
    t0 = time.time()
    cells = []
    for m in MS:
        for n in NS:
            for mode in MODES:
                for cfg in CONFIGS:
                    for adv in ADVERSARIES:
                        r = A.run_cell(cfg, adv, m, n, mode)
                        cells.append({
                            "m": m, "n_agents": n, "mode": mode,
                            "config": cfg, "adversary": adv,
                            "rounds": r.rounds,
                            "proposals": r.proposals,
                            "admitted": r.admitted,
                            "blocked_total": r.blocked_total,
                            "blocked_awaiting_auth": r.blocked_awaiting_auth,
                            "dropped": r.dropped,
                            "invalid_excluded": r.invalid_excluded,
                            "guard_evals": r.guard_evals,
                            "throughput": r.throughput,
                            "check_cost": (r.guard_evals / r.admitted
                                           if r.admitted else None),
                            "max_h_drain": {k: round(v, 6)
                                            for k, v in r.max_h_drain.items()},
                            "max_h_lost": {k: round(v, 6)
                                           for k, v in r.max_h_lost.items()},
                            "recoverable": r.recoverable,
                            "cross_violations": r.cross_violations,
                            "cross_violation_rounds": r.cross_violation_rounds,
                            "max_overdraft": r.max_overdraft,
                            "final_overdraft": r.final_overdraft,
                        })

    inv = {str(m): E.inventory(E.arena(m)) for m in MS}
    result = {
        "seed": E.SEED,
        "theta": E.THETA,
        "auth_cap": E.AUTH_CAP,
        "rounds": A.ROUNDS,
        "workload_mix": {"frac_cross": A.FRAC_CROSS,
                         "frac_legit_of_cross": A.FRAC_LEGIT_OF_CROSS},
        "inventory": inv,
        "blind_goal_agreement": blind_goal_agreement(),
        "violation_metric": ("COUNT over (round, victim principal) pairs; "
                             "cross_violation_rounds is the R10-comparable "
                             "per-round BINARY indicator"),
        "cells": cells,
        "elapsed_s": round(time.time() - t0, 2),
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "r13_result.json")
    with open(path, "w") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    print(f"wrote {path}  ({len(cells)} cells, {result['elapsed_s']}s)")


if __name__ == "__main__":
    main()
