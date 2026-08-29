# SR-1 — FINDINGS. Decision: **H1 NOT-EVALUABLE, H2 NULL, H3 MISSED (in the informative direction)**

Preregistration `PREREGISTRATION_SR1.md`, sha256
`4dd64e7d795f7c28598f36486b9938dfb86167bdaf2997ae7f93af235a30e6d9`, committed at
`fc3a65a` **before** any structure-outcome association was computed. Result
artifact `sr1_result.json`. No tuning after results.

**Void checks passed:** `commit_files.json` covers **100%** of subtasks
(missing fraction 0.0000 against a 0.10 void threshold), and 0 records were
UNDEFINED.

---

## The headline

**The interesting result is the tertiary one, and it is not the one I expected.**

> **Only 7.8% of real decompositions preserve conservation.** 165 of 179 revisit
> at least one file across subtasks. My preregistered prediction was 0.20–0.35;
> the observed 0.0782 is **below the entire predicted interval**.

The primary hypothesis could not be tested *because* of this: the CONSERVING arm
came to **n = 14**, one short of the preregistered minimum of 15, so H1 is
reported **NOT-EVALUABLE** rather than null. That threshold was fixed before
data and it is not moved now.

---

## H1 (PRIMARY) — NOT-EVALUABLE

| arm | n | substantive FAIL rate |
|---|---|---|
| CONSERVING | **14** | **0.0000** |
| REVISITING | 165 | 0.1273 |

**Decision: NOT-EVALUABLE** — `min(arm) = 14 < 15` (preregistration §6). The
route stops here for H1 rather than reporting the 0.127 difference, which would
otherwise have cleared the 0.167 threshold only by luck of a 14-record arm.

### Diagnosing the exact 0, before reporting it

`fail_conserving = 0.0000` is an exact 0 and is **small-sample, not a signal**:

- expected failures in the arm under the null = `14 × 0.1173 = 1.64`;
- **P(0 failures | null) = 0.174**.

Seeing zero failures in 14 draws at this base rate happens roughly one time in
six. It is unremarkable and carries no evidence. Reporting it as "conserving
decompositions never fail" would be the artifact this ledger exists to prevent.

### The counter-metric fired: CONSERVING is very nearly just SHORT

Preregistration §5.3 required checking whether conservation collapses into
depth. It does:

- CONSERVING depths are `[3,3,3,3,3,3,3,3,3,3,3,4,4,5]` — **11/14 are depth 3**,
  against a REVISITING median of 5 (max 100);
- and **the same 11/14 are the records already flagged for leakage risk**
  (`n_sub ≤ 3`, the `code → test → changelog` convention).

So on this corpus "conservation-preserving" and "minimum-length convention PR"
are close to the same set. **Even had n reached 15, H1 would have been confounded
with depth and could not have been read as a structural effect.** That is a
finding about the property, not merely a caveat about the sample.

One thing that does *not* collapse: CONSERVING records touch **more** files
(median 3 vs 2) in **fewer** commits. They are wide and shallow — one pass over
several files — rather than small.

---

## H2 (SECONDARY) — NULL

Logistic model, the two preregistered predictors only (21 events, EPV 10.5):

| term | coefficient | p |
|---|---|---|
| `log2(depth)` | **+0.174** (se 0.232) | **0.453** |
| `log10(1+n_files)` | −0.180 | 0.812 |

**Decision: NULL.** The sign is as predicted (deeper → more failure) but the
estimate is well inside noise. Given the preregistered ceiling — the best
possible split detects only a 0.167 absolute difference — this is an
**underpowered null**, and no claim that depth does not matter follows from it.

**The confound stands regardless of the result**, as stated in advance: depth is
not randomly assigned. A harder goal produces both more commits and more CI
failures, and `n_files` is a weak proxy that does not remove this. **No causal
claim is made from H2 under any outcome.**

---

## H3 (TERTIARY) — 0.0782, prediction MISSED

| | value |
|---|---|
| conserving | 14 |
| defined | 179 |
| **fraction conserving** | **0.0782** |
| predicted | 0.20–0.35 |

**I over-predicted by roughly 3×**, and the miss is the informative part.

**Why the real number is so low.** A decomposition stops conserving the moment
any file is touched twice. Review comments arrive *after* the first push, so the
second, third and fourth commits go back into files the first one already wrote.
Measured on this corpus, **30.6% of all subtasks are review residue** (`nit`,
`fix`, `wip`, `cln`, merge-from-main). Conservation is not a property authors
fail to achieve — it is a property that **the review process destroys after the
fact**, and it survives only in PRs short enough that no second round happened.

### Why this matters beyond SR-1

The architectural principle — *append-only, partitioned, derived-not-stored* —
buys its guarantees from exactly the partition shape measured here. This is the
first measurement of how often real work has that shape without being asked to,
and the answer is **7.8%**.

That is **not** evidence against the principle. The principle is a *design
constraint you impose*, and the whole point of imposing it is that it does not
arise on its own. What the number does establish is the **size of the imposition**:
adopting partitioned decomposition means diverging from what 92% of observed
human decompositions actually do, and any cost estimate that assumed the shape
was common was wrong by an order of magnitude.

---

## Counter-metrics, reported beside the headline (preregistration §5)

| | scikit-learn | pydantic |
|---|---|---|
| n (defined) | 121 | 58 |
| conserving / revisiting | 10 / 111 | 4 / 54 |
| FAIL conserving | 0.0000 (0/10) | 0.0000 (0/4) |
| FAIL revisiting | 0.0811 | 0.2222 |

**No Simpson reversal**: the direction is identical in both repositories. But
both conserving arms are far too small to carry any weight (10 and 4), so the
consistency is not evidence either.

The 2.8× difference in REVISITING failure rate between the two projects (0.081
vs 0.222) is larger than any structural effect measured here — **which repository
the work happened in matters more than how the work was split.** That is the
strongest signal in the data and it is a confound, not a result.

---

## What SR-1 does and does not license

**Licensed:**

- Real human decompositions are overwhelmingly non-partitioning (0.0782, n=179,
  two repositories, 100% subtask coverage).
- The mechanism is review-driven revisiting, supported by the 0.306 residue rate.

**Not licensed:**

- Any claim that conservation-preserving decomposition improves outcomes. H1 is
  NOT-EVALUABLE and would have been depth-confounded regardless.
- Any claim that depth does or does not affect outcome. H2 is an underpowered
  null.
- Any causal reading of either. This is observational; structure was not
  assigned.

**What would make H1 evaluable:** the binding constraint is the CONSERVING arm,
not the corpus. At the observed 7.8% rate, reaching a 50/50 split with the
preregistered 0.167 detectable difference needs roughly **1150 records** — about
6.4× this corpus — and even then the depth confound would remain unless
conserving and revisiting records were matched on depth. Matching on depth is
the cheaper fix and should come first.
