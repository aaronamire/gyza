# K-2's default shipped, and SR-1 depth-matched at 2.6× the corpus

**Branch `sr1-matched`.** **ZERO CREDITS** — `gh api` and arithmetic. 18/18
coordination tests pass.

---

## 1. PART A — THE DEFAULT IS SHIPPED, AND IT IS A **PARTIAL**

**A1, before changing anything:** `decompose()` raised `NotSelectedError`
naming SR-1 as the blocker. **A3: nothing called it** — the only references are
the `__init__` re-export and one test asserting it raises. **Blast radius: one
test.**

**But A1's instruction cannot be fully carried out, and the reason is in the
tree:** `TaskSpec` (`task.py:31-41`) carries `goal: str` and **no file list**.
CONSERVING is *file-partitioned*. **There is nothing for it to partition.** And
`grep claim_type gyza/` finds the field declared in `task.py:35` and **produced
nowhere**.

> **So K-2 is now SPLIT, and the split is the honest form:**
>
> - **the STRATEGY is shipped** — `DEFAULT_DECOMPOSITION_STRATEGY = CONSERVING`,
>   exported from `gyza.coordination`, with `DEFAULT_DECOMPOSITION_BASIS` beside
>   it;
> - **the IMPLEMENTATION still raises**, and the raise now names the *actual*
>   remaining blocker (claim-type assignment) instead of the resolved one.

**The basis, verbatim in the exported constant and in the raise message:**

> *"CONSERVING is the default because the architectural principle mandates
> partitioning on containment grounds. Its effect on task success is
> UNMEASURED — the causal comparison is blocked on ground truth, not budget."*

**A4 is pinned by test**, not by care:
`test_the_default_basis_does_not_claim_an_outcome_benefit` asserts `UNMEASURED`
and `containment` are present and that no outcome-claim wording
(`better outcome`, `improves`, `outperform`, …) appears. **That property is the
one most likely to be softened by a later edit, so it is enforced rather than
trusted.**

**Returning a fabricated decomposition would have been worse than raising** — the
stub was honest about not knowing.

---

## 2. B1 — THE SELECTION GATE, and the audit cited is for a **different corpus**

> **`research/claims_corpus/SELECTION_AUDIT.md` — the seven-stage pipeline trace
> — audits the CLAIMS corpus (GitHub ISSUES, used by the census and 1.B). It
> does NOT cover the decomposition corpus (PRs, used by SR-1).**

**Thirteenth premise of this shape.** The categories B1 asks me to confirm —
*closed-as-not-planned, duplicates, never-triaged* — are **ISSUE** states and do
not exist for pull requests.

**The decomposition corpus's actual selection properties, read from
`run_partB.py:214,43-44` and inherited UNCHANGED by the expansion:**

| property | effect |
|---|---|
| `pulls?state=closed&per_page=100&page=N` | **EXCLUDES OPEN PRs** — a resolution-status filter, present in the original |
| `MIN_COMMITS >= 3` | **EXCLUDES SHORT decompositions** |
| explicit in the source | *"CARRY THE UNMERGED POPULATION. A merged-only corpus selects on success"* — merged and unmerged both retained ✅ |

> **`MIN_COMMITS >= 3` is the one that matters, and it cuts against the arm
> under study.** FINDINGS_SR1 established conservation *"survives only in PRs
> short enough that no second round happened."* **The filter removes exactly
> where CONSERVING is densest**, so every conserving rate here is a **lower
> bound**. Not introduced by me; reported because an inherited filter left
> unstated is as misleading as a new one.

**The expansion uses the IDENTICAL query, pages 7+.** Selection properties are
unchanged, so the gate passes — with the correction that no audit ever covered
this corpus.

---

## 3. B2/B3 — THE EXPANSION

| | |
|---|---|
| original | 181 records (pages 1–6, 2 repos) |
| **added** | **299** (pages 7–13, scikit-learn) |
| **combined** | **480** — **2.6×** |
| target | 1150 (`FINDINGS_SR1.md:167`) |
| **shortfall** | **670 records — and it is WALL-CLOCK, not population** |

