# Preregistration — the census over the hand-extracted claim corpus

Committed **after** the corpus freeze and **before** any classification.

| artifact | value |
|---|---|
| frozen corpus | `claims_hand.json` |
| **sha256** | **`c5928b3d6e121e9ae7655023d46896ff1125940e437d9ae13cfad334ff6fa941`** |
| freeze commit | **`9ab33b1`** |
| claims / issues | **215 / 82**, cap 3 per issue |
| repos | pandas 96, scikit-learn 119 |

Zero credits. Analytic only. No API call.

---

## 1. The criterion — REUSED VERBATIM, NOT REFINED

From `research/census/PREREGISTRATION_CENSUS.md` §2, unchanged. It retrodicted
4/4 and **refining it after two voids would be tuning.**

**AXIS 1 — SPEECH ACT.** DECLARATIVE (success = felicity) · COMMISSIVE
(fulfilment) · DIRECTIVE (compliance) · ASSERTIVE (correspondence to a fact).

**AXIS 2 — DETERMINACY**, applied as a decision procedure, first match wins:

```
Q1. Is there a fact of the matter at all — could two competent parties
    disagree with no procedure that settles it?      -> CONTESTED
Q2. Can the success condition be written as a function of
    (a) state the system already stores, and
    (b) fields the CLAIM ITSELF names?               -> INTERNAL
Q3. Does a success condition exist, and would NAMING MORE PARAMETERS
    make Q2 answer YES, without acquiring any new fact
    from outside the system?                         -> UNDERDETERMINED
Q4. Otherwise                                        -> EXOGENOUS
```

**THE CONSERVATIVE DIRECTION IS BINDING.** Where a referent cannot be resolved
to stored state by inspection, classify **EXOGENOUS**.

**Q2 is COUNTERFACTUAL** — *could* this check be written, not *has* someone
written it. **Q3 is parameter ADDITION, never claim SUBSTITUTION** (the reading
fixed in the previous census; DR's rule 3d is the same constraint).

**"The system" for this corpus** = the repository plus its test suite and CI —
the artefacts a maintainer already holds. Fixed now, before classification,
because it decides many Q2 answers.

## 2. Decision rule

**f = fraction of the ASSERTIVE row that is EXOGENOUS or CONTESTED.**

| outcome | condition | consequence |
|---|---|---|
| **FAVOURABLE** | `f < 0.50` | most assertive claims are underdetermined, not exogenous; the bound covers a smaller region than 16 routes suggested; **Attacks 2 and 3 LICENSED** |
| **UNFAVOURABLE** | `f >= 0.80` | the underdetermined class is small; respecification's ceiling is low; **Attacks 2 and 3 KILLED, recorded closed** |
| **INTERMEDIATE** | `0.50 <= f < 0.80` | report the number, claim neither, name which classes fall where |

**Any cell driven by a single issue → INCONCLUSIVE for that cell.** With a
3-per-issue cap, one issue can contribute at most 3, so this is checked at issue
granularity, not claim granularity.

## 3. Point predictions, and why they differ from last time

The first census predicted `f ∈ [0.4, 0.7]` and **missed by 28×** — because the
instrument was broken (a vocabulary selected on being checkable), not because
the world surprised me. **These predictions are for THIS instrument**, whose
population is claims made *before* anyone decided what was checkable.

| prediction | value |
|---|---|
| **f** | **0.25 – 0.55** |
| **UNDERDETERMINED is NON-EMPTY** — the whole point of the route | **≥ 25 of 215 (≥ 0.12)** |
| ASSERTIVE is the largest speech-act row | yes, 0.55 – 0.80 of all claims |
| DIRECTIVE non-trivial (proposals, "Add a flag…") | 0.10 – 0.25 |
| judgement fraction | 0.35 – 0.65 (first census: 10/18 = 0.56) |

**Why lower than last time's f.** Bug reports are written by people who observed
something concrete in a system the maintainers hold. Most assertions should
resolve against the repo and its tests → INTERNAL. The genuinely exogenous ones
should be about *users*, *convenience*, *importance* and *other people's
software* — real but a minority.

**Prior: 40% FAVOURABLE / 40% INTERMEDIATE / 20% UNFAVOURABLE.**

## 4. B4 — the vagueness check, specified before data

If UNDERDETERMINED returns at or near zero a **third** time, that must be
diagnosed, not reported as a fact about the world. The specific alternative
hypothesis: **I resolved vagueness while reading**, silently supplying what the
reporter probably meant.

**Preregistered check:** count claims containing a term whose referent the claim
does not fix — `slow`, `wrong`, `unexpected`, `broken`, `should`, `vague`,
`suboptimal`, `unclear`, `surprising`, `confusing`, `complex`, `limited`,
`some cases`, `not sure`, `likely`, `probably`, `seems`, `hunch`, `guess`.

> **If that count is HIGH and UNDERDETERMINED is LOW, the classification is
> resolving vagueness that the extraction preserved — and that is a finding
> about the CRITERION, not about the claims.**

`EXTRACTION_AUDIT.md` already records a bias in the relevant direction: the
elisions ran toward brevity and away from hedging, which pushes **against**
finding UNDERDETERMINED. Recorded before classification so it cannot be reached
for afterwards.

## 5. Honesty conditions

- **A THIRD VOID IS TERMINAL AND IS A SUCCESS.** If this fails, **no fourth
  corpus will be proposed.** Four methods will have failed for four distinct
  structural reasons, and the conclusion is that the UNDERDETERMINED class is
  **not observable by this program with available methods** — Attacks 2 and 3
  then **CLOSE** rather than remain blocked. That is a real result about
  reachable scope.
- **UNFAVOURABLE IS A SUCCESS.** It closes two documents' worth of work cheaply.
- **This is an AUTHORED corpus AND an authored classification**, both by this
  agent. The H1 circularity is **doubled** relative to the earlier census and
  will be stated in the findings' first paragraph, not in a limits section.
- Diagnose any exact 0, any full row, any prediction missing by more than ~3×.
- Report **judgement** and **UNSURE** counts separately; *"I could not classify
  this"* and *"this is exogenous"* are different claims.
- Do not import `research/corpus/check_taxonomy.py` or any partition this
  program authored.
