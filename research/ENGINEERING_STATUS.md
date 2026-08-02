# Engineering status — the phase handoff

Input to the open-problem document. Written to be honest about gaps rather than
tidy. Every "BUILT" names the test that demonstrates it; every "PARTIAL" names
the specific gap.

## 1. The central engineering results of the phase

**Two findings, and they are the same species: an isolated number that shrinks
once you ask the system-level question.** Neither is a caveat on the other;
both are results.

> **THE ISOLATED NUMBER IS NOT THE SYSTEM NUMBER.**
>
> | | isolated | system-level |
> |---|---|---|
> | **verifiability** | 61.1% of claim types are tier-1 | **0.9%** of depth-8 chains are tier-1 |
> | **harm coverage** | 3 harm classes declared, bounded, and enforced | **13.3%** — 2 of 15 stateful action types move any declared quantity |
>
> Both were reported as the isolated number first, and in both cases the
> isolated number is the one a reader takes as the capability claim.

### 1a. Verifiability does not survive composition, and the ceiling on fixing that is low

| | tier-1 | tier-3 | any correctness claim |
|---|---|---|---|
| **isolated (one claim)** | **61.1%** | 22.2% | 77.8% |
| chains of depth 2 | 30.9% | 47.8% | 52.2% |
| chains of depth 4 | 9.5% | 72.8% | 27.2% |
| **chains of depth 8** | **0.9%** | **92.6%** | **7.4%** |

61.1% coverage in isolation is **0.9% at depth 8**. Upgrade *every* TEST and
SPEC claim type to PROOF — the most representation work can possibly buy — and
depth-8 tier-1 reaches **13.4%**; 86.6% of depth-8 chains stay tier 3.

The reason is structural: **4 of 18 claim types are semantic** (output content,
memory relevance, routing quality, external send content), their correctness is
the competence bound, and **any chain touching one inherits tier 3**. The
binding constraint is not verifier quality. It is the shape of the claim
vocabulary.

*(ANALYTIC, under a uniform-chain-sampling assumption. Real chains are not
uniform; this is a shape argument, not a forecast.)*

### 1b. The declared harm model covers 13.3% of the stateful action vocabulary

`selection_routes/unmeasured_actions.json`. For each action type, apply it and
ask whether any **declared** harm quantity moves.

| | |
|---|---|
| action types in the C-3 vocabulary | 19 |
| changing state | 15 |
| **moving any declared harm quantity** | **2 (13.3%)** — `settle_credits`, `reserve_credits`, both via H1 |
| **moving none** | **13 (86.7%)** |

**Two of the three declared harm classes have no action in the vocabulary that
moves them at all.** The action vocabulary and the harm model are largely
**disjoint**: H2 (market capital) and H4 (authority) are declared, bounded, and
never touched by anything the system does.

Sound in one direction only — a gap found is definite; a gap not found proves
nothing (R12). The unmeasured 13 are enumerated with proposed quantities in
`HARM_MODEL_GAP.md`; roughly two thirds are declarable today and the rest are
the competence bound reappearing in the harm model.

Two corollaries that changed what got built: **depth is the exponent**, so a
decomposer should minimise depth before improving per-subtask tier; and **tier
is not a composition budget** — a tier-1 claim whose verifier is a unit-test
suite forces its whole chain to tier 3.

## 2. Component inventory

### Substrate
| id | status | demonstrated by / gap |
|---|---|---|
| S1 append-only event store | **BUILT** | `test_staging.py::test_log_has_no_update_and_no_delete_api`, `::test_log_is_tamper_evident` |
| S2 capability attenuation | **BUILT** (pre-existing) | `verify_delegation`, `gyza/economy/delegation.py:213-289` |
| S3 provenance envelopes | **BUILT** (pre-existing) | `gyza/icp.py` |
| S4 sandbox enforcement | **PARTIAL** | empty-record hole **closed** (`test_containment.py::test_empty_enforcement_record_is_rejected_as_incomplete`). **GAP: the fail-open default is not flipped.** `require_enforcement` exists and is refusable, but defaults False because 18 test files drive the runner with non-sandboxing executors. Production entry points must set it explicitly. |
| S5 reproducible builds | **NOT-BUILT** | `S5_SPEC.md`; critical path is a second independent rebuilder (user-owned) |

### Containment (C-1 … C-8) — all BUILT
`test_containment.py` (25 tests), `test_staging.py` (20). Highlights: unset
bound fails closed; untagged invariant rejected at load; unknown action type ⇒
IRREVERSIBLE; cumulative invariants **deferred** in the interior and evaluated
only at the serialized gate; rollback preserves content where mutable storage
loses it; guard config refuses self-modification **and** downgrade.

### Verification (V-1 … V-5) — all BUILT
`test_verification.py` (15). Tier router makes **zero model calls** (asserted
under a network block, with a negative control proving the block detects one);
V-4 **refuses model-authored specs**; V-5 reports strength as a position between
floor and ceiling and returns "uninterpretable" for a bare number.

### Coordination (K-1 … K-8)
| id | status | note |
|---|---|---|
| K-1 task representation | **BUILT** | carries CARRIER alongside tier |
| K-2 decomposer | **STUB (raises)** | SR-1 blocked — see §4 |
| K-3 allocator | **BUILT** | round-robin, per SR-2 |
| K-4 executor pool | **BUILT** | concurrency from invariant CLASS, never carrier |
| K-5 combiner | **BUILT** | consults TIER_ALGEBRA; one TEST stage ⇒ tier 3 |
| K-6 scheduler | **BUILT** | per-carrier depth caps, cumulative serialization, per-action promotion |
| K-7 retry | **STUB (raises)** | SR-4 blocked — see §4 |
| K-8 termination | **BUILT** | four explicit states, **no TIMEOUT member** |

