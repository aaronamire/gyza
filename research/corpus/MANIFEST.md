# Task corpus — MANIFEST

**Built 2026-08-03, branch `corpus-build`.** Every number below carries its
source. Where the corpus is weak it is said here, not left for a route to
discover mid-run.

Artifacts: `decompositions.json` (Part B), `stochastic.json` + `c_cache/`
(Part C), `leakage_handcheck.json` (B2), `corpus_verification.json` (Part E),
`PART_D_MULTI_AGENT.md`, `SOURCE_ASSESSMENT.md` (Part A).
Invariants pinned by `tests/test_corpus.py` (10 tests, green).

---

## 0. A REUSABLE FINDING, recorded because the next person will reach for it

> **Running a commit's own tests against its own tree recovers the committing
> habit, not the goal.**

Measured here: 12 commits sampled from the 51 on `main` that touch `tests/`,
each checked out and run against the test files it itself touched — **12/12
green.** An exact 1, and it is **DEFINITIONAL**: a commit is published *after*
its author made it pass, so the population is selected on the outcome being
measured. Combined with **zero merge commits on `main`** (so the DAG carries no
decomposition structure at all), this repository's history fails both halves of
the required structure/verdict separation.

**This generalises to any clean history**, not just this one. A well-maintained
repository is *more* degenerate, not less, because its authors are more
disciplined about committing green. Anyone mining git history for ground-truth
outcomes must get the verdict from a source that observed the work **while it
was still failing** — CI on in-progress commits does; the commit's own tree does
not.

---

## 1. Requirement 1 — DECOMPOSITIONS (SR-1, K-2): **SUPPLIED**

**181 goals, 1455 subtasks**, from two repositories with deliberately different
review cultures.

| | scikit-learn | pydantic | total |
|---|---|---|---|
| goals | 121 | 60 | **181** |
| FAIL rate | 0.116 | **0.400** | 0.210 |
| mean subtasks | 9.1 | 5.9 | 8.0 (median 5, max 100) |

**The two-culture requirement earned its place.** The FAIL base rate differs by
**3.4×** between the repositories. A single-repo corpus would have fixed the
outcome base rate at either 0.116 or 0.400 and called it a property of
decomposition. It is a property of the project.

**Source separation, as built and as tested.**

- **STRUCTURE** = the PR → commit mapping recorded by GitHub at push time. Not
  my grouping rule, not commit-message text.
- **VERDICT** = CI check-run + legacy commit-status conclusions, executed by each
  project's own infrastructure before this corpus existed.
- Pinned by `test_no_verdict_is_derived_from_merge_status`, which passes because
  **all four cells are populated**: merged+PASS 119, merged+FAIL 14,
  unmerged+PASS 24, unmerged+FAIL 24. If `outcome` were merge status in
  disguise, two cells would be empty.
- The closed-unmerged population was **carried, not dropped**: 48/181 (0.265).

**Dropped, with reasons that mean what they say:** `few_commits` 646 (<3
commits), `no_ci` 2, `no_files` 0, **`api_failure` 0**. The `api_failure` bucket
exists because the first version of the extractor returned `None` on a failed
call and the caller's `or []` scored it as "this PR has 0 commits" — a transport
failure and a small PR became the same observation. That is artifact #16's
species reproduced in my own extractor; it now raises, retries, and counts
separately.

### What `outcome` MEANS — read this before using it

`outcome` is **"the CI checks on this commit concluded success/failure"**. It is
**not** "the goal was achieved"; no mechanical source supplies that, and claiming
it would be the competence bound ignored. Every record carries
`outcome_semantics` saying so.

**And CI failure is heterogeneous.** Of the 38 FAIL records:

- **22 (0.579)** have ≥1 code-substantive failing check (test matrix, lint);
- **16 (0.421)** fail **only** on non-code checks — CodSpeed performance
  analysis (the single most common failing check, 14), Cloudflare Pages doc
  previews, `labeler` bots, a "a reviewer will let you know" notice bot, and one
  `codecov/patch` coverage gate.

A route reading `outcome == FAIL` as "the code was wrong" would be wrong about
**42% of the failures**. Use the evidence field, not the label.

> **Correction recorded:** the first computation of this split returned 0.474,
> and it was contaminated. `ci_verdict` sliced evidence `[:12]` in API order, so
> on a commit with 36 checks the failing one could fall outside the stored
> evidence — leaving records marked FAIL whose evidence showed no failure at all
> (4 such records). The verdicts were always correct, being computed over *all*
> conclusions; the evidence did not support them. Evidence is now sorted
> failures-first and the corrected figure is **0.421**.

### B2 — the leakage check: **0.864 not reconstructible** (19/22 hand-verified)

Mechanical assertions (all green): `context` contains no subtask SHA, no commit
message, no subtask count, and `files_touched` is alphabetical so touch **order**
is destroyed.

Hand-verification on 22 sampled records (`leakage_handcheck.json`, per-record
judgements recorded so the rate is auditable): **19/22 = 0.864** could not be
reconstructed from goal+context.

