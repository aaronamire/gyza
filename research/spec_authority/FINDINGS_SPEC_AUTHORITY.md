# The specification authority — inventory, decision, build, migration

**Zero credits.** No model call, no generation, no download. Engineering against
measured results, as specified.

---

## 1. GATE 0 — what exists today, verified against the tree

**The prompt's premise is partly wrong, and the correction matters:** it says
*"there is no registry, no versioning, no authorship attestation, and no refusal
path."* **A registry exists, versioning exists, an authorship attestation
exists, and two refusal paths exist.** What is absent is narrower and is stated
in §1b.

### 1a. Inventory

| thing | where | what it holds |
|---|---|---|
| `Verifier` | `gyza/verification/registry.py:35` | `claim_type`, `fn`, `witness`, `carrier` (**default `"PROOF"`**) |
| `VerifierRegistry` | `registry.py:73` | dict + `version: int`, `load_version` |
| `PartialSpec` | `registry.py:62` | `claim_type`, `fn`, `cls`, `authored_by`, `human_attested`, `rationale` |
| `PartialSpecRegistry` | `registry.py:104` | dict + `version: int` |
| entries | `gyza/verification/adapters.py` | **13 `Verifier`** (`NATIVE`), **3 `PartialSpec`** (`HUMAN_SPECS`), **2 strings** (`NO_VERIFIER`) |
| carrier consumers | `router.py:31`, `scheduler.py:43`, `coordination/task.py:37` | |

**Carrier vocabulary is CONSISTENT across all four sites, not contradictory** —
I checked because it looked like a discrepancy. `scheduler.CARRIER_DEPTH_CAP`
and `coordination/task.py:45` use the full `{PROOF, SPEC, TEST, NONE}`;
`Verifier` restricts to `{PROOF, TEST}` because a native verifier is never
SPEC-carried; `SPEC` is what a `PartialSpec` carries and `NONE` is absence.

### 1b. What already enforces (i)–(iii) — and what does not

| condition | enforced today? | where / why not |
|---|---|---|
| **(i)** human attestation | **PARTLY.** Enforced for `PartialSpec` (`registry.py:110-122`, raises `AuthorshipError`). **NOT enforced for `Verifier` — the dataclass has no authorship field at all.** | 13 of 16 entries have no authorship of any kind |
| **(ii)** sampling ≠ PROOF | **NO.** `Verifier.__post_init__` (`registry.py:55`) checks only that the *string* is in `{"PROOF","TEST"}`. Nothing relates the label to what the function does. | `unit_test_execution` is correctly hand-labelled `TEST` — that is authorship discipline, not a guard |
| **(iii)** immutable frame | **NO, and no field exists.** | The precedent is real and in this package: `corpus_snapshot_digest` (`respec.py:62`) pins the ranked candidate set and `verify_retrieval_claim` (`respec.py:134`) refuses on digest mismatch — but that is **one claim type**, not the registration path |

**Versioning exists and is over the wrong quantity.** `load_version`
(`registry.py:96`, `:134`) refuses a *lower integer*. **The integer is a label
that correlates with strength; it is not strength.** This is the species the
prompt names, and the codebase already has it.

### 1c. Call sites — production vs test

> **`gyza.verification.adapters.build_registries` has ZERO production callers.**

| caller | kind |
|---|---|
| `research/selection_routes/carrier_coverage.py:31` | research |
| `research/type_signal/run_ar3.py:50` | research |
| `research/vocabulary_design/run_ar1.py:94` | research |
| `tests/test_verification.py` (×3), `test_registry_execution.py` (×3), `test_respecification.py` (×2) | test |

`TierRouter(...)` is constructed **only in `tests/test_verification.py`** (3
sites). `gyza.coordination` is imported **only by tests**.

**Correcting a stale number I found while checking:**
`research/census/census.py:166` prints *"build_registries() has 14 call sites,
ALL TESTS, ZERO production."* **The "ZERO production" half is still true. The
count is not:** there are **8 test call sites and 3 research call sites** today,
and the census line also conflates `gyza.verification.adapters.build_registries`
with the **different** function of the same name at
`gyza/containment/gyza_model.py:83` (harm/invariant registries, called by
`tests/test_containment.py` and `research/selection_routes/unmeasured_actions.py`).
**Two functions share a name and a prior count merged them.** Not fixed here —
it is a research artifact, not code.

