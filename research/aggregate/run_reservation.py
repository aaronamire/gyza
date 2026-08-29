"""Per-principal reservation — the run. Deterministic, SEED = 1, zero credits.

REUSE, AND THE ONE THING THAT IS REPRODUCED. `Cell`, `_orders`, `_drain_budget`,
`ROUNDS` and every environment/adversary module are IMPORTED from `run_ag3`, so
the measurement frame is bit-identical to AG-3's. The ONLY thing reproduced is
the round loop, and only because a per-round `open_round(s)` hook does not exist
in the committed runner -- guards there are `reset(s0)` once and never again.

That duplication is disclosed rather than hidden: `_round_loop` below is
AG-3's loop plus exactly one added call. If AG-3's loop changes, this drifts,
and the parity test in test_reservation.py is what would catch it.

The committed originals are NOT modified. Their sha256s are recorded in
FINDINGS_RESERVATION.md.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "federation"))

import env_aggregate as A                      # noqa: E402
import env_federation as E                     # noqa: E402  READ-ONLY
import guards_reservation as GR                # noqa: E402
import run_ag3 as R                            # noqa: E402  READ-ONLY

CONFIGS = ("F0", "PARTITIONED_READ", "RESERVATION")
MODES = ("serialized", "concurrent")


def run_cell(config, adversary, m, n, mode, rounds=R.ROUNDS) -> R.Cell:
    """AG-3's run_cell with ONE addition: `open_round(s)` per round."""
    rng = random.Random(A.SEED)
    ps = E.principals(m)
    s0 = E.arena(m)
    guards = GR.make_guards(config, ps)
    for g in guards.values():
        g.reset(s0)
    adv = R.ADV.ADVERSARIES[adversary]
    fed_guards = {p: __import__("guards_federation").F0(p, A.THETA) for p in ps}

    cell = R.Cell(config, adversary, m, n, mode, rounds=rounds)
    acc = A.CrossDrainAccumulator(s0, ps)
    peak = A.PeakConcentration(s0, ps)
    budget = R._drain_budget(m)
    s = s0

    for r in range(rounds):
        # ---- THE ONE ADDED LINE -----------------------------------------
        # The budget's origin is fixed here, once, from the round's opening
        # state, and is never rewritten inside admits(). A3.
        for g in guards.values():
            if hasattr(g, "open_round"):
                g.open_round(s)

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
                    if E.physically_valid(s, a) and guards[a.principal].admits(s, a):
                        ok.append(a)
                    else:
                        cell.blocked += 1
                if ok:
                    worst = None
                    for order in R._orders(len(ok), rng):
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

        # ---- ENVIRONMENT-SIDE measurement (no guard state read) ----------
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


def main() -> None:
    rows = []
    for config in CONFIGS:
        for adversary in R.ADV.ADVERSARIES:
            for m in (2, 3):
                for n in (1, 2, 4):
                    for mode in MODES:
                        c = run_cell(config, adversary, m, n, mode)
                        eff = (c.admitted / c.proposals) if c.proposals else float("nan")
                        rows.append({
                            "config": config, "adversary": adversary,
                            "m": m, "n": n, "mode": mode,
                            "v_inst": c.v_instantaneous,
                            "v_cum": c.v_cumulative,
                            "max_conc": c.max_concentration,
                            "admitted": c.admitted, "blocked": c.blocked,
                            "proposals": c.proposals,
                            "throughput": eff,
                        })

    print(f"{'config':<18}{'mode':<12}{'M':>2}{'N':>2}"
          f"{'v_inst':>8}{'maxconc':>9}{'thru':>8}{'blocked':>9}")
    for r in rows:
        mc = "-" if r["max_conc"] is None else f"{r['max_conc']:.4f}"
        print(f"  {r['config']:<16}{r['mode']:<12}{r['m']:>2}{r['n']:>2}"
              f"{r['v_inst']:>8}{mc:>9}{r['throughput']:>8.3f}{r['blocked']:>9}")

    (HERE / "reservation_result.json").write_text(json.dumps(rows, indent=1))
    print(f"\nwrote {HERE / 'reservation_result.json'}  ({len(rows)} cells)")


if __name__ == "__main__":
    main()
