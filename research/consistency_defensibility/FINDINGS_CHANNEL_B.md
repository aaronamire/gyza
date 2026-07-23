# Findings — Channel B (defensibility asymmetry)

Decision first, then the gap table, then hedge rates, then honest limits. **NOT a
Route 2 rescue** (terminal UNFALSIFIABLE-IN-PRACTICE stands). Channel B tests
whether a FALSE claim is harder to defend under a judge-free, mechanically-scored
adversarial challenge than a TRUE one.

## DECISION — B-INSINCERE-ONLY

The judge-free challenge (defender must maintain its claim under
semantics-preserving transforms; loses iff a transformed answer violates the
declared relation — no persuasiveness judge) catches **insincere/assigned lies**
but **not sincere errors**:

| comparison | violation (defend) | violation (truth) | **gap [CI over items]** | n |
|---|---|---|---|---|
| **B-ASSIGNED − B-TRUE** (lie you don't hold, on solvable items) | 0.558 | 0.058 | **+0.500 [0.365, 0.635]** ✓ | 52 |
| **B-HELD − B-TRUE** (falsehood you genuinely hold, on hard items) | 0.690 | 0.552 | **+0.138 [−0.103, 0.379]** ✗ | 29 |

gap(ASSIGNED − TRUE) excludes 0; gap(HELD − TRUE) includes 0 → **B-INSINCERE-ONLY**
by the preregistered rule. Adversarial challenge with mechanical verdicts catches
a lie a model does **not** believe, but cannot distinguish a falsehood the model
genuinely **holds** from the truth. This is the **known weak point of debate-style
mechanisms**, now shown for a *judge-free, purely mechanical* challenge — so it is
not a judge-quality artifact; it is structural.

## Why the held-gap is null — the mechanism, made precise (not just low power)

Note the B-TRUE baseline: **violation 0.552 on held (hard) items vs 0.058 on
assigned (solvable) items.** Defending the *truth* is easy on items the model can
solve and **hard on items it cannot**. The mechanical challenge works by exposing
that a claim can't be maintained consistently under transformation — which
distinguishes a lie from a truth **only when the truth itself is consistently
maintainable**. Sincere errors live precisely on the items the model can't solve,
where the truth is *also* not maintainable — so there the lie doesn't stand out.
The challenge catches **strategic deception, not genuine confusion.**

## Hedge rates (the defender's own correctness leaking — never counted as violation)

| condition | violation | hedge |
|---|---|---|
| B-TRUE (hard items) | 0.552 | 0.138 |
| B-HELD | 0.690 | **0.276** |
| B-ASSIGNED | 0.558 | 0.173 |
| B-TRUE (solvable items) | 0.058 | 0.077 |

B-ASSIGNED hedges ~2× B-TRUE-on-solvable (0.173 vs 0.077): assigned a lie on an
item it can solve, the model sometimes refuses/corrects — its correctness leaking,
reinforcing the insincere-lie signal *on top of* the +0.50 violation gap. B-HELD
hedges most (0.276): even defending its own error, the model wavers under
challenge (but wavering ≠ violation, and doesn't separate it from B-TRUE-on-hard).

## Power limitation (per model)

B-HELD fixtures = 29, **gemma-carried (23)**; phi-4 has 0 (never produced an
attractor). Per-model held gap: **gemma 0.739 vs 0.696 (gap ~0.04, n=23)** — the
only powered cell, and it is null; llama n=2 and mistral n=4 are uninterpretable.
So the sincere-error null is really "**on gemma's hard items, defending its held
error is no harder than defending the truth**." Data integrity: 1/322 gemma
generation failure (excluded).

## What it means

The oracle-free, judge-free challenge is a **real but bounded** fraud signal: it
deters **strategic/assigned falsehood** strongly (+0.50 violation gap, plus extra
hedging) with no ground truth and no adjudicator. It provides **no protection
against sincere error** — a genuinely confused defender defends its wrong answer
about as "well" (or as badly) as it defends the truth, because on hard items
neither is maintainable. For a bonded mechanism this means challenge-based bonding
punishes deliberate fraud but cannot substitute for ground-truth resolution when
the error is sincere. Combined with Channel A in `FINDINGS_SYNTHESIS.md`.
