"""Fetch outcome signals for the 82 sampled issues. Zero credits: `gh api` only.

NOTHING IS FILTERED. Every issue in the frozen sample is fetched, including
never-triaged ones with no events at all -- excluding those would select for
claims that got attention, which correlates with being checkable.

Recorded per issue: state, state_reason, created_at, closed_at, and every
timeline event that could carry a discriminating signal (merged-PR
cross-references, closing commits).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def api(path: str):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def main() -> None:
    claims = json.loads((ROOT / "research/claims_corpus/claims_hand.json").read_text())
    raw = {(x["repo"], x["number"]): x
           for x in json.loads((ROOT / "research/claims_corpus/issues_raw.json").read_text())}
    issues = sorted({(c["repo"], c["issue"]) for c in claims})
    print(f"issues to fetch: {len(issues)}", file=sys.stderr)

    out = {}
    for n, (repo, num) in enumerate(issues, 1):
        tl = api(f"repos/{repo}/issues/{num}/timeline?per_page=100")
        meta = raw[(repo, num)]
        rec = {
            "repo": repo, "number": num,
            "state": meta["state"], "state_reason": meta["state_reason"],
            "created_at": meta["created_at"], "closed_at": meta["closed_at"],
            "fetch_ok": tl is not None,
            "closing_commits": [], "merged_prs": [], "linked_prs_unmerged": [],
            "n_events": 0,
        }
        for e in (tl or []):
            rec["n_events"] += 1
            ev = e.get("event")
            if ev == "closed" and e.get("commit_id"):
                rec["closing_commits"].append(
                    {"sha": e["commit_id"], "at": e.get("created_at")})
            if ev in ("cross-referenced", "referenced"):
                src = (e.get("source") or {}).get("issue") or {}
                pr = src.get("pull_request")
                if pr is not None:
                    entry = {"num": src.get("number"), "at": e.get("created_at"),
                             "merged_at": pr.get("merged_at")}
                    (rec["merged_prs"] if pr.get("merged_at")
                     else rec["linked_prs_unmerged"]).append(entry)
        out[f"{repo}#{num}"] = rec
        if n % 20 == 0:
            print(f"  {n}/{len(issues)}", file=sys.stderr)

    (HERE / "outcomes.json").write_text(json.dumps(out, indent=1))
    ok = sum(1 for r in out.values() if r["fetch_ok"])
    print(f"fetched {len(out)} issues, {ok} ok, {len(out)-ok} failed", file=sys.stderr)


if __name__ == "__main__":
    main()
