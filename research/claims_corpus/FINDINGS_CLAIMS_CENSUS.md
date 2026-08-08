# Findings — the census over a hand-extracted, unselected claim corpus

> **THIS IS AN AUTHORED CORPUS AND AN AUTHORED CLASSIFICATION, both produced by
> the same agent. The H1 circularity is DOUBLED relative to the earlier census:
> I chose which sentences are claims, and then I classified them.** The freeze
> (§1) makes the two steps *separable* and the commit order proves they were
> separated — it does not make either step independent of me. Every number below
> should be read through that.

Zero credits. No model call, no API call — `issues_raw.json` was already
fetched and its selection audit already passed.

---

## 1. Freeze and audit — reported first

| | |
|---|---|
| corpus | `claims_hand.json`, **215 claims / 82 issues**, cap 3 per issue |
| **sha256** | **`c5928b3d6e121e9ae7655023d46896ff1125940e437d9ae13cfad334ff6fa941`** |
| **freeze commit** | **`9ab33b1`** — contained the corpus and *nothing else* |
| preregistration | `1c9b2b5`, parent = the freeze |
| classification | postdates both |

**A4 audit:**

| measure | result | judged by |
|---|---|---|
| fidelity — does the extraction match what the reporter asserted? | **40/40 = 1.000** | **me** (weak) |
| verbatim substring match, normalised | **28/40 = 0.700** | **mechanical** |

The 1.000 is an exact 1 scored by the extractor and is **not** offered as
reassurance; the 0.700 is the number I did not get to define afterwards. All 12
non-verbatim cases are faithful (elisions, truncations, one reconstruction), but
**the elisions run systematically toward brevity and away from hedging** — which
biases classification *against* finding UNDERDETERMINED. Recorded before
classification in `EXTRACTION_AUDIT.md`, so it could not be reached for later.

**Selection audit carried forward and NOT re-run** (it passed): 7-stage pipeline,
no stage filtered on verifiability/testability/actionability/resolution;
`not_planned` 3, `duplicate` 6, open 87 / closed 128 all present in the corpus.

---

## 2. The 4×4 joint distribution

| | INTERNAL | UNDERDETERMINED | EXOGENOUS | CONTESTED | UNSURE | row |
|---|---|---|---|---|---|---|
| DECLARATIVE | 0 | 0 | 0 | 0 | 0 | **0** |
| COMMISSIVE | 0 | 0 | 0 | 0 | 0 | **0** |
| DIRECTIVE | 30 | 13 | 3 | 0 | 0 | **46** |
| **ASSERTIVE** | **99** | **35** | **23** | **12** | 0 | **169** |
| **total** | **129** | **48** | **26** | **12** | **0** | **215** |

**No cell rests on a single issue** (checked at issue granularity, since the cap
is 3 per issue).

### Two empty rows and one empty column — diagnosed before reporting

**DECLARATIVE = 0 and COMMISSIVE = 0.** Structural, and the diagnosis is the
genre: **nobody files a bug report to *constitute* something.** A declarative
succeeds by felicity — a signature, a naming, a ruling — and issue *bodies* do
not contain those (closing an issue is an action, not a sentence in the body).
Commissives are absent for the same reason: reporters report and request, they
do not promise. **Contributing factor disclosed:** extraction rule R1 asked for
assertions *about the software*, which would suppress declaratives if any
existed. R2 explicitly kept imperatives and proposals, and those came through at
46, so the rule is not suppressing non-assertives generally.

**UNSURE = 0, and this one is DEFINITIONAL, not confidence.** The criterion is a
four-question procedure whose **Q4 is a catch-all** (*"otherwise → EXOGENOUS"*).
**It structurally cannot emit UNSURE.** Reporting 0 as evidence of confident
classification would be wrong. The real consequence: **anything I could not
resolve was absorbed into EXOGENOUS**, which *inflates* f and makes FAVOURABLE
*harder* to reach — the conservative direction, by design, but it means
EXOGENOUS is an upper bound on genuine exogeneity, not a measurement of it.

