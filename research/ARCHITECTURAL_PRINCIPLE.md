# The architectural principle

**Three independent routes converge on one property of state representation.** Each
found it from a different direction, answering a different failure mode, and none was
looking for it. This file states the principle once, with each route's evidence, its
cost, and — equally important — the boundary where it does not apply.

> **APPEND-ONLY, PARTITIONED, DERIVED-NOT-STORED.**
>
> Represent a safety-relevant quantity as a **pure fold over append-only, partitioned
> state**, and have the guard invoke **the same function** that computes the harm.

This is not a new idea in isolation — it is event sourcing plus UTXO plus
referential transparency. What the routes establish is that **one design choice buys
three different guarantees that were previously being sought separately**, and that
the failure modes are not independent bugs but the same shape appearing three times.

---

## What the three guarantees are NOT

**Added after AR-1, which measured what was already true.** The three guarantees
below are about **provenance**, **containment**, and the **composition of
INVARIANTS**. **None of them is a correctness guarantee**, and none ever was:

| guarantee | what it establishes | what it does not |
|---|---|---|
| blind channels architecturally impossible | every path that moves a quantity appends to the fold the gate reads | nothing about whether the work was right |
| frame alignment free | guard and harm measure cannot disagree about the frame | nothing about whether the work was right |
| breadth composition | conservation/monotone invariants hold under concurrency | nothing about whether the work was right |

AR-1 measured the consequence directly: real audited chains are 100%
PROOF-carried and flat through depth 8, while **correctness coverage is 0.0 at
every depth, including depth 1**. The fold composes; the claim that the folded
work is *correct* was never present to compose.

This is not a limitation discovered by AR-1. It is what a provenance substrate
is, stated plainly so no reader infers otherwise from the word "guarantee".

## The three guarantees

### 1. Blind channels become architecturally impossible — R12 Part C

R12 asked whether channels that move a harm quantity *without passing the guard*
("blind channels") can be found mechanically by static analysis. Answer: **UNSOUND** —
recall 0.5; they are not reliably discoverable. But Part C found the constructive
converse: Gyza's credit ledger has **no** blind channel, and not because the analyzer
was clever.

- Balances are **derived, never stored**: `gyza/economy/wallet.py:169-171` —
  *"Pure projection over an iterable of `LedgerEntry`."*
- Entries are **append-only**: `gyza/economy/ledger.py:30-32` — *"Entries are
  append-only. There is no `update_entry`. Adjustments are made by issuing a
  counter-entry."*
- The gate **reads the same fold**: `gyza/economy/subcontract.py:184-196`
  (`available()` → `self._wallet.net_balance(self._owner) − active_holds`).

**There is no balance field for an unmodelled path to write.** Every path that changes
the quantity must append an entry, and the gate that folds those entries necessarily
sees it. The blind channel has nowhere to hide — a structural property, not a
detection result.

### 2. Frame alignment comes for free — R9 condition 2

R9 established that an invariant is adequate only if evaluated over **the same frame**
as the harm. Its measured counterexample: `G4′` pinned its frame at `s₀` and lost
175 000; `G4` read the current frame and bounded at 50. Frame drift is not a subtle
bug — it is a four-order-of-magnitude failure with the invariant intact and never
violated.

If the guard and the harm **call the same fold**, the frame is the *same object*.
There is no second frame to drift. R12 observed this independently in simulation:
guards that called the environment's own accounting helpers (`principal_total`,
`recoverable`) inherited the harm's frame transitively, and were the ones that held.

**R9's condition 2 stops being a discipline you must remember and becomes a
consequence of the representation.**

### 3. Breadth composition — R10 H-APPEND and the H-CONS refutation

R10 asked whether locally-checked guards compose across *concurrent* agents (breadth),
having established that they compose across *depth* (66 serialized cells, 0
violations).

**H-APPEND — confirmed.** Append-only storage is the one thing that made a global
predicate compose: recoverability (G3) under append-only storage showed **0 violations,
`H_lost` = 0.000, final state recoverable, at N = 2, 4 and 8, under both shared and
partitioned accounts** — at *higher* throughput than its mutable counterpart
(0.67 vs 0.50). The canonical A/B race — content X in two objects, each agent deletes
one, each local check passes, the joint state has lost X — **couples entirely through
the archive's mutability.** Remove the mutability and the race cannot be constructed.

