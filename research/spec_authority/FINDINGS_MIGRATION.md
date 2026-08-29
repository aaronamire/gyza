# Putting the authority in force — structural migration and the governed cutover

**Branch: continued on `spec-authority`** (no fresh branch; this is the same
unit of work and splitting it would separate the standard from its adoption).
**Zero credits.** No model call.

---

## 0. THE PROMPT'S NUMBERS DO NOT MATCH THE TREE

Precedence is `committed FINDINGS > BUILD_PLAN > prompt`, so this is reported
rather than absorbed. **This is the fifth premise to fail this way**, and the
pattern in it is worth naming: every one has been an *overcount of what is
broken*.

| the prompt says | the tree says |
|---|---|
| "the **21** existing entries" | **18** — 13 `NATIVE` + 3 `HUMAN_SPECS` + 2 `NO_VERIFIER`, verified by executing `all_claim_types()` |
| "**ALL 21** would be refused" | **14 of 16** migratable candidates = **0.8750**, per committed `migration.json` |
| "every one missing authorship attestation **and carrier**" | **Neither is true of every entry.** `PartialSpec` *has* `authored_by` + `human_attested` — which is exactly why **2 entries already migrated**. `Verifier` *has* `carrier` |
| "21 registered / 0 consumed / 1 consumer existing" | **16 / 0 / 1** — and the "1" needs qualifying: `TierRouter` exists at `gyza/verification/router.py` but was instantiated **only in tests** |

The direction of the error matters: **acting on "all 21 are broken" would have
meant re-authoring two entries that were already correct**, and would have
overstated the adoption cost by ~17%.

---

## 1. PART A2 — THE CARRIER TABLE, and the mislabelled-PROOF finding first

### 1a. THE HEADLINE: **no mislabelled PROOF entries. Zero.**

> **The single highest-value output of Part A is a negative, and it is a real
> one.** Of 13 native verifiers, exactly one samples — `_unit_test_execution`,
> whose body is `all(fn(x) == y for x, y in cases)` — and it is **already
> correctly carried as `TEST`** at `adapters.py:132-133`. **No entry currently
> treated as PROOF samples.**

**Diagnosing the exact 0, because a clean number is a suspected artifact:** it
is **MEASURED and structural, not luck**. Gyza's verifier population is almost
entirely *hash and signature recomputation* and *total subset/fold checks* — the
least arguable shape a check can have. I read all sixteen bodies, including the
four I had initially classified from their call sites rather than their source
(`verify_envelope` `icp.py:82`, `verify_delegation` `delegation.py:213`,
`enforcement_satisfies_manifest` `sandbox/config.py:286`, `verify_entry`
`ledger.py`). All four recompute.

**The counter-metric that keeps this honest:** the screen behind this column is
one-directional (authority §A4) — *a declared sampling parameter is conclusive;
its absence is not evidence of recomputation*. **Zero mislabelled means "no
entry announces sampling while claiming PROOF", not "no entry samples."**

### 1b. Carrier classification — all 18

