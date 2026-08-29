# R-M1 — the margin route: findings

**Preregistration:** `PREREGISTRATION.md`, committed `0a43d7d` as the only file
in this directory, BLAKE3
`ff43eb54fc034c472c2e995ed36e149d3db8f25145c97b993b4f351eb1b73339`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic, no model
call.

**Verdict: `MARGIN-GROWS-WITH-M-AND-RUNS-OUT`, with a second, sharper result:
`ACTIVITY-IS-THE-CONTROL-PARAMETER`.**

---

## 1. The three results

**(1) `M-GROWTH` — the required margin grows with M, and at planetary scale it
exceeds what the bound has to give.** Under `FIXED_FRACTION` activity, δ\* rises
from 0.130 (M=8) to 0.295 (M=512) at ε=1, and from 0.190 to 0.480 at ε=2. At
ε=4 and M=512, **no margin below the feasibility ceiling is safe at all** — the
box empties before it becomes sound. Same at M=512 for every n=4 cell.

**(2) `ACTIVITY-IS-THE-CONTROL-PARAMETER`, not scale.** Under `FIXED_COUNT`
activity — three principals acting per round regardless of M — the aggregate
**cannot be moved at all** at M ≥ 64, at any staleness tested, **including at
1000 rounds**. Measured Δ falls as ≈1/M (2.54 → 0.449 → 0.058 for M = 8 → 64 →
512) exactly as predicted, while under `FIXED_FRACTION` it is flat (4.38 → 5.13
→ 5.18). Concurrency per principal, not population, decides whether a
cross-principal aggregate is boundable.

**(3) Margin is not a dial. It is a step function.** The violation curve is
`185 185 185 … 185 0` — flat across every sub-threshold margin, then zero in one
grid step. **Below δ\*, margin buys literally nothing.** Partial margin is
wasted capital.

---

## 2. δ\* — the measured margins

`FIXED_FRACTION`, κ = 0.60, grid g = 0.005, 5 seeds × 40 rounds.
Ceiling is the exact `κ − 1/M` at which the box is empty.

| M | ceiling | ε=1 | ε=2 | ε=4 |
|---|---|---|---|---|
| 2 | 0.100 | *unreachable* | *unreachable* | *unreachable* |
| 8 | 0.475 | **0.130** | **0.190** | **0.225** |
| 64 | 0.584 | **0.280** | **0.480** | **0.535** |
| 512 | 0.598 | **0.295** | **0.480** | **INFEASIBLE** |

(n = 1. With n = 4 agents per principal, δ\* is 0.240–0.550 at M ≤ 64 and
**INFEASIBLE at every M = 512 cell.**)

**M = 2 is structurally unreachable and is not scored.** With one other
principal and self-caused change known, there is no other-caused change inside a
round, so Δ = 0 **exactly** and no staleness exists to defend against. This
reproduces the escrow route's M = 2 result from an independent instrument.

### Decision rules

| rule | result |
|---|---|
| **M-GROWTH** (δ\*(512) > δ\*(8) + 2g) | ε=1: 0.295 > 0.140 ✓ · ε=2: 0.480 > 0.200 ✓ · ε=4: infeasible ✓ — **HOLDS** |
| **M-DECAY** | refuted |
| **INFEASIBLE** (δ\* ≥ κ − 1/M) | **fires** at M=512/ε=4/n=1 and at every M=512/n=4 cell |
| **THEORY** (closed form within 1 grid step) | **REFUTED** — see §4 |
| **COST** | reported, §3 |

---

## 3. What the margin costs — and why the obvious metric misleads

Two cost measures disagree in direction, and reporting either alone would
misstate the result.

| M | ε | δ\* | floor L(δ\*) | **floor inflation** vs L(0) | **retention forced** |
|---|---|---|---|---|---|
| 8 | 1 | 0.130 | 3.22 | 1.69× | 16.1% |
| 64 | 1 | 0.280 | 0.675 | 3.19× | 3.4% |
| 512 | 1 | 0.295 | 0.089 | 3.42× | **0.4%** |
| 64 | 4 | 0.535 | 4.57 | 21.6× | 22.8% |
| 512 | 2 | 0.480 | 0.287 | 11.0× | 1.4% |

