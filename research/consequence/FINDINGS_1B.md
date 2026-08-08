# Findings — Attack 1.B, verification by consequence

Preregistered at **`774775d`** (blob `4b33efe`), the only file in
`research/consequence/` at that commit. Zero credits: GitHub API and arithmetic,
no model call. **Nothing was built** — this route runs the falsifier.

Substrate: the frozen census corpus, sha256 `c5928b3d…`, **215 claims / 82
issues**, with outcome timelines fetched for **all 82 (0 failures)**.

---

## 1. PART A — the discrimination distribution, and **s**

**All 215 claims are in the denominator, including those with no outcome
signal** — excluding never-triaged issues would select for claims that got
attention, which correlates with being checkable.

| class | n | fraction |
|---|---|---|
| **STRONG** | **66** | **0.3070** |
| WEAK | 68 | 0.3163 |
| NONE | 9 | 0.0419 |
| **UNRESOLVED** (right-censored) | 72 | 0.3349 |
| UNSURE | 0 | 0.0000 |

> ## **s = 66/215 = 0.3070**

**Counter-metrics beside it:** NONE = 0.0419, UNRESOLVED = 0.3349.

**Diagnosing UNSURE = 0:** **DEFINITIONAL, not confidence.** The bar is a
decision procedure over structured fields (`merged_prs`, `closing_commits`,
`state`, `state_reason`) with the speech act supplied by the frozen census. **No
judgement is exercised at application time**, so UNSURE cannot arise. The
authored input is upstream: the census's speech-act calls, **98/215 = 0.4558
judgement**, inherited wholesale.

### 1a. THE VERDICT IS A KNIFE-EDGE, and this is the most important line here

`s = 0.3070` clears the preregistered `0.30` threshold by **1.5 claims out of
215**. **Two reclassifications flip it.**

And a **defensible stricter reading of the same bar** does flip it:

| reading | s | verdict |
|---|---|---|
| **preregistered** — any merged PR cross-referencing the issue | **0.3070** | VIABLE |
| **stricter** — the merged link must be tied to the issue's *closure*, not merely mention it | **0.2326** | **NOT VIABLE** |

**I am NOT adopting the stricter reading.** The bar was frozen before data and
tuning it now is exactly what the preregistration forbids. **But the decision
below is reported as NOT ROBUST**, and a reader who prefers the stricter reading
gets CONSEQUENCE-INTERMEDIATE.

The third figure, for completeness: **among resolved claims only, s = 0.4062** —
biased *upward* by removing censoring, and reported only to bracket the true
value. **0.3070 is a lower bound** on the fully-resolved population; **0.2326 is
the lower bound under the stricter linkage reading.**

---

## 2. A4 — the complementarity cross-tab

| determinacy | n | STRONG | rate | issues / repos |
|---|---|---|---|---|
| INTERNAL | 129 | 43 | 0.3333 | 25 / 2 |
| **UNDERDETERMINED** | 48 | 9 | **0.1875** | 9 / 2 |
| **EXOGENOUS** | 26 | 13 | **0.5000** | 9 / **1** ⚠ |
| CONTESTED | 12 | 1 | 0.0833 | 1 / 1 ⚠ |

**The prediction HELD directionally: EXOGENOUS 0.5000 > UNDERDETERMINED
0.1875**, a 2.7× ratio in the predicted direction.

### But two cells are INCONCLUSIVE by my own preregistered rule

> *"Any cell driven by a single issue, repository, or signal type → report
> INCONCLUSIVE for that cell."*

- **EXOGENOUS: all 13 STRONG claims come from ONE REPOSITORY** → **INCONCLUSIVE**.
- **CONTESTED: its single STRONG claim comes from one issue in one repo** →
  **INCONCLUSIVE**.

**The `analyze.py` concentration check only covered the discrimination classes,
not the determinacy cells.** I found this by checking separately, and it
materially qualifies A4: **the headline complementarity number rests on a
single-repo cell.**

**What survives the qualification:** the *ordering* is visible across cells that
are not single-repo — INTERNAL (0.3333, 2 repos) sits above UNDERDETERMINED
(0.1875, 2 repos), and CONTESTED is lowest. That CONTESTED is near-zero is the
mechanism working as theory predicts: **a claim with no fact of the matter gets
no verdict from reality, because there is nothing for reality to be right
about.**

**So the complementarity claim is SUPPORTED but NOT ESTABLISHED.** The direction
is right and the mechanism is coherent; the decisive cell is single-repo and
needs a second repository before it can carry weight.

---

## 3. PART B — lag, with censoring reported beside it

**Right-censored: 72/215 = 0.3349.** These are open issues with no signal *yet* —
first-class, never folded into NONE.

Among the 66 STRONG signals:

| statistic | days |
|---|---|
| **median** | **7.0** |
| Q1 / Q3 | 2.0 / 19.0 |
| min / max | 0 / 75 |

| resolves within | fraction |
|---|---|
| 1 day | 0.2273 |
| **7 days** | **0.5758** |
| **30 days** | **0.8636** |
| 365 days | 1.0000 |

