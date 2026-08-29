"""
AR-3 — do NON-TEXT signals assign claim type above the 0.5 text ceiling?

Signals are derived from the OBJECT the claim is about, never from its
description. Deterministic, zero model calls.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from gyza.verification.adapters import build_registries      # noqa: E402

SEED = 1

# The OBJECT each claim type is about, and the state it touches. Both are
# properties of the registered verifier's input contract, read off the adapter
# signatures -- not a labelling invented for this route.
OBJECT_SHAPE = {
    "envelope_signature":          "ICPEnvelope",
    "envelope_chain":              "ICPEnvelope",
    "envelope_dag":                "ICPEnvelope",
    "manifest_identity":           "manifest-dict",
    "enforcement_within_manifest": "enforcement-dict",
    "delegation_attenuation":      "DelegationHop-chain",
    "ledger_entry_signatures":     "LedgerEntry",
    "balance_fold":                "LedgerEntry-sequence",
    "market_capital_fold":         "CapitalEntry-sequence",
    "artifact_content_address":    "bytes",
    "unit_test_execution":         "program",
    "execution_output_content":    "program",      # SAME object as above
}

# Which verifiers' input contract an object of this shape satisfies.
APPLICABILITY = defaultdict(set)
for _ct, _shape in OBJECT_SHAPE.items():
    APPLICABILITY[_shape].add(_ct)

# Pair kind: do the competing types differ in the OBJECT, or only in what is
# ASSERTED about the same object?
ASSERTION_DIFFERING = {"unit_test_execution", "execution_output_content"}


def main() -> None:
    verifiers, _s = build_registries()
    types = sorted(set(OBJECT_SHAPE))

    rows = []
    for ct in types:
        shape = OBJECT_SHAPE[ct]
        # SHAPE signal: which types share this object shape?
        shape_peers = {t for t in types if OBJECT_SHAPE[t] == shape}
        # APPLICABILITY signal: which verifiers accept an object of this shape?
        applicable = APPLICABILITY[shape]
        rows.append({
            "claim_type": ct,
            "shape": shape,
            "shape_unique": len(shape_peers) == 1,
            "shape_peers": sorted(shape_peers),
            "applicability_unique": len(applicable) == 1,
            "n_applicable_verifiers": len(applicable),
            "pair_kind": ("ASSERTION" if ct in ASSERTION_DIFFERING else "TOUCH"),
            "registered": ct in verifiers.claim_types(),
        })

    def rate(sub, key):
        return round(sum(1 for r in sub if r[key]) / len(sub), 4) if sub else None

    touch = [r for r in rows if r["pair_kind"] == "TOUCH"]
    assertion = [r for r in rows if r["pair_kind"] == "ASSERTION"]

    # FEASIBILITY: does SHAPE carry any information at all?
    distinct_shapes = len({r["shape"] for r in rows})
    informative = distinct_shapes > 1

    res = {
        "seed": SEED, "n_claim_types": len(rows),
        "distinct_shapes": distinct_shapes,
        "feasible_signal_carries_information": informative,
        "overall": {
            "shape_unique_determination": rate(rows, "shape_unique"),
            "applicability_unique_determination": rate(rows, "applicability_unique"),
            "AMBIGUITY_RATE_shape": round(
                sum(1 for r in rows if not r["shape_unique"]) / len(rows), 4),
        },
        "by_pair_kind": {
            "TOUCH": {"n": len(touch),
                      "shape_unique": rate(touch, "shape_unique"),
                      "applicability_unique": rate(touch, "applicability_unique")},
            "ASSERTION": {"n": len(assertion),
                          "shape_unique": rate(assertion, "shape_unique"),
                          "applicability_unique": rate(assertion, "applicability_unique"),
                          "best_achievable_accuracy": round(1 / len(assertion), 4)
                          if assertion else None,
                          "DEFINITIONAL": True},
        },
        "rows": rows,
    }
    (HERE / "ar3_result.json").write_text(json.dumps(res, indent=1))

    print(f"claim types: {len(rows)}   distinct object shapes: {distinct_shapes}"
          f"   signal informative: {informative}\n")
    print(f"{'':22} {'shape-unique':>13} {'applic-unique':>14}")
    print(f"{'OVERALL':22} {res['overall']['shape_unique_determination']:>13.4f} "
          f"{res['overall']['applicability_unique_determination']:>14.4f}")
    for k in ("TOUCH", "ASSERTION"):
        b = res["by_pair_kind"][k]
        label = "%s (n=%d)" % (k, b["n"])
        print(f"{label:22} {b['shape_unique']:>13.4f} "
              f"{b['applicability_unique']:>14.4f}")
    print(f"\nAMBIGUITY RATE (shape): {res['overall']['AMBIGUITY_RATE_shape']:.4f}")
    print("collisions:")
    seen = set()
    for r in rows:
        k = tuple(r["shape_peers"])
        if len(k) > 1 and k not in seen:
            seen.add(k)
            print(f"   {r['shape']:24} -> {list(k)}")


if __name__ == "__main__":
    main()
