# S5 — reproducible builds and build attestation

**Status: B1 done and measured, B2/B3 built and tested, B4 stated, B5 specified
not built.** Every number below is measured on this machine on 2026-08-03.

---

## 0. SCOPE — read this before anything else

> **S5 DOES NOT ADDRESS CORRECTNESS.** Correctness of natural-language reasoning
> is closed across six mechanism families and the result is **terminal**
> (`research/COMPETENCE_BOUND.md`). **A TEE running a wrong computation
> faithfully attests a wrong result.** A build attestation says *these bytes
> came from that source*; it says nothing about whether the computation those
> bytes perform is right.

S5 removes exactly one clause from one claim, and nothing else:

```
BEFORE:  execution was bounded  GIVEN AN HONEST RUNNER
AFTER:   execution was bounded  GIVEN A RUNNER WHOSE BINARY IS ATTESTED
                                TO MATCH PUBLISHED SOURCE
```

The gap being closed is concrete and already documented in the code it fixes:
`gyza/release.py`'s own docstring says *"a malicious binary can lie about its
hash."* Today the enforcement record is stamped by a runner that **self-reports
its own build**, so a modified runner can stamp a record describing a sandbox it
never entered.

**Framing S5 as correctness would be the single overclaim that undermines the
program**, and every artifact this route produced states the scope in its own
header (asserted by `test_the_module_states_its_scope_and_does_not_claim_correctness`).

---

## 1. B1 — bit-reproducible build: **ACHIEVED, and the fix is attributed**

`gyza/release.py:compute_source_tree_hash` already pins the **input** side.
The missing half was the **output** side: same source → same binary bytes.

**Method: build twice, compare the ACTUAL BYTES** of every regular file in the
onedir tree — not a manifest hash, not a file list.
Harness: `packaging/check_reproducible.sh`.

### The measured baseline, before any fix

| | result |
|---|---|
| launcher `dist/gyza/gyza` | **already byte-identical** (`5545eb1a…`) |
| files in the onedir tree | 142 |
| **files differing** | **1 — `_internal/base_library.zip`** |

**This distinction is load-bearing and is easy to overstate: the executable
itself was never the problem.** The non-determinism lived in a sibling file
inside the bundle. A claim of the form "the binary is reproducible" would have
been *true and useless*; the artifact that ships is the whole onedir tree.

### Diagnosing the one differing file

| property | result |
|---|---|
| member count | 155 vs 155 |
| member set | identical |
| members differing in **content** (CRC) | **0** |
| members differing in **timestamp** | **0** |
| **member ORDER** | **DIFFERS** — first mismatch at index 0, `heapq.pyc` vs `locale.pyc` |

Set-iteration order leaking into archive order. Nothing else.

### Attribution — measured, not assumed

| control | effect |
|---|---|
| `SOURCE_DATE_EPOCH=1700000000` alone | **NO EFFECT.** Two builds still differed in `base_library.zip`. |
| **`PYTHONHASHSEED=0`** | **THE FIX.** 3 builds byte-identical across all 142 files. |

`SOURCE_DATE_EPOCH` is retained in `packaging/build.sh` as a defensive control —
it is the standard knob and guards against a future toolchain that stamps mtimes
— but it is recorded as **having no measured effect on this toolchain**.
Crediting it would be crediting a control that did nothing, which is the same
error as crediting a guard for its throughput cost.

### The check has power — negative control included

`NO_CONTROLS=1 packaging/check_reproducible.sh` restores CPython's default
randomised hashing and **must fail**. It does: `base_library.zip` differs.

> **Disclosed defect in my own harness, found by running the negative control.**
> The first version disabled the control with `PYTHONHASHSEED=""`. `build.sh`
> reads `${PYTHONHASHSEED:-0}`, and `:-` treats the empty string as unset — so
> the "negative control" was silently handed `0` and **reported REPRODUCIBLE**.
> A check that cannot fail proves nothing. `PYTHONHASHSEED=random` is the only
> value that restores the default. This is the *registering-a-checker-is-not-
> evidence-it-runs* species, in a checker written the same hour.

### Residual non-determinism, reported rather than worked around

**None on this machine**, across 3 builds with controls and 142 files compared.

**What is NOT established, stated plainly:** all builds were on **one machine
with one interpreter**. Reproducibility *across machines* — different kernel,
different filesystem ordering, different CPU — is **not verified here**. The
release container `packaging/Dockerfile.build` (manylinux_2_28 + a pinned
python-build-standalone 3.14.6) exists and is the right vehicle, and the
cross-machine double-build is **user-owned work**: it needs a second machine,
which is exactly the same prerequisite as B2's second rebuilder.

---

## 2. B2 — the attestation format (`gyza/attest.py`)

A signed statement binding `source_tree_hash → artifact_hash`, reusing the
existing discipline exactly: **canonical JSON → BLAKE3 → Ed25519 sign-the-hash**,
via `cryptography` (the library `gyza/icp.py` uses), with `signature` excluded
from the payload so a signature cannot sign over itself.

`compute_artifact_hash` mirrors `compute_source_tree_hash`'s injective
length-prefixed wire format, covers **every file** (a manifest-level digest
would have missed `base_library.zip`, which is precisely where the only
non-determinism was), and hashes **symlinks by target string** rather than
following them, so a bundle cannot be altered by re-pointing a link.

### ONE SIGNER IS A TRUSTED THIRD PARTY WITH EXTRA STEPS

