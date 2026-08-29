# Findings — Route 10: graded reversibility and breadth composition

Write-up per `PREREGISTRATION_R10.md` (`2708379`) and its pre-data amendment
(`a880f2c`). Zero credits: deterministic simulation and source reading only. All
prior decisions stand — R9 = ADEQUATE-BUT-RESTRICTIVE, R12 = UNSOUND — and
`research/invariant_adequacy/` was imported read-only and never modified.

---

## DECISIONS

| part | verdict | one line |
|---|---|---|
| **A** | delivered | `research/HARM_MODEL_DRAFT.md` — four harm classes; **two of four have no guard reading their fields**, one has no representation in the codebase at all |
| **B** | **MIXED** | the **measure** grades cleanly; the **boolean** steps at the first θ > 0. Harm must be declared as a measure of loss, not a boolean of recoverability |
| **C** | **COMPOSES — but vacuously; substantively DOES-NOT-COMPOSE** | the rule fires only on `G5(1.0)`, which admits everything. Every non-vacuous guard shows joint violations at N = 8, **including under partitioned accounts** |
| **D** | **NOT-TUNABLE** | harm is monotone in k, but no k > 1 holds harm at the k=1 level; and at k=1 **every round was rolled back**, so effective throughput was zero |

---

## 1. PART B — the θ frontier (the headline)

Reduced arena, **42 assets** (17 CONTENT + 20 RESOURCE + 3 OWNERSHIP + 2 CHANNEL).
`classmean` is the decision variant, fixed in the amendment before any number
existed.

| θ | max `H_lost` | max `H_drain` | `recoverable` | permissiveness | µs/check |
|---|---|---|---|---|---|
| 0.00 | **0.0000** | 0 | **True** | 0.625 | 30.1 |
| 0.01 | 0.0000 | 0 | True | 0.625 | 29.7 |
| 0.05 | **0.0500** | 4 | False | 0.625 | 31.6 |
| 0.10 | **0.1000** | 8 | False | **0.750** | 30.9 |
| 0.25 | **0.2500** | 13 | False | **0.875** | 36.2 |
| 0.50 | 0.4877 | 20 | False | **1.000** | 30.0 |
| 1.00 | 0.6985 | 20 | False | 1.000 | 30.8 |

**Adequacy grades exactly.** `max H_lost` equals θ to four decimals at θ = 0.05,
0.10, 0.25 and stays under it above — `max H_lost ≤ 2θ` holds in every cell. The
guard binds precisely at its budget. This is G2's *structure* (a monotone budget)
with R9 §3.2's *fix* applied: the counter reads state, not action shapes.

**Permissiveness climbs, and the unlock order is exactly the preregistered point
prediction:**

| θ | T-A | T-B | T-C-dup | T-C-uniq | T-D-pure | T-D-funded |
|---|---|---|---|---|---|---|
| 0 – 0.05 | 1.0 | 1.0 | 1.0 | **0.0** | **0.0** | **0.0** |
| 0.10 | 1.0 | 1.0 | 1.0 | **1.0** | 0.0 | 0.0 |
| 0.25 | 1.0 | 1.0 | 1.0 | 1.0 | **1.0** | 0.0 |
| 0.50 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | **1.0** |

R9 found G3 blocks **T-D-pure** — a notification carrying no resource — so a
recoverability guard admits only actions *internal* to the system. **The graded
guard unlocks external effect at θ = 0.25, and the price is exactly 25% of the
principal's assets becoming destructible.** Funded egress costs θ = 0.50.

### Why MIXED, stated precisely

The preregistered STEPS clause has two disjuncts, and its **second** one —
"a single admitted action reaches an unrecoverable state" — fires at every θ > 0:
one deletion of a unique content costs `1/17/4 ≈ 0.0147`, which θ = 0.05 admits,
and that state is unrecoverable. So STEPS technically fires while the measure
visibly grades across five distinct values. That is exactly the case the
preregistration anticipated and created MIXED for, so **MIXED is the verdict**,
and the finding is the one the rule named in advance:

> **Harm must be declared as a MEASURE OF LOSS, not a BOOLEAN OF RECOVERABILITY.**
> `recoverable()` provides no dial — it flips at the first θ admitting any loss at
> all — and a boolean harm model therefore forces you to R9's corner by
> construction. R9's empty middle was not a fact about reversibility; it was an
> artifact of declaring harm as a boolean.

`G5(0) == G3` is verified exactly (45 of 109 admitted actions, both variants), so
the graded guard is a strict generalization, not a different guard.

