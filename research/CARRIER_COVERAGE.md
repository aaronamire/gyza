# Carrier coverage, and why the coverage fraction is not a composition budget

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
