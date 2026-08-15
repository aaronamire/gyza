# Escrow — preregistration (Gate 0)

**Committed before any escrow code exists.** Nothing else is in this directory.
**Zero credits**; deterministic, no model call.

---

## 0. WHAT THIS ROUTE IS *NOT*, CHECKED FIRST

I proposed "per-agent escrow repairs the box's intra-principal concurrency
failure" as a cheap decisive test. **It is largely already answered**, and
recording that is the first obligation here — `OPEN_PROBLEM` §2 says the most
expensive thing a fresh agent can do is open a route that re-derives a closed
one.

`guards_reservation.ReservationAgg` **is** per-principal escrow: origin fixed
once at `open_round` and written nowhere else, budget decremented on every
admission, multiple actors within a principal sharing and drawing down that
budget. The route reached **RESERVATION-PARTIAL**, and its sharpest measured
fact is that **violations are non-monotone in N and worst at N=1** — so its
failures are *not* the within-principal race that motivated my proposal.

**So the intra-principal repair question is CLOSED and is not reopened here.**

## 1. What IS open

### E1 — Does reservation's verdict survive at real M?

Every RESERVATION cell ran at **M ≤ 3**, because `env_federation.principals`
silently capped there. The arena now expresses M up to 512. RESERVATION-PARTIAL
is therefore a verdict measured at a scale the environment could not exceed, and
whether it holds at M ≫ 3 has never been observed.

**The committed guard is imported READ-ONLY.** A copied guard is a second frame
that can drift from the one the verdict was measured on.

### E2 — Does escrow convert a TRANSFERS class into an EXTINGUISHES one?

**Completely untested, and the more consequential of the two.**

HARM-IS-TRANSFERRED's mechanism: bound reached → guard refuses → *the earner has
already done the work* → the earner bears an unmeasured loss. R-B1 attributes
that to **conservation**: reducing a conserved quantity inside a frame increases
it outside.

**The claim under test:** escrow does not violate conservation — it changes
*when* allocation happens. If funds are committed **before** work is
commissioned, the state "work performed, payment refused" becomes unreachable,
so no counterparty expectation is unmet and nothing is relocated.

If true, this is the constructive repair for the one finding that most narrowed
the vision, and it is memo M3's refuse-early option with a mechanism rather than
a hope.

## 2. Prior art, so novelty is not overclaimed

**Escrow (O'Neil, TODS 1986)** — the technique. Its own stated scope:
*"incremental changes to aggregate quantities"*, commutative, single-sided.
**Demarcation (Barbará & García-Molina, VLDB J 1994)** — coordination-free, and
*"limited because it only applies to **linear** arithmetic constraints."*
**I-confluence (Bailis, PVLDB 2014)** — necessary *and* sufficient for
coordination-free execution; its analysed table contains **no cross-principal
aggregate and no ratio**.

**Nothing about escrow is new.** What is untested is (a) whether it converts
harm-transfer to harm-extinction for agent consequence bounds, and (b) whether
the verdict on it holds past M = 3.

## 3. Measures — computed by the environment, never reading guard state

- **`unpaid_delivered_work`** — credits of earner-signed, never-settled work.
  Reused verbatim from `research/harm_redteam/damage.py`, which passes its own
  independence tests (no guard import, source inspection, identical scores under
  every guard configuration).
- **`drawdown`** — settled net outflow, same source.
- **`v_inst`** — rounds where `concentration > κ` while every local check passed.
- **`idle_escrow`** — committed-but-unspent funds. **The price.** Escrow
  over-allocates by construction, and a route reporting only its benefit would
  be the TPR-without-FPR defect this program has recorded.

## 4. Decision rules, with feasibility ceilings checked BEFORE the run

| rule | threshold | ceiling | trivially satisfiable? |
|---|---|---|---|
| **E1-HOLDS** | RESERVATION's violation rate at M ∈ {8,64,512} stays within 2× of its M=2 value | rate ∈ [0,1]; measured non-zero at small M | **No** — a rate that collapses or explodes with M refutes it |
| **E2-EXTINGUISHES** | with escrow, `unpaid_delivered_work` = **0** while drawdown stays bounded | 0 is attainable only if no work is ever commissioned unfunded | **No** — requires the commissioning path to actually gate on escrow |
| **E2-CONTROL** | without escrow, the same trajectory yields `unpaid_delivered_work` > 0 | already measured at 180.0 in the red team | it is the control; failing it voids E2 |
| **E2-PRICE** | `idle_escrow` is reported beside every E2 result | — | not a bar; a reporting obligation |

**A precondition, not a threshold:** any run where a principal exceeds its own
declared bound is discarded. That tests enforcement, not adequacy.

## 5. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-E1** | RESERVATION's violation rate is roughly flat in M | **YES** — the arena found the box's own rate flat from M=8; reservation bounds shedding by a budget derived from the same floor, so it should inherit that shape |
| **P-E2a** | escrow drives `unpaid_delivered_work` to **exactly 0** | **YES, and DEFINITIONALLY so** if commissioning gates on escrow — flagged now so the exact zero is diagnosed, not reported as discovery |
| **P-E2b** | `idle_escrow` is substantial — **≥ 25%** of committed funds | **YES** — escrow reserves worst-case; that idle capital is the price |
| **P-E3** | escrow does **not** repair the cross-principal ratio bound | **YES** — DERIVABLE, not new: concentration is two-sided, so no exact local test exists (THEORY_AG3), and escrow is local by construction |

**P-E2a is an exact-value prediction and is flagged in advance** (discipline #2).
A clean zero there is the construction, not a finding.

## 6. What this cannot establish

1. **Escrow is single-sided and commutative** by O'Neil's own scope. It covers
   increment/decrement quantities and not arbitrary effects.
2. **Irreversibility is not linear.** You cannot escrow "content destroyed" as
   you escrow credits, so the largest EXTINGUISHES class may sit outside this
   entirely.
3. **Simulated principals, no real agents, no real humans.**
4. **Nothing about correctness.** Consequence only; the competence bound is
   untouched.
