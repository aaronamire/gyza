"""Extract CLAIMS (assertions) from issue bodies. Fully mechanical. ZERO CREDITS.

WHAT IS MECHANICAL AND WHAT IS AUTHORED:
  * MECHANICAL: everything in this file executes without a model. Sectioning,
    stripping, sentence splitting, the statement filter, the per-issue cap.
  * AUTHORED: the section allow/deny lists and the statement heuristics below.
    They are declared here in full so the extraction can be audited (A4).

NO MODEL IS USED, TO SEGMENT OR OTHERWISE. The prompt permits a model for
segmentation only; it was not needed, so the credit gate never opens.

THE EXTRACTION MUST NOT PRE-FILTER ON SPEECH ACT OR VERIFIABILITY. If it kept
only sentences that "look checkable", the census would measure the extractor.
So sections are dropped only for being NON-PROSE (code, version dumps,
checkboxes, boilerplate), never for what they assert.

PER-ISSUE CAP: at most MAX_PER_ISSUE claims per issue, so a single verbose
report cannot dominate a cell. Requirement (3) of the census's stated need.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_PER_ISSUE = 3

# Sections dropped for being NON-PROSE. Nothing here is dropped for what it
# asserts -- these carry code, environment dumps, or checkbox forms.
DENY_SECTION = re.compile(
    r"version check|installed version|^versions?$|reproducible example|"
    r"steps?/code to reproduce|interest in fixing|checklist|"
    r"code of conduct|prior to submitting",
    re.I,
)

BOILERPLATE = re.compile(
    r"this issue is not yet ready for a pr|contributing guidelines|"
    r"needs triage|i have checked that this issue has not already been reported|"
    r"i have confirmed this bug exists on|latest version of pandas|"
    r"main branch of pandas|thanks for your report|please have a look at our",
    re.I,
)


def strip_noise(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)      # fenced code
    text = re.sub(r"`[^`\n]+`", " CODE ", text)             # inline code
    text = re.sub(r"^\s*>.*$", " ", text, flags=re.M)       # blockquotes
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)     # html comments
    text = re.sub(r"^\s*[-*]?\s*\[[ xX]\].*$", " ", text, flags=re.M)  # checkboxes
    text = re.sub(r"https?://\S+", " URL ", text)
    text = re.sub(r"!?\[[^\]]*\]\([^)]*\)", " ", text)      # md links/images
    text = re.sub(r"[ \t]+", " ", text)
    return text


def sections(body: str) -> list[str]:
    """Split on markdown headers; keep prose sections only."""
    parts = re.split(r"^#{1,6}\s*(.+?)\s*$", body, flags=re.M)
    if len(parts) == 1:
        return [body]                      # no headers: whole body is prose
    out, i = [], 1
    while i < len(parts) - 1:
        header, chunk = parts[i], parts[i + 1]
        if not DENY_SECTION.search(header):
            out.append(chunk)
        i += 2
    return out or []


# A statement is kept if it is prose of plausible assertion shape. These
# heuristics are AUTHORED and are audited in A4.
def is_statement(s: str) -> bool:
    s = s.strip()
    if not (25 <= len(s) <= 400):
        return False
    # A4 DEFECT 1: a NON-TERMINAL '?' slipped through ("Why is CODE unshashable? 2.")
    if "?" in s:                           # a question asserts nothing
        return False
    # A4 DEFECT 1b: interrogative openers with the mark stripped
    if re.match(r"^(why|how|what|when|where|which|who|is|are|does|do|can|could|"
                r"should|would|will|has|have|did)\b", s, re.I):
        return False
    if BOILERPLATE.search(s):
        return False
    if not re.search(r"[a-z]{3}", s):      # must contain real words
        return False
    words = s.split()
    if len(words) < 5:
        return False
    # mostly-code / mostly-path lines
    if sum(c in "/\\=<>{}[]|" for c in s) > len(s) * 0.08:
        return False
    # A4 DEFECT 2: pure code survived ('ts = pd.Timestamp("...") ts.tz_localize(...)')
    if re.search(r"\w+\s*=\s*\w+[.(]|\w+\.\w+\([^)]*\)", s):
        return False
    # A4 DEFECT 3: degenerate after placeholder substitution -- 'Homepage for
    # example: URL or URL' asserts nothing once URL/CODE are removed.
    residue = re.sub(r"\b(CODE|URL)\b", " ", s)
    if len(re.findall(r"\b[a-z]{3,}\b", residue, re.I)) < 6:
        return False
    # A4 DEFECT 3b: markdown remnants
    if re.search(r"\]\(|\[[^\]]*\]\s*\(|<img|<a\s|</?\w+>", s):
        return False
    if re.match(r"^(please|see|cc|ping|thanks|hi|hello)\b", s, re.I):
        return False
    # A4 ROUND 2, DEFECT 5: imperative REPRODUCTION STEPS escaped when the
    # section was not literally named "steps to reproduce"
    # ('Open a file without using a context manager 2.'). A step is an
    # instruction, not an assertion.
    if re.match(r"^(open|run|create|install|import|call|execute|set|add|remove|"
                r"click|download|switch|use|try|apply|build|start|check)\b",
                s, re.I) and not re.search(r"\b(is|are|was|were|has|have|had|"
                                           r"does|do|did|will|would|should|"
                                           r"cannot|can't|doesn't|don't)\b", s, re.I):
        return False
    # A4 ROUND 2, DEFECT 6: PASTED PROGRAM OUTPUT is the software speaking, not
    # the reporter ('ValueError: Input X contains infinity or a value too
    # large for dtype(...)').
    if re.match(r"^\s*(\w*(Error|Exception|Warning|Traceback)\b)", s):
        return False
    if re.search(r"^\s*(Traceback \(most recent|File \")", s):
        return False
    # A4 ROUND 2, DEFECT 7: META-COMMENTARY about the REPORT rather than a
    # claim about the software ('Hopefully the reproducible code ... explain
    # the issue well enough.').
    if re.search(r"\b(hopefully|i hope|let me know|as mentioned above|"
                 r"see below|attached below|reproducible code|the snippet below|"
                 r"my first issue|apolog)\b", s, re.I):
        return False
    return True


# A4 DEFECT 4: the splitter cut mid-sentence at "e.g." and friends, yielding
# fragments like 'There are several estimators that transform CODE (e.g.'
_ABBREV = re.compile(r"\b(e\.g|i\.e|etc|vs|cf|resp|approx|fig|eq|no|al)\.$", re.I)


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s*\n\s*", " ", text)
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z(`\"'])", text)
    out: list[str] = []
    for part in raw:
        if out and _ABBREV.search(out[-1]):      # re-join across the abbreviation
            out[-1] = out[-1] + " " + part
        else:
            out.append(part)
    return [p.strip() for p in out if p.strip()]


def main() -> None:
    issues = json.loads((HERE / "issues_raw.json").read_text())
    claims = []
    for it in issues:
        found = []
        for sec in sections(it["body"]):
            for sent in split_sentences(strip_noise(sec)):
                if is_statement(sent):
                    found.append(sent)
                if len(found) >= MAX_PER_ISSUE:
                    break
            if len(found) >= MAX_PER_ISSUE:
                break
        for j, text in enumerate(found):
            claims.append({
                "claim_id": f"{it['repo'].split('/')[-1]}#{it['number']}-{j}",
                "text": text,
                "repo": it["repo"],
                "issue": it["number"],
                "url": it["url"],
                # RECORDED, NEVER USED AS A FILTER:
                "issue_state": it["state"],
                "issue_state_reason": it["state_reason"],
                "issue_labels": it["labels"],
            })

    (HERE / "claims.json").write_text(json.dumps(claims, indent=1))
    from collections import Counter
    per_repo = Counter(c["repo"] for c in claims)
    print(f"issues in           : {len(issues)}")
    print(f"issues yielding >=1 : {len({c['issue'] for c in claims})}")
    print(f"CLAIMS EXTRACTED    : {len(claims)}")
    for r, n in per_repo.items():
        print(f"   {r}: {n}")
    print(f"max per issue       : {MAX_PER_ISSUE}")


if __name__ == "__main__":
    main()
