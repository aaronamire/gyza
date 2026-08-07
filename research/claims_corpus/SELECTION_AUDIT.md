# Selection audit + extraction verification — Part A

**Part B was NOT reached.** The A2 selection gate **passed**; the A4 extraction
gate **failed at 0.900 against a 0.95 bar**, after two rounds of targeted fixes.
Per the route's own instruction — *"Below 0.95, STOP — the extraction is
unreliable and the census would measure it rather than the claims"* — no
classification was performed and no census was run.

Zero credits. `gh api` and regex only; **no model call anywhere**, including for
segmentation.

---

## A1 — source selection

| candidate | (1) externally authored | (2) claims not checks | (3) large enough | verdict |
|---|---|---|---|---|
| **(i) issue / bug-report bodies** | ✅ reporters | ✅ **written before triage decides anything** | ✅ 386 issues → 835 claims | **CHOSEN** |
| (ii) PR descriptions | ✅ authors | ❌ **fails** | ✅ | rejected |
| (iii) requirement / acceptance criteria | — | — | ❌ **do not exist** | unavailable |

**(ii) fails requirement (2), which is the requirement that killed the last
census.** A PR exists because someone already decided to act; in both these
repos a PR normally ships with a test. A PR description is therefore
*downstream of the decision that the thing was actionable*, which is a weaker
form of the same selection that made CI check names useless.

**(iii) was checked, not assumed.** Neither repo has a requirements or
acceptance-criteria artifact; `pandas-dev/pandas` has `requirements-dev.txt`,
which is a dependency list.

**(i) is chosen precisely because the assertion predates any decision about
testability.** A reporter writing *"X is broken"* has no idea whether anyone
will find it checkable.

---

## A2 — THE SELECTION GATE: **PASSES**

### Full pipeline trace, stage by stage

| # | stage | could it remove claims for being unverifiable? |
|---|---|---|
| 1 | reporter writes an issue | **No.** Written before triage exists. |
| 2 | GitHub stores it | **No.** No filter. |
| 3 | `GET /issues?state=all` | **No.** `state=all` returns open **and** closed. |
| 4 | pagination, `sort=created&direction=desc` | **No selection on outcome.** Issue numbers are sequential at creation, so this is a contiguous creation-order slice. It *does* carry a **recency bias** — disclosed below. |
| 5 | exclude `pull_request` | **No — TYPE filter.** A PR is a proposed change, not a report of what is wrong. |
| 6 | exclude empty body | **No — PRESENCE filter**, and it removed **0 issues**, so it never fired. |
| 7 | extraction (A3) | **No.** Sections are dropped only for being non-prose. |

**There is no other stage. No stage filtered on verifiability, testability,
actionability, or resolution status.**

### The named hazards, MEASURED

| hazard | result |
|---|---|
| closed-as-`not_planned` (wontfix / invalid) **included?** | **YES — 7** |
| `duplicate` **included?** | **YES — 8** by `state_reason`, 9 by label |
| never-triaged **included?** | **YES — 34 unlabelled (8.8%)**, plus 96 labelled `needs triage` |
| open vs closed | **168 open (43.5%) / 218 closed (56.5%)** — not selected on resolution |
| `reopened` | 3, included |
| pagination biased toward resolved? | **No** — creation-order slice; if anything biased toward *un*resolved |

Labels `wontfix` and `invalid` return 0 because **these repos do not use those
label names** — the equivalent signal is `state_reason = not_planned`, which is
present and included. Reporting "0 wontfix" without that check would have been
a false all-clear.

### Population and sample, stated separately

| | count |
|---|---|
| raw items walked (both repos) | 2 000 |
| of which pull requests (excluded, type) | 1 614 |
| of which empty body (excluded, presence) | 0 |
| **ISSUES = the population** | **386** |
| scikit-learn / pandas | 211 / 175 |
| issues yielding ≥1 claim | 332 |
| **CLAIMS = the sample** | **835** |
| per-issue cap | 3 |

**Disclosed residual bias:** recency. These are the most recent ~1 000 items per
repo. Recent issues skew toward open and untriaged — a bias in the direction
that **reduces** selection on verifiability, which is the safe direction for
this route, but it is a bias and it is not corrected for.