| claim type | carrier | basis | reason (what the verifier actually does) |
|---|---|---|---|
| `envelope_signature` | PROOF | MEASURED | recomputes canonical payload → blake3 → Ed25519 verify (`icp.py:82-96`) |
| `manifest_identity` | PROOF | MEASURED | recomputes `manifest_hash_hex`, compares |
| `artifact_content_address` | PROOF | MEASURED | recomputes blake3 over the supplied bytes |
| `envelope_chain` | PROOF | MEASURED | `verify_chain` walks every element; no sampling |
| **`envelope_dag`** | PROOF | MEASURED | traverses every node — **but see §2a, BLOCKED** |
| `enforcement_within_manifest` | PROOF | MEASURED | total subset test over four declared dimensions |
| `delegation_attenuation` | PROOF | MEASURED | folds three subset checks over **every** hop, plus cycle and depth |
| `ledger_entry_signatures` | PROOF | MEASURED | recomputes `canonical_sign_bytes` per role, verifies each |
| `balance_fold` | PROOF | MEASURED | `Wallet(entries).net_balance` folds every entry |
| `market_capital_fold` | PROOF | MEASURED | sums `market.capital_entries()` in full |
| **`unit_test_execution`** | **TEST** | MEASURED | **`all(fn(x) == y for x, y in cases)` — sound exactly where it sampled** |
| `memory_retrieval_relevance` | PROOF | MEASURED | **recomputes the whole neighbour set** (`respec.py:122-150`) and refuses on corpus-digest mismatch |
| **`external_send_content`** | PROOF | MEASURED | recomputes `wire_digest` over emitted bytes — **but see §2a, BLOCKED** |
| `hlc_ordering` | SPEC | MEASURED | total tuple comparison |
| `reputation_score` | SPEC | MEASURED | total range check |
| `work_claim_exclusivity` | SPEC | MEASURED | counts every element of the supplied set |
| `execution_output_content` | **NONE** | **UNCLASSIFIABLE** | **no verifier body exists to read** |
| `routing_match_quality` | **NONE** | **UNCLASSIFIABLE** | **no verifier body exists to read** |

**Carriers: 12 PROOF / 1 TEST / 3 SPEC / 2 NONE.**

### 1c. A3 — "cannot classify" is kept distinct from "TEST"

The two `NO_VERIFIER` entries are **`UNCLASSIFIABLE`**, not `TEST`. Their
carrier is not *undetermined* but **absent** — there is no body to read. A test
asserts this so the two cannot silently collapse into each other.

### 1d. Judgement fraction: **0.0000 — and the difficulty moved, it did not vanish**

**16 MEASURED, 2 UNCLASSIFIABLE, 0 JUDGEMENT.** An exact 0 in a column I
authored deserves suspicion, and here is what it actually means:

> **The carrier column was easy for this codebase. The success-condition column
> was not.** All four genuinely hard entries surfaced as **success-condition**
> problems (§2a), not carrier problems. Reporting judgement as 0 would be
> misleading if it implied the migration was uncontentious — **4 of 18 entries
> are blocked on real, named defects.** The difficulty is in a different column
> from the one the task expected it in, and that is itself the finding.

---

## 2. THE MIGRATION MANIFEST

`research/spec_authority/MIGRATION_MANIFEST.json` — every entry, structural
fields filled, **`"attestation": null` on all 18**.

| | count |
|---|---|
| entries | **18** |
| **structurally ready** (blocked only on attestation) | **14** |
| **blocked on something other than attestation** | **4** |
| reference sets that can move (frame identifier assigned) | **7** |
| frames **already carried in production** | **1** — `corpus_snapshot` |
| frames **PENDING** (identifier named, not yet carried by the claim) | **6** |

### 2a. The 4 blocked entries — two defects, each found by writing the manifest

**Two are irreducibly semantic** and were already known: `execution_output_content`
and `routing_match_quality` have no verifier to govern. Recorded so they are not
proposed again.

**Two are new findings, and both are the same species:**

> **THE SUCCESS CONDITION IS NOT FIXED BY THE REGISTRY. The registered entry
> proves a different proposition depending on the call site.**

- **`envelope_dag`** — the adapter forwards `**kw` to `verify_dag`, whose
  `require_closed` defaults to **False** (`gyza/icp.py:220`). Production calls
  it **both ways**: `audit.py:101` and `demo/ddil_partition.py:616` pass
  `True`; `resilience.py:202`, `demo/byzantine.py:181` and
  `demo/collective_scale.py:237` pass `False`. **So "envelope_dag verified" can
  mean "parents resolve and closure holds" or "parents resolve" — and the
  registry cannot tell you which.**
- **`external_send_content`** — `verify_send_claim`'s `policy` parameter
  defaults to `None` (`respec.py:195`), and when `None` **the policy clause is
  skipped entirely**. The entry verifies hash+length at some call sites and
  hash+length+policy at others.

