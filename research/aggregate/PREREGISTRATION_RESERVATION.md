# Preregistration — per-principal reservation

**Committed BEFORE any environment code exists.** Zero credits: simulation only,
no model call. The guard semantics, metrics, decision rule, feasibility ceiling
and point predictions below are fixed now and are not revised after data.

> **WHY THIS PREREGISTRATION IS STRICTER THAN USUAL.** The repair was named by
> AG-3 **after** AG-3's results were known, and `OPEN_PROBLEM.md:436-445` makes
> the route legitimate only if preregistered *"with AG-3's counts treated as a
> stated prior and the entire design — guard definition, metric, decision rule,
> feasibility ceiling — fixed and committed before any new measurement."*
> **I have read AG-3's findings, its theory, its counterexample test and its
> result table.** So everything they contain is a **stated prior below**, and
> nothing in this file may move afterwards.

---

## 1. AG-3's counts, as the stated prior

Verified against `research/aggregate/FINDINGS_AG3.md` and `test_aggregate.py`:

| config | mode | v_inst | max conc | throughput | blocked |
|---|---|---|---|---|---|
| GLOBAL_READ | serialized | **0** | 0.6000 | 0.957 | 530 |
| GLOBAL_READ | concurrent | **2** | 0.6250 | 0.920 | 239 |
| PARTITIONED_READ | serialized | **0** | 0.6000 | 0.511 | 1387 |
| PARTITIONED_READ | concurrent | **9** | 0.7368 | 0.414 | 1361 |

- **PARTITIONED_READ violations are monotone in agents-per-principal**: M=2,
  N=1 → **0**, N=2 → **2**, N=4 → **6**.
- LOCAL blocked **871** extra actions with a violation count equal to the
  unguarded baseline **in all 60 cells**.
- κ = 0.60 (`agg.KAPPA`), M ∈ {2,3}.

**The counterexample, read from the test rather than the prose:** M=3; actions
are `("B","X0")` and `("C","X1")` each doing `(a0, 10)` then `(a1, 4)` —
**four actions, but only TWO actors** (`B/0`, `C/0`), i.e. **two actions per
actor**. Each passes against `s0`; jointly concentration reaches **0.625**; **A
never acts** and its total is bit-identical.

> **That reading is load-bearing and I am fixing it now:** the counterexample is
> **within-principal accumulation** (one actor, two admissions), not
> cross-principal. That is precisely the race reservation targets — so B1 is a
> *favourable* test for the repair, and I say so in advance rather than
> claiming credit for it afterwards.

## 2. The guard, specified before it exists

**`ReservationAgg`** — a subclass of `AggGuard`, added in a **read-only copy** of
`guards_aggregate.py`. The committed originals are not modified.

```
state:   self._budget : float | None   # None == not yet opened this round
         self._origin : float          # own total at round open; IMMUTABLE

open_round(s):                          # called once per round, before any admit
    self._origin = principal_total(s0, s, self.p)
    L, U = box_bounds(len(ps), kappa)
    self._budget = self._origin - L      # how much this principal may still SHED

admits(s, a):
    if a.principal != self.p:      return True
    if not physically_valid(s, a): return False
    delta = self._origin_relative_change(s, a)   # own-total change this action
    shed  = max(0.0, -delta)                     # only shedding consumes budget
    if shed > self._budget + 1e-9: return False
    self._budget -= shed
    return True
```

**Denomination:** the budget is in the **same units as `principal_total`**, and
it measures **how much this principal may still SHED this round** before
crossing the box's lower bound `L`.

**Why shedding and not acquiring.** The box has two sides. `PartitionedReadAgg`
already checks `mine >= L` and `mine <= U` against the *stale* snapshot. AG-3's
counterexample raises A's concentration by **shrinking the denominator** — B and
C shed. So the side that the stale read leaks through, in the measured
counterexample, is the **lower** one. **The upper side is left to the existing
box check and is not reimplemented**; reservation adds statefulness to the
lower side only.

**Reset:** at `open_round`, once per round, from the round's opening state.

**Exhaustion:** refuse. The action is blocked and counted as blocked.

### A3 — the origin is immutable within a round, and that is a test not a claim

`self._origin` is written **only** in `open_round` and read everywhere else.
**Asserted by test, with a negative control**: a mutant guard that re-bases
`_origin` inside `admits` must be **detected** by the same test. Without the
control the assertion passes vacuously — the fifth instance of the moving-origin
species this program has recorded, and I am not adding a sixth.

### A4 — what the budget CAN and CANNOT see, stated before results

**CAN see:** its own principal's total at round open; its own admissions within
the round; the static box bounds `L, U`, which are a function of `M` and `κ`
only.

**CANNOT see:** any other principal's holdings, at any time; any other
principal's admissions; the federation total; **therefore the concentration
ratio itself.**

> **That enumeration IS the mechanism's limit.** A local budget cannot observe
> another principal shrinking, and concentration is a ratio over all principals.

## 3. Metrics

