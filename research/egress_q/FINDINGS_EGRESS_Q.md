# Scoping the egress checker — is q measurable, and for what?

**Branch `egress-q`.** **ZERO CREDITS SPENT.** Scoping only; no generation, no
measurement run. §B4 reports a costed design and **stops**.

---

## 0. Two premises corrected before scoping

| stated | tree |
|---|---|
| "the **eight** EGRESS action types" (×6 in the task) | **SIX.** `coverage.json` → `external_send`, `publish_agent`, `publish_attestation`, `publish_delta`, `send_message`, `write_outside_sandbox` |
| the residue is the egress types | the residue is **9** = **6 EGRESS + 3 IRREVERSIBLE** (`delete_artifact`, `rotate_key`, `update_guard_config`) |

**Eleventh premise of this shape.** The scoping below covers the **six** that
exist.

**One thing the task gets exactly right, and it is worth confirming:** unlike the
action-type *tags*, the egress **operations** are genuinely live in production —
`settlement.py:535,833,992`, `global_cluster.py:521`,
`network_blackboard.py:521`, `cli.py:1539`. **The emissions run; the vocabulary
that would classify them does not.**

---

## 1. PART A — WHAT AN EGRESS CLAIM ASSERTS

### 1a. The six, decomposed into INTEGRITY and CORRECTNESS

| # | action | production call site | INTEGRITY component | CORRECTNESS component |
|---|---|---|---|---|
| 1 | **`external_send`** | claim type `external_send_content` (ungoverned — in the migration gap) | **ALREADY CHECKED**: `blake3(emitted) == artifact_hash` and byte count, `respec.py:204` | *was sending this artifact, to this destination, now, right?* |
| 2 | **`send_message`** | `settlement.py:535, 833, 992` | checkable: payload hash | *is this the correct protocol message, to the correct peer, at this protocol state?* |
| 3 | **`publish_delta`** | `network_blackboard.py:521` | checkable: delta bytes | *does this delta faithfully represent the local write?* |
| 4 | **`publish_agent`** | `global_cluster.py:521` | checkable: advertisement bytes | *should this agent be advertised, with these attributes, now?* |
| 5 | **`publish_attestation`** | `cli.py:1539` | checkable: k-of-n cert signatures | *does the agent actually have the attested capability?* |
| 6 | **`write_outside_sandbox`** | **NONE — appears only in `reversibility.py:54`** | — | **no claim exists** |

> **`write_outside_sandbox` is not an action this system performs. It is one the
> sandbox exists to PREVENT.** It has no implementation and therefore no claim,
> no checker, and no q. Counting it as an egress type whose q must be measured
> was a category error in my own vocabulary, and it is reported rather than
> quietly dropped.

### 1b. A3 — THE FROZEN CRITERION, APPLIED VERBATIM

From `research/claims_corpus/PREREGISTRATION_CLAIMS_CENSUS.md:28-47`, unmodified:

```
Q1. Is there a fact of the matter at all — could two competent parties
    disagree with no procedure that settles it?      -> CONTESTED
Q2. Can the success condition be written as a function of
    (a) state THIS SYSTEM stores, and
    (b) fields the CLAIM ITSELF names?               -> INTERNAL
Q3. Does a success condition exist, and would NAMING MORE PARAMETERS
    make Q2 answer YES, without acquiring any new fact
    from outside the system?                         -> UNDERDETERMINED
Q4. Otherwise                                        -> EXOGENOUS
```
> **THE CONSERVATIVE DIRECTION IS BINDING.** Where a referent cannot be resolved
> to stored state by inspection, classify **EXOGENOUS**.
> **Q3 is parameter ADDITION, never claim SUBSTITUTION.**

**Applied to the CORRECTNESS component only:**

| action | class | why |
|---|---|---|
| **`publish_delta`** | **INTERNAL** | the delta is a **derived function of the local write**. `payload == diff(local_state, last_published)` is a function of stored state and fields the delta names. Q2 = YES |
| **`send_message`** | **INTERNAL** | the settlement protocol is a **state machine over stored ledger state**; the correct message type and the correct `payer_peer_id` are both determined by the entry being settled. Q2 = YES (counterfactually — no such checker is written) |
| **`external_send`** | **EXOGENOUS** | see §1c |
| **`publish_agent`** | **EXOGENOUS** | the attributes are derived, but *whether to advertise* is discretionary and no stored predicate settles it. Conservative direction binds |
| **`publish_attestation`** | **EXOGENOUS** | the cert's signatures are internal; the asserted **capability** is a claim about future behaviour — the competence bound, terminal |
| `write_outside_sandbox` | **NO CLAIM** | no implementation |

### 1c. The crux — why `external_send` is EXOGENOUS and not UNDERDETERMINED

**This is the tempting classification and the frozen rule forbids it.**
`SendClaim` already names `policy_id` and `destination` (`respec.py:160-172`),
so it looks like "store the policy and Q2 answers YES" → UNDERDETERMINED.