Stated in the module header, in the verify-side reason string, and asserted by a
test. A single attestation proves only that the builder asserts the binding.
**The property becomes meaningful at ≥ 2 independent rebuilders**, and the second
rebuilder — a second machine, a second operator — is **user-owned and cannot be
produced from inside this repository**.

`AttestationSet` therefore expresses **N-of-M from the start**:

- agreement is computed **on `artifact_hash`, the protected quantity** — never on
  a signature count and never on builder names. Counting signatures without
  checking they attest the *same bytes* is the monotonicity-over-a-label error
  this program has recorded three times;
- **independence is per pubkey**, so the same signer twice is one signer;
- **disagreement is never resolved by majority vote.** If two valid signers
  attest *different* binaries for identical source, that is a reproducibility
  failure or a compromised builder, and the set returns no agreed hash and says
  so;
- `threshold == 1` is reported by `is_degenerate` as a **disclosure, not an
  error**.

---

## 3. B3 — verify-side binary check (`gyza/release.py:is_trusted_binary`)

`is_trusted_release` pinned a **source-tree** hash; `is_trusted_binary` extends
trust to the **binary**, with four distinct verdicts (all tested):

| situation | verdict |
|---|---|
| source-tree hash mismatch | **False** — B3 never rescues a source mismatch |
| source trusted, no binary attested | **False**, and the reason says *the source is known, the bytes executing are self-reported* — a **weaker** verdict, not a failure of the source check |
| binary attested by 1 signer, threshold 1 | **True**, with the trusted-third-party disclosure in the reason |
| signers below threshold | **False**, naming the count and the threshold |

### THE CIRCULARITY, stated in the function's own comment

> **B3 alone is SELF-REPORTING AT A FINER GRAIN.** A runner that lies about its
> source-tree hash can equally lie about its artifact hash. Asking a binary
> which binary it is buys nothing on its own.

It is sound **only given B1 and B2**: without B1 the binding is not
independently recomputable; without B2 the trusted set has one signer. The code
says this where the function lives, and a test asserts the sentence is present.

---

## 4. B4 — WHAT S5 DOES NOT FIX

1. **Containment still ends at emission.** External sends
   (`gyza/network/netd_client.py`) leave modelled state. A guard can refuse to
   *emit*; after emission containment has no meaning, **and no detector would
   help either**. This is a limit, not a gap to be closed.
2. **Semantic correctness is untouched.** See §0. This is the one that must
   never be blurred.
3. **The fail-open enforcement default is a POLICY question (S4), not a
   build-integrity one.** `gyza/runner.py` runs the bounds check only when an
   enforcement record is present; an executor that stamps none skips it. S5 makes
   the *stamper* attestable; it does not make stamping *mandatory*.
4. **Without hardware attestation, S5 proves the binary matches the source but
   NOT that this binary is the one executing.** Nothing here observes the
   running process. That is B5's trust root, and it is a different one.
5. **Cross-machine reproducibility is unverified** (§1).
6. **The empty-record hole and compositor key rotation** are untouched; they are
   independent of build integrity.

---

## 5. B5 — TEE: SPECIFICATION, NOT AN IMPLEMENTATION

**A TEE binds a different statement from a reproducible build**, and the two are
complementary rather than substitutes:

| mechanism | statement bound | trust root |
|---|---|---|
| reproducible build + N-of-M attestation | *these bytes came from that source* | independent rebuilders |
| TEE quote | *these bytes are what is actually executing* | silicon vendor's key |

### What it would require here

1. **A measured launch path.** The onedir bundle's `artifact_hash` (§2) becomes
   the measurement, extended into a PCR/RTMR at load. Requires the bundle to be
   loaded by an attesting loader rather than by the current
   `gyza_launcher.py` self-re-exec.
2. **Quote generation at envelope-signing time**, with the quote's report-data
   field bound to the envelope hash — otherwise a valid quote can be replayed
   beside an unrelated envelope.
3. **A verifier-side vendor-root chain** (AMD SEV-SNP / Intel TDX endorsement),
   plus revocation handling. This is a **new trust root**, and adopting it means
   accepting a hardware vendor as a trusted party — a real cost that a
   reproducible build does not impose.
4. **Reconciling bubblewrap with the enclave.** The current enforced path
   re-execs itself under bwrap; inside a confidential VM the sandbox story must
   be re-derived, not assumed to carry over.

### What it removes

Item 4 of §4, and only that: it closes the gap between *the attested binary* and
*the executing process*.

### What it still does not fix

**Everything else in §4 — and most importantly §0.** A TEE does not make outputs
correct. **A system whose provenance is hardware-attested still cannot tell you
whether its work was right**, and a confidential VM faithfully executing a
subtly wrong program produces a perfectly attested wrong answer. Nor does a TEE
extend containment past emission: an enclave that sends a packet has sent it.

### Effort estimate

| item | estimate |
|---|---|
| measured-launch + PCR extension | 1–2 weeks |
| quote generation bound to envelope hash | ~1 week |
| verifier-side vendor chain + revocation | 2–3 weeks |
| bwrap-inside-CVM reconciliation | **unknown — the genuine risk**, 1–4 weeks |
| CI on attestation-capable hardware | user-owned (cloud CVM instances) |

**Total 5–10 weeks, with the sandbox reconciliation carrying the variance.**

**Recommendation:** the second rebuilder (B2) is worth far more per unit effort
than a TEE. It costs one machine and one operator, needs no new trust root, and
is what turns §2's degenerate `threshold=1` into a real property. A TEE should
follow a specific threat model that names an adversary with host access — not be
adopted because it sounds stronger.
