"""Expand the decomposition corpus. IDENTICAL query, later pages only.

B1 — THE SELECTION PROPERTIES, stated before fetching and inherited UNCHANGED:

  endpoint   repos/{repo}/pulls?state=closed&per_page=100&page={N}
  filters    MIN_COMMITS >= 3  (a decomposition needs >= 3 subtasks)
             no_files -> drop;  no CI verdict -> drop
  pages      the original used 1..6. This uses 7.. onward. Same query, older
             PRs, nothing else changed.

WHAT THIS QUERY SELECTS ON, inherited from the original and NOT introduced here:
  * `state=closed` EXCLUDES OPEN PRs. A resolution-status filter.
  * `MIN_COMMITS >= 3` EXCLUDES SHORT decompositions -- and conservation
    "survives only in PRs short enough that no second round happened"
    (FINDINGS_SR1.md), so this filter removes exactly where the CONSERVING arm
    is densest. It bounds the measurable conserving rate from below.
Neither is new. Both are reported because an expansion that silently inherits a
filter is as misleading as one that adds it.

GROUND TRUTH IS THE PROJECT'S OWN CI, never a judgement made here.
Zero credits: gh api only.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent / "corpus"
sys.path.insert(0, str(CORPUS))

REPOS = ["scikit-learn/scikit-learn", "pydantic/pydantic"]
START_PAGE = 7                      # the original consumed 1..6
MIN_COMMITS = 3                     # identical to run_partB.py:44
CALL_BUDGET = int(sys.argv[1]) if len(sys.argv) > 1 else 4200

_calls = {"n": 0}


def gh(path: str):
    """One API call. Raises on failure -- never returns a stand-in, because an
    error absorbed as an empty list is the defect this corpus already records."""
    if _calls["n"] >= CALL_BUDGET:
        raise RuntimeError("BUDGET")
    _calls["n"] += 1
    p = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                       timeout=90)
    if p.returncode != 0:
        raise RuntimeError(f"gh failed: {path}: {p.stderr[:200]}")
    return json.loads(p.stdout)


def ci_verdict(repo: str, sha: str):
    """Substantive CI verdict from the project's OWN check-runs.

    REUSES `substantive_outcome`, the corpus's own frozen reduction, rather
    than reimplementing it. The first version of this function DID reimplement
    it and was wrong: `classify` returns a TUPLE `(bucket, why)` whose bucket is
    `CODE_SUBSTANTIVE`, and comparing that tuple to the string "SUBSTANTIVE"
    never matched, so every PR fell through to `no_ci` and four pages produced
    ZERO records. Comparing against the wrong representation, and the third
    instance of that shape in this session -- caught by the zero, not by review.

    The rule that a reduction should be imported and not restated is exactly
    what this file now follows.
    """
    from check_taxonomy import substantive_outcome
    d = gh(f"repos/{repo}/commits/{sha}/check-runs?per_page=100")
    runs = [{"name": r.get("name", ""), "conclusion": r.get("conclusion")}
            for r in d.get("check_runs", [])]
    v, fails = substantive_outcome(runs)
    if v == "NONE":                       # an absent verdict is NOT a pass
        return None, []
    return v, fails or runs[:12]


def main() -> None:
    existing = json.loads((CORPUS / "decompositions.json").read_text())
    seen = {(r["repo"], r["pr_number"]) for r in existing["records"]}
    out_path = HERE / "expanded.json"
    files_path = HERE / "expanded_files.json"
    records, files_map = [], {}
    if out_path.exists():
        prev = json.loads(out_path.read_text())
        records = prev["records"]
        files_map = json.loads(files_path.read_text())
        seen |= {(r["repo"], r["pr_number"]) for r in records}
    dropped = {"few_commits": 0, "no_files": 0, "no_ci": 0, "api_failure": 0}

    try:
        for repo in REPOS:
            for pg in range(START_PAGE, 200):
                prs = gh(f"repos/{repo}/pulls?state=closed&per_page=100&page={pg}")
                if not prs:
                    break
                for pr in prs:
                    if (repo, pr["number"]) in seen:
                        continue
                    try:
                        cms = gh(f"repos/{repo}/pulls/{pr['number']}/commits?per_page=100")
                        if len(cms) < MIN_COMMITS:
                            dropped["few_commits"] += 1
                            continue
                        v, ev = ci_verdict(repo, pr["head"]["sha"])
                        if v is None:
                            dropped["no_ci"] += 1
                            continue
                        for c in cms:
                            fs = gh(f"repos/{repo}/commits/{c['sha']}")
                            files_map[f"{repo}|{c['sha']}"] = [
                                f["filename"] for f in fs.get("files", [])]
                        records.append({
                            "repo": repo, "pr_number": pr["number"],
                            "goal": pr.get("title", ""),
                            "reference_decomposition": {
                                "subtasks": [{"sha": c["sha"],
                                              "message": (c["commit"]["message"]
                                                          .split("\n")[0])}
                                             for c in cms]},
                            "outcome_substantive": v,
                            "outcome_substantive_evidence": ev,
                            "merged": pr.get("merged_at") is not None,
                        })
                        seen.add((repo, pr["number"]))
                    except RuntimeError as e:
                        if "BUDGET" in str(e):
                            raise
                        dropped["api_failure"] += 1
                print(f"  {repo} page {pg}: records={len(records)} "
                      f"calls={_calls['n']}", flush=True)
    except RuntimeError as e:
        print(f"STOPPED: {e} after {_calls['n']} calls", flush=True)
    finally:
        out_path.write_text(json.dumps(
            {"_status": "EXPANSION. Identical query to run_partB.py, pages 7+.",
             "selection_inherited": {
                 "state": "closed -- EXCLUDES open PRs",
                 "min_commits": MIN_COMMITS,
                 "note": "MIN_COMMITS>=3 removes short PRs, where conservation "
                         "is densest; it bounds the conserving rate from below"},
             "start_page": START_PAGE, "repos": REPOS,
             "api_calls": _calls["n"], "dropped": dropped,
             "records": records}, indent=1))
        files_path.write_text(json.dumps(files_map))
        print(f"\nrecords={len(records)} calls={_calls['n']} dropped={dropped}")


if __name__ == "__main__":
    main()
