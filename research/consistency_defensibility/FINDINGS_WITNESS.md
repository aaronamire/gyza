# Findings — Phase 7: the witness/localization test

Decision first, then the (a)/(b) table, the paired witness effect, the
error-position histogram, localization accuracy, the C3 fraud result, cost ratios,
and limits. **NOT a Route 2 rescue** (terminal decision stands).

## DECISION — WITNESS-DEAD (the consequential outcome)

Giving the checker the reasoning **witness** (full trace, C1) and letting it
**localize** to a prefix (C2, k=1,2,3) does **not** create the verification/
generation asymmetry that a bare (problem, answer) pair lacked (6B). On problems
the checker **cannot solve** (cell b):

| condition | cell-(b) J [CI] | FPR | n | cell-(a) J |
|---|---|---|---|---|
| C0 no-witness (6B) | −0.133 [−0.334, 0.074] | 0.333 | 71 | 0.694 |
| **C1 full-trace** | **0.194 [−0.061, 0.447]** | **0.419** | 62 | 0.513 |
| C2 prefix ≤3 | 0.057 [−0.070, 0.185] | 0.054 | 73 | 0.034 |
| C2 k=1 | 0.059 [0.000, 0.148] | 0.000 | 68 | −0.036 |

**No checker** clears the preregistered bar (C1 cell-(b) J > 0.20 with CI
excluding 0): per-checker C1 cell-(b) J = llama 0.60 [0.0, 1.0] (n=11), gemma 0.19
[−0.14, 0.51] (FPR 0.54, n=35), mistral 0.14 [0.0, 0.43] (n=8), phi undefined
(never fires). The **paired witness effect C1−C0 in cell (b) is +0.232 [−0.062,
0.525] — CI includes 0.** C2 (localization) is null for every checker. By the
preregistered rule this is **WITNESS-DEAD: checking LLM reasoning requires
re-solving even with the witness.** The certificate gives a *positive but
non-significant, high-FPR* nudge — the honest reading is that it does not deliver a
usable asymmetry, and it is not softened. (Underpowered: cell-(b) n = 8–35 per
checker; the point estimates lean positive, so a much larger study could find a
small effect, but the preregistered call stands.)

## Error positions are NOT front-loaded — which is why localization fails

Hand-labelled first-error step on 15 confidently-labelled wrong traces
(normalized by trace length): **median 0.60**, only **20% before 0.40**. My
prediction (front-loaded, median < 0.4) is **refuted**: MATH errors here are
mostly mid-to-late — the setup/comprehension is usually fine and the error is an
algebra/arithmetic slip partway through (e.g. a wrong polynomial expansion at step
4/18, a spurious-root introduction at 3/8, a bad magnitude at 9/13, an
absolute-value case that cancels wrong at 17/22). Because the error is rarely in
the first 3 steps, **prefix-checking (C2) cannot catch it early** (J ≈ 0.06) — the
bisection economy does not apply.

**Localization accuracy**: when C1 names a first-invalid step on a wrong answer, it
matches the hand-labelled step (within ±1) **0.611** of the time (n=18 pairs) —
moderate, not reliable.

## C3 fabricated-trace (fraud) — caught, not evaded (prediction refuted)

I predicted a fabricated witness would evade detection (C3 ≪ C1). The opposite:
checkers caught the fabricated wrong traces at **0.974** (gemma 1.0, mistral 0.91,
phi 1.0) vs **0.607** on natural wrong traces. But this is **not** evidence that
trace-checking detects fabrication: C3 items are ones a model *did* solve, so the
checker catches the wrong conclusion by **re-solving**, not by finding the seam in
the trace — the same competence effect as everywhere else. So fraud-robustness here
is re-solving, consistent with WITNESS-DEAD.

## Cost ratios (an asymmetry needs cheaper AND detecting; this is cheaper but not detecting)

Mean output tokens: generate 312.6, C1 check 90.5 (**0.29×**), C2 k=1 57.3
(**0.18×**). Checking *output* is cheaper — **but** C1/C2 also pay **input** tokens
for the trace (a real, larger cost not in this ratio), and, decisively, the cell-(b)
detection is null. Cheaper-but-useless is not an asymmetry.

## Limits (load-bearing)

- **Notation false-positives contaminate the ground truth** (~**33%** of the
  sampled "wrong" set is actually CORRECT: `\cfrac`/`\dfrac`/unicode-√/`\text`/
  `\frac32` unparsed by `_sym_equal`). This depresses absolute TPR/J across the
  MATH phases (5, 6B, 7); paired comparisons (C1−C0) are more robust to it, but the
  absolute cell-J's are noisy — a real caveat, disclosed.
- **Underpowered** cell (b) (n=8–35/checker); parse-failure rate C1 124/2789
  (4.4%), C2 193 (6.9%); 12/2789 generation failures excluded.
- One task (competition MATH). MATH has an unusually tight solve↔verify coupling;
  domains with a **cheap external checker** (code + unit tests, formal proofs +
  a proof checker) would likely show the asymmetry that MATH does not. The claim is
  scoped to natural-language mathematical reasoning without an external verifier.
- C1/C2/C3 depend on **checker honesty** (a colluding checker returns NONE/VALID →
  J=0); only claimant-gameability is ruled out.

## What it means

For LLM mathematical reasoning, the witness does **not** buy the fraud-proof
economy that PoW/rollups get from checking a certificate: on a problem the checker
cannot itself solve, seeing the trace (and localizing) does not reliably reveal the
error. So **there is no cheap oracle-free fraud proof for LLM reasoning on this
task** — verification collapses into re-solving even with the witness. Optimistic
settlement over LLM reasoning has no free-lunch foundation here; a bonded system
must either restrict claims to a **checker's competence** (6B cell-a: strong,
non-gameable-by-claimant) or attach an **external verifier** (code tests, formal
checkers) — plain trace-checking is not enough.

## Implied DIFF to FINDINGS_ASYMMETRY.md (NOT applied)

```diff
@@ conclusion @@
- there is NO verification/generation asymmetry on MATH -- checking ~ re-solving.
+ there is NO verification/generation asymmetry on MATH -- checking ~ re-solving,
+ AND (Phase 7) adding the reasoning WITNESS + prefix localization does not create one
+ (WITNESS-DEAD: C1 cell-b J=0.19 CI incl 0; C2 null; errors mid-to-late median 0.6 so
+ bisection fails). LLM-reasoning fraud proofs need an EXTERNAL verifier (code tests,
+ formal checkers) or claims restricted to a checker's competence; the trace alone is
+ not a cheap certificate.
```