**The population is ample: 20,566 + 5,379 = ~26,000 closed PRs.** The binding
constraint was the 4,300-call budget (~17.6 calls/record); reaching 1150 needs
roughly **21,000 calls ≈ 4–5 hours**. **GitHub's rate limit was never the
constraint** — 4,988 remaining at the end.

### A harness bug, found by a zero and diagnosed rather than reported

**The first expansion run produced 0 records across 4 pages and 549 calls.** The
cause was mine: `check_taxonomy.classify` returns a **tuple** `(bucket, why)`
whose bucket is `CODE_SUBSTANTIVE`, and I compared it to the string
`"SUBSTANTIVE"`. It never matched, so every PR fell to `no_ci`.

> **Comparing against the wrong representation — the THIRD instance of that
> shape in this session** (the other being `len(reference_decomposition)`
> counting a dict's 3 keys as "depth 3" for every record, caught when REVISITING
> max came back 3 against a committed max of 100).
>
> **The fix is the general rule, not a patch:** `substantive_outcome()` already
> existed in the corpus and I had reimplemented it. It is now imported. **A
> reduction that exists should be called, not restated** — the same
> second-frame argument that governs the verifier registry.

### B3 — verification: **agreement 1.0000, and it is weaker than it looks**

20 new records re-fetched from the source and recomputed: **20/20 agree**,
against the original corpus gate of 0.95.

> **Diagnosing the exact 1: NEAR-DEFINITIONAL.** I re-fetched from the same API
> and recomputed with the **same frozen taxonomy**. That verifies the pipeline is
> **deterministic and faithfully stored** — it would catch transcription or
> storage error. **It does NOT verify the taxonomy itself**, because it reuses
> it. The original's 0.95 was a harder test and its two disagreements were a real
> substrate defect. **This check is strictly weaker and should not be read as
> matching it.**

---

## 4. B4/B5 — THE DEPTH-MATCHED ANALYSIS

### The asymmetry, stated so a future reader does not carry the wrong rule

> **OBSERVATIONAL data — structure was NOT assigned.** Task difficulty causes
> both depth and outcome, so **depth is a CONFOUNDER and matching on it is
> RIGHT.**
>
> **RANDOMIZED design — strategy IS assigned**, so nothing confounds it. Depth
> then lies on the path `strategy → depth → outcome`, making it a **MEDIATOR**,
> and **conditioning on it is WRONG.**
>
> **Same variable, opposite treatment. The difference is assignment, not data.**

### B5a — arm sizes per stratum

| depth | CONSERVING | REVISITING | |
|---|---|---|---|
| **3** | **32** | 108 | matchable |
| **4** | 5 | 57 | matchable |
| **5** | 3 | 56 | matchable |
| **24** | 1 | 1 | **matchable but STARVED** |
| 6–100 (all others) | **0** | 217 | starved — no conserving counterpart |

**The depth-24 stratum is 1 vs 1** and contributes nothing but noise; it is
reported rather than silently dropped.

### B5b — the effect

| | n | fail | rate | 95% CI (Wilson) |
|---|---|---|---|---|
| **CONSERVING** | **41** | 3 | **0.0732** | [0.0252, 0.1943] |
| **REVISITING** | 222 | 32 | **0.1441** | [0.1040, 0.1964] |
| **difference** | | | **+0.0710** | **CIs OVERLAP** |

> ### **THE ARM FLOOR IS CLEARED: CONSERVING n = 41 ≥ 15. H1 IS NOW EVALUABLE.**
> **And the answer is a NULL: +0.0710, well below the preregistered 0.167
> detectable difference, with overlapping CIs.**

