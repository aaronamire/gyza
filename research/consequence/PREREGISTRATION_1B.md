# Preregistration — Attack 1.B, verification by consequence

**Committed BEFORE any measurement.** Zero credits: GitHub API and arithmetic
only, no model call.

> **The idea:** every mechanism this program tested checks a claim at
> **production time**, and all six families failed because a model stood
> somewhere in the checking path. Verification by consequence does not check the
> claim at all — a claim about the world makes a **prediction**, and reality
> delivers a verdict later as a byproduct of operating. **The verifier is
> reality, so the competence bound does not apply.** What it forfeits is
> synchronicity.
>
> **This route does NOT build the mechanism. It runs the falsifier.**

---

## 1. Substrate

| | |
|---|---|
| corpus | `research/claims_corpus/claims_hand.json` |
| **sha256** | **`c5928b3d6e121e9ae7655023d46896ff1125940e437d9ae13cfad334ff6fa941`** |
| claims / issues | **215 / 82** |
| frozen classifications | `research/claims_corpus/classify.py` — index-aligned, verified |
| timestamps | joined from `research/claims_corpus/issues_raw.json` (`created_at`, `closed_at`) |

**Correcting the task's framing:** the census classified **233 claims across two
vocabularies** — 215 external + 18 Gyza registry types. **This route uses the 215
external claims only**, drawn from 82 issues sampled (SEED=1) out of 386
selection-audited issues.

## 2. Gate 0d — is the OUTCOME data itself selected?

The **selection audit passed** for claim *capture* and is not re-run. The
distinct question is whether the **outcome** signal is selected:

- Resolution status was **RECORDED at capture and never used as a filter** — the
  corpus contains 87 open / 128 closed claims, plus `not_planned` (3) and
  `duplicate` (6). That recording is what makes this route possible now.
- **Issues never triaged have no outcome.** Excluding them would select for
  claims that got attention, which correlates with being checkable — the same
  error that voided the first census.
- **Therefore: claims with no outcome signal are INCLUDED IN THE DENOMINATOR**
  and reported as their own category.

**One residual bias, disclosed:** the corpus is the most recent ~1000 items per
repo, so it over-represents young issues, which are **less likely to have
resolved**. This biases the STRONG fraction **downward** and the censoring
fraction **upward** — the conservative direction for a channel trying to prove
itself.

## 3. The discriminating-signal definition, verbatim

> **A signal S discriminates for claim C iff S would plausibly DIFFER had C been
> false.**

Discrimination is the whole content. **A signal that occurs equally whether the
claim was true or false verifies nothing, however reliably it arrives.**

### The observable signal vocabulary

Learned by probing issues **outside the sample**, so no sampled claim's outcome
was seen before this bar was fixed: `closed` (optionally carrying `commit_id`),
`cross-referenced` (source is a PR or issue, carrying merge status and
timestamp), `commented`, `labeled`.

### The bar, fixed now

**Discrimination depends on the CLAIM as well as the signal**, so the frozen
census speech act is part of the rule:

| class | condition |
|---|---|
| **STRONG** | a **merged PR cross-references** the issue, **or** the issue was closed by a commit — **AND** the claim is **ASSERTIVE**. A code change would plausibly not have been merged had the asserted behaviour not existed |
| **WEAK** | a merged code link exists but the claim is **DIRECTIVE** (a proposal) — the change may have been made for other reasons, the coincidence problem; **or** closed-as-`completed` with **no** code link |
| **NONE** | closed as `not_planned` or `duplicate` with no code link; **or** closed with no linkage of any kind |
| **UNRESOLVED** | still open, no signal yet — **a first-class category, right-censored, never folded into NONE** |
| **UNSURE** | I cannot tell whether the signal discriminates — reported **separately** from NONE |

