# The owner's attestation, and the release that was STOPPED at pre-flight

**Part A branch: `spec-attestation`** (off `carrier-enforcement`).
**Part B: nothing was merged, nothing was tagged, nothing was pushed.**
Zero credits.

---

## PART A — THE ATTESTATION

### A0. The prompt's counts, checked against the tree

**Eighth premise failure, same species as the previous four.**

| stated | tree |
|---|---|
| "the 21 spec entries" | **18** — `all_claim_types()` executed |
| "the four PROOF→TEST corrections and `credits_conserved`" | **do not exist** — `credits_conserved` has **0 hits**; the other three names appear **once each**, in my own findings recording that they don't exist |
| "the analyzer reached SCREENING-ONLY at 1/4 recall on the known-bad cases" | committed finding: **2/16 flagged, 0 true positives, precision 0.0000**. There were no known-bad cases to recall |
| "`credits_conserved`: the analyzer independently flagged it" | it flagged `envelope_dag` and `memory_retrieval_relevance`, **both diagnosed false positives** |

**A3's instruction to "verify the corrected carriers migrate as TEST rather than PROOF" was executed against the real registry**: the one sampling verifier, `unit_test_execution`, is attested as **TEST**, pinned by
`test_unit_test_execution_is_attested_as_TEST_not_PROOF`. **No entry was laundered into PROOF by the act of attesting it.**

### A1/A2. The basis, recorded exactly as authorized

`gyza/verification/attestations.json` — **written from the owner's authorization, not composed by the agent.**

> **basis:** *"Classified by Claude Code from the verifier implementations;
> reviewed and accepted by the repository owner, who takes responsibility for
> the classifications. The owner did not independently re-derive them."*

> ### THIS TRANSFERS RESPONSIBILITY, NOT KNOWLEDGE.
> It records **who is accountable if a classification is wrong.** It does **not**
> assert that a human re-derived each carrier. That is the weaker claim and it
> is the accurate one.

**`basis` was made a REQUIRED field on `Attestation`** and folded into
`SpecRecord.canonical_bytes()`, so a KEY_BOUND attestation signs its own basis
and the basis cannot be edited after signing. An attestation that could not
distinguish *"I re-derived every carrier"* from *"an agent classified these and I
accepted them"* would record less than it appears to.
`test_the_recorded_basis_does_not_claim_independent_verification` pins the
honest wording against drift.

### A3. Execution — **14 registered, 4 refused**

| | |
|---|---|
| attestations supplied | **18 / 18** |
| **registered** | **14** |
| **refused despite a valid attestation** | **4** |

**The 4 refusals, with reasons — and this is a finding, not an error worked
around:**

| entry | refusal |
|---|---|
| `envelope_dag` | **BLOCKED** — success condition not fixed by the registry: the adapter forwards `**kw` to `verify_dag`, and production calls it **both ways** |
| `external_send_content` | **BLOCKED** — `policy` defaults to `None`, so the policy clause is skipped at some call sites |
| `execution_output_content` | **BLOCKED** — irreducibly semantic, no verifier exists to govern |
| `routing_match_quality` | **BLOCKED** — same |

> **Attestation does not override the structural conditions**, and that is the
> design working. A human saying *"I vouch"* does not fix **which proposition** a
> verifier proves.

**Diagnosing the counts:** 14/18 is **DEFINITIONAL** — it is exactly
`structurally_ready` from the committed manifest, unchanged by attestation. The
would-be-suspicious number (18/18 clean) **did not occur**, and it could not
have: the blockers are checked before the attestation is consulted.

### A4. `carrier_verified`, per entry — **all 18 are DECLARED**

| assurance | n |
|---|---|
| **DECLARED under attestation** | **14 registered (+4 refused)** |
| VERIFIED by a mechanism | **0** |

Every registration and `audit()` now carries `CARRIER_ASSURANCE`:
*"DECLARED-UNDER-ATTESTATION — screened one-directionally against the verifier's
SIGNATURE. NOT verified to recompute."* A reader of the registry can tell
without opening a findings document.

**On the two entries the analyzer flagged — does that raise their status? NO,
and the reason is that both flags were false:**

- `memory_retrieval_relevance` flagged on `FILTER_SUCCESS_ONLY`, a **vocabulary
  token** compared against a field the claim *does* name. It is genuinely
  PROOF-carried; the flag was noise.
- `envelope_dag` flagged on a conservative `getattr` default over a *returned*
  object.

> **A false positive is not evidence about the entry it names.** Treating "the
> analyzer looked at it" as a higher assurance grade would be assurance
> laundering — the mechanism was measured SCREENING-ONLY precisely because its
> flags do not discriminate.

### A5. THE HONEST TRIPLE

| | |
|---|---|
| **registered (governed)** | **14** |
| **consumed** | **0** |
| **consumers existing** | **1** — `TierRouter`, wired to accept an authority, **not yet reading one in production** |

> **Consumed is still 0**, because nothing in production constructs a
> `TierRouter` at all — `build_registries()` has zero production callers and
> nothing produces a `claim_type`. **That is the accurate state and the next
> step, not a defect.**

---

## PART B — **STOPPED AT PRE-FLIGHT. NOT MERGED, NOT TAGGED, NOT PUSHED.**

### B1. The structural premise HOLDS

| premise | status |
|---|---|
| Rust crates have no `[[bin]]` sections | ✅ **confirmed — zero** |
| Rust crates have no `main.rs` | ✅ **confirmed — none** |

