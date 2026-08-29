# R-EVID Part C — the reflection criterion

**Analytic. No data.** Subsumes Part A (`c968d0c`) and the criterion measured in
Part B (`f9e02ef`): both are special cases of one condition.

---

## 0. The claim in one line

> **A safety quantity is boundable if and only if its fold has non-positive
> drift under benign behaviour and is reflected at zero. Every mechanism that
> has ever fixed such a bound — a zero benign rate, physical reversal, a
> sequential detector — is the same mechanism obtained three different ways.**

## 1. One recursion

Every accumulating safety quantity in this codebase, and every proposed repair
to one, has the form

```
Q(0) = 0            Q(n+1) = max(0, Q(n) + hₙ − cₙ)          alarm when Q > L
```

`h` is the harm increment, `c` the **compensation**, and `max(0, ·)` the
**reflection**. This is Lindley's recursion; `Q` is the waiting time of a
G/G/1 queue. What distinguishes the four mechanisms is only how `c` is obtained
and whether the reflection is present:

| mechanism | `c` | reflected | drift `E[h − c]` |
|---|---|---|---|
| cumulative bound over an immutable origin | `0` | no | `+b` |
| **H4** — benign rate zero | `0` | — | `0` (and `Q ≡ 0`) |
| **physical reversal** (tombstone, deletion, refund) | `r` | yes | `b − r` |
| **sequential detector** (CUSUM reference value) | `k` | yes | `b − k` |

> **CUSUM subtracts a reference value; reversal subtracts a real event. The
> recursion cannot tell them apart, and neither can the mathematics.** Part A §3
> treated the sequential detector as an alternative to a reversible quantity.
> They are the same construction.

## 2. Theorem 5 — the drift criterion

Let `δ = E[h] − E[c] = b − c̄` be the benign drift.

> **(i) `δ > 0`, no reflection** — `Q(n) → ∞` deterministically; alarm at
> `⌈L/b⌉` with probability 1. **A timer.** (Part A, Theorem 2.)
>
> **(ii) `δ > 0`, with reflection** — reflection cannot save a positive drift.
> `Q(n) → ∞` a.s.; still a timer, merely a slower one.
>
> **(iii) `δ = 0`** — null recurrent. `Q` is unbounded in probability
> (diffusive growth). Still not a bound. **The degenerate exception is `b = 0`
> with `c = 0`, where `Q ≡ 0` and no alarm is possible at any `L`** — this is
> H4, and it is sound not because the drift is zero but because the walk never
> takes a step.
>
> **(iv) `δ < 0`, with reflection** — positive recurrent. `Q` has a stationary
> distribution and `P(Q > L) ≍ e^{−θL}`, with `θ` the Lundberg exponent solving
> `E[e^{θ(h−c)}] = 1`. **A bound.**

*Proof sketch.* (i) is arithmetic. (ii)–(iv) are the standard classification of
the reflected random walk: by the SLLN `Q(n)/n → δ`, so `δ > 0` gives transience
and `δ < 0` positive recurrence; the geometric tail in (iv) is
Cramér–Lundberg / Kingman. ∎

**Corollary 5.1 — the false-alarm rate is the whole story.**

| case | `P(false alarm)` | time to it |
|---|---|---|
| cumulative bound | **1** | `⌈L/b⌉`, deterministic |
| reflected, `δ < 0` | `≍ e^{−θL}` | `≍ e^{θL}` |

Raising `L` on a cumulative bound buys benign lifetime **linearly**. Raising it
on a reflected negative-drift fold buys it **exponentially**. That is Part A
§3's claim, now derived rather than asserted, and it holds for reversal exactly
as it holds for CUSUM.

## 3. Theorem 6 — reversal is a CAPACITY, not a feature

The practically important half of (ii).

> **Adding a reversal operation does not make a quantity boundable. It makes it
> boundable only if the reversal rate strictly exceeds the harm rate:
> `E[r] > E[h]`. A reversal that cannot keep up leaves a timer.**

`δ = b − r` is negative iff `r > b`. So a delete button, a refund path, a
garbage collector or a retention policy is a **capacity claim** about the
system, and it is falsifiable by measurement: compare the rate at which the
quantity is created against the rate at which it is reversed.

**Corollary 6.1 — the recommendation R-EVID Part B §8 made is insufficient as
stated.** Part B concludes H5 "needs a reversal that is an appended fact." True
and not enough: a tombstone with `r < b` yields case (ii), a slower timer.
**The tombstone must be paired with a measured reversal capacity**, and Part D
measures whether Gyza has one.

**Corollary 6.2 — where reversal is human-mediated, its capacity is `H`.** If
an artifact can only be released by a human decision, then `r ≤ H`, and
stability requires `b·λ < H` for action rate `λ`. This has the same shape as the
planetary program's `N ≤ H·A/[(1−p)(1−c)]`: **the action rate is bounded by
reversal capacity divided by harm per action.** Stated as a structural
correspondence, not an identity — the planetary derivation has its own
assumptions (`PROGRAM.md` §1.2) and this does not re-derive them.

## 4. The trichotomy, as a corollary

Part B's `H-ZERO` — sound iff benign rate is zero or the quantity is a
decrementable stock — is Theorem 5 restricted to the two ways of obtaining
non-positive drift. Part C adds the third (an artificial reference value), the
missing stability condition on the second (Theorem 6), and the reason all three
work (reflection).

**A cumulative safety bound is therefore exactly one of:**

1. **Sound-by-silence** — benign behaviour never increments it (`b = 0`). H4.
2. **Sound-by-capacity** — reversal outpaces harm (`r > b`), reflected.
3. **Sound-by-detection** — a reference value is subtracted (`k > b`),
   reflected. Bounds the *rate*, not the total.
4. **A timer** — everything else.

**Nothing else is available**, because the four cases exhaust the sign of the
drift.

## 5. What this does not do

- It does not escape irreversibility. Cases 2 and 3 bound a *stationary* or
  *rate* quantity; **bounded total irreversible harm over unbounded lifetime
  remains unavailable** (Part A §5), and case 1 achieves it only by never
  incurring the harm at all.
- The tail in (iv) is asymptotic. At small `L` the geometric approximation is
  poor, which is exactly the regime where Part B measured CUSUM losing to the
  level at `ρ ≤ 1.2`.
- `h` and `c` are assumed to have finite mean and, for the Lundberg exponent, a
  finite moment generating function. **Heavy-tailed harm breaks the exponential
  tail** and gives only a power law — and this program has already measured
  heavy tails in consequence (`COMPETENCE_BOUND.md` §4 records 0.56–0.59 of
  consequence held under heavy tails). **Part D must check which regime Gyza's
  quantities are in rather than assuming the light-tailed one.**

## 6. What is and is not new

**Classical, and cited:** Lindley's recursion (1952); the drift classification
of reflected random walks; Cramér–Lundberg and Kingman's bound; CUSUM (Page
1954) and its optimality (Lorden 1971; Moustakides 1986).

**The contribution:**

1. The identification that agent-safety budgets *are* this object, so their
   failure mode is determined by the sign of one number rather than by the level
   chosen.
2. That the three known repairs are one mechanism — reflection with negative
   drift — obtained physically, structurally, or statistically.
3. **Theorem 6**: reversal is a capacity claim and is falsifiable. A reversal
   operation that cannot keep up is not a fix.
4. The classification's exhaustiveness: four cases, nothing else.