> **But substituting *"complies with policy P"* for *"was the right thing to
> send"* is CLAIM SUBSTITUTION, and Q3 permits only parameter ADDITION.** The
> criterion was frozen long before this question existed. Under it, the
> unrestricted correctness claim's referent cannot be resolved to stored state,
> so the conservative direction binds: **EXOGENOUS**.

`respec.py:196-199` independently reaches the same place — `policy` is
caller-supplied precisely because *"a policy this module wrote for the sends
this module checks would be the tautology the header warns about."*

### 1d. A4 — DISTRIBUTION, and the zero diagnosed

| class | n | fraction |
|---|---|---|
| **INTERNAL** | **2** | 0.333 |
| **EXOGENOUS** | **3** | 0.500 |
| **UNDERDETERMINED** | **0** | **0.000** |
| CONTESTED | 0 | 0.000 |
| NO CLAIM | 1 | 0.167 |

**It is NOT all-EXOGENOUS, and that is the useful finding: egress is not
monolithic.** The line that actually separates them is **protocol-determined vs
discretionary emission** — where the payload is a derived function of stored
state and the protocol fixes *when* to send, correctness is mechanically
decidable; where the payload encodes a claim about the world or the decision to
send is discretionary, it is not.

**Diagnosing UNDERDETERMINED = 0** (the census preregistration §4 requires this):

- The preregistered vagueness check uses a **prose term list** (`slow`, `wrong`,
  `should`…) built for a GitHub-issue corpus. **It does not transfer** to
  code-level claims with no prose. Stated rather than applied mechanically to
  something it was not built for.
- **The honest diagnosis is the opposite of "I resolved vagueness":** I applied
  Q3's substitution ban **strictly**. Had claim substitution been allowed,
  `external_send` would classify UNDERDETERMINED, respecification would be the
  licensed lever, and the frontier would look considerably better. **The rule
  forbids it, and the rule predates the question.**
- **n = 6.** A zero in a six-cell classification is **weakly powered** whatever
  its cause, and the counter-metric is that **two cells came back INTERNAL**, so
  the criterion is not simply refusing everything.

---

## 2. PART B — IS q MEASURABLE?

### 2a. B1 — the candidate checkers, with the quantity each decides

| action | checker | decides | model needed? |
|---|---|---|---|
| `publish_delta` | recompute `diff(local_state, last_published)` and compare | **CORRECTNESS** | **no — mechanical** |
| `send_message` | replay the settlement state machine over stored entries; compare message type + peer | **CORRECTNESS** | **no — mechanical** |
| `external_send` | `verify_send_claim` | **INTEGRITY ONLY** | no |
| `publish_agent` | recompute advertised attributes from local state | **INTEGRITY of the attributes**, not correctness of the decision to advertise | no |
| `publish_attestation` | verify k-of-n signatures | **INTEGRITY ONLY** | no |

> **THE TRAP, CONFIRMED PRESENT.** For `external_send` — the type the frontier's
> egress rows are really about — **the only implemented checker decides
> INTEGRITY.** `verify_send_claim` recomputes `blake3` of the bytes that left. It
> would score **q ≈ 1**, and reporting that as the frontier's q would replace
> *"was this the right thing to send"* with *"were these the bytes I said"*.
> **They are different claims and only the second is checked.**

### 2b. B2 — ground truth: **none exists, and inducing it is the thing the architecture forbids**

- **Historical egress events with known-false claims: ZERO.** There is no egress
  event log carrying a truth label anywhere in the tree. The blackboard stores
  envelopes, not adjudicated outcomes. **DEFINITIONAL — the field does not
  exist**, so the count is zero by absence of a schema, not by a search that
  came up empty.
- **Induced false claims on the live mesh: NOT SAFE, and the reason is this
  program's own result.** The public `gyza.network` mesh is live (3 VPSes).
  **Containment ends at emission** (C15) — an induced false egress cannot be
  taken back, only attributed. Deliberately emitting known-false claims to a
  live public mesh to measure a detector is precisely the harm the detector
  would be measuring.
- **Induced on a loopback mesh: SAFE, and worthless for this purpose.** Two local
  daemons can be driven to emit anything. But the *correctness* of an egress is a
  fact about a **counterparty and a context**, and a synthetic mesh supplies both
  from the same hand that writes the ground truth. **That is the R14 Part B4
  failure**: the harness author would be measuring the harness.

> ### **q FOR THE EXOGENOUS EGRESS TYPES IS UNMEASURABLE FOR THIS SYSTEM.**
> Not "unmeasured" — **unmeasurable**, with no safe path to ground truth.

**For the two INTERNAL types the situation is completely different**, and the
asymmetry is the result:

### 2c. B3 — f, treated equally to q

