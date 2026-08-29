"""Part E — the verification gate.

E1 REQUIRES VERIFYING AGAINST THE ORIGINAL SOURCE, NOT AGAINST THE EXTRACTION.
So this deliberately does NOT re-run the extractor's query. Extraction read the
REST check-runs endpoint (`repos/{r}/commits/{sha}/check-runs`) and applied its
own any-failure rule. Verification reads GitHub's **GraphQL
`statusCheckRollup`** -- a different endpoint, a different data model, and the
aggregate GitHub's own UI displays, which folds in the legacy commit-status API
that the extractor never saw. Re-running the same query would compare a parser
with itself and would pass by construction.

E4: every verdict comparison goes through `gyza.canon.values_equal`. Artifact
#15's species (comparing representations instead of values) has recurred three
times, most recently in the session that wrote the rule down.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from gyza.canon import values_equal          # noqa: E402

N_SAMPLE = 45
GATE = 0.95

_Q = """
query($owner:String!,$name:String!,$oid:GitObjectID!){
  repository(owner:$owner,name:$name){
    object(oid:$oid){ ... on Commit {
      statusCheckRollup { state contexts(first:100){ nodes {
        ... on CheckRun { name conclusion }
        ... on StatusContext { context state } } } } } } } }
"""


def rollup(repo: str, sha: str):
    owner, name = repo.split("/")
    for attempt in range(4):
        r = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={_Q}",
             "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"oid={sha}"],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            try:
                d = json.loads(r.stdout)
            except json.JSONDecodeError:
                time.sleep(2 * (attempt + 1)); continue
            obj = ((d.get("data") or {}).get("repository") or {}).get("object")
            if obj is None:
                return None, "commit not reachable (fork deleted / GC'd)"
            rl = obj.get("statusCheckRollup")
            if rl is None:
                return None, "no rollup on this commit"
            return rl, None
        time.sleep(2 * (attempt + 1))
    return None, "graphql failed after retries"


def source_verdict(rl):
    """What the SOURCE says, mapped to the corpus vocabulary."""
    st = rl.get("state")
    if st == "SUCCESS":
        return "PASS"
    if st in ("FAILURE", "ERROR"):
        return "FAIL"
    return f"OTHER:{st}"


def main():
    recs = json.loads((HERE / "decompositions.json").read_text())["records"]
    rng = random.Random(11)
    sample = rng.sample(recs, min(N_SAMPLE, len(recs)))

    agree = 0
    checked = 0
    disagreements = []
    unresolvable = []
    for r in sample:
        rl, err = rollup(r["repo"], r["outcome_source"]["tree_state"])
        if rl is None:
            # AN ERROR IS NOT A VALUE: an unresolvable record is excluded from
            # the denominator and reported separately -- never scored as a
            # disagreement (which would understate) or an agreement (overstate).
            unresolvable.append({"record_id": r["record_id"], "reason": err})
            continue
        checked += 1
        src = source_verdict(rl)
        if values_equal(r["outcome"], src):
            agree += 1
        else:
            ctx = rl.get("contexts", {}).get("nodes", [])
            disagreements.append({
                "record_id": r["record_id"],
                "recorded": r["outcome"],
                "source_says": src,
                "rollup_state": rl.get("state"),
                "n_check_runs": sum(1 for c in ctx if "conclusion" in c),
                "n_legacy_statuses": sum(1 for c in ctx if "context" in c),
                "legacy_status_states": sorted({c.get("state") for c in ctx
                                                if "context" in c}),
                "check_run_conclusions": sorted({c.get("conclusion") for c in ctx
                                                 if "conclusion" in c}),
            })
    res = {
        "n_sampled": len(sample),
        "n_checked": checked,
        "n_unresolvable_excluded": len(unresolvable),
        "unresolvable": unresolvable,
        "agreement": round(agree / checked, 4) if checked else None,
        "gate": GATE,
        "gate_pass": bool(checked and agree / checked >= GATE),
        "verification_source": "GraphQL statusCheckRollup (DIFFERENT endpoint "
                               "from extraction's REST check-runs)",
        "disagreements": disagreements,
    }
    (HERE / "corpus_verification.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items()
                      if k not in ("disagreements", "unresolvable")}, indent=1))
    print(f"\ndisagreements ({len(disagreements)}):")
    for d in disagreements:
        print(" ", json.dumps(d))


if __name__ == "__main__":
    main()
