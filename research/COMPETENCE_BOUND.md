# The competence bound: cheap verification of natural-language reasoning

*A cross-program synthesis. This supersedes nothing — every phase finding stands in its
own directory; this is the paper-shaped account of what the whole program found. Zero new
experiments. All numbers trace to committed preregistrations and findings.*

---

## 1. The question

Can an AI system's output be trusted **without redoing the work** and **without
contacting reality**? This is the premise of optimistic verification. Proof-of-work,
optimistic rollups, and TrueBit all achieve it: a cheap verifier accepts a claim unless
challenged, and challenges are settled by a mechanical check far cheaper than producing
the claim. That works because in those systems **the claim is already in a
mechanically-checkable form** — a hash preimage, a state-transition function, a program
trace. The verifier does not need to be as smart as the producer; it needs to run a fixed
procedure.

Natural-language reasoning is not in such a form. "The answer is 47 because …" is a claim
whose checkability is exactly the thing in question. The program asked, across five
structurally independent mechanism families, whether cheap verification is nonetheless
recoverable for natural-language mathematical reasoning. It is not. The reason is a single
boundary, which the program calls the **competence bound**: *you cannot cheaply verify
what you cannot understand.*

---

## 2. Five mechanism families, one boundary

Each family was preregistered with a decision rule before data. Each hit the same wall
from a different direction.

**(i) Agreement between independent producers — Route 2, three rounds,
UNFALSIFIABLE-IN-PRACTICE.** If independent solvers rarely make the *same* mistake,
agreement certifies correctness. But family diversity does not decorrelate errors: measured
excess agreement-on-wrong was ≈ 0 against a conditional-independence null. The regime where
agreement *would* be informative — dense, open, high-cardinality wrong-answer spaces — does
not occur naturally (MATH: mean 2.0 distinct wrong answers per 10 solvers; Simpson diversity
of the wrong set ≈ 0.0) and could not be induced adversarially (GATE B reached 22 of the 25
qualifying items required). And when a shared wrong attractor *is* present, method
disjointness does not break it: escape rates were nested COT 0.955 > DECOMP 0.727 > CODE
0.318, with 0/5 and 0/14 discordant cases — the more faithfully a method executes the
misreading, the more reliably it lands on the same wrong answer. Agreement measures shared
competence, not correctness.

**(ii) Consistency / metamorphic self-audit — Channel A, A-LIVE but the power was
DE-TRAPPING.** Ask the model the same question transformed; inconsistency flags error. It
fires — but the measured power came from the transform *fixing* the problem, not revealing
it: a T2 rephrase corrected 100% of previously-wrong originals (accuracy 0.844 → 1.000,
attractor mass 0.156 → 0). The genuinely content-preserving transform (T3 variable-rename,
which cannot fix anything) is weak (J = 0.14). A self-audit whose power is that the restated
version solves the problem is not a cheap verifier — it is a second attempt.

**(iii) Defensibility under adversarial challenge — Channel B, B-INSINCERE-ONLY.** Make the
model defend its answer against challenge; the indefensible ones are wrong. It separates
*strategic* deception cleanly (assigned-lie gap +0.500) but not *sincere* confusion
(held-error gap +0.138, CI includes 0). The reason is the boundary again: on hard items the
**truth is equally undefendable** — B-TRUE violation rate 0.552 on hard items vs 0.058 on
solvable ones. When the model cannot understand the problem, it cannot tell a defensible
truth from a defensible error.

**(iv) Cross-model checking, with and without the witness — 6B ASYMMETRY-WEAK, 7
WITNESS-DEAD.** Let a cheap model check an expensive model's answer. **Within the checker's
competence this works** — cell-(a) J = 0.777, likelihood ratio 19.8 (n = 433). **Outside it,
it collapses** — cell-(b) J = 0.111, CI including 0 (n = 36). Handing the checker the
producer's reasoning **trace** does not help (C1 cell-(b) J = 0.164, CI incl 0; paired
witness effect −0.077), because the errors are mid-computation (median normalized position
0.60), so neither reading the trace nor bisecting it localizes the fault. The checker
succeeds exactly where it did not need help.

