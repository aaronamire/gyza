"""
Route 8 orchestrator. `generate` (Stage 1, model calls, cached) then `analyze`
(Stages 2-3, OFFLINE, zero model calls). Deterministic (SEED=1, temp 0).
  generate: ~/dev/marshal/.os/bin/python run_r8.py generate
  analyze : ~/dev/marshal/.os/bin/python run_r8.py analyze
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

import native_verifier as V
from native_verifier import (CACHE, CHECKERS, N_CODE, ROUND1_PASS, SEED,
                             expected_signature, extract_calls, entry_point, load_mbpp)

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "correlated_failure"))


def _problems():
    mbpp = load_mbpp(n=N_CODE, seed=SEED)
    calls = [extract_calls(p["test_list"]) for p in mbpp]
    fns = [entry_point(p["test_list"]) for p in mbpp]
    expected = [expected_signature(c) if c else [] for c in calls]
    return mbpp, calls, fns, expected


# --------------------------------------------------------------------------- #
#  Stage 1 — generation (model calls, cached)                                 #
# --------------------------------------------------------------------------- #
def generate():
    from rho_measure import APIBackend
    BASE = "https://openrouter.ai/api/v1"
    KEY = [l for l in (HERE.parent / "correlated_failure" / ".env").read_text().splitlines()
           if l.startswith("OPENROUTER")][0].split("=", 1)[1].strip()
    CACHE.mkdir(exist_ok=True)
    mbpp, calls, fns, expected = _problems()

    def safe(b, prompt):
        try:
            return b.generate(prompt, max_new_tokens=400)
        except Exception as e:
            return f"__ERR__:{type(e).__name__}"

    for mid, fam in CHECKERS:
        b = APIBackend(mid, fam, base_url=BASE, api_key=KEY)
        slug = mid.replace("/", "__")
        # -- substrate: the model's own programs --
        pf = CACHE / f"prog__{slug}.json"
        if not pf.exists():
            print(f"[gen] {mid}: programs ...", flush=True)
            progs = []
            for i, p in enumerate(mbpp):
                src = V._extract_block(safe(b, V.code_prompt(p, fns[i])))
                sig = V.run_signature(src, calls[i]) if calls[i] else []
                progs.append({"source": src, "signature": sig,
                              "status": V.program_status(sig, expected[i])})
            pf.write_text(json.dumps(progs))
        # -- test suites: both arms --
        for arm in ("E", "P"):
            tf = CACHE / f"tests__{slug}__{arm}.json"
            if tf.exists():
                continue
            print(f"[gen] {mid}: tests arm {arm} ...", flush=True)
            suites = []
            for i, p in enumerate(mbpp):
                if not fns[i]:
                    suites.append({"raw": "", "asserts": []})
                    continue
                raw = safe(b, V.testgen_prompt(p, fns[i], arm))
                suites.append({"raw": raw, "asserts": V.extract_asserts(raw)})
            tf.write_text(json.dumps(suites))
    print("[gen] done.")


# --------------------------------------------------------------------------- #
#  Stage 2-3 — offline analysis                                               #
# --------------------------------------------------------------------------- #
def _load():
    mbpp, calls, fns, expected = _problems()
    progs = {mid: json.loads((CACHE / f"prog__{mid.replace('/', '__')}.json").read_text())
             for mid, _ in CHECKERS}
    tests = {(mid, arm): json.loads(
                 (CACHE / f"tests__{mid.replace('/', '__')}__{arm}.json").read_text())
             for mid, _ in CHECKERS for arm in ("E", "P")}
    return mbpp, calls, fns, expected, progs, tests


def analyze():
    mbpp, calls, fns, expected, progs, tests = _load()
    refs = [p["code"] for p in mbpp]
    scorable = [i for i in range(N_CODE) if fns[i] and calls[i]]
    # recompute status from source+signature: __ERR__ generation failures -> UNRESOLVED
    # (the cached status predates the __ERR__ fix; do not trust it)
    for mid, _ in CHECKERS:
        for i in range(N_CODE):
            p = progs[mid][i]
            p["status"] = V.program_status(p["signature"], expected[i], p.get("source"))

    # ---- validity per (checker, arm, problem): which tests pass the reference ----
    valid = {}          # (mid, arm, i) -> list of valid test srcs
    validity_rows = {}  # (mid, arm) -> dict of validity stats (overall + by cell)
    proto_viol = {}     # (mid, arm) -> (violations, total) for arm P
    for mid, _ in CHECKERS:
        own = progs[mid]
        for arm in ("E", "P"):
            n_tests = n_valid = n_prob_with_valid = 0
            pv = pt = 0
            cell_valid = {"a": [0, 0], "b": [0, 0]}   # [valid, total]
            for i in scorable:
                asserts = tests[(mid, arm)][i]["asserts"]
                vlist = []
                for t in asserts:
                    n_tests += 1
                    if arm == "P":
                        pt += 1
                        if V.is_smuggled_example(t, fns[i]):
                            pv += 1
                    if V.test_is_valid(t, refs[i]):
                        vlist.append(t)
                valid[(mid, arm, i)] = vlist
                n_valid += len(vlist)
                if vlist:
                    n_prob_with_valid += 1
                # split validity by checker's OWN status on this problem
                st = own[i]["status"]
                if st in ("CORRECT", "WRONG"):
                    cell = "a" if st == "CORRECT" else "b"
                    cell_valid[cell][0] += len(vlist)
                    cell_valid[cell][1] += len(asserts)
            validity_rows[(mid, arm)] = dict(
                test_validity_rate=round(n_valid / n_tests, 4) if n_tests else None,
                frac_problems_with_valid=round(n_prob_with_valid / len(scorable), 4),
                n_tests=n_tests, n_valid=n_valid,
                validity_cell_a=round(cell_valid["a"][0] / cell_valid["a"][1], 4)
                                if cell_valid["a"][1] else None,
                validity_cell_b=round(cell_valid["b"][0] / cell_valid["b"][1], 4)
                                if cell_valid["b"][1] else None,
                n_cell_a_tests=cell_valid["a"][1], n_cell_b_tests=cell_valid["b"][1])
            if arm == "P":
                proto_viol[mid] = dict(violations=pv, total=pt,
                                       rate=round(pv / pt, 4) if pt else None)

    # ---- detection: cross pairs (checker != claimant) and self (arm S) ----
    # Two variants: VALID-only (reference-filtered UPPER BOUND, unavailable in
    # production) and ALL-tests (unfiltered, the deployable variant).
    def run_detection(select):
        det, percheck = {}, {}

        def add(key, pk, i, fired, wrong):
            det.setdefault(key, {"pairs": [], "groups": {}})
            det[key]["pairs"].append((fired, wrong))
            det[key]["groups"].setdefault(i, []).append((fired, wrong))
            percheck.setdefault(pk, []).append((fired, wrong))

        for mid, _ in CHECKERS:
            own = progs[mid]
            for arm in ("E", "P"):
                for i in scorable:
                    stests = select(mid, arm, i)
                    cst = own[i]["status"]
                    if cst not in ("CORRECT", "WRONG"):
                        continue                 # checker's own program unresolved
                    cell = "a" if cst == "CORRECT" else "b"
                    for cmid, _ in CHECKERS:
                        prog = progs[cmid][i]
                        if prog["status"] == "UNRESOLVED":
                            continue             # never score an unresolved claimant
                        wrong = prog["status"] == "WRONG"
                        res = V.score_triple(stests, prog["source"], wrong)
                        if res is None:
                            continue             # zero (valid) tests -> excluded
                        fired, w = res
                        pairing = "self" if cmid == mid else "cross"
                        add((arm, pairing, cell), (mid, arm, pairing, cell), i, fired, w)
                        add((arm, pairing, "all"), (mid, arm, pairing, "all"), i, fired, w)
        return det, percheck

    det, percheck = run_detection(lambda m, a, i: valid[(m, a, i)])
    det_all, _ = run_detection(lambda m, a, i: tests[(m, a)][i]["asserts"])

    def block(key, source=det):
        d = source.get(key)
        if not d:
            return dict(n=0)
        groups = list(d["groups"].values())
        return V.metrics_from_pairs(d["pairs"], groups=groups, seed=SEED)

    # ---- assemble result ----
    # pass rate over RESOLVED scorable programs only (exclude __ERR__/timeout non-programs)
    def _passrate(mid):
        res = [progs[mid][i]["status"] for i in scorable
               if progs[mid][i]["status"] != "UNRESOLVED"]
        return round(sum(s == "CORRECT" for s in res) / len(res), 3) if res else None
    new_pass = {mid: _passrate(mid) for mid, _ in CHECKERS}
    unresolved = {mid: sum(progs[mid][i]["status"] == "UNRESOLVED" for i in scorable)
                  for mid, _ in CHECKERS}

    result = dict(
        seed=SEED, n_problems=N_CODE, n_scorable=len(scorable),
        roster=[m for m, _ in CHECKERS],
        drift_disclosure=dict(round1_pass=ROUND1_PASS, new_pass=new_pass,
                              unresolved_per_model=unresolved),
        Q1_validity={f"{mid}|{arm}": validity_rows[(mid, arm)]
                     for mid, _ in CHECKERS for arm in ("E", "P")},
        Q1_protocol_violation_armP=proto_viol,
        Q2_cross={f"{arm}|{cell}": block((arm, "cross", cell))
                  for arm in ("E", "P") for cell in ("all", "a", "b")},
        Q2_cross_ALL_TESTS_unfiltered={f"{arm}|{cell}": block((arm, "cross", cell), det_all)
                                       for arm in ("E", "P") for cell in ("all", "a", "b")},
        armS_self={f"{arm}|{cell}": block((arm, "self", cell))
                   for arm in ("E", "P") for cell in ("all", "a", "b")},
        per_checker_cross={f"{mid}|{arm}|{cell}": V.metrics_from_pairs(
                               percheck.get((mid, arm, "cross", cell), []), seed=SEED)
                           for mid, _ in CHECKERS for arm in ("E", "P")
                           for cell in ("all", "a", "b")},
    )
    # Q3 paired E vs P over identical (checker, problem, claimant) cross triples
    result["Q3_paired_E_vs_P"] = _paired_EvP(progs, valid, scorable, fns)
    # Q4 error-class dissociation (computational vs comprehension), valid tests, cross
    result["Q4_dissociation"] = _q4(progs, valid, scorable, expected)
    (HERE / "r8_result.json").write_text(json.dumps(result, indent=2, default=_js))
    _print_summary(result)


def _paired_EvP(progs, valid, scorable, fns):
    """Paired over triples where BOTH arms have >=1 valid test for that problem."""
    out = {}
    for cell in ("a", "b", "all"):
        eP, pP = [], []
        for mid, _ in CHECKERS:
            own = progs[mid]
            for i in scorable:
                ve, vp = valid[(mid, "E", i)], valid[(mid, "P", i)]
                if not ve or not vp:
                    continue
                cst = own[i]["status"]
                if cst not in ("CORRECT", "WRONG"):
                    continue
                c = "a" if cst == "CORRECT" else "b"
                if cell != "all" and c != cell:
                    continue
                for cmid, _ in CHECKERS:
                    if cmid == mid:
                        continue
                    prog = progs[cmid][i]
                    if prog["status"] == "UNRESOLVED":
                        continue
                    w = prog["status"] == "WRONG"
                    eP.append((V.suite_fires(ve, prog["source"]), w))
                    pP.append((V.suite_fires(vp, prog["source"]), w))
        mE, mP = V.metrics_from_pairs(eP, seed=SEED), V.metrics_from_pairs(pP, seed=SEED)
        out[cell] = dict(n_paired=len(eP), armE=mE, armP=mP,
                         J_diff_P_minus_E=(None if (mE.get("J") is None or mP.get("J") is None)
                                           else round(mP["J"] - mE["J"], 4)))
    return out


def _q4(progs, valid, scorable, expected):
    """For each WRONG claimant program (bug class from signature), the fraction caught
    by checker-written VALID tests (cross), per arm. Prediction: computational >> comp-
    rehension. Also dumps a labeling sample for hand-validation of the classifier."""
    counts = {}   # (arm, cell, bugclass) -> [caught, total]
    sample = []
    for mid, _ in CHECKERS:
        own = progs[mid]
        for arm in ("E", "P"):
            for i in scorable:
                vtests = valid[(mid, arm, i)]
                if not vtests:
                    continue
                cst = own[i]["status"]
                if cst not in ("CORRECT", "WRONG"):
                    continue
                cell = "a" if cst == "CORRECT" else "b"
                for cmid, _ in CHECKERS:
                    if cmid == mid:
                        continue
                    prog = progs[cmid][i]
                    if prog["status"] != "WRONG":
                        continue
                    bc = V.classify_bug(prog["signature"], expected[i])
                    if bc is None:
                        continue
                    caught = V.suite_fires(vtests, prog["source"])
                    for c in (cell, "all"):
                        counts.setdefault((arm, c, bc), [0, 0])
                        counts[(arm, c, bc)][0] += caught
                        counts[(arm, c, bc)][1] += 1
                    if len(sample) < 40 and arm == "E":
                        sample.append(dict(claimant=cmid.split("/")[-1], problem_idx=i,
                                           bugclass=bc, signature=prog["signature"],
                                           expected=expected[i]))
    out = {f"{arm}|{cell}|{bc}": dict(caught=v[0], total=v[1],
                                      catch_rate=round(v[0] / v[1], 4) if v[1] else None)
           for (arm, cell, bc), v in sorted(counts.items())}
    (HERE / "q4_label_sample.json").write_text(json.dumps(sample, indent=2, default=_js))
    return out


def _js(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if o == float("inf"):
        return "inf"
    return str(o)


def _print_summary(r):
    print("=== R8 summary ===")
    print("drift new_pass:", r["drift_disclosure"]["new_pass"],
          "| round1:", {k.split('/')[-1]: v for k, v in r["drift_disclosure"]["round1_pass"].items()})
    print("unresolved/model:", r["drift_disclosure"]["unresolved_per_model"])
    print("-- Q1 validity (rate | cell_a | cell_b) --")
    for k, v in r["Q1_validity"].items():
        print(f"  {k:>52}: {v['test_validity_rate']} | a={v['validity_cell_a']} b={v['validity_cell_b']}")
    print("  arm-P protocol violations:", {m.split('/')[-1]: d["rate"]
                                            for m, d in r["Q1_protocol_violation_armP"].items()})
    print("-- Q2 cross detection (n, TPR, FPR, LR, J[CI], perm_p) --")
    for k, m in r["Q2_cross"].items():
        if m.get("n"):
            print(f"  {k:>7}: n={m['n']} nw={m.get('n_wrong')} TPR={m.get('TPR')} "
                  f"FPR={m.get('FPR')} LR={m.get('LR')} J={m.get('J')} {m.get('J_ci')} p={m.get('perm_p')}")
    print("-- Q2 cross ALL-TESTS unfiltered (deployable; no reference filter) --")
    for k, m in r["Q2_cross_ALL_TESTS_unfiltered"].items():
        if m.get("n"):
            print(f"  {k:>7}: n={m['n']} TPR={m.get('TPR')} FPR={m.get('FPR')} "
                  f"LR={m.get('LR')} J={m.get('J')} {m.get('J_ci')}")
    print("-- Q4 dissociation (catch rate by bug class, valid tests, cross) --")
    for k, v in r["Q4_dissociation"].items():
        print(f"  {k:>22}: {v['catch_rate']} (caught {v['caught']}/{v['total']})")
    print("-- arm S (self) --")
    for k, m in r["armS_self"].items():
        if m.get("n"):
            print(f"  {k:>7}: n={m['n']} TPR={m.get('TPR')} FPR={m.get('FPR')} J={m.get('J')}")
    print("-- Q3 paired E vs P --")
    for cell, d in r["Q3_paired_E_vs_P"].items():
        print(f"  cell {cell}: n={d['n_paired']} J_E={d['armE'].get('J')} "
              f"J_P={d['armP'].get('J')} diff(P-E)={d['J_diff_P_minus_E']}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    (generate if mode == "generate" else analyze)()
