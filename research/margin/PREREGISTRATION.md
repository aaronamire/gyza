# R-M1 — the margin route: preregistration (Gate 0)

**Committed before any experiment code exists.** Nothing else is in this
directory. **Zero credits**; deterministic, no model call.

---

## 0. Why this route exists, and what it is not

The escrow route closed with a correction that matters more than its findings
(`research/escrow/CORRECTION_E1_PARTITIONED.md`). `PARTITIONED_READ` — the one
admission discipline that survives many concurrent writers — works **only by
admitting exactly to the bound**. It drives concentration to κ and holds it
there: at M = 512 the trajectory settles at κ − 4.8e-10, at M = 64 at
κ + 5.6e-9. Whether that reads as 0% or 98% violations is decided by a 1e-9
tolerance, not by the guard.

> **A guard that admits optimally leaves zero margin, so its measured adequacy is
> a property of the arithmetic rather than of the design.**

Every real deployment carries jitter orders of magnitude above 1e-9. So the
question is not *whether* a local check can bound an aggregate — it can, at
exactly the boundary, uselessly — but **how far inside the bound it must run,
and what that costs.**

**This route is not a re-run of AG-3, R13, or escrow.** Those asked whether the
box is sound (it is, single-threaded), whether reservation repairs it (it does
not, above M = 3), and whether escrow converts transfer to extinction (it
converts realized loss to forgone gain). None of them varied the margin. δ has
been fixed at 0 in every cell this program has ever run.

## 1. The question

> **How much margin δ must a local admission check leave below an aggregate
> bound κ to stay sound under staleness ε — and how does δ\*(ε, M) scale?**

The answer decides whether planetary aggregate alignment is mechanizable, because
"beneficial = aggregate alignment" is a **cross-principal ratio**, and that is
exactly the many-writer regime where every single-writer mechanism this program
has validated stops working.

## 2. The geometry, derived and verified BEFORE any run

From `env_aggregate.box_bounds`: `L(κ) = U(1−κ)/(κ(M−1))`, `U = 20`, κ = 3/5.
The guard is given margin δ by enforcing the box for `κ′ = κ − δ`.

**(a) The margin the floor buys — an exact identity.**

```
L(δ) − L(0)  =  U·δ / [ (M−1)·κ·(κ−δ) ]
```

**(b) The feasibility ceiling — exact.** The box is empty (`L(δ) > U`, nothing
admissible at all) once

```
δ  ≥  κ − 1/M
```

verified exactly: `L = U` precisely at `δ = κ − 1/M`. **Available margin grows
with M**: 0.100 at M=2, 0.475 at M=8, 0.598 at M=512.

**(c) The closed-form prediction.** If Δ is the staleness-induced error — the
other-caused change to one principal's total over ε rounds — then safety needs
`L(δ) − L(0) ≥ Δ`, giving

```
δ*  =  Δ(M−1)κ² / (U + Δ(M−1)κ)  =  κ·x/(1+x),   x = κ(M−1)Δ/U
```

**Required margin also grows with M.** Which of (b) and (c) wins is precisely
the empirical question, and it turns on whether **Δ shrinks with M** — i.e. on
whether concurrent activity scales with population. That is why activity is a
preregistered factor and not an assumption.

**These three are predictions, not machinery.** Standing rule: a closed form is
validated case-by-case against ground truth, and **disagreement is a finding,
never patched**. The simulator is ground truth; §2c is on trial with everything
else.

## 3. Prior art, so novelty is not overclaimed