**SR-1's exact zero is GONE, exactly as SR-1 predicted it would be.** It reported
`fail_conserving = 0.0000` and diagnosed it as small-sample with
`P(0 | null) = 0.174`. **At n = 41 it is 3/41 = 0.0732.** The zero was noise, the
diagnosis was right, and this is the cleanest available vindication of that
discipline.

**Replication check:** fraction conserving **0.0854** here vs **0.0782** in
SR-1 — stable across 2.6× the data.

### B5c — the counter-metric: **the entanglement PERSISTS**

**32 of 41 CONSERVING records (0.7805) are at depth 3**, against 11/14 (0.7857)
before. **Expansion did not decouple structure from depth.** Conservation
remains, in this population, close to a synonym for *short*.

### B6 — did matching CREATE the effect?

| | difference |
|---|---|
| **unmatched** (all depths) | **+0.0544** |
| **matched** (depths 3,4,5,24) | **+0.0710** |
| discarded REVISITING (depth ≥ 6) | fails at **0.1106** |

> **Matching INCREASED the apparent effect**, and the reason is the opposite of
> the usual worry: the discarded deep records fail at **0.1106**, **LOWER** than
> the matched revisiting rate of 0.1441. **In this corpus deeper decompositions
> fail LESS.**
>
> So the depth confound was **suppressing** the difference, not inflating it, and
> matching removed a suppressor. **The direction contradicts the intuition that
> deeper = harder = more failure** — which SR-1's H2 also failed to find
> (coefficient +0.174, p = 0.453). **Neither the matched nor the unmatched
> difference is significant**, so this changes nothing about the verdict; it
> changes what one should expect the confound to do.

---

## 5. PART C — WHAT THIS SETTLES

### C1. It does **not** answer the causal question

**Matching removes a KNOWN confounder. It cannot remove unknown ones.** SR-1
already identified a larger one: *"which repository the work happened in matters
more than how the work was split"* (2.8× between repos). **Randomization is what
would handle the unknown ones; this does not.** It **screens**.

### C2. THE GATE RECOMMENDATION — **screens strongly toward NOT running it**

| | before | **after this session** |
|---|---|---|
| gate 1 — free expansion | recommended | **DONE (partial, 2.6×)** |
| gate 2 — $62 pilot | hold | **HOLD, and now for a second reason** |
| gate 3 — experiment | $300–$3,000 | **$464–$4,600, and worth less** |

**The observed effect is 0.0710.** My causal design was powered for an
**authored** 0.08 and needed 195/arm. **At the measured 0.0710 it needs 301/arm**
— **55% more**, and cost scales with it.

> **So the free path did exactly what it was supposed to: it replaced an
> authored effect size with a measured one, and the measured one is SMALLER and
> NOT SIGNIFICANT.** An experiment sized on 0.08 would have been underpowered
> for the effect that is actually there.

**And the ground-truth blocker is untouched** — the causal experiment still has
no way to score agent work, which the pilot cannot fix.

### C3. D3's deflation survives, unchanged

**A large effect favouring CONSERVING would only confirm a choice the
architecture already forces on containment grounds. The outcome that would change
something is the opposite one** — CONSERVING materially *worse*. **This session
measured +0.0710 in CONSERVING's favour, not against it**, so even the observed
direction is the one that changes least. **An experiment worth running for one of
its two outcomes is worth less than a clean design suggests.**

---

## 6. Honest limits

1. **The expansion is scikit-learn only** (pages 7–13). pydantic was not reached
   before the budget ran out, so the new records **shift the repo mix** toward
   the lower-failing repo — and SR-1 measured repo as the strongest signal in the
   data. **This is a real limitation of the partial expansion**, and a full run
   must balance the repos.
2. **n = 480 of a 1150 target.** The shortfall is wall-clock, not population.
3. **`MIN_COMMITS ≥ 3` bounds every conserving rate from below** (§2).
4. **B3's 1.0000 verifies reproducibility, not the taxonomy** (§3).
5. **K-2 still raises.** The strategy is shipped; the implementation is not, and
   the remaining blocker is not a strategy question.
