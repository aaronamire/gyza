# Carrier corrections — the retroactive check, the carrier rule, and the DAG entries

**Branch `carrier-corrections`.** Zero credits. No attestation authored.

---

## 0. THE PROMPT'S PREMISE IS FALSE — checked first, because everything downstream depends on it

**Sixth premise to fail against the tree, and this one is load-bearing: it
describes work that never happened.**

| the prompt states | the tree |
|---|---|
| "four entries classified as TEST that the registry carried as PROOF" | **Zero.** No PROOF→TEST reclassification has ever occurred |
| `memory_bound`, `capability_check`, `session_dag` | **Do not exist.** `grep -rn` across all `.py` and `.md`: **no hits at all** |
| "the 21 entries" / "all 21 entries" | **18** — verified by executing `all_claim_types()` |
| "Five entries were verified by inspection as genuinely recomputing" | **Sixteen** were read; **fifteen** recompute, **one** samples |

The committed finding says it plainly: **"No mislabelled PROOF entries.
Zero."** (`FINDINGS_MIGRATION.md` §1a). The migration classified exactly one
entry as TEST — `unit_test_execution` — and **the registry already carried it as
TEST**. Nothing moved.

> **So Part A's stated cause does not exist.** The retroactive check was run
> anyway, on the real question underneath it — *does any committed finding carry
> a number computed over the registry's carrier composition?* — and **it found a
> genuine stale figure with a different cause.** The premise was wrong; the
> instinct was right.

---

## 1. PART A — THE RETROACTIVE CHECK

### 1a. What was searched

Every committed research artifact containing a carrier distribution, a
`p(composable)`, a coverage fraction, an expected-tier-by-depth table, or a
figure derived from counting PROOF-carried types:

`CARRIER_COVERAGE.md`, `ENGINEERING_STATUS.md`, `OPEN_PROBLEM.md`,
`TIER_ALGEBRA.md`, `AUTONOMOUS_SESSION.md`, `BUILD_PLAN.md`,
`ARTIFACT_LEDGER.md`, `selection_routes/carrier_coverage.{py,json}`,
`selection_routes/FINDINGS_SR3.md`, `vocabulary_design/FINDINGS_AR1.md`.

### 1b. THE HIT — `CARRIER_COVERAGE.md` drifted from its own generator

**MEASURED, by re-executing the generator against the live registry.**

| quantity | committed | **recomputed** | |
|---|---|---|---|
| carriers | PROOF 10 · TEST 1 · SPEC 3 · **NONE 4** | **PROOF 12 · TEST 1 · SPEC 3 · NONE 2** | |
| tier-1 **claim types** | **61.1%** (11/18) | **72.2%** (13/18) | |
| depth-2 chain tier-1 | 0.309 | **0.4444** | |
| depth-4 | 0.095 | **0.1975** | |
| **depth-8** | **0.009** | **0.0390** | **4.3×** |
| depth-8 any correctness claim | 0.074 | **0.2326** | |
| depth-8 ceiling after all upgrades | 0.134 | **0.3897** | |
| *"4 of 18 claim types are semantic"* | 4 | **2** | |

**The cause is the respecification, not a carrier correction.** Commit
`60081f4` moved `memory_retrieval_relevance` and `external_send_content` out of
`NO_VERIFIER` into registered PROOF-carried verifiers. `CARRIER_COVERAGE.md`
was computed before that and never recomputed, even though its own header says
*"Computed by `selection_routes/carrier_coverage.py`"*. **The document and its
generator disagree**, which is the failure mode `ARTIFACT_LEDGER.md` warns about
under *a count is not a ledger*.

**A5 — DEFINITIONAL/MEASURED split:** the *discovery* that the document is stale
is **MEASURED** (the generator was re-run). Every *corrected figure* is
**DEFINITIONAL** — each follows arithmetically from the registry composition
under the unchanged uniform-sampling assumption. **Nothing was re-derived and no
new experiment was run.**