**H-CONS — refuted, and the refutation is the sharper half.** R10 predicted
conservation would compose once accounts were partitioned. It does not: G2 and G4
violate under partitioned accounts exactly as under shared ones, because

> **the guard's own state is the conflict set.**

A single counter `c`, or a single pool of single-use authorizations, has a conflict set
of size one *no matter how the accounts are arranged*. Eight agents all check against
the same pre-round `c = 0`; all pass; the joint total blows the budget.

**Bitcoin's discipline is stronger than "partition ownership":** each UTXO is an
independent spend-once token and validating a spend is **stateless with respect to
every other UTXO**. Bitcoin partitions *the guard's state*, not merely who owns what.

> **DESIGN RULE. A guard scales in breadth only if its state partitions along the same
> axis as the actions.** A monotone budget is inherently global and therefore
> inherently serializing, regardless of how the underlying resource is partitioned.

### CORRECTION (AG-3) — the rule above is NECESSARY BUT NOT SUFFICIENT

**The prior text is preserved verbatim above and remains true.** AG-3 measured
that it is only half of the requirement.

`PARTITIONED_READ` partitions its state perfectly — it reads no other
principal's state at all and enforces a box *proved sound* — and it **leaks
4.5x MORE than the global-read guard**: 9 violations against 2, with max
concentration 0.7368 against 0.6250. Violations by agents-per-principal at M=2
are **0, 2, 6 — monotone in N.**

> **THE RULE, IN FULL. A guard bounds a quantity in breadth only if BOTH hold:**
> **(i) the guard's own state partitions along the action axis** — R10; and
> **(ii) the admission decision is LINEARIZED against updates to everything it
> READS** — AG-3.

**The mechanism, which is the part worth carrying.** Removing the
cross-principal read did not remove the staleness — it **relocated it from
between principals to within one**. With N >= 2 agents per principal, each agent
verifies "my principal's total stays above the floor" against the *same stale
value of its own principal's total*, and they jointly breach it.

**The read-set's EXTENT was never the disease. Recency at decision time is.**
And note precisely what fails: **consistency is not the property required.**
Every guard read a perfectly *consistent* pre-round snapshot and was still
wrong, because the other admitted effects land after the read. A stale read is
exactly as unsound as an unobserved write — reads commute and never conflict,
but a *decision* taken from a stale read does not commute with anything.

### THE COMPOSABILITY CRITERION IS DIRECTIONAL LOCALITY (AG-3), not the temporal class

AG-3 preregistered a three-way temporal taxonomy (instantaneous / cumulative /
path-dependent) and **retired it**: it is a valid partition that does not predict
composability, because the instantaneous class is not internally uniform.

> **A sound purely-local test `T_p` exists iff `h` decomposes as
> `F(g_1(s_1), …, g_M(s_M))` with `F` monotone in each argument IN THE SAME
> DIRECTION** — so that every principal can conservatively bound its own
> contribution's movement in the harmful direction using only what it controls.

| quantity | shape | local test? |
|---|---|---|
| `total_holdings = Σ_p x_p` | monotone **increasing** in every `x_p` | **yes** — a static split `x_p >= B/M` composes |
| `concentration = max_p x_p / Σ_q x_q` | increasing in `x_p`, **decreasing** in every other `x_q` | **no exact test exists** |

For concentration the proviso is **unsatisfiable, not merely unmet**: a
principal can push another past the bound by an action wholly inside its own
authority, so no test over what a principal controls can prevent it.

**Witness (M=3, κ=0.60), proved and unit-tested.** At `s_0` every principal
holds 20. Four actions, each evaluated by its own guard against the **same
pre-round state**, each admitted at concentration ≤ 0.40:

| action | concentration if applied ALONE |
|---|---|
| B sends 10 from `B:a0` | 0.4000 |
| B sends 4 from `B:a1` | 0.3571 |
| C sends 10 from `C:a0` | 0.4000 |
| C sends 4 from `C:a1` | 0.3571 |

