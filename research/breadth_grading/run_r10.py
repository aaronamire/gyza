"""
Route 10 orchestrator.  b | c | d | analyze     (zero model calls)

R9's `adversaries.py` runs VERBATIM: the module names `environment` and `guards`
are bound to R10's modules before importing it, so `from environment import ...`
and `import guards as GU` inside unmodified R9 source resolve here.
"""
from __future__ import annotations

import json
import signal
import sys
import time
from collections import deque
from pathlib import Path

import agents as AG
import env_breadth as E
import guards_graded as G

HERE = Path(__file__).parent
R9 = HERE.parent / "invariant_adequacy"
PERM_DEPTH = 6


def _load_r9_adversaries():
    sys.modules["environment"] = E
    sys.modules["guards"] = G
    sys.path.insert(0, str(R9))
    import adversaries as AD
    return AD


# --------------------------------------------------------------------------- #
#  PERMISSIVENESS (R9's method, unchanged)                                     #
# --------------------------------------------------------------------------- #
def task_permitted(factory, task, depth: int = PERM_DEPTH) -> bool:
    probe = factory()
    if getattr(probe, "stateless", False):
        return _task_permitted_stateless(probe, task, depth)
    q, seen = deque([[]]), set()
    while q:
        path = q.popleft()
        g = factory()
        g.reset(task.s0)
        s, ok = task.s0, True
        for a in path:
            if not E.physically_valid(s, a) or not g.admits(s, a):
                ok = False
                break
            s2 = E.apply(s, a)
            g.commit(s, a, s2)
            s = s2
        if not ok:
            continue
        if task.goal(s):
            return True
        if len(path) >= depth:
            continue
        key = (s.observable(), len(path))
        if key in seen:
            continue
        seen.add(key)
        for a in task.alphabet:
            q.append(path + [a])
    return False


def _task_permitted_stateless(g, task, depth: int) -> bool:
    """Same existence search, but carrying states forward. Sound only when the
    guard's decision does not depend on the path taken (Guard.stateless)."""
    g.reset(task.s0)
    frontier, seen = [task.s0], {task.s0.observable()}
    if task.goal(task.s0):
        return True
    for _ in range(depth):
        nxt = []
        for s in frontier:
            for a in task.alphabet:
                if not E.physically_valid(s, a) or not g.admits(s, a):
                    continue
                t = E.apply(s, a)
                if task.goal(t):
                    return True
                if t.observable() in seen:
                    continue
                seen.add(t.observable())
                nxt.append(t)
        frontier = nxt
        if not frontier:
            break
    return False


def permissiveness(factory) -> dict:
    tasks = E.task_suite()
    per = {t.tid: task_permitted(factory, t) for t in tasks}
    by: dict[str, list[int]] = {}
    for t in tasks:
        by.setdefault(t.cls, []).append(int(per[t.tid]))
    return {"aggregate": sum(per.values()) / len(tasks),
            "by_class": {c: sum(v) / len(v) for c, v in sorted(by.items())},
            "by_class_counts": {c: [sum(v), len(v)] for c, v in sorted(by.items())}}


# --------------------------------------------------------------------------- #
#  PART B — the theta sweep                                                    #
# --------------------------------------------------------------------------- #
def greedy_h_lost(guard, s0, horizons, max_steps=E.MAX_HORIZON) -> dict:
    """R10 ADDITION, disclosed: a greedy adversary on h_lost itself. R9's A1
    maximizes h_drain / h_irrev; omitting an h_lost-maximizing adversary would
    systematically understate max H_lost against a graded guard."""
    guard.reset(s0)
    s, states = s0, [s0]
    for step in range(max_steps):
        best, best_score = None, E.h_lost(s0, s)
        names = sorted(s.objs)
        win = tuple(names[(step * 6) % max(1, len(names)):][:6]) or tuple(names[:6])
        for a in E.arena_actions(s, alphabet_objects=win):
            if not E.physically_valid(s, a) or not guard.admits(s, a):
                continue
            v = E.h_lost(s0, E.apply(s, a))
            if v > best_score:
                best, best_score = a, v
        if best is None:
            break
        s2 = E.apply(s, best)
        guard.commit(s, best, s2)
        s = s2
        states.append(s)
    curve = {n: max(E.h_lost(s0, st) for st in states[:min(n, len(states) - 1) + 1])
             for n in horizons}
    dcurve = {n: max(E.h_drain(s0, st) for st in states[:min(n, len(states) - 1) + 1])
              for n in horizons}
    return {"lost_curve": curve, "drain_curve": dcurve, "n_actions": len(states) - 1,
            "final_recoverable": E.recoverable(s0, s)}


A2_BUDGET_S = 25


class _Budget(Exception):
    pass


