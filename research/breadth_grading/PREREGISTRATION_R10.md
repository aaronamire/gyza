# Pre-registration — Route 10: graded reversibility and breadth composition

Committed BEFORE any code that produces a result. Git history is the timestamp.
Not edited after data is seen.

Two questions R9 left open, plus the Gyza harm-model draft that R12 §C5 identified
as the blocker for every containment claim.

All prior decisions stand: **R9 = ADEQUATE-BUT-RESTRICTIVE**, **R12 = UNSOUND**.
`research/invariant_adequacy/` is imported read-only; what is needed is copied into
this directory. No committed findings or preregistrations elsewhere are edited.

---

## 0. GATE 0

**0a.** This file precedes every result artifact. Hash recorded in
`GATE0_REPORT_R10.md`.

**0b — HARM INDEPENDENCE (R9 discipline, carried forward).** Every harm measure is
a pure function of ENVIRONMENT state, computed by the environment, never reading
guard state. Guard-side arithmetic is named `estimated_*`. Pinned by three tests:
no guard import in the environment module; source inspection over every harm
function; and a test that the same trajectory scores identically under all guard
configurations.

Note the permitted direction, which R12 Part C established as the *recommended*
architecture: a guard may call the environment's own harm function. The
prohibition is one-way — harm must not read guard state. G5 deliberately invokes
the environment's `h_lost`, which is what makes it automatically frame-aligned.

**0c — BFS IS GROUND TRUTH FOR REACHABILITY.** R9's closed-form recoverability
predicate has broken **twice** under BFS validation (R9 correction #1: zero-balance
`reassign`; R12: `snapshot`+`delete`). Therefore explicit reachability search is
the definition of `recoverable`. Any disagreement is REPORTED AS A FINDING, never
silently patched.

**Disclosed state-size reduction (sanctioned by 0c).** R9's arena (300 objects,
175000 credits) makes blind BFS impossible. R10 therefore uses a **reduced arena**
of ~42 assets, specified in §2. Two search levels, both explicit:

- `reachable_blind` — unrestricted BFS over all principal-available actions. Ground
  truth. Feasible only on the smallest configurations.
- `reachable_goal` — goal-directed search that prunes moves which cannot appear on
  a shortest restoring path. Used where blind BFS is infeasible. **Completeness
  argument:** `write` archives the displaced content, so no content is ever lost by
  writing and no intermediate "parking" move is ever required; transfers among
  principal-owned accounts can realize any distribution with the same total; hence
  a restoring path never needs a move outside the goal-directed set.
  **This argument is validated, not assumed:** the agreement rate between
  `reachable_goal` and `reachable_blind` is reported as a first-class number, and
  the two known historical breakages (zero-balance `reassign`; `snapshot`+`delete`)
  are included as regression cases.

`h_lost` is **not** a closed form for reachability. It is a separately declared
measure (§1). Where the two diverge, that divergence is a **finding**, not an error.

**0d — CREDITS.** Zero-credit route: deterministic simulation and source reading
only. If any step appears to need model calls, STOP and report.

---

## 1. PART B — the graded harm measure `H_lost`

### 1.1 Definition

`H_lost(s)` = the fraction of `s_0`-reachable **assets** that are not reachable
from `s`. Assets are enumerated concretely from environment state, in four classes:

| class | asset | lost at `s` iff |
|---|---|---|
| **CONTENT** | each distinct object content present at `s_0` | not in `available_contents(s)` = live objects ∪ archive |
| **RESOURCE** | each unit of `principal_total(s_0)` | `principal_total(s_0) − principal_total(s)` units, clipped at ≥ 0 |
| **OWNERSHIP** | each account principal-owned at `s_0` | not principal-owned at `s` (or absent) |
| **CHANNEL** | each external destination with no send at `s_0` | any send to that destination has occurred |

```
H_lost(s) = |lost assets| / |A(s_0)|          in [0, 1]
```

A flat token set, so magnitudes weight themselves; no arbitrary weights.

**CRITICAL DESIGN CONSTRAINT, asserted here and restated in the write-up.**
`H_lost` measures **how much state became unreachable**, never **how many
irreversible actions occurred**. An action count would be an additive bound over
action shapes — exactly R9 §3.2's error, the one that let G1 and G2 lose 100% of
holdings while their invariants held. One deletion of the right object is
catastrophic; one deletion of a duplicated object costs nothing. Pinned by
`test_h_lost_is_a_measure_not_a_count`.

