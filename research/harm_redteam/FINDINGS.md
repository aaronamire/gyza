# §4.2 — Harm-model completeness: HARM-IS-TRANSFERRED

**Preregistration:** `PREREGISTRATION.md`, BLAKE3
`7d6349029ca027bfcfbad41624fc55231d7e0be06b9ad14b609d86ff9d5aa8fd`, committed
`19d8d23` as the sole file in this directory. Every artifact here postdates it.

**Zero credits.** Attacks run against the REAL shipped `LedgerSettlementService`
and the REAL `SettlementGuard` over the real protocol — not a synthetic
environment. Damage is scored by `damage.py`, which cannot see the guard (T1–T3
pass).

---

## The verdict

> ### H1 is not a harm BOUND. It is a harm TRANSFER — and the declared model measures only one side of it.

All three preregistered predictions confirmed. Both decision rules met. **No
declared bound was violated in any attack**, which is the precondition: the
guard worked exactly as designed and the system was harmed anyway. That is R9's
shape, reproduced in shipped code.

---

## A1 — exhaust-then-refuse. **R-A1 MET** (bar: D1 ≥ 100.0)

A payer draws H1 to 90.0 with one legitimate settlement, then three honest
earners deliver work the guard can never let it cosign.

| | |
|---|---|
| **D1 unpaid delivered work** | **180.0 credits** |
| **D2 earners locked out** | **2 of 3** |
| H1_credits (declared) | **90.0** against bound 100.0 |
| **declared bound violated** | **NO** |

**Verified independently of the harness.** D1 was rescored from *the earners'
own ledgers* — records the payer never touched — and returned 180.0, identical
to the payer-view score. Not an artifact of how the harness looks at the data.

### The counterfactual, which is where the finding actually lives

Pairing a containment number with what it bought (the AG-3 rule):

| | guard ON | guard OFF |
|---|---|---|
| H1_credits | **90.0** | 270.0 |
| declared bound violated | NO | **YES** |
| settlements completed | 1 | 4 |
| **D1 unpaid delivered work** | **180.0** | **0.0** |

> **The guard prevented 180.0 credits of drawdown and created 180.0 credits of
> unpaid delivered work.**

**DIAGNOSING THE CLEAN 180 = 180 — it is DEFINITIONAL, not a measured law.**
Every credit the guard refuses to settle *is* a credit of delivered work that
goes unpaid: the same entries, counted from the other side. The transfer is
one-for-one by construction and must never be reported as an empirical
regularity. What is *not* definitional is the direction — that the harm goes
somewhere at all rather than being extinguished — and that is the finding.

**The guard is not inert.** With it absent the bound is genuinely exceeded
(270.0 > 100.0), so this is not AG-3's failure mode of an expensive guard whose
violation count matches the baseline. It enforces. It enforces by relocating the
harm onto parties the model does not measure.

### Why this is an adequacy finding and not "the bound works"

H1's declared quantity is *this compositor's* drawdown. Nothing in the declared
model measures a counterparty's loss. So an operator can declare a tight bound,
consume delivered work, and refuse to pay — and every declared quantity reports
the system inside its limits. **The guard becomes a mechanism for obtaining free
work, and the harm model certifies it.**

---

## A2 — frame multiplication. **R-A2 MET** (bar: D3 ≥ 200.0)

One operator, three compositors, each drawing to exactly the declared bound.

| compositor | H1_credits |
|---|---|
| `db99c67a9227…` | 100.0 |
| `8006c25cd41a…` | 100.0 |
| `884804f02154…` | 100.0 |
| **D3 operator-level drain** | **300.0** |
| **declared bound violated** | **NO** |

H1's declared frame is `compositor pubkey`. **An operator is not a compositor**,
and no declared class names the operator as a frame. The bound is therefore per
*key*, not per *actor*, and an actor may hold arbitrarily many keys.

**Diagnosing the exact 100.0 × 3:** DEFINITIONAL — the attack delivers exactly
100.0 to each. It demonstrates that three compositors *can* sit at the bound
simultaneously; it is not evidence about calibration.

This is **R13 (federation does not compose) reappearing one layer up**, in the
harm model rather than in the delegation chain. It was predicted (P2) for that
reason.

---

## A3 — honest control. **R-A3 MET**

D1 = **0.0**, D2 = **0**, H1 = 60.0 in bound, nothing refused. Without this,
D1 > 0 would be measuring "settlement occurred" rather than "damage occurred",
and A1 would establish nothing.

---

## Exact-value diagnoses, flagged in advance (discipline #2)

| value | reading |
|---|---|
| **H4_authority = 0.0** in every attack | Correct and expected (P3). None of these attacks exceeds authority. It is *not* evidence that authority containment resisted an attack — none was mounted against it. |
| **H2_market_capital = 0.0** in every attack | **DEFINITIONAL (P4).** `BondedMarket` has zero production constructors, so the quantity cannot move. **This must never be cited as "market capital was unharmed."** |

Both were predicted before the run precisely so they could not later be read as
findings.

---

## What this does NOT establish

1. **Not completeness.** The author of the harm model ran the red team
   (§2 of the preregistration). A *found* attack is valid — an existence proof
   does not depend on the prover — but this exercise cannot say the model has no
   other gaps, and a null here would have established nothing at all.
2. **Not exhaustiveness.** R12: unmodelled channels are not mechanically
   discoverable, and a search bounded by one author's imagination is not a
   survey.
3. **Nothing about damage past emission.** C15 — containment ends at emission,
   out of scope by construction.
4. **Nothing about H2.** No production existence; attacking it would measure the
   fixture.

---

## What follows, stated as options rather than a decision

Both findings are about the **declared model**, not about broken code, so both
remedies are declarations — and declaring what a system must not do is the
owner's call, not an implementer's.

- **A1** wants a declared harm class over *counterparty* loss — unpaid delivered
  work is a state function of the ledger and is computable today (`damage.py`
  computes it). Declaring it would make the transfer visible instead of silent.
  Note the cost honestly: bounding both sides at once may be infeasible, since
  refusing to pay and paying past the bound cannot both be avoided once the
  bound is reached. That tension is real and is the reason this is a decision.
- **A2** wants either an operator-level frame for H1, or an explicit statement
  that the bound is per-key and an operator may hold many. The second is
  cheaper and honest; the first is what most readers will assume was meant.

**Neither is implemented here.** A red team that fixes what it finds stops being
a red team, and bound levels and frames are `TBD — user decision` by standing
policy.
