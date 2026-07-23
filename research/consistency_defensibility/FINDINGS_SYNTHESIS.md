# Synthesis — Channels A + B: an oracle-free, judge-free trust primitive and its bounds

**NOT a Route 2 rescue.** The Route 2 terminal decision
(UNFALSIFIABLE-IN-PRACTICE) stands: trusting *agreement* between parallel
producers is dead. This program tested two *different* trust sources that need no
independence, and both are **live but bounded** — the first positive results in
the program.

## The unified primitive

Channel A and Channel B are the **same mechanical operation** used two ways:
*answer a semantics-preserving transform of a claim and check the declared
relation (invariance / equivariance) against the original — with no ground truth
and no judge.*

- **Channel A (self-audit / consistency):** apply the transforms to your own
  claim; an inconsistency proves ≥1 answer is false.
- **Channel B (adversarial / defensibility):** a challenger applies the transforms;
  the defender loses iff it can't maintain its claim. The verdict is mechanical,
  so **no adjudicator is needed** — the A×B synthesis the program set out to test.

## What it catches (both channels agree)

| error / claim type | caught oracle-free & judge-free? | evidence |
|---|---|---|
| **surface-keyed error** (latches on an irrelevant feature; the round-3 comprehension error) | **YES** | A: NoOp J=0.815, beats resampling +0.367; A2 inversion FPR 0.015, precision 0.86 |
| **strategic / assigned falsehood** (a lie the model doesn't hold) | **YES** | B: violation gap +0.500 [0.365, 0.635], plus extra hedging |
| **concept-keyed error** (a memorized misconception) | partially — no better than cheap resampling | A: concept J=0.544 but A1−SC gap +0.024 (CI incl 0) |
| **sincere held error** (genuine confusion on a hard item) | **NO** | B: held gap +0.138 [−0.103, 0.379], CI incl 0; truth also undefendable there |
| **non-surface error in a strong model** (phi-4) | **NO** | A: phi-4 J=0 — its errors are invisible to transformation |

## Can a challenger win with a mechanically-checkable inconsistency, no ground truth, no judge?

**Yes — for a bounded class, and cheaply.** A challenger needs only to (a) propose
verified transforms (a fixed, precomputable set — challenger *identity is
irrelevant* because the verdict is mechanical) and (b) check a declared numeric
relation. This wins against **surface-keyed errors and strategically-planted
falsehoods** without any oracle or persuasiveness judge. It does **not** win
against **sincere confusion** (where the truth is equally undefendable) or
**non-surface errors** (invisible to the transforms).

**Cost per challenge:** 3–5 transform-solves (Channel A used up to 5 relations per
item; Channel B used 3 rounds). At the models here that is fractions of a cent per
challenge — the whole program's generation cost was **~$0.5**. So a bonded
challenge is economically trivial relative to the work being audited.

## What this supports building (for Gyza), honestly bounded

A **bonded, oracle-free, judge-free challenge layer** is viable as:
1. a **fraud deterrent** — strategically planting a false result is punishable
   (violation gap +0.50) with no trusted resolver, so the *economic* case for
   deliberate fraud collapses;
2. a **cheap catcher of surface-keyed / comprehension errors** — exactly the class
   round 3 showed execution (Route 1's oracle) cannot catch, because CODE
   faithfully runs the miscomprehension.

It is **not** a replacement for ground-truth resolution, because it is blind to
(i) sincere confusion and (ii) non-surface errors in strong models. So the honest
architecture is **layered**: challenge-based bonding handles fraud + surface
errors trustlessly and cheaply; ground-truth resolution (Route 1) remains the
backstop for sincere, deep error. This is consistent with — and sharpens —
`research/CARDINALITY_LAW.md`'s conclusion that constrained/deep-error decisions
need an external reality anchor.

## Honest limits (carried from both channels)

- **Model-carried.** Channel A's power and Channel B's held comparison both rest on
  **gemma-2** (the one error-prone model); phi-4 is a clean counterexample in A
  (J=0) and has zero held fixtures in B. Non-gemma cells are underpowered.
- **Surface-specific.** The advantage over cheap self-consistency exists only for
  surface-keyed errors (A1−SC gap +0.37 NoOp vs +0.02 concept).
- **False positives.** The transform-solve detector fires on ~18% of correct NoOp
  answers (partly transform-induced error); self-inversion (A2) is the clean,
  low-FPR variant.
- **Two benchmarks, one tier, English, numeric answers.** These are results across
  a specific fixture family, not theorems.

## Bottom line

After Route 2's death (agreement-from-independence is unfalsifiable-in-practice),
this program found a **real, oracle-free, judge-free trust primitive** — mechanical
consistency-under-transformation — that catches surface-keyed errors and strategic
fraud cheaply, but is bounded: blind to sincere confusion and non-surface error.
It is a genuine building block for a bonded fraud-proof, layered with (not
replacing) ground-truth resolution.
