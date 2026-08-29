# Stress test — adversarial re-reading of the census verdict

## What this is NOT, stated first because it decides how much the number is worth

> **This is the same agent, adversarially instructed, with the verdict already
> known.** I wrote the corpus, wrote the classification, and knew `f = 0.2071`
> before starting. It **cannot rule out a systematic bias shared by both
> passes**: a criterion I read one way throughout would be read that way in both
> directions, and nothing here would detect it.
>
> **It measures whether individual calls are robust. It does not measure whether
> the criterion is applied correctly.** Independent replication remains the thing
> that would settle this and remains unavailable.

**This is explicitly NOT an inter-rater agreement measurement.** A
re-classification by the same agent in the same session measures memory and
would return high agreement by construction; reporting it as inter-rater
agreement would be the most misleading number this program has produced.

What it *is*: the original robustness arithmetic counted 51 flippable calls
**without attempting to flip them**. This attempts it.

---

## A1 — the adversarial pass

Procedure: take the **98 claims classified by judgement** (not the 117 by
inspection). For each, write the strongest case for moving it toward
EXOGENOUS/CONTESTED **first**, then decide. The bar is not *"could this be
exogenous"* — almost anything could under a loose reading — but the frozen
criterion applied honestly: **does Q2 fail AND Q3 fail?**

| | |
|---|---|
| judgement calls re-argued | **98** |
| **FLIPPED** | **19 (0.194)** |
| HELD | 79 |
| of the flips, **moving f** | **14** (5 were INTERNAL→UNDERDETERMINED, which does not touch f) |

### The arithmetic that matters

| | |
|---|---|
| baseline | `f = 35/169 = 0.2071` |
| **after adversarial pass** | **`f = 49/169 = 0.2899`** |
| required for `f ≥ 0.50` | 84 assertive claims in EXOGENOUS+CONTESTED |
| **short by** | **36** |

> ## **CENSUS-FAVOURABLE SURVIVES.**

Stated as the prompt requires: **fewer than 49 assertive claims flipped (14 did),
so FAVOURABLE survives adversarial re-reading by its own author.** That is a
**weaker** claim than independent replication and a **stronger** one than the
original robustness arithmetic, which counted flippable calls without trying to
flip them.

**The flip count is 19, not 0.** A flip count of exactly zero would have been as
suspicious as the 1.000 fidelity was — it would have meant the adversarial pass
was not adversarial. 19.4% of judgement calls changed.

---

## A4 — the flip distribution, which is more useful than the count

| category | n |
|---|---|
| quality-judgement | 4 |
| population-of-practice | 2 |
| hardware-dependent | 2 |
| user-expectation | 2 |
| unbuilt-artifact | 2 |
| external-referent, security-reachability, expressive, user-population, unnamed-criterion, unnamed-referent, no-threshold | 1 each |

**The flips are not spread evenly, and the concentration is the finding:**

> **10 of 19 flips are claims whose referent is a PERSON or a POPULATION** —
> quality-judgement (4) + population-of-practice (2) + user-expectation (2) +
> user-population (1) + expressive (1).

That is where the criterion is unstable. *"Difficult to understand"*, *"often
suboptimal"*, *"different from the user's expectations"* — Q2 asks whether the
success condition evaluates over held state, and when the referent is **someone's
judgement or a population of practice**, that question has no stable answer.
Everything else is comparatively firm.

**A second, smaller cluster (4):** referents outside the repo boundary —
hardware, an external page, real-world input distributions. Those flipped
because I had scoped *"the system"* to repo-plus-tests-plus-CI, and they sit just
outside it.

**A third cluster (5) flipped INTERNAL→UNDERDETERMINED and does not move `f`:**
unbuilt artifacts, unnamed criteria, missing thresholds. These are claims I had
read *charitably* — supplying the referent from the surrounding issue, which is
exactly the failure mode B4 warned about. They are corrected here.

**The criterion was NOT tuned.** Every flip is a case where the *original
application* was wrong on that claim, not where the rule changed. No
classification was altered by reinterpreting Q1–Q4.

---

## A5 — the reverse direction, because A1 alone is selective stressing

`UNSURE = 0` is definitional: **Q4 is a catch-all**, so EXOGENOUS absorbed
everything I could not resolve and is an **upper bound**, not a measurement.
Reporting only the direction that could hurt the verdict, while ignoring the one
that could help it, would be selective stressing.

Of the **23 EXOGENOUS + 12 CONTESTED**, how many survive an argument that they
are merely *unresolved*?

| | |
|---|---|
| baseline EXOGENOUS+CONTESTED | 35 |
| **argued merely UNRESOLVED** | **6** |
| **f after reverse pass** | **`29/169 = 0.1716`** |

All six are the same shape — **resolvable-by-naming**:

- *"the upstream change is PR 29469, commit ec65514"* — **names its referent
  exactly**; a pinned dependency's commit is resolvable.
- *"the URL should have been www.openml.org"* — naming both URLs makes it a
  two-request check.
- *"these objects have all the info specified by the array API standard"* — the
  standard is a document; naming the fields resolves it.

> **So EXOGENOUS is inflated by roughly 6/35 ≈ 17% absorbed-unresolved claims.**
> That is the predicted consequence of Q4 being a catch-all, now quantified.

## Both directions at once

| pass | f | verdict |
|---|---|---|
| baseline | 0.2071 | FAVOURABLE |
| A1 adversarial only | **0.2899** | FAVOURABLE |
| A5 reverse only | 0.1716 | FAVOURABLE |
| **both applied** | **0.2544** | **FAVOURABLE** |

**The verdict does not change under any of the four readings.** The plausible
range for `f` is roughly **0.17 – 0.29**, and the decision boundary is **0.50**.

---

## What survives, precisely

1. **CENSUS-FAVOURABLE holds** under adversarial re-reading by its author, and
   under the reverse direction, and under both together.
2. **The criterion's unstable region is named:** claims whose referent is a
   person or a population. That is a finding about the criterion, not about the
   corpus, and it should be carried into any future use of it.
3. **EXOGENOUS is an upper bound**, inflated ~17% by unresolved claims Q4
   absorbed. The true exogenous fraction is *lower* than reported, which
   strengthens FAVOURABLE.

## What does not

Everything in the disclaimer at the top. **The single cheapest thing that would
settle this remains a classifier who did not write the corpus**, and this is not
that. If the criterion is systematically misread, both passes misread it
identically and this document would look exactly as it does.
