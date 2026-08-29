# The phase constraint — sweep, and why the mechanism asked for already exists

**A's verdict, first, because it decides whether a defect commit exists:**

> ## LATENT. No shipped defect. No separate defect commit.
>
> **No CUMULATIVE invariant is evaluated in the INTERIOR phase** — and it is
> **prevented**, not merely absent.

Zero credits. One test file changed; no production code touched.

---

## 0. THE PROMPT'S PREMISE DOES NOT HOLD, and it has to be said before the rest

The task describes RESPEC-3 as having established that **`harm_bounds_respected`
was UNDERDETERMINED**, that a verifier **now proves a frame divergence**, and
that the criterion **has one successful prospective use**. Verified against the
tree:

| claim | reality |
|---|---|
| `harm_bounds_respected` is a claim type | **Does not exist.** Absent from every branch (`git grep` across all refs) |
| RESPEC-3 found it UNDERDETERMINED | **RESPEC-3 REFUSED.** It selected `execution_output_content`, classified it **EXOGENOUS**, and built nothing (`8fd277b`) |
| a verifier now proves the divergence | **No verifier was built** |
| the criterion has 1 prospective use | **Zero.** `FINDINGS_RESPEC_3.md` states explicitly that it was *not* prospective and that the NONE bucket is exhausted for that purpose |

The registry's NONE bucket is unchanged: **`execution_output_content`,
`routing_match_quality`** — the same two, both pre-classified.

**Parts A and B do not depend on that premise.** They rest on committed findings
— C7 (*"no stateless local check bounds a cumulative quantity"*) and BUILD_PLAN
§7's acceptance criterion (*"cumulative invariants are evaluated only at the
promotion gate"*) — so they were executed. **Part C cannot run**, for the reason
in §4.

---

## 1. PART A — the sweep

### A1 — every registered invariant

Registry: `InvariantRegistry`, `gyza/containment/invariants.py:64`.
Registrations: `gyza/containment/gyza_model.py:113, 123, 129`. **Three, total.**

| id | harm class | CLASS TAG | evaluated at | evaluating path |
|---|---|---|---|---|
| `INV-H1-drain` | `H1_credits` | **CUMULATIVE** | PROMOTION only | `engine.py:108-118` via `staging.py:204,209` |
| `INV-H2-capital` | `H2_market_capital` | **CUMULATIVE** | PROMOTION only | same |
| `INV-H4-attenuation` | `H4_authority` | MONOTONE_NON_CUMULATIVE | PROMOTION only | same |

**There is no phase field on `Invariant`** (`invariants.py:56-62`). Phase is a
**call-time argument** to `GuardEngine.evaluate` (`engine.py:62-63`), not a
registration property. That fact governs Part B.

### A2 — is any CUMULATIVE invariant evaluated in the interior? **NO.**

Answered from the **call graph**, not the metadata, as required:

1. **The engine refuses.** `engine.py:109-111`:
   ```python
   if phase is Phase.INTERIOR and not inv.cls.composes_statelessly:
       d.deferred.append(inv.id)   # C7 -- refuse to pretend. Defer, do not evaluate.
       continue
   ```
   It **defers**, and records the deferral, rather than evaluating and
   pretending.
2. **`GuardEngine.evaluate` has exactly two production callers**, `staging.py:204`
   and `:209`, and **both pass `Phase.PROMOTION`.**

### A4 — LATENT, and the two mechanisms are of very different strength

**Prevented, genuinely:** the `engine.py:109` check is a real mechanism on the
evaluation path, and the default `phase=Phase.INTERIOR` (`engine.py:63`) is
**fail-safe** — a caller who forgets gets deferral, the conservative outcome.

**But also merely-does-not-occur, and this is the finding:**

> **`Phase.INTERIOR` is never passed by any production caller.** Its only
> occurrences in `gyza/` are the default value (`:63`) and the two guard
> conditions that test for it (`:74`, `:109`). **The interior evaluation path is
> exercised only by tests.**

So the deferral branch — the mechanism that makes the architecture safe — **has
never fired in production**, because nothing in production evaluates in the
interior at all.

**This is the third instance of the same pattern in this codebase**, after
`last_send_claim` (written 5×, read 0×) and `DemandOracle` (injected, never
constructed). A capability is built, registered and tested, and no production
path reaches it.

### A5 — the counter-metric: unnecessary serialization. **YES.**

Reporting only the direction that could reveal a bug would be selective
sweeping.

`INV-H4-attenuation` is **MONOTONE_NON_CUMULATIVE** — it composes statelessly
(C6) and is explicitly safe to evaluate concurrently in the interior; its own
description says so. **It is evaluated only at the serialized gate**, because
both call sites pass `Phase.PROMOTION`.

And the stronger form: **all three** invariants are gate-only, so
`concurrency_plan()`'s `interior_concurrent` list — the thing the scheduler and
O-3 read — describes a concurrency the system never uses. **1 of 3 invariants is
needlessly serialized; 3 of 3 are in practice.**

That is not unsound. It is throughput left on the table by the architecture's own
measure, and the architecture was designed around C6 licensing exactly that
concurrency.

---

## 2. PART B — the constraint is ALREADY mechanized, and B1's location has nothing to check

### B1 as specified is not implementable against this design

B1 asks to *"reject at REGISTRATION a CUMULATIVE invariant configured for
interior evaluation."*

> **There is no such configuration.** `Invariant` carries `id`, `harm_class`,
> `cls`, `description`, `predicate` — **no phase**. An invariant is not
> registered *for* a phase; the phase arrives as an argument when the engine is
> called. **A load-time check would have nothing to test.**