---

## 2. PART C — the consumption decision, made before building

### The honest triple

| | |
|---|---|
| specs **registered** | **16** (13 `Verifier` + 3 `PartialSpec`) |
| specs **consumed in production** | **0** |
| **production consumers existing** | **0** |

**And the reason is structural, not "not wired yet."** Nothing in production
produces a `claim_type`. `grep claim_type gyza/` outside `gyza/verification/`
returns only `gyza/coordination/task.py` — itself test-only. The registry is
**keyed by claim type**; with no claim-type producer there is nothing to look
up. `gyza/coordination/orchestrator.py:33` makes this explicit: `decompose()`
**raises** `NotSelectedError` citing
`research/selection_routes/BLOCKED_SR1_SR2_SR4.md`, which records the deeper
obstacle — *"assigning a claim type to a natural task is itself a tier-3
claim."*

### The decision, and the line I drew

**BUILD the refusals. DO NOT BUILD reader-side machinery.**

The send-claim precedent (written at 5 sites, read at 0, full hashing cost per
send, removed) **does not apply to a refusal, and the difference is not a
technicality**:

> A **payload** is written now to be read later — if no reader arrives it was
> pure cost. A **refusal** fires at write time. Its consumer is **the
> registration path**, which executes today: at import of
> `gyza.verification.adapters` (the module-level `NATIVE` / `HUMAN_SPECS` lists
> are built at import) and in **11 call sites** across tests and research.

So the refusals have a consumer that exists. What does **not** have a consumer
is persistence, signed registry bundles, or network distribution of specs —
**none of which was built**, because their only consumer is the blocked
coordination layer.

**What would consume the registry, and when:** `TierRouter.route` → the
orchestrator's tier decisions → SR-1's decomposer. That chain is blocked at
SR-1 on substrate that does not exist (a task corpus, a subtask→claim-type
mapping) and the mapping is itself tier-3. **This is not a foreseeable near
path, and the write-up says so rather than implying the registry is about to be
used.**

---

## 3. PART A — the authority, and its refusals demonstrated

Built at **`gyza/verification/authority.py`**. Existing registries are **not
modified** — see §5 for why rewiring would have been a refactor.

### A1 — required fields, no defaults

`SpecRecord` carries `claim_type`, `success_condition`, `fn`, `carrier`,
`invariant_class`, `attestation`, `frame`, `obligations`, `version`, `witness`.
**Every one is required and `None` is never accepted.**

Where a field genuinely does not apply the author passes
**`NotApplicable(reason=...)`**, which requires a non-empty reason. This is the
**empty-record hole** fix: absence must be a *decision somebody recorded*, not a
*gap nobody noticed*. Contrast `Verifier.carrier: str = "PROOF"` — **a default
that silently makes every unlabelled verifier claim the strongest carrier.**

### A2 — versioning over the protected quantity

The protected quantity is **the obligation set**, not the version integer.
`weakening(old, new) = old.obligations - new.obligations`. A replacement that
drops obligations is **REFUSED** unless it carries a `SupersedeAck` naming
**exactly** what was dropped and who accepted it — an ack naming the wrong
obligation is itself refused.

> **This is the fourth instance of the label-versus-quantity species and it is
> caught rather than repeated.** G4′ pinned the frame; SR-5 floated the origin;
> `GuardConfigStore` tested the version integer so a correctly-signed *higher*
> version could raise every bound and install cleanly. `test_negative_control_
> higher_version_with_fewer_obligations_is_refused` is that exact defect,
> inverted into a test.

### A3 — the three refusals, each with a negative control that FIRES

**35/35 tests pass.** The negative controls, and what each constructs:

| condition | negative control | result |
|---|---|---|
| **(i)** | attestation with empty author; `SpecRecord` with `attestation=None`; **KEY_BOUND signature that does not verify** | `AttestationRefused` ✅ |
| **(ii)** | `_sampling(fn, cases)` declared `carrier="PROOF"` | `CarrierRefused` ✅ |
| **(iii)** | `_over_movable_set(claim, candidates)` with `frame=NotApplicable(...)` | `FrameRefused` ✅ |
| **A2** | v99 with a **smaller** obligation set than v1 | `WeakeningRefused` ✅ |
| **A2** | `SupersedeAck` naming an obligation that was not dropped | `WeakeningRefused` ✅ |
| **A1** | each required field set to its empty value; `None` for the two optional-looking fields | `MissingField` ✅ |

