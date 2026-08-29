# Findings — Phase 6A: T2's J=1.0 is a de-trapping artifact (headline restated)

Decision first. **NOT a Route 2 rescue.** FREE, cache-only, zero generations.

## DECISION — T2 (and partly T4) is DE-TRAPPING; the deployable headline is downgraded

The deployable metamorphic detector {T2,T3,T4} (J=0.94, Phase 4) is carried by T2
rephrase (J=1.0). Testing whether T2 measures genuine invariance-instability or is
partially removing the trap, on surface (NoOp) items:

| transform | acc original | acc transform | paired diff [CI] | % of wrong-originals FIXED by transform | attractor-hit orig → transform |
|---|---|---|---|---|---|
| **T2 rephrase** | 0.844 | **1.000** | **+0.156 [0.100, 0.213]** | **100% (25/25)** | 0.156 → **0.000** |
| T4 reorder | 0.844 | 0.906 | +0.063 [0.000, 0.125] | 68% | 0.156 → 0.094 |
| T3 rename | 0.844 | 0.825 | −0.019 [−0.063, 0.025] | 20% | 0.156 → 0.175 |

**T2 is fully de-trapping:** the rephrase makes the model answer correctly **100%
of the time** (acc 1.0), eliminates the attractor entirely (0.156 → 0), and fixes
**every** wrong original. So T2's J=1.0 is *"clearer restatement solves the
problem, so the rephrase disagrees with the original attractor answer by
construction"* — **not** *"the error is invariance-unstable."* T4 is partially
de-trapping (68% fixed, diff CI touches 0). **T3 (rename) is the only genuine
invariance transform** (accuracy unchanged) — and its J is weak (0.14).

Per model, the de-trapping is concentrated in the error-prone model: **gemma-2
acc 0.50 → 1.00 under T2** (diff +0.50 [0.35, 0.65]); llama 0.975 → 1.0 (n.s.);
phi-4 1.0 → 1.0 (no errors to fix).

## What this changes (and what it does not)

**Does NOT change:** the detector still *works* empirically — a battery of
restatements that disagree with the original still flags the error oracle-free
(you don't need to know which answer is right; disagreement proves ≥1 is wrong).
The deployable J≈0.94 as a **detector** stands.

**DOES change — the mechanism and the claim (restated):** the power is
**restatement-instability, which includes the restatement clarifying the trap**,
NOT a property of the error being "surface-keyed / invariance-unstable." This is a
**weaker and not-fully-content-agnostic** claim: an effective restatement
partially targets the confusing clause (my T2 template de-emphasises the NoOp
aside), so "content-agnostic" overstated it. The genuinely content-agnostic
invariance signal (T3 rename, no de-trapping) is **weak (J=0.14)**. The corrected
statement: *"applying a battery of restatements and firing on disagreement catches
comprehension errors, partly because a clearer restatement fixes them"* — useful,
oracle-free, but restatement-quality-dependent and not a claim that the error is
intrinsically invariance-unstable.

This also further motivates Phase 6B: self/single-model restatement is fragile and
content-dependent; the robust, non-gameable form is **cross-model verification**.

## Implied DIFF to FINDINGS_ABLATION.md / FINDINGS_CHANNEL_A.md (NOT applied)

```diff
@@ 4a deployable headline @@
- A-LIVE survives; the corrected deployable headline is J ≈ 0.94.
+ A-LIVE survives as a DETECTOR (deployable J ≈ 0.94), but Phase 6A shows the
+ mechanism is RESTATEMENT-INSTABILITY (incl. the restatement clarifying the trap),
+ not pure invariance-instability: T2 rephrase fixes 100% of wrong originals
+ (acc 0.844 -> 1.000, attractor 0.156 -> 0), T4 partly (68%), and only T3 rename is
+ genuine invariance (and weak, J=0.14). The "content-agnostic surface-invariance"
+ claim is downgraded to "a battery of restatements + fire-on-disagreement catches
+ comprehension error, partly by clarifying it" -- restatement-quality-dependent.
```

## Implied DIFF to FINDINGS_SYNTHESIS.md (NOT applied)

```diff
@@ what it catches @@
- surface-keyed error ... A: NoOp J=0.815 [metamorphic]
+ surface-keyed error ... A: metamorphic detector J~0.94 works, but Phase 6A shows
+ its power is restatement clarifying the trap, not intrinsic invariance-instability;
+ the robust oracle-free primitive is A2/cross-model verification, not self-restatement.
```
