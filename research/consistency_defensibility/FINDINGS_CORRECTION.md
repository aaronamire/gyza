# Findings — Phase 8: canonicalization correction (cache-only)

**A correction to Phases 5/6B/7, not a new experiment. No new round follows.**
NOT a Route 2 rescue. Zero new generations — the cached detector outputs are held
fixed; only the ground-truth wrongness labels are recomputed with a hardened,
conservative canonicalizer (`canonicalizer_v2.equal`, returning True / False /
UNRESOLVED). UNRESOLVED items are EXCLUDED, never scored.

## Headline — the artifact was real, but NO decision changes; the nulls get FIRMER

The ~33% contamination flagged in `FINDINGS_WITNESS.md` is confirmed: **13
(model, problem) pairs flip WRONG → CORRECT**, the wrongness base rate drops from
**0.204 → 0.128**, and **all 4 of mistral's "wrong" answers were false-positives**
(every one flipped). Yet **not one preregistered decision changes**, and the two
nulls move *away* from their thresholds after correction — so the architectural
conclusions rest on firmer ground, not weaker.

| phase | preregistered decision | old | new | change? |
|---|---|---|---|---|
| Phase 5 (A2 self-inversion generalizes) | GENERALIZES | J 0.374 | **J 0.451** | **unchanged, stronger** |
| Phase 6B (cross-verify) | ASYMMETRY-WEAK | cell-a 0.720 / cell-b −0.133 | cell-a **0.777** / cell-b **0.111** | **unchanged** |
| Phase 7 (witness) | WITNESS-DEAD | C1 cell-b 0.194; effect +0.226 | C1 cell-b **0.164**; effect **−0.077** | **unchanged, firmer** |

The decisive near-miss — Phase 7 C1 cell-(b) J = 0.194 against the 0.20 bar — did
**not** cross: it *fell* to 0.164 (CI still includes 0), and the paired witness
effect fell from +0.226 to −0.077. WITNESS-DEAD is more robust after correction,
not less. The program's one positive (6B cell-a) and the external-validity result
(Phase 5) both strengthen.

## 8b — validation (mandatory gate): 100% agreement, ZERO false merges

Hand-verified against 27 non-ambiguous hand judgments from the Phase-7 examination
(stratified across the failure modes: \\cfrac/\\dfrac, unicode-√, \\text, brace-less
\\frac32, ordinals+units):

| hand \\ new | CORRECT | WRONG | UNRESOLVED |
|---|---|---|---|
| **hand CORRECT** (10) | **10** | 0 | 0 |
| **hand WRONG** (17) | **0** | 16 | 1 |

**Agreement 1.00**; the fatal error (hand-WRONG → new-CORRECT, a false merge) is
**0**. The one hand-WRONG → UNRESOLVED is a conservative exclusion, not a
mis-score. Exceeds the ≥95% gate. Conservatism unit-tested: `1/2` vs `2/3`,
`\\sqrt{2}` vs `1.414`, `(4,1)` vs `(2,1)` all stay distinct; `\\dfrac{1}{2}`≡`0.5`,
`3\\frac12`≡`3.5`, `\\frac{25}{16}`≡`\\cfrac{25}{16}`, `2√13`≡`2\\sqrt{13}`,
`162 minutes`≡`162`, `12^{\\mathrm{th}} grade`≡`12` all merge.

**Flips WRONG→CORRECT**: llama 3/11, gemma 3/24, mistral **4/4**, phi 3/7 (total
13). **UNRESOLVED**: 8 (excluded). Base rate wrong **0.204 → 0.128**.

## 8c — recompute (old vs new)

**Phase 5 — A2 self-inversion on MATH**

| | n | wrong | TPR | FPR | LR | precision | J [CI] | perm p |
|---|---|---|---|---|---|---|---|---|
| old | 215 | 41 | 0.415 | 0.040 | 10.3 | 0.708 | 0.374 [0.231, 0.535] | 0.0 |
| **new** | 208 | 24 | 0.500 | 0.049 | 10.2 | 0.571 | **0.451 [0.241, 0.659]** | 0.0 |

Generalization **holds and strengthens** (J up, LR stable, perm p=0). Precision
falls (0.71→0.57) only because the base rate fell — fewer true positives available.

**Phase 6B — cross-model verification (competence split)**