- **Escrow (O'Neil, TODS 1986)** — commutative, single-sided, "incremental
  changes to aggregate quantities." Measured dead above M = 3 for this quantity.
- **Demarcation (Barbará & García-Molina, VLDB J 1994)** — coordination-free
  local limits from a global constraint; **linear arithmetic only**, and the
  authors state they "have difficulty envisioning more complex constraints."
  Concentration is a **ratio**, not linear.
- **I-confluence (Bailis, PVLDB 2014)** — necessary *and* sufficient for
  coordination-free execution; the analysed table contains **no cross-principal
  aggregate and no ratio**.
- **Guard bands / safety margins** are standard in control and in real-time
  scheduling. **Nothing about leaving margin is new.** What is untested is
  δ\*(ε, M) *for a cross-principal ratio under stale local admission*, and
  whether the available margin (2b) outruns the required margin (2c) as M grows.

## 4. Environment — exact rational arithmetic, harm computed by the environment

**EXACT ARITHMETIC IS A PRECONDITION, not a refinement.** This program has now
recorded **five** float-boundary artifacts, and I misdiagnosed the last two as
structural — once as a "seed effect," once as a scaling trend. Both readings
were the flattering one. A margin study *is* a boundary study, so every quantity
is `fractions.Fraction` and every comparison is exact. **There is no tolerance
parameter anywhere in the instrument**, which removes that entire defect species
by construction rather than by care.

The exact box has been checked against the committed float `box_bounds` at
M ∈ {2,4,8,64,512} and agrees to < 1e-12. **The committed environments are not
modified.**

**Gate 0 (harm independence).** `concentration` is a pure function of
environment state; the module imports no guard. **UNDEFINED is not a value**
(`env_aggregate` GATE 0c): when the federation total reaches 0 concentration
returns `None`, and those rounds are **counted and excluded, never scored as
either safe or violating.**

**Factors.**

| factor | levels |
|---|---|
| M | 2, 8, 64, 512 |
| ε (staleness, rounds) | 0, 1, 2, 4 |
| activity | `FIXED_COUNT` (3 principals act/round, any M) · `FIXED_FRACTION` (all act) |
| n (agents per principal) | 1, 4 |

**Population.** A fraction of principals are adversarial (shed to whatever the
guard admits); the rest are honest (attempt a legitimate bounded shed and are
refused if the guard says no). Both are needed: a route measuring only the
adversary would report containment without permissiveness.

## 5. Measures

**Harm — environment-computed, guard-blind:**
- `violations` — rounds with `concentration > κ`, **exact rational comparison**.
- `undefined_rounds` — excluded and reported (GATE 0c).
- `peak_concentration` — exact.

**Cost — the counter-metric, mandatory beside every δ\*:**
- `honest_refusal_rate` — honest attempts refused ÷ honest attempts.
- `admitted_volume` — total admitted shed, against the δ = 0 baseline.

> A guard at δ = κ − 1/M admits nothing and has perfect containment. **δ\*
> reported without `honest_refusal_rate` would be exactly the AG-3 defect this
> program already recorded** — a throughput cost mistaken for evidence of work.

**Δ — measured, not assumed:** the environment records the max other-caused
change to any principal's total over ε rounds, so §2c is tested against a
measured Δ rather than a fitted one.

## 6. Search procedure and its resolution

δ is searched on an **absolute** grid of `g = 1/200 = 0.005`, two-stage: a coarse
scan at `1/40` recording the **full violation-vs-δ curve**, then refinement
within the bracketing interval.

**The full curve is recorded because monotonicity of violations in δ is
ASSUMED BY BISECTION AND HAS NEVER BEEN CHECKED.** If it is non-monotone, every
bisection result in this route is wrong, and that is a finding rather than a
nuisance. `δ*` is defined as the **smallest grid δ with zero violations across
all seeds**, which is correct even under non-monotonicity.

Seeds 5, rounds 40. Reported, so the trajectory-length confound that E1 found
(partitioned looked safe at 40 rounds and reached 0.98 at 1000) is checkable: a
**duration control at 200 rounds** runs on the δ\* cells.

## 7. Decision rules, with feasibility ceilings checked BEFORE the run

| rule | threshold | ceiling | trivially satisfiable? |
|---|---|---|---|
| **M-GROWTH** | δ\*(512) > δ\*(8) + 2g | δ\* ∈ [0, κ−1/M); ranges differ per M (0.475 vs 0.598) — **dynamic range is compressed, stated now** | No |
| **M-DECAY** | δ\*(512) < δ\*(8) − 2g | as above | No |
| **M-FLAT** | neither | — | It is the default; reported as such, never as a positive result |
| **INFEASIBLE** | δ\* ≥ κ − 1/M in any cell | — | No — means **no margin suffices**: the box is empty before it is safe |
| **COST** | `honest_refusal_rate` at δ\* reported for every cell | [0,1] | Not a bar; a reporting obligation |
| **THEORY** | measured δ\* within 1 grid step of §2c | — | No |

**The comparison is ADDITIVE against 2g, deliberately.** E1-HOLDS was a ratio
rule whose baseline came out exactly 0.000, making it unscorable — the fourth
instance of standing rule #4 and the first where the unchecked ceiling was the
rule's **denominator**. An additive rule is well-defined at a zero baseline. The
ratio is reported additionally, when defined.

**ε = 0 is the control column** and δ\* there is expected to be exactly 0
(§8, P-M0). If it is not, the instrument is broken and no other cell is read.

## 8. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-M0** | at ε = 0, δ\* = **exactly 0** | **YES, and DEFINITIONAL** — with no staleness the admitted value is the true value. Flagged in advance (rule #2); a clean zero here is the control working, not a result. |
| **P-M1** | under `FIXED_FRACTION`, **M-GROWTH** | **YES** — Δ per principal stays roughly constant when activity scales with population, so x ∝ M and δ\* → κ |
| **P-M2** | under `FIXED_COUNT`, **M-FLAT** | **YES** — a fixed number of actors spreads a fixed disturbance over M principals, so Δ ∝ 1/M and x is constant |
| **P-M3** | §2c predicts measured δ\* within one grid step | **YES**, and it is the risky one: it assumes worst-case Δ is the binding quantity, when the trajectory may never realise the worst case |
| **P-M4** | `honest_refusal_rate` at δ\* exceeds 10% wherever δ\* > 0 | **YES** — margin is bought directly out of permissiveness |
| **P-M5** | δ\* is monotone non-decreasing in ε | **YES** — weakly, and a violation would indicate a non-monotone instrument |

**If P-M1 and P-M2 both hold**, the governing condition is named: *a planetary
aggregate is boundable by local checks iff concurrent activity per principal
falls as the population grows.* In a planetary system it does not — which would
make hierarchical or partitioned aggregates the only route, and that is a
different architecture, not a tuning of this one.

## 9. What this route cannot establish

1. **One aggregate.** Concentration is a two-sided ratio over a conserved total.
   Other aggregates (sums, maxima, unconserved quantities) are not covered.
2. **Uniform staleness.** Real staleness is per-observer and asymmetric.
3. **Simulated principals.** No real agents, no real humans, no real market.
4. **Exact arithmetic removes float artifacts from the INSTRUMENT**, not from any
   deployment. A real system's jitter is the thing δ is being measured against.
5. **Nothing about correctness.** Consequence only; the competence bound
   (`research/COMPETENCE_BOUND.md`) is untouched and remains terminal.
6. **δ\* is a property of this environment's Δ**, and Δ is a modelling choice.
   §2c is the transferable claim; the numbers are not.