> **δ\* climbing toward the ceiling sounds catastrophic and mostly is not.** δ\*
> lives in κ-space; what an agent actually experiences is the floor L, and L(δ\*)
> **falls** with M. At M = 512, ε = 1 a principal must retain 0.4% of its
> endowment and may divest 99.6%. The margin is expensive in the bound's units
> and cheap in the agent's.

**`honest_refusal_rate` was 0.0000 in every n=1 cell and 0.45–0.57 at n=4.** The
zeros are real but weak evidence: honest principals were given a demand of 1% of
endowment per round, so over 40 rounds they seek to divest 40% and never
approach a floor of 3.4% or 22.8%. **P-M4 is refuted as stated, and the
refutation is partly an artifact of a parameter I chose** — which is why
retention/floor-inflation, which is parameter-free, is the cost measure of
record. Disclosed rather than quietly replaced.

---

## 4. The closed form is a loose bound — and it fails in the unsafe direction exactly where it matters

Preregistration §2c predicted `δ* = Δ(M−1)κ²/(U + Δ(M−1)κ)` from measured Δ.

| cell | measured δ\* | predicted | |
|---|---|---|---|
| M=8, ε=1 | 0.130 | 0.287 | conservative |
| M=64, ε=1 | 0.280 | 0.544 | conservative |
| M=512, ε=2 | 0.480 | 0.593 | conservative |
| **M=512, ε=4** | **INFEASIBLE (> 0.598)** | **0.594** | **UNDER-predicts** |

**Conservative in 10 of 11 scorable cells, by roughly 2×** — because the box is a
*sufficient* condition for `concentration ≤ κ`, so sizing margin to keep every
principal inside the box demands more than the aggregate actually needs. That is
the failure mode P-M3 flagged in advance.

**But it under-predicts in the one cell where the answer is "no margin works."**
A designer using §2c would compute 0.594, see it under the 0.598 ceiling, and
conclude the configuration is safe. It is not. **The closed form's error changes
sign precisely at the feasibility boundary**, which is the worst place for a
bound to stop being a bound. Use it as a *lower* bound on the margin required,
never as a certificate.

---

## 5. Instrument validation — every preregistered control ran

| control | result |
|---|---|
| **P-M0** (ε=0 ⇒ δ\*=0, definitional) | **holds exactly** at M ∈ {2,8,64,512}: 0 violations, Δ = 0 **exactly** |
| **Monotonicity of violations in δ** | **0 non-monotone cells of 48.** Bisection would have been valid — now checked rather than assumed |
| **Duration control** (200 and 1000 rounds at δ\*) | **every δ\* holds.** This is the confound that killed E1's partitioned claim; it does not bite here |
| **Seed robustness** (5 → 20 seeds at δ\*) | **every δ\* holds** |
| **Reachability** | M=2 unreachable everywhere; `FIXED_COUNT` unreachable at M ≥ 64 **even at 1000 rounds** — genuinely unreachable, not merely slower |
| **GATE 0c** (UNDEFINED ≠ value) | 0 undefined rounds in every scored cell — and the state is **unreachable by divestment**, see below |
| **Exact box vs committed float `box_bounds`** | agrees to < 1e-12 at M ∈ {2,4,8,64,512} |

**A cross-instrument confirmation, found by a test I wrote wrong.** I asserted
that divesting every principal's total drives the federation to UNDEFINED. It
does not: `claim = contrib · pool / funded`, and withdrawal never reduces
`contrib`, so each withdrawal takes only a pro-rata share and the pool decays
geometrically (24 → 18 → 13.5 → 10.1 → 7.6 at M=4). **A principal cannot reach
zero total while the pool holds anything.** This is the escrow route's §2.6
reproduced by an independent instrument built afterwards — two transcriptions of
`env_federation`'s arithmetic, agreeing on a property neither was built to test.
It also explains the 0 undefined rounds: the state is unreachable, not merely
rare.

**There is no tolerance parameter anywhere in this instrument.** State is integer
nano-units and every comparison is exact integer arithmetic. The five
float-boundary artifacts this program has recorded — two of which I misdiagnosed
as structural — are unreachable here by construction rather than by care.

---

## 6. Predictions, scored

