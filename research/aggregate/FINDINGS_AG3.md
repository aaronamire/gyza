# Findings — AG-3: does R13's impossibility apply to AGGREGATE harm?

Write-up per `PREREGISTRATION_AG3.md` (`a30ef4b`, sha256 `6a86444…`), committed
before any derivation or code that produces a result. 240 cells, deterministic,
`SEED = 1`, **zero model calls**, 13 gate tests green. Disclosures are in §7 and
are not buried.

---

## DECISION: **AGGREGATE-IS-HARDER**

> **Aggregate harm does not compose under concurrency, and the reason is NOT
> R13's.** R13's obstruction is that a stateless check cannot accumulate.
> AG-3's is that **an admission decision taken from a stale read of a quantity
> other principals can move is unsound — even when the quantity is
> instantaneous, even when the read is perfectly consistent, and even when the
> guard reads nothing but its own principal's state.**

**This was the outcome I said must not be softened, and it is reported at full
strength.** It was my own prediction against the prompt's 0.30 prior, and I
recorded the reason in the preregistration before deriving: concentration is a
ratio, so one principal's action raises another's share.

| decision clause | fires? |
|---|---|
| AGGREGATE-IS-CUMULATIVE — all three classes reduce to cumulative | **no** — instantaneous-joint holds perfectly under serialization (0 violations, bound tight at exactly κ) |
| AGGREGATE-SPLITS — instantaneous boundable without serialization, ≥0.50 throughput | **no** — GLOBAL_READ leaks 2 and PARTITIONED_READ leaks 9 under concurrency |
| **AGGREGATE-IS-HARDER** — instantaneous fails for a reason distinct from R13's | **YES** |

**Prior vs outcome:** the prompt's priors were SPLITS 0.50 / HARDER 0.30 /
CUMULATIVE 0.20. **HARDER fired.** My stated deviation from that prior was
correct, and for the stated reason.

---

## 1. The class taxonomy — and it does not carve the space

The three-way taxonomy was mine and was preregistered as a hypothesis. **It is a
valid partition and a bad predictor, and I said I would report that if so.**

| proposition | verdict |
|---|---|
| **P1** classification is a partition | **TRUE**, trivially (a decision tree) |
| **P1'** the three cells have different guard-theoretic consequences | **REFUTED** |
| **P2** instantaneous-joint is inductively checkable under serialization | **TRUE** (proof + 0 violations) |
| **P3** inductive invariant bounds aggregate harm without serialization | **REFUTED** for ratio-type; vacuous for same-direction |
| **P4** path-dependence reduces by augmentation, register serializes | **TRUE**, both halves |
| **P5** R13 is scoped to CUMULATIVE-JOINT | **TRUE** |

**Why P1' fails: INSTANTANEOUS-JOINT is not internally uniform.**
`total_holdings = Σ_p x_p` is monotone increasing in every principal's holding,
so a static split (`x_p ≥ B/M`) is a sound purely-local test.
`concentration = max_p x_p / Σ_q x_q` is increasing in `x_p` and **decreasing in
every other `x_q`**. Two quantities, same class, opposite composability.

> **The predictive property is not the temporal class. It is DIRECTIONAL
> LOCALITY — whether each guard can bound the quantity's movement in the harmful
> direction using only what its own principal controls.** A taxonomy that does
> not carve the space is worse than none, so this one is retired in favour of
> that criterion.

**The counterexample, which is the core of the result** (M=3, κ=0.60, verified
in `test_aggregate.py`): four actions, each admitted by its own guard against the
same pre-round state at concentration ≤ 0.40, jointly reaching **0.625**. The
principal whose share crossed the bound — A — **took no action at all**, and its
total is bit-identical before and after.

---

## 2. The read-set result — the crux, answered

**Does a global READ-SET serialize the way a global WRITE-SET does? Yes, but not
for the same reason.**

Write-sets serialize because writes *conflict*. Reads commute and never
conflict. What serializes is sharper:

> **An admission decision that is a function of the joint state must be
> linearized against joint-state updates. A stale read is exactly as unsound as
> an unobserved write.**

Under R13's concurrent semantics every guard reads the same pre-round snapshot —
**perfectly consistent, and still wrong**, because the effects of the other
admitted actions land after the read. Consistency is not the property required;
recency at decision time is.

### The result that was not predicted

