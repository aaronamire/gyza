# Findings — SR-5: promotion granularity

Per `PREREGISTRATION_SR5.md` (`07c2be0`), committed before any result existed.
Deterministic, `SEED = 1`, zero model calls. Selection route: it closes here.

## DECISION: **PER-ACTION (k = 1)** — on the Occam tiebreak, not on the margin

| variant | k | **effective throughput** | nominal admission | escalation | gate evals / promoted | peak harm / bound |
|---|---|---|---|---|---|---|
| **per-action** | 1 | **0.0542** | 1.0000 | 0.946 | 18.46 | 0.99 |
| per-task | 4 | 0.0500 | 1.0000 | 0.950 | 5.00 | 0.97 |
| per-batch | 32 | **0.0000** | 1.0000 | 1.000 | ∞ | 0.00 |

per-action beats per-task by **0.42 percentage points**, which is **inside the
preregistered 5pp equivalence bound**. The two are therefore *equivalent on the
primary metric*, and the decision falls to the Occam tiebreak: **per-action
carries no batch state at all**, so it wins. Claiming a 0.42pp win as a
*result* would be over-reading the margin, and the preregistration exists to
stop exactly that.

**A tension the rule does not capture, reported rather than buried.** per-task
is **3.7× cheaper** per promoted action (5.00 vs 18.46 gate evaluations) for an
indistinguishable throughput. The preregistered rule ranks on effective
throughput with simplicity as tiebreak, so it selects per-action; if gate cost
is expensive in a real deployment, per-task is the defensible override. The rule
was not rewritten after seeing this.

## The counter-metric earns its keep

**Nominal admission is 1.0000 for every variant while effective throughput
ranges 0.0542 → 0.0000.** Nominal is completely uninformative here, exactly as
the preregistration predicted it would be.

The sharpest case is **per-batch (k = 32): peak harm / bound = 0.00**. Read
alone, that is a *perfect containment score*. It is achieved by promoting
nothing at all — every batch of 32 exceeds the bound wholesale, so every batch
is refused, nothing is ever admitted, and no harm is ever consumed. Perfect
containment and zero value, which is the TPR-without-FPR trap in its most
literal form. **A configuration that blocks everything must never be allowed to
look safe.**

## Point predictions, scored

| # | prediction | outcome |
|---|---|---|
| P1 | effective throughput highest at k=1, falling with k | ✓ 0.0542 > 0.0500 > 0.0000 |
| **P2** | **harm consumed EQUAL across variants** | **✗ WRONG** — 0.99 / 0.97 / 0.00 |
| P3 | gate cost amortizes with k | ✓ 18.46 → 5.00, but **∞** at k=32 |
| P4 | NOT-A-FRONTIER (no harm/throughput trade-off) | ✓ **conclusion holds, stated reason does not** |

**P2 was wrong, and P4's reasoning depended on it.** I predicted harm would be
equal because the bound is enforced at the gate in every configuration. It is
not equal, for a reason I did not anticipate: a variant that can never promote
consumes *no* harm. P4's conclusion — that there is no harm/throughput frontier
to tune, only a throughput/cost one — survives, but it survives for a different
reason than the one I gave. Recorded rather than quietly repaired.

**P3 holds only while a variant can promote at all.** Amortization is not
monotone in k; it inverts to infinity the moment k exceeds what the bound admits.

## The defect this route found in C-6

The preregistered feasibility check is what caught it. It required refusals at
k = 1 before the comparison could be trusted, and the first run reported
**zero**.

The cause was a real frame error in the promotion gate: it measured cumulative
harm from `baseline_state()` — the **moving rollback checkpoint** — so every
promotion silently re-based the measurement. Under that gate, promoting after
every action bought **unlimited drain**: each batch measured a fresh, tiny
delta and the run-level total was never anyone's frame.

That is R9's G4′ failure in this codebase's own shape, mirrored: G4′ pinned the
frame at `s₀` and lost 175000; this pinned it at the *moving checkpoint* and
lost the bound entirely. Fixed by measuring cumulative harm from
`origin_state()`, the accounting-period origin, which is distinct from the
rollback checkpoint and does not move. Pinned by
`test_frequent_promotion_cannot_reset_a_cumulative_budget`.

**Without the feasibility check this route would have reported a clean
three-way tie at effective throughput 1.0 and concluded that granularity does
not matter.** The check was preregistered precisely because a metric sitting at
its ceiling means the harness is broken, not that the question is answered.

## Diagnosed clean numbers

- `nominal admission = 1.0000` for all three — **definitional**: every action is
  staged, and nominal counts staged-plus-rolled-back.
- `peak harm / bound = 0.00` at k=32 — **diagnosed above**: nothing is ever
  promoted, so nothing is ever measured. Not safety.
- `gate evals / promoted = ∞` at k=32 — same cause, division by zero promoted.

## What this cannot establish

Simulated workload, one harm class, one bound (100.0), one arrival pattern,
`SEED = 1`, refusal modelled as whole-batch rollback, and an effective
throughput of ~5% that is a property of *this* workload's drain-to-budget ratio
rather than of any granularity. It fixes a **parameter for this architecture**;
it is not a general claim about batching.
