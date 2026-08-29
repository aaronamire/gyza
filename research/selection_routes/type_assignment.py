"""
A2 — how far does a MECHANICAL type assigner diverge from the audited one?

The session established that assigning a claim type to a task is ITSELF a
tier-3 claim: the router is sound given a type, nothing verifies the type is
right, and nothing mechanical can. This measures the gap rather than asserting
it.

SCOPING, WHICH IS THE POINT AND NOT A CAVEAT. The corpus's types are CONSTRUCTED
-- each task was generated to be an instance of a known type, and its goal text
was written alongside. A keyword heuristic therefore has an easy job here, so
the number below is a LOWER BOUND on the difficulty of type assignment in the
wild. It measures how clean this corpus is, not how hard the problem is. The
real rate on natural tasks is unmeasured, and unmeasurable without natural
tasks -- which is the same missing artifact this whole part is about.
"""
from __future__ import annotations
import json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent

RULES = [
    (r"content address", "artifact_content_address"),
    (r"manifest'?s? identity|manifest hash", "manifest_identity"),
    (r"enforcement", "enforcement_within_manifest"),
    (r"attenuat|delegat", "delegation_attenuation"),
    (r"envelope signature|icp envelope", "envelope_signature"),
    (r"pass the given tests|passes .* tests", "unit_test_execution"),
    (r"produce a program", "execution_output_content"),
]


def heuristic(goal: str) -> str:
    g = goal.lower()
    for pat, ct in RULES:
        if re.search(pat, g):
            return ct
    return "UNKNOWN"


def main():
    tasks = json.loads((HERE / "corpus.json").read_text())
    dis, unknown, rows = 0, 0, []
    per_type: dict[str, list[int]] = {}
    for t in tasks:
        h = heuristic(t["goal"])
        agree = (h == t["claim_type"])
        per_type.setdefault(t["claim_type"], []).append(1 if agree else 0)
        if h == "UNKNOWN":
            unknown += 1
        if not agree:
            dis += 1
            if len(rows) < 6:
                rows.append({"goal": t["goal"][:70], "heuristic": h,
                             "audited": t["claim_type"]})
    n = len(tasks)
    out = {"n": n, "disagreements": dis, "disagreement_rate": round(dis / n, 4),
           "unassignable_by_heuristic": unknown,
           "per_type_agreement": {k: round(sum(v) / len(v), 4)
                                  for k, v in sorted(per_type.items())},
           "examples": rows,
           "scoping": "types are CONSTRUCTED; this is a LOWER BOUND"}
    (HERE / "type_assignment.json").write_text(json.dumps(out, indent=1))
    print(f"n={n}  disagreement rate = {out['disagreement_rate']:.4f} "
          f"({dis} tasks); heuristic could not assign {unknown}")
    for k, v in out["per_type_agreement"].items():
        print(f"  {k:32} agreement {v:.3f}")
    for r in rows:
        print("  EXAMPLE:", r)


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------- #
#  The 0.0000 above is DEFINITIONAL. This is the measurement that can fail.    #
# --------------------------------------------------------------------------- #
def external_text_test():
    """Can the type be recovered from the EXTERNAL task text alone?

    The 196 MBPP artifacts each carry TWO claim types --
    `execution_output_content` (is it correct?) and `unit_test_execution` (does
    it pass these tests?) -- over the SAME artifact. The external source text
    (MBPP's own prompt, which I did not author) is IDENTICAL for both.

    So a text-based assigner is at chance between them, and no amount of text
    analysis helps: the distinction is about WHAT IS BEING CLAIMED, not about
    what the task is. That is the tier-3-ness of type assignment demonstrated
    rather than asserted.
    """
    tasks = json.loads((HERE / "corpus.json").read_text())
    by_artifact: dict[tuple, set] = {}
    for t in tasks:
        if "problem_idx" not in t:
            continue
        key = (t["handler"], t["problem_idx"])
        by_artifact.setdefault(key, set()).add(t["claim_type"])

    ambiguous = {k: v for k, v in by_artifact.items() if len(v) > 1}
    n = len(by_artifact)
    rate = len(ambiguous) / n if n else 0.0
    best = 1.0 / max(len(v) for v in by_artifact.values()) if by_artifact else None
    out = {"n_external_artifacts": n,
           "artifacts_with_ambiguous_type": len(ambiguous),
           "ambiguity_rate": round(rate, 4),
           "max_accuracy_of_any_text_based_assigner": best,
           "note": ("the external prompt is identical across the competing "
                    "types, so no text feature can separate them")}
    (HERE / "type_assignment_external.json").write_text(json.dumps(out, indent=1))
    print(f"\nEXTERNAL-TEXT TEST: {len(ambiguous)}/{n} artifacts carry >1 claim "
          f"type from IDENTICAL source text (rate {rate:.4f})")
    print(f"  ceiling for ANY text-based assigner on those: {best}")
    return out
