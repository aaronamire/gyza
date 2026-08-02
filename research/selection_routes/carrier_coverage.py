"""
Part A — carrier coverage and EXPECTED CHAIN TIER by depth.

Pure arithmetic over the V-1/V-4 registry. Deterministic, zero model calls.

SR-3 established that composition is governed by the CARRIER, not the tier.
Phase 3 surfaced the consequence and left it unquantified: a claim's tier is a
property of that claim IN ISOLATION, so the coverage fraction is NOT a
composition budget. This computes what it actually costs.

Everything here is ANALYTIC, not measured: it follows from the TIER_ALGEBRA
rules plus the registry's composition. Labelled as such throughout -- a
definitional cell illustrates, it does not confirm.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gyza.verification.adapters import NO_VERIFIER, build_registries  # noqa: E402

SEED = 1
DEPTHS = (1, 2, 4, 8)


def inventory() -> list[dict]:
    """The 18 claim types with tier AND carrier, each citing its witness."""
    v, s = build_registries()
    rows = []
    for ct in v.claim_types():
        ver = v.get(ct)
        rows.append({"claim_type": ct, "tier": 1, "carrier": ver.carrier,
                     "witness": ver.witness})
    for ct in s.claim_types():
        sp = s.get(ct)
        rows.append({"claim_type": ct, "tier": 2, "carrier": "SPEC",
                     "witness": f"human-authored ({sp.authored_by})"})
    for ct in NO_VERIFIER:
        rows.append({"claim_type": ct, "tier": 3, "carrier": "NONE",
                     "witness": "no verifier — semantic (competence bound)"})
    return rows


def chain_tiers(rows: list[dict], depth: int) -> dict:
    """Fraction of UNIFORMLY-SAMPLED chains of `depth` stages landing in each
    tier, under the TIER_ALGEBRA rules:
        any TEST-carried stage -> tier 3
        any tier-3 stage       -> tier 3
        otherwise              -> min(input tiers)

    UNIFORM SAMPLING IS AN ASSUMPTION and is the main thing that could be
    wrong: real chains are not drawn uniformly from the vocabulary. It is stated
    rather than hidden because every number below inherits it.
    """
    n = len(rows)
    p_proof1 = sum(1 for r in rows if r["carrier"] == "PROOF" and r["tier"] == 1) / n
    p_spec = sum(1 for r in rows if r["carrier"] == "SPEC") / n
    p_test = sum(1 for r in rows if r["carrier"] == "TEST") / n
    p_none = sum(1 for r in rows if r["carrier"] == "NONE") / n

    tier1 = p_proof1 ** depth
    preserving = (p_proof1 + p_spec) ** depth        # no TEST, no tier-3
    tier2 = preserving - tier1
    tier3 = 1.0 - preserving
    return {"depth": depth,
            "tier_1": round(tier1, 6), "tier_2": round(tier2, 6),
            "tier_3": round(tier3, 6),
            "any_correctness_claim": round(preserving, 6),
            "_p": {"proof_t1": round(p_proof1, 6), "spec": round(p_spec, 6),
                   "test": round(p_test, 6), "none": round(p_none, 6)}}


def ceiling_after_upgrades(rows: list[dict], depth: int) -> float:
    """HARD CEILING. Upgrade every TEST and every SPEC type to PROOF; the four
    semantic types cannot be upgraded at all (competence bound, terminal). This
    is the best tier-1 chain fraction any representation work could buy."""
    n = len(rows)
    upgradable = sum(1 for r in rows if r["carrier"] in ("PROOF", "SPEC", "TEST"))
    return round((upgradable / n) ** depth, 6)


def main() -> None:
    rows = inventory()
    by_carrier: dict[str, int] = {}
    for r in rows:
        by_carrier[r["carrier"]] = by_carrier.get(r["carrier"], 0) + 1
    n = len(rows)

    isolated = {"n": n,
                "tier_1": sum(1 for r in rows if r["tier"] == 1),
                "fraction_tier_1": round(
                    sum(1 for r in rows if r["tier"] == 1) / n, 4),
                "by_carrier": by_carrier,
                "fraction_by_carrier": {k: round(v / n, 4)
                                        for k, v in by_carrier.items()}}

    chains = [chain_tiers(rows, d) for d in DEPTHS]
    ceilings = {d: ceiling_after_upgrades(rows, d) for d in DEPTHS}

    out = {"seed": SEED, "status": "ANALYTIC (definitional, not measured)",
           "assumption": "chains sampled uniformly from the claim vocabulary",
           "inventory": rows, "isolated": isolated, "chains": chains,
           "tier1_ceiling_after_all_possible_upgrades": ceilings}
    Path(__file__).with_name("carrier_coverage.json").write_text(
        json.dumps(out, indent=1))

    print(f"{'claim type':32} {'tier':>4} {'carrier':>8}  witness")
    print("-" * 96)
    for r in rows:
        print(f"{r['claim_type']:32} {r['tier']:>4} {r['carrier']:>8}  {r['witness']}")
    print()
    print(f"ISOLATED: {isolated['fraction_tier_1']:.1%} tier-1 "
          f"({isolated['tier_1']}/{n}); carriers {isolated['by_carrier']}")
    print()
    print(f"{'depth':>6} {'tier-1':>9} {'tier-2':>9} {'tier-3':>9} "
          f"{'any claim':>10} {'t1 ceiling':>11}")
    for c in chains:
        print(f"{c['depth']:>6} {c['tier_1']:>9.4f} {c['tier_2']:>9.4f} "
              f"{c['tier_3']:>9.4f} {c['any_correctness_claim']:>10.4f} "
              f"{ceilings[c['depth']]:>11.4f}")


if __name__ == "__main__":
    main()