**Each refusal has a matching acceptance**, so the guard is not simply blocking
everything: the same sampling function **registers as `TEST`**, and the same
movable-reference spec **registers once a `FrameRef` pins it**. *The refusal is
about the label, not the function* — otherwise this would be banning finite
samples rather than banning lying about them.

### A4 — declaration or property? **DECLARATION, and I will not dress it up**

> **Whether an arbitrary callable recomputes rather than samples is not
> decidable, and this module does not claim to decide it.**

What the screens do is **mechanical and one-directional**:

- a **declared sampling parameter** (`cases`, `samples`, `examples`,
  `test_cases`) is conclusive evidence of sampling;
- **its absence is NOT evidence of recomputation.**

So (ii) and (iii) are **necessary-condition screens**. To stop a caller reading
"not refused" as "verified", `ScreenResult`'s field is named
**`no_declared_evidence`**, not `ok` — and a test asserts the screen returns a
judgement rather than a bare bool.

**What binds the declaration to reality** is the third screen:
`check_witness_resolves` requires the cited `file:line` to exist. **It is
advisory, not a refusal**, because legitimate witnesses include non-file strings
like `"V-3 adapter (finite sample)"` and refusing those would force authors to
fabricate paths.

**And it is weaker than it looks — this is the honest limit.** It checks that
the line **exists**, not that it **contains the cited implementation.** Proof
that this matters, found while testing it: `NO_VERIFIER`'s two comment citations
(`adapters.py:172,173`) both point at real files and in-range lines, and both
are **wrong at the content level** — `gyza/demand.py:35` is `class LSHIndex:`,
which has nothing to do with `routing_match_quality`. **My screen would pass
both.** It catches deletion and truncation; it does not catch drift.

---

## 4. PART B — what the attestation actually establishes

### B1 — the honest answer, in three levels

| level | what it establishes | available? |
|---|---|---|
| `SELF_ASSERTED` | **whoever constructs the record typed a name.** A NON-REPUDIATION RECORD | today, and it is what all 3 existing `PartialSpec`s use |
| `KEY_BOUND` | **someone holding Ed25519 key K signed the record's canonical bytes.** ACCOUNTABILITY | **built here**, reusing `cryptography`'s Ed25519 — the same primitive as `gyza/identity.py:384` |
| *"a human wrote this"* | — | **NOT AVAILABLE, and no mechanism in this codebase could provide it** |

`SELF_ASSERTED` **does not prevent a model-authored spec. It records who
answered for one.** `KEY_BOUND` raises the bar from "someone typed a name" to
"someone holding K signed it" — **a model with access to the key produces an
identical signature.**

### B2 — so the artifact says the weaker thing

The module docstring, the `Attestation` docstring, and `verify_attestation`'s
docstring each state **"ESTABLISHES ACCOUNTABILITY, NOT HUMANITY."** The
existing `PartialSpec.human_attested: bool` is a **self-asserted boolean** whose
field name asserts more than the mechanism delivers; `SpecAuthority.audit()`
therefore reports **`self_asserted`** as a named list, so the weaker status of
every such entry is visible rather than implied.

**This registry exists partly to stop the unenforced-invariant species, and
"human-authored" as a self-set boolean is exactly that species.** Naming it is
the only fix available.

---

## 5. PART D — migration, nothing auto-fixed

| | count |
|---|---|
| existing entries | **18** = 13 `NATIVE` + 3 `HUMAN_SPECS` + 2 `NO_VERIFIER` |
| migratable candidates (have an `fn`) | 16 |
| **UNMIGRATABLE without inventing a field** | **16 / 16** |
| **WOULD BE REFUSED IF SUBMITTED FRESH** | **14 / 16 = 0.8750** |
| actually migrated | **2 / 3** `HUMAN_SPECS` |
| witness citations that do not resolve | **0 / 13** — *see the diagnosis* |

**Missing fields, by source** (these are schema gaps, not bad entries):

- `NATIVE` (13): `attestation`, `success_condition`, `frame`, `obligations`,
  `invariant_class`
- `HUMAN_SPECS` (3): `carrier`, `success_condition`, `frame`, `obligations`,
  `witness`, `version`