### Diagnosis of the clean numbers (mandatory, nine artifacts to date)

- **θ = 0.01 ≡ θ = 0.** The granularity floor: 0.01 × 42 < 1 asset. Reported, not
  hidden — it means grading resolution is bounded below by one asset token.
- **θ = 1.0 is flat at 0.6985 with permissiveness 1.000 and is worthless.** Flat
  is not bounded. It is flat at 70% of everything.
- **`H_lost = 0` at θ = 0 is analytic**, inherited from R9's G3 result and re-verified
  here by `G5(0) == G3`.

### The denomination artifact the amendment predicted, before data

The `flat` variant — the definition as originally preregistered — behaves
differently, and the amendment said why in advance:

| θ | `classmean` perm | `flat` perm | `flat` unlocks |
|---|---|---|---|
| 0.01 | 0.625 | **0.875** | T-C-uniq **and** T-D-pure immediately |
| 0.05 | 0.625 | **1.000** | everything |

With RESOURCE counted in credit units, one CHANNEL asset is `≈ 0.001` of a
T-D state holding 1000 credits, so **egress unlocks first instead of last** — the
reverse ordering. **The same guard at the same θ admits opposite task classes
depending on how the harm measure normalizes.** That is a result about harm-model
design, not about guards, and it is why the amendment fixed `classmean` as the
decision variant before any number existed.

---

## 2. PART C — breadth composition

**SERIALIZED is the control and it reproduces R9 exactly: 0 violations in every
one of the 40 serialized cells.** Depth composition works with multiple actors;
it is a longer trajectory, nothing more.

Concurrent, N = 8, mutable archive:

| guard | accounts | violations | throughput | max `H_lost` | recoverable |
|---|---|---|---|---|---|
| G2 | shared | **1** | 2.67 | 0.400 | False |
| G2 | partitioned | **1** | 2.67 | 0.425 | False |
| G4 | shared | **1** | 2.67 | 0.400 | False |
| G4 | partitioned | **1** | 2.67 | 0.425 | False |
| G3 | shared | **1** | 0.50 | 0.044 | False |
| G3 | partitioned | **1** | 0.50 | 0.044 | False |
| **G3 + append-only** | either | **0** | 0.67 | **0.000** | **True** |
| G5(1.0) / G0 | either | 0 | 4.00 | 0.500 | False |

### H-REC: confirmed. Recoverability does not compose.

The canonical race is real and the harness detects it (pinned by
`test_concurrency_race_...`): content X in exactly two objects; agent A deletes
one (X survives at the other — local check passes), agent B deletes the other
(local check passes), the joint state has lost X. **Each local check passes; the
conjunction fails.** 1 violation at N = 2, 4 and 8.

### H-CONS: the prediction was PARTITION-DEPENDENT. **It is wrong, and the reason is sharper.**

I predicted conservation would compose once accounts were partitioned. It does
not: G2 and G4 violate under **partitioned** accounts just as under shared ones.

The diagnosis is that **I mis-identified the conflict set.** Partitioning the
*accounts* leaves the *guard's own state* shared — G2's single counter `c`, and
G4's single pool of single-use authorizations. Eight agents each check
`c + drain ≤ B` against the same pre-round `c = 0`, all pass, and the joint total
blows the budget; eight agents each match the same unconsumed authorization.
**Bitcoin's UTXO model partitions the state being conserved, not merely the
accounts that hold it** — and a guard with one global counter has a conflict set
of size one no matter how the accounts are arranged.

### H-APPEND: confirmed, and it is the one constructive result.

Append-only storage makes recoverability composable: **0 violations, `H_lost` =
0.000, final state recoverable**, at *higher* throughput than the mutable variant
(0.67 vs 0.50). The coupling in the A/B race runs entirely through the archive's
mutability, and removing that removes the race —
`test_append_only_makes_the_race_impossible` pins it.

**Its cost is real and is reported:** deletion no longer frees anything, so
storage grows without bound (`test_append_only_has_a_cost_nothing_is_ever_freed`).
This is the same property that makes Gyza's ledger blind-channel-free (R12 Part C):
a fold over append-only state.

### Why the verdict is vacuous, and what the honest reading is

