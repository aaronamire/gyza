# Reversibility coverage, and the audit economics instantiated

---

> # ⚠ CORRECTION BLOCK — 2026-08-10, `reversibility-correction`
>
> **This document's own §A3 count is corrected. Prior text preserved unedited.**
>
> **CLAIMED below:** *"the operationally meaningful reversible count is 4, not
> 7"* — the four append-only actions `rollback()` can reach.
>
> **MEASURED, under the criterion this program already fixed** (*"here is the
> undo operation", not "could be undone in principle"*): **ZERO of 19 action
> types have a PER-ACTION undo.** `StagingArea.rollback()` abandons a **whole
> staged range** since the last promotion; it takes no action identifier and
> cannot target one. So the 4 are **within reach of a coarse batch
> abandonment**, which is not the same predicate as *reversible*.
>
> | reading | count |
> |---|---|
> | declared `REVERSIBLE_INTERIOR` | 7 / 19 |
> | ~~state-changing AND undoable~~ → **within reach of COARSE batch abandonment** | **4 / 19** |
> | **action types with a PER-ACTION undo** | **0 / 19** |
>
> **DEFINITIONAL, not a new measurement:** it follows from reading
> `rollback()`'s signature (`staging.py:148`) — it takes a `reason` string and
> nothing else. **No re-derivation was required; the prior count answered a
> weaker question than the one that matters.**
>
> **CORRECTED MECHANISM:** the interior is unbounded because it is
> **UNCOMMITTED**, not because it is reversible. Two consequences that do not
> follow from "reversible": **abandonment is coarse**, and **past the promotion
> gate there is no recovery at all.**
>
> **What is UNCHANGED:** every by-call-site number (2 production sites total,
> residue 0), the A3 storage split, and all of Part B. Those did not depend on
> the per-action reading.
>
> **A number in the task that does not match the tree:** the task states *"zero
> of thirteen action types"*. The vocabulary is **19**, not 13, verified by
> executing `ReversibilityTable().vocabulary`. The **zero** is right; the
> denominator is not.

---

**Branch `costless-measurements`.** **Zero credits** — source inspection and
arithmetic over committed data. No generation. No production code changed.

---

## 0. One premise corrected before the measurement

> *"Nobody has measured what fraction of the vocabulary is actually
> reversible."*

**A classification already existed.** `gyza/containment/reversibility.py:30`
declares the vocabulary and assigns every action a class. What had **never**
been done is (a) weighting it by call site, (b) checking rollback
*reachability* rather than assuming it, and (c) separating *durable* from
*reversible*. Those are what this measures.

---

## 1. PART A — COVERAGE

### A1. The vocabulary IS enumerable — **19 action types**, `reversibility.py:30`

It is a single declared table, not scattered call sites, so the architecture's
assumption **is** expressible. Whether it is *exercised* is a different question
and is §A4.

### A4. COVERAGE — BOTH WEIGHTINGS, and they disagree completely

| class | types | fraction | **production call sites** | fraction |
|---|---|---|---|---|
| **REVERSIBLE_INTERIOR** | **7** | **0.3684** | **2** | 1.0000 |
| IRREVERSIBLE | 6 | 0.3158 | **0** | 0.0000 |
| EGRESS | 6 | 0.3158 | **0** | 0.0000 |
| **TOTAL** | **19** | 1.0000 | **2** | |
| **UNDETERMINED** | **0** | — | — | reported separately by design |

> ## THE HEADLINE IS THE SECOND COLUMN, AND IT IS NOT 1.0000 — IT IS 2.
>
> **The entire action vocabulary is tagged at exactly TWO sites in `gyza/`, both
> `stage_artifact`:** `gyza/coordination/orchestrator.py:254` and
> `gyza/containment/staging.py:205`. The first is in the orchestrator, which has
> **zero production callers**; the second is the containment machinery
> referring to itself.

**Diagnosing the exact 1.0000 (A5): it is VACUOUS.** It is 2/2. With a
denominator of 2 the by-call-site weighting carries no information about the
system — and that *is* the finding. `GuardEngine`, `StagingArea` and
`PromotionGate` are constructed **only in tests and one research script**
(`run_sr5.py`). **No running code classifies an action, stages one, or promotes
one.**

> **So the architecture's central assumption is expressible but not exercised.**
> "Reversible actions need not be verified before acting" is a claim about a
> machine that is built and idle. **DEFINITIONAL, not measured:** nothing is
> reversible *in production* because nothing is *anything* in production.

**Counter-metric, honestly:** the by-type 0.3684 is a **declaration**, not a
measurement of the property. The table asserts these classes; §A3 shows the only
mechanical check available agrees with it *by construction*.

**False matches excluded and listed** (auditable, not silent): `"read"` in
`identity.py`, `sandbox/config.py`, `cli.py`, `delegation.py` is a
capability-manifest key (`fs.get("read")`); `"sign_envelope"` in `icp.py` is an
`__all__` export. Six files, all verified by reading.

### A3. APPEND-ONLY / ROLLBACK-REACHABILITY — **the split that matters**

| bucket | n | actions |
|---|---|---|
| **append-only AND rollback-reachable** | **4** | `claim_work_item`, `reserve_credits`, `stage_artifact`, `stage_envelope` |
| **append-only but NOT reachable** | **3** | `grant_delegation`, `settle_credits`, `sign_envelope` |
| mutable | 3 | `delete_artifact`, `rotate_key`, `update_guard_config` |
| external (egress) | 6 | the six emission actions |
| no write at all | 3 | `read`, `compute`, `retrieve_memory` |

> **THE THREE APPEND-ONLY-BUT-UNREACHABLE ACTIONS ARE DURABLE, NOT REVERSIBLE.**
> A signed envelope, a settled credit and a granted delegation all land in
> append-only storage — nothing is destroyed — but **`StagingArea.rollback()`
> cannot reach them**, because `stage()` refuses to stage anything not classed
> REVERSIBLE_INTERIOR (`staging.py:83-88`). An append-only log with no reachable
> rollback is durable. It is not undoable.

**So the operationally meaningful reversible count is 4, not 7:**

| reading | count | fraction |
|---|---|---|
| declared REVERSIBLE_INTERIOR | 7 | 0.3684 |
| **state-changing AND undoable** | **4** | **0.2105** |
| reversible only because they change nothing (`read`, `compute`, `retrieve_memory`) | 3 | 0.1579 |

**And the undo is named, as A2 requires:** `StagingArea.rollback()`
(`staging.py:148`). **It is a BATCH undo to the last promotion, not a per-action
inverse** — and after promotion the watermark moves, so **nothing is reversible
once promoted.** "REVERSIBLE_INTERIOR" means *reversible while staged*.

**A3's reachability check is DEFINITIONAL, and I will not dress it up as
corroboration.** `stage()` accepts exactly the class the table calls reversible,
so reachability agrees with the classification **by construction**. It confirms
the plumbing is consistent; it says nothing about whether the underlying action
is truly reversible.

---

## 2. PART B — THE AUDIT ECONOMICS

### B1. PARAMETER INVENTORY — **and it is one number, not four**

| param | kind | note |
|---|---|---|
| **q** detection given audit | **MEASURABLE** | 0.818 in / 0.556 out — `FINDINGS_R6.md:48-49` |
| **f** false-conviction rate | **MEASURABLE** | 0.041 in / 0.444 out — same source |
| **g** gain from a false claim | **BUSINESS DECISION** | what a lie is worth |
| **w** honest profit per claim | **BUSINESS DECISION** | only the ratio `g/w` enters |
| **B** bond | **BUSINESS DECISION** | **CANCELS from feasibility** (`PROPOSITIONS.md:303`) |

> **Correcting the task: it is 3 business parameters of 5, not 4. And because
> the bond cancels, the user must decide exactly ONE NUMBER: `g/w`.**
> B is needed only to convert a feasible region into an audit *probability*, not
> to decide whether a mechanism can exist at all.

**No value was invented for g, w or B.**

### B2. What the measured numbers actually say

Verified against the committed source rather than the restatement:

| regime | TPR | FPR | n | **LR = q/f** | source |
|---|---|---|---|---|---|
| **in-competence** | 0.818 | 0.041 | **433** | **19.95** | `FINDINGS_R6.md:48` (6B cell-a) |
| **out-of-competence** | 0.556 | 0.444 | **36** | **1.25** | `FINDINGS_R6.md:49` (6B cell-b) |
| out, **calibrated** | q = J_out = 0.112 | 0.444 | 36 | **0.25** | `MODEL.md:50` |

**A correction the task's restatement omits:** the calibrated model does **not**
use the raw out-of-competence TPR. `MODEL.md:50` bounds out-of-competence
detection by the *actionable edge* `J_out = TPR − FPR = 0.111`, "swept over
[0, 0.3] because cell-(b) is underpowered (n=36, CI incl 0)." **Using the raw
0.556 overstates LR_out by 5×** (1.25 vs 0.25).

**SCOPE, and it is a JUDGEMENT not a measurement:** these were measured on a
**cross-model checker over a MATH/reasoning task family** (Phase 6B), n=433 and
n=36. **Whether they transfer to Gyza's claim vocabulary — signatures, folds,
capability containment — is authored judgement, and I think transfer is
doubtful in the favourable direction:** Gyza's in-competence claims are
mechanically checkable at LR far *above* 19.95 (a signature verifies or it does
not), while its semantic claims are exactly the out-of-competence regime. The
measured pair probably brackets the truth rather than describing it.

### B3. THE FEASIBILITY FRONTIER — feasible iff `LR = q/f ≥ g/w`

| `g/w` | in-competence (19.95) | out raw (1.25) | out calibrated (0.25) |
|---|---|---|---|
| 1.00 | ✅ FEASIBLE | ✅ FEASIBLE | ❌ |
| 1.25 | ✅ FEASIBLE | ✅ FEASIBLE | ❌ |
| 2.00 | ✅ FEASIBLE | ❌ | ❌ |
| 5.00 | ✅ FEASIBLE | ❌ | ❌ |
| 10.00 | ✅ FEASIBLE | ❌ | ❌ |
| **19.95** | ✅ **FEASIBLE (the edge)** | ❌ | ❌ |
| 20.00 | ❌ | ❌ | ❌ |

**In words:** in-competence, **a lie may be worth up to ~20× honest profit and
the mechanism still works.** Out-of-competence it must be worth **barely more
than honest work** — and on the calibrated reading, **less than honest work**,
i.e. no temptation at all is tolerable.

### B4. THE RESIDUE — **9 action types, 0 production call sites**

The audit economics govern claims that are neither reversible nor verified by
construction:

| | |
|---|---|
| action types | 19 |
| − REVERSIBLE_INTERIOR | −7 |
| − covered by a **governed** verifier (`sign_envelope`, `settle_credits`, `grant_delegation`) | −3 |
| **= RESIDUE** | **9  (0.4737 of the vocabulary)** |

`delete_artifact`, `rotate_key`, `update_guard_config`, and all six egress
actions.

> ### **RESIDUE BY PRODUCTION CALL SITE: 0 of 2.**
>
> **Say it plainly: the audit mechanism currently governs a slice of running
> code that is empty.** Nearly half the *vocabulary* by type, and nothing at all
> by what executes. The economics are sound and the frontier is real; they have
> no population to apply to yet.

**Note the mapping action-type → verifier is AUTHORED JUDGEMENT** (4 pairs, one
of which — `external_send` → `external_send_content` — is *not* governed, since
it sits in the migration gap, so it stays in the residue).

---

## 3. WHAT THIS DOES NOT ESTABLISH

1. **The bound is on the RATE of undetected consequential error, not on any
   individual claim.** No claim is guaranteed correct. ε(r) plateaus at 0.219·e₀
   past r ≈ 0.05 (`FINDINGS_R6.md`), and **the residual floor is set by the
   competence bound, not the budget** — more auditing does not buy it down.
2. **It assumes a rational actor who responds to expected cost.** It says
   nothing about an actor who is simply **wrong rather than strategic**. Prior
   work established adversarial defensibility catches strategic deception but
   **not sincere confusion**, and sincere error is the ~20–30% case the
   frontier ledger records.
3. **q and f come from a different population** — a cross-model checker on a
   reasoning task family, n=433 / n=36. **Transfer to Gyza's claim vocabulary is
   a judgement** (§B2), and the out-of-competence cell is underpowered with a CI
   including zero.
4. **The reversibility classification is a declaration.** The only mechanical
   check available agrees with it by construction (§A3).
5. **Both parts describe a machine that is not running.** Every by-call-site
   number in this document is dominated by the fact that the containment engine
   has no production caller.

## 4. Artifacts

- `research/reversibility/measure.py` + `coverage.json`
- `research/audit_economics/instantiate.py` + `frontier.json`
- No production code changed; `tests/test_containment.py` (the suite covering
  the module read here) **passes unchanged**.