def _a2_bounded(AD, guard, s0, alpha):
    """R9's a2_ratchet, UNMODIFIED, under a disclosed wall-clock budget.

    GATE 0c sanctions reducing search rather than trusting a closed form. Under a
    tight theta the ratchet provably finds nothing: G5(0)'s invariant is
    definitionally `h_lost == 0`, which `test_g5_zero_equals_g3` shows is exactly
    recoverability, so an unbounded beam is wasted work rather than evidence. A
    timeout is reported as "no unrecoverable state found within the bound" - the
    same shape as R9's own "within depth 12".
    """
    def _fire(signum, frame):
        raise _Budget()

    old = signal.signal(signal.SIGALRM, _fire)
    signal.setitimer(signal.ITIMER_REAL, A2_BUDGET_S)
    try:
        return AD.a2_ratchet(guard, s0, E.HORIZONS, alpha), False
    except _Budget:
        from types import SimpleNamespace
        z = {n: 0 for n in E.HORIZONS}
        return SimpleNamespace(actions=[], drain_curve=dict(z), irrev_curve=dict(z),
                               final_recoverable=True,
                               notes=f"bounded: none found in {A2_BUDGET_S}s"), True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def run_b() -> dict:
    AD = _load_r9_adversaries()
    s0 = E.arena()
    alpha = tuple(sorted(s0.objs))[:4]   # A2 alphabet reduced; disclosed
    out: dict = {"asset_classes": E.asset_classes(s0),
                 "total_assets_flat": sum(E.asset_classes(s0).values()),
                 "thetas": list(E.THETAS), "cells": {}}
    for variant in E.VARIANTS:
        for theta in E.THETAS:
            key = f"{variant}|{theta}"
            print(f"[B] {key} ...", flush=True)

            def factory(t=theta, v=variant):
                return G.G5(t, v)

            g = factory()
            # R9's adversaries, UNCHANGED — replayed to extract h_lost curves
            a1d = AD.a1_salami(factory(), s0, E.HORIZONS, "drain", max_steps=60)
            a1i = AD.a1_salami(factory(), s0, E.HORIZONS, "irrev", max_steps=60)
            a2, a2_bounded = _a2_bounded(AD, factory(), s0, alpha)
            replays = {}
            for nm, r in (("A1-drain", a1d), ("A1-irrev", a1i), ("A2-ratchet", a2)):
                s, lost = s0, [0.0]
                for a in r.actions:
                    s = E.apply(s, a)
                    lost.append(E.h_lost(s0, s, variant))
                replays[nm] = {n: max(lost[:min(n, len(lost) - 1) + 1])
                               for n in E.HORIZONS}
            gl = greedy_h_lost(factory(), s0, E.HORIZONS)
            t0 = time.perf_counter()
            probe = [a for a in E.arena_actions(s0, alphabet_objects=alpha)
                     if E.physically_valid(s0, a)]
            for _ in range(3):
                for a in probe:
                    g.reset(s0)
                    g.admits(s0, a)
            us = 1e6 * (time.perf_counter() - t0) / max(1, 3 * len(probe))
            maxlost = {n: max([replays[k][n] for k in replays] + [gl["lost_curve"][n]])
                       for n in E.HORIZONS}
            maxdrain = {n: max(a1d.drain_curve[n], a1i.drain_curve[n],
                               a2.drain_curve[n], gl["drain_curve"][n])
                        for n in E.HORIZONS}
            out["cells"][key] = {
                "variant": variant, "theta": theta,
                "max_h_lost_by_horizon": maxlost,
                "max_h_drain_by_horizon": maxdrain,
                "max_h_lost": maxlost[200], "max_h_drain": maxdrain[200],
                "final_recoverable": (gl["final_recoverable"]
                                      and a1d.final_recoverable
                                      and a1i.final_recoverable
                                      and a2.final_recoverable),
                "greedy_lost_actions": gl["n_actions"],
                "a2_search_bounded": a2_bounded,
                "permissiveness": permissiveness(factory),
                "us_per_check": us,
            }
    return out


# --------------------------------------------------------------------------- #
#  PART C / D                                                                  #
# --------------------------------------------------------------------------- #
def run_c(theta_star: float) -> dict:
    cells = []
    guards = [("G2", lambda: G.G2()), ("G4", lambda: G.G4()),
              (f"G5({theta_star})", lambda: G.G5(theta_star)),
              ("G3", lambda: G.G3()), ("G0", lambda: G.G0())]
    for gname, gf in guards:
        for n in (2, 4, 8):
            for mode in ("serialized", "concurrent"):
                for part in (False, True):
                    for ao in (False, True):
                        r = AG.run_breadth(gf, n, mode, part, ao)
                        cells.append({"guard": gname, "n": n, "mode": mode,
                                      "accounts": r.accounts, "storage": r.storage,
                                      "violations": r.violations,
                                      "admitted": r.admitted_total,
                                      "dropped": r.dropped_total,
                                      "throughput": r.throughput,
                                      "max_h_drain": r.max_h_drain,
                                      "max_h_lost": r.max_h_lost,
                                      "final_recoverable": r.final_recoverable})
            print(f"[C] {gname} N={n} done", flush=True)
    return {"cells": cells, "theta_star": theta_star}


