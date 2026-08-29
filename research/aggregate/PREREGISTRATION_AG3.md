# AG-3 — does R13's statelessness impossibility apply to AGGREGATE harm?

**Committed before any derivation, any proof, and any code that produces a
result.** Print this file's hash and confirm it predates `ag3_result.json`,
`THEORY_AG3.md`, and `FINDINGS_AG3.md`.

**ZERO CREDITS.** Analytic + deterministic simulation. `SEED = 1`. If any step
appears to require a model call, the route STOPS and reports.

---

## 0. Citation check on the prompt (Gate 0, before anything else)

| claim | verified |
|---|---|
| `research/THE_CORE.md` never committed | **confirmed absent**; not used for precedence |
| R13 = FEDERATION-DOES-NOT-COMPOSE; "a signature authorizes an ACTION, not a CONSEQUENCE"; statelessness is the mechanism | **confirmed**, `FINDINGS_R13.md` §DECISION |
| R13 counted violations as a COUNT over `(round, victim)` pairs, with the R10 binary retained separately | **confirmed**, `cross_violation_rounds` in `r13_result.json` |
| R13 concurrent semantics = all guards evaluate against the same pre-round state, admitted actions applied in a fixed order, worst case over orders | **confirmed**, `adversaries_federation.py:271-325` |
| the joint-pool overdraft is physically possible *on purpose* | **confirmed**, `env_federation.py` module docstring |

`research/federation/` is imported **read-only**; nothing in it is edited.

---

## 1. What I already know, declared because it bounds the claim

Known before writing this: R13's decision and mechanism; R10's design rule; the
attainable concentration ranges in §4 (measured during Gate 0c, below); and the
fact — noticed while measuring feasibility, therefore declared here rather than
presented later as a discovery — that **concentration is a RATIO**, so one
principal's action can change another principal's share without touching that
principal's state. That observation informs my priors in §7 and is *not* a
result.

**Not known:** whether any proposition below is true, and every simulated
number.

---

## 2. Definitions — the two axes, which are ORTHOGONAL

Conflating them is the error this route exists to avoid.

Let `s = (s_1, …, s_M)` be a joint state over M principals, and let
`τ = (s^0, a^1, s^1, …, a^T, s^T)` be a joint trajectory.

- **AGGREGATE** is a *spatial* property: `h` is aggregate iff it is not a
  function of any single principal's projection alone — formally, there exist
  `s, s'` with `s_p = s'_p` and `h(s) ≠ h(s')`.
- **CUMULATIVE** is a *temporal* property: `h` is cumulative iff
  `h(τ) = Σ_t g(s^{t-1}, a^t)` and `h` is **not** a function of `s^T` alone.

These are independent, so the space is a 2×2 and the prompt's three-way list is
a slice of it:

| | instantaneous (function of `s^T`) | cumulative (sum over `τ`) |
|---|---|---|
| **single-principal** | balance | total spend by *p* — **R10's domain** |
| **aggregate** | **concentration — the unnamed middle case** | cross-principal drain — **R13's domain** |

**PATH-DEPENDENT-JOINT** is a third temporal kind, neither of the above: not a
function of `s^T`, and not a sum (e.g. `max_t` of a per-state quantity).

## 3. The propositions to prove or refute

**P1 (classification is a partition).** Every joint quantity falls in exactly
one of {INSTANTANEOUS-JOINT, CUMULATIVE-JOINT, PATH-DEPENDENT-JOINT} under the
criterion: *(i)* is it a function of `s^T`? if yes → instantaneous; *(ii)* else
is it `Σ_t g(s^{t-1},a^t)`? if yes → cumulative; *(iii)* else path-dependent.
**This is near-trivial as a partition; the claim with content is that the three
cells have DIFFERENT guard-theoretic consequences.** If they do not, the
taxonomy does not carve the space and I will say so.

**P2 (instantaneous-joint is inductively checkable under SERIALIZED
execution).** If `h` is a function of `s`, then `P(s) ≡ h(s) ≤ κ` is maintained
by a guard admitting `a` only when `h(apply(s,a)) ≤ κ`. Predicted **TRUE**,
by trivial induction. Its purpose is to isolate concurrency as the sole
remaining suspect.

**P3 (THE DECISIVE PROPOSITION).** *An inductive invariant over the joint state
bounds aggregate harm without serialization, provided the invariant's evaluation
partitions along the action axis.*
I will prove or refute this and, in doing so, answer the crux:
**does a global READ-SET serialize the way a global WRITE-SET does?**

**P4 (path-dependence reduces by augmentation).** `max_t h(s^t)` is reducible to
an instantaneous quantity over an augmented state carrying a max-so-far
register. **Second half, which is the part that matters:** the register is
itself monotone across the joint trajectory, so if it is a single shared cell it
has a conflict set of size one and serializes — making the reduction *legal but
worthless*. Predicted TRUE for both halves.

