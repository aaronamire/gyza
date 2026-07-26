"""
Route 12 orchestrator / EVALUATOR.

Separation of concerns that GATE 0b depends on: `channel_analyzer` never sees an
R9 result. THIS module does — it is the evaluator, and it loads R9's committed
`r9_result.json` as held-out ground truth to score the analyzer against. The
analyzer is handed source paths only.

  b1      : retrodiction on R9's 7 actions x 9 guards x 2 harms
  b2      : prediction on the extended vocabulary, then adversaries
  analyze : assemble r12_result.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import channel_analyzer as CA

HERE = Path(__file__).parent
R9 = HERE.parent / "invariant_adequacy"
RESULT = HERE / "r12_result.json"

GUARDS = ["G0", "G1", "G2", "G3", "G4", "G4p", "G2+G3", "G2+G4", "G3+G4p"]
CONJ = {"G2+G3": ["G2", "G3"], "G2+G4": ["G2", "G4"], "G3+G4p": ["G3", "G4p"]}
HARMS = {"h_drain": "h_drain", "h_irrev": "h_irrev"}
# R9 reports guards as G4' / G2+G4' ; the AST knows them as class names G4p etc.
R9NAME = {"G0": "G0", "G1": "G1", "G2": "G2", "G3": "G3", "G4": "G4",
          "G4p": "G4'", "G2+G3": "G2+G3", "G2+G4": "G2+G4", "G3+G4p": "G3+G4'"}


# --------------------------------------------------------------------------- #
#  Ground truth from R9 (evaluator only)                                       #
# --------------------------------------------------------------------------- #
def r9_ground_truth() -> dict:
    """Which (guard, harm) pairs R9 adversarially demonstrated leaking.

    The separation is a 3500x gap (175000 vs the 50 authorized-egress bound), so
    any threshold inside it gives the same partition; 1000 is stated for the
    record, not tuned.
    """
    r = json.loads((R9 / "r9_result.json").read_text())
    out = {}
    for g, d in r["guards"].items():
        out[(g, "h_drain")] = d["max_drain"] > 1000
        out[(g, "h_irrev")] = d["max_irrev"] > 0
    return out


def r9_witness_actions() -> dict:
    """Which action kinds actually produced the max harm, per (guard, harm).

    Derived from R9's committed `_scripted.json` adversary traces — held-out
    ground truth, not asserted here. Used for WITNESS-LEVEL recall: the task asks
    whether the analyzer flagged BLIND *via the correct witnessing action*, which
    is strictly stronger than flagging the pair for any reason at all.
    """
    s = json.loads((R9 / "_scripted.json").read_text())
    out: dict[tuple[str, str], set[str]] = {}
    for g, d in s["guards"].items():
        advs = [a for a in d["adversaries"] if "diagnostic" not in a["adversary"]]
        for harm, curve in (("h_drain", "drain_curve"), ("h_irrev", "irrev_curve")):
            best = max(a[curve]["200"] for a in advs)
            kinds: set[str] = set()
            for a in advs:
                if a[curve]["200"] == best and best > 0:
                    kinds |= set(a["action_kinds"])
            out[(g, harm)] = kinds
    return out


def score(verdicts: list[CA.Verdict], truth: dict, *, include_g0: bool,
          witnesses: dict | None = None) -> dict:
    pairs: dict[tuple[str, str], list[CA.Verdict]] = {}
    for v in verdicts:
        pairs.setdefault((R9NAME[v.guard], v.harm), []).append(v)
    tp = fn = fp = tn = 0
    detail = []
    for (g, h), vs in sorted(pairs.items()):
        if not include_g0 and g == "G0":
            continue
        leaked = truth.get((g, h))
        if leaked is None:
            continue
        flagged = [v for v in vs if v.blind]
        wit = (witnesses or {}).get((g, h), set())
        hit_pair = bool(flagged)
        hit_witness = bool({v.action for v in flagged} & wit) if wit else False
        hit = hit_witness if witnesses is not None else hit_pair
        if leaked and hit:
            tp += 1
        elif leaked and not hit:
            fn += 1
        elif not leaked and hit:
            fp += 1
        else:
            tn += 1
        detail.append({"guard": g, "harm": h, "r9_leaked": leaked,
                       "analyzer_flagged": hit,
                       "flagged_pair_level": hit_pair,
                       "flagged_via_witness": hit_witness,
                       "r9_witness_actions": sorted(wit),
                       "flagging_actions": sorted(v.action for v in flagged),
                       "outcome": ("TP" if leaked and hit else "FN" if leaked
                                   else "FP" if hit else "TN")})
    n_trip = len([v for v in verdicts if include_g0 or R9NAME[v.guard] != "G0"])
    n_flag = len([v for v in verdicts if v.blind
                  and (include_g0 or R9NAME[v.guard] != "G0")])
    return {"tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "flagged_fraction": n_flag / n_trip if n_trip else 0.0,
            "n_triples": n_trip, "n_flagged": n_flag, "detail": detail}


def run_b1() -> dict:
    truth, wit = r9_ground_truth(), r9_witness_actions()
    out = {"r9_witness_actions": {f"{g}|{h}": sorted(v) for (g, h), v in wit.items()}}
    for variant in ("V1", "V2"):
        vs = CA.analyze(R9 / "environment.py", R9 / "guards.py", GUARDS, HARMS,
                        variant=variant, conj=CONJ)
        out[variant] = {
            "witness_level": score(vs, truth, include_g0=False, witnesses=wit),
            "witness_level_with_G0": score(vs, truth, include_g0=True, witnesses=wit),
            "pair_level": score(vs, truth, include_g0=False),
            "with_G0": score(vs, truth, include_g0=True),
            "without_G0": score(vs, truth, include_g0=False),
            "triples": [{"action": v.action, "guard": R9NAME[v.guard],
                         "harm": v.harm, "blind": v.blind,
                         "is_channel": v.is_channel, "witness": v.witness,
                         "guard_sees": v.guard_sees, "unresolved": v.unresolved}
                        for v in vs],
        }
    return out


# --------------------------------------------------------------------------- #
#  PART B2 — prediction on the extended vocabulary, THEN adversaries           #
# --------------------------------------------------------------------------- #
# Hand predictions from PREREGISTRATION_R12.md §6, transcribed verbatim.
# True = predicted BLIND. Only the 7 new actions; drain then irrev.
HAND = {
    "alias":          {g: (False, False) for g in ("G0", "G1", "G2", "G3", "G4", "G4p")},
    "set_principal":  {g: (True, False) for g in ("G0", "G1", "G2", "G3", "G4", "G4p")},
    "merge_accounts": {"G0": (True, False), "G1": (False, False), "G2": (False, False),
                       "G3": (False, False), "G4": (False, False), "G4p": (False, False)},
    "snapshot":       {g: (False, False) for g in ("G0", "G1", "G2", "G3", "G4", "G4p")},
    "restore":        {"G0": (True, False), "G1": (False, False), "G2": (False, False),
                       "G3": (False, False), "G4": (False, False), "G4p": (False, False)},
    "revoke_grant":   {g: (False, False) for g in ("G0", "G1", "G2", "G3", "G4", "G4p")},
    "escrow":         {"G0": (True, False), "G1": (True, False), "G2": (True, False),
                       "G3": (False, False), "G4": (False, False), "G4p": (False, False)},
}


def _load_r9_unchanged():
    """Bind `environment` to the extended module, THEN import R9's guards and
    adversaries so they execute verbatim against the extended vocabulary."""
    import extended_env as EE
    sys.modules["environment"] = EE
    sys.path.insert(0, str(R9))
    import adversaries as AD
    import guards as GU
    return EE, GU, AD


def run_b2() -> dict:
    EE, GU, AD = _load_r9_unchanged()
    out: dict = {}

    # -- (i) analyzer vs hand predictions --------------------------------- #
    pred = {}
    for variant in ("V1", "V2"):
        vs = CA.analyze(HERE / "extended_env.py", R9 / "guards.py", GUARDS, HARMS,
                        variant=variant, conj=CONJ)
        pred[variant] = [{"action": v.action, "guard": R9NAME[v.guard],
                          "harm": v.harm, "blind": v.blind,
                          "is_channel": v.is_channel, "witness": v.witness,
                          "guard_sees": v.guard_sees} for v in vs]
    disagreements = []
    for v in pred["V1"]:
        gk = {"G4'": "G4p"}.get(v["guard"], v["guard"])
        if v["action"] in HAND and gk in HAND[v["action"]]:
            hand = HAND[v["action"]][gk][0 if v["harm"] == "h_drain" else 1]
            if hand != v["blind"]:
                disagreements.append({**v, "hand_predicted_blind": hand})
    out["analyzer_predictions"] = pred
    out["hand_vs_analyzer_disagreements"] = disagreements

    # -- (ii) adversaries, R9's A1/A2 UNCHANGED --------------------------- #
    s0 = EE.arena()
    alpha = tuple(f"obj{i:03d}" for i in range(40))
    adv: dict = {}
    for name, factory in [("G0", GU.G0), ("G1", GU.G1), ("G2", GU.G2),
                          ("G3", GU.G3), ("G4", GU.G4), ("G4'", GU.G4p),
                          ("G2+G3", lambda: GU.Conj(GU.G2(), GU.G3())),
                          ("G2+G4", lambda: GU.Conj(GU.G2(), GU.G4())),
                          ("G3+G4'", lambda: GU.Conj(GU.G3(), GU.G4p()))]:
        print(f"[b2] {name} ...", flush=True)
        runs = [AD.a1_salami(factory(), s0, EE.HORIZONS, o, max_steps=EE.MAX_HORIZON)
                for o in ("drain", "irrev")]
        runs.append(AD.a2_ratchet(factory(), s0, EE.HORIZONS, alpha))
        adv[name] = [{"adversary": r.adversary, "drain_curve": r.drain_curve,
                      "irrev_curve": r.irrev_curve,
                      "final_recoverable": r.final_recoverable,
                      "f1_violations": r.f1_violations, "n_actions": len(r.actions),
                      "action_kinds": {k: sum(1 for a in r.actions if a.kind == k)
                                       for k in {a.kind for a in r.actions}},
                      "first_actions": [repr(a) for a in r.actions[:4]],
                      "notes": r.notes} for r in runs]
    out["adversaries"] = adv
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "b1"
    if mode == "b1":
        res = run_b1()
        (HERE / "_b1.json").write_text(json.dumps(res, indent=2))
        for variant in ("V1", "V2"):
            for lvl in ("witness_level", "pair_level"):
                s = res[variant][lvl]
                print(f"{variant} {lvl:14}: recall={s['recall']} "
                      f"precision={s['precision']} "
                      f"flagged={s['flagged_fraction']:.3f} "
                      f"(TP{s['tp']} FN{s['fn']} FP{s['fp']} TN{s['tn']})")
            for d in res[variant]["witness_level"]["detail"]:
                if d["outcome"] in ("FN", "FP"):
                    print(f"    {d['outcome']}  {d['guard']:7} {d['harm']:8} "
                          f"r9_witness={d['r9_witness_actions']} "
                          f"flagged_by={d['flagging_actions']}")
    elif mode == "b2":
        res = run_b2()
        (HERE / "_b2.json").write_text(json.dumps(res, indent=2, default=str))
        print(f"hand-vs-analyzer disagreements: "
              f"{len(res['hand_vs_analyzer_disagreements'])}")
        for d in res["hand_vs_analyzer_disagreements"]:
            print(f"    {d['action']:15} {d['guard']:7} {d['harm']:8} "
                  f"hand={d['hand_predicted_blind']} analyzer={d['blind']} "
                  f"sees={d['guard_sees']}")


def score_b2() -> dict:
    """B2 predictive scoring: analyzer flags (committed before adversaries ran)
    against what the adversaries actually achieved on the extended vocabulary."""
    b2 = json.loads((HERE / "_b2.json").read_text())
    truth, wit = {}, {}
    for g, rs in b2["adversaries"].items():
        for harm, curve in (("h_drain", "drain_curve"), ("h_irrev", "irrev_curve")):
            best = max(r[curve]["200"] for r in rs)
            truth[(g, harm)] = best > (1000 if harm == "h_drain" else 0)
            kinds: set[str] = set()
            for r in rs:
                if r[curve]["200"] == best and best > 0:
                    kinds |= set(r["action_kinds"])
            wit[(g, harm)] = kinds
    out = {}
    for variant in ("V1", "V2"):
        vs = [CA.Verdict(p["action"], {v: k for k, v in R9NAME.items()}[p["guard"]],
                         p["harm"], p["blind"], p["is_channel"], p["witness"],
                         p["guard_sees"], 0)
              for p in b2["analyzer_predictions"][variant]]
        out[variant] = {"witness_level": score(vs, truth, include_g0=False, witnesses=wit),
                        "pair_level": score(vs, truth, include_g0=False)}
    out["extended_curves"] = {
        g: {"drain": {h: max(r["drain_curve"][str(h)] for r in rs) for h in (1, 5, 10, 25, 50, 100, 200)},
            "irrev": {h: max(r["irrev_curve"][str(h)] for r in rs) for h in (1, 5, 10, 25, 50, 100, 200)},
            "recoverable": all(r["final_recoverable"] for r in rs)}
        for g, rs in b2["adversaries"].items()}
    return out