| action | q | f | LR = q/f |
|---|---|---|---|
| `publish_delta` | **1.0 by construction** — recompute-and-compare is total | **0 by construction** — a correct delta always matches | **unbounded** |
| `send_message` | **1.0 by construction** (if written) | **0**, modulo protocol nondeterminism | **unbounded** |
| `external_send` (correctness) | **undefined — no checker** | **undefined** | **undefined** |
| `publish_agent` (correctness) | undefined | undefined | undefined |
| `publish_attestation` (correctness) | undefined | undefined | undefined |

**Diagnosing the q = 1.0 / f = 0 pair: DEFINITIONAL, not measured, and it is the
same species the trap warns about.** A recompute-and-compare checker is total
over the property *"the payload equals the function of stored state"*. It is
sound **only because that property IS the correctness claim for those two
types** — which §1b established, and which does **not** hold for the other three.

> **Where a checker exists, LR is unbounded and the audit economics are
> trivially feasible. Where the frontier's egress rows actually bite, there is no
> checker at all.** The borrowed q was applied uniformly across both groups.
> **That uniformity is the error the frontier carries.**

### 2d. B4 — the costed design: **there is none to cost**

No measurement is proposed, so **no credit gate is reached and nothing is
spent**:

- the two INTERNAL types need **no measurement** — write the checker and its q/f
  are definitional (an engineering task, zero credits, not scoped here);
- the three EXOGENOUS types have **no ground truth and no safe way to induce
  it**, so there is nothing to cost.

**A measurement I could have costed and will not:** generating synthetic egress
scenarios with an LLM judge as ground truth. That would measure **the judge**,
inherits the competence bound wholesale, and would produce a number for the
frontier that looks measured and is not. **Reported so it is not re-proposed.**

---

## 3. PART C — WHAT THIS MEANS FOR THE FRONTIER

### C1. The verdict is **SPLIT**, which none of the three offered options covers

| group | verdict |
|---|---|
| **`publish_delta`, `send_message`** (INTERNAL) | **q MEASURABLE — trivially, and by construction rather than by experiment.** No frontier row is needed: a total mechanical checker makes the audit question moot |
| **`external_send`, `publish_agent`, `publish_attestation`** (EXOGENOUS) | **q UNMEASURABLE.** No ground truth, none safely inducible. `external_send` additionally exhibits the trap: its implemented checker decides **INTEGRITY ONLY** |
| `write_outside_sandbox` | **no claim exists** |

**So the honest answer is C1's second and third options simultaneously, applied
to different types.** Reporting a single verdict for "egress" would repeat the
error the frontier already made.

### C2. What the frontier can still honestly claim

> **The egress rows are a SHAPE, not a contract.**
>
> They show how the required audit rate moves with `q`, `g/w` and `B`. They do
> **not** state the audit rate for Gyza's egress, because **`q` for the egress
> types that matter is not merely unmeasured — it is unmeasurable for this
> system.** The rows are marked ASSUMED; on this scoping they should be marked
> **UNVALIDATABLE**, which is stronger and more accurate.

**And the direction of the error is the unfavourable one.** If real egress
correctness-q is below the borrowed 0.5/0.2 probes — and for a discretionary
"should I have sent this" judgement it very likely is — **the 1e-4 tier moves
toward the 1e-6 tier's verdict: human gate rather than audit rate**, exactly as
the task anticipated.

### C3. What an audit of egress buys: **deterrence, not prevention**

The reversibility correction bears on this directly and sharpens it:

- **No egress action is reversible** — 0 of 19 action types have a per-action
  undo, and egress additionally leaves modelled state entirely.
- **Past the promotion gate there is no recovery at all.**

> So a false egress claim detected after the fact **cannot be remedied — only
> attributed and settled.** An audit of egress buys **deterrence** (a rational
> actor's expected cost) and **non-repudiation** (who is answerable). **It buys
> no prevention whatsoever.**
>
> And deterrence requires a feasible mechanism, which requires `LR ≥ g/w`, which
> requires a measurable `q`. **For the three EXOGENOUS egress types there is no
> q, so there is no demonstrable deterrence either — only attribution.**

**That is the strongest honest statement available: for discretionary egress,
Gyza offers non-repudiation. It does not offer a bounded error rate, and the
frontier should not be read as though it does.**

---

## 4. What this does not establish

1. **The INTERNAL classification of `send_message` is COUNTERFACTUAL.** Q2 asks
   whether the check *could* be written; **no such checker exists**. Calling its
   q "1.0 by construction" describes a checker nobody has built.
2. **n = 6**, and one cell is a category error (`write_outside_sandbox`). Every
   fraction here is weakly powered.
3. **The INTERNAL/EXOGENOUS line is authored judgement** — protocol-determined
   vs discretionary. I find it principled and it maps onto Q2, but a different
   reading of "was the right thing to do" for `publish_delta` (should I gossip
   *at all*?) would push it to EXOGENOUS too.
4. **Nothing here measures anything.** It is a scoping document, and its
   conclusion is that the measurement the frontier needs cannot be safely made.