**The direction is worth stating: every corrected number is more favourable.**
The committed figures *understate* coverage by up to 4.3×. A stale pessimistic
number is still a wrong number.

### 1c. A second defect, found while correcting the first

**The row labelled "isolated (depth 1) — 61.1%" is a different quantity from
every row beneath it in the same column.** 61.1% counts **claim types** (11/18);
the rows below are **chain probabilities** (powers of 10/18 — note 0.5556² =
0.3086 ≈ the 30.9% shown). **That is `ARTIFACT_LEDGER.md` #17's species,
occurring inside a single table**, and #17 was recorded against a comparison
*between* documents. The correction block keeps the two quantities on separate
rows.

### 1d. A3 — the correction applied

A **labelled correction block** at the head of `research/CARRIER_COVERAGE.md`,
**preserving all prior text unedited**. No number was silently changed.

**Deliberately NOT edited:**

- **`ARTIFACT_LEDGER.md` #17** — it records a *reasoning defect* that occurred
  with these numbers. Correcting the arithmetic does not unmake the defect, and
  the ledger's definition ("clean numbers that turned out false") must stay
  intact.
- **`ENGINEERING_STATUS.md` and `OPEN_PROBLEM.md`** — both already carry the
  table **struck through and marked as superseded prior framing**, pointing at
  AR-1. They inherit the correction; adding a second supersession notice on top
  of an existing one would obscure rather than clarify.

### 1e. A2 — **AR-1 SURVIVES, and the reason is exact**

AR-1's audited path exercises five claim types, named in its generator at
`research/vocabulary_design/run_ar1.py:33-39`:

```
verify_dag.signature -> envelope_signature      binding_ok        -> artifact_content_address
verify_dag.linkage   -> envelope_chain          manifest_bound_ok -> manifest_identity
                                                within_bounds     -> enforcement_within_manifest
```

**All five recompute** (verified by reading `icp.py:82`, `identity.py:101`,
`artifact_store`, `sandbox/config.py:286`, and the linkage traversal).
**`envelope_dag` — the registry entry with the unrecorded policy — is NOT among
them**: AR-1 decomposes `verify_dag` into the two *properties* it checks rather
than attributing the whole adapter, and records that mapping as authored.

> **AR-1 is untouched *because* `audit.py` binds the policy explicitly.**
> `audit.py:75` declares `require_closed: bool = True` and `audit.py:101` passes
> it by name. Had the audit path forwarded `**kw` the way the registry adapter
> does, AR-1's linkage attribution would itself have been underdetermined and
> `p_proof = 1.0000` would have needed qualifying. **The defect and its absence
> have the same root, one call site apart.**

AR-1's `p_proof = 1.0000` stands, and its own diagnosis of that exact 1.0000 as
**DEFINITIONAL** stands with it.

### 1f. Diagnosing the near-miss: **one hit, not zero and not many**

The check did not come back clean, so there is no exact-0 to diagnose — but the
**counter-metric** matters: **nine other artifacts were searched and are
unaffected**, and the single hit has a cause (respecification) unrelated to the
one the task proposed (reclassification). **The blast radius of the carrier
question itself is zero.** What was found was a different, real staleness that
the search happened to pass through.

---

## 2. PART C — THE CARRIER RULE (reported before B, because it governs B4)

### 2a. Both sides of C1, then the resolution

**FOR TEST:** "within bounds" without naming `T` is underdetermined; a different
`T` gives a different verdict and the claim cannot say which ran.

**FOR PROOF:** given a *named* `T`, `value <= T` is not a sample — it is the
property itself, decided completely, with nothing left to recompute.

> ### The resolution is that **both are right about different things, and the
> two-valued carrier field was hiding it.**
>
> "Sampling" and "underdetermination" are **different defects with different
> consequences and different remedies**, and collapsing them is the error.

### 2b. THE RULE

