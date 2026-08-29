# R-EVID Part A — a cumulative bound is a timer, not a detector

**Analytic. No data, no preregistration required, and none of it depends on
Gyza.** Part B is the empirical route and is preregistered separately, after
this file is committed.

The results here are elementary. They are written down because this program
spent five routes discovering their consequences one at a time — H1's
retirement, H2's retirement, R-H3L's `Q-COUNT-DEAD`, H6's shape, and the
planetary program's inverted amortization factor are all the same theorem
observed from five directions.

---

## 0. Setting

An agent takes actions `1, 2, …`. Action `i` incurs harm `hᵢ ≥ 0` in a measured
quantity. The guard folds them:

```
Q(n) = Σᵢ₌₁ⁿ hᵢ        Q(0) = 0
```

The **origin is immutable**: `Q(0) = 0` is fixed at genesis and nothing the
agent does moves it. This is not an incidental choice — artifact #13 was bought
by an origin the agent could advance by acting, and `CLAUDE.md` standing rule #6
makes immutability binding. Every registered cumulative class in Gyza has this
shape (`gates.py:genesis_origin`, `origin_ns = 0`).

A **level** `L` refuses at the first `n` with `Q(n) > L`.

Two behaviours, each with a constant per-action harm rate:

- **benign**: `hᵢ = b > 0`
- **adversary**: `hᵢ = a ≥ b`

Write `ρ = a/b ≥ 1` for the **strength ratio** — how much louder the adversary
is per action, in the quantity actually being measured.

Two requirements:

- **Liveness(N)** — the benign agent completes `N` actions unrefused.
- **Containment(K)** — the adversary is refused by its `K`-th action.

## 1. Theorem 1 — the separation condition

> **A level `L` satisfying Liveness(N) and Containment(K) exists if and only if
> `ρ > N/K`.**

*Proof.* Liveness(N) holds iff `Q_benign(N) = Nb ≤ L`. Containment(K) holds iff
`Q_adv(K) = Ka > L`. Both hold iff `Nb ≤ L < Ka`, and such an `L` exists iff
`Nb < Ka`, i.e. `a/b > N/K`. ∎

**Corollary 1.1 (the degenerate case).** If `ρ = 1` — the measured quantity does
not distinguish the adversary at all — then no separating `L` exists for any
`N > K`.

**Corollary 1.2 (lifetime is bought with loudness).** For fixed `K`, the
maximum achievable benign lifetime is `N < Kρ`. **Lifetime is linear in the
strength ratio and nothing else.**

**Corollary 1.3 (unbounded lifetime is unavailable).** For fixed `K` and fixed
`ρ`, no `L` satisfies Liveness(N) for all `N`.

> This is exactly what R-H3L measured. Its rule fixed `N = 1000`, `K = 100`,
> giving a threshold of `ρ > 10` — and the sweep located the crossing between 2
> and 3 artifacts, at `ρ = 11.25`. **The measured threshold is `N/K`, not a
> property of Gyza.** `research/h3_level/FINDINGS.md` §3 reports the same
> identity from the data side.

## 2. Theorem 2 — the false-alarm probability is 1

> **Under a cumulative bound with an immutable origin and any `b > 0`, every
> benign agent is refused in finite time — at action `⌈L/b⌉`.**

*Proof.* `Q_benign(n) = nb → ∞`, so `Q(n) > L` for all `n > L/b`. ∎

Trivial, and it is the whole point:

> **A cumulative bound over an immutable origin is not a detector. It is a
> timer.** Its false-alarm rate is 1, its alarm time is `⌈L/b⌉`, and the only
> thing the adversary changes is how much earlier the timer fires.

Everything called "containment" under such a bound is the statement *this agent
has not yet run for `L/b` actions*. Calling that a harm bound is the label/
quantity confusion this program has now recorded four times.

## 3. Theorem 3 — the sequential test dominates, exponentially

The alternative is to test for a **change in rate** rather than accumulate the
raw quantity. Page's CUSUM (1954) over the same append-only log:

```
S₀ = 0        Sₙ = max(0, Sₙ₋₁ + hₙ − k)        alarm when Sₙ > H
```

with reference value `b < k < a`. Under benign the increment has negative mean
`b − k < 0`, so `Sₙ` is positive-recurrent and does not drift; under the
adversary the mean is positive and `Sₙ` climbs.

Classical results (Page 1954; Lorden 1971; Moustakides 1986 — CUSUM is minimax
optimal for detection delay at a given false-alarm rate; Siegmund 1985 for the
approximations):

| | benign lifetime before false alarm | detection delay |
|---|---|---|
| **cumulative level `L`** | `L/b` — **linear in `L`** | `L/a` — linear in `L` |
| **CUSUM threshold `H`** | `≈ e^{cH}` — **exponential in `H`** | `≈ H/(a−k)` — linear in `H` |

> **The tradeoff curve is linear for the level and exponential for the
> sequential test.** Raising `H` buys benign lifetime exponentially while paying
> for it in delay only linearly. Raising `L` buys lifetime and delay at a fixed
> exchange rate `ρ` that Theorem 1 says cannot be improved.

