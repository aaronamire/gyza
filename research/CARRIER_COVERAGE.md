# Carrier coverage, and why the coverage fraction is not a composition budget

---

> # ⚠ CORRECTION BLOCK — 2026-08-10, `carrier-corrections`
>
> **Every number below this block is STALE. Prior text is preserved unedited;
> nothing has been silently changed.**
>
> **Cause — and it is NOT a carrier reclassification.** No entry's carrier was
> ever corrected from PROOF to TEST. This document was computed **before the
> respecification** (`60081f4`, *"respecify: move 2 claim types out of
> NO_VERIFIER"*), which moved **`memory_retrieval_relevance`** and
> **`external_send_content`** from semantic/NONE into registered PROOF-carried
> verifiers (`gyza/verification/respec.py`). The document then drifted from its
> own generator: `selection_routes/carrier_coverage.py` recomputes these numbers
> from the live registry and **now disagrees with the table below.**
>
> | quantity | committed below | **recomputed from the registry** | |
> |---|---|---|---|
> | carriers | PROOF 10 · TEST 1 · SPEC 3 · **NONE 4** | **PROOF 12 · TEST 1 · SPEC 3 · NONE 2** | DEFINITIONAL |
> | tier-1 **claim types** | 11/18 = **61.1%** | **13/18 = 72.2%** | DEFINITIONAL |
> | depth-1 **chain** tier-1 | 0.5556 (implied) | **0.6667** | DEFINITIONAL |
> | depth 2 | 0.309 | **0.4444** | DEFINITIONAL |
> | depth 4 | 0.095 | **0.1975** | DEFINITIONAL |
> | **depth 8** | **0.009** | **0.0390** | DEFINITIONAL — **4.3× higher** |
> | depth-8 "any correctness claim" | 0.074 | **0.2326** | DEFINITIONAL |
> | depth-8 ceiling after all upgrades | 0.134 | **0.3897** | DEFINITIONAL |
> | *"4 of 18 claim types are semantic"* | 4 | **2** | DEFINITIONAL |
>
> **All DEFINITIONAL:** each follows arithmetically from the registry
> composition under the unchanged uniform-sampling assumption. **Nothing was
> re-derived and no new measurement was taken.**
>
> **The direction matters: every corrected figure is more favourable.** The
> committed numbers *understate* coverage. A stale pessimistic number is still
> wrong, and this one was load-bearing in two other documents.
>
> **A SECOND DEFECT IN THE TABLE BELOW, and it is artifact #17 inside a single
> column.** The row labelled *"isolated (depth 1) — 61.1%"* is a count of
> **CLAIM TYPES** (11/18), while every row beneath it is a **CHAIN PROBABILITY**
> (powers of 10/18: 0.5556² = 0.3086 ≈ the 30.9% shown). **The first row is a
> different quantity from the rest of its own column**, which is exactly the
> species `ARTIFACT_LEDGER.md` #17 records. The corrected figures above keep the
> two separate and are labelled accordingly.
>
> **What is NOT affected:**
> - **AR-1 is untouched.** It measured the *audited* path, whose five claim
>   types (`envelope_signature`, `envelope_chain`, `artifact_content_address`,
>   `manifest_identity`, `enforcement_within_manifest` — `run_ar1.py:33-39`)
>   are all genuine recomputers and **do not include** either respecified type.
>   Its `p_proof = 1.0000` stands.
> - **`ARTIFACT_LEDGER.md` #17 is NOT edited.** It records a *reasoning defect*
>   that occurred with these numbers; correcting the numbers does not unmake the
>   defect, and the ledger's definition must stay intact.
> - **`ENGINEERING_STATUS.md` and `OPEN_PROBLEM.md`** carry the same table and
>   **already mark it as superseded prior framing** (struck through, pointing at
>   AR-1). They inherit this correction; they are not separately edited, because
>   their rows are already labelled as not-current.
>
> **The qualitative conclusion below SURVIVES.** Multiplicative decay with depth
> is unchanged, the ceiling still binds, and the design guidance (minimise depth;
> keep semantic stages at boundaries; optimise for PROOF-or-SPEC carriage, not
> tier) is unaffected. **What changes is the magnitude, not the shape.**

---

**Analytic, not measured.** Every number below follows from the `TIER_ALGEBRA.md`
rules plus the V-1/V-4 registry's composition. Labelled DEFINITIONAL throughout:
it illustrates a consequence, it does not confirm a theory. Computed by
`selection_routes/carrier_coverage.py`, deterministic, zero model calls.

**Standing assumption, stated because every number inherits it:** chains are
sampled **uniformly** from the claim vocabulary. Real chains are not. This is
the main thing that could be wrong, and it is why the table below is a *shape*
argument rather than a forecast.

## A1 — the 18 claim types, by tier AND carrier

| claim type | tier | carrier | witness |
|---|---|---|---|
| `artifact_content_address` | 1 | PROOF | `gyza/network/artifact_store.py:47` |
| `balance_fold` | 1 | PROOF | `gyza/economy/wallet.py:274` |
| `delegation_attenuation` | 1 | PROOF | `gyza/economy/delegation.py:213` |
| `enforcement_within_manifest` | 1 | PROOF | `gyza/sandbox/config.py:286` |
| `envelope_chain` | 1 | PROOF | `gyza/icp.py:105` |
| `envelope_dag` | 1 | PROOF | `gyza/icp.py:217` |
| `envelope_signature` | 1 | PROOF | `gyza/icp.py:82` |
| `ledger_entry_signatures` | 1 | PROOF | `gyza/economy/ledger.py:348` |
| `manifest_identity` | 1 | PROOF | `gyza/identity.py:101` |
| `market_capital_fold` | 1 | PROOF | `gyza/economy/market.py` CapitalEntry fold |
| **`unit_test_execution`** | **1** | **TEST** | V-3 adapter (finite sample) |
| `hlc_ordering` | 2 | SPEC | human-authored |
| `reputation_score` | 2 | SPEC | human-authored |
| `work_claim_exclusivity` | 2 | SPEC | human-authored |
| `execution_output_content` | 3 | NONE | semantic — competence bound |
| `memory_retrieval_relevance` | 3 | NONE | semantic — competence bound |
| `routing_match_quality` | 3 | NONE | semantic — competence bound |
| `external_send_content` | 3 | NONE | semantic — competence bound (and C15) |

**PROOF 10 · TEST 1 · SPEC 3 · NONE 4.** `unit_test_execution` is the case that
motivated this document: **tier 1 and TEST-carried simultaneously.** Tier and
carrier are independent, and only one of them predicts composition.

## A2/A3 — THE HEADLINE: isolated coverage vs chain coverage

| | tier-1 | tier-2 | tier-3 | any correctness claim |
|---|---|---|---|---|
| **isolated (depth 1)** | **61.1%** | 16.7% | 22.2% | 77.8% |
| chains of depth 2 | **30.9%** | 21.3% | 47.8% | 52.2% |
| chains of depth 4 | **9.5%** | 17.7% | 72.8% | 27.2% |
| chains of depth 8 | **0.9%** | 6.5% | **92.6%** | **7.4%** |

> **61.1% tier-1 coverage in isolation is 0.9% at depth 8.** By depth 8, **92.6%
> of chains carry no correctness claim at all** and are containment-only.

The collapse is multiplicative and there is no threshold to tune: each stage is
another chance to draw a TEST-carried or semantic type, and one draw is enough.

## The hard ceiling — representation work cannot fix this

Upgrade **every** TEST and **every** SPEC type to PROOF. The four semantic types
cannot be upgraded at all: their correctness is a claim about content, which is
the competence bound, closed across six families and terminal.

| depth | tier-1 now | tier-1 after *all possible* upgrades |
|---|---|---|
| 2 | 0.309 | 0.605 |
| 4 | 0.095 | 0.366 |
| 8 | 0.009 | **0.134** |

**Even with perfect representation work, 86.6% of depth-8 chains are tier 3.**
The binding constraint is not the quality of Gyza's verifiers; it is that four
of eighteen claim types are semantic, and any chain touching one inherits that.

## What this does to K-2's objective

The decomposer's objective **is not** "maximise the fraction of subtasks that
are tier 1". Part A says that objective is nearly irrelevant to what a chain
ends up being. Three corrections follow, and they should be preregistered into
SR-1 rather than discovered afterwards:

1. **Minimise DEPTH before maximising per-subtask tier.** Depth is the exponent.
   A decomposition into 3 verifiable subtasks beats one into 8, even if the 8
   have a better per-subtask tier distribution.
2. **Avoid semantic-type stages inside a chain that needs a correctness claim.**
   One is enough to make the whole chain tier 3. Where a semantic stage is
   unavoidable, put it at a boundary and gate it, rather than in the middle of a
   chain whose tier you wanted.
3. **Optimise for PROOF-or-SPEC carriage, not for tier.** SPEC composes exactly
   as well as PROOF (SR-3: both 1.000). A tier-2 SPEC-carried chain is worth
   more than a tier-1 TEST-carried one, which the tier number inverts.

## A4 — representation upgrade candidates (the deliverable; not implemented)

| candidate | from → to | cost | value |
|---|---|---|---|
| `unit_test_execution` | TEST → PROOF | a human-authored property per claim type that RECOMPUTES rather than samples. This is C11's cost model: one spec per *type*, not per instance. Not generally possible — for an arbitrary function, recomputing the property *is* solving it (the competence bound). Possible where the claim has an algebraic invariant (length, multiset, ordering, conservation). | Removes the one type that turns a tier-1 chain into tier 3. Highest value per unit of work in the table. |
| `hlc_ordering` | SPEC → PROOF | the ratchet is already recomputable from the event log; the work is wiring it, not inventing it. | Low. SPEC already composes at 1.000; this buys tier-2 → tier-1, not composition. |
| `reputation_score` | SPEC → PROOF | recomputable as a fold over the event log (same shape as `balance_fold`). | Low, same reason. |
| `work_claim_exclusivity` | SPEC → PROOF | recomputable from the blackboard's claim log. | Low, same reason. |
| the four semantic types | NONE → anything | **not available.** Competence bound, terminal. | — |

**The actionable form of "coverage is a design variable, not a measurement":**
the only upgrade that changes the composition picture is the TEST → PROOF one,
and the ceiling above shows even that leaves depth-8 chains at 13.4% tier-1.
**The lever with real leverage is not upgrading verifiers — it is designing the
claim vocabulary so that chains are short and semantic stages sit at boundaries.**