The preregistered rule fires **COMPOSES** — but the *only* configurations
satisfying it are `G5(1.0)`, which admits everything and is byte-identical to the
unguarded baseline. **That is a preregistration defect, disclosed:** the θ\*
selection rule ("largest θ with `max H_lost ≤ 2θ` and perm ≥ 0.80") is trivially
satisfied for θ ≥ 0.5, so it selected θ\* = 1.0 and Part C's graded-guard cell
tested an unguarded system. Per the preregistered "any single guard driving a cell
⇒ INCONCLUSIVE" clause, **the G5 cell of Part C is INCONCLUSIVE**, and the
substantive verdict for non-vacuous guards is **DOES-NOT-COMPOSE**.

**Supplementary, explicitly NOT preregistered and therefore not driving the
decision:** re-running Part C at meaningful θ shows a configuration that does
compose —

| supplementary cell (N=8, concurrent, shared) | violations | throughput | max `H_lost` |
|---|---|---|---|
| G5(0.05), mutable | 1 | 0.67 | 0.074 |
| G5(0.10), mutable | 1 | 1.33 | 0.191 |
| **G5(0.25), append-only** | **0** | **4.00** (= unguarded) | **0.250** (= θ exactly) |

A graded guard at θ = 0.25 over append-only storage shows zero joint violations at
N = 8 at full unguarded throughput, with harm bounded exactly at θ. **This points
the opposite way from the preregistered verdict and is reported as such**; it is
one supplementary configuration, and it is what the θ\* rule should have found had
it been written with a cap.

### Throughput and the serialization cost

Serialized throughput is *lower* than concurrent in every guard (G3: 0.25 vs 0.50;
G2: 1.92 vs 2.67), so the measured "serialization cost" is negative — serializing
makes each check see prior actions and correctly reject more of them. **Safety is
bought with rejected work, not with coordination overhead, at this scale.** The
coordination bottleneck is nonetheless real and unmeasured here: serialization
requires a global order, which is exactly what does not scale, and N ≤ 8 on one
machine cannot show that.

---

## 3. PART D — the checkpoint frontier

Concurrent conservation-guarded agents, serialized global recoverability check
every k rounds with rollback. 30 rounds, N = 4.

| k | rollbacks | nominal throughput | **effective throughput** | max `H_lost` (mutable) | max `H_lost` (append-only) |
|---|---|---|---|---|---|
| 1 | **30 / 30** | 4.00 | **0.00** | 0.029 | **0.000** |
| 5 | 6 / 30 | 4.00 | **3.20** | 0.250 | 0.000 |
| 10 | 3 / 30 | 2.53 | 2.28 | 0.500 | 0.250 |
| 25 | 1 / 30 | 1.87 | 1.80 | 0.500 | 0.250 |
| 50 | 0 / 30 | 1.20 | 1.20 | 0.500 | 0.250 |
| ∞ | 0 / 30 | 1.20 | 1.20 | 0.500 | 0.250 |

**Harm is monotone increasing in k** (0.029 → 0.250 → 0.500, then flat), as
predicted. **NOT-TUNABLE** fires because no k > 1 holds harm at or below the k = 1
level — and inspecting the rule, it could not have fired: "harm ≤ the k=1 level
**and** throughput > 2× k=1" demands strict improvement on *both* axes, which is
the definition of *not* a frontier. **The rule as written can only fire in a
degenerate case; that is a second preregistration defect, disclosed.**

**The finding the rule missed is the throughput metric itself.** At k = 1 every
single round was rolled back (30/30), so the nominal throughput of 4.00
corresponds to **zero surviving work**. Counting admitted-but-rolled-back actions
as throughput inverts the reading entirely. On effective throughput there *is* a
real frontier — k = 5 delivers 3.20 effective at harm 0.250, versus 0.00 effective
at harm 0.029 for k = 1 — but it is a frontier between "no work" and "some harm",
not the tunable knob the prediction hoped for.

**Append-only halves harm at every k** (0.500 → 0.250) and gives **0.000 at
k ≤ 5**, because content loss is impossible by construction; the residual 0.250 is
resource and ownership loss, which checkpointing does bound.

**Rollback in the model.** Local state (balances, ownership, objects) is rolled
back because the harness retains the immutable checkpoint. **External sends cannot
be rolled back** — they left the modeled system — so CHANNEL assets lost between
checkpoints stay lost. **This asymmetry was asserted in the design but not
exercised: `channel_assets_lost = 0` in every cell**, because the agent policy
proposed deletes and transfers, never sends. The claim stands as a model property,
not as a measurement, and is labelled as such.

---

## 4. Corrections and disclosures

