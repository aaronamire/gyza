"""Part A — reversibility coverage over the action vocabulary.

WHAT THIS MEASURES, AND THE ONE THING IT CANNOT. The architecture rests on
"reversible actions need not be verified before acting", which makes the
reversible FRACTION the load-bearing number. That fraction has never been
computed. It is computed here two ways, because the two disagree and the
disagreement is the finding:

  BY ACTION TYPE        how many KINDS of action are reversible
  BY PRODUCTION CALL SITE   how much of what actually RUNS is reversible

WHAT IT CANNOT DO: decide whether the declared classification is CORRECT. The
table at `gyza/containment/reversibility.py:30` is a declaration, and
`StagingArea.stage` refuses to stage anything the table does not call
REVERSIBLE_INTERIOR (staging.py:83-88). So rollback-reachability agrees with the
class BY CONSTRUCTION and confirms nothing about the underlying property. That
is reported as DEFINITIONAL rather than presented as corroboration.

FALSE-MATCH HANDLING. Several action-type strings collide with unrelated code --
`"read"` is a capability-manifest key (`fs.get("read")`), `"sign_envelope"`
appears in `gyza/icp.py`'s `__all__`. Every exclusion is listed in
`_FALSE_MATCHES` and REPORTED, so the filtering is auditable rather than a
silent adjustment.

    ~/dev/marshal/.os/bin/python research/reversibility/measure.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from gyza.containment.reversibility import (                    # noqa: E402
    Reversibility, ReversibilityTable,
)

# (file, reason) pairs whose hits are NOT action-type tags. Verified by reading
# each site; listed so the exclusion is auditable.
_FALSE_MATCHES = {
    "gyza/identity.py": 'fs.get("read") — a capability-manifest key',
    "gyza/sandbox/config.py": 'fs.get("read") — a capability-manifest key',
    "gyza/cli.py": 'fs.get("read") — a capability-manifest key',
    "gyza/economy/delegation.py": 'fs.get("read") — a capability-manifest key',
    "gyza/icp.py": '"sign_envelope" in __all__ — an export name',
    "gyza/containment/reversibility.py": "the table itself",
}

# Where each action's effect lands. Authored from reading the code, and the
# citation is given so it can be checked rather than believed.
_STORAGE = {
    "read":              ("none", "a pure read; no write at all"),
    "compute":           ("none", "no write at all"),
    "retrieve_memory":   ("none", "a query over the memory store"),
    "stage_artifact":    ("append-only", "StagingArea.stage -> AppendOnlyLog.append (staging.py:89)"),
    "stage_envelope":    ("append-only", "StagingArea.stage -> AppendOnlyLog.append (staging.py:89)"),
    "claim_work_item":   ("append-only", "staged; blackboard claim log"),
    "reserve_credits":   ("append-only", "a hold, released; ReservationBook"),
    "sign_envelope":     ("append-only", "envelope log; non-repudiable once made"),
    "settle_credits":    ("append-only", "LedgerEntry — ledger.py:30 'no update_entry'"),
    "grant_delegation":  ("append-only", "delegation chain hop"),
    "delete_artifact":   ("mutable", "removes content with no retained copy"),
    "rotate_key":        ("mutable", "supersedes the prior key"),
    "update_guard_config": ("mutable", "replaces the guard configuration"),
    "publish_agent":     ("external", "leaves modelled state (C15)"),
    "send_message":      ("external", "leaves modelled state (C15)"),
    "publish_delta":     ("external", "leaves modelled state (C15)"),
    "publish_attestation": ("external", "leaves modelled state (C15)"),
    "external_send":     ("external", "leaves modelled state (C15)"),
    "write_outside_sandbox": ("external", "leaves modelled state (C15)"),
}


def call_sites(action: str) -> dict[str, list[str]]:
    """Literal occurrences of the action-type tag, partitioned by tree area."""
    out = subprocess.run(
        ["grep", "-rn", "--include=*.py", f'"{action}"', str(ROOT)],
        capture_output=True, text=True).stdout
    buckets: dict[str, list[str]] = {"production": [], "test": [],
                                     "research": [], "excluded": []}
    for line in out.splitlines():
        rel = line.split(":", 1)[0].replace(str(ROOT) + "/", "")
        if "__pycache__" in rel:
            continue
        if rel in _FALSE_MATCHES:
            buckets["excluded"].append(rel)
        elif rel.startswith("gyza/"):
            buckets["production"].append(rel)
        elif rel.startswith("tests/"):
            buckets["test"].append(rel)
        elif rel.startswith("research/"):
            buckets["research"].append(rel)
    return buckets


def main() -> None:
    t = ReversibilityTable()
    vocab = t.vocabulary
    rows = []
    for a in vocab:
        cs = call_sites(a)
        storage, why = _STORAGE.get(a, ("UNDETERMINED", "not classified"))
        cls = t.classify(a)
        rows.append({
            "action": a, "class": cls.value, "storage": storage,
            "storage_basis": why,
            "n_production": len(cs["production"]),
            "n_test": len(cs["test"]), "n_research": len(cs["research"]),
            "production_sites": sorted(set(cs["production"])),
            "excluded_sites": sorted(set(cs["excluded"])),
            # Rollback reaches an action iff StagingArea.stage would accept it,
            # and stage() accepts exactly REVERSIBLE_INTERIOR. DEFINITIONAL.
            "rollback_reachable": cls is Reversibility.REVERSIBLE_INTERIOR,
        })

    n = len(rows)
    by_class: dict[str, list[dict]] = {}
    for r in rows:
        by_class.setdefault(r["class"], []).append(r)

    print("=" * 78)
    print(f"A1/A2 — ACTION VOCABULARY: {n} types, declared at "
          f"gyza/containment/reversibility.py:30")
    print("=" * 78)
    print(f"  {'action':<24}{'class':<22}{'storage':<13}{'prod':>5}{'test':>6}{'res':>5}")
    for r in rows:
        print(f"  {r['action']:<24}{r['class']:<22}{r['storage']:<13}"
              f"{r['n_production']:>5}{r['n_test']:>6}{r['n_research']:>5}")

    print("\n" + "=" * 78)
    print("A4 — COVERAGE, BOTH WEIGHTINGS")
    print("=" * 78)
    tot_prod = sum(r["n_production"] for r in rows)
    print(f"  {'class':<24}{'types':>7}{'frac':>9}{'prod sites':>12}{'frac':>9}")
    for cls in ("REVERSIBLE_INTERIOR", "IRREVERSIBLE", "EGRESS"):
        g = by_class.get(cls, [])
        p = sum(r["n_production"] for r in g)
        print(f"  {cls:<24}{len(g):>7}{len(g)/n:>9.4f}{p:>12}"
              f"{(p/tot_prod if tot_prod else float('nan')):>9.4f}")
    print(f"  {'TOTAL':<24}{n:>7}{1.0:>9.4f}{tot_prod:>12}")
    print(f"\n  UNDETERMINED: {sum(1 for r in rows if r['storage']=='UNDETERMINED')} "
          f"(reported separately from IRREVERSIBLE by design)")

    print("\n" + "=" * 78)
    print("A3 — APPEND-ONLY / ROLLBACK-REACHABILITY SPLIT")
    print("=" * 78)
    ao_reach = [r for r in rows if r["storage"] == "append-only" and r["rollback_reachable"]]
    ao_not = [r for r in rows if r["storage"] == "append-only" and not r["rollback_reachable"]]
    mut = [r for r in rows if r["storage"] == "mutable"]
    ext = [r for r in rows if r["storage"] == "external"]
    none_ = [r for r in rows if r["storage"] == "none"]
    for label, g in (("append-only AND rollback-reachable", ao_reach),
                     ("append-only but NOT reachable", ao_not),
                     ("mutable", mut), ("external (egress)", ext),
                     ("no write at all", none_)):
        print(f"  {label:<38}{len(g):>3}  {[x['action'] for x in g]}")

    print("\n" + "=" * 78)
    print("EXCLUDED FALSE MATCHES (auditable, not silent)")
    print("=" * 78)
    for f, why in sorted(_FALSE_MATCHES.items()):
        print(f"  {f:<40} {why}")

    (HERE / "coverage.json").write_text(json.dumps({
        "n_action_types": n,
        "by_type": {c: len(g) for c, g in by_class.items()},
        "by_type_fraction": {c: round(len(g)/n, 4) for c, g in by_class.items()},
        "total_production_sites": tot_prod,
        "by_production_sites": {c: sum(r["n_production"] for r in g)
                                for c, g in by_class.items()},
        "append_only_rollback_reachable": [r["action"] for r in ao_reach],
        "append_only_not_reachable": [r["action"] for r in ao_not],
        "mutable": [r["action"] for r in mut],
        "external": [r["action"] for r in ext],
        "no_write": [r["action"] for r in none_],
        "rows": rows,
    }, indent=1))
    print(f"\nwrote {HERE / 'coverage.json'}")


if __name__ == "__main__":
    main()
