# Respecification 3 — a REFUSAL, and why the refusal was foreseeable

**Result: the selected claim type classifies EXOGENOUS. Respecification is NOT
licensed for it. Nothing was built.**

Zero credits. No code changed; no producer wired; no verifier written.

---

## B1 — the NONE list, complete, reported before selection

`gyza/verification/adapters.py:178-181`. **The bucket has exactly two members:**

| # | claim type | cited producer | line |
|---|---|---|---|
| 1 | `execution_output_content` | `gyza/runner.py:374` | 179 |
| 2 | `routing_match_quality` | `gyza/demand.py:35` | 180 |

### Both citations are STALE — found while verifying, not sought

| cited | what is actually there |
|---|---|
| `runner.py:374` | `valid, first_bad = verify_chain(ancestors_chain)` — chain verification, not output production |
| `demand.py:35` | `class LSHIndex:` — a class definition, not routing |

Line drift, the same species CLAUDE.md's own §7 warns about. **Real producers:**
`execution_output_content` ← `AgentRunner._execute` (`runner.py:404`) and
`_complete` (`runner.py:571`); `routing_match_quality` ← `DemandOracle`
(`demand.py:92`).

## B1 — selection by the preregistered rule

**Rule, fixed before candidates were inspected:** *highest production call
volume among NONE-carried types, tie-broken by earliest definition in the file.*
It selects on **impact**, which is orthogonal to tractability — the point being
that selecting on tractability would make success prove nothing.

| | `execution_output_content` | `routing_match_quality` |
|---|---|---|
| producer | `AgentRunner._execute` / `_complete` | `DemandOracle` |
| producer constructed in `gyza/` | **5 sites** (`AgentRunner(`) | **0 sites** |
| producer method call sites (non-test) | `_complete` 9, `_execute` 2 | `compute_deficit` 2, `should_spawn_replica` **0** |
| runs on | **every work item** | never, in production |

> ### SELECTED: `execution_output_content`. No tie; the tie-break was not needed.

**Diagnosing the exact zero**, because a 0 is a suspected artifact until shown
otherwise: `DemandOracle` is **dependency-injected** into `supervisor.py`
(parameter at `:153`, used at `:288` and `:295`) and **constructed nowhere in
`gyza/`** — only in tests. The zero is real, not a grep artifact. The codebase
already documented the pattern at `supervisor.py:7`: *"`DemandOracle.
should_spawn_replica` existed but had zero callers."*

> **`routing_match_quality` is a registered claim type whose PRODUCER NEVER RUNS
> IN PRODUCTION.** That is the consumption gap on the producer side, and it means
> the type could not be demonstrated even if it were respecifiable.

---

## B2 — the criterion's verdict: **EXOGENOUS. NOT LICENSED.**

Frozen criterion, `research/census/PREREGISTRATION_CENSUS.md` §2, unchanged.

**The claim:** *the output of this execution is correct.*

| | |
|---|---|
| **Q1** — no fact of the matter? | **No.** For a given task the output is right or wrong; a competent party could settle it by doing the work. → not CONTESTED |
| **Q2** — evaluable over stored state + fields the claim names? | **No.** Correctness requires the intended semantics, which live in `item.description` — natural language. Evaluating "does this output satisfy this description" **is** the competence bound |
| **Q3** — would naming more parameters make Q2 YES, without an outside fact? | **No**, and this is the load-bearing step |
| **Q4** | → **EXOGENOUS** |

**Why Q3 fails, from the committed record rather than fresh reasoning.**
`adapters.py:170-172` states it: restating as *"output hash = H, checkable by
re-execution"* verifies **reproducibility** and **discards exactly the property
wanted — a deterministic wrong program passes every time.** That is **claim
substitution, not parameter addition**, and Q3 permits only the latter.

> **Respecification is NOT licensed. Forcing one would be the rule-3d failure:
> verifiable because it no longer asks for anything useful.** Reported and
> stopped, per B2.

### This is NOT the criterion's first prospective use — correcting the task's framing

The task states this would be *"the criterion's first PROSPECTIVE use"* and that
*"every prior application was retrodiction."* **That is not what happened, and
the reason is structural.**

`execution_output_content` was **already classified EXOGENOUS twice**: once in
the first census's Part C retrodiction, and again as index 17 of the Gyza
vocabulary census. **The criterion returned the answer it had already given, on a
claim it had already seen.**

The honest selection rule caused this, not evaded it: **the NONE bucket has two
members and BOTH were classified in the first census.** So:

> **There is no unclassified NONE-carried claim type left to test the criterion
> prospectively on. The bucket is exhausted for that purpose.**

A genuinely prospective test needs a claim type that does not yet exist in the
registry — which means it must come from new vocabulary, not from re-examining
the old. That is a real constraint on how the criterion can be validated
further, and it is worth more than the refusal itself.

---

## B3 / B4 — not reached

No parameters named, no verifier written, no power demonstration attempted.
**B4's binding standard — the verifier must fail on a REAL divergence — was never
in play**, because no verifier was built. Manufacturing one to satisfy the form
would have been the rule-3d failure the refusal exists to prevent.

## B5 — the consumption question, moot but reported

Nothing was built, so nothing emits and nothing consumes. The triple is unchanged
from the prior session:

| | |
|---|---|
| composable | **0.8333** (12 PROOF + 3 SPEC of 18) |
| emitted, production | **0.0000** — send-claim emission removed; retrieval opt-in and never requested |
| consumed, production | **0/0** — no claim is produced, so there is nothing to consume |

**The decision B5 demanded was made and it decided against building.** No
write-into-a-void was created because no producer was wired.

---

## What this session actually produced

The refusal was foreseeable — arguably it was already on record — so the value
is in the three things found while verifying rather than in the verdict:

1. **Both NONE-list citations are stale** (`runner.py:374`, `demand.py:35`). A
   registry that cites the wrong lines is an unenforced invariant: the citation
   is documentation with no mechanism checking it.
2. **`routing_match_quality`'s producer is never constructed in production.** The
   consumption gap has a mirror on the producer side, and this is a second
   instance of the pattern the prior session found in `last_send_claim`.
3. **The NONE bucket is exhausted for prospective criterion-testing.** Both
   members are pre-classified, so no re-selection within the bucket could have
   produced a prospective test — which is also why re-selecting after seeing this
   result would have been pointless as well as forbidden.

**The rule was not re-run after seeing the outcome.** B1 fixed the rule before
inspection, the rule selected `execution_output_content`, that type refused, and
the refusal is the result. A method that only works on types chosen after
inspection is not a method.

## Honest limits

1. **The refusal is not new information.** DR recorded it; the census confirmed
   it twice. This session re-derived it under a selection rule that could not
   have chosen otherwise. **It demonstrates the criterion is consistent, not that
   it is predictive.**
2. **"Production call volume" was measured by static call-site counting**, not by
   instrumentation. A site inside a rarely-taken branch counts the same as one on
   the hot path. The gap here (5 constructions vs 0) is wide enough that the
   crudeness does not change the ordering, but a closer contest would need real
   counts.
3. Point 1 above (**stale citations**) is reported, **not fixed** — fixing it is a
   separate change and does not belong in a respecification write-up.