**Neither is fixed here.** Each needs the kwarg bound or the claim type split,
and both are design decisions. A test pins the consequence: **attesting a
blocked draft still does not admit it** — a human saying "I vouch" does not fix
*which proposition* a verifier proves.

### 2b. A limitation of the authority's own screen, found by migrating

`market_capital_fold` folds `market.capital_entries()` — a movable reference set
reached **through an object**, not through a named parameter. **The authority's
`MOVABLE_REFERENCE_PARAMS` signature screen does not see it.** The manifest
assigns it a frame anyway, by reading the body. Same for
`ledger_entry_signatures`, whose keys come from the `ledger` argument.

> **This is a concrete false negative in a guard I built last session**, and it
> is exactly what §A4 predicted in the abstract: signature screens catch what
> announces itself. Named here rather than left for a later session to
> rediscover.

---

## 3. PART B — the cutover

### B1 — what the router read, and what it reads now

`TierRouter.route` (`gyza/verification/router.py`) read `VerifierRegistry`
(tier 1) then `PartialSpecRegistry` (tier 2) then defaulted to tier 3. It now
takes an optional `authority` and, **when one is supplied, a mandatory
`CutoverPolicy`**.

**One router class, not two.** Two routers over two registries is the same
defect this migration exists to remove — they would be free to disagree.
Construction without an authority is **byte-for-byte the previous behaviour**,
pinned by `test_legacy_construction_is_unchanged`.

### B2 — the decision: **FAIL_CLOSED, and adopt it now precisely because it is free**

| option | cost | what breaks today |
|---|---|---|
| **FAIL_CLOSED** | the verified tier shrinks to exactly what is attested — **today that is 0 of 18** | **Nothing in production.** `TierRouter` had no production caller; the three research consumers (`carrier_coverage.py`, `run_ar1.py`, `run_ar3.py`) read `build_registries()` directly, not the router |
| DUAL_READ | preserves behaviour; **defers the forcing function indefinitely** | nothing — which is the problem |
| REFUSE TO CUT OVER | no mechanism exists when attestations arrive | nothing, and nothing is ready either |

> ## Recommendation: **FAIL_CLOSED.**
>
> **The consequence, stated plainly: with zero attestations, a FAIL_CLOSED
> router routes all 18 claim types to tier 3. The verified tier is empty.**
>
> That is not a regression — it is the honest size of the verified tier under a
> standard nobody has yet signed. The alternative reading, that 13 entries are
> tier-1 verified, is a claim resting on **no attestation from anyone.**

**The argument for adopting now rather than after attestation:** the cost of
FAIL_CLOSED is exactly zero today because **there is no production consumer to
break**. Once the coordination layer is live, fail-closed becomes a breaking
change and DUAL_READ becomes irresistible — *which is how ungoverned entries
accumulated in the first place*. **This is the cheapest moment this decision
will ever be.**

**DUAL_READ is implemented, and deliberately not recommended.** Where it is
used, every fallback is marked in the routing reason
(`"UNGOVERNED FALLBACK (DUAL_READ): …"`) and counted by
`TierRouter.governance()`, which names the fallback claim types. **A fallback
nobody can count is a fallback that never expires**; this one is countable.

**There is no default policy.** Supplying an authority without a
`CutoverPolicy` raises. A policy nobody chose is the defect, not the fix.

### B3 — the honest triple, after the wiring

| | before | **after** |
|---|---|---|
| specs registered (ungoverned) | 16 | 16 |
| **specs registered (governed)** | 2 | **0** |
| specs consumed | 0 | **0** |
| consumers existing | 1, unwired | **1, wired and awaiting attestation** |

> ### **16 ungoverned / 0 governed / 0 consumed / 1 consumer, now wired.**

**The 0 governed is not a defect and not a regression — it is the accurate
state, and it is the user's move.** The two entries that "already migrated" last
session did so under `PartialSpec.human_attested=True`, a **self-set boolean in
source**. Carrying that forward as an attestation would have been the trap this
task named: an attestation records whatever it is given.

