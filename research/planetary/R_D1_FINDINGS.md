# R-D1 — the escalation budget: **AMORTIZATION-IS-THE-BINDING-TERM**

**Derived, not measured.** Consequences of `N ≤ H·A / [(1−p)(1−c)]`, whose
assumptions are in `PROGRAM.md` §1.2. This establishes nothing empirical; it
converts a qualitative worry into a number and a target.

Predictions fixed in `PROGRAM.md` §6 before running. **One of the three was
wrong** — see §4.

---

## 1. The headline

At today's coverage, one human decision per action, H = 10⁴ reviews/day:

> ### N ≤ ~26,000 actions/day
>
> Planetary is 10⁹. **We are 4.6 orders of magnitude short.**

**P-D1b predicted "below 10⁶/day". Confirmed, by a further factor of forty.**

## 2. Neither lever alone is close, and they are nearly equally useless

Setting each axis to its worst case in turn:

| | ceiling |
|---|---|
| p as measured (0.556), **c = 0** | 22,500/day |
| **p = 0**, c as measured (0.133) | 11,538/day |

They differ by less than 2×. **Both are currently so far from 1 that neither
dominates** — there is no "just fix verification" or "just fix containment" story.

## 3. What planetary scale demands of each axis alone

Solving for 10⁹/day at H = 10⁴, A = 1:

| hold this fixed | the other must reach |
|---|---|
| p = 0.556 (measured) | **c ≥ 0.9999775** — four and a half nines of containment |
| c = 0.133 (measured) | **p ≥ 0.9999885** — five nines of verification |

Neither is plausible. And §6 of the sweep makes the asymmetry concrete: **with
p = 0.556, even c = 0.99 reaches only 2.25 M/day** — still 400× short — because
`(1−p) = 0.444` dominates the product.

## 4. A PREDICTION I GOT WRONG

**P-D1c said amortization is a *larger* lever than human capacity. It is not —
they are mathematically identical.** H and A enter the inequality as a product,
so 10× either yields exactly 259,615/day. The sweep says so directly and I had
asserted an asymmetry that does not exist.

**The correct statement**, which survives: they are equivalent in the arithmetic
and *not* equivalent in practice, because **H is bounded by hiring and A is
bounded by the harm bound.** One is a budget, the other is a design parameter.

Recorded rather than quietly amended, because the arithmetic corrected me and
that is the whole point of writing predictions down.

## 5. THE ACTUAL FINDING

Solve for A instead. At today's p and c, to reach 10⁹/day with H = 10⁴:

> ### A ≈ 38,500 actions per human decision

**That is not absurd.** It is roughly "one capability manifest safely covering
forty thousand actions" — and Gyza *already has that mechanism*. A manifest is
exactly one human decision constraining every action an agent takes under it.

So the framing changes:

> **Planetary scale is not blocked on five nines of verification or of
> containment. It is blocked on how many actions one human policy decision can
> safely cover — and nobody has ever measured that number.**

`A ≈ B / h̄` — the declared bound over mean harm per uncontained action. For H1
at B = 100 credits, A ≈ 100/h̄, so h̄ ≈ 0.0026 credits/action would suffice. That
is a **measurable quantity of the running system** and it has never been
instrumented.

## 6. The one lever that does not pay the competence bound

36.8% of action types are `REVERSIBLE_INTERIOR`, and **zero** have a per-action
undo. Moving an action into the interior raises c **without requiring anything
to be verified** — the only lever in the equation that escapes the competence
bound entirely, because a reversible action needs no truth condition.

That makes **R-B4 (widen the interior)** cheaper per unit of scale than any
verification work, and it is currently unranked in every planning document we
hold.

## 7. Consequences for the program

1. **Measure A.** New highest-priority empirical target, and it did not exist
   before this derivation. Instrument `h̄` on the settlement path where H1 is
   already enforced.
2. **R-B4 is underrated.** Widening the reversible interior buys scale without
   paying for verification.
3. **Sampling is the other relaxation** and it is conditional: assumption 3 lifts
   exactly when Route 6's `LR ≥ g/w` holds — measured 19.8 in competence, 1.25
   out. **Sampling buys scale inside competence and nothing outside it.**
4. **Do not pursue five-nines verification.** §3 shows it is the required figure
   only under A = 1, which is the assumption we should attack instead.

## 8. Limits

A scaling argument, not a theorem. H fixed and non-substitutable; escalations
independent; p and c independent — **almost certainly false**, since unverifiable
actions are plausibly the harder-to-contain ones, which makes every bound here
**optimistic**. And §4 of the sweep combines two differently-populated
measurements: it is marked ILLUSTRATIVE in the source and its *shape* is the
claim, never its digits (artifact #17).