**Refused if submitted fresh, by condition:**

- **(i) — 13.** Every `NATIVE` verifier, because **`Verifier` has no authorship
  field at all.** Not a judgement about the entries; the schema cannot express
  the attestation.
- **(iii) — 6.** `envelope_chain` and `envelope_dag` (`envelopes`),
  `delegation_attenuation` (`chain`), `balance_fold` (`entries`),
  `memory_retrieval_relevance` (`candidates`), `work_claim_exclusivity`
  (`claims`) — each takes a reference set the caller supplies and that can grow
  between claim and check, with nothing pinning it.
- **(ii) — 0.** Diagnosed below.

**The 2 that migrated:** `hlc_ordering` and `reputation_score`. **The 1 that did
not:** `work_claim_exclusivity`, refused by **(iii)** — it folds over `claims`,
a set that can grow. **Nothing was fabricated to make it pass.**

### Diagnosing the two clean numbers

**(ii) = 0 — MEASURED, and it is a real (small) result.** Of 13 verifiers, one
samples (`_unit_test_execution(fn, cases)`) and it is **already correctly
labelled `TEST`** at `adapters.py:132-133`. So the screen found no mislabelling
because there is none to find — the hand-discipline held. **The counter-metric
that keeps this honest: the screen's power is limited to declared sampling
parameters, so 0 means "no entry announces sampling while claiming PROOF", not
"no entry samples."**

**0 / 13 unresolved witnesses — PARTLY DEFINITIONAL, and the denominator is
wrong.** The decomposition:

| | n |
|---|---|
| **file + numeric line, actually checked** | **11** |
| file-only (`gyza/economy/market.py:CapitalEntry fold` — line not numeric) | 1 |
| non-file, skipped (`V-3 adapter (finite sample)`) | 1 |

> **The honest statement is "0 unresolved of the 11 that were checked," not
> "0 of 13."** And per §3's A4, even those 11 were checked for line
> *existence*, not for content.

---

## 6. Where this stops, and why that is the boundary

**Everything built is tested; nothing is half-wired.**

- `gyza/verification/authority.py` — the authority. **35/35 tests pass.**
- `tests/test_spec_authority.py` — 6 refusal conditions, each with a negative
  control that fires, each paired with an acceptance.
- `research/spec_authority/migrate.py` + `migration.json` — the measurement.
- **107/107 pass** across `test_spec_authority`, `test_verification`,
  `test_registry_execution`, `test_respecification`, `test_containment`. **No
  existing behaviour changed.**

**`adapters.py` was deliberately NOT rewired.** Adopting the standard requires
**13 authorship attestations and 6 frame identifiers** that do not exist, and
**D3 forbids fabricating either.** Wiring the authority into `build_registries`
today would refuse 14 of 16 entries and break the suite — or force exactly the
fabrication the migration was designed to measure.

> **The 0.8750 refusal rate is the deliverable, not a defect report.** It
> measures what adopting the authority's own standard costs, and the cost is
> **human authorship — which only the user can supply.** That is the throughput
> constraint this task set out to make legible, and it is now a number.

## 7. Honest limits

1. **(ii) and (iii) are signature screens, not semantic checks.** They catch the
   entry that announces its defect. §3's A4 states the one-directionality in the
   type system, not just in prose.
2. **The witness screen catches deletion, not drift.** Demonstrated on
   `NO_VERIFIER`'s two stale citations, which it passes.
3. **`SAMPLING_PARAMS` and `MOVABLE_REFERENCE_PARAMS` are authored vocabularies.**
   Deliberately short and literal: a longer heuristic list produces refusals
   nobody can predict, and an authority with unpredictable refusals is worse
   than one that refuses less. **Six of the sixteen refusals under (iii) depend
   on this word list**, so the 0.8750 is sensitive to it — a different list
   gives a different number, and that is authored judgement, labelled.
4. **The authority has no production consumer**, for the reason in §2, and this
   document does not imply otherwise. Its consumer is the registration path.
5. **Incidental finding, not fixed:** `gyza/canon.py`'s single `__all__`
   (line 98) omits `Failure`, `CallFailed`, `failed`, `attempt`, `unwrap_or`.
   The failure sentinel built to be used is not wildcard-exported. Direct
   imports work, so nothing is broken today.
