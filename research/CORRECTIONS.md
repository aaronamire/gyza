# Corrections of record

**Every claim in this corpus that is now known to be wrong or narrower than it
reads, and where its correction lives.**

## Why this file exists

The established pattern here is right: a superseded finding **stands unedited**
and its correction lives in the new document (`FINDINGS_BOX_SCALING` §5 does
exactly this to `FINDINGS_ROUND3_DISTANCE` §4c). That preserves the record of
what was believed and when.

It also makes corrections **undiscoverable.** A reader of
`FINDINGS_BOX_SCALING` has no way to learn that §4b was later refuted. The
corpus is 144 tracked markdown files; nobody reads them in commit order.

So this is the index. It edits nothing. It applies the ledger discipline —
*cite the entry, never the tally* — to corrections rather than to artifacts.

**A claim not listed here has not been checked, not "verified correct."** This
file is sound in one direction only.

---

## 1. `aggregate/FINDINGS_BOX_SCALING.md` §4b — **REFUTED**

**Claimed:** the staleness attack *"gets harder with scale"* — the required shed
rises from 33.3% of endowment at M=2 to 99.3% at M=100, so violations should
decay as the federation grows.

**Now known:** the arithmetic is correct and **does not protect the box.** The
floor `L` falls as 1/(m−1) by the same factor, so an agent shedding *to the
floor* scales its attack exactly with the defence. They cancel. Measured
violation rate is **flat from M=8 to M=512**.

**Sharper replacement:** the box's soundness is a property of **single-threaded
principals**, not of scale. With one agent per principal it is sound at every M;
with two it is breached at every M, and n=2, 4, 8 are identical. Concurrency,
not scale, is the control parameter — and any deployment running more than one
agent per principal is outside the guarantee.

**Correction:** `research/arena/FINDINGS.md` (`b6a37b7`).

## 2. `aggregate/FINDINGS_BOX_SCALING.md` §4a — narrowed, **in-file**

"Cheaper at scale" is true per participant and false in aggregate: `(m−1)L` is
invariant in m. Already corrected by §7 of the same document. Listed so the
index is complete.

## 3. `prior_art/FINDINGS_ROUND3_DISTANCE.md` §4c — **SUPERSEDED**

Claimed planetary-scale collective-harm bounding is *"structurally obstructed."*
Superseded by `FINDINGS_BOX_SCALING` §5, which already carries the correction.
The reading error was treating *"no **exact** local test exists"* (completeness)
as *"no local bounding exists"* (soundness).

## 4. "Bounding a consequence TRANSFERS harm" — **OVERSTATED**

Stated in session summaries on 2026-08-14 as a general property of harm bounds
and a general blocker on the vision.

**Now known:** transfer follows from **conservation**, definitionally. Gyza's
vocabulary contains exactly two conserved quantities and **six of ten
declarable quantities EXTINGUISH** when bounded. The transfer result bounds one
class; it does not poison the model.

**Correction:** `research/planetary/R_B1_FINDINGS.md` (`270f391`).

## 5. PROOF-carried claim types: **61.1% → 55.6%**

`OPEN_PROBLEM.md` §2.7 reports **61.1%** (11 of 18). The registry now computes
**10 of 18 = 0.556**.

**Not a regression.** The FAIL_CLOSED cutover moved `envelope_dag` to carrier
NONE because its success condition is not fixed by the registry — production
calls `verify_dag` both ways. Refusing to count an unattested carrier claim
*lowered* the measured number honestly. Attesting it restores +5.6 points.

**Always recompute from the registry, never cite the document.**

## 6. `ENGINEERING_STATUS.md` capability paragraph — **WRONG IN BOTH DIRECTIONS**

Says Gyza *"bounds declared harm classes against declared bounds, over a harm
model currently covering 13.3% of the stateful action vocabulary."*

- **Too weak** when written: no runtime path consulted the harm model at all.
- **Too strong now**: H2 has no production existence, H3 is unmodelled, H1 was
  **retired** 2026-08-15, and **no declared class is enforced at runtime.**
  Authority containment *is* enforced, by a separate mechanism that is not a
  declared class.

**Correction: pending.** The wording is the owner's; a draft is in
`research/decisions/DECISION_MEMOS_2026_08_14.md` (M5). **Until it lands, do not
reuse that paragraph.**

## 7. `HARM_MODEL_GAP.md` — two entries now have code

Listed storage growth and several others as "declarable, existing code: **none**."
`H5_storage_growth` now exists and is bounded at 10 GB
(`gyza/containment/gyza_model.py`). `H6_unsupervised_actions` is new and was not
in that enumeration at all.

## 8. `guard_bounds.json` `H1_credits: 100.0` — **RETIRED**

The level refused every real model's first action (Sonnet 40,000 credits, Opus
120,000 against a bound of 100). Credits are `TOKEN_IS_FAKE`, so no level in
them is checkable. Retired 2026-08-15 by owner decision; listed in `UNMODELLED`
so the gap stays reported.

**Correction:** `research/planetary/R_D1b_FINDINGS.md` (`923a388`), retirement
in `a29f2e5`.

---

## Predictions I made and got wrong

Recorded because a program that only publishes its confirmed predictions is not
running the discipline it claims.

| prediction | outcome |
|---|---|
| **P-D1c** amortization is a *larger* lever than human capacity | **WRONG** — `H` and `A` enter as a product; identical. The real asymmetry is that one is bounded by hiring and the other by the harm bound. |
| **P-A1** `A` is order 1–100, "the lever is near-unused" | **WRONG** — measured 0.0008–1.0. Not near-unused; *inverted*. |
| **P1** (arena) violation rate falls monotonically in M | **REFUTED** — flat from M=8 to M=512. |

## Apparatus defects found in my own instruments

Four in the M>3 arena, each producing a publishable-looking number, **all
failing in the reassuring direction**: an adversary too weak to shed at all, one
actor per principal where the box is sound *by construction*, symmetric shedding
that cannot move a ratio, and a float boundary at exactly `L` — which I
diagnosed in print as a "seed effect" in the same output whose data refuted it.

Detail: `research/arena/FINDINGS.md` §4.
