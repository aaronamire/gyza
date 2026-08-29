# Finishing the migration — STOPPED at Gate 0, and the expiry condition proved satisfiable

**Branch `migration-complete`.** Zero credits. No attestation authored.
**No adapter was modified.**

---

## 0. GATE 0 — **the two classes named do not exist as ungoverned work**

### 0a. INVENTORY — the three classes that actually exist

| class | where | n | **governed** |
|---|---|---|---|
| **`Verifier`** (`NATIVE`) | `gyza/verification/adapters.py:114` | 13 | **11** |
| **`PartialSpec`** (`HUMAN_SPECS`) | `adapters.py:155` | 3 | **3 — all of them** |
| **`NO_VERIFIER`** (bare strings) | `adapters.py:178` | 2 | 0 — nothing to govern |

**`EXTERNAL_VERIFIER`: 0 hits** across every `.py`, `.md` and `.json` in the
tree. **`_LEGACY_FALLBACK_ACTIVE`: 0 hits** — the expiry condition I wrote is
`fallback_scope()`, a function, not a flag. **`PARTIAL_SPEC` as a token: 0
hits** — the class is `PartialSpec` and the list is `HUMAN_SPECS`.

**Call sites:** `HUMAN_SPECS` is read by `build_registries` (`adapters.py:190`),
`migration.py:99`, one research script (`research/domain_restriction/
dr_experiment.py:40`), and four test files. **Zero production callers**, as
before.

> ### VERDICT PER CLASS
>
> | class | verdict |
> |---|---|
> | **`EXTERNAL_VERIFIER`** | **DOES NOT EXIST.** Nothing to migrate |
> | **`PartialSpec`** | **ALREADY MIGRATED** — all 3 governed since the attestation session |
> | **`Verifier`** | 11 of 13 governed; **2 remain**, and they are the real gap |

**Tenth premise failure of this shape, and this one had no work in it at all.**
The task's model of the remaining gap — two ungoverned *classes* — does not
match the tree, where the gap is **two individual `Verifier` entries** blocked
for a reason unrelated to their class.

**Per the standing instruction — *if a gate fails, STOP and report rather than
improvising past it* — no adapter was modified.** §2 states exactly what would
close the gap and reports it as measured, not applied.

### 0b. The attestation condition, answered per class rather than filled in

**`PartialSpec` — the attestation is NOT redundant, and the distinction is
sharp:**

| field | what it records | value today |
|---|---|---|
| `PartialSpec.authored_by` | **who wrote the PREDICATE.** R14's requirement: the property itself is human-authored | `"xan"` |
| `Attestation.author` + `basis` | **who takes responsibility for the STRUCTURAL CLASSIFICATION** — carrier, invariant class, frame, obligations | `"Aaron (repository owner)"` |

> **These are different facts about different objects.** The predicate
> `0.0 <= score <= 1.0` was human-authored; the surrounding judgement *"this is
> SPEC-carried, CONSERVATION-class, needs no frame"* was authored by Claude Code
> and accepted by the owner. **Neither field can substitute for the other.**

**AND A DEFECT IN THE COMMITTED ATTESTATION, found by answering this:** the
basis reads *"Classified by Claude Code from the verifier implementations…"* —
accurate for the 11 `Verifier` entries, but for the 3 `PartialSpec` entries it
**under-describes provenance**, because it omits that the *predicate* was
human-authored by `xan` before any classification happened. **The basis is not
false; it is incomplete for one class.** Correcting it is the owner's — the
attestation is theirs and this document does not edit it.

**`EXTERNAL_VERIFIER` — the question is answerable in principle and moot here.**
Had such a class existed, the attester could not vouch for a third party's
implementation; the attestation could only cover **"this is the verifier I
selected, at this pinned identity, and I accept its verdicts as authoritative
for this claim type."** That is a *selection* record, not an implementation
record — a strictly weaker thing than what the current attestation covers.