| | prediction | outcome |
|---|---|---|
| **P-M0** | δ\* = exactly 0 at ε=0 | **CONFIRMED, definitional as flagged.** The control works. |
| **P-M1** | `FIXED_FRACTION` ⇒ M-GROWTH | **CONFIRMED** at every ε |
| **P-M2** | `FIXED_COUNT` ⇒ M-FLAT | **UNSCORABLE AS STATED, mechanism CONFIRMED.** δ\* does not exist because the attack is unreachable — a stronger result than flatness, but *not the rule I wrote*. The mechanism behind it was verified directly: Δ ∝ 1/M as predicted. |
| **P-M3** | closed form within 1 grid step | **REFUTED** — off by ≈2×, and sign-flipping at the feasibility boundary (§4) |
| **P-M4** | honest refusal > 10% wherever δ\*>0 | **REFUTED** at n=1 (0.0000), confirmed at n=4 (0.45–0.57). Partly an artifact of the honest-demand parameter; see §3 |
| **P-M5** | δ\* monotone non-decreasing in ε | **CONFIRMED** in every cell (M=8: 0.130→0.190→0.225; M=64: 0.280→0.480→0.535) |

---

## 7. Apparatus defects, found by controls before any data

Three, and **all three would have produced publishable-looking numbers.**

1. **Rotating roles.** The adversarial set was re-drawn every round, so a
   principal that shed to the floor in round *r* was "honest" at 0.21 in round
   *r+1* and refused for that reason alone. It reported **85–95% honest refusal
   at δ = 0** — the cost metric saturated before any margin existed.
2. **Staleness that was amnesia.** `seen − true` folded in the principal's own
   prior shedding, reporting **Δ at 17–19 of a 20-unit endowment**. A real agent
   knows its own writes. This contradicted the preregistration's own definition
   of Δ, and left uncorrected it would have made δ\* infeasible everywhere for a
   reason that has nothing to do with staleness.
3. **Containment and permissiveness measured on one population.** Honest
   principals that hold their position make concentration **unreachable** at
   large M — 32 principals holding 14 units each cannot let one reach 60% of the
   total. A larger honest population silently weakens the adversary. Split into
   separate populations, which is the ordinary TPR/FPR separation.

And one bug caught by an impossible value: **δ\* = −0.0200**. With δ = 0 already
safe, the refinement stepped *below* zero — negative margin, which is a
*stronger* guard, not a weaker one. It was reported for every unreachable cell.
Fixed by checking reachability first: **unreachable is not δ\* = 0**, and
recording it as 0 would have read as "no margin needed" — the reassuring
direction again.

---

## 8. What this means for the vision

The scaling equation `N ≤ H·A / [(1−p)(1−c)]` needs `c`, the contained fraction.
This route measured what `c` costs for a **cross-principal aggregate** — the
class "beneficial = aggregate alignment" actually lives in.

1. **Bounded aggregates are reachable at planetary M**, at ε ≤ 2 and one agent
   per principal, and the behavioural cost is small (0.4–1.4% retention).
2. **They run out.** At ε = 4, or with 4 agents per principal, **no margin
   suffices at M = 512.** The box empties before it becomes sound. Staleness and
   intra-principal concurrency, not population, are what exhaust it.
3. **The lever is activity, not scale.** Under bounded concurrent activity the
   aggregate could not be moved at all at M ≥ 64. This is the constructive
   finding: *rate-limit concurrent state change per principal and a
   cross-principal bound becomes enforceable by purely local checks.*

That last point is the first mechanism this program has found that makes a
many-writer aggregate locally boundable, and it costs throughput rather than
correctness. It is also **exactly the single-writer principle in continuous
form** — `FIXED_COUNT` does not make writers singular, it makes them *rare*, and
rarity is sufficient.

---

## 9. What this route cannot establish

1. **One aggregate.** Concentration is a two-sided ratio over a conserved total.
2. **Uniform staleness.** Real staleness is per-observer and asymmetric.
3. **Simulated principals.** No real agents, no humans, no market.
4. **Exact arithmetic removes float artifacts from the INSTRUMENT**, not from a
   deployment — a real system's jitter is what δ is measured *against*.
5. **`FIXED_COUNT` is an assumption about the world, not a mechanism.** Nothing
   here *enforces* bounded activity; this route shows only that if it holds, the
   aggregate is boundable. Building and testing that rate limiter is the next
   route, not this one.
6. **Nothing about correctness.** Consequence only; the competence bound is
   untouched and remains terminal.