So the cumulative level is not merely suboptimal — it is dominated by a
statistic computable **from exactly the same log, with no new instrumentation**.
Gyza already has the log (`blackboard.egress_log`, append-only, per-event
`byte_count`).

**What this does NOT buy, stated because it is the honest limit.** CUSUM bounds
the *rate*. An adversary that holds its rate at or below `k` is never detected
and accumulates unbounded total harm over unbounded time. **Theorem 2's problem
is solved; the trilemma's third horn is not escaped.** Bounded total
irreversible harm over unbounded lifetime remains unavailable — see §5.

## 4. Theorem 4 — the evidence identity, and why the two arms are one

Wald's identity for a sequential test: the expected number of observations to
reach a log-threshold `log A` is

```
E[n] ≈ log A / D          D = KL(f_adv ‖ f_benign)
```

`D` is the **expected evidence per observation**, in nats.

For a binary detector with detection rate `q` and false-alarm rate `f`, the
per-observation log-likelihood ratio has expectation

```
D = q·log(q/f) + (1−q)·log((1−q)/(1−f))
```

whose leading term is `q·log(q/f)` — and `q/f` is precisely the statistic
`research/COMPETENCE_BOUND.md` §4 identified as the mechanism-relevant one:

> *"a mechanism that both deters lying and retains honest agents exists iff
> `LR = q/f ≥ g/w` … the likelihood ratio is [the decision-relevant statistic],
> not Youden's J."*

> **The competence bound and the containment work are measuring the same
> quantity: evidence per observation.** The competence bound measures it for
> semantic verification and finds `LR = 19.8` in-competence, `1.25` outside.
> R-EVID measures it for containment quantities. `log(19.8) = 2.99` nats;
> `log(1.25) = 0.22` nats — **an out-of-competence checker needs ≈13× more
> observations for the same confidence.**

**Corollary 4.1 — `Q-COUNT-DEAD` is a corollary of the competence bound's own
statistic.** R-H3L measured Q-COUNT at exactly 1.000 events per action for both
behaviours, i.e. `ρ = 1`, i.e. `q = f`, i.e. `LR = 1`, i.e. `D = 0`, hence
`E[n] = ∞`. **No bound, no detector, no budget and no amount of observation
separates them**, because the measurand carries zero evidence. Theorem 1's
Corollary 1.1 is the fixed-sample shadow of the same fact.

> **The unified statement.** *Containment and verification are both detection
> problems, and both are bounded by the evidence the measurand carries about the
> behaviour being detected. You cannot cheaply verify what you cannot understand
> (`D → 0` for semantics outside competence); you cannot bound what your
> quantity does not distinguish (`D = 0` for a count of sends).*

The two arms were motivated separately and ran years apart in program time — the
competence-bound arm was declared terminal on 2026-07-25, before any of the harm
model existed. The convergence was not engineered, which is the only thing that
makes it worth stating.

## 5. What remains impossible, and it is arithmetic

None of the above escapes the irreversibility trilemma. For genuinely
irreversible harm with a positive benign rate, **bounded total harm and
unbounded lifetime are incompatible**, because the total is a divergent sum. The
exits are exactly four:

1. bound the lifetime (declare a deployment horizon)
2. make the harm reversible — represent it as a **stock** that reversal
   decrements, which is why `H5_storage_growth` amortises ~3.5M actions for free
   while `H3` and `H6` cannot
3. bound the **rate** and accept unbounded total — Theorem 3, done optimally
4. renew authorisation from **outside** the agent — a human, or a verifier

(4) is the planetary program's `N ≤ H·A/[(1−p)(1−c)]`. That inequality is not a
scaling estimate; it is the statement that irreversible action is rationed by
external authorisation, and this program has measured both rationing channels.

## 6. What is and is not new here

**Not new, and cited as such:** sequential analysis (Wald 1945), CUSUM (Page
1954), its optimality (Lorden 1971; Moustakides 1986), Wald's identity. §3 and
§4 apply textbook results.

**The contribution is the application and the identification:**

1. Theorem 2 — that the immutable-origin cumulative bound, which safety
   engineering reaches for by default and which this codebase adopted for three
   of four harm classes, is a timer with false-alarm probability 1.
2. Corollary 1.2 — that lifetime under such a bound is linear in the strength
   ratio, so the bound's usefulness degrades linearly with the operating
   horizon demanded. Measured on production code in R-H3L.
3. Corollary 4.1 — that a registered, signed harm class of a real system had
   `D = 0`, so it could never have bounded anything, and that this is derivable
   from the same likelihood-ratio statistic the verification arm arrived at
   independently.
4. The design rule in §7.

## 7. The design rule

> **Choose the measurand by its evidence, then use the optimal test over it.
> A bound is not a design; the statistic is.**

Procedurally, for each harm class:

1. Measure `ρ` (or `D`) between benign and adversarial behaviour **in the
   quantity you propose to bound**. If `D = 0`, stop — no level is worth
   declaring and declaring one is how `H1` and `H2` were retired.
2. If the harm is reversible, represent it as a stock; the lifetime term
   disappears.
3. If it is irreversible, bound the rate with a sequential test, and declare the
   deployment horizon that converts the rate bound into a total.

Part B measures step 1 for every registered Gyza class.