### 0c/0d. Carrier and frame for an external verifier — **the conditions would bite hardest here**

- **Carrier:** declaring PROOF for code you cannot inspect is a claim about a
  third party's implementation. The registry's screens are signature-based and
  would see nothing. **It should be accepted only as `TEST`, or as PROOF under
  an explicitly recorded basis naming the external evidence** — never on the
  registry's own screens, which are blind here.
- **Frame:** an external verifier's behaviour can change with no change in this
  repository. **That is precisely the movable-reference case**, and such an
  entry would require an immutable identifier — a version pin, a content hash of
  the binary, or a pinned endpoint. **Absent one, refuse rather than waive.**

**None of this is applied, because no such entry exists.** Recorded so the
question is not re-derived if one is added.

### 0e. **Zero credits.** No generation.

---

## 1. PART A — nothing to migrate

**No new structural fields were filled, because there is no unmigrated class.**
The analyzer and screens were run over the 3 `PartialSpec` entries anyway, since
A2 asks:

| entry | signature | totality | determinacy | analyzer |
|---|---|---|---|---|
| `hlc_ordering` | `(prev, nxt)` | ✅ | ✅ | not flagged |
| `reputation_score` | `(score)` | ✅ | ✅ | not flagged |
| `work_claim_exclusivity` | `(claims, work_item_id)` | ✅ | ✅ | not flagged |

**Judgement fraction: 0/3.** All three are total, determinate, and read no
unnamed state. **Diagnosing this exact 0:** **DEFINITIONAL given what a partial
spec is** — each is a one-line total predicate over its arguments, which is the
form R14's cost model requires (one human-authored property per *type*).
**Counter-metric, and it is the honest one:** the analyzer is SCREENING-ONLY
with measured precision 0.0000 on the live registry, so **an absence of flags is
not evidence of anything.**

**No PROOF-declared sampler was found.** There is none to find: the only
sampling verifier, `unit_test_execution`, is already carried as `TEST`.

**A3 — attestation: nothing new to attest.** All three `PartialSpec` entries are
already attested. The only outstanding basis question is the incompleteness in
§0b, which is the owner's to correct.

---

## 2. PART B — THE FALLBACK

### B1. **`fallback_scope()` is NOT empty. The fallback stays.**

```
envelope_dag           SUCCESS CONDITION IS NOT FIXED BY THE REGISTRY
external_send_content  SUCCESS CONDITION IS NOT FIXED BY THE REGISTRY
```

**MEASURED**, derived from live registry state (`ungoverned − governed`), not
asserted.

### B2/B3. Not removed — and what each entry needs, exactly

| entry | what closes it |
|---|---|
| **`envelope_dag`** | `_envelope_dag(envelopes, **kw)` → **`(envelopes, require_closed)`**. Production calls `verify_dag` both ways, so the claim must name the policy |
| **`external_send_content`** | `_external_send_content(claim, emitted, policy=None)` → **`(claim, emitted, policy)`**. When `policy` is `None` the policy clause is skipped entirely |

### B4. **THE EXPIRY CONDITION IS SATISFIABLE — measured, and this is the deliverable**

> **Nobody had checked whether `fallback_scope()` can ever return `{}`.** A
> condition that cannot go false is a proxy, not a gate — and this program has
> shipped exactly that defect before (`GuardConfigStore` checking a version
> integer). Deriving the condition from registry state is only worth something
> if the state can reach the terminal value.

**Applying the real remedy** — binding both policy parameters — in a test:

| | |
|---|---|
| governed entries | **14 → 16** |
| `fallback_scope()` | **`{}`** |
| still skipped | only `execution_output_content`, `routing_match_quality` — **which were never in the fallback's scope** (in neither registry) |

**And the negative control that makes the above mean something:** merely
clearing `blocked_reason` **does not** satisfy the condition — the authority's
determinacy screen still refuses the unbound signatures, and the scope stays at
the same two entries.