**(v) Mechanical (CAS) checking — R5-DEAD.** Replace the intelligent checker with a computer
algebra system — non-intelligent, so surely not competence-bounded. Two independent failures.
Coverage: only ≈ 0.20 of reasoning transitions are mechanically checkable at all (ASSERTION —
invoking a theorem, a case split, a definition — is the *plurality* transition type, and a
CAS cannot check it). And the extraction stage that converts prose to CAS input **re-imports
the bound**: a strong and a weak extractor, feeding the *same* CAS over the *same* traces,
produce opposite-sign detection (J = −0.089 vs +0.149). The CAS is sound; the LLM in front of
it is not, and it carries the competence dependence back in.

---

## 3. The boundary, stated once

**You cannot cheaply verify what you cannot understand.** Every mechanism that tried to route
around this re-imported the competence requirement somewhere else:

- **Agreement** (Route 2) needed error *independence* it could not have — independent solvers
  of the same competence share the same blind spots.
- **Consistency** (Channel A) borrowed its power from *re-solving* the problem, not from a
  content-free check.
- **Defensibility** (Channel B) needed the model to distinguish defensible truth from
  defensible error — which requires understanding the problem.
- **Mechanical checking** (R5) needed a *competent transcriber* to put the reasoning in
  checkable form.
- **The two-tier router** (Route 6, below) needs *competence-classification* — deciding
  whether a claim is within the cheap checker's competence — which may itself be
  out-of-competence.

This is an **empirical regularity across five families on natural-language mathematical
reasoning**, not a theorem. It is possible a mechanism we did not test escapes it; it is
possible a different task distribution behaves differently. What the program shows is that
five structurally distinct, individually plausible mechanisms all fail for the *same reason*,
and that the reason is legible: cheap verification requires the verifier (or some stage it
depends on) to understand the claim, and where it does, it did not need the mechanism.

---

## 4. The economic consequence (Route 6)

The bound is not merely a ceiling on *detection*. Taking it as an input and asking the
costly-state-verification question — how to *price* error rather than detect it — shows it is
a floor on any incentive mechanism built over the checker.

Deterrence requires the audit probability `p ≥ g/(q·B)` (gain `g`, detection `q`, bond `B`);
participation by honest agents requires `w ≥ p·f·B` (honest surplus `w`, false-conviction
rate `f`). Together a mechanism that both deters lying and retains honest agents exists iff
**`LR = q/f ≥ g/w`** — the bond cancels; feasibility is governed by the **likelihood ratio**.
Measured: in-competence `LR = 19.8` (feasible for lies worth up to ~20× honest profit);
out-of-competence `LR = 1.25` (feasible only if a lie gains barely more than honest work —
effectively never). Two checkers with **identical Youden J = 0.5** but likelihood ratios 6
and 2.25 have **opposite** feasibility. So **J — the statistic this program itself optimized
for nine phases — is not the decision-relevant one.** The likelihood ratio is.

The consequence: out-of-competence claims are **both undetectable and un-priceable**. No
bond/audit pair protects them; they must be routed to ground-truth resolution. And the
targeting rule for the claims that *can* be protected is the **consequence-to-gain ratio
`v/g`** (corrected from an earlier error that read the proportional-gain special case as
general): under proportional gains stake is uninformative, but under *saturating* gains — the
realistic case, holding 0.56–0.59 of consequence under heavy tails — the ratio rises with
stake, so high-stake claims are the right priority precisely because their gain has decoupled
from their consequence. Prioritise by `v/g`; meter each claim at its own `p_min = g/(qB)`.

---

## 5. Methodological contributions

Standard tools from other fields, applied here; the contribution is the application and the
artifact ledger, not the tools.

1. **The conditional-independence null.** Permutation nulls answer the wrong question (they
   test "better than shuffling labels," not "better than independent errors would predict").
   Against the *conditional-independence* null, MBPP's 0.56 raw agreement-convergence became
   excess ≈ 0, and the apparent signal collapsed (0.56 → 0.17) once restricted to items with
   ≥ 3 distinct wrong answers. (The conditional-independence null is standard in
   meta-analysis; new here is using it as the agreement baseline.)
2. **The cardinality law.** Agreement informativeness is governed by the *size of the
   wrong-answer space*: convergence is nearly guaranteed when there are few ways to be wrong,
   and says nothing then. Always report wrong-answer cardinality beside any convergence figure.
