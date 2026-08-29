# Route 3 — exploratory appendix (POST-HOC, UNDERPOWERED, NOT PREREGISTERED)

**Read this first.** Everything below is a **post-hoc, zero-cost diagnostic on
the existing cache** — no new generations. It is **exploratory and
underpowered** (the key cell is n=22 items) and **carries no preregistered
confirmatory weight**. It does **not** edit or reopen the committed
`PREREGISTRATION.md` or the terminal `FINDINGS_ROUTE3.md`: the preregistered
decision remains **UNFALSIFIABLE-IN-PRACTICE**. This appendix only asks whether
GATE B failed for *instrument* reasons, and what the induced sub-regime hints at.

## Classification (reported first)

**Effectively CLOSED (suggestive, n=22) — and INSTRUMENT FAILURE is ruled out.**

On the 22 items that actually induced the attractor, forcing a different
**pure-reasoning** path does **not** break the shared blind spot — if anything
it hurts: llama attractor-escape is **COT 0.955 > DECOMP 0.727 > CODE 0.318**.
McNemar DECOMP-vs-COT has **0** items where DECOMP escapes and COT does not,
versus **5** the other way (exact p=0.0625) — the *opposite* of the
instrument-failure trigger ("DECOMP escape clearly exceeds COT"). So this is not
a case of "the gate failed only because half the budget was non-inducing and a
focused battery would show Route 2 live" — on the inducing items we already have,
method-disjointness does not help. The terminal decision stands, now with a
directional mechanism (leans CLOSED) rather than pure "couldn't test." The one
honest hedge: at n=22 the McNemar is p=0.0625, so "CLOSED" is *suggestive*, not
established.

## 1. GATE B diagnostic — manipulation vs item mix

**(1a) Density was a whole-battery average across inducing and non-inducing
categories.** On the 22 attractor items the mean density is **5.05** (≥3 by
construction — attractor-hits ⊆ wrong-agents — so re-checking density *there* is
circular). Over all 72 valid items it is **2.10**. The pre-registered criterion
("mean wrong-agents-per-item ≥3 over valid items") is not mis-aggregated in a bug
sense — it is a legitimate whole-battery manipulation check — but it reflects the
**item mix** (half the budget was non-inducing) more than the per-item strength
of the manipulation, which on the inducing subset is strong (concentration 1.0).

**(1b) Per-category attractor yield (valid items):**

| category | valid | attractor (≥3 hits) | yield | mean density |
|---|---|---|---|---|
| ii_noop | 40 | 21 | **52%** | 2.85 |
| i_classic | 12 | 1 | 8% | 1.33 |
| iii_substitution | 20 | 0 | 0% | 1.05 |

An 80-item **NoOp-only** battery at the observed 52% yield would give **~42
attractor items** (well past the ≥25 threshold). **But** the all-NoOp mean
density is **~2.85**, still short of the ≥3.0 threshold — so a focused battery
would clear two GATE-B criteria (item count, concentration) and **still narrowly
miss density**. Combined with (2), this is why a focused battery is not warranted:
it would neither cleanly pass GATE B nor show DECOMP beating COT.

**(1c) Agent-pool composition.** The density/cardinality pool is the **12
deterministic agents = 4 models × 3 methods**; **3** are llama (its COT/DECOMP/
CODE, indices 0–2). The M1 same-model samples are **not** in this pool (they are
separate indices 12–15), so the pool is 4 distinct models, not llama-heavy. The
"≥3 wrong of 12" threshold is largely meaningful, not an artifact of
method-correlation within a model: of the 22 attractor items, **18/22 have ≥2
distinct models** hitting the attractor (median 3 distinct models), and only
**4/22** get all their hits from a single model's three methods.

## 2. Exploratory Phase D on the 22 attractor items (n=22, underpowered)

Computed from cache; **not** preregistered-confirmatory.

**Attractor escape rate per llama method** (item-level bootstrap CI):