> **So the condition tests the protected quantity, not a label.** The
> annotation is not the gate; the guard is. Had clearing the annotation been
> sufficient, this would have been the **fifth** instance of the
> label-versus-quantity species in this program.

**One thing the condition still does not do:** nothing fails a build when
`fallback_scope()` is non-empty. It is checked by a test that pins the *current*
gap, which catches a **new** gap appearing but does not force the existing one
closed. That is visibility, not pressure — the same distinction that made the
original DUAL_READ marking insufficient.

---

## 3. PART C — THE AUTHORITY, AT ITS HONEST STRENGTH

### C1. THE TRIPLE — unchanged, because nothing migrated

| | |
|---|---|
| registered (governed) | **14** |
| consumed | **14** |
| consumers existing | **1**, wired |

### C2. What it guarantees

**GUARANTEED:**
- Every claim type the router serves at tier 1 or 2 has an **attested entry
  naming who takes responsibility**, on a basis stating the owner did not
  independently re-derive the classifications.
- The three refusal conditions **gate the live path** — negative controls inject
  a defective draft into the actual `DRAFTS` list `governed_registry()` reads,
  and a **positive control** confirms a clean spec does get through, so the
  refusals are not passing for unrelated reasons.
- The fallback's remaining scope is **named, finite, and its terminal state is
  reachable** (§B4).

**NOT GUARANTEED — the weaker true statement:**
- **`carrier_verified` is False for all 14.** The carrier is **DECLARED UNDER
  ATTESTATION**, screened one-directionally against the verifier's *signature*
  and never verified to recompute. **NON-REPUDIATION for carrier claims, not
  prevention.**
- The attestation is **self-asserted** — accountability, not humanity.
- **Nothing constructs `governed_router()` in any runtime path.**

### C3. **THE AUTHORITY'S SCOPE IS BOUNDED, and here is the boundary**

| inside the authority | outside it |
|---|---|
| 11 of 13 `Verifier` entries | **`envelope_dag`, `external_send_content`** — their success condition is not fixed by the registry |
| 3 of 3 `PartialSpec` entries | **`execution_output_content`, `routing_match_quality`** — irreducibly semantic; no verifier exists to govern |
| | **any external verifier** — the class does not exist, and §0c/0d records what it would have to satisfy |

**Four of eighteen claim types sit outside**, for two structurally different
reasons: two are *fixable* (bind the parameter) and two are *not* (the
competence bound). **A bounded scope stated plainly is a stronger artifact than
an unbounded one implied.**

---

## 4. What was built, and where this stops

- `tests/test_registry_cutover.py` — **+2 tests**: the expiry-condition
  satisfiability proof and its negative control. **20 tests in the file.**
- **No production code changed.** No adapter modified, no attestation authored,
  no fallback removed.
- **195/195 pass** across ten suites, run sequentially.

**What the user must decide to close this out** — one line each, and neither is
mine:

1. **Bind the two policy parameters** (§B2). Measured to take governed 14 → 16
   and `fallback_scope()` → `{}`. Zero production callers, so nothing breaks at
   runtime — but it changes what the registry *claims*, which is why it is not
   applied here.
2. **Correct the attestation basis** for the 3 `PartialSpec` entries to record
   that their predicates were human-authored by `xan` before classification
   (§0b).

## 5. Honest limits

1. **This session migrated nothing**, because there was nothing to migrate. The
   substantive output is the §B4 measurement.
2. **The satisfiability proof uses monkeypatched drafts**, not the real
   adapters. It demonstrates the condition *can* go false; it does not prove the
   bound signatures would pass `test_registry_execution`'s
   every-entry-executes check, which was not run against them.
3. **The 0/3 judgement fraction on `PartialSpec` is definitional**, and the
   analyzer's silence is worth nothing (§1).
4. **`fallback_scope()` has no CI teeth** (§B4).