> **A verifier is PROOF-carried for a claim iff BOTH hold:**
>
> **TOTALITY** — it decides the claimed property for **every** input in the
> claim's declared domain; no proper-subset generalisation.
>
> **DETERMINACY** — the claim **names every parameter that changes the
> verdict**, so exactly one proposition is decided.
>
> | failure | carrier | composition | remedy |
> |---|---|---|---|
> | **fails TOTALITY** | **TEST** | **0.000** (SR-3) — behaviour outside the sample is unconstrained | **none.** Naming a parameter cannot help: the claim is about the function, the check is about the sample |
> | **fails DETERMINACY** | **UNDERDETERMINED** — *not* TEST | **not 0.000.** Every link IS fully decided; what fails is composing the **meanings** | **name the parameter.** Complete fix |

This answers C1/C2 as C2 anticipated — **the resolution turns on whether `T` is
named in the claim** — but with a correction to C2's framing: an unnamed `T` does
**not** make the verifier TEST. It makes it **underdetermined**, which is a
different cell with a different composition consequence. **Calling it TEST would
predict 0.000 composition for a check that actually decides its proposition
completely.**

### 2c. Enforced, not just stated

`check_claim_determinacy` (`gyza/verification/authority.py`) refuses a
PROOF/SPEC entry whose signature admits `**kwargs` or carries a defaulted
parameter — mechanical and conclusive evidence that **the caller chooses the
proposition**. It raises **`UnderdeterminedClaim`, a distinct exception from
`CarrierRefused`**, and a test asserts neither subclasses the other: *a caller
catching `CarrierRefused` is handling "this samples", which no parameter-naming
repairs.*

**One-directional, like every other screen:** a defaulted parameter is
conclusive; its absence does not prove the claim names everything that moves the
verdict (see §2e).

**12 tests, 3 negative controls that fire**, plus the positive control that
**binding the parameter repairs it** — the remedy is demonstrated, not asserted.

### 2d. C4 — the rule applied to all 18

| grade | n | entries |
|---|---|---|
| **VARIABLE-UNDETERMINED** (refused as PROOF) | **2** | `envelope_dag` (`**kw`), `external_send_content` (`policy=None`) |
| **FIXED-UNNAMED** (PROOF stands, claim incomplete) | **1** | `delegation_attenuation` |
| DETERMINATE | 13 | the rest |
| no verifier | 2 | `execution_output_content`, `routing_match_quality` |
| fails TOTALITY | **1** | `unit_test_execution` — unchanged, and still the only one |

**The mechanical rule reproduces the hand pass exactly on the refusals.**
Diagnosing that agreement rather than celebrating it: **it is not independent
confirmation.** Both readings looked at the same signal — I found those two by
reading signatures too. What the rule adds is that the check is now **a guard
rather than discipline**.

**And the rule found one thing the hand pass missed — a finding about the
pass, per C4's own framing:**

> **`delegation_attenuation` is FIXED-UNNAMED.** `verify_delegation` carries
> `max_depth=8` (`MAX_DELEGATION_DEPTH`), which moves the verdict. The adapter
> `_delegation_attenuation(chain)` does not expose it, so the verdict **cannot
> vary per call site** — PROOF stands, and it is not refused. But my
> hand-written success condition said only *"depth is bounded"*, which **does
> not say which bound was checked.** Corrected: the claim now names
> `max_depth = 8` and the obligation is `depth_at_most_8`.

**FIXED-UNNAMED is not detectable from the adapter's signature** — it required
reading one level into the delegate. That limit is stated in the screen's
docstring rather than left implicit.

---

## 3. PART B — THE DAG ENTRIES

### 3a. B1 — RESPEC-4 already did this design work

`research/respecification/FINDINGS_RESPEC_4.md` specified it, and it is reused
rather than re-derived. It named **four** parameters that must be recorded:

| parameter | why |
|---|---|
| **verification policy** | `require_closed` — the live divergence |
| **artifact policy** | `require_all_artifacts` (`audit.py:77`) — same shape, second flag |
| **DAG identity** | *which* envelope set — pin by content address |
| **expected head** | a caller may know it; the claim does not record it |

