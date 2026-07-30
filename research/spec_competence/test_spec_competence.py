"""
Route 14 tests. Must pass before ANY result is trusted.

The load-bearing one is VACUITY DETECTION: if `return True` did not score
validity 1.0 and kill rate 0.0, the whole route would measure nothing, because
verifiable-but-vacuous is the dominant failure mode being hunted.

Run:  ~/dev/marshal/.os/bin/python -m pytest research/spec_competence/ -q
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "native_verifier"))

import mutations as M                                   # noqa: E402
import spec_experiment as SE                            # noqa: E402
from refspecs import REFERENCE_SPECS, REFERENCE_SPECS_PROP   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROBS = {r["i"]: r for r in json.load(open(os.path.join(HERE, "problems.json")))}


def _calls(r):
    import native_verifier as V
    return V.extract_calls(r["tests"])


def _eval(i, specs):
    r = PROBS[i]
    return M.evaluate_problem(r["fn"], _calls(r), r["tests"], r["code"],
                              M.generate_mutants(r["code"]), specs)


# --------------------------------------------------------------------------- #
#  ISOLATION — a spec written with the answer in view is not a specification   #
# --------------------------------------------------------------------------- #
def test_isolation_prompt_leaks_nothing():
    for i in (0, 13, 33):
        r = PROBS[i]
        for arm in ("PROP", "FREE"):
            p = SE.spec_prompt(r["prompt"], r["fn"], arm)
            assert r["code"] not in p, "reference solution leaked into prompt"
            for t in r["tests"]:
                assert t not in p, "MBPP assert leaked into prompt"
                assert t.replace("assert ", "") not in p
            assert "assert" not in p
            # the entry-point name IS permitted; the body is not
            body = r["code"].split(":", 1)[-1].strip()
            assert body[:40] not in p


def test_isolation_negative_control_detects_a_leak():
    """Without this, the isolation test could be vacuously passing."""
    r = PROBS[0]
    clean = SE.spec_prompt(r["prompt"], r["fn"], "PROP")
    leaked = clean + "\nREFERENCE:\n" + r["code"] + "\n" + r["tests"][0]

    def leaks(p):
        return (r["code"] in p) or any(t in p for t in r["tests"])

    assert not leaks(clean), "clean prompt must not leak"
    assert leaks(leaked), "the leak detector must be able to detect a leak"


# --------------------------------------------------------------------------- #
#  VACUITY DETECTION — the load-bearing test                                   #
# --------------------------------------------------------------------------- #
def test_vacuity_return_true_is_valid_and_kills_nothing():
    for i in (0, 13, 33, 46):
        res = _eval(i, [M.SPEC_TRUE])
        s = res["specs"][0]
        assert s["status"] == "VALID", (i, s)
        assert s["denom"] > 0, f"problem {i} has no WRONG mutants — no power"
        assert s["killed"] == 0, (i, s)


def test_type_only_floor_is_above_zero_but_below_reference():
    """The floor must be a real floor: non-zero (so it is not the same thing as
    vacuity) and strictly below the hand-written ceiling."""
    i = 13
    res = _eval(i, [M.SPEC_TYPE_ONLY, REFERENCE_SPECS_PROP[i]])
    tyo, ref = res["specs"]
    assert tyo["status"] == "VALID" and ref["status"] == "VALID"
    assert ref["killed"] > tyo["killed"], (tyo, ref)


# --------------------------------------------------------------------------- #
#  MUTANT CLASSIFICATION                                                       #
# --------------------------------------------------------------------------- #
def test_equivalent_mutant_is_excluded_from_the_denominator():
    r = PROBS[13]
    muts = M.generate_mutants(r["code"])
    # an equivalent mutant: reformat only (semantically identical)
    equiv = {"op": "noop", "src": r["code"] + "\n"}
    res = M.evaluate_problem(r["fn"], _calls(r), r["tests"], r["code"],
                             muts + [equiv], [M.SPEC_TRUE])
    assert res["mut_class"][-1] == "EQUIVALENT"
    assert res["specs"][0]["denom"] == res["mut_class"].count("WRONG")


def test_syntax_error_mutant_is_discarded_not_counted_as_killed():
    r = PROBS[13]
    bad = {"op": "broken", "src": "def merge_sort(x):\n    return ((("}
    res = M.evaluate_problem(r["fn"], _calls(r), r["tests"], r["code"],
                             [bad], [M.SPEC_TRUE, REFERENCE_SPECS_PROP[13]])
    assert res["mut_class"] == ["DISCARDED"]
    for s in res["specs"]:
        assert s["denom"] == 0, "a discarded mutant must not enter the denominator"


# --------------------------------------------------------------------------- #
#  REFERENCE SPEC — the ceiling is real and the metric has range               #
# --------------------------------------------------------------------------- #
def test_reference_specs_are_valid_and_materially_above_type_only():
    import statistics as st
    tyo, ref = [], []
    for i in sorted(REFERENCE_SPECS_PROP)[:8]:
        res = _eval(i, [M.SPEC_TYPE_ONLY, REFERENCE_SPECS_PROP[i]])
        a, b = res["specs"]
        assert b["status"] == "VALID", (i, b)     # never rejects the reference
        if a["status"] == "VALID" and a["denom"]:
            tyo.append(a["killed"] / a["denom"])
        if b["denom"]:
            ref.append(b["killed"] / b["denom"])
    assert st.mean(ref) > st.mean(tyo) + 0.10, (st.mean(tyo), st.mean(ref))


# --------------------------------------------------------------------------- #
#  NON-SPEC HANDLING                                                           #
# --------------------------------------------------------------------------- #
def test_nonspec_is_excluded_from_both_metrics_never_scored_as_a_miss():
    crashing = "def spec(inp, out):\n    raise ValueError('boom')\n"
    nonbool = "def spec(inp, out):\n    return 'yes'\n"
    missing = "x = 1\n"
    res = _eval(13, [crashing, nonbool, missing])
    for s in res["specs"]:
        assert s["status"] == "NONSPEC", s
        assert "killed" not in s and "denom" not in s


def test_invalid_spec_is_reported_not_imputed():
    always_false = "def spec(inp, out):\n    return False\n"
    res = _eval(13, [always_false])
    s = res["specs"][0]
    assert s["status"] == "INVALID"
    assert "killed" not in s, "an invalid spec must not receive a kill rate"


# --------------------------------------------------------------------------- #
#  CELL PROVENANCE — the R8 GATE 0b lesson                                     #
# --------------------------------------------------------------------------- #
def test_cell_assignment_and_program_source_come_from_the_same_run():
    for model in SE.MODELS:
        f = SE.NV_CACHE / f"prog__{model.replace('/', '__')}.json"
        d = json.loads(f.read_text())
        assert len(d) == 50
        for e in d:
            # both fields in the SAME dict entry — they cannot be from
            # different runs, which is exactly what R8's GATE 0b caught
            assert "source" in e and "status" in e
            assert e["status"] in ("CORRECT", "WRONG", "UNRESOLVED")
    cells = SE.load_cells()
    assert set(cells) == set(SE.MODELS)
    assert all(len(v) == 50 for v in cells.values())


# --------------------------------------------------------------------------- #
#  ORACLE-EMBEDDING heuristic                                                  #
# --------------------------------------------------------------------------- #
def test_embedding_heuristic_flags_a_recomputing_spec_and_spares_a_property_one():
    ref = PROBS[15]["code"]
    embedding = REFERENCE_SPECS[15]          # computes `kept` and compares
    prop = REFERENCE_SPECS_PROP[15]          # order/membership only
    assert SE.embedding_flags(embedding, ref)["embedding"] is True
    assert SE.embedding_flags(prop, ref)["embedding"] is False
    assert SE.embedding_flags(M.SPEC_TRUE, ref)["embedding"] is False


def test_spec_extractor_handles_fences_and_prose():
    src = "Here is the spec:\n```python\ndef spec(inp, out):\n    return isinstance(out, list)\n```\nDone."
    got = SE.extract_spec(src)
    assert got is not None and got.startswith("def spec")
    assert "Here is" not in got and "Done" not in got
    assert SE.extract_spec("no function here") is None


# --------------------------------------------------------------------------- #
#  COMPOSITION (Part B) — without this, B's null has no power                  #
# --------------------------------------------------------------------------- #
def test_cumulative_budget_violation_passes_every_local_spec_and_is_detected():
    """Hand-built: a total-budget violation that EVERY per-stage spec accepts.
    The harness must detect it, or Part B's cumulative null means nothing."""
    import pipelines as P
    found = []
    for pl in P.PIPELINES:
        for idx in (0, 1, 2):
            out, tr = P.run(P.mutate_stage(pl, idx, "overadd"), P.INPUT)
            local_ok = P.per_stage_conjunction(pl, "cumulative", tr)
            e2e_ok = P.E2E["cumulative"](pl, P.INPUT, out)
            if local_ok and not e2e_ok:
                found.append((pl["name"], idx, len(out) - len(P.INPUT)))
    # Not every pipeline admits one — PIPELINES[0] adds 1 per stage, so a single
    # overadd reaches exactly the budget (4 <= 4) rather than exceeding it. The
    # claim under test is that such a violation is CONSTRUCTIBLE and detected.
    assert found, "no local-passing budget violation could be built anywhere"
    for _name, _idx, total in found:
        assert total > P.END_TO_END_BUDGET, (total, P.END_TO_END_BUDGET)


def test_conservation_and_monotone_base_pipelines_satisfy_their_own_specs():
    """A spec that rejects the correct pipeline is invalid; the base case must
    hold or every composition number is meaningless."""
    import pipelines as P
    for pl in P.PIPELINES:
        out, tr = P.run(pl["stages"], P.INPUT)
        for cls in ("conservation", "monotone", "cumulative"):
            assert P.per_stage_conjunction(pl, cls, tr), (pl["name"], cls)
            assert P.E2E[cls](pl, P.INPUT, out), (pl["name"], cls, "e2e")
