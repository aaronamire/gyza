# ADR-0017: Runner attestation via source-tree hash (G1a)

**Status:** Accepted (Session 34). Soundness-delta ADR; partial
closure of ADR-0016 §A4 (host integrity). Ships with
`gyza/release.py`, the runner-identity stamp, and the cli
verdict extension.

## Context

ADR-0016 stated the bounds-proof soundness theorem and named A4
(host integrity) as the largest residual: `__enforcement__` is
stamped by `make_sandboxed_executor._wrapped` in the trusted
parent, so the sandboxed code cannot forge it — but **the parent
binary is whoever runs the daemon**. A hostile operator can patch
the wrapper to stamp tighter bounds than bwrap actually enforced.
The submitter, given only the signed envelope, had no way to tell
which binary did the stamping.

ADR-0016 listed three closure paths: G1a (binary-hash + trusted
release set — cheap, partial), G1b (TEE remote attestation —
real, vNext L8), G1c (threshold-attested execution — research).
This ADR is G1a.

## Decision

The runner self-reports a release identity inside the
`__enforcement__` record:

```
runner_version          : str   (gyza.__version__)
runner_source_tree_hash : str   (BLAKE3-256 of gyza/**/*.py)
```

`compute_source_tree_hash` (`gyza/release.py`) is a deterministic,
injective content hash with a pinned contract (locked by
`tests/test_release.py`):

- **install-location independent** — only paths *relative to the
  package root* feed the hash;
- **toolchain independent** — generated protobuf
  (`*_pb2.py`, `*_pb2_grpc.py`) excluded; its bytes vary by
  protoc version for identical `.proto`;
- **enumeration-order independent** — files sorted by POSIX
  relative path;
- **injective under concatenation** — every field
  length-prefixed (`b"P"||u32(len)||relpath`,
  `b"D"||u32(len)||bytes`), so the classic
  `("ab","")` vs `("a","b")` boundary collision cannot occur;
- **scoped to `*.py`** — non-source files (README, data) do not
  perturb identity; `__pycache__` never does.

`CURRENT_RELEASE` is computed **once at module import** — matching
the intended semantics of "the binary's identity at process
start." A daemon that hot-swaps source mid-process keeps reporting
its load-time hash, which then mismatches the on-disk tree: an
honest signal that something is wrong, not a silent drift.

The submitter checks `(runner_version, runner_source_tree_hash)`
against `TRUSTED_RELEASES` — a **source-pinned literal in the
submitter's own client**, not a value fetched from the daemon
being queried. This is the package-signing trust model: you trust
the keyring your client shipped with. The set is empty until the
first tagged release; until then every runner is honestly labeled
"unverified build."

### Orthogonality (a deliberate design constraint)

Runner identity does **not** enter
`enforcement_satisfies_manifest`. The predicate proves
`enforcement ⊆ manifest`; runner attestation proves *which binary
produced that enforcement record*. These are distinct axes.
Conflating them would let an untrusted build's bounds pass merely
because the predicate held — exactly the failure G1a exists to
surface.

### Verdict tree (cli)