**The mechanism behind the 3 failures is worth more than the rate.**
Reconstruction risk is a function of **decomposition length**, not of context
content. All three flagged records were either minimum-length (`n_sub == 3`,
following the project's `code → test → changelog` convention) or the single
record whose PR body is literally a 16-item release checklist. Every record with
`n_sub ≥ 4` was judged not reconstructible, because **445/1455 = 0.306 of
subtasks are review-cycle residue** (`nit`, `fix`, `wip`, `cln`, `empty commit`,
merge-from-main) that did not exist when the goal was written. A reader cannot
predict a reviewer's future comments.

Every record now carries `leakage_risk.flag`; **56/181 (0.309)** are flagged.
Routes should exclude them or report split by that boundary.

### The carrier distribution is DEFINITIONAL and must not be read as a result

`carrier`: **NONE 884, TEST 571, PROOF 0, SPEC 0.**

**The 0s are a property of the assignment function, not of the substrate.**
`propose_carrier` can only ever return `TEST` or `NONE` — inspect its source; no
branch emits `PROOF` or `SPEC`. So this distribution is **no evidence whatever**
about how much ordinary software carries proofs or specs, and SR-1's primary
metric (fraction PROOF/SPEC-carried) is **not measurable on this corpus**. It is
disclosed here rather than discovered by SR-1 mid-run.

Type assignment is itself a tier-3 claim. Every assignment carries
`assigned_by: "mechanical-proposal:propose_carrier"`, **`audited: false`**, and
its source. **Nothing in this corpus is human-audited type assignment**, and the
`audited` field is false everywhere so no route can mistake it for one.

---

## 2. Requirement 2 — STOCHASTIC OUTCOMES (SR-4): **SUPPLIED, and SR-4 stays BLOCKED as directed**

An OpenRouter key was found at `research/correlated_failure/.env` (gitignored,
loaded by file path at `run_openrouter.py:31`, which is why an environment scan
missed it). **Balance $3.172**; estimate $0.154; gate `balance ≥ 2× estimate`
passed with ~10× headroom. **Actual spend $0.0504** (1.8282 → 1.8786).

**200 (model, task) pairs × K=5 samples at temperature 0.7 = 1000 generations**,
4 models × the 50 MBPP problems of the decisive run (seed 1). Verdicts are the
**MBPP asserts EXECUTED** — the external ground truth of `mbpp_truth.json`
(agreement 0.9439, false_wrong 11, **false_correct 0**, one-directional).
Prompts imported verbatim from `native_verifier.code_prompt` for comparability
with the temperature-0 arm.

`route3_attractor`'s intact K=4 arm was **not used**: its `items.json` is
program-authored with hand-computed answers, and that reasoning did not change
when credits turned out to exist.

### VARIANCE PROFILE — reported first, as C4 requires

| | n | fraction |
|---|---|---|
| complete pairs | 200 | — |
| dropped for error | **0** | — |
| all K agree | 156 | 0.780 |
| **samples differ (retry measurable)** | **44** | **0.220** |
| all agree, all pass | 54 | 0.270 |
| all agree, all fail | 102 | 0.510 |

**Retry is measurable on 44 pairs.** On 51% of pairs the model fails all five
times (retry is definitionally useless) and on 27% it passes all five (retry is
unnecessary).

**And the differing population is concentrated in one model**: llama-3.1-70b
supplies **24/44 (0.545)** of it, with a pass rate of 0.240 at T=0.7 against
0.458 at T=0 while the other three models are stable. **Diagnosed before
reporting**: extraction failure was ruled out — 185/190 of its failing samples
contain a real `def` and 0 extract empty; the sampled example is a genuine
argument-order error. Remaining candidates are real temperature sensitivity and
OpenRouter provider drift since the T=0 run, and **provider drift cannot be
excluded** from here. A route using this arm would substantially be measuring
one model.

Overall per-sample pass rate 0.379 at T=0.7 against 0.403 at T=0 — the substrate
is comparable in aggregate.

**7 generations failed (all HTTP 429) and were retried to completion**; they were
recorded as `__ERR__` and excluded from the profile, never counted as failing
samples. Final state 200/200 complete, **0 dropped**.

### SR-4 remains BLOCKED, as directed

- **(a) Status: BLOCKED.** The substrate now exists but the route is not run.
- **(b) What would unblock it:** exactly what is now here — K ≥ 5 samples at
  temperature > 0.7 per task over a substrate with external ground truth. **That
  condition is now met**, so SR-4's blocker has moved from *substrate* to
  *statistical power*: n = 44 differing pairs, 55% of them one model.
- **(c) The blocker was a CREDIT constraint, not a design one** — and it was a
  *discovery* constraint too: the key existed all along in a gitignored file
  loaded by path. **This project's measurement capability is limited by
  $3.12 of remaining credit**, and that is a capability limit worth stating
  rather than routing around.

**The human FAIL → PASS population is NOT merged into this.** Part B's per-commit
CI contains 678 FAIL / 431 PASS across 1455 subtasks with many recovery
trajectories, but that is *human* retry under review, not model resampling —
same units, plausible ordering, different measurement (artifact #17's species).
It is a separate question and is recorded as one.

---

## 3. Requirement 3 — MULTI-AGENT TRACES (AG-1..3): **NOT SUPPLIED**

Full reasoning in `PART_D_MULTI_AGENT.md`. Summary:

- **`AG-1`, `AG-2`, `AG-3` have no committed definitions in the tree.** The
  requirement assessed is the task prompt's prose.
- **No public dataset** of real multi-agent traces with team-level collective
  verdicts was located; the 2025–26 survey literature names the gap directly.
- **Multi-author PRs are harvestable** (9/26 = 0.346 of ≥3-commit PRs) but are
  the **wrong shape**: authors are serialized through git, and rebase resolves
  the interference *before* CI computes the verdict. The coordination failures
  are eaten by the workflow before they can be measured.
- **CooperBench** (652 tasks, 12 libraries, 4 languages; success only when both
  agents' patches merge cleanly and both test suites pass) satisfies the verdict
  property **mechanically, collectively, and externally**. It is an environment,
  not a corpus: traces must be generated in it.
- **Nothing was synthesized** (D3).

**Finding: NOT-HARVESTABLE-BUT-STUDIABLE.** Requirement 3 is blocked on
**trace-generation budget, not on the absence of a verdict** — the same class of
blocker as SR-4. D2 states the six properties a source must have.

---

## 4. Part E — the verification gate: **PASS at 0.9778**, and the 1.0000 that followed is definitional

E1 verified 45 records against **GraphQL `statusCheckRollup`** — a different
endpoint and data model from extraction's REST check-runs, chosen because
re-running the extractor's own query would compare a parser with itself.

| run | agreement | meaning |
|---|---|---|
| **before the fix** | **0.9778 (44/45)** | **the gate result. Independent.** |
| after the fix | 1.0000 (45/45) | **DEFINITIONAL — not an improvement** |

**Diagnosing the 1.0000, as required.** The fix made the extractor read both CI
channels; the rollup aggregates both CI channels. The verifier and the extractor
now read the same underlying data, so the second run is **near-tautological** and
confirms only that the fix was applied. Reported as such rather than as a better
gate result.

> **A methodological consequence worth carrying: a verification gate is
> single-use against the defect it finds.** Fixing the defect by adopting the
> verifier's data source destroys the independence that made the gate
> meaningful. Any future re-verification of this corpus needs a *third* source.

### E3 — the disagreement mechanism (n=1, and one-directional)

`scikit-learn#34378`: recorded PASS, source FAIL. All 36 check-runs were
SUCCESS/SKIPPED, but 5 **legacy commit-status** contexts included a FAILURE.
GitHub has two CI reporting channels and the extractor read only the modern one;
older integrations (CircleCI on scikit-learn) still report through the legacy
API.

**The sign of the residual confirms the mechanism.** A channel you do not read
can only *hide* failures, never invent them — so the error must be one-directional
`recorded PASS / source FAIL`, and every instance found was exactly that.

**Extent measured across the whole corpus, not just the sample:** 140/181 records
had legacy statuses present; **2/181 (0.011)** were wrong. Both are now FAIL.

**Confirmed against a genuinely third-party source**, not GitHub at all:
CircleCI's own API reports build 357960 as `{"status": "failed", "outcome":
"failed"}`. The corrected verdict is right.

---

## 5. What this corpus does NOT supply — and what stays blocked

| route | status | why |
|---|---|---|
| **SR-1** decomposition | **partially unblocked** | 181 goals with external structure/verdict separation. But its stated primary metric — fraction PROOF/SPEC-carried — is **not measurable**: the carrier proposer's range is `{TEST, NONE}` by construction. SR-1 needs either a new metric or an assignment function that can emit PROOF/SPEC. |
| **K-2** decomposer | **unblocked** | goals + context with a 0.864 hand-verified non-reconstruction rate; 56 records flagged for length-driven leakage risk. |
| **SR-4** retry | **BLOCKED (as directed)** | substrate now exists; power is the open question (n=44, 55% one model). |
| **K-7** retry policy | **BLOCKED** | follows SR-4. |
| **AG-1..3** | **BLOCKED** | no traces; CooperBench would supply the verdict; blocked on budget. |
| any route needing **audited type assignment** | **BLOCKED** | `audited: false` on all 1455 subtasks. Type assignment is a tier-3 claim and no human audited these. |
| any route needing **"was the goal achieved"** | **BLOCKED** | the corpus has CI conclusions, not goal satisfaction. No mechanical source supplies the latter. |

### Caveats every downstream result inherits

1. **Two repositories is the minimum, not a sample of software.** Both are
   mature Python libraries with heavy CI. Nothing here generalises to
   application code, small projects, or other languages.
2. **PR decompositions are human commit hygiene**, shaped by review, rebase and
   squash policy — not agent decompositions. `reference_decomposition` is
   labelled `ONE STRATEGY'S OUTPUT` and must never be scored against as a target.
3. **42% of FAIL records fail only on non-code checks.**
4. **Part C's differing population is 55% one model** and provider drift cannot
   be excluded.
5. **The carrier 0s are definitional**, not measured.
