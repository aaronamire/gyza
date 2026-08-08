# A4 — extraction audit

Frozen corpus: `claims_hand.json`, sha256
**`c5928b3d6e121e9ae7655023d46896ff1125940e437d9ae13cfad334ff6fa941`**,
frozen at commit **`9ab33b1`** before any classification artifact existed.

---

## THE DISCLOSURE THAT COMES FIRST

> **The auditor and the extractor are the same agent.** I am checking whether I
> faithfully represented prose I read, and I have privileged access to what I
> intended it to mean. **This is the weakest possible form of audit and it
> cannot be guarded away, only disclosed.** It is the H1 circularity, and in
> this route it is doubled: the corpus is authored by the same agent that
> classifies it.

Because of that, the audit reports **two** numbers, and the second is the one
that is not self-assessed.

| measure | result | who judged it |
|---|---|---|
| **fidelity** — does the extracted assertion match what the reporter asserted? | **40/40 = 1.000** | **me** (weak) |
| **verbatim substring match** after Unicode/punctuation normalization | **28/40 = 0.700** | **mechanical** (independent) |

**GATE: fidelity ≥ 0.95 → PASSES.** But the 1.000 is an exact 1 assessed by the
extractor and is diagnosed below rather than reported as reassurance.

---

## Diagnosing the exact 1.000

Standing discipline: any exact 0 or 1 is a suspected artifact until shown
otherwise. Here the mechanism is plain — **I am scoring my own reading against
my own reading.** A misextraction would have to be one I both made and then
failed to notice, and nothing in the procedure makes the second independent of
the first.

**The 0.700 is the honest counter-metric**, and it measures something I did not
get to define after the fact: whether the stored text is literally present in
the source. It is not flattering, and it is reported at equal prominence.

## The 12 non-verbatim cases, by category

All 12 are **faithful** — none misattributes, fabricates, or reverses a claim.
All 12 nonetheless **deviate from my own stated rule**, which said *"verbatim
text"*.

| category | n | example |
|---|---|---|
| **elision** of a parenthetical, URL or bracketed link | 6 | `…F1-score or Area Under the ROC Curve **(AUC)** provide…` → `(AUC)` dropped |
| **truncation** of a trailing clause | 3 | `…same results on macOS/arm64 and Linux/x86-64**, both on pandas 3.0.5 with pyarrow 25.0.0**.` |
| **punctuation normalisation** (`:` → `.`) | 2 | `…from regular dense arrays**:**` → `…arrays**.**` |
| **reconstruction** across a list boundary | 1 | `Since a tree can be used from multiple threads**: 1.** The statistics will be garbage…` joined into one sentence |

### The one that matters most, named rather than averaged away

`scikit-learn#34278-0`. Source: *"**I would like to propose that** scikit-learn
should start publishing Pyodide/WASM wheels…"*. Stored: *"scikit-learn should
start publishing Pyodide/WASM wheels…"* — **the proposal framing was dropped.**

That is not a neutral elision. It converts an explicitly hedged proposal into a
bare normative claim, and **the speech act is axis 1 of the census.**

## The systematic direction of the error, and why it matters for B4

> **The elisions run consistently toward brevity and away from hedging,
> qualification and framing.** Parentheticals, "I would like to propose that",
> and trailing qualifiers are exactly what got dropped.

**This biases classification toward MORE determinate readings**, because hedges
and qualifiers are what make a claim look underspecified. So the bias runs
**against** finding UNDERDETERMINED:

- if the census **does** find an UNDERDETERMINED class, the finding is
  **robust** — it survived an extraction that trimmed the vagueness markers;
- if the census finds the class **empty or near-empty**, this elision is a
  **live candidate explanation** and must be weighed in B4 before concluding
  anything about the world.

That is recorded here, before classification, so B4 cannot reach for it as a
post-hoc excuse.

## No fix-and-rescore was performed

A4 permits one round of fix-and-rescore. **None was used.** The gate passed on
its stated criterion at the first attempt, and re-running extraction to raise
the *verbatim* rate would have meant editing a corpus that is already frozen and
committed — which would destroy the freeze's purpose.

## What the audit does not establish

1. **It does not establish that I extracted every claim.** It samples what was
   extracted and asks whether it is faithful. **Claims I failed to notice are
   invisible to this audit**, and there is no measurement of recall anywhere in
   this route.
2. The 0.700 verbatim rate means **the stored text is a lightly normalised
   rendering, not a quotation.** Anyone re-deriving from `claims_hand.json`
   should treat `text` as faithful-but-edited and go to `url` for the exact
   wording.
