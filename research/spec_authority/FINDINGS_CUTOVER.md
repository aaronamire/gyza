# The cutover — the router now reads the attested registry

**Branch `registry-cutover`.** Zero credits. No attestation authored.

---

## 0. GATE 0 — the reconciliation, and three premises that failed

### 0a. **The collapse described does not exist. Nothing was lost.**

| stated | tree |
|---|---|
| "the governed registry holds **20** attested entries" | **14** registered, from **18** drafts |
| "the manifest listed **21** entries" | **18** |
| "`envelope_dag` and `session_dag` both map to claim type `dag_verified`" | **`dag_verified`: 0 hits. `session_dag`: 2 hits — both in my own findings recording that it does not exist.** All **18** draft claim types are **unique**; no collapse occurred |
| "`credits_conserved`" | **3 hits, all in my own findings recording that it does not exist** |
| "the four PROOF→TEST corrections … changed carrier during migration" | **no carrier changed. 0 mismatches** (0c) |
| "the analyzer reached SCREENING-ONLY at **1/4 recall**" | committed: **2/16 flagged, 0 true positives, precision 0.0000** |

**Ninth premise failure of this shape.** Gate 0a asked whether a lossy collapse
blocks cutover: **there is no collapse, so it does not.** Verified by executing
the uniqueness check, not by reading the manifest.

### 0b. **FULL COVERAGE COMPARISON — a real gap of exactly 2**

| | n | claim types |
|---|---|---|
| **in BOTH** | **14** | `artifact_content_address`, `balance_fold`, `delegation_attenuation`, `enforcement_within_manifest`, `envelope_chain`, `envelope_signature`, `hlc_ordering`, `ledger_entry_signatures`, `manifest_identity`, `market_capital_fold`, `memory_retrieval_relevance`, `reputation_score`, `unit_test_execution`, `work_claim_exclusivity` |
| **ONLY governed** | **0** | — |
| **ONLY ungoverned** | **2** | **`envelope_dag`, `external_send_content`** |

> **The sets are NOT identical, so per B3 the fallback CANNOT be removed.** The
> difference is the remaining migration work, and it is named entry by entry in
> §2.

**Diagnosing the exact 0 (ONLY-governed):** **DEFINITIONAL.** Every draft is
derived from an existing registry entry, so the governed set is a subset of the
ungoverned one by construction. A non-zero value here would have meant a spec
was invented during migration.

### 0c. **CARRIER PARITY — 0 mismatches across all 14**

Every governed carrier equals what the ungoverned registry already held:
11 PROOF, 3 SPEC, 1 TEST (`unit_test_execution`).

> **So the prompt's central claim for A3 is false: NO type changes carrier, and
> the router's behaviour changes for NO type on this axis.** There is no
> PROOF→TEST correction to report, because none occurred.

**Diagnosing the exact 0, and it is the honest part:** **MEASURED, but NOT
independent confirmation.** I classified the drafts with the pre-existing
carriers visible in the same inventory. Agreement is **consistency, not
corroboration.** It is pinned by test anyway, because a *disagreement* would be
a real defect — the test earns its place on the failure it would catch, not on
the pass it currently reports.

### 0d. **Zero credits.** No generation.

---

## 1. PART A — THE ROUTER IS WIRED

### A1. What it read before

`TierRouter.route` consulted `VerifierRegistry` then `PartialSpecRegistry`
(`gyza/verification/router.py`). Since last session it *could* accept an
`authority` and a `CutoverPolicy` — but **nothing ever passed one.** Fourteen
attested records governed nothing.

### A2. The live construction point

**`gyza.verification.migration.governed_router()`** builds the router from the
attested registry. **The router reads the carrier off the attested record** —
`test_the_routers_carrier_comes_FROM_the_attested_record` asserts equality for
all 14, so one record governs rather than two sources agreeing by luck.

**Default policy: `FAIL_CLOSED`**, and not because it is the safe default. The
two types outside the governed set are blocked because **their success
condition is not fixed by the registry** — the verifier proves a different
proposition depending on the call site. **Tier 3 is the correct verdict for
those, not a conservative one.** Under DUAL_READ they would keep tier 1 on a
carrier claim nobody attested, which is the state the authority exists to end.

### A3. Per-type behaviour change

| | before (ungoverned) | after (governed, FAIL_CLOSED) |
|---|---|---|
| the 14 governed types | tier 1/2 at their carrier | **identical tier, identical carrier** — now sourced from an attested record |
| **`envelope_dag`** | tier 1, PROOF | **tier 3, NONE** |
| **`external_send_content`** | tier 1, PROOF | **tier 3, NONE** |
| `execution_output_content`, `routing_match_quality` | tier 3 | tier 3 — unchanged |

> **Two types lose tier 1, and it is a CORRECTION, not a regression.** Neither
> lost it for a carrier reason. Each lost it because the registry cannot say
> *which proposition* the verifier proves: `_envelope_dag` forwards `**kw` to
> `verify_dag`, whose `require_closed` defaults False and which production calls
> **both ways**; `verify_send_claim`'s `policy` defaults to `None`, and the
> policy clause is then **skipped**. A tier-1 claim that cannot name what it
> proved was never worth what it said.

**A4 — nothing broke. 193/193 pass**, including the pre-existing
`test_verification`, `test_registry_execution`, `test_respecification` and
`test_containment` suites. **The reason nothing broke is itself the finding:**
no production path constructs a router, so there was nothing relying on the two
downgraded entries. Had something broken, that would have been information;
that nothing did is a measure of how little was wired.

---

## 2. PART B — THE FALLBACK