B1's own stated rationale — *"the guard must sit where the configuration is
ESTABLISHED"* — is right, and correctly applied it points at
**`engine.evaluate`**, because that is where the phase is established. **The
guard is already there** (`engine.py:109`).

### B3's negative control already exists, and is stronger than the one requested

`tests/test_containment.py:163-179`,
`test_cumulative_invariants_are_DEFERRED_in_the_interior_not_evaluated`, asserts
**both directions**: the interior defers *and admits*; the gate evaluates *and
refuses*. A load-failure test would only have shown one.

### B2 — tag or property? **BOTH GUARDS ARE PROXIES, and neither is validated**

Stated explicitly, as B2 requires.

The protected property is *"this predicate reads state a per-transition claim
cannot bound."* The guard tests **two labels instead**:

| guard input | what it is | validated? |
|---|---|---|
| `inv.cls` | a **class tag** set by whoever registered it | Only that it is an `InvariantClass` member (`invariants.py:70-77`). **Never validated against the predicate's behaviour.** `composes_statelessly` (`:39`) is a pure function of the tag — a restatement of the label, not a test of the property |
| `phase` | an argument **supplied by the caller** | **Not at all.** Nothing verifies the caller is in the phase it claims |

> **This is the G4′ / SR-5 / GuardConfigStore species, twice over.** Both proxies
> are correct today. Neither is enforced, and **an unenforced invariant is an
> assumption.**

**Why I did not "fix" this:** validating the tag against the predicate requires
deciding whether an opaque callable is cumulative — undecidable in general.
Making `phase` non-forgeable requires deriving it from the staging context
instead of accepting it as an argument, which is an architectural change to
`evaluate`'s signature and its two callers, not a guard. **Both are recorded as
the residual assumption rather than papered over with a check that would test a
third proxy.**

### What WAS built — one real gap, closed

The registry **advertises** a partition (`interior()` / `promotion_only()`,
`invariants.py:100,104`) which `concurrency_plan()` (`engine.py:124-127`)
publishes to the scheduler and O-3. The engine **enforces** its own filter at
`:109`. **Two expressions of one rule, in two files, with nothing asserting they
agree** — the same shape as the Python↔Rust canonical-bytes divergence, and a
drift would be **silent**: `concurrency_plan()` would publish a partition the
engine does not honour, and the scheduler would act on it.

Added to `tests/test_containment.py`:

- `test_engine_filter_MATCHES_registry_advertised_partition` — parametrized over
  **all three** classes, not just the two `gyza_model` happens to register.
- `test_NEGATIVE_CONTROL_a_divergent_partition_is_CAUGHT` — constructs a registry
  that lies about the partition and shows the comparison catches it, so the test
  above cannot be vacuously true.

**Power demonstrated, not asserted.** The engine's filter was deliberately
broken (`engine.py:109` → `if False:`) and the suite re-run:

```
FAILED test_cumulative_invariants_are_DEFERRED_in_the_interior_not_evaluated
FAILED test_engine_filter_MATCHES_registry_advertised_partition[CUMULATIVE]
3 failed, 28 passed
```

Restored byte-identical to HEAD; **31 passed**.

### B4 — nothing was weakened

No registration was accommodated, because nothing needed accommodating: no
registered invariant violates the constraint (A2).

---

## 3. What was NOT done, and why

**No separate defect commit**, because A found no shipped defect. Creating one
would have meant manufacturing a defect to satisfy the structure of the task.

**No load-time guard**, because there is no load-time configuration to guard
(§2). Adding one would be ceremony: a check that always passes, testing a
property nothing can set.

---

## 4. PART C — cannot run

C1 requires *"every remaining NONE-carried type"* and C2 a **second** prospective
use. Both fail on the tree:

1. **There is no first prospective use to be second to.** §0.
2. **The NONE bucket is unchanged and exhausted**: `execution_output_content`
   and `routing_match_quality`, both classified in the first census's Part C
   retrodiction. RESPEC-3 recorded this: *"there is no unclassified NONE-carried
   claim type left to test the criterion prospectively on."*
3. **Re-running the same selection rule would select `execution_output_content`
   again** — highest production call volume, 5 constructions vs 0 — and return
   **EXOGENOUS** again. That is not a second data point; it is the same one.

**C4 anticipated a refusal and called it a stronger result than another success.
That reading applies here at one remove:** the refusal is real, but it is
RESPEC-3's, already recorded, and re-deriving it would not add evidence.

> **A genuinely prospective test requires a claim type that does not yet exist in
> the registry.** It has to come from new vocabulary — a claim the system starts
> making — not from re-examining the two that remain. That is a real constraint
> on how this criterion can be validated further, and it is unchanged since
> RESPEC-3 reported it.

---

## 5. Honest limits

1. **"No production caller passes `Phase.INTERIOR`" is static analysis**, from
   grep over `gyza/` plus the two `evaluate` call sites. A dynamically dispatched
   or reflective call would not appear. Given two call sites and a small
   containment layer, I judge the risk low — **authored judgement, not
   measurement.**
2. **The new test pins agreement between two expressions of the rule. It does
   not validate either against the protected quantity** (B2). If both the tag
   and the engine were wrong in the same direction, the test would pass.
3. **A5's "unnecessary serialization" is not quantified.** No throughput cost was
   measured; the claim is that concurrency licensed by C6 is unused, not that
   using it would be faster by any particular amount.