| config | mode | v_inst | max concentration | throughput ratio | blocked |
|---|---|---|---|---|---|
| GLOBAL_READ | serialized | **0** | 0.6000 (= κ exactly) | 0.957 | 530 |
| GLOBAL_READ | concurrent | **2** | 0.6250 | 0.920 | 239 |
| PARTITIONED_READ | serialized | **0** | 0.6000 | 0.511 | 1387 |
| PARTITIONED_READ | concurrent | **9** | **0.7368** | 0.414 | 1361 |

**PARTITIONED_READ — which reads no other principal's state at all and enforces
a box proved sound — leaks 4.5× MORE than GLOBAL_READ.** Violations by agents
per principal at M=2: **N=1 → 0, N=2 → 2, N=4 → 6.** Monotone in N.

The box is a sound predicate over *states*; the admission *test* is still taken
against a stale snapshot. With N ≥ 2 a principal's own agents each verify "my
total stays ≥ L" against the same stale value of **their own** principal's total,
and jointly breach it.

> **Removing the cross-principal read did not remove the staleness — it
> relocated it from BETWEEN principals to WITHIN one.** The read-set's *extent*
> was never the disease. Its *recency requirement* is, and that survives every
> partitioning of the read-set.

That is why this is AGGREGATE-IS-HARDER rather than AGGREGATE-SPLITS: the
partitioned design that R10's rule points at does not rescue the quantity, and
the failure it leaves behind is not even aggregate any more.

---

## 3. The composition matrix, with counter-metrics beside every containment number

240 cells. Violations are COUNTS over `(round, quantity)` pairs; the R10-style
per-round binary is in `ag3_result.json` as `rounds_any_violation`.

| config | mode | v_inst | v_cum* | v_path | throughput | ratio to F0 | blocked | UNDEF |
|---|---|---|---|---|---|---|---|---|
| F0 | serialized | 18 | 123 | 42 | 3.88 | 1.000† | 360 | 4 |
| F0 | concurrent | 12 | 125 | 30 | 4.88 | 1.000† | 0 | 4 |
| LOCAL | serialized | **18** | 123 | 42 | 2.76 | 0.713 | 760 | 4 |
| LOCAL | concurrent | **12** | 125 | 30 | 3.70 | 0.759 | 471 | 4 |
| GLOBAL_READ | serialized | 0 | 73 | 0 | 3.71 | 0.957 | 530 | 0 |
| GLOBAL_READ | concurrent | 2 | 79 | 3 | 4.49 | 0.920 | 239 | 0 |
| PARTITIONED_READ | serialized | 0 | 63 | 0 | 1.98 | 0.511 | 1387 | 0 |
| PARTITIONED_READ | concurrent | 9 | 71 | 11 | 2.02 | 0.414 | 1361 | 0 |

\* **the cumulative column is a CONTROL and is DEFINITIONAL.** No guard here
bounds cumulative drain; R13 already measured that class. Its counts are **not**
independent replication of R13 and carry no weight. The 123 → 73 reduction is an
incidental side effect of a concentration guard blocking some drains.

† **F0's ratio of exactly 1.000 is DEFINITIONAL** — it is the baseline divided
by itself.

### LOCAL costs 26% of throughput and buys EXACTLY NOTHING

**LOCAL's violation count equals F0's in all 60 cells — zero cells differ** —
while blocking **871 extra actions**. Diagnosed, not reported raw: LOCAL compares
its own share against a denominator frozen at `s_0`, so it can only ever block
its own principal's *growth*. The mechanism that raises concentration is **other
principals shrinking**, which LOCAL cannot see by construction. It is a guard
that watches the wrong end of the ratio.

This is the cleanest available demonstration that **a guard's throughput cost is
not evidence that it is doing anything.**

### Diagnosing the exact 0s and 1s (standing rule)

| number | verdict |
|---|---|
| GLOBAL/PARTITIONED serialized `v_inst = 0` | **MEASURED.** The same detector reports 18 on the same cells under F0, so it has power; and the composition-failure test proves the harness can exhibit a violation. |
| F0 throughput ratio `1.000` | **DEFINITIONAL** (baseline over itself). |
| LOCAL ≡ F0 in all 60 cells | **MEASURED**, with the mechanism above. |
| GLOBAL_READ serialized max = `0.6000` = κ | **Expected**: an inductive invariant binding tight is what correctness looks like here. |

---

## 4. WHAT THIS DOES TO THE AGGREGATE BUDGET QUESTION

**The practical deliverable. AGGREGATE-IS-HARDER fired, so the mechanism
question is answered analytically and the budget picture changes.**

**What CooperBench traces are NO LONGER needed for:**

1. **Establishing whether aggregate harm composes under concurrent multi-agent
   execution.** It does not. That is now a proof with a constructive
   counterexample, verified in 240 deterministic cells at zero cost. Buying
   traces to discover it would be buying a confirmation.
