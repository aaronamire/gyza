# The reversibility correction, and the audit frontier at test parameters

**Branch `reversibility-correction`.** **Zero credits.** Document work and
arithmetic over committed data. No production code changed.

---

## 1. PART A — THE CORRECTION

### 1a. Every document carrying the claim — found by searching, not from memory

I searched every committed `.md` under `research/` plus the containment module.
**Three sites carry it; a fourth was already correct.**

| # | location | exact wording | verdict |
|---|---|---|---|
| 1 | **`research/BUILD_PLAN.md:64`** | architecture diagram — *"unbounded autonomy, no per-action gates, **everything reversible**"* | **WRONG — corrected** |
| 2 | **`research/BUILD_PLAN.md:261`** | *"Git is append-only by construction, **the interior is fully reversible**, and there is exactly one gated egress… The architecture fits it almost without adaptation."* | **TRUE OF GIT, FALSE OF GYZA — corrected as a conflation** |
| 3 | **`research/router/PREREGISTRATION_R11.md:18`** | *"**reversibility check** — if the action is reversible, run it unverified"* | **NOT EDITED — it is a preregistration** |
| 4 | `gyza/containment/staging.py:1-27` | *"the interior can be ungated because nothing in it is **irreversible** (C9)"* | **ALREADY CORRECT** — this is the *uncommitted* framing in other words |

**Site 4 is worth stating plainly: the code header never drifted.** It says
nothing in the interior is *irreversible*, describes abandonment accurately
(*"the abandoned events REMAIN IN THE LOG and the fold skips them"*), and never
claims an undo. **The documentation drifted away from a correct implementation
comment**, which is the opposite of the usual direction.

**Site 3 is deliberately untouched.** A preregistration records what was
believed *before* data; editing one destroys its function. The correction of
record is here and in the corrected findings.

### 1b. The corrections applied

Labelled blocks preserving prior text, per the census precedent. Each states
**what was claimed / what was measured / the corrected mechanism**, and each
carries the two new consequences (A4):

> **ABANDONMENT IS COARSE** — you discard everything staged since the last
> promotion, not one action. **PAST THE GATE THERE IS NO RECOVERY AT ALL** —
> promotion moves the watermark and prior events are permanently beyond
> `rollback()`.

**I also corrected my own committed finding.** `FINDINGS_REVERSIBILITY_AND_AUDIT.md`
said *"the operationally meaningful reversible count is 4"*. Under the criterion
this program already fixed — *"here is the undo operation"*, not *"could be
undone in principle"* — **the count is 0**:

| reading | count |
|---|---|
| declared `REVERSIBLE_INTERIOR` | 7 / 19 |
| within reach of **coarse batch** abandonment | 4 / 19 |
| **action types with a PER-ACTION undo** | **0 / 19** |

**DEFINITIONAL, not a new measurement:** it follows from `rollback()`'s
signature (`staging.py:148`) — it takes a `reason` string and **no action
identifier**. My prior count answered a weaker question.

**One number in the task does not match the tree:** it says *"zero of thirteen
action types"*. **The vocabulary is 19**, verified by executing
`ReversibilityTable().vocabulary`. **The zero is right; the denominator is not.**

### 1c. A3 — THE RETROACTIVE CHECK: **CLEAN, and one document had it right already**

Checked for any committed number depending on the interior being *undoable*:

| artifact | depends? | why not |
|---|---|---|
| **`FINDINGS_SR5.md`** | **NO — and notably so** | *"refusal modelled as **whole-batch rollback**"* (`:96`, and `PREREGISTRATION_SR5.md:77`). **SR-5 already used the corrected coarse mechanism.** It never assumed selective undo |
| `FINDINGS_R9.md` | NO | its reversible/irreversible split is over **its own task suite**, not Gyza's action vocabulary. The 25/40 = 0.625 is a property of that environment |
| `FINDINGS_R10.md` | NO | graded reversibility measured on R10's own model of θ, not on this implementation |
| `FINDINGS_R11.md` | NO | ROUTER-DEAD is about difficulty routing. Its remark that reversibility is a *"structural predicate over state"* survives — the **predicate** is structural; only the *undo* reading was wrong |
| `CARRIER_COVERAGE.md`, audit economics | NO | no reversibility term |

