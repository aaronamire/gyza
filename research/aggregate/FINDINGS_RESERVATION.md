# Findings — per-principal reservation: it fixes its own counterexample and is not a repair

Preregistered at **`09996bf`** (blob `270125b`), the **only file at that commit**,
committed **before any environment code existed**. **Zero credits**; deterministic,
`SEED = 1`, 180 cells, no model call.

**The committed originals are untouched**, verified by sha256:

```
e0b4f166…  env_aggregate.py       a1b59080…  run_ag3.py
d876be28…  guards_aggregate.py    32e4a43a…  test_aggregate.py
```

`guards_reservation.py` **imports** them rather than copying — a copied
environment is a second frame that can drift from the one AG-3 measured.

---

## 1. B1 — THE MINIMUM BAR: **PASSED**

AG-3's exact fixture, copied literally from `test_aggregate.py:168-172`:

| guard | admitted | concentration | |
|---|---|---|---|
| **GLOBAL_READ** (AG-3's) | **4/4** | **0.6250** | **VIOLATES** κ=0.60 |
| **RESERVATION** | **2/4** | **0.5000** | within κ |

**MEASURED.** Reservation refuses the second admission by each actor, because the
budget it decremented on the first is visible when deciding the second.

**With the control that gives it meaning:**
`test_B1_control_the_unreserved_guard_STILL_fails_the_same_case` requires
GLOBAL_READ to still reach 0.625 on the identical actions — so B1 passes because
reservation caught it, **not** because the fixture stopped exhibiting the effect.

**B2 — mechanism, not accident.** The reversed ordering also holds
(`test_B2_holds_under_reversed_action_order`). The budget decrements on every
admission, so order cannot matter. **7/7 tests pass.**

**And I said this in advance:** the preregistration recorded that the
counterexample is **two admissions by one actor**, i.e. *within-principal*
accumulation, and therefore *"a favourable test for the repair."* **B1 passing is
the predicted outcome, not a discovery.**

---

## 2. THE COUNTER-METRIC, AND IT INVERTS THE HEADLINE

Summed over M ∈ {2,3}, N ∈ {1,2,4}, both modes:

| config | adversary | **v_inst** | blocked | **throughput** |
|---|---|---|---|---|
| PARTITIONED_READ | A2-ratchet | 0 | 740 | 0.119 |
| PARTITIONED_READ | **A3-cross** | **0** | 840 | **0.000** |
| PARTITIONED_READ | **A4-pool** | **0** | 840 | **0.000** |
| PARTITIONED_READ | mixed | **9** | 326 | 0.606 |
| **RESERVATION** | A2-ratchet | 0 | 752 | 0.105 |
| **RESERVATION** | **A3-cross** | **0** | **151** | **0.706** |
| **RESERVATION** | **A4-pool** | **0** | **0** | **1.000** |
| **RESERVATION** | mixed | **13** | 246 | 0.707 |

> ### **PARTITIONED_READ's zero violations on A3-cross and A4-pool are bought at throughput 0.000. It admits NOTHING — 840 blocked, 0 admitted.**
>
> **That is exactly the degenerate guard C1 names**, and it is why *"reservation
> has 13 violations, PARTITIONED_READ has 9"* is not a containment comparison.
> On the two adversaries where PARTITIONED_READ scores perfectly, **it is not
> guarding, it is refusing to operate.**

**Diagnosing the exact 0.000: DEFINITIONAL, not containment.** A guard that
admits no action cannot admit a violating one. Reservation reaches **0
violations on those same adversaries at throughput 0.706 and 1.000** — the same
containment at 840 fewer blocks.

---

## 3. THE REAL RESULT: RESERVATION TRADES ONE STALENESS FOR ANOTHER

**Reservation is NOT a strict improvement**, and the cell that shows it is the
one where no race exists at all:

| adversary | M | N | mode | **v_inst** | max conc |
|---|---|---|---|---|---|
| mixed | 2 | **1** | **serialized** | **6** | 0.6667 |
| mixed | 2 | 1 | concurrent | 6 | 0.6667 |
| mixed | 2 | 4 | concurrent | 1 | 0.6316 |

> **`N=1, serialized` has no concurrency and no within-principal race. There is
> nothing there for reservation to fix — and PARTITIONED_READ scores 0 on the
> same cell.** So the violations are not the race; they are reservation's own
> design.

**The trajectory shows it accumulating across rounds** (RESERVATION vs
PARTITIONED_READ, same cell):

```
RESERVATION       0.50 0.50 0.50 0.50 0.60 0.55 0.6111 → violates from round 6
PARTITIONED_READ  0.50 0.50 0.50 0.50 0.55 0.50 0.5556 → never violates
```

### The mechanism, located in the environment

`env_federation.py:383-391`:

> `principal_total` = *"Balances of accounts **CURRENTLY OWNED** by p, **plus p's
> pool claim**"* — reading the **current owner map**, never one pinned at s₀.

**So a principal's own total moves for three reasons**: its own actions; **another
principal draining the shared pool**; and **ownership transfer**. Reservation's
budget is computed **once, at round open**, from that total.

> ### **Reservation removes staleness about SELF-CAUSED change and INTRODUCES staleness about OTHER-CAUSED change to its own quantity.**
>
> `PartitionedReadAgg` re-reads `mine` on every admission, so pool drift and
> ownership transfer are seen immediately. Reservation's round-open origin does
> not see them, and by the time the round ends the principal is below `L` without
> ever having been refused.

**That is AG-3's own result recurring one level in**: *"a stale read is exactly
as unsound as an unobserved write."* Reservation replaces a stale **snapshot**
with a stale **origin**, and an origin is a snapshot of one number.

---

## 4. D1/D2 — THE CROSS-PRINCIPAL VERDICT, LABELLED

**It does not compose, and that is DERIVABLE, not new.**
`THEORY_AG3.md:116-118`, quoted in the preregistration before any run:

> *"`concentration`: two-sided ⇒ **no exact local test exists**. The proviso is
> not merely unmet by my implementation; it is **unsatisfiable for the exact
> quantity**."*

Reservation is local by construction (§A4 of the preregistration enumerated what
it cannot see **before** results: any other principal's holdings, any other
principal's admissions, the federation total, and therefore the ratio itself).
**So its cross-principal failure follows from the theorem and is labelled
DERIVABLE.**

**One honest correction to my own D1 test.** The configuration I preregistered —
one action per principal — **does not exhibit a violation at all** (0.5000,
within κ). The static box absorbs a single round of within-budget shedding by
construction. **So that test measures nothing**, and it is reported as such
rather than as evidence. The cross-principal effect appears instead through the
**pool coupling** in §3, which I did not anticipate.

**D3 does not fire** — reservation did not compose, so there is no false
composition to diagnose.

---

## 5. THE DECISION

| rule | condition | met? |
|---|---|---|
| REPAIRS-WITHIN | `v_inst(N=2)` and `v_inst(N=4)` equal `v_inst(N=1)` in every cell, throughput ≥ 0.30 | **NO** — mixed M=2 gives N=1→**6**, N=2→0, N=4→1 |
| REPAIRS-BUT-COSTLY | violations fall to baseline but throughput < 0.30 | NO — throughput is *better*, not worse |
| **PARTIAL** | violations fall but not to the N=1 baseline | **YES** |
| DEAD | violations do not fall, or only where throughput collapses | NO |

> # **RESERVATION-PARTIAL** — and the modal prediction (55%) was right.

**Violations are NOT monotone in N**, which inverts AG-3's PARTITIONED_READ
pattern (0, 2, 6). Reservation is **worst at N=1**. That non-monotonicity is the
tell that its failures are not the within-principal race.

**Predictions scored:**

| prediction | predicted | actual | |
|---|---|---|---|
| B1 prevents the counterexample | YES ~85% | **YES** | ✅ |
| B2 survives reordering | YES ~75% | **YES** | ✅ |
| D1 composes across principals | NO ~95% | **NO** | ✅ |
| v_inst at M=2, N=4 | 0 (= N=1 baseline) | **1**, and N=1 is **6** | ❌ **missed, and in the informative direction** |
| throughput_effective | 0.30–0.50 | **0.105 – 1.000**, mixed **0.707** | ❌ **missed high** |
| blocked vs 1361 | higher, 1400–1900 | **1151 total** | ❌ **missed — it blocks LESS** |
| outcome | PARTIAL 55% | **PARTIAL** | ✅ |

**The three misses share one cause and it is the finding:** I predicted
reservation would be *more conservative* than the box. It is **less** — it
blocks less, admits more, and violates more. **I had the sign wrong on what a
stateful local budget does**, because I modelled it as adding a constraint when
it actually **replaces a per-action re-read with a once-per-round one.**

---

## 6. What this closes, and what it does not

**AG-3's one named repair has now been tested.** It **fixes the counterexample it
was proposed for** and **is not a general repair**: it introduces a new staleness
of the same species it removes.

> **AG-3's impossibility stands. The last named candidate mechanism has been
> tested and is partial.** That is stronger than *"none found yet"* and weaker
> than *"none exists"* — and per the preregistration's honesty condition, **no
> second repair is proposed here.**

**What a repair would have to do, stated for whoever tries next:** bound a
quantity whose own value moves for reasons outside the principal's control.
Reservation assumed self-caused change was the only kind. **In an environment
with a shared pool and transferable ownership it is not**, and any local budget
inherits that.

## 7. Honest limits

1. **One environment, one quantity family, one κ.** Concentration and cross-drain
   under AG-3's federation arena. It licenses claims about that.
2. **The design was fixed before the code and not tuned after.** §3's defect —
   bounding only the shedding side — was preregistered as a deliberate choice
   with its reason. **It is reported as a finding about the design, not
   repaired**, exactly as §7 of the preregistration required.
3. **My D1 test configuration measures nothing** (§4) and is reported rather than
   quietly replaced.
4. **`throughput` here is nominal admitted/proposals.** C3 asked for
   admitted-and-not-rolled-back; **this environment has no rollback**, so the two
   coincide. Labelled DEFINITIONAL rather than claimed as the stronger metric.
5. **The mixed adversary drives every violation.** Four of five adversaries give
   `v_inst = 0` for reservation. A result resting on one adversary is one
   adversary's imagination, and this one rests on `mixed`.
