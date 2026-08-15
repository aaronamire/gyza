# Escrow — findings

**Preregistration:** `PREREGISTRATION.md`, committed `5cdb324` as the only file
in this directory, BLAKE3
`bd02fdb02fe29ae5b4a2450e536379304748e2df44b83a309eef9d0c43003841`. Re-verified
unchanged after the runs. **Zero credits**; deterministic, no model call.

**Verdict: `ESCROW-CONVERTS-LOSS-TO-FORGONE-GAIN`, and separately
`RESERVATION-DEAD-ABOVE-M=3`.**

---

## 1. The two results in one paragraph each

**E2.** Escrow drives `unpaid_delivered_work` from **80.0 to exactly 0.0** while
drawdown stays at the bound in both arms. But **both arms settle exactly 100.0
credits**, and the 80 credits do not disappear — they move from *"work performed,
payment refused"* to *"work never commissioned."* Escrow does not extinguish the
transferred harm; it **converts a realized loss into a forgone gain**. Whether
that counts as extinction depends on a measure choice nobody has made yet (§4).

**E1.** RESERVATION's `PARTIAL` verdict does **not** survive past M = 3. At M = 2
reservation is perfect (0.000 against naive's 1.000); from **M = 4 it is
indistinguishable from no guard at all** (0.975 vs 0.975), and stays that way to
M = 512. `PARTITIONED_READ` strictly dominates it at every M ≥ 4 and *improves*
with scale. The mechanism is exactly the one `FINDINGS_RESERVATION` §3 named, and
M ≤ 3 is the precise regime in which it cannot appear.

---

## 2. E1 — RESERVATION at M ≫ 3

### 2.1 Three passes, two of them nulls, and why both are recorded

| pass | arena | reserved rate | why it was not the answer |
|---|---|---|---|
| 1 | `research/arena/arena.py`, M→512 | **0.0000 at every M** | **DEFINITIONAL.** No other-caused change exists, so the round-open origin is never stale, the budget is exact, and the box theorem does the rest. |
| 2 | `coupled_arena.py`, drain ungated | all three arms **identical** | The pool drain bypassed admission. A guard governing one end of a two-sided box is AG-3's inert guard restated. |
| 3 | `coupled_arena.py`, drain gated, shedders able to divest | **the result below** | — |

Pass 1 is the important null: **the arena that reaches M = 512 is not the arena
that produced the verdict.** `env_federation.principal_total` moves for three
reasons — own action, others draining the shared pool, ownership transfer — and
`arena.py` has only the first.

### 2.2 The measured result

40 rounds × 20 seeds per cell, κ = 0.6. Rate = fraction of rounds with
`concentration > κ`.

**n = 1 agent per principal**

| M | naive | **reserved** | partitioned |
|---|---|---|---|
| 2 | 0.000 | **0.000** | 0.000 |
| 4 | 0.975 | **0.975** | 0.925 |
| 8 | 0.975 | **0.975** | **0.000** |
| 64 | 0.925 | **0.925** | **0.000** |
| 512 | 0.875 | **0.875** | **0.000** |

**n = 4 agents per principal**

| M | naive | **reserved** | partitioned |
|---|---|---|---|
| 2 | 1.000 | **0.000** | 0.000 |
| 4 | 1.000 | **0.975** | 0.850 |
| 8 | 1.000 | **0.975** | 0.825 |
| 64 | 1.000 | **0.950** | 0.525 |
| 512 | 0.975 | **0.950** | 0.000 |

### 2.3 The mechanism, and why M ≤ 3 is exactly the blind spot

Reservation pins its origin at round open. Within a round, a principal's total
also moves because **other** principals withdraw their pool claims, shrinking the
pool and therefore everyone's claim. That is other-caused change, and the pinned
origin cannot see it.

> **At M = 2 there is exactly ONE other principal, so no other-caused change
> exists inside a round and reservation is exact. The mechanism needs ≥ 2 other
> actors, which first occurs at M = 4.**

`RESERVATION-PARTIAL` was measured at M ≤ 3. That is the largest scale at which
reservation's own failure mode is nearly unreachable. The verdict was not wrong;
it was measured in the one regime that flatters the guard.

### 2.4 Two honest deflations of the numbers above

1. **The violation rate and the floor-breach rate coincide in every arm**
   (0.975/0.975, 0.925/0.925). They are not independent evidence — the aggregate
   bound is breached exactly when the box is, which is the box theorem's
   contrapositive. One measurement, reported twice, would have been the
   plot-a-curve-through-two-quantities defect (artifact #17).
2. **This is a transcription of the coupling, not `env_federation` itself.** The
   committed environment caps at M = 3, which is the thing under test, so it
   cannot be the instrument. The claim is therefore about the *mechanism* at
   scale, not a re-measurement of the committed cells.

### 2.5 The decision rule failed its own feasibility check

**E1-HOLDS** was *"reserved rate at M ∈ {8,64,512} within 2× of its M=2 value"*,
with a preregistered ceiling note reading *"measured non-zero at small M."*

**The M = 2 value is exactly 0.000**, so the ratio is undefined and the rule is
unscorable. This is a **fourth instance** of the defect standing rule #4 exists to
prevent (after R10's θ\*, R10's TUNABLE clause, R11's 0.40 economy bar). I
checked the ceiling of the *quantity* and not of the *baseline the rule divides
by*.

The finding does not depend on the broken rule: 0.000 → 0.975 is a refutation of
"roughly flat" under any reading.

### 2.6 A property of `env_federation`'s own arithmetic, found by a failing test

`pool_claim` reads `s.contrib[p]`, and **no withdrawal ever reduces `contrib`.**
So a principal withdrawing X from the pool loses only **X/m** of its own claim
while every other principal loses X/m as well:

> **Withdrawing from the pool is net-POSITIVE for the withdrawer by X·(1 − 1/m).**
> `env_federation`'s docstring calls it *"NET-NEUTRAL in its own frame"*, which is
> true only at m = 1.

Two consequences. It is why draining is a concentration attack from both ends at
once (the drainer rises, everyone else falls), and it means **a principal cannot
reach zero total in one move** — at M = 8 a full divestment lands at 5.25 against
an L of 1.90. The floor is breached only over a trajectory, as the pool is worn
down. I asserted the single-step version in a test and it failed; the assertion
was wrong, not the transcription.

Whether the committed environment intends this is a question for that
environment, not this route. It is transcribed faithfully either way.

---

## 3. E2 — escrow on the real settlement path

Real `LedgerSettlementService`, real protocol, real `SettlementGuard`, scored by
`harm_redteam/damage.py`, which cannot see any guard. Bound 100.0 credits, demand
9 × 20.0 = 180.0.

| measure | control | escrow |
|---|---|---|
| `unpaid_delivered_work` | **80.0** | **0.0** |
| `drawdown` | 100.0 | 100.0 |
| `settled_credits` | 100.0 | 100.0 |
| `forgone_credits` | 0.0 | **80.0** |
| `lockout_breadth` | 0.0 | 0.0 |

**E2-CONTROL** PASS · **E2-EXTINGUISHES** PASS · **E2-PRICE** reported below.

### 3.1 The zero is the construction, as preregistered

P-E2a predicted exactly 0 **and flagged it DEFINITIONAL in advance**. It is: the
escrow gate refuses to commission precisely when payment would later be refused,
so the state "delivered and unpaid" is not constructible. Reporting this as a
discovery would be reporting the definition.

**What is not definitional is the identity of the two numbers.** The control
leaves **80.0 credits unpaid**; escrow leaves **80.0 credits uncommissioned**.
Same magnitude, different bearer:

> **Escrow does not remove the 80 credits. It moves them from a REALIZED LOSS
> borne by an earner who did the work to a FORGONE GAIN borne by nobody.**

### 3.2 So does escrow convert TRANSFERS into EXTINGUISHES? It depends on the measure — and nobody has chosen it

- Under a **loss** measure (R-B1's `unpaid_delivered_work`): **extinguished**,
  exactly 0.
- Under a **surplus/welfare** measure: **still transferred.** The earner's
  expected surplus on 80 credits of work is gone either way; only the expended
  effort differs.

R-B1's taxonomy classifies quantities, not welfare, so on its own terms this is
an EXTINGUISHES conversion. That is the narrower and defensible claim, and the
broader one — *"escrow makes the counterparty whole"* — is **false**. This is the
`counterparty loss` measurement listed as still-owed work; it now has a first
number, and the number says the two framings disagree.

### 3.3 E2-PRICE: the price is linear in the concurrency it buys

The serial arm measured 20% idle and would have "missed" P-E2b's 25% bar — but
20% is a property of the **rig** (one item in flight), not of escrow. Varying the
batch:

| work in flight | peak idle escrow | % of bound | unpaid |
|---|---|---|---|
| 1 item | 20.0 | 20.0% | 0.0 |
| 2 items | 40.0 | 40.0% | 0.0 |
| 5 items | 100.0 | **100.0%** | 0.0 |

`idle_escrow = batch × item_cost`, exactly.

> **To have the whole bound's worth of work in flight you must idle the whole
> bound.** Escrow's price is not a percentage to be tuned; it is the concurrency
> you asked for, paid up front.

**P-E2b (≥ 25%) is scored MISSED-AS-STATED and REPLACED**: as a single number it
is meaningless, because the quantity is a free parameter of the deployment. The
prediction was malformed, not merely wrong.

### 3.4 A measure defect found in the red team's own instrument

`lockout_breadth` (D2) reads **0.0 in the control while D1 is 80.0.** D2 is
`{earners who delivered} − {earners who were paid}`, so an earner who is
**partially** paid is not counted as locked out. In the exact case D2 was built to
illuminate — one earner, some entries settled, 80 credits not — it reports
nothing.

D2 is sound only for earners paid *nothing at all*. Recorded here; the committed
red-team findings stand unedited, per standing practice.

---

## 4. What E1 and E2 say together — the boundary of escrow

E1: escrow's pinned origin is unsound once **≥ 2 other actors** can move the
protected quantity inside the window.
E2: escrow is exact for a payer's own credit balance, which **no other principal
can move**.

> **Escrow is sound exactly when the escrowed quantity has a SINGLE WRITER.**

That is not a new theorem — it is O'Neil's own stated scope (*commutative,
single-sided*) and it is what I-confluence predicts. What is new here is that the
boundary was crossed **inside this codebase without being noticed**: per-principal
credits are single-writer and escrow works; cross-principal concentration is
many-writer and escrow is worth nothing at M ≥ 4. Both were called "reservation."

---

## 5. Predictions, scored

| | prediction | outcome |
|---|---|---|
| **P-E1** | reservation's rate roughly flat in M | **REFUTED at the M=2→4 step** (0.000 → 0.975); flat only for M ≥ 4 |
| **P-E2a** | `unpaid_delivered_work` → exactly 0 | **CONFIRMED, and definitional as flagged** |
| **P-E2b** | `idle_escrow` ≥ 25% | **MALFORMED.** The quantity is a free parameter (20% / 40% / 100% for 1 / 2 / 5 items in flight) |
| **P-E3** | escrow does not repair the cross-principal ratio bound | **CONFIRMED**, and now measured rather than derived: reserved ≈ naive at every M ≥ 4 |

---

## 6. Apparatus defects found in my own instruments

Three, all in E1's arena, and **all failing in the reassuring direction** — the
same pattern as the four in `research/arena/FINDINGS.md` §4.

1. **Rotating target** (defect #5 of the program). `run` reshuffled every round,
   so whoever gained in round *r* was shed around in round *r+1*. Concentration
   could not accumulate and **all three arms scored 0.0000 at every M ≥ 8,
   naive included.** AG-3's own trajectory violates only from round 6 — the
   mechanism *is* accumulation. This is the symmetric-shedding defect in
   temporal form: an adversary that undoes its own work.
2. **Ungated drain.** The disciplines governed shedding only, so the pool drain
   ran unadmitted and every arm scored identically. A guard governing one end of
   a two-sided box is expensive and inert.
3. **Shedders that could not divest** (defect #6). Reduction applied to
   `holdings` only, so every shedder was floored at its pool claim (6.0 against
   an L of 4.44 at M = 4) and **the box looked sound at every M ≥ 4 for reasons
   entirely internal to the instrument.** Same species as the arena's first
   defect: an adversary too weak to perform the attack.

And two in E2, both of the **AN ERROR IS NOT A VALUE** species, in the same
experiment:

4. `E2_drawdown` was registered as a harm class with **no invariant**, so the
   engine's C4 error came back through the *same channel* as a bound breach and
   the guard refused all nine items. The control scored a perfect-looking 180.0.
5. `float(Credits)` raised inside the quantity function — `Credits` is integer
   micro-credits and deliberately not float-able. **The resulting table was
   byte-identical to the previous broken run.** Two different errors, one
   identical reassuring number: had I not read the stderr, neither would have
   been visible in the result.

---

## 7. What this does not establish

1. **Simulated principals.** No real agents, no real humans, no real market.
2. **E1 is a transcription of the coupling**, not `env_federation` itself
   (§2.4.2). The committed environment cannot express M > 3, which is the thing
   under test.
3. **Escrow is single-sided and commutative** by O'Neil's scope. It covers
   increment/decrement quantities and not arbitrary effects.
4. **Irreversibility is not linear.** You cannot escrow "content destroyed" the
   way you escrow credits, so the largest EXTINGUISHES class (H3) sits outside
   this route entirely.
5. **Nothing about correctness.** Consequence only; the competence bound is
   untouched.
6. **`E2_drawdown` is a research-local harm class.** H1 was retired 2026-08-15
   and `SettlementGuard` correctly refuses to construct against it. Nothing here
   re-enables H1, and `guard_bounds.json` was not touched.
