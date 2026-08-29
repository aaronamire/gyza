# Task corpus — Part A source assessment

**Status: STOP-AND-REPORT gate (A3). No extraction performed.**
Every number below is MEASURED against the tree or a live API on 2026-08-03,
not estimated. Probe commands are recorded so each is reproducible.

---

## A0. Citation check on the task prompt itself

The prompt's precedence chain names `research/THE_CORE.md`. **That file does not
exist** (`ls research/` — 33 entries, no `THE_CORE.md`). Precedence therefore
runs: committed FINDINGS > `research/BUILD_PLAN.md` > this prompt.

Two further prompt claims, checked:

| claim | verdict |
|---|---|
| "the corpus build gate landed exactly at 0.95 last time (38/40) and the two disagreements were a real substrate defect (repr-vs-value)" | **CONFIRMED.** `research/selection_routes/corpus_verification.json`: `agreement = 0.95`, `n_sample = 40`, two disagreements both `recorded: False → source_says: True`. One-directional, matching `mbpp_truth.json`'s `false_wrong = 11, false_correct = 0`. |
| "self-authored goals are the R14 B4 trap, which voided a cell and produced the definitional 0.0000 type-assignment number" | **CONFLATES TWO EVENTS.** R14 B4 voided the conservation cell (`FINDINGS_R14.md:319` — prompt/pipeline mismatch, 24/24). The `0.0000` is AR-3's ASSERTION-differing number (`FINDINGS_AR3.md:12`), definitional for a different reason: byte-identical objects admit no separating function. Both traps are real and both bear on this build; they are not one causal chain. |

The correction does not change the instruction — self-authored fixtures are
still disqualifying — but a corpus built on a fused citation would inherit it.

---

## A1. Candidate sources, in the prompt's priority order

### (i) This repository's git history — **CAN supply structure, CANNOT supply the verdict**

| property | measured | command |
|---|---|---|
| commits on `main` | 125 | `git rev-list --count main` |
| commits across all refs | 207 | `git rev-list --all --count` |
| **merge commits on `main`** | **0** | `git rev-list --merges main --count` |
| commits touching `tests/` | 51 | `git rev-list main -- tests/ \| wc -l` |
| `fix`/`revert` commits on `main` | 3 | `git log main --format=%s \| grep -icE '(fix\|revert)'` |
| date range | 2026-05-05 → 2026-07-22 | `git log main --date=short` |

**Two independent disqualifications, both measured.**

**(a) The DAG carries no decomposition structure.** The prompt's design property
says "STRUCTURE comes from the commit DAG (what was split into what)." With
**zero merge commits**, this history is a straight line: there is no
branch-and-merge unit anywhere in it. The only available grouping is the
scope prefix in commit *messages* (e.g. twelve consecutive
`research/correlated-failure: …` commits). That grouping rule would be **mine**,
applied to message text — one step from the commit-message sentiment the prompt
explicitly bans as a verdict source, and squarely inside the "if it is authored
rather than harvested" failure.

**(b) The execution verdict is degenerate.** Measured directly: 12 commits
sampled (`random.seed(7)`) from the 51 that touch `tests/`, each checked out into
a worktree, each running the test files that commit itself touched:

```
12 / 12 GREEN.  (2 passed … 37 passed; runtimes 0.23 s – 43.79 s)
```

**Exact 1 — diagnosed before reporting, per standing discipline. It is
DEFINITIONAL, not measured.** A commit is a snapshot its author published *after*
making its tests pass. Running a commit's own tests against its own tree recovers
"the author committed green", which is a property of the committing habit, not of
the goal. The outcome variable has no variance and cannot be a ground truth.

The three `fix`/`revert` commits are the entire non-degenerate population — too
few for anything, and each would still need me to decide what it was a fix *of*.

**The externality caveat the prompt asked for, stated plainly:** even had the
verdict survived, every goal in this history was authored by this same research
program. "External" would have been a word, not a property.

**Verdict: rejected as the decomposition source.** Not on strength-of-externality
grounds — on the harder ground that neither half of the required separation
exists here.

### (ii) External open-source repositories — **VIABLE, and it is the only viable one**

`gh` is authenticated (`amirewontmiss`) with **5000 req/hr, 4995 remaining**.
Probe repo: `scikit-learn/scikit-learn`, 200 closed PRs sampled.

| property | measured |
|---|---|
| merged / closed-unmerged | 128 / 72 — **unmerged fraction 0.360** |
| merged PRs with ≥3 commits | 14 / 35 (**0.40**) |
| merged PRs touching test files | 16 / 35 (0.46) |
| CI on merged head | 32/35 all-success, 3/35 contain a failure |
| **per-commit CI, 12 multi-commit PRs** | **FAIL 78, PASS 44, NONE 28** |
| PRs showing FAIL → … → PASS | **11 / 12** |

**This source satisfies the design property in the strong form.** The two halves
come from genuinely different places:

- **STRUCTURE** = the PR → commit mapping, recorded by GitHub when the author
  pushed. Not my grouping rule; not message text.
- **VERDICT** = CI check-run conclusions, computed by scikit-learn's own
  infrastructure, on hardware I do not control, before this corpus existed. Not
  merge status, not message sentiment, not my judgement of the change.