Applied jointly: `A=20, B=6, C=6`, **concentration = 0.625 > κ**. **Principal A,
whose share crossed the bound, took no action at all** — its total is
bit-identical before and after. That is what "no exact local test exists" looks
like operationally: the violating movement was not A's to make and not B's or
C's to see.

This is why the principle needs all three words. *Append-only* alone removes the
storage race; *partitioned* is what removes the guard-state race; *derived-not-stored*
is what removes the blind channel.

---

## CORRECTION (SR-3) — the taxonomy is TWO-DIMENSIONAL

**Added after SR-3. The prior text above is preserved verbatim and is not
wrong; it is INCOMPLETE, and the omission changed a design decision.**

Everything above treats the invariant **CLASS** (conservation / monotone /
cumulative) as the variable that governs composition. SR-3 measured composition
directly and found class is **not** that variable. Two dimensions govern two
different questions, and this document had collapsed them into one:

| dimension | values | governs | established by |
|---|---|---|---|
| **invariant CLASS** | CONSERVATION / MONOTONE_NON_CUMULATIVE / CUMULATIVE | **CONCURRENCY** — what may run in the interior vs what must serialize at the gate | C6, C7 (R9+R10+R13) |
| **CARRIER** | PROOF / SPEC / TEST | **EVIDENTIAL COMPOSITION** — whether a chain of checks still checks anything | SR-3 |

Class still governs concurrency exactly as §3 says. It does **not** govern
whether per-stage checks compose into a check on the whole.

### The measurement

SR-3, 12 three-stage pipelines over Gyza's own claim types, 27 end-to-end
violations, single-stage mutations:

| carrier | n | detection under verified fold |
|---|---|---|
| PROOF — the check RECOMPUTES the property | 21 | **1.000** |
| SPEC — a registered partial property | 2 | **1.000** |
| **TEST — a finite sample** | 4 | **0.000** |

### How the class reading fooled itself — the carrier mixture

Measured **by class**, CONSERVATION detects **0.667** and MONOTONE **1.000**,
which reads as "conservation composes less well than monotone" and would have
been recorded as a class property. It is not. CONSERVATION decomposes:

| class × carrier | n | detection |
|---|---|---|
| CONSERVATION × PROOF | 8 | **1.000** |
| CONSERVATION × TEST | 4 | **0.000** |

**0.667 was a MIXTURE of two populations, not a property of either.** Every
conservation failure was a TEST-carried failure. The aggregate had no referent.

### The corrected statement

> **APPEND-ONLY, PARTITIONED, DERIVED-NOT-STORED** — governs whether a quantity
> can be bounded at all, and (via class) what may run concurrently.
>
> **PROOF-CARRIED, NOT TEST-CARRIED** — governs whether the bound survives
> composition. A check that RECOMPUTES its property composes to arbitrary
> depth; a check that SAMPLES its property composes to nothing, because a finite
> sample cannot bound behaviour outside itself. Adding cases moves the boundary
> without removing it.

The practical consequence, quantified in `CARRIER_COVERAGE.md`: a claim type's
TIER is a property of that claim **in isolation** and is not a composition
budget. A tier-1 claim whose verifier is a unit-test suite forces every chain
containing it to tier 3.

## The cost, stated plainly

**Nothing is ever freed.** Deletion stops reclaiming anything, so storage grows without
bound — pinned in R10 by `test_append_only_has_a_cost_nothing_is_ever_freed`. This is
not a rounding error in the design; it is the whole price, and it is paid forever.

**This is the same tradeoff Bitcoin accepted**, and the reason its UTXO set and chain
history only grow. It is a defensible trade when the quantity being protected is
safety-relevant and the volume is bounded by economic cost; it is a bad trade for
high-volume, low-stakes state.

A second cost, measured: under append-only storage R10's Part D frontier **disappears**
— k = 5 dominates every other checkpoint interval at zero harm and full effective
throughput. That is a benefit, but it means the tuning knob you might have wanted is
gone; you are choosing the representation, not calibrating it.