**Diagnosing this exact 0:** **DEFINITIONAL.** `governed_registry({})` admits
nothing because no attestation was supplied, and no attestation was supplied
because supplying one is not mine to do. `test_attesting_more_entries_
monotonically_grows_the_governed_tier` shows the count moving 0 → 1 → 2 as
attestations arrive, so the 0 is a starting state and not a broken mechanism.

---

## 4. PART C — WHAT THIS DOES NOT ESTABLISH

**This section is the scope of the guarantee, not a caveat on it.**

1. **The attestation is SELF-ASSERTED.** `Attestation(method="SELF_ASSERTED")`
   records who takes responsibility for a spec. **It does not prevent a
   model-authored spec.** `KEY_BOUND` (built last session, Ed25519) raises it to
   "someone holding key K signed these bytes" — **accountability, not
   humanity.** A model with access to the key produces an identical signature.
   **Nothing in this codebase can establish that a human wrote the text.**

2. **The carrier check tests a DECLARATION under attestation, not a verified
   property.** No static analysis decides recompute-versus-sample — R12 measured
   that closing that gap requires deciding the question the check was meant to
   replace. §2b gives a concrete false negative in the screen.

3. **Therefore the registry's guarantee is NON-REPUDIATION, not prevention.**
   It makes every spec attributable to someone who accepted responsibility, and
   it refuses entries that are structurally malformed. **It does not make specs
   correct**, and a determined or careless attester can admit a bad spec.

4. **Who attested, and on what basis: NOBODY, YET.** Zero of 18 entries carry an
   attestation. When they do, the basis will be — for anything in this
   manifest — *"the agent classified the structure and I agreed."* **That is a
   real attestation and should be described as exactly that**, not as
   independent human specification. The structural classification in §1b is
   authored by a model; **the attestation's whole content is a human's decision
   to stand behind it.**

---

## 5. Where this stops

**Everything built is tested; nothing is half-wired.**

- `gyza/verification/migration.py` — 18 drafts, **no `attestation` field
  exists on `SpecDraft` at all** (a field that could hold a default is a field
  that will); `governed_registry()`; `manifest()`.
- `gyza/verification/router.py` — governed routing, mandatory explicit policy,
  `governance()` counting migration debt. Legacy path unchanged.
- `tests/test_spec_migration.py` — **22 tests**, load-bearing property first.
- **129/129 pass** across the six affected suites, run sequentially. **No
  existing behaviour changed** — `adapters.py` is untouched and the ungoverned
  registries still work exactly as before.

**What the user does next, entry by entry:** attest any of the **14
structurally-ready** drafts by passing
`{claim_type: Attestation(author=..., method="SELF_ASSERTED")}` to
`governed_registry()`. Each one moves a claim type out of tier 3 under
FAIL_CLOSED. **The 4 blocked entries need a design decision first**, and two of
those are the `**kw`/`policy` defects in §2a.

## 6. Honest limits

1. **The structural classification is authored by a model**, which is the exact
   thing R14 says not to trust for specification. It is offered as *structure to
   be checked*, not as specification — and the attestation slot is empty
   precisely because the two must not be conflated.
2. **`judgement_fraction = 0.0000` is a statement about the carrier column
   only.** §1d.
3. **6 of 7 frame identifiers are PENDING** — named, not yet carried by the
   claims. Attesting an entry whose frame is PENDING attests that the frame
   *should* be that identifier, not that it *is* pinned. Only
   `corpus_snapshot` is live.
4. **A stale note corrected:** the "empty-record hole" recorded in `CLAUDE.md`
   §3 is **CLOSED** — `gyza/sandbox/config.py:329-343` now requires
   `ro_paths`, `rw_paths` and `requires_network` to be positively declared, so
   an absent field fails closed. The finding it came from is older than the fix.