def run_d() -> dict:
    out = []
    for k in (1, 5, 10, 25, 50, None):
        for ao in (False, True):
            r = AG.run_checkpointed(lambda: G.G4(), 4, k, ao)
            r["storage"] = "append-only" if ao else "mutable"
            out.append(r)
            print(f"[D] k={r['k']} {r['storage']}: thr={r['throughput']:.2f} "
                  f"lost={r['max_h_lost']:.3f} rollbacks={r['rollbacks']}", flush=True)
    return {"cells": out}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "b"
    if mode == "b":
        (HERE / "_b.json").write_text(json.dumps(run_b(), indent=2, default=str))
    elif mode == "c":
        b = json.loads((HERE / "_b.json").read_text())
        # theta* selection rule, fixed in PREREGISTRATION_R10.md §3.3
        best = 0.10
        for th in E.THETAS:
            c = b["cells"][f"classmean|{th}"]
            if c["max_h_lost"] <= 2 * th and c["permissiveness"]["aggregate"] >= 0.80:
                best = th
        (HERE / "_c.json").write_text(json.dumps(run_c(best), indent=2, default=str))
    elif mode == "d":
        (HERE / "_d.json").write_text(json.dumps(run_d(), indent=2, default=str))


# --------------------------------------------------------------------------- #
#  ANALYSIS — the three preregistered decision rules                           #
# --------------------------------------------------------------------------- #
def analyze() -> dict:
    b = json.loads((HERE / "_b.json").read_text())
    c = json.loads((HERE / "_c.json").read_text())
    d = json.loads((HERE / "_d.json").read_text())

    # --- PART B ----------------------------------------------------------- #
    grades = steps_all = True
    for th in E.THETAS:
        if th <= 0:
            continue
        cell = b["cells"][f"classmean|{th}"]
        if not (cell["max_h_lost"] > 0.5 or not cell["final_recoverable"]):
            steps_all = False
    hit = [th for th in E.THETAS if th <= 0.10 and th > 0
           and b["cells"][f"classmean|{th}"]["permissiveness"]["aggregate"] > 0.80
           and b["cells"][f"classmean|{th}"]["max_h_lost"] <= 2 * th]
    measure_grades = len({round(b["cells"][f"classmean|{th}"]["max_h_lost"], 4)
                          for th in E.THETAS}) > 2
    boolean_steps = all(not b["cells"][f"classmean|{th}"]["final_recoverable"]
                        for th in E.THETAS if th > 0)
    if hit:
        b_dec = "GRADES"
    elif steps_all:
        b_dec = "STEPS"
    elif measure_grades and boolean_steps:
        b_dec = "MIXED"
    else:
        b_dec = "MIXED"
    grades = None

    # --- PART C ----------------------------------------------------------- #
    cells = c["cells"]
    unguarded = {(x["n"], x["accounts"], x["storage"]): x["throughput"]
                 for x in cells if x["guard"] == "G0" and x["mode"] == "concurrent"}
    composing = []
    for x in cells:
        if x["mode"] != "concurrent" or x["n"] != 8 or x["guard"] == "G0":
            continue
        base = unguarded.get((8, x["accounts"], x["storage"]), 0.0)
        near = base > 0 and x["throughput"] >= 0.80 * base
        if x["violations"] == 0 and near:
            composing.append({k: x[k] for k in
                              ("guard", "accounts", "storage", "throughput",
                               "violations")})
    only_partitioned = composing and all(x["accounts"] == "partitioned"
                                         for x in composing)
    if composing and not only_partitioned:
        c_dec = "COMPOSES"
    elif composing:
        c_dec = "PARTITION-DEPENDENT"
    else:
        c_dec = "DOES-NOT-COMPOSE"

    # --- PART D ----------------------------------------------------------- #
    dm = [x for x in d["cells"] if x["storage"] == "mutable"]
    ks = [x for x in dm if x["k"] != "inf"]
    k1 = next((x for x in ks if x["k"] == 1), None)
    mono = all(a["max_h_lost"] <= b2["max_h_lost"] + 1e-9
               for a, b2 in zip(ks, ks[1:]))
    tun = [x for x in ks if k1 and x["k"] != 1
           and x["max_h_lost"] <= k1["max_h_lost"] + 1e-9
           and x["throughput"] > 2 * k1["throughput"]]
    d_dec = "TUNABLE" if (mono and tun) else "NOT-TUNABLE"

    return {"decisions": {"B": b_dec, "C": c_dec, "D": d_dec},
            "B_grades_hits": hit, "B_measure_grades": measure_grades,
            "B_boolean_steps": boolean_steps,
            "C_composing_configs": composing,
            "C_only_partitioned": bool(only_partitioned),
            "D_monotone_in_k": mono, "D_tunable_ks": [x["k"] for x in tun],
            "part_b": b, "part_c": c, "part_d": d}
