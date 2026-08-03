"""Re-fetch the COMPLETE check list per record, untruncated.

The corpus's `outcome_source.evidence` is capped at 12 entries (failures first).
That is enough to justify a verdict but NOT enough to partition checks into
CODE-SUBSTANTIVE vs INFRASTRUCTURE, because the partition needs every check that
ran, including the passing ones. Computing the partition off truncated evidence
is how the first code-substantive split came out contaminated (0.474 vs a true
0.421); this file exists so that cannot happen again.

Both GitHub CI channels are read -- modern check-runs AND the legacy
commit-status API that the Part E gate caught the extractor ignoring.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "all_checks.json"


def gh(path, tries=4):
    for a in range(tries):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                pass
        elif "Not Found" in r.stderr:
            raise RuntimeError("404")
        time.sleep(2 * (a + 1))
    raise RuntimeError("gh failed: " + path)


def main():
    recs = json.loads((HERE / "decompositions.json").read_text())["records"]
    out = {}
    for i, r in enumerate(recs):
        sha = r["outcome_source"]["tree_state"]
        checks = []
        d = gh(f"repos/{r['repo']}/commits/{sha}/check-runs?per_page=100")
        for c in (d or {}).get("check_runs") or []:
            if c.get("conclusion"):
                checks.append({"name": c["name"], "conclusion": c["conclusion"],
                               "channel": "check-run"})
        s = gh(f"repos/{r['repo']}/commits/{sha}/status")
        for c in (s or {}).get("statuses") or []:
            checks.append({"name": c["context"], "conclusion": c["state"],
                           "channel": "legacy-status"})
        out[r["record_id"]] = checks
        if i % 40 == 0:
            print("  ..", i, flush=True)
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, "for", len(out), "records")


if __name__ == "__main__":
    sys.exit(main())