So no Rust-signed history could exist to invalidate. **That argument is intact
and was not re-derived.**

### B2. Pre-flight — **TWO GATES FAILED**

| check | result |
|---|---|
| `origin/main` via `git ls-remote` | **`f67c917`**, tag `v0.1.2` present, **no `v0.1.3`** |
| merge is a fast-forward? | **NO** — `main` is **not** an ancestor of `divergence-fix` |
| textual conflicts | **none** — the one `grep` hit was the word *CONFLICT* inside a research document's prose |
| Python suite | **967 passed, 1 skipped** after a fix (below) |
| Rust workspace | **108 passed** |
| Go daemon | **all packages ok**, including the flaky `gossip` |

#### ❌ GATE FAILURE 1 — the merge would DELETE the fail-closed signing gate

`divergence-fix` branched **before** `f67c917`, the single commit on `main` it
lacks: *"release: bump to 0.1.2 and make the signing step fail CLOSED."*

```
.github/workflows/release.yml | 27 ---------------------------
```

Those 27 lines are the **"refuse to ship unsigned (fail closed)"** step. Its own
comment says why it exists:

> *"Without this the job was fail-OPEN: when `MINISIGN_SECRET_KEY` is unset the
> sign step is skipped … and `publish` ships an UNSIGNED release while reporting
> success. An unsigned release from a provenance project is worse than no
> release."*

> **Merging as instructed would restore the fail-OPEN behaviour and re-enable
> exactly the outcome this task's own instructions forbid.**

#### ❌ GATE FAILURE 2 — the version would regress

| | |
|---|---|
| `main` | `version = "0.1.2"` |
| `divergence-fix` | `version = "0.1.1"` |

Tagging `v0.1.3` on a tree whose `pyproject.toml` says `0.1.1` would ship a
release whose metadata contradicts its tag.

#### The merge is also far larger than described

The task describes the release as *"the Rust non-ASCII escaping fix including
the DEL boundary, and the NaN guard reshaped as a positive finiteness
predicate."* The actual delta is **99 commits**:

| area | files changed |
|---|---|
| `research/` | **393** |
| `gyza/` | 32 |
| `tests/` | 12 |
| `gyza-rs/` | 12 |
| `packaging/`, `pyproject.toml`, `.github/` | 4 |

The two Rust fixes are in there (`d3f4646`, `c214038`) — alongside the entire
post-closure research program. That may well be intended, since `research/` is
tracked and public by design. **But it is not what the authorization
described**, and a 99-commit public release is not a decision to make on a
mistaken description of its contents.

### B3. NOT EXECUTED

**Per the instruction to STOP on any pre-flight failure rather than improvise**,
and per *"do not resolve conflicts unilaterally on a signed-bytes change"*: no
merge, no tag, no push. **`origin/main` is unchanged at `f67c917`.**

**What would unblock it (user's call, one line of judgement each):**

1. Merge `main` **into** `divergence-fix` first, keeping **main's**
   `release.yml` and **main's** version, then bump to `0.1.3`. This preserves
   the fail-closed gate.
2. Confirm that shipping the full 99-commit research stack to public `main` is
   intended.

### B4. RELEASE ASSETS — user-owned blocker, unchanged

On tag push, `release.yml` builds the onedir tarballs, signs each with
`minisign`, and **refuses to publish if the signature is missing**. It **cannot
complete without `MINISIGN_SECRET_KEY`**, which is a repository secret this
session cannot supply or verify.

**Required, all user-owned:**
1. `minisign -G`
2. `gh secret set MINISIGN_SECRET_KEY < minisign.key`
3. commit the **public** key into `scripts/install.sh` (`GYZA_MINISIGN_PUBKEY`)
   and `packaging/gyza-release.pub`

**No unsigned artifact was published or proposed.**

---

## An existing tripwire caught my own new code

`tests/test_canonical_comparison.py::test_no_unexempted_site_builds_or_compares_representations`
failed on **`gyza/verification/reads.py:105`** — I had used `repr(fn)` as a
display label. **Fixed by removing the `repr`, not by adding an exemption**: the
exemption list is only useful while it stays short, and a label is not worth
one. Reported because it is the tripwire doing its job on code written in the
same session that praised it.

---

## WHAT IS NOW IN FORCE, AND WHAT IS NOT

**IN FORCE:**
- 14 spec entries governed under a truthful, owner-supplied attestation whose
  basis states plainly that the owner **did not** independently re-derive them.
- The registry refuses unattested, sampling-declared-PROOF, unpinned-movable-
  frame, underdetermined, and unacknowledged-weakening entries — each with a
  negative control that fires.
- Every record says the carrier is **declared, not verified**.

**NOT IN FORCE:**
- **The tier router does NOT read the governed registry.** It accepts an
  `authority` and a `CutoverPolicy`, but **nothing in production constructs
  one** — so the 14 governed entries are consumed by exactly nothing. The
  ungoverned `build_registries()` is still the only registry any code path
  reads, and it too has zero production callers.
- **v0.1.3 does not exist.** `origin/main` is unchanged at `f67c917`.
- **No release assets can be published** until `MINISIGN_SECRET_KEY` exists.

> **The honest one-line summary: the standard is now signed, and still nothing
> is held to it at runtime.** Attestation closed the authorship gap; the
> consumption gap is untouched and is the next real step.
