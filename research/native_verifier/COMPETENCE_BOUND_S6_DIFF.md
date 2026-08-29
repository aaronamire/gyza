# Proposed DIFF to research/COMPETENCE_BOUND.md §6 (NOT applied)

R8 measured the one load-bearing claim in the synthesis that was REASONED rather than
MEASURED — §6's "native formal verifier plausibly escapes this bound entirely." The claim
needs a qualification: the escape is real **only when the tests are externally specified**;
when a checker LLM writes them, the bound re-enters through test-writing (ESCAPE-ILLUSORY,
FINDINGS_R8.md). This diff restates §6 accordingly. It is provided for the user to apply;
per the task, committed findings/synthesis are not edited here.

```diff
-- **The escape hatch, stated plainly.** A domain with a **native formal verifier** — code
-  with unit tests, a theorem with a Lean/Coq kernel — **plausibly escapes this bound
-  entirely**, because the claim is already mechanically checkable and no LLM stage stands
-  between the claim and the check. That is *why* those domains already have cheap fraud proofs
-  and natural-language mathematical reasoning does not. The strongest response to the
-  competence bound is therefore to **scope claims to domains with native verifiers**, not to
-  search for a better prose-reasoning detector — the program is five families of evidence that
-  the latter search does not pay.
+- **The escape hatch, and its measured boundary (Route 8).** A domain with a **native formal
+  verifier** — code with unit tests, a theorem with a Lean/Coq kernel — escapes this bound
+  **only when the check itself comes from an independent, non-LLM source** (human-written
+  tests, a formal spec, a proof kernel). It does **not** escape when a cheap checker LLM is
+  asked to *write* the tests: Route 8 measured this on MBPP (4 in-band models, well-powered
+  cell (b), n=127–290) and found ESCAPE-ILLUSORY. Test-writing is itself competence-bounded —
+  a checker's test validity collapses from ~0.77 on problems it can solve to ~0.28 on problems
+  it cannot, and without a reference solution to filter the invalid tests (the very ground
+  truth deployment lacks), the mechanism is a false-positive generator (deployable LR
+  1.17–1.92, FPR 0.44–0.71); property/invariant tests, the "checking-without-solving" hope,
+  do worse than example tests, not better. So the escape is real but its boundary is sharp:
+  the verifier must be **externally specified**, because writing a discriminating check is the
+  same competence as producing the answer. The strongest response to the competence bound is
+  therefore to **scope claims to domains with an independent verifier already in hand** (human
+  tests, a formal kernel, reality) — not to a better prose-reasoning detector, and not to a
+  cheap model asked to invent the check. Route 8 is the sixth family of evidence.
```

Consequential note for §2(v)/§3: R8 makes the mechanical-checking row (R5) and the
native-verifier escape one story — **an LLM that must supply the check re-imports the bound**,
whether the checker is a CAS (R5, extraction) or a unit-test writer (R8, test validity). The
synthesis's "five families" becomes six, all converging on the same boundary.
```
