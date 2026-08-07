"""Fetch issue bodies. NOTHING IS FILTERED ON VERIFIABILITY.

The last census died because its vocabulary was selected on the outcome being
measured. This fetcher is written so every filter it applies is declared here
and is a TYPE filter or a PRESENCE filter, never a verifiability, testability,
actionability or resolution filter.

DECLARED FILTERS, exhaustive:
  1. `pull_request` key present  -> EXCLUDED. A PR is a different artifact
     (a proposed change), not a report of what is wrong. TYPE filter.
  2. empty/None body             -> EXCLUDED. There is no prose to extract an
     assertion from. PRESENCE filter.
  There is no third filter.

EXPLICITLY INCLUDED, because excluding any of them would select for
actionable-and-therefore-often-testable claims:
  * state=all           -> open AND closed
  * state_reason        -> `not_planned` (wontfix / invalid) is KEPT
  * no label filter     -> untriaged and unlabelled issues are KEPT
  * duplicates          -> KEPT
  * locked issues       -> KEPT

Resolution status is RECORDED on every claim and NEVER used as a filter.

Sampling: issues are walked in CREATION ORDER (sort=created, direction=desc)
and taken as a CONTIGUOUS BLOCK. Issue numbers are assigned sequentially at
creation, so a contiguous block is a creation-order slice with no selection on
outcome. Taking the most recent block deliberately MAXIMISES the share of
never-triaged issues, which is the direction that reduces selection.

Zero credits: `gh api` only. No model call.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
REPOS = ["scikit-learn/scikit-learn", "pandas-dev/pandas"]
PAGES = 10          # 10 x 100 = up to 1000 raw items per repo
PER_PAGE = 100


def api(path: str):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"gh api failed: {r.stderr[:300]}")
    return json.loads(r.stdout)


def main() -> None:
    all_rows = []
    stats = {}
    for repo in REPOS:
        raw = 0
        prs = 0
        empty = 0
        kept = []
        for page in range(1, PAGES + 1):
            path = (f"repos/{repo}/issues?state=all&per_page={PER_PAGE}"
                    f"&page={page}&sort=created&direction=desc")
            batch = api(path)
            if not batch:
                break
            raw += len(batch)
            for it in batch:
                if it.get("pull_request") is not None:
                    prs += 1
                    continue
                body = (it.get("body") or "").strip()
                if not body:
                    empty += 1
                    continue
                kept.append({
                    "repo": repo,
                    "number": it["number"],
                    "url": it["html_url"],
                    "created_at": it["created_at"],
                    # RECORDED, NEVER FILTERED ON:
                    "state": it["state"],
                    "state_reason": it.get("state_reason"),
                    "closed_at": it.get("closed_at"),
                    "labels": [l["name"] for l in it.get("labels", [])],
                    "body": body,
                })
        stats[repo] = {"raw_items": raw, "excluded_pull_requests": prs,
                       "excluded_empty_body": empty, "kept_issues": len(kept)}
        all_rows.extend(kept)
        print(f"  {repo}: raw {raw}, PRs {prs}, empty {empty}, KEPT {len(kept)}",
              file=sys.stderr)

    (OUT / "issues_raw.json").write_text(json.dumps(all_rows, indent=1))
    (OUT / "fetch_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