---

## The document fails its own rule, applied to itself

The cost section above states the price of append-only — **nothing is ever
freed, paid forever** — and then declares no quantity that measures it. The
rule this document exists to state is that a safety-relevant quantity should be
a **declared fold that a guard reads**. Storage growth is safety-relevant (it is
the one unbounded consequence the design knowingly accepts), it is trivially a
fold over the log, and **no guard reads it**.

Named here rather than fixed, because declaring a bound is an owner decision.
A proposed quantity — with its immutable origin, its CUMULATIVE class, and the
observation that CUMULATIVE puts it at the promotion gate the architecture
already serializes — is in `HARM_MODEL_GAP.md`.

## Where it does NOT apply — the boundary of containment

**Effects that leave modeled state entirely.** Gyza's H3 sub-class *external network
sends* (`netd_client.py` — `publish_agent`, `send_message`, `publish_delta`,
`publish_attestation`) leaves the modeled system. There is no fold over them because
**there is no state to fold.**

Stated plainly, because it is the boundary condition of the whole containment story:

> A guard can refuse to **emit**. After emission, containment has no meaning — and
> **no detector would help either.** This is not a gap to be closed; it is the limit
> of what containment can claim, and it belongs in any claim Gyza makes.

Two further limits:

- **The principle is about state, not semantics.** It makes *quantities* auditable. It
  says nothing about whether a claim is *true* — that is the competence bound, closed
  across six mechanism families and terminal (`COMPETENCE_BOUND.md`).
- **Bounded loss is not zero loss.** R10's graded guard `G5(0.25)` composes at N = 8
  with harm bounded exactly at θ — and leaves the state **not recoverable**. The
  principle bounds harm; it does not make harm reversible.

---

## Where Gyza stands against it

| harm class | append-only? | derived-not-stored? | guard reads the same fold? | status |
|---|---|---|---|---|
| **H1 credits** | yes (`ledger.py:30-32`) | yes (`wallet.py:169-171`) | yes (`subcontract.py:184-196`) | **conformant** |
| **H2 market capital** | **no** — `_capital` is a mutable dict, mutated in place at four sites (`market.py:287, 325, 332, 345`) | **no** — stored aggregate | **no gate reads it at all** | **anti-pattern** |
| **H3 irreversible change** | n/a | n/a | no representation in the codebase | **unmodelled** |
| **H4 authority** | yes (delegation chain is append-only) | re-decided at acceptance time | yes (`verify_delegation`) | **conformant** |

**H2 is the anti-pattern living in the same codebase as the pattern.** Today it is not
a leak — `_capital` is seeded from a constructor argument and no path bridges it to
`LedgerEntry` credits, so they are two disjoint currencies. The hazard is the stated
roadmap (`market.py:21-23`, the multilateral settlement layer). The moment market
capital becomes fungible with ledger credits, it is **exactly R9's G2 failure**: value
moving through a channel the gate's counter does not track, which R9 measured at 100%
of holdings lost with the invariant intact and never violated.

**The fix is a representation choice, not a bigger gate.** Route market P&L *through*
`LedgerEntry` so it lands inside the fold the gate already reads. Extending the gate to
read a second mutable pool would restore the check but forfeit all three guarantees —
the blind channel becomes possible again, the frame can drift again, and the guard
acquires a second piece of global state that does not partition.

---

## Provenance

| claim | route | artifact |
|---|---|---|
| no blind channel in the ledger; the fold is why | R12 Part C | `channel_discovery/` |
| frame must match harm's frame (condition 2) | R9 | `invariant_adequacy/` |
| append-only makes recoverability compose | R10 H-APPEND | `breadth_grading/`, `router/R10_CORRECTIONS.md` |
| guard state is the conflict set | R10 H-CONS refutation | `breadth_grading/`, `router/R10_CORRECTIONS.md` |
| composition conditions, corrected | R11 Part A1 | `router/R10_CORRECTIONS.md` |
| checkpointing bounds resource loss, not content loss | R11 Part A2 | `router/R10_CORRECTIONS.md` |