> **NOTHING NEEDED CORRECTING. The blast radius is bounded to prose.**
> **DEFINITIONAL: 0 figures moved** — no arithmetic anywhere consumed the
> assumption. **MEASURED: 0 re-derivations required.**

**Diagnosing the exact zero:** it is **not** suspicious here, and the reason is
structural — every research route built **its own environment** rather than
measuring Gyza's implementation, so none of them could inherit an
implementation-level error. **The counter-metric that keeps this honest:** the
same isolation means those routes' reversibility numbers say nothing about Gyza
either. The blast radius is small *because the coupling was always weak*.

---

## 2. PART B — THE FRONTIER

> ## ⚠ EVERY PARAMETER BELOW IS A **TEST VALUE** SUPPLIED FOR A BUILD-AND-TEST
> ## INSTANTIATION. NOT DERIVED, NOT MEASURED, NOT FOR DEPLOYMENT.
> A frontier computed on chosen inputs describes **the choice**, not the system.

### 2a. B3 — THE MEASURED CONTRAST AT g/w = 10, checked before asserting

| regime | LR = q/f | vs g/w = 10 | n | source |
|---|---|---|---|---|
| **in-competence** | **19.95** | **CLEARS** (2.0×) | 433 | `FINDINGS_R6.md:48` |
| **out-of-competence** | **1.25** | **FAILS** (0.125×) | 36 | `FINDINGS_R6.md:49` |
| out, **calibrated** | **0.25** | **FAILS** (0.025×) | 36 | `MODEL.md:50` |

> ### THE PATTERN HOLDS. **This is the competence bound reappearing in ECONOMIC form.**
>
> The same boundary, reached from a different direction: inside competence a lie
> may be worth **20× honest profit** and a bonded mechanism still exists; outside
> it, **no bonded mechanism exists at any bond** — because `B` cancels, and the
> failure is in the likelihood ratio, not the budget.

**A correction to the restatement I was given:** the calibrated model does **not**
use the raw out-of-competence TPR. `MODEL.md:50` bounds detection by the
actionable edge `J_out = 0.111`, giving **LR = 0.25, not 1.25** — a **5×**
difference, and it is the difference between "on the edge" and "below 1".

### 2b. B4 — REQUIRED AUDIT RATE, measured and assumed cells kept distinct

`p ≥ (g/w)/(q·(B/w))`, participation cap `p ≤ 1/(f·(B/w))`, at **B = 100w**:

| regime | q source | g/w=5 | g/w=10 | g/w=20 | cap |
|---|---|---|---|---|---|
| **in-competence** | **M** | 0.0611 ✅ | **0.1222 ✅** | 0.2445 ❌ | 0.2439 |
| **out-of-competence** | **M** | 0.4464 ❌ | 0.8929 ❌ | 1.7857 ❌ *(p>1)* | 0.0225 |
| **EGRESS** *(assumed q=0.50)* | **A** | 0.1000 ✅ | 0.2000 ❌ | 0.4000 ❌ | 0.1000 |
| **EGRESS** *(assumed q=0.20)* | **A** | 0.2500 ❌ | 0.5000 ❌ | 1.0000 ❌ | 0.1000 |

**M = q MEASURED** (on a cross-model checker over a MATH/reasoning family — a
**different population**; transfer is a **JUDGEMENT**).
**A = q ASSUMED. NOBODY HAS MEASURED q FOR THE EIGHT EGRESS TYPES.** Both egress
rows are illustrative arithmetic over invented detection rates and **license
nothing**.