### B1. **The expiry test the task refers to does not exist, and that is the finding**

> **DUAL_READ shipped with MARKING and COUNTING but NO TERMINATION CONDITION.**

`test_dual_read_falls_back_and_MARKS_the_fallback` asserts the routing reason is
prefixed; `TierRouter.governance` counts fallbacks and names them. Its docstring
says *"an unmarked fallback is a fallback that never expires."* **Marking and
counting are visibility. Neither is an expiry condition, and none was written.**

> **This is an unenforced invariant inside the mechanism built to enforce
> invariants** — the species this program has recorded repeatedly, occurring in
> the code that records it. B4's question — *is the expiry condition as
> originally written now satisfiable?* — has the answer: **it was never
> written**, so it was neither satisfiable nor unsatisfiable.

### B2/B3. The gap is real, so the fallback STAYS — with named, finite scope

**`fallback_scope()` is the condition that was missing.** It enumerates exactly
what the fallback still covers, and **the fallback may be removed when it
returns `{}`** — not before.

| claim type | what it needs |
|---|---|
| **`envelope_dag`** | bind `require_closed` at the adapter, or split into two claim types (closed / not-closed). Production uses both settings, so one entry cannot serve both |
| **`external_send_content`** | bind `policy`, or split hash+length from hash+length+policy |

**Counter-metric to the gap:** **4 types fail closed, but only 2 are fallback
scope.** `execution_output_content` and `routing_match_quality` are in
**neither** registry — they were tier 3 before the cutover and are tier 3 after,
and the fallback never covered them. Reporting 4 as the migration debt would
overstate it by 2×.

**And the gap is not an attestation gap:** every structurally-ready draft **is**
attested. Nothing sits in the fallback merely awaiting a signature — the two
entries need a **design decision**, which is the user's.

---

## 3. PART C — THE TRIPLE, AND WHAT IS AND IS NOT GUARANTEED

### C1. THE HONEST TRIPLE

| | before | **after** |
|---|---|---|
| registered (governed) | 14 | **14** |
| **consumed** | **0** | **14** — every governed type is served by `governed_router()` |
| consumers existing | 1, unwired | **1, wired** |

> ### **14 registered / 14 consumed / 1 consumer, wired.**
>
> **This is the first time in this program that `consumed` is non-zero.**

**The counter-metric, and it matters:** *consumed* means "the router serves them
when it is constructed." **`governed_router()` still has no caller in
`gyza/cli.py` or any runtime path** — the consumption gap moved one level, from
"nothing passes an authority" to "nothing constructs a router." **The authority
now governs the router; the router still governs nothing that runs.**

### C2. What the authority guarantees — and the weaker true statement

**GUARANTEED:**
- Every claim type the router serves at tier 1 or 2 has an **attested entry
  naming who takes responsibility**, with a basis stating plainly that the owner
  **did not independently re-derive** the classifications.
- A spec failing attestation, carrier, or frame **cannot enter the path the
  router reads** (C3).
- The fallback's remaining scope is **enumerated and finite**.

**NOT GUARANTEED — say the weaker thing:**
- **`carrier_verified` is False for all 14.** The carrier is **DECLARED UNDER
  ATTESTATION**, screened one-directionally against the verifier's *signature*
  and never verified to recompute. **The registry provides NON-REPUDIATION for
  carrier claims, not prevention.**
- The attestation is **self-asserted**; it records accountability, not humanity.
- **Nothing constructs the router in production**, so no running code yet obeys
  any of this.

### C3. The refusals fire on the LIVE path — with a positive control

**18 tests**, of which the C3 group injects a defective draft into the **actual
`DRAFTS` list `governed_registry()` reads**, then asks the **router** whether it
serves it:

| control | result |
|---|---|
| **POSITIVE CONTROL** — a clean injected spec | **reaches the router** ✅ *(without this, the refusals below would prove nothing)* |
| unattested | refused — `AWAITING ATTESTATION` |
| sampling declared PROOF | refused — `CarrierRefused` |
| unpinned movable frame | refused — `FrameRefused` |
| the same movable spec **with** a `FrameRef` | admitted — the refusal is about the missing frame, not the function |
| **live-path check** | a refused spec routes **tier 3 / not governed** through `governed_router()` — the real call chain, not a direct `register()` call |

---

## 4. Where this stops

- `gyza/verification/migration.py` — `governed_router()` (the wiring),
  `fallback_scope()` (the expiry condition that was missing).
- `gyza/verification/router.py` — **unchanged.** DUAL_READ is not removed.
- `tests/test_registry_cutover.py` — **18 tests**, 3 negative controls plus a
  positive control, all on the live path.
- **193/193 pass** across ten suites, run sequentially.

## 5. Honest limits

1. **`consumed = 14` counts the router's service, not runtime use.** No CLI
   command or runtime path constructs `governed_router()`. The honest reading is
   *"the authority is in force wherever the router is used, and the router is
   used nowhere yet."*
2. **Carrier parity is consistency, not corroboration** (§0c).
3. **The two gap entries need a design decision**, not more attestation, and it
   is the user's: bind the kwarg or split the claim type.
4. **`FAIL_CLOSED` was selected, not measured.** It is authored judgement that
   an entry whose proposition is caller-determined should not be claimed as
   tier 1. DUAL_READ remains one argument away and is tested.
5. **The expiry condition is now specified but is itself unenforced in CI** —
   nothing fails a build when `fallback_scope()` is non-empty. It is a test that
   asserts the gap is *currently* the known two, which would catch a *new* gap
   appearing but does not force the existing one closed.