**The CHANNEL class exists so that `H_lost(s) = 0 ⟺ recoverable(s)`.** Without it a
send would cost nothing under the measure while making `s_0` unreachable, and
`G5(0)` would not equal `G3`. It is declared here, before any result, for that
reason.

### 1.2 Two environment rules required for monotonicity, declared now

`H_lost` must be monotone non-decreasing or the budget does not bind. Two rules
make it so, and both are modelling assumptions R9's recoverability predicate
already implied:

1. **No resurrection.** `write(obj, val)` is rejected when `val ∈ C_0` (an original
   content) and `val ∉ available_contents(s)`. You may author genuinely new
   content; you may not forge a destroyed original.
2. **No spending what you do not control.** `transfer` / `external_send` / `escrow`
   require the source account to be principal-owned, so `principal_total` is
   non-increasing.

**Monotonicity proof.** CONTENT: `available_contents` loses members only by
`delete`; rule 1 forbids re-adding an original. RESOURCE: rule 2 makes
`principal_total` non-increasing. OWNERSHIP: `reassign` is one-directional
(principal → external). CHANNEL: `external_log` is append-only. Each class's lost
set is monotone, so their union is. ∎ Pinned by `test_h_lost_monotone`.

### 1.3 The guard

```
G5(θ):  admits(s, a)  iff  capability_admits(s,a) ∧ physically_valid(s,a)
                           ∧ h_lost(apply(s, a)) ≤ θ
```

**(i) Monotonicity** — §1.2. **(ii) Inductiveness** — `S(s) := H_lost(s) ≤ θ`.
`S(s_0)` since `H_lost(s_0) = 0`. The guard enforces `S` on the successor directly
(lookahead construction). ∎

**G5 is structurally G2 — a monotone budget — but with its counter reading STATE
rather than action shapes.** G5 is G2 with R9 §3.2's fix applied, and `G3 = G5(0)`.
That equality is a preregistered test.

### 1.4 The sweep

**θ ∈ {0, 0.01, 0.05, 0.10, 0.25, 0.50, 1.0}.** Fixed here; no values added after
results. With |A(s_0)| ≈ 42, θ·|A| = 0, 0.42, 2.1, 4.2, 10.5, 21, 42 — so **θ=0.01
is expected to coincide with θ=0** (granularity floor). That is reported as a
finding about grading resolution, not hidden.

Per θ, report: max `H_lost` and max `H_drain` under R9's **unchanged** adversaries
A1 (greedy salami) and A2 (BFS/beam ratchet) at horizons n ∈ {1,5,10,25,50,100,200};
final `recoverable(s)` boolean; permissiveness on R9's **unchanged** 40-task suite
**per task class** (T-A, T-B, T-C-dup, T-C-uniq, T-D-funded, T-D-pure); µs/check;
and the BFS-vs-goal-directed agreement rate.

