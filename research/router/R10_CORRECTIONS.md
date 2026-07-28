# R10 CORRECTIONS — an amendment to Route 10 Parts C and D

**This is an AMENDMENT. `breadth_grading/FINDINGS_R10.md` and
`breadth_grading/PREREGISTRATION_R10.md` are NOT edited and remain committed as
written.** Nothing here re-runs a simulation: every number below is re-derived from
the committed `breadth_grading/r10_result.json`, read-only, by
`research/router/part_a.py`.

Both defects corrected here were **disclosed by R10 itself** (`FINDINGS_R10.md` §2,
§3, §4 "Two preregistration defects, disclosed not repaired"). R10 was bound by its
own preregistered rules and reported them as written. This file applies the
corrections that R10 could not apply to itself.

**All prior decisions stand.** R9 = ADEQUATE-BUT-RESTRICTIVE, R12 = UNSOUND, R10
Part A (the harm model) and Part B (MIXED — harm must be a measure, not a boolean)
are untouched.

---

## A1 — PART C: `DOES-NOT-COMPOSE` → **COMPOSES-CONDITIONALLY**

### Why the recorded verdict was wrong

R10's preregistered rule mechanically fired **COMPOSES**, and R10 correctly called
that firing **vacuous**: the θ\* selection rule ("largest θ with `max H_lost ≤ 2θ`
and perm ≥ 0.80") is trivially satisfied for every θ ≥ 0.5, so it selected
**θ\* = 1.0** — a guard that admits everything and is byte-identical to the
unguarded baseline. R10 therefore reported the substantive verdict as
**DOES-NOT-COMPOSE**.

That substitution over-corrected. **A matrix containing a composing cell cannot be
summarised as does-not-compose.** R10's own supplementary run contains
`G5(0.25) + append-only` at N = 8 with **0 violations, harm bounded exactly at θ, at
full unguarded throughput**.

The correct treatment of a rule that selects a vacuous configuration is that the rule
is **INAPPLICABLE**, not that its output is authoritative in either direction. So:

> **The θ\* rule is INAPPLICABLE. The verdict is COMPOSES-CONDITIONALLY, and the
> conditions are enumerable from the measured matrix.**

### The control holds

**66 serialized cells, 0 total violations.** Depth composition works with multiple
actors; a serialized multi-agent trajectory is a longer trajectory and nothing more.
This reproduces R9 exactly and is unchanged from R10.

### The corrected concurrent matrix (non-vacuous guards only)

`G0` and `G5(1.0)` are excluded: both admit everything, so a cell running them is not
evidence about composition. 42 non-vacuous concurrent cells; **12 compose.**

| guard | N | accounts | storage | viol | thru | max `H_lost` | recoverable |
|---|---|---|---|---|---|---|---|
| G2 | 2 | shared | mutable | 1 | 2.00 | 0.350 | False |
| G2 | 2 | shared | append-only | 1 | 2.00 | 0.100 | False |
| G2 | 2 | partitioned | mutable | 1 | 2.00 | 0.350 | False |
| G2 | 2 | partitioned | append-only | 1 | 2.00 | 0.100 | False |
| G2 | 4 | *(all four)* | — | 1 | 2.00 | 0.100–0.350 | False |
| G2 | 8 | *(all four)* | — | 1 | 2.67 | 0.150–0.425 | False |
| **G3** | **2, 4, 8** | **shared** | **append-only** | **0** | **0.67** | **0.000** | **True** |
| **G3** | **2, 4, 8** | **partitioned** | **append-only** | **0** | **0.67** | **0.000** | **True** |
| G3 | 2, 4, 8 | shared / partitioned | mutable | 1 | 0.50 | 0.044 | False |
| **G4** | **2** | **shared / partitioned** | **mutable** | **0** | **1.83** | **0.300** | False |
| **G4** | **2** | **shared / partitioned** | **append-only** | **0** | **1.83** | **0.050** | False |
| G4 | 4 | *(all four)* | — | 1 | 2.00 | 0.100–0.350 | False |
| G4 | 8 | *(all four)* | — | 1 | 2.67 | 0.150–0.425 | False |
| G5(0.05) | 8 | shared | mutable / append-only | 1 | 0.67 / 2.67 | 0.074 / 0.150 | False |
| G5(0.10) | 8 | shared | mutable / append-only | 1 | 1.33 / 2.67 | 0.191 / 0.150 | False |
| **G5(0.25)** | **8** | **shared** | **mutable** | **0** | **2.00** | **0.250** | False |
| **G5(0.25)** | **8** | **shared** | **append-only** | **0** | **4.00** | **0.250** | False |

**`violations` is a BINARY INDICATOR** (every non-zero value in the dataset is exactly
1), not a count of violating rounds. It answers *did a joint violation occur*, not
*how many*. Nothing here measures violation frequency.

### The conditions under which local checks compose

1. **Recoverability (G3) + append-only storage — composes at every N tested (2, 4, 8),
   under BOTH shared and partitioned accounts.** 0 violations, `H_lost` = 0.000, final
   state recoverable, at *higher* throughput than its mutable counterpart
   (0.67 vs 0.50). This is R10's H-APPEND, and it is the strongest cell in the matrix.
2. **Graded reversibility at meaningful θ — `G5(0.25)` composes at N = 8 under BOTH
   storage models**, harm bounded exactly at θ = 0.250. Under append-only it does so at
   **4.00 throughput — identical to the unguarded baseline.** R10's supplementary
   section highlighted only the append-only cell; **the mutable cell composes too**, at
   half the throughput. Neither leaves the state recoverable — bounded loss is not zero
   loss.
3. **Conservation (G2) — never composes.** Violations at N = 2, 4 and 8, under every
   storage model and every account partitioning.
4. **Authorization pools (G4) — composes at N = 2 only**, then fails at N = 4 and 8
   under every configuration. N = 2 is not evidence of composition; it is the smallest
   arena in which the race has least opportunity to fire.

**Scope limit, disclosed:** the `G5(θ)` cells at θ ∈ {0.05, 0.10, 0.25} were run
**only at N = 8 with shared accounts** (12 supplementary cells). The claim
"G5(0.25) composes" is therefore an N = 8, shared-accounts claim, **not** an
all-N claim like the G3 + append-only result. It was also not preregistered.

### The mechanism — why H-CONS was refuted

R10 predicted conservation would compose once accounts were partitioned
(PARTITION-DEPENDENT). It does not: **G2 and G4 violate under partitioned accounts
exactly as under shared ones.** The diagnosis:

> **THE GUARD'S OWN STATE IS THE CONFLICT SET.**

Partitioning the *accounts* leaves the *guard's* state shared — G2 has a single
counter `c`; G4 has a single pool of single-use authorizations. Eight agents each
check `c + drain ≤ B` against the same pre-round `c = 0`; all pass; the joint total
blows the budget. Eight agents each match the same unconsumed authorization. **A guard
with one global counter has a conflict set of size one no matter how the accounts are
arranged.**

Bitcoin is the contrast, and the distinction is sharper than "it partitions state":
**each UTXO is an independent spend-once token, and validating a spend is stateless
with respect to every other UTXO.** Bitcoin partitions *the guard's own state*, not
merely ownership.

> **DESIGN RULE. A guard scales in breadth only if its state partitions along the same
> axis as the actions.** A monotone budget is inherently global, therefore inherently
> serializing, **regardless of how the underlying resource is partitioned.**

This is why G3 + append-only is the exception that proves the rule: append-only
storage removes the shared mutable cell the racing agents were both writing, so the
predicate stops having a conflict set at all.

---

## A2 — PART D: `NOT-TUNABLE` → a real frontier under mutability, and **no frontier at
all under append-only**

### Why the recorded verdict was unsound

Two defects, both disclosed by R10:

1. **The TUNABLE rule demanded strict improvement on BOTH axes** — "harm ≤ the k = 1
   level **and** throughput > 2× k = 1". That is the definition of *not* a frontier:
   **a tradeoff cannot dominate itself.** The rule could only have fired in a
   degenerate case.
2. **At k = 1, every round was rolled back (30/30)**, so the reported nominal
   throughput of 4.00 corresponded to **zero surviving work**. Counting
   admitted-but-rolled-back actions as throughput inverts the entire reading.

### Corrected: EFFECTIVE throughput, and the Pareto question

`effective_throughput` = admitted-and-not-rolled-back actions per round. It is already
present in `r10_result.json`; no re-simulation was needed.

Corrected rule: **FRONTIER-EXISTS if the (harm, effective-throughput) points across k
are not all dominated by a single k** — i.e. at least two non-dominated operating
points.

**Mutable archive:**

| k | harm | nominal | **EFFECTIVE** | rollbacks |
|---|---|---|---|---|
| **1** | **0.0294** | 4.00 | **0.00** | 30/30 |
| **5** | **0.2500** | 4.00 | **3.20** | 6/30 |
| 10 | 0.5000 | 2.53 | 2.28 | 3/30 |
| 25 | 0.5000 | 1.87 | 1.80 | 1/30 |
| 50 | 0.5000 | 1.20 | 1.20 | 0/30 |
| ∞ | 0.5000 | 1.20 | 1.20 | 0/30 |

**PARETO SET = {k = 1, k = 5}. FRONTIER-EXISTS = True.** k = 10, 25, 50 and ∞ are all
dominated by k = 5 — strictly worse on both axes. The frontier is real but brutal: it
runs between **"no useful work at almost no harm" (k = 1)** and **"3.20 effective
throughput at harm 0.250" (k = 5)**. There is no intermediate operating point.

**Append-only archive:**

| k | harm | nominal | **EFFECTIVE** | rollbacks |
|---|---|---|---|---|
| 1 | 0.0000 | 4.00 | 0.27 | 28/30 |
| **5** | **0.0000** | 4.00 | **3.20** | 6/30 |
| 10 | 0.2500 | 2.53 | 2.28 | 3/30 |
| 25 | 0.2500 | 1.87 | 1.80 | 1/30 |
| 50 | 0.2500 | 1.20 | 1.20 | 0/30 |
| ∞ | 0.2500 | 1.20 | 1.20 | 0/30 |

**PARETO SET = {k = 5}. FRONTIER-EXISTS = False — and this is the good outcome.**
k = 5 achieves **harm 0.0000 at 3.20 effective throughput**, dominating every other k
including k = 1 (equal harm, 12× the useful work). There is no frontier because
**there is nothing to trade off**: append-only storage collapses the tradeoff instead
of moving along it.

> **The harm/throughput frontier is an artifact of mutable storage.** Under
> append-only storage the frontier does not exist, because the dominating point
> achieves zero harm and full effective throughput simultaneously.

### RESULT — ROLLBACK HAS A FLOOR THAT THE REPRESENTATION DOES NOT

*Stated as a standalone claim, because it is the strongest architectural finding in
Part A and R10 recorded it only as an observation about append-only halving harm.*

> **At k = 1 — a checkpoint every single round — mutable-archive harm is 0.0294 while
> append-only harm is 0.0000. Maximum checkpoint frequency cannot restore destroyed
> content; under mutable storage the deletion already happened. Therefore checkpoint
> frequency bounds RESOURCE and OWNERSHIP loss, and only append-only storage bounds
> CONTENT loss. Checkpointing is not a substitute for the representation choice.**

The mechanism is that rollback restores *what the checkpoint retained*. The harness
holds an immutable checkpoint of balances, ownership and objects, so those are
restorable. A mutable archive keeps no pre-image of a destroyed object, so there is
nothing for the rollback to restore — and this is true **at every checkpoint
frequency, including the maximum.** k = 1 is the limit case and it does not reach
zero. No frequency does.

> **COROLLARY. The harm/throughput frontier is an artifact of mutable storage.** Under
> append-only storage, k = 5 achieves harm **0.0000 at full effective throughput
> (3.20)** and **dominates every other k, including k = 1** — which pays 28/30
> rollbacks for 0.27 effective throughput at the same zero harm. The principle
> **collapses the tradeoff rather than moving along it.**

The practical reading: a system that reaches for more frequent checkpointing to bound
content loss is buying a guarantee it cannot obtain at any price, while paying the
rollback cost in full. The representation is the lever; the frequency is not.

**Scope:** N = 4, 30 rounds, one agent policy, the 42-asset arena. The *floor*
(k = 1 mutable > 0 = k = 1 append-only) is a structural consequence of what a
checkpoint retains and does not depend on those parameters; the *magnitudes*
(0.0294, 0.250, 3.20) are arena-specific.

### One asymmetry that remains asserted, not measured

**External sends cannot be rolled back** — they left the modeled system. R10 asserted
this in the design but **never exercised it**: `channel_assets_lost = 0` in every Part
D cell, because the agent policy proposes deletes and transfers, never sends. **The
claim stands as a model property, not as a measurement**, and is repeated here with
the same label.

---

## Summary of corrected verdicts

| | R10 as committed | corrected | why |
|---|---|---|---|
| Part C | COMPOSES (vacuous) / DOES-NOT-COMPOSE (substantive) | **COMPOSES-CONDITIONALLY** | θ\* rule INAPPLICABLE; 12 of 42 non-vacuous concurrent cells compose, and the conditions are enumerable |
| Part D, mutable | NOT-TUNABLE | **FRONTIER-EXISTS**, Pareto {1, 5} | the TUNABLE rule demanded self-domination; effective throughput is the right axis |
| Part D, append-only | NOT-TUNABLE | **NOT-A-FRONTIER — tradeoff collapses** | k = 5 dominates everything at zero harm and full effective throughput |

Part A (harm model) and Part B (MIXED) are unchanged.