> **A2 VERDICT: PASS.** Requirements (1) and (3) met; requirement (2) met by
> construction and verified against every named hazard.

---

## A3 — extraction

Fully mechanical: sectioning, noise stripping, sentence splitting, a statement
filter, and a 3-per-issue cap so no single verbose report can dominate a cell.
The section allow/deny lists and the statement heuristics are **authored** and
declared in full in `extract_claims.py`.

**No model was used, for segmentation or anything else.** The route permitted a
model for segmentation only; it was not needed, so the credit gate never opened.

**The extraction does not pre-filter on speech act or verifiability.** Sections
are dropped only for being non-prose (code, version dumps, checkbox forms,
boilerplate). Imperative and proposal statements are kept — the census's
DIRECTIVE and COMMISSIVE classes exist for them, and filtering them at
extraction would have biased axis 1.

Resolution status is **recorded on every claim and never used as a filter**.

---

## A4 — THE EXTRACTION GATE: **FAILS at 0.900**

Three hand-verifications, each against the source issues, each on a **fresh**
sample (seeds 1, 2, 3 — no sample was re-scored after being seen).

| round | fixes applied | agreement | verdict |
|---|---|---|---|
| 1 | none | **25/30 = 0.833** | FAIL |
| 2 | 4 targeted | **27/30 = 0.900** | FAIL |
| 3 | 3 further targeted | **27/30 = 0.900** | FAIL |
| | | **gate = 0.950** | |

**Two rounds of fixes were applied and then I stopped, by prior decision.**
Fixing the instrument before measuring is what this gate is *for*, and no
classification had been done, so there was no result to tune toward. But
iterating indefinitely would overfit the extractor to the audit samples, so the
round count was fixed at two before round 3 was drawn.

### Why it stalled — and this is the finding

Seven targeted fixes moved agreement 0.833 → 0.900, then **it stopped moving**.
Every fix retired one *surface form*; the next fresh sample produced a different
surface form **of the same category**:

| category | r1 | r2 | r3 |
|---|---|---|---|
| pasted program output | pure code | `ValueError: …` | `output (pandas 3.0): np.float64 …` |
| meta-commentary about the report | — | *"Hopefully the reproducible code…"* | *"The code to reproduce the issue is below."* |
| malformed fragment | markdown remnant | — | unbalanced paren mid-list |
| question / imperative | non-terminal `?` | repro step | — |

> **The residual error is a LONG TAIL, not a fixable few.** Each of the three
> categories that survived to round 3 had already been "fixed" once. A regex
> retires an instance; the category persists.

### The deeper reason, and it is the point

The three residual categories all require the same judgement: **is this sentence
the reporter speaking about the software, or is it something else** — the
program's own output, the reporter talking about their report, or debris. That
judgement is *reading comprehension*.

> **The only instrument that would reliably make it is a language model — and
> A3 forbids using one, because doing so reimports the competence bound into the
> instrument that is supposed to measure the competence bound.**

That is not an accident of this implementation. **The route to measure whether
the competence bound decomposes is blocked by the competence bound itself, one
level down, at corpus construction.** A model-segmented corpus would measure the
segmenter; a regex-segmented corpus measures the regex at 0.900.

---

## What was produced, and what it is worth

| artifact | status |
|---|---|
| `issues_raw.json` | 386 issues, selection-audited, **PASS** — reusable |
| `claims.json` | 835 claims, **0.900 fidelity — BELOW GATE, not census-grade** |
| `verify_sample{,2,3}.json` | the three audit samples, scored |

**`claims.json` is not void — it is under-verified.** The selection audit that
killed the previous corpus is the part that *passed* here. What failed is a
different and more tractable problem, and the corpus is retained so a future
attempt does not re-fetch or re-audit selection.

**Do not run a census on it at 0.900.** A 10% extraction error is not obviously
neutral across the axes: pasted program output would classify INTERNAL (it is a
mechanical fact), and meta-commentary would classify CONTESTED — so the error is
**correlated with the classes the decision statistic is computed over**, and
could move `f` in either direction by an unknown amount.
