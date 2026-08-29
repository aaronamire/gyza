"""Part B — the decomposition corpus, mined from EXTERNAL pull requests.

THE DESIGN PROPERTY, and how it is enforced here.

  STRUCTURE comes from the PR -> commit mapping, recorded by GitHub when the
  author pushed. It is not my grouping rule and not commit-message text.

  VERDICT comes from CI check-run conclusions -- executed by each project's own
  infrastructure, on hardware nobody here controls, before this corpus existed.
  Never merge status, never message sentiment, never my judgement of the change.

  These are enforced by `assert_source_separation()` below and pinned by a test:
  no field of a record's verdict may be derived from any field of its structure.

WHY NOT THIS REPOSITORY'S HISTORY (measured, SOURCE_ASSESSMENT.md §A1): zero
merge commits, so the DAG carries no decomposition structure at all; and 12/12
sampled commits run GREEN at their own tree -- an exact 1 that is DEFINITIONAL,
because a commit is published after its author made it pass. Running a commit's
own tests against its own tree recovers the committing habit, not the goal.
That is a general result about mining any clean history for outcomes.

WHAT THE OUTCOME IS, STATED PRECISELY. It is "the CI check-runs on this commit
concluded success / failure". It is NOT "the goal was achieved" -- no mechanical
source supplies that, and claiming it would be the competence bound ignored.
Records carry `outcome_semantics` so no downstream route can forget which one it
has.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "decompositions.json"

# Two review cultures, deliberately different (see MANIFEST for the profile):
#   scikit-learn -- academic, long multi-reviewer cycles, many small fixups
#   pydantic     -- fast-moving library, tighter PRs, heavy CI matrix
REPOS = ["scikit-learn/scikit-learn", "pydantic/pydantic"]
PAGES = 6                       # 100 closed PRs per page
MIN_COMMITS = 3                 # a decomposition needs >= 3 subtasks
PER_REPO = 60          # cap PER REPOSITORY, not globally -- see note in extract()

_TEST_RE = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$")
_DOC_RE = re.compile(r"\.(md|rst|txt)$|(^|/)docs?/|(^|/)changes/")


class APIFailure(Exception):
    """AN ERROR IS NOT A VALUE.

    The first version of this file returned None on a failed call, and the
    caller's `or []` turned it into "this PR has 0 commits" -- silently
    incrementing the `few_commits` drop counter. A transport failure and a
    genuinely small PR became the same observation, which is artifact #16's
    species (an exception written into the measurement channel) reproduced in
    this extractor. Failures now raise, are retried, and are counted in their
    OWN bucket, so `dropped` means what it says.
    """


def gh(path: str, *, tries: int = 4):
    last = ""
    for attempt in range(tries):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError as e:
                last = f"bad JSON: {e}"
        else:
            last = r.stderr.strip()[:200]
            # 404 on a deleted fork is a REAL absence, not a transport failure.
            if "Not Found" in last or "HTTP 404" in last:
                raise APIFailure("404")
        time.sleep(2 * (attempt + 1))
    raise APIFailure(last or "exhausted retries")


# --------------------------------------------------------------------------- #
#  VERDICT SOURCE -- CI only                                                   #
# --------------------------------------------------------------------------- #
def ci_verdict(repo: str, sha: str):
    """PASS / FAIL / NONE from BOTH CI reporting APIs. NONE is dropped by the
    caller and is NEVER defaulted to PASS -- an absent verdict is not a passing
    one.

    THE LEGACY-STATUS BLIND SPOT, found by the Part E gate. The first version
    read only the modern check-runs API. GitHub has TWO CI reporting channels,
    and older integrations (CircleCI on scikit-learn) still report through the
    legacy commit-status API, which check-runs does not surface. A commit whose
    check-runs were all green while a legacy status was red was recorded PASS.

    The error is ONE-DIRECTIONAL by construction: a channel you do not read can
    only hide failures, never invent them. That is why every instance found was
    `recorded PASS / source FAIL` and none the reverse -- the sign of the
    residual confirms the mechanism rather than merely being consistent with it.
    Measured extent before the fix: 2/181 records (140/181 had legacy statuses
    present at all).
    """
    d = gh(f"repos/{repo}/commits/{sha}/check-runs?per_page=100")
    runs = (d or {}).get("check_runs") or []   # gh() raises on failure; {} is a real empty
    concl = [c["conclusion"] for c in runs if c.get("conclusion")]
    legacy = gh(f"repos/{repo}/commits/{sha}/status")
    legacy_state = (legacy or {}).get("state")
    if legacy_state == "failure":
        ev = [{"name": s["context"], "conclusion": s["state"],
               "started_at": s.get("created_at"), "html_url": s.get("target_url"),
               "channel": "legacy-commit-status"}
              for s in (legacy.get("statuses") or []) if s.get("state") == "failure"][:12]
        return "FAIL", ev
    if not concl:
        if legacy_state == "success":
            return "PASS", [{"name": s["context"], "conclusion": s["state"],
                             "started_at": s.get("created_at"),
                             "html_url": s.get("target_url"),
                             "channel": "legacy-commit-status"}
                            for s in (legacy.get("statuses") or [])][:12]
        return "NONE", []
    # FAILURES FIRST. The first version sliced [:12] over check-runs in API
    # order, so on a commit with 36 checks the failing one could fall outside
    # the stored evidence -- leaving records marked FAIL whose evidence showed
    # no failure. The verdict was right (computed over ALL conclusions) but the
    # evidence did not support it, and any analysis reading `evidence` rather
    # than recomputing would silently under-count failures.
    _rank = {"failure": 0, "success": 1}
    ev = sorted(
        [{"name": c["name"], "conclusion": c["conclusion"],
          "started_at": c.get("started_at"), "html_url": c.get("html_url")}
         for c in runs if c.get("conclusion") in ("success", "failure")],
        key=lambda c: _rank[c["conclusion"]])[:12]
    if "failure" in concl:
        return "FAIL", ev
    if "success" in concl:
        return "PASS", ev
    return "NONE", []


# --------------------------------------------------------------------------- #
#  CONTEXT -- must not leak the split                                          #
# --------------------------------------------------------------------------- #
def build_context(repo, pr, files):
    """What a strategy needs to produce its OWN decomposition.

    Deliberately excluded, because each would leak the reference split:
      - per-commit anything (messages, SHAs, per-commit file lists)
      - the COMMIT COUNT (that is the answer's length)
      - any ordering information
    Files are sorted alphabetically, which destroys the touch order.
    """
    paths = sorted({f["filename"] for f in files})
    return {
        "repo": repo,
        "base_sha": pr["base"]["sha"],
        "files_touched": paths,                       # UNION, alphabetical
        "n_files": len(paths),
        "total_additions": sum(f.get("additions", 0) for f in files),
        "total_deletions": sum(f.get("deletions", 0) for f in files),
        "modules": sorted({str(Path(p).parent) for p in paths})[:40],
        "touches_tests": any(_TEST_RE.search(p) for p in paths),
        "touches_docs": any(_DOC_RE.search(p) for p in paths),
        "language_mix": sorted({Path(p).suffix or "<none>" for p in paths}),
    }


# --------------------------------------------------------------------------- #
#  CARRIER proposal -- mechanical, then hand-audited (see audit_types.py)      #
# --------------------------------------------------------------------------- #
def propose_carrier(files_in_commit):
    """MECHANICAL PROPOSAL ONLY. `assigned_by` records this; `audited` is false
    until a human confirms it. Type assignment is itself a tier-3 claim
    (BLOCKED_SR1_SR2_SR4.md) -- nothing here is self-declared ground truth."""
    paths = [f["filename"] for f in files_in_commit]
    if not paths:
        return "NONE", "empty commit"
    if any(_TEST_RE.search(p) for p in paths):
        return "TEST", "adds or modifies test files; CI executes them (finite sample)"
    if all(_DOC_RE.search(p) for p in paths):
        return "NONE", "documentation only; no executable evidence"
    return "NONE", "code change with no test in the same commit"


def commit_files(repo, sha):
    d = gh(f"repos/{repo}/commits/{sha}")
    return (d or {}).get("files") or []


# --------------------------------------------------------------------------- #
#  EXTRACTION                                                                  #
# --------------------------------------------------------------------------- #
def extract():
    records, seen = [], set()
    if OUT.exists():
        records = json.loads(OUT.read_text())["records"]
        seen = {(r["repo"], r["pr_number"]) for r in records}
    dropped = {"few_commits": 0, "no_ci": 0, "no_files": 0, "api_failure": 0}

    for repo in REPOS:
        # THE CAP IS PER REPOSITORY. The first version broke on a GLOBAL target,
        # and because `break` leaves only the inner loop, the first repo consumed
        # the whole budget: 120 scikit-learn records to 1 pydantic. A corpus like
        # that is a single project's commit hygiene wearing two repo names, which
        # is the confound the two-culture requirement exists to prevent.
        n_repo = sum(1 for r in records if r["repo"] == repo)
        prs = []
        for pg in range(1, PAGES + 1):
            # No `or []` here. `gh` raises on failure, so the default would be
            # dead code -- but it is the exact idiom that caused the defect this
            # file already documents, and leaving it would re-arm the trap the
            # moment gh's contract changes. Found by the AST scanner in
            # tests/test_canonical_comparison.py on its first run.
            d = gh(f"repos/{repo}/pulls?state=closed&per_page=100&page={pg}")
            prs += d
            if len(d) < 100:
                break
        # CARRY THE UNMERGED POPULATION. A merged-only corpus selects on success
        # and re-imports the degeneracy that disqualified source (i).
        print(f"{repo}: {len(prs)} closed PRs "
              f"({sum(1 for p in prs if p.get('merged_at'))} merged)", flush=True)

        for pr in prs:
            if (repo, pr["number"]) in seen:
                continue
            try:
                cms = gh(f"repos/{repo}/pulls/{pr['number']}/commits?per_page=100")
                if len(cms) < MIN_COMMITS:
                    dropped["few_commits"] += 1
                    continue
                files = gh(f"repos/{repo}/pulls/{pr['number']}/files?per_page=100")
                if not files:
                    dropped["no_files"] += 1
                    continue
                verdict, evidence = ci_verdict(repo, pr["head"]["sha"])
            except APIFailure as e:
                dropped["api_failure"] += 1          # NOT a corpus property
                print(f"  api-failure PR#{pr['number']}: {e}", flush=True)
                continue
            if verdict == "NONE":
                dropped["no_ci"] += 1
                continue

            subtasks = []
            try:
                for c in cms:
                    cf = commit_files(repo, c["sha"])
                    carrier, why = propose_carrier(cf)
                    sv, _ = ci_verdict(repo, c["sha"])
                    subtasks.append({
                        "sha": c["sha"],
                        "message": c["commit"]["message"].split("\n")[0],
                        "n_files": len(cf),
                        "per_commit_ci": sv,
                        "claim_type": {
                            "carrier": carrier, "rationale": why,
                            "assigned_by": "mechanical-proposal:propose_carrier",
                            "audited": False,
                            "source": "file paths of the commit (GitHub API)"},
                    })
            except APIFailure as e:
                dropped["api_failure"] += 1
                print(f"  api-failure (subtasks) PR#{pr['number']}: {e}", flush=True)
                continue

            records.append({
                "record_id": f"{repo.split('/')[1]}#{pr['number']}",
                "repo": repo,
                "pr_number": pr["number"],
                # GOAL -- verbatim, never paraphrased
                "goal": {"title": pr["title"],
                         "body": (pr.get("body") or "")[:4000],
                         "source": f"{pr['html_url']} (PR title+body, verbatim)"},
                "context": build_context(repo, pr, files),
                # ONE STRATEGY'S OUTPUT -- never the target
                "reference_decomposition": {
                    "LABEL": "ONE STRATEGY'S OUTPUT (this human author's commit "
                             "sequence, shaped by review and rebase policy). NOT a "
                             "target, NOT ground truth for how the goal should be "
                             "split. SR-1 compares strategies; scoring against this "
                             "would score commit hygiene.",
                    "subtasks": subtasks,
                    "n_subtasks": len(subtasks),
                },
                "outcome": verdict,
                "outcome_semantics": "CI check-runs on the PR head commit concluded "
                                     "success/failure. This is NOT 'the goal was "
                                     "achieved' -- no mechanical source supplies that.",
                "outcome_source": {
                    "kind": "CI check-runs (executed by the project's own "
                            "infrastructure, external to this program)",
                    "tree_state": pr["head"]["sha"],
                    "command": f"gh api repos/{repo}/commits/{pr['head']['sha']}"
                               f"/check-runs",
                    "evidence": evidence,
                },
                "merged": bool(pr.get("merged_at")),   # RECORDED, never a verdict input
            })
            seen.add((repo, pr["number"]))
            if len(records) % 10 == 0:
                print(f"  {len(records)} records", flush=True)
            n_repo += 1
            if n_repo >= PER_REPO:
                break

    OUT.write_text(json.dumps({"dropped": dropped, "records": records}, indent=1))
    print(f"\nextracted {len(records)}   dropped {dropped}")
    return records


if __name__ == "__main__":
    extract()
