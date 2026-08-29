"""Part D — migrate the existing registry into the authority, and REPORT.

THIS SCRIPT FIXES NOTHING. A migration that becomes a refactor stops being a
migration, and the interesting number here is precisely how much of the current
registry would NOT pass its own new standard. Fabricating an attestation or a
frame to make an entry migrate would destroy the measurement.

Where a required field does not exist on the old record, the entry is reported
UNMIGRATABLE with the field named. Where the field exists but the entry would
be REFUSED by (i), (ii) or (iii), it is reported REFUSED with the condition
named. Those are different outcomes and are counted separately.

    ~/dev/marshal/.os/bin/python research/spec_authority/migrate.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from gyza.containment.invariants import InvariantClass          # noqa: E402
from gyza.verification.adapters import (                        # noqa: E402
    HUMAN_SPECS, NATIVE, NO_VERIFIER,
)
from gyza.verification.authority import (                       # noqa: E402
    Attestation, NotApplicable, SpecAuthority, SpecRecord, SpecRefused,
    check_carrier_claim, check_frame_requirement, check_witness_resolves,
)

# Fields the OLD records simply do not have. Named once, here, so the report
# distinguishes "this entry is bad" from "this schema never had the field".
VERIFIER_MISSING_FIELDS = ("attestation", "success_condition", "frame",
                           "obligations", "invariant_class")
SPEC_MISSING_FIELDS = ("carrier", "success_condition", "frame", "obligations",
                       "witness", "version")


def main() -> None:
    rows = []

    # ---- native verifiers -------------------------------------------------
    for v in NATIVE:
        r = {"claim_type": v.claim_type, "source": "NATIVE",
             "declared_carrier": v.carrier, "witness": v.witness}
        r["missing_fields"] = list(VERIFIER_MISSING_FIELDS)
        r["carrier_screen"] = check_carrier_claim(v.fn, v.carrier)
        r["frame_screen"] = check_frame_requirement(
            v.fn, NotApplicable("old schema has no frame field"))
        r["witness_screen"] = check_witness_resolves(v.witness)
        rows.append(r)

    # ---- human partial specs ---------------------------------------------
    for s in HUMAN_SPECS:
        r = {"claim_type": s.claim_type, "source": "HUMAN_SPECS",
             "declared_carrier": "SPEC", "witness": None}
        r["missing_fields"] = list(SPEC_MISSING_FIELDS)
        r["carrier_screen"] = check_carrier_claim(s.fn, "SPEC")
        r["frame_screen"] = check_frame_requirement(
            s.fn, NotApplicable("old schema has no frame field"))
        r["witness_screen"] = None
        rows.append(r)

    # ---- what would be REFUSED if submitted fresh -------------------------
    for r in rows:
        conds = []
        # (i) -- no old record carries a KEY_BOUND attestation, and Verifier
        # carries no authorship field at all.
        if r["source"] == "NATIVE":
            conds.append("(i) no authorship field on Verifier at all")
        if not r["carrier_screen"].no_declared_evidence:
            conds.append("(ii) " + r["carrier_screen"].detail)
        if not r["frame_screen"].no_declared_evidence:
            conds.append("(iii) " + r["frame_screen"].detail)
        r["refused_by"] = conds

    # ---- attempt an actual registration for the ones that could ----------
    # Only HUMAN_SPECS carry an attestation, so only they are even candidates.
    auth = SpecAuthority()
    migrated, failed = [], []
    for s, r in zip(HUMAN_SPECS, [x for x in rows if x["source"] == "HUMAN_SPECS"]):
        if r["refused_by"]:
            failed.append((s.claim_type, r["refused_by"]))
            continue
        try:
            auth.register(SpecRecord(
                claim_type=s.claim_type,
                # The old record's `rationale` is the closest thing to a stated
                # success condition. Reused, not invented -- and flagged, because
                # a rationale explains WHY a spec exists and a success condition
                # says WHAT must hold. They are not the same field.
                success_condition=f"[MIGRATED FROM rationale] {s.rationale}",
                fn=s.fn,
                carrier="SPEC",
                invariant_class=s.cls,
                attestation=Attestation(s.authored_by, "SELF_ASSERTED",
                                    "[MIGRATION DRY RUN] old PartialSpec.human_attested boolean"),
                frame=NotApplicable(
                    "migration: old schema had no frame field; NOT verified as "
                    "immutable, only unexamined"),
                obligations=frozenset({f"migrated:{s.claim_type}"}),
                version=1,
                witness="[MIGRATED] PartialSpec had no witness field",
            ))
            migrated.append(s.claim_type)
        except SpecRefused as e:
            failed.append((s.claim_type, [f"{type(e).__name__}: {e}"]))

    # ---- report -----------------------------------------------------------
    n_native, n_specs = len(NATIVE), len(HUMAN_SPECS)
    print("=" * 74)
    print("PART D -- MIGRATION REPORT (nothing was fixed)")
    print("=" * 74)
    print(f"  existing entries: {n_native} NATIVE + {n_specs} HUMAN_SPECS "
          f"+ {len(NO_VERIFIER)} NO_VERIFIER = {n_native + n_specs + len(NO_VERIFIER)}")

    print(f"\n  UNMIGRATABLE without inventing a field:")
    print(f"    NATIVE      {n_native}/{n_native}  missing {VERIFIER_MISSING_FIELDS}")
    print(f"    HUMAN_SPECS {n_specs}/{n_specs}  missing {SPEC_MISSING_FIELDS}")

    refused = [r for r in rows if r["refused_by"]]
    print(f"\n  WOULD BE REFUSED IF SUBMITTED FRESH: {len(refused)}/{len(rows)}"
          f" = {len(refused)/len(rows):.4f}")
    by_cond = Counter(c.split()[0] for r in refused for c in r["refused_by"])
    for cond, k in sorted(by_cond.items()):
        print(f"    {cond}  {k}")
    for r in refused:
        for c in r["refused_by"]:
            print(f"      {r['claim_type']:<32} {c}")

    print(f"\n  ACTUALLY MIGRATED (attestation present, screens pass): "
          f"{len(migrated)}/{n_specs}  {migrated}")
    for ct, why in failed:
        print(f"    FAILED {ct}: {why}")

    bad_w = [r for r in rows if r["witness_screen"] is not None
             and not r["witness_screen"].no_declared_evidence]
    print(f"\n  WITNESS CITATIONS THAT DO NOT RESOLVE: {len(bad_w)}/{n_native}")
    for r in bad_w:
        print(f"    {r['claim_type']:<32} {r['witness_screen'].detail}")

    out = {
        "counts": {"native": n_native, "human_specs": n_specs,
                   "no_verifier": len(NO_VERIFIER),
                   "unmigratable": len(rows),
                   "would_be_refused": len(refused),
                   "migrated": len(migrated),
                   "unresolved_witnesses": len(bad_w)},
        "refused_by_condition": dict(by_cond),
        "entries": [{"claim_type": r["claim_type"], "source": r["source"],
                     "declared_carrier": r["declared_carrier"],
                     "missing_fields": r["missing_fields"],
                     "refused_by": r["refused_by"],
                     "carrier_detail": r["carrier_screen"].detail,
                     "frame_detail": r["frame_screen"].detail,
                     "witness_detail": (r["witness_screen"].detail
                                        if r["witness_screen"] else None)}
                    for r in rows],
        "migrated": migrated,
    }
    (HERE / "migration.json").write_text(json.dumps(out, indent=1))
    print(f"\nwrote {HERE / 'migration.json'}")


if __name__ == "__main__":
    main()
