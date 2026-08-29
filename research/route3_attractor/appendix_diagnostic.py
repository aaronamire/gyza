"""
Exploratory, post-hoc GATE-B diagnostic + Phase D on the 22 attractor items.
Zero-cost (cache only). NOT preregistered-confirmatory; see
FINDINGS_ROUTE3_APPENDIX.md. Reproduces every number in that appendix.
"""
from __future__ import annotations
import sys
from collections import Counter
import numpy as np
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import route3_experiment as R3


def run():
    items = R3.load_items()
    A = R3.assemble(items)
    gb = R3.gate_b(A)
    card = {c["q"]: c for c in A["cardinality"]}
    valid = gb["valid_idx"]
    attr = [q for q in valid if card[q]["attractor_hits"] >= 3]
    sigs, atok, det = A["sigs"], A["attractor_tok"], A["det_agents"]

    print("valid", len(valid), "attractor(>=3)", len(attr))
    print("1a density: 22-item %.2f | 72-item %.2f" % (
        np.mean([card[q]["m_wrong"] for q in attr]),
        np.mean([card[q]["m_wrong"] for q in valid])))
    for cat in ("ii_noop", "i_classic", "iii_substitution"):
        qs = [q for q in valid if card[q]["category"] == cat]
        y = sum(1 for q in qs if card[q]["attractor_hits"] >= 3)
        print(f"1b {cat}: {y}/{len(qs)} yield={y/len(qs):.0%} density={np.mean([card[q]['m_wrong'] for q in qs]):.2f}")
    span = [len({det[a][0] for a in range(12)
                 if sigs[a][q] == [atok[q]] and not R3.is_non_answer(sigs[a][q])}) for q in attr]
    print("1c >=2 distinct models:", sum(1 for s in span if s >= 2), "/22; single-model:",
          sum(1 for s in span if s == 1), "/22")

    d = R3.phase_d(A, valid)
    print("2 escape:", {k: round(v, 3) for k, v in d["escape_rate_by_method"].items()})
    prim = d["discriminator"]["COT_x_DECOMP_primary"]
    print("  McNemar DECOMP-vs-COT:", prim["mcnemar_DECOMP_vs_COT"])
    print("  held-out lift COT×DECOMP:", prim["heldout_lift"]["lift_vs_mean_item_ci"])
    print("  McNemar CODE-vs-COT:", d["discriminator"]["COT_x_CODE"]["mcnemar_CODE_vs_COT"])
    phi = R3._det_index(3, 0)
    nq = [q for q in valid if card[q]["category"] == "ii_noop"]
    print("3 phi-4 COT NoOp hits:", sum(1 for q in nq if sigs[phi][q] == [atok[q]]), "/", len(nq))


if __name__ == "__main__":
    run()