| method | escape rate | 95% CI (over items) |
|---|---|---|
| COT | **0.955** | [0.864, 1.000] |
| DECOMP | **0.727** | [0.545, 0.909] |
| CODE | **0.318** | [0.136, 0.500] |

**Pairwise discriminator (D2: COT×DECOMP is the only pure-reasoning signal;
CODE = verification = Route 1, not manufactured independence):**

| pair | McNemar (a-esc-b-not / b-esc-a-not / discordant / exact p) | pairwise excess |
|---|---|---|
| **DECOMP vs COT** (primary) | 0 / 5 / 5 / **p=0.0625** | COT×DECOMP excess **0.0** |
| CODE vs COT | 0 / 14 / 14 / **p=0.0001** | COT×CODE excess 0.0 |
| CODE vs DECOMP | 1 / 10 / 11 / p=0.0117 | DECOMP×CODE excess 0.151 |

(a = first-named method escapes and second does not.)

- **DECOMP does not decorrelate the attractor relative to COT** — it escapes it
  *less* (0.727 vs 0.955), and never escapes where COT fails. Method-disjointness
  among pure-reasoning paths does not break the induced blind spot.
- **CODE is the *worst* escaper** (0.318), decisively behind COT (14–0 discordant,
  p=0.0001). This refutes the intuitive form of the D2 assumption for *this* class
  of attractor: CODE does not rescue via execution, because the NoOp error is in
  **problem comprehension**, and CODE faithfully executes the miscomprehension
  (writes a program that uses the irrelevant number). **Execution is an oracle for
  computational error, not for comprehension error.** This is a genuine refinement
  of the Route 1 story, not evidence for Route 2.
- **Held-out trust-lift, COT×DECOMP: +0.151 [0.034, 0.261]** (n_agree=17, item
  bootstrap, C1 definition). When the two pure-reasoning paths agree, the answer
  is more accurate than the mean held-out agent — consistent with
  `CARDINALITY_LAW.md` (agreement is informative), but this is *agreement quality*,
  not *path-independence breaking the attractor*, and does not move the LIVE/CLOSED
  call.

## 3. Contamination caveat (weakens the "capability, not blind spot" claim)

phi-4 hit the NoOp attractor **0/40** times. phi-4 was released **Dec 2024**,
after GSM-Symbolic/GSM-NoOp were published (**Oct 2024**). The NoOp *items here
are hand-built*, not the published dataset, so direct item contamination is
impossible — but the **NoOp technique** (ignore the irrelevant clause) could have
entered phi-4's training. Since the terminal write-up's "capability-driven, not a
shared blind spot" reading partly rests on phi-4's immunity, that reading is
**confounded** and cannot be cleanly separated from contamination. Mitigating but
not resolving it: the picture is mixed — **gemma-2** (released *before* GSM-NoOp)
is the *most* fooled (0.31–0.36), while llama and mistral (also pre-NoOp for
llama-3.1) mostly resist (COT 0.03 / 0.06). So resistance is not simply "post-NoOp
models are immune." The honest status: capability and contamination are entangled
here and this appendix cannot separate them.

## What this changes

Nothing in the committed decision. It sharpens the *reason*: the terminal
UNFALSIFIABLE-IN-PRACTICE result now has a directional, suggestive-but-underpowered
reading that **leans CLOSED** (forcing different reasoning paths does not break an
induced shared attractor; DECOMP ≤ COT; CODE worst), and it **rules out instrument
failure** (DECOMP does not beat COT, so a focused NoOp battery would not surface a
Route-2-LIVE result — it would confirm CLOSED, at ~$1, which does not change the
Route 1 build decision either way). Per the anti-self-deception rule, no round 4 is
proposed. Route 1 (external verification anchor) remains committed — with the added
nuance that verification helps for *computational* error and not for
*comprehension* error, which needs correct reading, not a bigger committee.