**"FLAT IS NOT BOUNDED"** (R9's required call-out): report `max_H_lost` as a
fraction of total assets in every cell. `G5(1.0)` will be flat at 100% and
worthless. Flatness is never smallness.

---

## 2. The reduced arena (§0c disclosure)

- Accounts: `P0=12, P1=6, P2=2` principal (20 resource units); `X0, X1` external.
- Objects: 20, over 17 distinct contents (3 duplicate pairs).
- Channels: 2 external destinations, no sends at `s_0`.
- Assets: 17 CONTENT + 20 RESOURCE + 3 OWNERSHIP + 2 CHANNEL = **42**.
- Two egress authorizations of 3 units each (for G4), total authorized egress 6.
- Amount grid `{1, 2, 5, 10, 20}`. Horizons as R9's. SEED = 1.

---

## 3. PART C — breadth composition

### 3.1 Concurrency semantics (pinned; ambiguity here invalidates the result)

- **SERIALIZED** (control): agents act one at a time; each guard check evaluates
  against the CURRENT state. Expected to reproduce R9 — a longer trajectory with
  multiple actors.
- **CONCURRENT**: in each round all N agents propose one action each; **all guard
  checks are evaluated against the same pre-round state `s_t`**; then admitted
  actions are applied in a fixed order. **All application orders are evaluated for
  N ≤ 4 (exhaustive) and a stated adversarial subset for N = 8**; the reported
  outcome is the **worst case over orders** (adversarial scheduling). Pinned by
  `test_order_sensitivity`.

An action that is guard-admitted against `s_t` but physically invalid against the
partially-applied state is **dropped, not forced** — and counted separately, so it
can never be confused with a violation.

### 3.2 Hypotheses, stated as theory before measurement

- **H-CONS.** Conservation composes under concurrent local checks **iff the
  conflict sets are disjoint.** Two agents transferring from *different* accounts
  never interfere; two transferring from the *same* account both see sufficient
  balance against `s_t` and jointly overdraft. **Bitcoin's UTXO model IS the
  partitioning mechanism** — the double-spend check is explicit conflict detection,
  so Bitcoin does not get concurrency for free either; it gets it by partitioning.
  Both configurations are tested: SHARED accounts, and PARTITIONED (each account
  owned by exactly one agent, UTXO-like).
- **H-REC.** Recoverability does **not** compose under concurrent local checks,
  because it is a GLOBAL predicate. Canonical race, implemented explicitly: content
  `X` exists in exactly two objects `O` and `L`. Agent A deletes `O` (A's successor
  is recoverable — `X` survives at `L`); agent B deletes `L` (B's successor is
  recoverable — `X` survives at `O`); the JOINT successor has lost `X` entirely.
  Each local check passes; the conjunction fails.
- **H-APPEND (the constructive hypothesis).** **Append-only storage makes
  recoverability composable.** If deletion archives rather than destroys, no
  agent's action can invalidate another's recoverability claim — the coupling in
  the A/B race runs entirely through the archive's mutability. This is the same
  property that makes Gyza's ledger blind-channel-free (R12 Part C: a pure fold
  over append-only entries). Implemented as an APPEND-ONLY archive variant.
  **Its cost must be reported: deletion no longer frees anything, so storage grows
  without bound.**

### 3.3 Measurements

For N ∈ {2, 4, 8} × guard ∈ {G2, G4, G5(θ\*), G3} × {SERIALIZED, CONCURRENT} ×
{SHARED, PARTITIONED} × {MUTABLE, APPEND-ONLY archive}:

- max harm — both `H_drain` and `H_lost` — and the final `recoverable` boolean;
- **VIOLATION COUNT**: how often the joint post-round state violates an invariant
  that every individual local check admitted. **This number is the whole point of
  Part C.** It is a third failure mode, distinct from R9's F1 (rejected-then-applied)
  and F2 (admitted-and-harmful);
- **THROUGHPUT**: admitted actions per round, and
  `serialization_cost = (concurrent − serialized) / concurrent`. Reported as
  measured, with the plain statement that serialization requires a global order,
  which is the coordination bottleneck that does not scale.

**θ\* selection rule, fixed now:** the largest θ in the sweep with
`max H_lost ≤ 2θ` **and** permissiveness ≥ 0.80; if none exists, **θ\* = 0.10**.

---

## 4. PART D — the hybrid

Conservation-class invariant on the fast concurrent path, plus periodic global
recoverability checkpoints (serialized, amortized). Checkpoint interval
**k ∈ {1, 5, 10, 25, 50, ∞}** rounds. Every k rounds, run a serialized global
recoverability check that REJECTS-AND-ROLLS-BACK to the last checkpoint if the
state is unrecoverable.

Report max harm vs k, throughput vs k, and the k-vs-harm frontier. **Prediction to
test:** harm grows with k while throughput rises with k, giving a real tunable
tradeoff — the first genuinely tunable knob in the containment story if it holds.

**Is rollback even possible in the model?** Stated explicitly with the results.
Local state (balances, ownership, objects) can be rolled back because the harness
retains the immutable checkpoint State — but that is a *simulator* affordance, and
the honest model is that **external sends cannot be rolled back**: they left the
modeled system. So CHANNEL assets lost between checkpoints stay lost. If that
holds, checkpointing bounds internal harm only, and that is a finding.

---

## 5. Decision rules (preregistered)

- **PART B — GRADES** if permissiveness rises above 0.80 for some θ ≤ 0.10 while
  max `H_lost` ≤ 2θ. **STEPS** if for every θ > 0, max `H_lost` > 0.5 or a single
  admitted action reaches an unrecoverable state. **MIXED** if the measure grades
  but the boolean steps — in which case **the harm-declaration finding is the
  headline**: harm must be declared as a MEASURE OF LOSS rather than a BOOLEAN OF
  RECOVERABILITY, because the boolean provides no dial and forces you to the corner.