3. **LR over J.** The likelihood ratio `q/f`, not Youden's J or TPR/FPR individually, is the
   mechanism-relevant statistic (§4). Elementary in decision theory; the program had to
   rediscover it the hard way, having optimized J for nine phases.
4. **The artifact ledger.** Each of the following would have produced a *false positive*
   result; each was caught before it did:

   | Artifact | What it would have falsely shown | What caught it |
   |---|---|---|
   | Forced collision (curated-list answer matching) | Spurious cross-model agreement | Switching to free-form answers |
   | Degenerate weak-model outputs | Inflated "diversity" from garbage | Output-quality filtering |
   | MBPP function-name harness bug | Wrong pass/fail ground truth | Per-item execution audit |
   | Sentinel collision | Extractor markers colliding with content (`rfind` vs `find`) | Marker-boundary check |
   | Trust-lift selection confound | Apparent verifier "lift" that was selection | Held-out comparator design |
   | T1/T2 detector coupling | Consistency "power" that was the two detectors sharing a transform | Decoupling T1 from T2 |
   | 33% canonicalization contamination | Inflated detection from notation-only false merges | Hand-validated canonicalizer (Phase 8), zero false merges 27/27 |

   Seven artifacts, each a clean number that was definitional, coupled, or contaminated. The
   discipline that caught them — preregister, then treat any suspiciously-clean result as a
   suspected artifact and diagnose before reporting — is the transferable contribution.

---

## 6. Limits (first-class, unhedged)

- **Two task families** (MBPP code, MATH) plus one hand-built fixture set (NoOp). **English.
  Numeric answers.** No proofs, no long-form argument, no multilingual, no open-ended tasks.
- **4–9 open-weight models in one capability tier.** No frontier models; no deliberately
  heterogeneous capability ladder.
- **Cell-(b) is underpowered.** The out-of-competence cells pool to n = 32–36. Several of the
  decisive nulls — 6B cell-(b) J = 0.111, Route 7 C1 cell-(b) J = 0.164, R5 cell-(b) — are
  **UNDERPOWERED-NULL, not DEMONSTRATED-NULL**, with confidence intervals including 0. The
  *direction and convergence* across five families is the strength of the result; no single
  out-of-competence cell is individually decisive.
- **Route 6 is single-shot and risk-neutral.** Repeated play and risk aversion would both
  deter more cheaply; the ε(r) floor is a conservative one-shot bound. The router is modeled
  as free and is the weakest link — if competence-classification is itself out-of-competence,
  the bound re-enters through it.
- **The escape hatch, stated plainly.** A domain with a **native formal verifier** — code
  with unit tests, a theorem with a Lean/Coq kernel — **plausibly escapes this bound
  entirely**, because the claim is already mechanically checkable and no LLM stage stands
  between the claim and the check. That is *why* those domains already have cheap fraud proofs
  and natural-language mathematical reasoning does not. The strongest response to the
  competence bound is therefore to **scope claims to domains with native verifiers**, not to
  search for a better prose-reasoning detector — the program is five families of evidence that
  the latter search does not pay.

---

## 7. What this supports building

The positive result, stated without hedging it into invisibility:

**A bonded market over claims that fall WITHIN a cheap checker's competence is viable.** The
in-competence checker has likelihood ratio 19.8 and Youden J 0.777 (n = 433, LR stable,
permutation p = 0). Over such claims: run the audit at the (measured) plateau rate; expect
undetected consequential error floored at ≈ 0.22 × the unaudited baseline (a relative figure —
quote the absolute floor for the deployment's own claim distribution); prioritise audits by
the consequence-to-gain ratio and meter at each claim's `p_min`; commit to a
profile-independent randomisation so coalitions cannot manipulate it. **Admission is gated on
a measured criterion: accept a claim onto the cheap rail only if `LR_i = q_i/f_i ≥ g_i/w_i`.**
Everything outside that gate — out-of-competence, likelihood ratio ≈ 1.25, undetectable and
un-priceable — goes to ground-truth resolution.

This is **Route 1 (a single-agent bonded claim with a provenance receipt) plus a measured
admission criterion and an audit policy** — which is exactly what the program produced. The
competence bound is not a dead end; it is a **specification**. It tells you which claims a
cheap verifier can carry and which it cannot, and it draws the line with a number you can
measure. Build the market inside the line, and send the rest to reality.
