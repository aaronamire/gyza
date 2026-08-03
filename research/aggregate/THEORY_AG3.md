# AG-3 — the taxonomy, the propositions, and their numerical verification

Preregistration `PREREGISTRATION_AG3.md`, sha256
`6a8644436ed7f26db2672e5d777aee2234f3daff93728aab230768ceb8bbe6e1`, committed at
`a30ef4b` before any derivation. Results in `ag3_result.json` (240 cells,
deterministic, `SEED = 1`, **zero model calls**).

---

## 1. Two axes, and they are orthogonal

Let `s = (s_1,…,s_M)` be a joint state and `τ = (s^0,a^1,…,a^T,s^T)` a joint
trajectory.

- **AGGREGATE** (*spatial*): `h` is aggregate iff it is not a function of any
  one principal's projection — `∃ s,s'` with `s_p = s'_p` and `h(s) ≠ h(s')`.
- **CUMULATIVE** (*temporal*): `h(τ) = Σ_t g(s^{t-1},a^t)` and `h` is not a
  function of `s^T`.

|  | instantaneous | cumulative |
|---|---|---|
| **single-principal** | balance | total spend by *p* — **R10** |
| **aggregate** | **concentration** | cross-principal drain — **R13** |

`PATH-DEPENDENT-JOINT` (e.g. `max_t`) is neither: not a function of `s^T`, not a
sum.

## 2. P1 — the classification is a partition, but it DOES NOT CARVE THE SPACE

**Proved as a partition, trivially:** the criterion *(i) function of `s^T`?
(ii) else a sum of per-step increments?* is a decision tree, so the three classes
are disjoint and exhaustive.

**REFUTED as a predictor of composability, and this is the honest headline of
Part A.** The preregistration said the contentful claim is that the three cells
have *different guard-theoretic consequences*, and that I would say so if they
did not. They do not — because **INSTANTANEOUS-JOINT is not internally uniform.**

Consider two instantaneous-joint quantities:

- `total_holdings(s) = Σ_p x_p`, bounded below by `B`. Monotone **increasing**
  in every `x_p`. A static split (each principal must keep `x_p ≥ B/M`) is a
  sound local sufficient condition requiring **no cross-principal read**.
- `concentration(s) = max_p x_p / Σ_q x_q`, bounded above by `κ`. Monotone
  **increasing** in `x_p` and monotone **DECREASING** in every `x_q`, `q ≠ p`.

The second is the problem, and the reason is not that it is aggregate or that it
is instantaneous. It is that **its dependency on other principals runs in the
opposite direction from its dependency on self**, so a principal can push
another principal past the bound by an action wholly inside its own authority.

> **The property that predicts composability is not the temporal class. It is
> DIRECTIONAL LOCALITY: whether every principal's guard can bound the quantity's
> movement in the harmful direction using only what that principal controls.**

The taxonomy I preregistered is a real partition that answers the wrong
question. Recorded as such.

## 3. P2 — instantaneous-joint IS inductively checkable under serialization

**Proof.** Let `P(s) ≡ h(s) ≤ κ` and let the guard admit `a` at `s` only if
`h(apply(s,a)) ≤ κ`. Serialized execution gives `s^t = apply(s^{t-1}, a^t)` for
admitted `a^t`. Then `P(s^t)` holds directly by the admission test, for every
`t`, independently of `P(s^{t-1})`. ∎

The proof needs the guard to be able to *evaluate* `h(apply(s,a))`, i.e. to read
the joint state — but under serialization there is exactly one writer at a time,
so that read is current. **VERDICT: TRUE.**

**Numerical verification.** Predicted: 0 instantaneous violations, serialized,
for any guard that evaluates `h` on the true successor state.

| config, serialized | predicted | simulated |
|---|---|---|
| GLOBAL_READ | 0 | **0** |
| PARTITIONED_READ | 0 | **0** |

**The 0s are MEASURED, not definitional**, and the check that establishes it is
that *the same detector on the same cells reports 18 violations under F0*. A
detector with no power reports zero for free; this one does not.
Max concentration reached under GLOBAL_READ serialized is **exactly 0.6000 = κ**
— the invariant binding tight, which is what a correct inductive invariant looks
like.

## 4. P3 — REFUTED. And the proviso is unsatisfiable for ratio-type quantities

> *An inductive invariant over the joint state bounds aggregate harm without
> serialization, provided the invariant's evaluation partitions along the action
> axis.*

**Constructive counterexample (M = 3, κ = 0.60), verified in
`test_aggregate.py`.** At `s_0` every principal holds 20, `T = 60`,
`concentration = 1/3`. Four actions, each evaluated by its own guard against the
**same pre-round state**:

| action | concentration if applied ALONE | admitted? |
|---|---|---|
| B sends 10 from `B:a0` | 0.4000 | yes |
| B sends 4 from `B:a1` | 0.3571 | yes |
| C sends 10 from `C:a0` | 0.4000 | yes |
| C sends 4 from `C:a1` | 0.3571 | yes |

Applied jointly: `A = 20, B = 6, C = 6`, `T = 32`, **`concentration = 0.625 > κ`.**

**And principal A, whose share crossed the bound, took no action at all** — its
total is bit-identical before and after. No guard that reasons about *its own
principal's actions* can prevent this, because the violating movement was not
A's to make and was not B's or C's to see.

**Formalising the proviso.** "Evaluation partitions along the action axis" means
there is a decomposition `h(s) = F(g_1(s_1),…,g_M(s_M))` together with a local
test `T_p` on `g_p` such that `(∀p. T_p)` implies `h ≤ κ`. Such a `T_p` exists
iff `F` is monotone in each argument **in the same direction**, so that each
principal can conservatively bound its own contribution's harmful movement.

- `total_holdings`: same-direction ⇒ the proviso is satisfiable ⇒ composes.
- `concentration`: two-sided ⇒ **no exact local test exists**. The proviso is
  not merely unmet by my implementation; it is unsatisfiable for the exact
  bound.

**VERDICT: P3 REFUTED for ratio-type instantaneous-joint quantities.** It
survives, vacuously, for same-direction ones — which is P1's point restated.

### 4a. The strictly stronger condition that IS local, and what it costs

A sufficient (not necessary) local condition does exist: the **static box**.
If every principal keeps `L ≤ x_p ≤ U` then

```
concentration ≤ U / (U + (M-1)L) ≤ κ     whenever  U(1-κ) ≤ κ(M-1)L
```

With `U = 20` (the endowment): `L = 13.333` at M=2, `L = 6.667` at M=3, both
verified sound in `test_the_static_box_is_actually_sound`. **No principal reads
any other's state.** The price is measured in §6: throughput ratio **0.511**
serialized, against 0.957 for GLOBAL_READ.

## 5. THE CRUX — does a global READ-SET serialize the way a global WRITE-SET does?

**Answer: YES, but not for the same reason, and the difference matters.**

- A global **write-set** serializes because concurrent writes *conflict*: two
  writers to one cell must be ordered.
- A global **read-set** has no such conflict — reads commute. What serializes is
  weaker and sharper:

> **An admission decision that is a function of the joint state must be
> linearized with respect to joint-state updates. Reads do not conflict;
> DECISIONS TAKEN FROM STALE READS ARE UNSOUND.**

Under R13's concurrent semantics every guard reads the same pre-round snapshot.
That snapshot is perfectly **consistent** — and still wrong, because between the
read and the effect, other admitted actions move the quantity. **Consistency is
not the property required; recency at decision time is.** A stale read is
exactly as unsound as an unobserved write.

**Numerically:** GLOBAL_READ holds at 0 violations serialized and leaks
**2** concurrent, with max concentration rising from exactly 0.6000 to **0.6250**.
Nothing changed but the recency of the read.

### 5a. The PARTITIONED-READ result, which was NOT predicted

The preregistration's B4 asked whether removing the cross-principal read would
lose composition. It did something worse and more informative: **PARTITIONED_READ
leaks MORE than GLOBAL_READ under concurrency — 9 violations against 2, with max
concentration 0.7368 against 0.6250** — despite enforcing a box proved sound.

**Diagnosis, and the signature is unambiguous.** Violations by N at M=2:

```
N=1: 0      N=2: 2      N=4: 6
```

Monotone in the number of agents **per principal**. The box is a sound predicate
over *states*, but the admission *test* is still evaluated against the pre-round
snapshot. With `N ≥ 2`, a principal's own agents each check "does my total stay
≥ L?" against the same stale value of its own total, and jointly push it below.

> **Removing the cross-principal read did not remove the staleness. It
> relocated it from BETWEEN principals to WITHIN one.** The global read-set was
> never the disease; stale-read admission was, and it survives every
> partitioning of the read-set.

This is why the crux question, as posed, has a slightly misleading shape: the
read-set's *extent* is not what serializes. Its *recency requirement* is.

**Untested implication, labelled as such:** the repair is per-principal
reservation — a guard that decrements a local budget as it admits within a round,
rather than re-reading a snapshot. That is a stateful guard, i.e. a serialization
point of width one principal rather than width M. It was **not** added as an arm,
because adding arms after seeing results is the tuning this program forbids.

## 6. P4 — path-dependence reduces by augmentation, and the reduction buys nothing

**First half (legal).** `peak(τ) = max_t h(s^t)` is a function of an augmented
state `(s, r)` with `r' = max(r, h(s'))`. So the augmented quantity is
instantaneous by construction. **TRUE.**

**Second half (worthless).** `r` is monotone non-decreasing and shared across
principals: bounding `peak ≤ κ` is *exactly* bounding `h ≤ κ` at every step,
since the register latches on first exceedance. The augmentation inherits every
difficulty of the underlying quantity and adds a shared cell. **TRUE.**

**Numerical verification.** Predicted: path violations occur iff instantaneous
ones do, and persist once triggered (a latch), so `v_path ≥ v_inst`.

| config / mode | v_inst | v_path | latch holds? |
|---|---|---|---|
| F0 serialized | 18 | 42 | yes |
| GLOBAL_READ serialized | 0 | 0 | yes |
| GLOBAL_READ concurrent | 2 | 3 | yes |
| PARTITIONED_READ concurrent | 9 | 11 | yes |

`v_path > 0` in exactly the cells where `v_inst > 0`, in all 240. The
path-dependent class contributes **no independent difficulty**.

## 7. P5 — R13's scope

R13's counterexample is **CUMULATIVE-JOINT**: its quantity is cross-principal
drain accumulated over a trajectory, and its mechanism is that *a stateless check
cannot accumulate*. **VERDICT: TRUE — R13 is scoped to that cell.**

But the scoping does not rescue the other cells, because **AG-3 finds a second,
independent obstruction**: instantaneous-joint quantities fail under concurrency
not from an inability to accumulate but from stale-read admission. Two different
mechanisms, two different cells, the same conclusion.

**The cumulative column here is a CONTROL and is NOT independent replication of
R13.** No guard in this route bounds cumulative drain; the column's non-zero
counts (63–125) are DEFINITIONAL for that reason, and the reduction from 123
(F0) to 73 (GLOBAL_READ) is an incidental side effect of a concentration guard
blocking some drains. It is reported for completeness and carries no weight.