2. **Deciding whether a partitioned/local guard design rescues it.** It does not
   — measured, and it is *worse* than the global read. No trace is needed to
   re-learn this.
3. **Deciding where an aggregate bound must be evaluated.** At a point where the
   read is current with respect to the decision. The architecture already has
   exactly one such point — the promotion gate — and this result says aggregate
   bounds belong there and nowhere else.

**What CooperBench traces are STILL needed for, and it is the whole remaining
question:**

> **WHICH aggregate harms do real multi-agent systems actually exhibit?**

AG-3 shows ratio-type quantities do not compose and same-direction ones do. That
turns the empirical question into a **classification** task over real workloads —
are the aggregate harms that matter in practice directionally local or not? —
which is far cheaper than the open-ended one that was blocked. It needs traces
*labelled by harm type*, not a full generation run over 652 tasks, and a
100-task subset would answer it.

**The budget implication:** requirement four's *mechanism* is off the critical
path. Its *taxonomy* is now the blocker, and the taxonomy question is answerable
with roughly an order of magnitude less generation than the original framing
required. **This does not make it free, and this route deliberately does not
substitute for it.**

---

## 5. Relationship to R13 and R10

**R13** measured CUMULATIVE-JOINT and its mechanism is *a stateless check cannot
accumulate*. **AG-3 finds a second, independent obstruction in a different cell**:
instantaneous-joint quantities fail from stale-read admission, which has nothing
to do with accumulation — the quantity has no memory at all. Two mechanisms, two
cells, the same conclusion. R13's impossibility does **not** generalise; it did
not need to.

**R10's design rule** — a guard scales in breadth only if its own state
partitions — is **necessary but not sufficient**, and AG-3 sharpens it.
PARTITIONED_READ's state partitions perfectly and it still fails. The rule
governs *state*; the failure is in *read recency*. R10's rule should be read as
one of two conditions, the other being that the admission decision is linearized
against updates to everything it reads.

---

## 6. Honest limits

- **Analytic + simulation over a hand-designed action vocabulary and hand-chosen
  quantities, M ≤ 3, N ≤ 4.** It says **nothing** about which aggregate harms
  real systems exhibit.
- **The counterexample is the load-bearing result; the simulation confirms it.**
  The *rate* at which composition fails is workload-dependent and rests on one
  adversary (§7).
- Two quantities exercise one class each; the classification claim generalises
  by the directional-locality argument, not by breadth of examples.
- No cumulative guard was implemented. The cumulative class is untested here by
  design.

## 7. Disclosures

1. **ALL instantaneous violations come from ONE adversary — `mixed`.** A1-salami,
   A2-ratchet, A3-cross and A4-pool contribute **0** in every configuration.
   Per the preregistered rule this makes **every instantaneous simulation cell
   INCONCLUSIVE on adversary breadth.** The reason is structural and was not
   anticipated: R13's four attacks were designed against R13's quantities
   (drain, pool overdraft) and none of them targets concentration, so the new
   quantity is exercised only by the benign varied workload. **No adversary was
   designed to attack concentration**, and designing one after seeing these
   results is the tuning this program forbids. The *refutation of P3 does not
   depend on this*: it is a constructive counterexample, proved and unit-tested,
   not a simulated rate.
2. **M = 3 is underpowered for concentration, as flagged in the preregistration.**
   F0 concurrent instantaneous violations at M=3 are 1, 0, 0 for N = 1, 2, 4.
   The M=3 concentration cells carry almost no information and the preregistration
   said so before the run (exceedance 0.0167).
3. **Gate 0c error, caught before any threshold was fixed:** my first
   concentration probe returned `1.0` when the federation total reached 0,
   conflating "maximally concentrated" with "undefined". Fixed to return `None`;
   UNDEFINED rounds are counted (`undefined_rounds`) and excluded, never scored.
   This is the error-as-value species, found in my own metric.
4. **Test-fixture fix, disclosed:** the first composition-failure fixture used
   one action per principal (amt=8) and reached only 0.4545 — too weak to exhibit
   the effect it exists to prove is detectable. **The threshold κ was not moved**;
   the fixture was rebuilt with two actions per principal. Implementation fix,
   not tuning.
5. **PARTITIONED_READ's failure was not predicted.** The preregistration asked
   whether it would lose composition relative to GLOBAL_READ; it does, by 4.5×,
   and for a reason (intra-principal staleness) that the preregistration did not
   name. Reported as an unpredicted finding rather than folded into P3.
