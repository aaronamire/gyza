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

## 5. PROOF-carried claim types — **DO NOT CITE ANY NUMBER FROM A DOCUMENT**

`OPEN_PROBLEM.md` §2.7 reports **61.1%** (11 of 18). That figure moved **three
times on 2026-08-15 alone**, and I wrote a correction here that was itself stale
within minutes — which is the actual lesson, so it is recorded rather than
tidied away.

| when | value | why it moved |
|---|---|---|
| as documented | 11/18 = 0.611 | — |
| after the FAIL_CLOSED cutover | 10/18 = 0.556 | `envelope_dag` routed to carrier NONE: its success condition was not fixed by the registry, since production called `verify_dag` both ways. Refusing to count an unattested carrier claim **lowered** the number honestly. |
| after the determinacy repair | 12/19 = 0.632 | `envelope_dag` split into closed/open, each proving one proposition |
| after attestation landed | **13/19 = 0.684** | `external_send_content`'s policy bound out and attested |

**A split raises the count without adding any verification capability.** Read
these as defects being repaired, not as capability gained.

> **Recompute from the registry. Never cite a number from any document,
> including this row — it will be wrong again.**

## 6. `ENGINEERING_STATUS.md` capability paragraph — **RESOLVED 2026-08-15**

The prior paragraph said Gyza *"bounds declared harm classes against declared
bounds, over a harm model currently covering 13.3% of the stateful action
vocabulary."* It was **too weak** when written (no runtime path consulted the
harm model at all) and **too strong** later (it implied enforced consequence
bounds; H1 was retired, H2 has no production existence, H3 is unmodelled, and
**no declared class is enforced at runtime**).

**Replaced** by an owner-selected statement that leads with the aggregate-
alignment results, states the substrate as working, and names what is not
claimed. The prior text stands unedited beneath it. The suspension is lifted:
the new paragraph **is** the one to reuse.

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