**B is the designer's lever**, `p ∝ 1/B`, at g/w = 10:

| regime | B=10w | B=100w | B=1000w |
|---|---|---|---|
| in-competence | 1.2225 *(p>1)* | **0.1222** | 0.0122 |
| out-of-competence | 8.9286 | 0.8929 | 0.0893 |

**Raising B lowers the required rate — but it never rescues out-of-competence**,
because the *participation cap* falls with B too. At B=1000w the required rate
is 0.0893 and the cap is 0.00225. **The gap is the likelihood ratio, and no bond
closes it.**

### 2c. B5 — THE HUMAN-GATE BOUNDARY

**First, an overclaim I had to back out of.** The conditional escape floor at
p = 1 is `(1 − q)` = **0.182** in-competence. That is **not** ε. ε is an
**absolute** rate; `(1 − q)` is **conditional on a lie being attempted**.
Converting requires **e₀, the unaudited baseline consequential-error rate —
another unset parameter.**

R6 measured ε **plateaus at 0.219·e₀** past r ≈ 0.05, and that *"the floor is set
by the competence bound, not the budget."* So each tier implies a **maximum e₀**:

| tier (TEST VALUE) | ε | needs e₀ ≤ | verdict |
|---|---|---|---|
| reversible-by-a-third-party | 1e-2 | **4.57e-2** | **plausible** — a system erring < 4.6% of the time unaudited can reach it |
| irreversible-but-recoverable | 1e-4 | 4.57e-4 | **HUMAN GATE** |
| **irreversible-and-consequential** | **1e-6** | **4.57e-6** | **HUMAN GATE** |

> ### THE ANSWER TO B5: **no audit rate reaches 1e-6, and the reason is not budget.**
>
> To reach ε = 1e-6 by auditing, the **unaudited** system would already have to
> err consequentially less than **4.6 in a million** — at which point the audit
> is buying nothing. **The tier is self-defeating as an audit target.** For
> irreversible-and-consequential actions the right answer is **not a smaller
> epsilon: it is not-autonomous.** That is a design conclusion, not a failure of
> the arithmetic.
>
> **Only the loosest tier (1e-2, third-party-reviewed) is an audit target at
> all** — which is the tier where a human is already in the loop downstream.

### 2d. The residue this governs

**9 action types (0.4737 of the vocabulary), 0 production call sites** —
unchanged by Part A's correction, because the by-call-site figures never
depended on the per-action reading. **The audit economics still govern a slice
of running code that is empty.**

---

## 3. WHAT THIS DOES NOT ESTABLISH

1. **The bound is on the RATE of undetected consequential error, never on an
   individual claim.** No claim is guaranteed correct.
2. **It assumes a RATIONAL actor responding to expected cost.** It says nothing
   about an actor who is **wrong rather than strategic**. Prior work established
   adversarial defensibility catches **strategic deception but not sincere
   confusion**, and that distinction applies here unchanged — deterrence has no
   grip on someone who believes their false claim.
3. **q and f come from a different population** — a cross-model checker on a
   reasoning family, n=433 and n=36, the latter with a CI including zero.
   **Transfer to Gyza's vocabulary is a JUDGEMENT, not a measurement.**
4. **Every parameter in §2 is a TEST VALUE.** ε tiers, g/w, B — all chosen for a
   build-and-test instantiation, none derived or measured.
5. **q for all eight EGRESS types is ASSUMED.** Those are the actual residue, and
   the one number that would matter most for them has never been measured.
6. **e₀ is unset**, so §2c's tier verdicts are conditional on it.

## 4. Artifacts

- `research/BUILD_PLAN.md` — two labelled correction blocks, prior text intact.
- `research/reversibility/FINDINGS_REVERSIBILITY_AND_AUDIT.md` — correction of my
  own count, 4 → 0 per-action undos.
- `research/audit_economics/frontier_test_params.py` + `.json`.
- **No preregistration was edited. No production code changed.**