**The median is computed over STRONG signals only and is therefore conditional on
a signal having arrived** — it is *not* a median over all claims, and I do not
report it as one. With 33.5% censored, a Kaplan–Meier estimate over
time-to-STRONG would be the right statistic for the full population; **the
preregistration set that threshold at 20% censoring, so KM is indicated and its
absence is a gap, recorded in §6.**

### B2 — the operational consequence, stated plainly

**This is the result that surprised me.** I predicted a median of 20–90 days and
argued the channel would be retrospective. **Measured: 7 days, with 86% inside 30
days.**

> **At that lag the channel is not purely retrospective.** A 7-day median is too
> slow to gate an individual action, but it is fast enough to **inform a
> decision on the next one** — a policy that updates weekly can use it.
>
> **Decision-gating vs liability-settling is the right distinction, and this
> lands between them**: it cannot gate *this* action, but it can gate *this
> class* of action within a working week. That is a different and better product
> than bond settlement alone.

---

## 4. PART C — attribution

| | |
|---|---|
| STRONG with **exactly one** link (clean) | **53/66 = 0.8030** |
| counter-metric: **MULTI-link** | 0.1970 |
| link-count distribution | 1 → 53, 2 → 10, 3 → 3 |

**a = 0.8030**, comfortably above the 0.60 threshold. Attribution is *not* the
binding constraint here, which was not obvious in advance — the channel's
reputed weakness turns out to be its strongest leg.

### C3 — would attribution be easier for AGENT claims? **AUTHORED JUDGEMENT**

**Yes, and materially — but this is judgement and is not smuggled into the
decision.**

Bug reports are unstructured and arrive from many parties; the 19.7% multi-link
rate is a commit fixing several reported issues at once. **An agent claim could
carry an identifier that a downstream outcome references**, making attribution
near-exact by construction rather than by inference.

> **This is the main reason a negative here would not have generalised** — and,
> symmetrically, **the reason this positive should not be over-read.** The
> measured `a = 0.8030` is for a population with *no* attribution machinery. It
> is a floor for a designed one, not a prediction about it.

---

## 5. THE DECISION

| statistic | value | threshold | margin |
|---|---|---|---|
| **s** | **0.3070** | ≥ 0.30 | **1.5 claims — knife-edge** |
| **a** | **0.8030** | ≥ 0.60 | comfortable |
| **median STRONG lag** | **7.0 d** | < 30 d | comfortable |

> # CONSEQUENCE-VIABLE — by the preregistered rule, and NOT ROBUST.

**All three conditions are met and the rule fires.** But the fragility is
entirely in `s`, and I will not report this as a clean positive:

- **two reclassifications flip it**;
- **a stricter linkage reading gives 0.2326 → INTERMEDIATE**;
- **the A4 cell that makes the complementarity case is single-repo.**

**What 1.B concluded:** the channel is **real and worth designing**, and it is
the first mechanism in this program to clear its own preregistered bar. **It is
not established.** The honest summary is *"viable at the boundary, on one
population, with the decisive complementarity cell unreplicated."*

**Predictions scored:**

| prediction | predicted | actual | |
|---|---|---|---|
| s | 0.15 – 0.35 | 0.3070 | ✅ top of range |
| a | 0.55 – 0.80 | 0.8030 | ⚠ marginally **above** the top |
| median lag | 20 – 90 d | **7.0 d** | ❌ **missed low by 2.9×** |
| censored | 0.35 – 0.50 | 0.3349 | ❌ missed low, just outside |
| A4 holds | yes | directionally yes | ⚠ decisive cell INCONCLUSIVE |

The lag miss is the substantive one and sits just inside the ~3× diagnostic
threshold. **It moved the product category** — I predicted settlement-only and
measured something that can inform decisions weekly.

---

## 6. Honest limits

1. **The verdict is not robust.** §1a. A stricter reading of the same bar gives
   INTERMEDIATE. The preregistered rule is reported because it was frozen, not
   because it is more defensible than the alternative.
2. **The A4 complementarity cell is single-repo**, so the finding most relevant
   to the program — that consequence verification reaches the class the other
   six mechanisms cannot — is **supported, not established.**
3. **No Kaplan–Meier estimate was computed** despite 33.5% censoring exceeding
   the 20% trigger I set. The reported median is conditional on a signal having
   arrived; a KM estimate over the full population would be **higher**, which
   would weaken the lag result, not strengthen it.
4. **Scope: bug reports against two mature Python libraries.** It licenses claims
   about that population. **C3's judgement about agent claims is labelled as
   judgement and is not part of the decision.**
5. **The STRONG bar credits a merged PR that cross-references an issue.** That a
   fix merged does not *prove* the reporter's claim was true — it shows
   maintainers acted as if it were. **Reality's verdict here is mediated by human
   judgement**, which is weaker than the "verifier is reality" framing suggests
   and is the deepest caveat on the whole route.
