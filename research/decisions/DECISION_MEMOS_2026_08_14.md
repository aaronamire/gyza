# Decision memos — 2026-08-14

**These are memos, not decisions.** Each states the options, what each costs,
what it forecloses, and what it lets the system claim. Bound levels and frames
are `TBD — user decision` by standing policy, and reconstructing them from what
is convenient to implement is the circularity the harm model exists to avoid.

**Recommendations are given** where the evidence supports one, and marked where
it does not.

---

## M1 — Does the bonded market ship? (H2_market_capital)

**The fact.** `BondedMarket` has **zero production constructors**. Its only
importer, `gyza/economy/resolution.py`, is itself imported only by
`tests/test_resolution.py`. `guard_bounds.json` declares
`H2_market_capital: 100.0`, and no execution path in `gyza/` can move that
quantity off zero.

So one of three declared, bounded harm classes is over a quantity the product
does not have. That inflates the apparent reach of the model: a reader counting
declared classes counts three, and two are real.

| option | cost | what it lets you claim |
|---|---|---|
| **A. Ship the market** | wires `resolution.py` into a production path; the market's assertion/staking flow becomes live surface that must then be maintained and audited | 3 of 3 declared classes real; H2 becomes attackable, which is a prerequisite for it meaning anything |
| **B. Mark it aspirational** — keep the code, remove the declared bound, list H2 beside H3 in `UNMODELLED` | ~1 hour; `gyza status` and any capability statement drop from 3 declared classes to 2 | 2 of 2 declared classes real. Smaller number, no overstatement |
| **C. Leave as is** | zero | **nothing** — and a reader who checks discovers a declared bound over a quantity that cannot move. This is the option with a downside |

**Recommendation: B**, unless the market is on the near roadmap. The honest
number is more useful than the larger one, and C is the only option that can
embarrass you in diligence.

---

## M2 — H1's accounting origin: per-run or per-ledger?

**The conflict.** `guard_bounds.json` declares H1 as *"max net drawdown **per
run**"*. `SettlementGuard` measures **per ledger** (genesis origin). These are
different bounds and only one is implemented.

**Why the implementation diverged deliberately:** an origin at process start is
ledger artifact #13 wearing a hat — restart the process and the budget refills.
That is a bound whose origin moves, which is not a bound.

| option | cost | what it lets you claim |
|---|---|---|
| **A. Per-ledger (as implemented)** | strictest; a long-lived node eventually exhausts its lifetime budget and stops settling until the bound is raised | a genuine cumulative bound over the node's whole history, ungameable by restart |
| **B. Per-run, as declared** | requires a persisted, signed window marker so "run" cannot be re-based by restarting; without that it is defeated by `kill -9` | a per-run bound **only if** the marker is persisted and tamper-evident. Otherwise it is theatre |
| **C. Per accounting window** — explicit `open_window`, persisted | the machinery exists (`StagingArea.open_window`, `WindowOrigin`); needs a persisted marker and an operator action to roll the window | the useful middle: bounded per period, ungameable within it, and the roll is a deliberate, auditable act |

**Recommendation: C**, with **A as the default until C is built.** B as written is
not implementable safely, and saying so is more useful than implementing
something weaker than its own declaration.

**Whichever you pick, `guard_bounds.json`'s wording must match**, or the
declaration and the mechanism disagree — which is the defect class this program
keeps catching.

---

## M3 — Declare a counterparty-loss harm class? (from HARM-IS-TRANSFERRED)

**The fact.** Enforcing H1 produced **180.0 credits of unpaid delivered work**
and locked out 2 of 3 earners, with every declared quantity inside bound. The
quantity is already computable: `research/harm_redteam/damage.py`.

**The tension, stated because it is the whole difficulty.** Past the bound,
*refusing to pay* and *paying past the bound* cannot both be avoided. A
counterparty-loss bound and a drawdown bound are **jointly unsatisfiable** in
that region. So this is not "add another invariant" — it is choosing what
happens at the boundary.

| option | cost | what it lets you claim |
|---|---|---|
| **A. Declare and bound it** | jointly unsatisfiable with H1 past the bound; the guard will deadlock unless one bound yields | nothing you could honestly enforce — **do not pick this without resolving the conflict** |
| **B. Declare it as MEASURED, not bounded** | ~2 hours; it appears in `readiness()` and `gyza status` as a measured quantity with no bound | that the transfer is **visible** rather than silent. An operator sees what their bound costs counterparties |
| **C. Refuse-early instead of refuse-late** — decline work you cannot pay for *before* it is delivered | design work in the acceptance path; requires advertising remaining headroom | the strongest position: the harm is not transferred because the work is never done. **Prevention rather than relocation** |
| **D. Nothing** | zero | the guard keeps converting drawdown into counterparty loss, unmeasured |

**Recommendation: B now, C as the real fix.** C is the only option that
*extinguishes* rather than *transfers*, which is exactly the distinction the
conservation taxonomy would formalise. B is cheap and makes the cost legible
meanwhile.

---

## M4 — Operator-level frame for H1?

**The fact.** One operator, three compositors, each at exactly the declared
bound: **300.0 credits of operator-level drain, no bound violated.** H1's frame
is `compositor pubkey`, and an operator is not a compositor.

| option | cost | what it lets you claim |
|---|---|---|
| **A. Say plainly the bound is per-key** | one sentence in the declaration | an honest, checkable claim. Costs nothing and forecloses nothing |
| **B. Operator-level frame** | requires a notion of operator identity that does not exist; and any such frame is itself evadable by an operator who is really two operators — **R13 says this recurses** | a bound that is harder to evade, never one that cannot be |
| **C. Bound the count of compositors per operator** | needs the same missing identity | moves the problem, does not solve it |

**Recommendation: A.** B and C both need an identity layer Gyza does not have,
and R13's result is that federating the frame does not close the gap — it
relocates it. Say per-key, mean per-key. Most readers will assume otherwise
unless told, which is the actual risk here.

---

## M5 — The capability statement

**The fact.** `research/ENGINEERING_STATUS.md` carries the paragraph every other
document must be consistent with. It says Gyza *"bounds declared harm classes
against declared bounds, over a harm model currently covering 13.3% of the
stateful action vocabulary."*

That was written when **no runtime path consulted the harm model at all**. It is
now wrong in **both directions**, which is why it needs your attention rather
than a quiet edit:

- **Too weak:** H1 is now genuinely enforced on a production path. There is one
  real consequence bound where there were none.
- **Too strong:** it reads as a runtime property covering three classes. H2 has
  no production existence (M1), H3 is unmodelled, and H1's enforcement
  *transfers* harm rather than removing it (M3).

**A draft, for you to accept, edit, or reject — the wording is yours:**

> Gyza is a provenance and containment layer. It proves what ran, under what
> bounds, in what order, with attribution to a bonded actor, and those proofs
> compose to arbitrary depth. It makes no claim that any output is correct, at
> any depth; cheap correctness verification is closed across six mechanism
> families. It enforces **one** declared consequence bound on **one** production
> path — credits at risk, at the settlement serialization point — and that bound
> is measured to **transfer** harm to counterparties rather than remove it. Two
> further harm classes are declared: one has no production existence, one is
> unmodelled. Authority containment is enforced separately and unconditionally,
> per work item, by the runner's bounds gate.

**Do not adopt this without deciding M1–M4 first**, since three of its clauses
depend on them.