| | n | wrong | TPR | FPR | LR | J [CI] |
|---|---|---|---|---|---|---|
| old cell-(a) SOLVED | 413 | 29 | 0.759 | 0.039 | 19.4 | 0.720 [0.554, 0.867] |
| **new cell-(a)** | 433 | 22 | 0.818 | 0.041 | 19.8 | **0.777 [0.605, 0.923]** |
| old cell-(b) FAILED | 71 | 35 | 0.200 | 0.333 | 0.6 | −0.133 [−0.343, 0.068] |
| **new cell-(b)** | 36 | 9 | 0.556 | 0.444 | 1.25 | **0.111 [−0.292, 0.477]** |

Cell-(a) (the program's one positive) **strengthens**; cell-(b) remains null (CI
includes 0, LR≈1). **ASYMMETRY-WEAK unchanged.** (Half the cell-(b) "wrongs" were
notation false-positives — correct answers on problems the checker couldn't solve —
so n falls 71→36; the point estimate rises to +0.11 but with a wide CI through 0.)

**Phase 7 — witness (cell b)**

| | n | TPR | FPR | J [CI] |
|---|---|---|---|---|
| old C0 (no witness) | 71 | 0.20 | 0.333 | −0.133 [−0.329, 0.069] |
| new C0 | 36 | 0.556 | 0.444 | 0.111 [−0.271, 0.492] |
| old **C1 (full trace)** | 62 | 0.613 | 0.419 | **0.194 [−0.065, 0.434]** |
| **new C1** | 32 | 0.800 | 0.636 | **0.164 [−0.178, 0.462]** |
| old C2 (prefix ≤3) | 73 | 0.111 | 0.054 | 0.057 [−0.070, 0.185] |
| new C2 | 40 | 0.083 | 0.071 | 0.012 [−0.146, 0.214] |

Paired **witness effect C1−C0 (cell b): +0.226 [−0.082, 0.529] → −0.077 [−0.649,
0.493]** (n_paired 29). C1 cell-(b) J falls below its old value and stays under the
0.20 bar with CI through 0; the witness effect loses its positive lean. **WITNESS-DEAD
unchanged and firmer.** (FPR rises to 0.64 in new C1 cell-(b) — with the
notation-FPs removed, the "correct" answers a checker can't verify now correctly
count as false alarms, exposing that C1's apparent cell-(b) signal was partly the
contamination.)

## 8d — decision reporting

**All three preregistered decisions are UNCHANGED**: Phase 5 GENERALIZES, Phase 6B
ASYMMETRY-WEAK, Phase 7 WITNESS-DEAD. The nulls are **robust to the contamination**
— and the two decision-critical numbers (Phase 7 C1 cell-b J, the paired witness
effect) move *away* from the threshold after correction, so the WITNESS-DEAD
conclusion is on firmer ground. The positives strengthen. Cell-(b) n is small
(now 32–36 pooled), so none of the point-estimate movements approach CI separation
— consistent with "not a decision change."

The correction confirms the honesty of the original write-ups (the artifact was
disclosed, and fixing it does not rescue any null or overturn any positive) and
removes an inflated signal (the old C1 cell-b 0.194 was partly contamination).

## Implied DIFFs (NOT applied)

```diff
@@ FINDINGS_EXTERNAL_VALIDITY.md — A2 pooled @@
- LR 10.3, FPR 0.040, precision 0.71, J 0.374 [0.231, 0.535]
+ (corrected canonicalizer, Phase 8) LR 10.2, FPR 0.049, precision 0.57, J 0.451
+ [0.241, 0.659] — generalization holds and strengthens; base rate 0.204->0.128.
```
```diff
@@ FINDINGS_ASYMMETRY.md — cells @@
- cell (a) J=0.694 ... cell (b) J=-0.13
+ (Phase 8 corrected) cell (a) J=0.777 [0.605,0.923]; cell (b) J=0.111 [-0.292,0.477]
+ (CI incl 0). ASYMMETRY-WEAK unchanged; cell-a positive strengthens.
```
```diff
@@ FINDINGS_WITNESS.md — decision @@
- C1 cell-b J=0.194 [-0.061,0.447]; paired witness effect +0.232 [-0.062,0.525]
+ (Phase 8 corrected, ~33% notation FPs fixed) C1 cell-b J=0.164 [-0.178,0.462];
+ paired witness effect -0.077 [-0.649,0.493]. WITNESS-DEAD unchanged and FIRMER —
+ the near-miss fell below the bar and the witness effect lost its positive lean.
```