**P5 (R13's scope).** R13's counterexample inhabits **CUMULATIVE-JOINT**
specifically. Its impossibility is scoped to that cell unless P3 is refuted for
a reason that also applies to instantaneous quantities.

## 4. GATE 0c — FEASIBILITY CEILING, measured under the mechanism's own dynamics

Measured with `F0` (no guard) over all 5 adversaries × M∈{2,3} × N∈{1,2,4} ×
{serialized, concurrent}, 12 rounds:

| M | initial concentration | DEFINED attainable range | UNDEFINED observations |
|---|---|---|---|
| 2 | 0.5000 | **[0.5000, 1.0000]** | 8/360 (0.022) |
| 3 | 0.3333 | **[0.3333, 0.7500]** | 0/360 |

**UNDEFINED is a real category, not a value of 1.0.** When every principal's
total reaches 0 (all value sent to EXTERNAL) the ratio has no denominator. My
first probe returned `1.0` there, conflating "maximally concentrated" with "no
longer defined" — the error-as-value species, caught in Gate 0c and fixed before
any threshold was chosen. Concentration is UNDEFINED when the denominator is 0,
such rounds are excluded from concentration statistics, and the exclusion count
is reported.

**Threshold κ (concentration bound), fixed now: κ = 0.60.**
Admissible window `(0.50, 0.75)`:
- `κ > 0.50` — else the bound is violated at `s_0` for M=2 and every result is
  definitional;
- `κ < 0.75` — else it is unreachable at M=3 and "0 violations" is definitional.

Exceedance under F0 at κ = 0.60: **M=2 → 0.068, M=3 → 0.0167** (6 observations).
**M=3 is thin and may return INCONCLUSIVE for the concentration cells; this is
stated now rather than discovered later.**

**θ (cumulative control) = `E.THETA` = 0.10**, R13's own value, unchanged.

**The F0 range is a REFERENCE, not a ceiling.** Guards change the trajectory, so
guarded play can leave it in either direction. This is R13's fourth
feasibility-ceiling defect (its ratio reached 1.263 above a 0.90 "ceiling") and
the lesson is applied here by refusing to treat the F0 envelope as a bound.

**Throughput ratio** (guarded admitted / F0 admitted) lies in `[0, 1]`
analytically, since a guard can only remove admissions. Given exceedance rates
of 1.7–6.8%, **the throughput floor is expected to be NON-BINDING for
concentration and BINDING for the cumulative control.** A ratio of exactly 1.0
means the guard never blocked and is DEFINITIONAL, not a success.

## 5. Numerical verification plan

Environment `env_aggregate.py` (R13's env imported read-only; aggregate
quantities added), guards `guards_aggregate.py`, both deterministic, `SEED = 1`.

Quantities, one per class:
- **INSTANTANEOUS-JOINT** — `concentration(s)`: max principal share of total.
- **CUMULATIVE-JOINT** — `cross_drain(τ)`: R13's cross-principal drain. **This
  is the CONTROL and is R13's own result. It must NOT be counted as independent
  replication.**
- **PATH-DEPENDENT-JOINT** — `peak_concentration(τ)`: running max.

Cells: class × {LOCAL, PARTITIONED-READ, GLOBAL-READ} × M∈{2,3} × N∈{1,2,4} ×
{serialized, concurrent} × 5 adversaries.

Reported per cell, always together: **violation COUNT** over `(round, quantity)`
pairs (never a binary — R10's binary was a stated limitation), **throughput**,
**blocked-action count**, and **UNDEFINED-round count**.

**B4 read-set experiment.** GLOBAL-READ (each guard reads all M principals'
live balances at admission) vs PARTITIONED-READ (own state + a *committed*
bound published by others, never a live read). If GLOBAL-READ composes and
PARTITIONED-READ does not, the global read-set is load-bearing and a
concentration invariant needs a consistent joint snapshot — **which is a
serialization point under another name, and will be stated as such.**

## 6. Decision rule

- **AGGREGATE-IS-CUMULATIVE** — all three classes reduce to cumulative; R13
  applies universally; aggregate harm evaluates only at a serialization point.
- **AGGREGATE-SPLITS** — instantaneous-joint bounded by an inductive invariant
  without serialization (0 violations, concurrent, all M and N, throughput ratio
  ≥ 0.50) while cumulative-joint is not.
- **AGGREGATE-IS-HARDER** — instantaneous-joint fails to compose for a reason
  **distinct from R13's accumulation argument** (e.g. the global read-set).

Any cell driven by a single quantity, M, or N → **INCONCLUSIVE for that cell**.
Any violation count of exactly 0, throughput ratio of exactly 1.0, or
proposition verifying exactly → **diagnose the coupling before reporting**.

## 7. Point predictions, with a prior

| outcome | prior |
|---|---|
| AGGREGATE-SPLITS | 0.50 |
| **AGGREGATE-IS-HARDER** | 0.30 |
| AGGREGATE-IS-CUMULATIVE | 0.20 |

**My own prediction, stated to be scored against:** I expect
**AGGREGATE-IS-HARDER** to be likelier than the 0.30 the prompt assigns, because
of the ratio observation in §1 — a concentration bound can be violated by an
action of a principal *other than* the one whose share rises, so no local guard
owns the quantity it is protecting. I predict P3 is **REFUTED** for concentration
under concurrency, P2 TRUE, P4 TRUE in both halves, P5 TRUE.

**AGGREGATE-IS-HARDER is a SUCCESS, not a failure**, and will not be softened:
it would establish that requirement four needs a mechanism that does not exist.

## 8. Tests that must pass before any result is trusted

`test_aggregate.py`: harm independence (no guard import in the environment;
source inspection over every aggregate quantity; identical scores under all
guard configs); class membership (concentration invariant under trajectory
reordering ending in the same state; cross-drain not; peak ≠ current on a
spike-and-return); composition failure detectable (hand-built joint state where
every local check passes and the aggregate invariant is violated); read-set
(source-level check that PARTITIONED-READ reads no other principal's live
state, **with a negative control proving the check can fail**); moving frame
(artifact #13 — a cumulative aggregate must name an immutable origin; a frame
re-based per round is rejected).

## 9. What this cannot establish

Analytic plus simulation over a hand-designed action vocabulary and hand-chosen
quantities, M ≤ 3, N ≤ 4. **It says nothing about WHICH aggregate harms real
multi-agent systems exhibit.** That is the empirical question CooperBench would
answer and this route deliberately does not substitute for it.
