# R-EVID — prior art, and what survives

**Written 2026-08-21, after the theorems were committed.** The claim being
tested is the one this route was drifting toward in conversation: *"six theorems,
first ever."* **It is false, and on the theorem that felt most original it is
furthest from true.**

Recorded here rather than by editing `THEOREMS.md` or `THEOREMS_C.md`, which
stand as committed. `research/CORRECTIONS.md` #32 indexes this.

---

## 0. The standard applied

`research/prior_art/FINDINGS_PRIOR_ART.md` §3 already did this to the
competence bound and concluded *"THE COMPETENCE BOUND HAS A NAME, AND IT IS NOT
OURS"* (the generation–verification gap). §4 did it to delegation depth caps
(macaroons). The same standard is applied here, and it produces the same kind
of answer.

Its §0 method finding is also binding: **a summariser asked for something a
paper does not contain will often produce it.** Every claim below that matters
was checked against the primary source — the Sahoo paper was read via
`pdftotext`, not via a summary.

## 1. Theorem by theorem

| # | claim | prior art |
|---|---|---|
| 1 | separating level exists iff `ρ > N/K` | elementary algebra; not a claimable result |
| 2 | a cumulative bound refuses every benign agent at `⌈L/b⌉` | **this is why token buckets exist.** The quota-vs-rate-limit distinction is standard systems engineering (token bucket, RFC 1633, 1994) |
| 3 | CUSUM buys lifetime exponentially, a level linearly | Page 1954; Lorden 1971; Moustakides 1986 — cited in `THEOREMS.md` §6 |
| 4 | `E[n] ≈ log A / D` | Wald 1945 — cited |
| **5** | **the reflection criterion** | **Neely's virtual queues.** `Q(t+1) = max(0, Q(t) + a − b)` with Lyapunov drift is the foundational technique of stochastic network optimization. Textbook since ~2010 |
| **6** | reversal is a capacity, `r > b` | **that is queue stability, `λ < μ`** |

> **Theorem 5 was presented as the deepest contribution. It is the most standard
> object in the set.** "Safety virtual queues" as runtime-observable backlogs,
> with Foster–Lyapunov drift arguments, already appear in current
> network-control work doing exactly the job assigned to them here.

## 2. The agent-safety application is also prior

**Sahoo, *The Controllability Trap: A Governance Framework for Military AI
Agents*, ICLR 2026 Workshop on Agents in the Wild, arXiv 2603.03515 (March
2026)** defines, verbatim:

```
IC(t) = Σ_{j=1}^{t} ι(a_j)
```

> *"The Irreversibility Budget `I_B` is set by the operational commander. When
> `IC(t) ≥ I_B`, the agent must pause and request human re-authorization."*

That is `Q(n) = Σ hᵢ` against a level `L`, for AI agents, **five months before
this route.** Further:

- `ι(a) = 0` for fully reversible actions — **our SILENCE case, present as a
  design feature.**
- *"authorize budget **replenishment**"* — the compensation term `c`.
- A **collective** budget across a swarm, which we have not addressed at all.

**What that paper does not appear to contain** (checked against the extracted
text, not a summary): any analysis of whether the budget necessarily exhausts,
any drift condition, any replenishment-*rate* condition, any false-alarm
analysis. It is a governance framework and does not claim to be an analysis.
**But the mechanism is theirs first, and any future write-up must cite it.**

## 3. Adjacent work checked and found NOT to duplicate

- ***What Can Be Enforced? A Theory of Certified Runtime Safety for Tool-Using
  Agents*** (arXiv 2607.22868) — models monotone budgets as **register automata
  with saturating counters** and calibrates thresholds by **conformal risk
  control**. Decidability and risk certification, not a soundness
  classification. No drift, no reflection, no false-alarm necessity.
- ***Oversight Has a Capacity*** (arXiv 2606.08919) — a **fatigue-depletion**
  reviewer model `r(ℓ) = max(r_min, 1 − slope·max(0, ℓ − C))`, explicitly *"not
  a novel-mechanism paper … an applied, measurement-driven systems study"* with
  no formal stability theorem. Closest in spirit to our Corollary 6.2 and does
  not state it.
- ***Drift-to-Action Controllers*** (arXiv 2603.08578) — "drift" here means
  **distribution shift**, not random-walk drift. **A false hit from the title**,
  recorded because it nearly entered this table on the strength of its name.
- **CUSUM for LLM monitoring** — DeepLLR-CUSUM; CUSUM-shaped inference-time
  monitoring; LDP-CUSUM. **Applying sequential detection to LLM monitoring is
  not novel as of 2025–26.**

## 4. What survives

1. **The classification as an audit method** — declaring the drift class *beside
   each declared bound* and enforcing it with a standing test
   (`tests/test_drift_classification.py`). No prior art found for that specific
   move.
2. **The measured result** — a real system's registered, *signed* harm classes
   are mostly timers: `ρ = 1.000` for two of them, `b = 0.000` for the one that
   works. An empirical finding about a deployed system, ours because the system
   is ours.
3. **Two live defects the method found** — `action_rate_cap` (a lifetime quota
   named a rate, hard permanent refusal) and `load_bounds` silently dropping
   fields. Engineering value, independent of novelty.
4. **The append-only tension** — that the principle which closes blind channels
   forces monotone folds, hence timers. **UNCHECKED: not searched directly.**
   Treat as open, not as clear.

## 5. The honest position

A rigorous, well-instrumented audit method that found real defects in its own
system, built on classical mathematics that was correctly cited, applied to a
problem someone else framed five months earlier.

**That is solid work. It is not six new theorems**, and the word "epochal" was
doing work the evidence did not support.