RESPEC-4 also found the same defect in its own census (`envelope_dag`
classified by analogy to `envelope_chain`) and corrected it there. **This
session's mechanical rule independently refuses the same entry**, which is the
first time that finding has been *enforced* rather than recorded.

### 3b. B3 — THE CONSUMER GATE: **REFUSED AGAIN, and the split is the point**

RESPEC-4 ran this gate and it **FAILED**: *"Nothing in production consumes any
claim of any type."* **That has not changed** — last session's triple was
`16 registered / 0 consumed`, and `build_registries()` still has **zero
production callers**.

> **So the claim-side artifact is NOT built.** A `DagClaim` dataclass carrying a
> recorded policy would need a producer and a reader; there is neither. Send
> claims were written at five sites, read at zero, and were removed. **This is
> the fourth refusal (RESPEC-3, RESPEC-4, 3.C, now B3) and the gate binds.**

**What WAS built, and why it passes the same gate:** the **determinacy check**,
whose consumer is the **registration path** — it fires at write time, and the
registration path executes at import of `gyza.verification.adapters` and across
every test and research call site. This is the distinction established last
session: *a payload is pure cost if no reader arrives; a refusal fires when it
is written.*

**Net: the defect is now caught, and no unread field was added to carry it.**

### 3c. B4 — does recording the policy upgrade the carrier? **YES for these two, and NOT because of the recording**

Under §2b's rule, answered explicitly rather than assumed:

- `verify_dag` **already satisfies TOTALITY** — it traverses every node and
  verifies every signature. It never failed the sampling test.
- Its only failure is **DETERMINACY**, and naming `require_closed` fixes that
  completely.
- **Therefore binding the parameter makes it PROOF-carried** — not because
  recording upgrades a carrier, but because **totality was never the problem.**

**The general answer is the one B4 asks for, and it is a NO:** recording a
policy does **not** upgrade a carrier in general. `unit_test_execution` fails
**totality**; recording its case set would make the claim perfectly determinate
and it would **still be TEST**. *A decidable claim checked by a sampling
verifier is still TEST-carried* — B4's own formulation, and the rule reproduces
it.

---

## 4. What was built, and where this stops

- `gyza/verification/authority.py` — `check_claim_determinacy`,
  `UnderdeterminedClaim`, wired into `register()` and into `audit()`.
- `gyza/verification/migration.py` — `delegation_attenuation`'s success
  condition and obligations corrected to name `max_depth = 8`.
- `tests/test_carrier_rule.py` — **12 tests**, 3 negative controls, 1 positive
  control demonstrating the remedy.
- `research/CARRIER_COVERAGE.md` — labelled correction block, prior text intact.
- **141/141 pass** across seven suites, run sequentially.

**No attestation was authored.** The manifest still reads `"attestation": null`
on all 18, and that remains the user's.

## 5. Honest limits

1. **The determinacy screen is a signature screen.** It catches
   `VARIABLE-UNDETERMINED` mechanically and **cannot see `FIXED-UNNAMED`**,
   which needed reading the delegate. One instance was found that way; there may
   be others deeper in call graphs I did not traverse.
2. **The rule's two conditions are not symmetric in enforcement.** Totality is
   screened by a short authored word list (`SAMPLING_PARAMS`); determinacy is
   screened by a structural property of the signature. **Determinacy is the
   better-enforced half**, and totality remains the weaker check.
3. **The corrected coverage figures inherit the uniform-sampling assumption**
   that AR-1 already showed is wrong for real chains (empirical curve flat at
   1.0). They are corrected as *arithmetic under a stated assumption*, not
   promoted to descriptions of the system.
4. **`delegation_attenuation`'s correction is to the CLAIM, not the code.**
   `max_depth` is still a defaulted parameter of `verify_delegation`; nothing
   prevents a future adapter from exposing it, at which point the entry becomes
   VARIABLE-UNDETERMINED and the screen would refuse it. That is the screen
   working, not a latent defect.