| metric | definition |
|---|---|
| **`v_inst`** | count of rounds whose end-state concentration exceeds κ. **The containment metric.** |
| **`max_conc`** | peak concentration over the trajectory |
| **`blocked`** | actions refused by a guard |
| **`throughput_nominal`** | admitted / offered |
| **`throughput_effective`** | admitted **and not rolled back** / offered |

**Every containment number is reported beside `blocked` and
`throughput_effective`.** C2's precedent is explicit: LOCAL bought 871 blocked
actions and zero violations caught. **A throughput cost is not evidence of
work.**

## 4. Feasibility ceiling — fixed BEFORE the thresholds

**Attainable range of `v_inst`, from AG-3's measured cells:**

- `v_inst = 0` **is attainable** — GLOBAL_READ *serialized* and
  PARTITIONED_READ *serialized* both reach it, as does PARTITIONED_READ
  concurrent at **M=2, N=1**.
- `v_inst = 0` is **NOT attainable for a local guard in general**, and this is
  **derivable, not conjectural**: `THEORY_AG3.md:116-118` states *"concentration:
  two-sided ⇒ **no exact local test exists**. The proviso is not merely unmet by
  my implementation; it is **unsatisfiable for the exact quantity**."*

> **So a decision rule demanding `v_inst = 0` universally would be demanding
> something the theory says is impossible — an unattainable threshold, the
> defect this program has recorded three times.** The rule below therefore
> targets the **within-principal** component only, which *is* attainable.

**The attainable target:** PARTITIONED_READ concurrent at M=2 gives
N=1 → 0, N=2 → 2, N=4 → 6. **The N=1 cell is the within-principal-race-free
baseline.** If reservation removes that race, N=2 and N=4 must fall to the N=1
value in the same cell.

## 5. Decision rule, fixed now

| outcome | condition |
|---|---|
| **RESERVATION-REPAIRS-WITHIN** | for every (M, config) cell, `v_inst(N=2)` and `v_inst(N=4)` equal `v_inst(N=1)`, **and** `throughput_effective` ≥ **0.30** (PARTITIONED_READ concurrent's 0.414 minus a 0.11 allowance) |
| **RESERVATION-REPAIRS-BUT-COSTLY** | violations fall to the N=1 baseline but `throughput_effective` < 0.30 |
| **RESERVATION-PARTIAL** | violations fall but not to the N=1 baseline |
| **RESERVATION-DEAD** | violations do not fall, or fall only where throughput collapses to ~0 |

**Cross-principal composition (D1) is scored separately and does NOT enter the
rule above**, because §4 establishes it is derivably unattainable. Reporting it
as a failure of *this* mechanism would be reporting a theorem as a measurement.

**Any cell driven by a single ordering, a single seed, or a throughput of ~0 →
INCONCLUSIVE for that cell.**

## 6. POINT PREDICTIONS, with a prior

**Mine, stated before any code exists:**

| prediction | value |
|---|---|
| **B1 — reservation prevents AG-3's counterexample** | **YES, ~85%.** The counterexample is two admissions by one actor; a stateful budget sees the first when deciding the second. **This is a favourable test and I have said so** (§1) |
| **B2 — it survives a reordered variant** | **YES, ~75%.** The mechanism is order-independent because the budget decrements on every admission |
| **D1 — reservation composes across principals** | **NO, ~95%.** **DERIVABLE** from `THEORY_AG3.md:116-118` |
| `v_inst` at M=2, N=4 | **0**, matching the N=1 baseline |
| `v_inst` at M=3 | **> 0** — M=3 is where the cross-principal counterexample lives |
| `throughput_effective` | **0.30 – 0.50**, i.e. near PARTITIONED_READ's 0.414 |
| blocked, vs PARTITIONED_READ's 1361 | **higher**, 1400 – 1900 |

> **Prior over outcomes: RESERVATION-PARTIAL 55% / REPAIRS-WITHIN 25% /
> REPAIRS-BUT-COSTLY 15% / DEAD 5%.**
>
> **PARTIAL is the modal prediction** because §4's derivation says the
> cross-principal component cannot be fixed locally, and M=3 cells will still
> carry it.

## 7. Honesty conditions

- **A NEGATIVE IS A SUCCESS.** If reservation fails, **the last named repair for
  concurrent coordination closes**, and AG-3's impossibility stands *with no
  candidate mechanism remaining* — strictly stronger than "none found yet".
  **No second repair will be proposed in the same session**, because that is how
  a route becomes a search for something that works.
- **NO TUNING AFTER RESULTS.** If the semantics in §2 need changing, that is a
  **FINDING about the design**, reported with every changed behaviour named.
- **DIAGNOSE ANY EXACT 0 OR 1**, including `v_inst = 0`, which under a guard
  that blocks heavily is the trivial outcome C1 warns about.
- **LABEL EVERY CELL DEFINITIONAL OR MEASURED.** A cell that follows by
  construction is illustration, not confirmation.
- **THE COMMITTED ENVIRONMENT IS NOT MODIFIED.** Copies only, and the
  originals' hashes are reported unchanged.
- **SCOPE.** This measures one repair, in one simulated environment, over
  concentration and cross-drain. It licenses claims about that. It does **not**
  license a claim about real multi-agent systems, whose aggregate harms this
  program has never observed.