---

## 3. The decision

> **f = (23 EXOGENOUS + 12 CONTESTED) / 169 ASSERTIVE = 0.2071**
>
> # CENSUS-FAVOURABLE

### Robustness, because a favourable result needs its counter-metric

Reaching `f ≥ 0.50` requires **84** assertive claims in EXOGENOUS+CONTESTED; there
are **35**. So **50 more would have to flip** — out of **51** assertive judgement
calls currently sitting in INTERNAL or UNDERDETERMINED.

> **97% of my flippable assertive judgement calls would have to be wrong, all in
> the same direction, to move this out of FAVOURABLE.** The verdict is not
> balanced on a handful of calls.

### Predictions vs outcome

| prediction | predicted | actual | |
|---|---|---|---|
| **f** | 0.25 – 0.55 | **0.2071** | **missed low by 1.21×** |
| **UNDERDETERMINED non-empty** | ≥ 25 | **48** | ✅ |
| ASSERTIVE share | 0.55 – 0.80 | 0.786 | ✅ |
| DIRECTIVE share | 0.10 – 0.25 | 0.214 | ✅ |
| judgement fraction | 0.35 – 0.65 | 0.456 | ✅ |

The f miss is **1.21×**, far inside the ~3× diagnostic threshold. Contrast the
first census, which missed by **28×** — that magnitude was the tell of a broken
instrument, and nothing like it occurred here.

---

## 4. B4 — the vagueness check, and it clears

**The worry:** UNDERDETERMINED could be empty because *I* resolved vagueness
while reading. **The inverse worry**, equally real: UNDERDETERMINED could be a
relabeling of *"contains a hedge word"*.

| | count |
|---|---|
| claims containing an unfixed-referent term | **51** (0.237) |
| of those, classified UNDERDETERMINED | **21** (0.412) |
| **UNDERDETERMINED with NO such term** | **27** |
| **vague-term claims NOT classified UNDERDETERMINED** | **30** |

**The overlap is partial in BOTH directions, which is what clears both worries.**
UNDERDETERMINED is not the hedge-word set: 27 of 48 contain no flagged term, and
30 flagged claims are not in the class.

**And the term list turned out to be a poor proxy, for a nameable reason.** Its
biggest false positive is **`should`**, which marks *normativity*, not
*underspecification*:

> *"pd.date_range("2026-04-17 00:00", periods=24, freq="h") **should** return a
> DatetimeIndex of 24 hourly timestamps"* — fully determinate. Names the input,
> the call, and the expected output. INTERNAL.

That is the proxy-vs-protected-quantity species again, caught here rather than
shipped: **a hedge-word count measures wording; UNDERDETERMINED is about whether
the referent is fixed.** They correlate weakly and are not the same thing.

---

## 5. Judgement and UNSURE

| | |
|---|---|
| by **inspection** | **117 / 215 (0.544)** |
| requiring **judgement** | **98 / 215 (0.456)** |
| **UNSURE** | **0 — definitional (§2), not confidence** |

**Nearly half the classifications required judgement.** This is an authored
classification. The first census was 10/18 = 0.56 and said so; this is 0.456 and
says so.

---

## 6. THE COMPARISON THE FIRST CENSUS COULD NOT RUN

The first census's Part B3 wanted to compare Gyza's vocabulary against an
external one and **could not**, because its external vocabulary was selected on
checkability. This corpus is not. So the comparison runs:

| | Gyza's 18 claim types | external claims (215) |
|---|---|---|
| **DECLARATIVE share** | **0.556** (10/18) | **0.000** (0/215) |
| ASSERTIVE share | 0.389 (7/18) | 0.786 (169/215) |
| **f on the ASSERTIVE row** | **0.2857** | **0.2071** |

> **The `f` values are SIMILAR — 0.29 against 0.21. What differs by a factor of
> infinity is HOW MUCH OF THE VOCABULARY IS ASSERTIVE AT ALL.**