And it is **non-degenerate where the repo's own history was degenerate**: 52% of
per-commit CI conclusions are FAIL, and 36% of closed PRs were never merged.
Failures exist because CI ran on work *in progress*, which is exactly the state
our own history never records.

One caveat to carry forward: **28/150 commits have NO check-runs** (`NONE`) —
forks without CI enabled, or runs aged out of retention. Those records must be
dropped rather than defaulted to PASS. An absent verdict is not a passing one.

### (iii) The cached MBPP substrate — **supplies outcomes, no decompositions**, as the prompt says

`research/selection_routes/corpus.json`: 472 records. `mbpp_truth.json`: 196
records with `agreement_with_cached_label = 0.9439`, `false_wrong = 11`,
`false_correct = 0` — verdicts **re-derived by executing the MBPP asserts**,
which is genuinely external ground truth. Confirmed single-function tasks:
zero decomposition structure. The prompt's assessment is accurate and needs no
amendment.

---

## A2. Which source supplies which of the three needs

**No single source supplies all three — as the prompt anticipated. Composing.**

| need | source | strength | caveat |
|---|---|---|---|
| **decompositions** (SR-1, K-2) | **(ii) external PRs** | strong: structure and verdict from different origins, both external to this program | extraction cost; ~40% of PRs qualify, so a ≥60-goal target needs ~150+ PRs sampled |
| **stochastic outcomes** (SR-4, K-7) | see below — **currently unmet** | — | the credit gate fails; the one live cache is program-authored |
| **multi-agent traces** (AG-1..3) | none identified | — | Part D, attempted next |

### The stochastic requirement is in worse shape than the prompt assumes

**Part C's credit gate (C2) fails before it can be run.** Measured:

- `ANTHROPIC_API_KEY` is present; a 4-token probe returns
  `"Your credit balance is too low to access the Anthropic API."`
- **No `OPENROUTER_API_KEY` exists in the environment**, and every prior route's
  harness reads OpenRouter or `GROQ_API_KEY`. Balance is effectively 0 against
  any positive estimate, so `balance < 2 × estimate` holds and **C1 generation is
  STOPPED as instructed.**

Existing caches were then searched for a substrate that needs no new spend:

- Every cache file is `__s1` — **single sample** — and every `temperature=` in
  `research/*/*.py` is `0.0` except two `SAMPLE_TEMP = 0.7` arms. Confirmed:
  `find research -name "*__s[2-9]*.json"` → **0 files**.
- `route2_independence` M1 arm (K=4, temp 0.7): **80/80 entries are
  `__ERR__:HTTPError`** — the run died on HTTP 402 mid-flight. The route's own
  result file already records `m1_arm_usable: false`,
  `total_failed_402: 486 / 1280`. Dead.
- `route3_attractor` M1COT (K=4, temp 0.7, llama-3.1-70b): **80 tasks × 4
  samples, 0 errors — intact.** But `route3_attractor/items.json` is
  **program-authored** (hand-perturbed Monty Hall variants with hand-computed
  `true_answer`). Its ground truth is internal. Using it as SR-4's substrate
  would reproduce the exact trap this build exists to avoid.

**So the honest position: there is no stochastic substrate with external ground
truth, and none can be generated at present.** What source (ii) offers instead is
a *different* recovery signal — human FAIL → PASS trajectories within a PR, 11/12
of the multi-commit PRs sampled, externally verdicted by CI at zero cost. That is
a real retry-and-recovery population, but **it is human retry, not model
resampling**, and SR-4 must either be rescoped to that question or stay blocked.
Substituting one for the other silently would be the interpolation error recorded
as artifact #17: two quantities that share units and a plausible ordering are not
the same measurement.

---

## A3. Report, and the caveat every downstream result inherits

The prompt's A3 asks what to say "if the only viable decomposition source is this
repository's own history." **It is not — it is worse and better than that.** This
repository's history is not merely weakly external; it fails the design property
outright on two independently measured grounds (no merges, 12/12 definitional
green). External PR mining is not a fallback here, it is the only candidate that
works at all.

**The caveat SR-1 will inherit from source (ii)**, stated now so no route
discovers it mid-run:

1. **PR decompositions are not agent decompositions.** They are how a human
   author chose to sequence commits, shaped by review, rebasing, and squash
   policy. A strategy scored against them is being scored against human commit
   hygiene in one project's culture.
2. **Merged PRs are selected on success** (32/35 green heads). Any corpus drawn
   only from merged PRs re-imports the degeneracy that killed source (i). The
   closed-unmerged 36% must be carried, or the outcome variable collapses again.
3. **Single-repo culture is a confound.** ≥2 repositories with different review
   norms are needed before any number is read as a property of decomposition
   rather than of scikit-learn.
4. **`NONE` verdicts must be dropped, never defaulted.** 28/150 commits have no
   check-runs; an error is not a value.

**Requested decision before extraction begins:**

- **Proceed on (ii)** — mine ≥2 external repos for ≥60 goals, structure from
  PR→commit, verdict from CI check-runs, dropping `NONE`. This is the
  recommendation.
- **Part C** cannot be run as written. Either rescope SR-4 to the human FAIL→PASS
  population, or leave SR-4 blocked and say so in the manifest. Generating new
  samples requires credits that do not exist.