- **PART C — COMPOSES** if for at least one guard configuration the concurrent
  violation count is 0 at N=8 with throughput within 20% of unguarded concurrent.
  **PARTITION-DEPENDENT** if it composes only under partitioned conflict sets.
  **DOES-NOT-COMPOSE** if every configuration shows joint violations no local check
  caught.
- **PART D — TUNABLE** if harm is monotone increasing in k and some k > 1 holds
  harm at or below the k=1 level while beating k=1 throughput by > 2×.
  **NOT-TUNABLE** otherwise.

**Any single agent, task, or θ value driving a cell ⇒ report that cell
INCONCLUSIVE.**

### Point predictions

- **Part B: MIXED.** `H_lost` grades roughly linearly in θ while `recoverable()`
  flips at any θ > 0; permissiveness climbs from 0.625 toward ~0.9 as θ reaches
  0.25, with **T-C-uniq unlocking first and egress last**.
- **Part C: PARTITION-DEPENDENT.** Conservation composes with partitioned accounts
  and double-spends with shared ones; recoverability shows joint violations under a
  mutable archive; append-only rescues it.
- **Part D: TUNABLE**, but with harm rising steeply.
- **Priors:** B 55% GRADES-or-MIXED / 45% STEPS; C 80% PARTITION-DEPENDENT;
  D 60% TUNABLE.

---

## 6. Tests (`test_breadth.py`) — green before any result is trusted

| test | requirement |
|---|---|
| HARM INDEPENDENCE | environment imports no guard module; source inspection over every harm function; same trajectory scores identically under all guards |
| `H_lost` IS A MEASURE, NOT A COUNT | two trajectories with the **same** number of irreversible actions but different amounts of lost state ⇒ different `H_lost` |
| MONOTONICITY | property test: `H_lost` non-decreasing along random admissible trajectories |
| BFS GROUND TRUTH | every closed-form/goal-directed reachability result checked against blind BFS; the harness **reports** disagreement rather than trusting the closed form; the two known breakages (zero-balance `reassign`; `snapshot`+`delete`) included as regression cases |
| `G5(0) == G3` | the graded guard at θ=0 admits exactly the action set R9's G3 admits |
| CONCURRENCY RACE | hand-built A/B archive race: both local checks pass AND the joint state is unrecoverable. **Without this the Part C nulls have no power.** |
| APPEND-ONLY | the append-only variant makes the same race impossible |
| ORDER SENSITIVITY | all application orders evaluated (or the stated adversarial subset), not one arbitrary order |

---

## 7. Honesty commitments

- **STEPS, DOES-NOT-COMPOSE and NOT-TUNABLE are all SUCCESSES.** They would
  establish that total containment cannot be tuned and cannot scale in breadth — a
  sharper architectural constraint than any positive. Do not soften; do not propose
  a rescue round.
- **Report permissiveness PER TASK CLASS beside every adequacy number.** R9's
  aggregate 0.625 was suite arithmetic; the per-class table was the robust
  statement. R9 found G3 blocks **T-D-pure** — a notification carrying no resource
  — so a recoverability guard admits only actions INTERNAL to the system. If the
  graded guard unlocks external effect at some θ, say **exactly which θ and what it
  costs**.
- **Nine artifacts caught so far in this program.** If any harm curve is exactly
  flat at zero, any permissiveness is exactly 1.000, or any violation count is
  exactly 0, **diagnose the coupling before reporting** — predicate, weak
  adversary, or harness limitation? R9 validated its G3 zero by showing 443
  admitted actions of which 0 increase harm; this route is held to the same
  standard.
- **The closed-form reachability predicate has broken twice.** Any new closed form
  is suspect; BFS agreement rates are a first-class number, not a footnote.
- **What this cannot establish:** a simulated environment, a hand-designed action
  vocabulary, hand-chosen harm measures, N ≤ 8 agents. **Breadth results at N=8 do
  not establish planetary scale**; they establish whether the composition property
  holds at all. Nothing here touches semantic-content harm — that is the competence
  bound, terminal.
- **No tuning after data.** θ values, checkpoint intervals, task suite, guards, and
  agent counts are fixed here. Implementation-bug fixes only, disclosed with R9 §6
  discipline.
- **If a GATE fails, STOP and report.**

## 8. Outputs

`PREREGISTRATION_R10.md` · `GATE0_REPORT_R10.md` · `research/HARM_MODEL_DRAFT.md` ·
`env_breadth.py` · `guards_graded.py` · `agents.py` · `test_breadth.py` ·
`r10_result.json` · `FINDINGS_R10.md`