`all_ok` (process exit code) is **unchanged**:
`verified ∧ (¬bounds_claimed ∨ bounds_independently_verified)`.
Runner-trust does **not** flip pass/fail — it caps *claim
strength*. Rationale: the bounds are still cryptographically
re-checked by the submitter regardless of runner trust; failing
the exit code on an unverified build would regress every
development build (including the user's own) to a hard error and
make the tool unusable pre-release. A future
`--require-trusted-runner` strict flag can opt into hard failure;
the default is honest labeling.

Five terminal states:

| State | Exit | Message |
|---|---|---|
| verified ∧ bounds-verified ∧ runner trusted | 0 | `INDEPENDENTLY VERIFIED + RUNNER ATTESTED` — strongest |
| verified ∧ bounds-verified ∧ runner unverified | 0 | `INDEPENDENTLY VERIFIED` + ⚠ unverified-build caveat |
| verified ∧ bounds claimed, manifest not delivered | 0 | claimed but not independently verifiable |
| verified ∧ no bounds claim | 0 | no bounds-proof (legacy/v1) |
| bounds claim failed (hash mismatch / predicate) | 5 | `BOUNDS-PROOF FAILED` |
| signature/artifact failed | 5 | `VERIFICATION FAILED` |

## What G1a buys (precisely)

It moves the trust anchor from **"trust whoever runs the
daemon"** to **"trust whoever curates the trusted-release set,
AND assume the binary honestly self-reports its hash."**

Attack-surface delta:

| | Pre-G1a | Post-G1a |
|---|---|---|
| Forge bounds via patched daemon | undetectable | binary either lies about its hash (see residual) or honestly reports a non-trusted hash → caught at submission as "unverified build" |
| Trust roots | 1 (the host) | 2 (client's release set + honest self-report) |
| Dev/test builds | indistinguishable from prod | explicitly labeled "unverified build", bounds still checked |

## What G1a does NOT buy (the residual)

**The self-reported hash is computed by the binary itself. A
malicious binary can lie about it.** Trusted-set membership only
bounds *which lie* is accepted: an attacker must forge the entire
stamp pipeline to be byte-consistent with a known trusted
release's `(version, hash)` — non-trivial, but not impossible
for a determined operator who controls the host.

Honest closure requires breaking the "binary attests itself"
circularity:

- **Reproducible builds + independent verification.** Anyone
  rebuilds `gyza==X` from public source, confirms the tree hash,
  and (ideally) a third party publishes a signed attestation
  binding `version X ↔ tree-hash H`. The submitter then trusts
  the third party, not the daemon. This is the next concrete
  step and is *code+process*, not hardware — should be done
  before TEE work.
- **TEE remote attestation (G1b).** TDX / SEV-SNP / CCA report
  covers the stamping binary's code + initial memory; the
  verifier learns it is the exact code claimed. vNext L8.
- **Threshold-attested execution (G1c).** K independent hosts
  execute, agree on the enforcement record, sign as a quorum.
  Uses existing Tier-3 machinery; K× compute cost; no TEE
  hardware required (useful for consumer/mobile/embedded).

## Deliberate non-inclusions

- **Python interpreter hash is OUT.** The "trusting trust" chain
  (Thompson) does not terminate: interpreter → libc → kernel →
  microcode → silicon. We draw the line at the gyza source tree
  and name the rest as standard platform trust assumptions,
  alongside A2 (bwrap correctness). Adding the interpreter hash
  adds noise (it legitimately varies across distros/patch
  levels) without removing the residual, which is the
  self-report circularity, not interpreter coverage.
- **Foundation-key-signed out-of-band release manifest is OUT
  for this turn.** The source-pinned `TRUSTED_RELEASES` literal
  is trust-anchor-equivalent to "trust the client you
  installed." A Foundation Ed25519 key signing a fetched release
  manifest is a strict improvement (decouples release curation
  from client release cadence) and is the natural next step, but
  it requires the Foundation key lifecycle (`gyza foundation
  init` / `sign-release`) which is its own change.

## Failure-mode decision

`CURRENT_RELEASE` is computed at import of `gyza.release`. If
`compute_source_tree_hash()` raises (file removed mid-rglob,
permission error, zipimport where `Path(__file__)` is not a real
directory), the import fails and the daemon does not start.

This is **deliberately fail-closed**: a process that cannot hash
its own source has no business stamping bounds-proofs. The
alternative (degrade to "unknown" on error) is rejected because
an attacker could *induce* the error to suppress attestation. Ops
cost accepted: a broken package install fails loudly at startup
rather than silently shipping unattested bounds.

## Consequences

**Positive:**
- A4 is partially closed with code only — no hardware, no new
  key lifecycle. The trust surface shrinks from "any operator"
  to "operator running a self-reported trusted-release hash."
- The cli now distinguishes the strongest claim
  (`+ RUNNER ATTESTED`) from the dev/unverified state, honestly,
  without breaking the dev workflow (exit 0 preserved).
- The determinism contract is locked by tests; a future change
  that breaks reproducibility fails CI rather than silently
  voiding the trusted set.

**Negative:**
- The residual (self-report circularity) is real and named; G1a
  is explicitly a *staging step*, not the close. Marketing must
  not call this "attested execution" — it is "trusted-release
  self-report."
- Every source change moves the tree hash. Pre-release this is
  fine (everything is "unverified build"). Post-release, the
  release process MUST update `TRUSTED_RELEASES` in the same
  signed commit that cuts the tag, or the just-released daemon
  reports a hash absent from its own client's trusted set.
- `import gyza.release` walks the package tree once. One-time,
  ~ms for 49 files; negligible but noted.

## References

- Residual closed (partially): ADR-0016 §A4, §"Path to closing
  A4" G1a.
- Code: `gyza/release.py`,
  `gyza/sandbox/executor.py::make_sandboxed_executor._wrapped`,
  `gyza/cli.py::cmd_submit` verdict tree.
- Tests: `tests/test_release.py` (determinism contract +
  trusted-set lookup).
- Next steps, in order: reproducible-build + third-party
  attestation (code+process) → Foundation-key-signed release
  manifest → G1b TEE (vNext L8) → G1c threshold execution.