### Interface / observability
H-1 **BUILT** (refuses an escalation with no cited bound or no provenance);
O-1 **BUILT** (pre-existing); O-2, O-3 **BUILT** (`test_coordination.py`).

## 3. Selection routes

| route | status | decision |
|---|---|---|
| SR-1 decomposition | **BLOCKED** | corpus provides tasks, not decompositions; generating them needs goals I author → the R14 B4 trap |
| **SR-2 allocation** | **CLOSED** | **round-robin.** Type-routed measured **13 pp WORSE** (0.3261 vs 0.4565). The finding is about the **taxonomy**: two claim types cannot discriminate four handlers, so type-routing commits to one where round-robin diversifies. Gap to oracle 0.2391; oracle itself only 0.5652, so 43% is an escalation floor no allocator moves. |
| **SR-3 tier algebra** | **CLOSED** | **carrier-dominated.** PROOF 1.000, SPEC 1.000, **TEST 0.000** |
| SR-4 retry | **BLOCKED** | the cached substrate is temperature-0 single-sample, so retry is *definitionally* identical; measuring it needs new stochastic generations |
| **SR-5 promotion granularity** | **CLOSED** | **per-action** (Occam; per-task within the equivalence bound and 3.7× cheaper per promoted action if gate cost matters) |
| **SR-6 depth cap** | **CLOSED (DERIVED)** | per **carrier**: PROOF/SPEC none, TEST/NONE 10 |

## 4. The type-assignment finding

**Assigning a claim type to a task is itself a tier-3 claim.** The router is
sound *given* a type; nothing verifies the type is right, and nothing mechanical
can.

Measured two ways, and the first is an artifact:

- A keyword assigner scored **0.0000 disagreement** against the audited types.
  **DEFINITIONAL** — I wrote the goal strings *and* the keyword rules. It
  measures my authorship, not the problem. Reported as not-measurable.
- The measurement that can fail: **196 of 196 external artifacts carry more than
  one legitimate claim type from *identical* source text** (`is it correct?`
  vs `does it pass these tests?` over the same program). The *rate* is
  definitional; the **ceiling of 0.5 for any text-based assigner is structural**,
  because the source text is externally authored and simply does not contain the
  distinction.

The consequence for the architecture: the verified tier needs a human-audited
**type assignment per task** — per *task*, not per *type*. C11's affordable
cost model (one spec per type) does **not** extend to type assignment.

## 5. What the system can do today

It runs a task through a kernel-enforced sandbox, refuses to sign unless
enforcement is no wider than the signed manifest, and emits a provenance chain
any third party can verify offline with no trust in the producing machine. That
part is unqualified.

**Its containment claim is narrower than that sentence suggests, and the honest
form is:** the system bounds **declared** harm classes against **declared**
bounds — and the declared model currently covers **13.3% of the stateful action
vocabulary** (2 of 15 action types). Two of its three declared classes have no
action that moves them at all. Deletion, key rotation, delegation, storage
growth, guard-configuration updates, and every form of emission move **no
declared quantity**.

Within that scope the machinery is real and demonstrated: conservation and
monotone invariants evaluate concurrently in an append-only interior while
cumulative ones evaluate only at a serialized promotion gate; rollback restores
interior state without losing content; the constrained system cannot rewrite its
own guard configuration; claims route to a verification tier with zero model
calls; model-authored specs are refused; a measured tier algebra is consulted
before a deep chain is permitted; and a refusal escalates with the specific
bound that would be exceeded. 785 Python tests, 94 Rust, the Go suite.

**A reader who takes this section as a capability claim is being misled.** The
mechanism is built; the model it enforces is 13.3% of the vocabulary.

## 6. What it cannot do today

It cannot tell you whether any output is *correct* — the competence bound,
closed across six mechanism families and terminal. It cannot bound harm it was
not told about: **13 of 15 stateful action types move no declared quantity**, so
for those the system provides attribution and containment-of-authority but no
harm bound at all. It cannot bound the *consequence* of an emission even in
principle, only the count — after emission there is no containment and no
detector helps. It cannot verify that the claim type attached to a task is the
right one, so the whole tier apparatus rests on a human judgement it cannot
check, and the ceiling for any text-based assigner is 0.5. It cannot keep a
correctness claim across a deep chain: at depth 8, 92.6% of uniformly-drawn
chains are containment-only, and no representation work moves that past ~13%. It
cannot decompose a task or decide when to retry — both stubs, both blocked on
evidence rather than effort. It cannot prove the runner that stamped an
enforcement record is the runner whose source you read (S5). And it has never
been run by anyone other than its author.

## 7. The three things gating value

1. **E1 shipping.** `main` has been merged locally and unpushed for four
   sessions. This is a user decision, not a task.
2. **An external user.** BUILD_PLAN §7's last criterion, outstanding longest,
   and it cannot begin until (1).
3. **S5.** Until it exists, "oracle-free" carries an asterisk, and the critical
   path is a second independent rebuilder — user-owned, like the other two.

All three are user-owned. **No amount of further engineering moves any of them.**