**Worked examples fixing the standard** (from the task, adopted verbatim as the
calibration): a linked commit changing the named function **DISCRIMINATES**; a
close-as-stale **does not**; a merged performance fix discriminates **weakly**; a
deprecation discriminates on a normative claim **only if** done for that reason,
otherwise coincidence.

## 4. Attribution and lag, defined now

**ATTRIBUTION.** A STRONG signal has **CLEAN** attribution iff **exactly one**
merged PR or closing commit links to the issue. Two or more → **MULTI**: a commit
fixing three reported bugs attributes cleanly to none.

**LAG.** Days from `created_at` to the **earliest** discriminating signal
(merged-PR cross-reference timestamp, or `closed_at` when the signal is the
close). **Open issues are RIGHT-CENSORED.** A median over resolved-only would be
biased downward and will not be reported as the median; censoring is reported
beside it, and a Kaplan–Meier estimate is used if censoring exceeds 20%.

## 5. Decision rule

Let **s** = fraction of all 215 claims with a STRONG signal; **a** = fraction of
those with clean attribution.

| outcome | condition |
|---|---|
| **CONSEQUENCE-VIABLE** | `s ≥ 0.30` **and** `a ≥ 0.60` **and** median STRONG lag < 30 days → proceeds to design |
| **CONSEQUENCE-SETTLEMENT-ONLY** | `s ≥ 0.30` and `a ≥ 0.60` but median lag ≥ 30 days → real but retrospective; settles bonds, cannot gate actions |
| **CONSEQUENCE-DEAD** | `s < 0.15` **or** `a < 0.40` → **CLOSE 1.B** |
| **CONSEQUENCE-INTERMEDIATE** | anything else |

**Any cell driven by a single issue, repository, or signal type → INCONCLUSIVE
for that cell.**

## 6. Point predictions, stated now

The first census missed by **28×** on a broken instrument (a vocabulary selected
on checkability); the claims census missed by **1.21×** on a sound one. **This
instrument is sound in the same way the second was** — outcomes were recorded at
capture without being selected on — so I predict at the second's precision, not
the first's.

| prediction | value |
|---|---|
| **s** (STRONG fraction) | **0.15 – 0.35** |
| **a** (clean attribution among STRONG) | **0.55 – 0.80** |
| median lag among STRONG | **20 – 90 days** |
| censored (still open) | **0.35 – 0.50** |
| **A4: EXOGENOUS more consequence-verifiable than UNDERDETERMINED** | **yes** |
| judgement fraction | **0.30 – 0.60** (census was 0.456) |

**Prior: 45% SETTLEMENT-ONLY / 30% DEAD / 15% INTERMEDIATE / 10% VIABLE.**

### A4 — the complementarity prediction, stated before data

**EXOGENOUS claims should be MORE consequence-verifiable than UNDERDETERMINED
ones**, because an exogenous claim is precisely one whose truth lives in the
world — which is where the verdict comes from. **If that holds, consequence
verification covers exactly the class the other six mechanisms cannot, and the
two are COMPLEMENTARY rather than competing.** If it does not hold, the channel
does not reach the class it was proposed for, and I will say so.

## 7. Honesty conditions

- **CONSEQUENCE-DEAD IS A SUCCESS.** It would close the last channel proposed as
  an escape from the competence bound and complete the map. **No rescue corpus
  will be proposed.**
- **The STRONG/WEAK line is an AUTHORED JUDGEMENT.** Judgement fraction reported,
  and **UNSURE reported separately from NONE** — *"I cannot tell whether this
  discriminates"* and *"it does not discriminate"* are different claims.
- Counter-metrics throughout: **s beside NONE, a beside MULTI, lag beside
  censoring.**
- **Scope:** this measures **bug reports against mature Python libraries**. It
  licenses claims about that population. **Whether it generalises to agent claims
  is C3's judgement and is labelled as one, never smuggled into the decision.**
- **No tuning of the bar after seeing what clears it.** Refinement would be a
  FINDING about the bar, with every reclassification named.
