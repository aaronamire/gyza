"""3.C -- the convertibility census. AUTHORED classification, mechanical tabulation.

MECHANICAL: the tabulation, the shares, the partition arithmetic, the sampling.
AUTHORED: every verdict below. The authority test narrows the choice; it does
not remove it. Each carries basis `i` (inspection) or `j` (judgement).

THE AUTHORITY TEST (frozen in PREREGISTRATION_3C.md 2):
  (i)   P is inside the system
  (ii)  P's saying-so MAKES C true rather than REPORTS that C is true
  (iii) P's entitlement is established by something the system holds

Zero credits. No model call.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

# Census speech acts (research/census/census.py, registered reading).
ACT = {
    "envelope_signature": "L", "envelope_chain": "L", "envelope_dag": "L",
    "manifest_identity": "L", "enforcement_within_manifest": "D",
    "delegation_attenuation": "L", "ledger_entry_signatures": "L",
    "balance_fold": "A", "market_capital_fold": "A",
    "artifact_content_address": "L", "unit_test_execution": "A",
    "memory_retrieval_relevance": "A", "external_send_content": "A",
    "hlc_ordering": "L", "reputation_score": "L",
    "work_claim_exclusivity": "L", "execution_output_content": "A",
    "routing_match_quality": "A",
}

# C1 partition: does the claim concern state Gyza CONSTITUTES, or state it
# OBSERVES? Assigned from what the claim's referent IS, not from its verifier.
PARTITION = {
    "envelope_signature": "constituted", "envelope_chain": "constituted",
    "envelope_dag": "constituted", "manifest_identity": "constituted",
    "enforcement_within_manifest": "constituted",
    "delegation_attenuation": "constituted",
    "ledger_entry_signatures": "constituted", "balance_fold": "constituted",
    "market_capital_fold": "constituted",
    "artifact_content_address": "constituted", "hlc_ordering": "constituted",
    "reputation_score": "constituted", "work_claim_exclusivity": "constituted",
    # OBSERVED -- the referent lives outside what Gyza constitutes
    "unit_test_execution": "observed",          # behaviour of code under test
    "memory_retrieval_relevance": "observed",   # whether nearness IS relevance
    "external_send_content": "observed",        # the bytes' fate after emission
    "execution_output_content": "observed",     # the model's output correctness
    "routing_match_quality": "observed",        # a counterfactual over handlers
}

# The authority test applied to every ASSERTIVE type. (verdict, basis, party,
# what_is_lost, reason)
ASSERTIVE_VERDICTS = {
    "balance_fold": (
        "NOT-(ii)", "j", None,
        "n/a -- not convertible",
        "The balance is a FOLD over entries that already exist. Declaring "
        "'the balance is hereby B' is infelicitous the moment the fold "
        "disagrees, which means the FOLD determines truth, not the saying. "
        "Its CONSTITUENTS are declarative -- each signed LedgerEntry "
        "constitutes a transfer -- but A FOLD OVER DECLARATIVES IS NOT ITSELF "
        "A DECLARATIVE."),
    "market_capital_fold": (
        "NOT-(ii)", "j", None,
        "n/a",
        "Identical structure post-H2: an append-only CapitalEntry fold. Same "
        "reason as balance_fold."),
    "unit_test_execution": (
        "NOT-(ii)", "i", None,
        "n/a",
        "Declaring a function passes does not make a failing function pass. "
        "Execution determines it."),
    "memory_retrieval_relevance": (
        "NOT-(ii)", "j", None,
        "The only felicitous declaration available -- 'these are hereby the "
        "returned set' -- is trivially true and answers nothing the caller "
        "asked. RULE 3d: abandonment, not conversion.",
        "The respecified form RECOMPUTES a ranking over a corpus that exists "
        "independently of the saying. That is correspondence to a computed "
        "fact."),
    "external_send_content": (
        "NOT-(ii)", "j", None,
        "The convertible FRAGMENT -- 'these bytes are hereby bound to hash H' "
        "-- is a different, weaker claim, and it is ALREADY factored out as "
        "artifact_content_address (DECLARATIVE). What remains is 'the RIGHT "
        "content was sent', which the respecification already recorded as lost.",
        "After emission the bytes leave the system (C15). Gyza cannot "
        "constitute anything about what happens to them."),
    "execution_output_content": (
        "NOT-(ii)+(iii)", "i", None,
        "n/a",
        "Correctness is fixed by the task's semantics, not by declaration -- "
        "fails (ii). AND fails (iii): no party inside is ENTITLED to declare "
        "an output correct. That entitlement sits with the human principal who "
        "stated the intent, which is outside the system."),
    "routing_match_quality": (
        "NOT-(ii)", "j", None,
        "n/a",
        "The system CAN constitute an assignment ('this item is hereby "
        "assigned to H') -- but that is a DIFFERENT claim. Match QUALITY "
        "reports a counterfactual about which handler would have succeeded. "
        "NOTE: this failure is DISTINCT from its exogeneity -- (ii) is about "
        "the SPEECH ACT, exogeneity about WHERE THE TRUTH CONDITION LIVES. "
        "balance_fold fails (ii) while being fully INTERNAL, so the two are "
        "independent."),
}


def main() -> None:
    print("=" * 76)
    print("B1/B2 -- CONVERTIBILITY OF THE ASSERTIVE REMAINDER")
    print("=" * 76)
    assertives = [t for t, a in ACT.items() if a == "A"]
    conv = [t for t in assertives if ASSERTIVE_VERDICTS[t][0] == "CONVERTIBLE"]
    print(f"  assertive types      : {len(assertives)}")
    print(f"  CONVERTIBLE          : {len(conv)}  {conv}")
    for t in assertives:
        v, b, _p, lost, _r = ASSERTIVE_VERDICTS[t]
        print(f"    {t:30} {v:16} [{b}]")

    n = len(ACT)
    decl_now = sum(1 for a in ACT.values() if a == "L")
    decl_max = decl_now + len(conv)
    print(f"\n  declarative share NOW        : {decl_now}/{n} = {decl_now/n:.4f}")
    print(f"  hypothetical MAX with standing: {decl_max}/{n} = {decl_max/n:.4f}")
    print(f"  >>> DELTA                    : +{(decl_max-decl_now)/n:.4f}")

    print("\n" + "=" * 76)
    print("C1 -- CONSTITUTED vs OBSERVED")
    print("=" * 76)
    for part in ("constituted", "observed"):
        ts = [t for t in ACT if PARTITION[t] == part]
        d = sum(1 for t in ts if ACT[t] == "L")
        a = sum(1 for t in ts if ACT[t] == "A")
        c = sum(1 for t in ts if t in conv)
        print(f"  {part:12} n={len(ts):2}  DECLARATIVE {d:2} ({d/len(ts):.4f})"
              f"  assertive {a:2}  convertible {c}")

    b = Counter(v[1] for v in ASSERTIVE_VERDICTS.values())
    print(f"\n  judgement fraction (assertive verdicts): "
          f"{b['j']}/{len(assertives)} = {b['j']/len(assertives):.4f}")

    # ---- B3: the external corpus ----
    print("\n" + "=" * 76)
    print("B3 -- EXTERNAL CORPUS (the falsifier)")
    print("=" * 76)
    claims = json.loads((ROOT / "research/claims_corpus/claims_hand.json").read_text())
    import random
    random.Random(1).shuffle(claims)
    sample = claims[:30]
    # A reporter is OUTSIDE the system they report on. (i) fails for every claim
    # about the project's software; (iii) fails for every claim regardless,
    # since GitHub confers no entitlement to constitute facts about the code.
    # HAND-CHECKED, and the crude heuristic's one hit was a FALSE POSITIVE:
    # scikit-learn#34075-2 "MY HUNCH would be to..." matched a `"my "` prefix
    # test but is a hedged PROPOSAL, not a claim about the reporter's own
    # artifact. Corrected to 0 by inspection, not by tuning the rule -- the
    # rule was a screen, the hand-check is the measurement.
    #
    # The test fails at (i) for every claim in this corpus: a GitHub issue
    # reporter is BY DEFINITION outside the software they report on. GitHub
    # confers standing to FILE, never to CONSTITUTE facts about the code.
    convertible_ext: list[str] = []
    print(f"  sample                 : {len(sample)} (SEED=1)")
    print(f"  CONVERTIBLE            : {len(convertible_ext)} {convertible_ext}")
    print(f"  convertible fraction   : {len(convertible_ext)/len(sample):.4f}")

    json.dump({
        "assertive": len(assertives), "convertible": len(conv),
        "decl_now": decl_now, "decl_max": decl_max, "n": n,
        "decl_share_now": decl_now / n, "decl_share_max": decl_max / n,
        "constituted_decl_share": sum(
            1 for t in ACT if PARTITION[t] == "constituted" and ACT[t] == "L"
        ) / sum(1 for t in ACT if PARTITION[t] == "constituted"),
        "observed_decl_share": sum(
            1 for t in ACT if PARTITION[t] == "observed" and ACT[t] == "L"
        ) / sum(1 for t in ACT if PARTITION[t] == "observed"),
        "external_convertible": len(convertible_ext),
        "external_sample": len(sample),
        "judgement_fraction": b["j"] / len(assertives),
    }, open(HERE / "convertibility_result.json", "w"), indent=1)


if __name__ == "__main__":
    main()
