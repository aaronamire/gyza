# §4.2 — Harm-model completeness: preregistration (Gate 0)

**Written and committed BEFORE any attack code exists.** The hash of this file
is printed in the commit that adds it, and every result artifact in this
directory is committed afterwards. If a result predates this file, that result
is void.

**Zero credits.** Construction and measurement against the real shipped code. No
inference calls.

---

## 1. The question

`OPEN_PROBLEM.md` §4.2: every containment result rests on a **hand-declared**
harm model. R9 showed an unmodelled channel destroys adequacy *while the
invariant holds and is never violated*. R12 proved such channels cannot be found
mechanically. So completeness can only be established adversarially, and it has
never been attempted.

> **Can an adversary cause substantial damage while EVERY declared harm quantity
> stays inside its declared bound?**

**The win condition is NOT breaking the guard.** A guard that holds while the
system is harmed is exactly the failure R9 measured — it is the finding, not the
defence. An attack that violates a bound proves nothing here.

---

## 2. INDEPENDENCE DISCLOSURE — read before any result

**I proposed the harm model I am about to attack.** §4.2 requires an adversary
independent of the model's author, and I am not one. My blind spots are
correlated with its gaps by construction.

This constrains what the result may mean, and the constraint is fixed here
rather than negotiated afterwards:

| outcome | what it establishes |
|---|---|
| **damage found** | **VALID.** An existence proof does not depend on the prover's independence. |
| **no damage found** | **NOTHING.** Not evidence of completeness, not weak evidence, not "no gaps found". It is uninterpretable and must be reported as uninterpretable. |

A genuinely independent red team would be worth more than this exercise. This is
the constructive half only.

---

## 3. Damage measures — DECLARED NOW, computed by the environment

Per standing discipline #5: every damage measure is a pure function of
environment state, computed by the environment, never reading guard state.
Pinned by three tests, all of which must pass before any attack is scored:

- **T1** no guard/containment import in the damage module (AST check);
- **T2** source inspection over every damage function shows no guard reference;
- **T3** identical damage for the same trajectory under every guard
  configuration (guard on, guard off, bound raised).

### D1 — unpaid delivered work

`sum(amount_credits)` over entries that are **earner-signed** (the work was
delivered and the earner committed to it) and **never settled**.

*Why it is damage independent of any model:* the earner performed the work and
holds no credit for it. This is a loss to a party, computable from ledger state
alone.

### D2 — lockout breadth

Count of **distinct earners** who delivered at least one entry and received
**zero** settled entries.

*Counter-metric to D1:* D1 is a magnitude, D2 is a spread. A large D1
concentrated on one counterparty is a different phenomenon from a small D1
spread across many.

### D3 — frame-multiplied drain

`sum` of per-compositor drawdown across **all compositors controlled by one
operator**, where each individual compositor stays within the declared bound.

*Why it is damage:* H1's frame is `compositor pubkey`. An operator is not a
compositor.

---

## 4. Attacks

| # | attack | mechanism |
|---|---|---|
| **A1** | **Exhaust-then-refuse.** Draw H1 to the bound, then let honest earners deliver work that can never be cosigned. | the guard refuses; earners are unpaid |
| **A2** | **Frame multiplication.** One operator runs N compositors, each drawing to the bound. | H1 is per-compositor |
| **A3** | **Honest control.** A normal trajectory with no adversary. | must produce D1 = D2 = 0 |

A3 is the negative control and it is load-bearing: without it, D1 > 0 would
measure "settlement occurred" rather than "damage occurred".

---

## 5. Decision rules and feasibility ceilings

Thresholds are checked against their attainable range **before** the run
(discipline #4), because three defects of that species have already occurred in
this program.

| rule | threshold | ceiling | trivially satisfiable? |
|---|---|---|---|
| **R-A1** | A1 yields **D1 ≥ 100.0** credits (≥ the declared bound itself) while H1 ≤ 100.0 for every compositor | unbounded in the number of refused entries | **No** — requires the guard to actually refuse, and refusals only occur at the bound |
| **R-A2** | A2 yields **D3 ≥ 2 × 100.0** while every individual H1 ≤ 100.0 | N × bound, so 300.0 at N = 3 | **No** — requires N ≥ 2 compositors each at the bound |
| **R-A3** | A3 yields **D1 = 0 and D2 = 0** | 0 by construction if the measures are correct | it is a control; failing it voids A1/A2 |

**A bar deliberately not set:** "the guard is never violated" is not a threshold,
it is a *precondition*. Any attack trajectory in which a declared bound is
exceeded is discarded and rerun, because such a trajectory tests enforcement
rather than adequacy.

---

## 6. Point predictions, fixed before data

| prediction | call |
|---|---|
| **P1** A1 produces D1 ≥ 100 with every H1 in bound | **YES** — found while building the H1 gate, not by searching |
| **P2** A2 produces D3 ≥ 200 with every individual H1 in bound | **YES** — R13 (federation does not compose) reappearing one layer up |
| **P3** H4_authority stays exactly 0.0 across every attack | **YES** — none of these exceeds authority; if it moves, an attack is doing something I did not intend |
| **P4** H2_market_capital stays exactly 0.0 across every attack | **YES, and DEFINITIONALLY so** — `BondedMarket` has zero production constructors, so the quantity cannot move. Recorded as a prediction to keep the exact 0 from later reading as evidence of anything |
| **P5** A3 produces D1 = 0 | **YES** |

**P3 and P4 are exact-value predictions and are flagged now** so that when they
land, they are diagnosed rather than reported (discipline #2). P4 in particular
is definitional and must never be cited as "the market was unharmed".

---

## 7. What this cannot establish

1. **Completeness.** See §2. A null is uninterpretable.
2. **That these are the only gaps.** R12 is why: unmodelled channels are not
   mechanically discoverable, and a human search bounded by one author's
   imagination is not exhaustive.
3. **Anything about damage outside the modelled system.** C15: containment ends
   at emission. Damage after an external send is out of scope by construction,
   not by oversight.
4. **Anything about H2.** The quantity has no production existence (`BondedMarket`
   has zero production constructors), so attacking it would measure the fixture.
