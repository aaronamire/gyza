"""The decidability census — tabulation.

WHAT IS MECHANICAL AND WHAT IS NOT, stated because the distinction decides how
much this result is worth:

  * MECHANICAL: the tabulation, the joint distribution, f, the single-type-cell
    check, the UNSURE/judgement counts, and the pattern rule applied to the
    external vocabulary.
  * AUTHORED: every classification of a Gyza claim type below. The criterion
    (PREREGISTRATION_CENSUS.md 2) narrows the choice but does not remove it.
    Each carries `basis="inspection"` or `basis="judgement"` and the counts are
    reported.

Zero credits. No model call anywhere in this file.
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

ROOT = Path("/home/xan/dev/gyza")
SEED = 1

ACTS = ["DECLARATIVE", "COMMISSIVE", "DIRECTIVE", "ASSERTIVE"]
DETS = ["INTERNAL", "UNDERDETERMINED", "EXOGENOUS", "CONTESTED"]


# ---------------------------------------------------------------------------
# PART A -- Gyza's 18 claim types. AUTHORED classification.
#
# `named` is the claim as its NAME asserts it; `registered` is the claim as the
# registry's verifier actually evaluates it. Where they differ, the difference
# is the finding, not a nuisance -- so both are recorded and both are reported.
# ---------------------------------------------------------------------------
# (type, line, act, det_registered, det_named, basis, note)
GYZA: list[tuple] = [
    ("envelope_signature", 115, "DECLARATIVE", "INTERNAL", "INTERNAL", "inspection",
     "A signature CONSTITUTES approval; verification checks felicity. Envelope + pubkey both held."),
    ("envelope_chain", 116, "DECLARATIVE", "INTERNAL", "INTERNAL", "inspection",
     "Structural well-formedness over held envelopes (icp.py:105)."),
    ("envelope_dag", 117, "DECLARATIVE", "INTERNAL", "INTERNAL", "inspection",
     "As above, DAG form (icp.py:217)."),
    ("manifest_identity", 118, "DECLARATIVE", "INTERNAL", "INTERNAL", "inspection",
     "Content-addressing is constitutive: the manifest IS its hash preimage."),
    ("enforcement_within_manifest", 119, "DIRECTIVE", "INTERNAL", "INTERNAL", "judgement",
     "COMPLIANCE against a stated spec (the manifest). Directive-vs-declarative is a real call: "
     "the manifest is a specification, so 'was it done as specified' fits DIRECTIVE."),
    ("delegation_attenuation", 121, "DECLARATIVE", "INTERNAL", "INTERNAL", "judgement",
     "The subset relation over held grants is constitutive of valid delegation, not a report about it."),
    ("ledger_entry_signatures", 123, "DECLARATIVE", "INTERNAL", "INTERNAL", "inspection",
     "Two signatures over canonical bytes; all held."),
    ("balance_fold", 125, "ASSERTIVE", "INTERNAL", "INTERNAL", "judgement",
     "ASSERTIVE x INTERNAL: it corresponds to a fact (the balance is B) and that fact is "
     "DEFINITIONALLY a fold over held entries. Assertive does not imply unverifiable."),
    ("market_capital_fold", 126, "ASSERTIVE", "INTERNAL", "INTERNAL", "judgement",
     "As balance_fold, post-H2 append-only fix."),
    ("artifact_content_address", 128, "DECLARATIVE", "INTERNAL", "INTERNAL", "inspection",
     "blake3(data) == address. Constitutive."),
    ("unit_test_execution", 132, "ASSERTIVE", "INTERNAL", "EXOGENOUS", "judgement",
     "REGISTERED: passes THESE cases -- cases named in the claim, fn held -> INTERNAL. "
     "NAMED: 'the code works' -> EXOGENOUS. SR-3 measured the finite sample catches nothing "
     "under composition (0.000, n=4), which is the named claim failing, not the registered one."),
    ("memory_retrieval_relevance", 135, "ASSERTIVE", "INTERNAL", "EXOGENOUS", "judgement",
     "POST-respecification. RetrievalClaim names metric/k/threshold/filter/corpus_snapshot, "
     "so the neighbour set is recomputable -> INTERNAL. NAMED ('these memories are relevant') "
     "asks whether nearness under M IS relevance -> EXOGENOUS."),
    ("external_send_content", 137, "ASSERTIVE", "INTERNAL", "EXOGENOUS", "judgement",
     "POST-respecification. Hash binds to bytes that actually left -> INTERNAL. "
     "NAMED ('the RIGHT content was sent') needs a policy no caller supplies -> EXOGENOUS."),
    ("hlc_ordering", 156, "DECLARATIVE", "INTERNAL", "EXOGENOUS", "judgement",
     "The registry's own rationale states the split: 'the ratchet is checkable; wall-clock "
     "truth is not'. Registered = the monotone ratchet. Named = this timestamp reflects real time."),
    ("reputation_score", 158, "DECLARATIVE", "INTERNAL", "EXOGENOUS", "judgement",
     "Registry rationale again: 'range is checkable; whether it tracks trustworthiness is not'. "
     "Registered = 0<=s<=1. Named = the score tracks trustworthiness."),
    ("work_claim_exclusivity", 160, "DECLARATIVE", "INTERNAL", "INTERNAL", "inspection",
     "At most one claim per work item -- a conservation property over held claims."),
    ("execution_output_content", 179, "ASSERTIVE", "EXOGENOUS", "EXOGENOUS", "inspection",
     "Follows from a COMMITTED finding (adapters.py:170-172): restating as 'output hash = H' "
     "verifies reproducibility and discards correctness; a deterministic wrong program passes."),
    ("routing_match_quality", 180, "ASSERTIVE", "EXOGENOUS", "EXOGENOUS", "judgement",
     "The referent of 'match QUALITY' is a counterfactual about which handler would have "
     "succeeded -- not stored state, and not obtainable by naming parameters. R11 ROUTER-DEAD "
     "measured the restatement does not deliver even with an AUROC-1.000 oracle."),
]


# ---------------------------------------------------------------------------
# PART B -- 240 externally-authored CI check names. The rule is declared and
# ordered; first match wins; NO DEFAULT. An unmatched name is UNSURE, which is
# reported separately from EXOGENOUS -- "I could not classify this" and "this
# is exogenous" are different claims.
# ---------------------------------------------------------------------------
EXTERNAL_RULE: list[tuple[str, str, str, str]] = [
    # (regex, act, determinacy, why)
    (r"reviewer will let you know|will let you know",
     "DECLARATIVE", "CONTESTED", "a notice, not a check: no success condition at all"),
    (r"check all job statuses|check build trigger|all checks|ci success",
     "DECLARATIVE", "INTERNAL", "meta-job restating other jobs' held results"),
    (r"upload|publish|deploy|anaconda|cloudflare|pages|preview|\bdocs?\b.*(preview|deploy)",
     "COMMISSIVE", "EXOGENOUS", "success depends on a THIRD-PARTY SERVICE's state, outside the repo"),
    (r"update.tracker|update_tracking|label|triage|assign|stale|comment",
     "COMMISSIVE", "EXOGENOUS", "mutates an external tracker; success is that service's state"),
    (r"benchmark|asv|performance|speed|timing",
     "ASSERTIVE", "EXOGENOUS", "depends on machine/runner state, not on the repo"),
    (r"codecov|coverage",
     "ASSERTIVE", "INTERNAL", "a ratio computed over held source + held tests"),
    (r"codeql|analy[sz]e|bandit|security|sast",
     "ASSERTIVE", "INTERNAL", "static analysis over held source"),
    (r"lint|flake8|ruff|black|format|style|mypy|typecheck|pyright|pre-commit",
     "ASSERTIVE", "INTERNAL", "a rule set applied to held source"),
    (r"build|wheel|sdist|compile|dist|wasm|cibw",
     "ASSERTIVE", "INTERNAL", "it compiles or it does not; evaluable over held source"),
    (r"test|pytest|pylatest|linux|macos|windows|ubuntu|debian|osx|win|arm64|i386|"
     r"free_threaded|scipy_dev|conda|pypy|python3|doctest",
     "ASSERTIVE", "INTERNAL", "a named test suite executed against held source"),
    (r"doc|sphinx|circleci: doc",
     "ASSERTIVE", "INTERNAL", "docs build executes held example code"),
]


def classify_external(name: str):
    low = name.lower()
    for pat, act, det, why in EXTERNAL_RULE:
        if re.search(pat, low):
            return act, det, why
    return "UNSURE", "UNSURE", "no declared pattern matched -- NOT defaulted"


# ---------------------------------------------------------------------------
# Tabulation -- mechanical from here down.
# ---------------------------------------------------------------------------
def joint(rows) -> dict:
    t = {a: {d: 0 for d in DETS + ["UNSURE"]} for a in ACTS + ["UNSURE"]}
    for act, det in rows:
        t.setdefault(act, {d: 0 for d in DETS + ["UNSURE"]})
        t[act][det] = t[act].get(det, 0) + 1
    return t


def show(title, t, total):
    print(f"\n### {title}  (n={total})")
    hdr = f"{'':16}" + "".join(f"{d:>17}" for d in DETS + ["UNSURE"])
    print(hdr)
    for a in ACTS + ["UNSURE"]:
        if a not in t:
            continue
        if sum(t[a].values()) == 0:
            continue
        print(f"{a:16}" + "".join(f"{t[a].get(d,0):>17}" for d in DETS + ["UNSURE"]))


def f_stat(t) -> tuple[float, int, int]:
    row = t.get("ASSERTIVE", {})
    exo = row.get("EXOGENOUS", 0) + row.get("CONTESTED", 0)
    tot = sum(row.get(d, 0) for d in DETS)
    return (exo / tot if tot else float("nan")), exo, tot


def main() -> None:
    print("=" * 78)
    print("PART A -- GYZA'S VOCABULARY (18 types, adapters.py:115-181)")
    print("  NOTE: build_registries() has 14 call sites, ALL TESTS, ZERO production.")
    print("  This is the vocabulary's SPECIFICATION, not its deployed behaviour.")
    print("=" * 78)

    reg = joint([(r[2], r[3]) for r in GYZA])
    nam = joint([(r[2], r[4]) for r in GYZA])
    show("A-registered: determinacy of the claim THE VERIFIER EVALUATES", reg, len(GYZA))
    show("A-named: determinacy of the claim THE TYPE'S NAME ASSERTS", nam, len(GYZA))

    f_reg, e_reg, t_reg = f_stat(reg)
    f_nam, e_nam, t_nam = f_stat(nam)
    print(f"\n  f(gyza, registered) = {e_reg}/{t_reg} = {f_reg:.4f}")
    print(f"  f(gyza, named)      = {e_nam}/{t_nam} = {f_nam:.4f}")

    b = Counter(r[5] for r in GYZA)
    print(f"\n  basis: inspection {b['inspection']}, judgement {b['judgement']}, "
          f"of {len(GYZA)}")

    print("\n" + "=" * 78)
    print("PART B -- EXTERNAL VOCABULARY (CI check names, third-party authored)")
    print("=" * 78)
    checks = json.loads((ROOT / "research/corpus/all_checks.json").read_text())
    names = sorted({c["name"] for v in checks.values() for c in v})
    print(f"  PRs {len(checks)}   distinct check names {len(names)}")

    cls = [(n,) + classify_external(n) for n in names]
    ext = joint([(a, d) for _, a, d, _ in cls])
    show("B: external vocabulary", ext, len(names))

    f_ext, e_ext, t_ext = f_stat(ext)
    unsure = sum(1 for _, a, _, _ in cls if a == "UNSURE")
    print(f"\n  f(external) = {e_ext}/{t_ext} = {f_ext:.4f}")
    print(f"  UNSURE      = {unsure}/{len(names)} = {unsure/len(names):.4f}"
          f"   (reported SEPARATELY from EXOGENOUS)")

    # single-type-cell check, preregistered
    print("\n  cells driven by a SINGLE type (-> INCONCLUSIVE for that cell):")
    any_single = False
    for label, t in (("gyza-registered", reg), ("gyza-named", nam), ("external", ext)):
        for a in t:
            for d, k in t[a].items():
                if k == 1:
                    print(f"    {label}: {a} x {d} = 1  -> INCONCLUSIVE")
                    any_single = True
    if not any_single:
        print("    none")

    # audit sample, seed fixed in the preregistration
    rnd = random.Random(SEED)
    sample = rnd.sample(names, 30)
    (ROOT / "research/census/audit_sample.json").write_text(
        json.dumps([{"name": n, **dict(zip(("act", "det", "why"),
                                           classify_external(n)))} for n in sample],
                   indent=1))
    print(f"\n  audit sample of 30 (SEED={SEED}) written to audit_sample.json")

    (ROOT / "research/census/census_result.json").write_text(json.dumps({
        "gyza_registered": reg, "gyza_named": nam, "external": ext,
        "f_gyza_registered": f_reg, "f_gyza_named": f_nam, "f_external": f_ext,
        "unsure_external": unsure, "n_external": len(names),
        "basis_counts": dict(b),
    }, indent=1))


if __name__ == "__main__":
    main()