**One harness bug, found by the mandated diagnose-any-exact-zero rule, before
reporting.** `run_round` evaluated the guard invariant **before** `commit`, so
G2's violation count read 0 while its counter stood at **16 against a budget of
6**. Fixed by cloning the guard per application order, committing each admitted
action, then evaluating the invariant on the joint state. **Part C was re-run in
full.** The pre-fix matrix is not reported. This is precisely the artifact class
the rule exists for — an exact zero that was definitional, not safe.

**One unsound memoization, caught by a test before any result.** `recoverable`
was memoized on `observable()` alone; two states with equal observables but
different archives have different reachability, and
`test_append_only_makes_the_race_impossible` failed immediately. Key corrected to
include archive and the append-only flag.

**Two preregistration defects, disclosed not repaired:** the θ\* selection rule
selects a vacuous θ (§2), and Part D's TUNABLE clause demands strict improvement
on both axes (§3). Both were fixed before data and are reported as written.

**Three declared implementation aids, all before results:** a stateless fast path
for the permissiveness search; memoized reachability; and a 25 s wall-clock bound
on R9's **unmodified** `a2_ratchet`, reported per cell as `a2_search_bounded`. The
bound fired only at θ ∈ {0, 0.01}, where `G5(0) == G3` makes the invariant
definitionally equivalent to recoverability, so no such path can exist.

**One adversary added and disclosed:** a greedy on `H_lost` itself. R9's A1
maximizes `H_drain`/`H_irrev`; omitting an `H_lost`-maximizing adversary would have
systematically understated max `H_lost` against a graded guard.

**GATE 0c held.** `reachable_blind` is the definition; `reachable_goal` agreed with
it on every parametrized case, including the zero-balance-`reassign` regression.
R12's `snapshot`+`delete` breakage cannot arise here and is asserted rather than
dropped. **No disagreement was found** — the first route in this program where the
reachability predicate did not break.

**Point predictions:** Part B MIXED ✓ with the unlock order exactly right (T-C-uniq
first, egress last) ✓; Part C PARTITION-DEPENDENT ✗ (partitioning does not rescue
conservation — the guard's own state is the conflict set); Part D TUNABLE ✗.

---

## 5. What this cannot establish

- A simulated environment, a hand-designed action vocabulary, two hand-chosen harm
  measures, and **N ≤ 8 agents on one machine**. Breadth results at N = 8 do **not**
  establish planetary scale; they establish whether the composition property holds
  at all. The coordination cost of a global order — the thing that actually fails
  to scale — is not measured here and cannot be at this size.
- The 42-asset arena is a disclosed reduction made so that BFS could be the ground
  truth (GATE 0c). Every θ value is relative to that asset set.
- `H_lost` measures destruction and loss of control. It does **not** measure
  disclosure harm beyond the coarse CHANNEL class, and the Part D rollback
  asymmetry was never exercised.
- Nothing here touches **semantic-content harm** — that is the competence bound,
  closed across six families, terminal.

## 6. What this does establish

1. **Reversibility grades, but only as a measure.** A graded guard bounds harm
   exactly at its budget (`max H_lost = θ` to four decimals) and buys back
   permissiveness monotonically — 0.625 → 0.750 → 0.875 → 1.000. R9's two-point
   frontier with an empty middle was an artifact of declaring harm as a **boolean**.
   **Declare harm as a measure of loss or you have no dial.**
2. **External effect has a price, and it is now named.** A recoverability-class
   guard admits only internal actions. Unlocking a no-resource external
   notification costs θ = 0.25; funded egress costs θ = 0.50.
3. **Depth composes; breadth does not.** Serialized multi-agent reproduces R9
   exactly (0 violations in 40 cells). Concurrent local checks produce joint
   violations that **no local check caught** — a third failure mode, distinct from
   R9's F1 and F2 — for conservation *and* recoverability, at N = 2, 4 and 8.
4. **Partitioning the accounts is not partitioning the conflict set.** A guard with
   one global counter or one authorization pool has a conflict set of size one
   however the accounts are arranged. Bitcoin partitions the state being conserved;
   that is a stronger discipline than partitioning who owns what.
5. **Append-only storage is the one thing that made a global predicate compose** —
   zero violations, zero harm, recoverable, at higher throughput — at the cost that
   nothing is ever freed. Together with R12 Part C (Gyza's ledger is
   blind-channel-free because it folds append-only entries), the same architectural
   property answers two different failure modes: it removes blind channels *and* it
   removes concurrent recoverability races.
