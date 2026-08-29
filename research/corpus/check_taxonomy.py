"""The CODE-SUBSTANTIVE / INFRASTRUCTURE partition, declared as a rule.

WHY THIS IS A CORPUS FIELD AND NOT AN ANALYSIS-TIME FILTER. 42% of the corpus's
FAIL records failed only on bots and benchmarks -- a performance-regression
service, a docs-preview deploy, a labeler, and a "a reviewer will let you know"
notice. That is contamination of the DEPENDENT VARIABLE, not a caveat: a route
regressing on `outcome` would be fitting deploy-preview flakiness. So the
partition is computed once, stored on every record, and pinned by a test.

THE RULE. Ordered; first match wins. Every one of the 240 distinct check names
observed in the corpus must land in a declared bucket -- `UNCLASSIFIED` is a
FAILURE STATE, not a default. Defaulting the unknown to either class is the same
error as defaulting a missing verdict to PASS.

  CODE-SUBSTANTIVE -- the check re-runs something about the code and can fail
  because the code is wrong: test suites, linters, type checkers, static
  analysis, and builds/compilations (a build failure IS a code failure).

  INFRASTRUCTURE -- the check reports, publishes, annotates, or measures
  something orthogonal to correctness: deploy previews, benchmark services,
  coverage reporters, labelers, notice bots, publishing steps, and CI
  orchestration meta-jobs that only marshal other jobs.

BORDERLINE CALLS, DECLARED RATHER THAN HIDDEN:
  * coverage (codecov/*) -> INFRASTRUCTURE. It measures the TESTS, not the code;
    a coverage drop is a policy violation, not a defect. This is the one that
    flipped scikit-learn#34334 and it is the least obvious call here.
  * docs BUILD (`ci/circleci: doc`) -> CODE-SUBSTANTIVE. Sphinx executes example
    code and fails on real errors.
  * docs PREVIEW/DEPLOY (Cloudflare Pages, "Check the rendered docs here!")
    -> INFRASTRUCTURE. Hosting, not correctness.
  * CodeQL / "Analyze (...)" -> CODE-SUBSTANTIVE. It analyses the source.
  * CI meta-jobs ("Check all job statuses", "Check build trigger") ->
    INFRASTRUCTURE. They restate other jobs' results; counting them would
    double-count the jobs they aggregate.
"""
from __future__ import annotations

import re

SUBSTANTIVE = "CODE_SUBSTANTIVE"
INFRA = "INFRASTRUCTURE"

# (pattern, bucket, why). ORDER MATTERS -- first match wins.
RULES: list[tuple[str, str, str]] = [
    # --- INFRASTRUCTURE that would otherwise be caught by a later rule -------
    (r"^check the rendered docs", INFRA, "doc-preview notice bot"),
    (r"^a reviewer will let you know", INFRA, "review-requirement notice bot"),
    (r"^create an issue if", INFRA, "issue-filing bot"),
    (r"^send tweet", INFRA, "announcement bot"),
    (r"^upload |^publish|anaconda|pypi|^deploy\b|^release\b", INFRA,
     "publishing/deployment step"),
    (r"codspeed|benchmark|^bench\b|performance analysi|profiling", INFRA,
     "performance-benchmark service; a regression is not a defect"),
    (r"codecov|coverage", INFRA,
     "coverage reporter; measures the TESTS, not the code"),
    (r"cloudflare|netlify|vercel|readthedocs|^docs? preview|surge\.sh", INFRA,
     "docs/site preview hosting"),
    (r"^labeler|^label\b|semantic-pull-request|^size-label|dependabot|"
     r"^changelog\b|towncrier|^conventional", INFRA,
     "metadata/labeling/changelog-policy bot"),
    (r"update-tracker|update_tracking_issue|^triage|^stale\b", INFRA,
     "issue-tracker automation"),
    (r"^check all job statuses|^check build trigger|^retrieve |^determine |"
     r"^setup\b|^prepare\b|^collect |^report\b|^summary\b|^status\b", INFRA,
     "CI orchestration meta-job; restates other jobs (double-counting)"),
    (r"^ci/circleci: deploy$", INFRA, "artifact deployment step"),

    (r"^remove \"|^add \"|^remove .*label|auto-labeler|^welcome$|^post_comment$|"
     r"^check-assignment$|coderabbit|copilot-pull-request-reviewer|^greet", INFRA,
     "labeling / greeting / AI-review-comment bot"),

    # --- CODE-SUBSTANTIVE ----------------------------------------------------
    (r"lint|ruff|flake8|black|isort|pre-commit|^format|^style|spelling|"
     r"codespell|^typo", SUBSTANTIVE, "linter/style/spell checker"),
    (r"mypy|pyright|pyre|type.?check|^typing", SUBSTANTIVE, "type checker"),
    (r"codeql|^analyze \(|bandit|semgrep|^security", SUBSTANTIVE,
     "static analysis over the source"),
    (r"^build |^build$|wheel|sdist|source distribution|compile|^cmake|"
     r"ci/circleci: doc", SUBSTANTIVE, "build/compilation (incl. docs build)"),
    (r"^core / |^docs-build$|^build-pydantic$|reproducer|^run .*tests?$|"
     r"^matrix\.name$", SUBSTANTIVE,
     "project-specific test/build job. `matrix.name` is an UNEXPANDED GitHub "
     "template that GitHub reported literally; it is a real job whose name "
     "failed to render, and it is classified with the jobs it belongs to "
     "rather than left unclassified"),
    (r"^test|pytest|^linux|^macos|^windows|^ubuntu|^win|^py3|^check$|"
     r"^ci/circleci: |^continuous-integration|^conda|^pyodide|^wasm|^arm|"
     r"^free.?threaded|^nogil|^doctest|^integration|^unit", SUBSTANTIVE,
     "test suite / platform test matrix"),
]

_COMPILED = [(re.compile(p, re.I), b, w) for p, b, w in RULES]


def classify(name: str) -> tuple[str, str]:
    """-> (bucket, why). Returns ("UNCLASSIFIED", ...) rather than guessing."""
    n = name.strip()
    for rx, bucket, why in _COMPILED:
        if rx.search(n):
            return bucket, why
    return "UNCLASSIFIED", "no rule matched; must be declared before use"


def is_substantive(name: str) -> bool:
    return classify(name)[0] == SUBSTANTIVE


def substantive_outcome(checks) -> tuple[str, list]:
    """Outcome over CODE-SUBSTANTIVE checks only.

    NONE (no substantive check ran) is NOT PASS. An absent verdict is not a
    passing one -- the rule that governs the raw outcome governs this one too.
    """
    sub = [c for c in checks if is_substantive(c["name"])]
    concl = {str(c["conclusion"]).lower() for c in sub}
    if not sub:
        return "NONE", []
    if "failure" in concl:
        return "FAIL", [c for c in sub if str(c["conclusion"]).lower() == "failure"]
    if "success" in concl:
        return "PASS", []
    return "NONE", []