This is a sharper result than "Gyza's claims are more checkable", and it is not
the result I expected. **Within assertive claims, both vocabularies behave about
the same** — roughly a fifth to a quarter genuinely exogenous. Gyza's advantage
is **not** that its assertions are easier to check. It is that **56% of its
vocabulary does not assert anything at all**: a signature does not *claim* that a
key holder approved something, it *constitutes* approval, and there was never a
correspondence to check.

**That is Attack 3's vocabulary-design thesis, measured, on an unselected
external comparison** — and it relocates the thesis. The lever is not "make
assertions more checkable". It is **"make fewer claims assertive"**.

---

## 7. WHAT THIS LICENSES OR KILLS

### Attack 2 — **LICENSED, PROCEEDS.**
`f = 0.2071 < 0.50`. **A majority of assertive claims in an unselected,
externally-authored vocabulary are INTERNAL or UNDERDETERMINED, not EXOGENOUS.**
The UNDERDETERMINED class is real and substantial — **48 of 215 (22.3%)**, and
**35 of 169 assertive claims (20.7%)** — which is the class respecification acts
on. The competence bound covers a smaller region than sixteen routes suggested:
it covers the **23 EXOGENOUS + 12 CONTESTED**, not the assertive row.

**Scope it honestly:** licensed for *this* claim population — bug reports and
feature requests against mature Python libraries. Nothing here licenses a claim
about natural-language reasoning tasks, which is where the six mechanism
families were measured.

### Attack 3 — **LICENSED, PROCEEDS, and its thesis is RELOCATED by §6.**
The vocabulary-design lever is real and now measured against an external
baseline. But the mechanism is not the one the attack assumed. The gap is in
**speech act, not determinacy**: Gyza is 55.6% declarative, the external corpus
0%. Attack 3 should be rewritten around *"how much of a vocabulary can be made
non-assertive"*, because that is where the entire measured difference lives.

### The UNDERDETERMINED class is OBSERVABLE. The three prior failures are explained.

| attempt | vocabulary | why it failed |
|---|---|---|
| 1 | 240 CI check names | **selected on outcome** — a check exists because someone built it |
| 2 | Gyza's 18 registry types | **post-respecification** — everything movable had already moved |
| 3 | regex extraction from issues | **comprehension-blocked** — 0.900 fidelity, long-tail error |
| **4** | **hand extraction from the same issues** | **WORKED — 48 UNDERDETERMINED observed** |

Attempt 4 differs from 3 in exactly one respect: **a reader who can tell the
reporter's assertion from pasted output, meta-commentary and debris.** That
capability is what the previous route named as the blocker, and it is what made
the class visible.

---

## 8. Honest limits

1. **Doubled H1.** Corpus and classification are both mine. The freeze proves
   they were *sequential*, not that either is *independent*. **A second
   classifier over the same frozen corpus is the single cheapest thing that
   would strengthen this**, and it was not done.
2. **The elision bias runs against the finding**, which is the safe direction —
   UNDERDETERMINED survived an extraction that trimmed hedges. But no correction
   was applied and its size is unmeasured.
3. **`UNSURE = 0` is definitional.** Q4 is a catch-all, so EXOGENOUS absorbed
   everything unresolved and is an **upper bound**, not a measurement. True `f`
   is likely **lower** than 0.2071, which strengthens FAVOURABLE — but it means
   the 23 EXOGENOUS are not all demonstrably exogenous.
4. **Fidelity, not recall.** The audit asks whether what I extracted is faithful.
   **Claims I failed to notice are invisible**, and nothing in this route
   measures recall.
5. **Two repositories, one language, one genre.** SR-1 measured a 2.8× cross-repo
   failure-rate difference; two Python data-science libraries are not a sample of
   software.
6. **Q2's counterfactual is generous.** "Could this check be written" over a repo
   with a full test suite makes INTERNAL easy to reach. A stricter reading — "and
   would anyone actually write it" — would move claims toward UNDERDETERMINED,
   not EXOGENOUS, so it would not threaten the verdict, but it would change the
   INTERNAL/UNDERDETERMINED split.
