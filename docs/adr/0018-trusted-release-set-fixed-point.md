# ADR-0018: Dissolving the trusted-release fixed point

**Status:** Accepted (Session 34). Design-correction ADR for G1a
(ADR-0017). Ships with the `trusted_releases.json` refactor and
`scripts/cut_release.py`.

## Context

G1a (ADR-0017) added runner attestation: the runner stamps
`(runner_version, runner_source_tree_hash)` into `__enforcement__`;
the submitter checks the pair against `TRUSTED_RELEASES`; the
strongest verdict-tree state is `✓ bounded (INDEPENDENTLY VERIFIED
+ RUNNER ATTESTED)`.

`TRUSTED_RELEASES` was a Python dict literal **in
`gyza/release.py`**. `compute_source_tree_hash()` hashes every
`gyza/**/*.py` — including `release.py`.

## The flaw (discovered cutting the first release)

To pin release `0.1.0` you must write its own
`source_tree_hash = H` into `release.py`. But `release.py` is in
the hashed tree:

```
write H into release.py  →  release.py bytes change
→  source_tree_hash ≠ H  →  recompute H'  →  write H'
→  bytes change again  →  source_tree_hash ≠ H'  →  … (diverges)
```

BLAKE3 gives no reason for this iteration to converge, and a fixed
point — if one even existed — is not findable without brute force.

**Consequence:** `+ RUNNER ATTESTED`, the strongest state in the
G1a verdict tree, was **unreachable in principle for every
release**, not merely unimplemented. Shipping a feature that is
logically impossible to activate is a defect, not a TODO.

## Decision

Move the trusted-set **data** out of the hashed tree into
`gyza/trusted_releases.json`. `compute_source_tree_hash` globs
only `*.py`, so the JSON is excluded by construction: writing a
release's own hash into it cannot perturb that hash. The fixed
point is dissolved — not approximated, eliminated.

The verification **logic** — `is_trusted_release`,
`compute_source_tree_hash`, `_load_trusted_releases` — stays in
`*.py` and so stays hash-covered. An attacker still cannot change
*how* trust is evaluated without changing the tree hash; they can
only change *what* is trusted, which is policy the trust model
already governs.

`scripts/cut_release.py` encodes the only correct ordering (set
version → freeze `*.py` → hash → write JSON) and refuses to cut a
release unless it can re-prove, on that run, that writing the JSON
leaves the hash invariant. If that invariant is ever broken
(someone renames the file to `.py`, or makes
`compute_source_tree_hash` include it), `cut_release.py` hard-fails
rather than silently reintroducing the divergence.

## Why this is *more* correct, not a workaround

Under the old scheme a release's hash committed to its own
trusted-set contents. So an honest client that later added a peer
release to its trust list would change its *own binary identity
hash* — even though the runtime behavior of every line of
verification code is byte-identical. That is wrong: **code
identity must be invariant under trust-policy changes.** The trust
set is policy data (which releases this client honors), not code
(how trust is decided). Separating data from code gives the
correct invariant for free. The fixed-point dissolution is a
*consequence* of modeling the system correctly, not a hack to
escape it.

## Trust model (unchanged from ADR-0017)

A submitter trusts the `trusted_releases.json` that shipped in
**its own** `pip install`, never one fetched from the daemon it is
querying — exactly the package-signing model ADR-0017 specified.
The wheel **force-includes** the JSON
(`[tool.hatch.build.targets.wheel.force-include]`) so a
missing-from-wheel bug cannot silently downgrade every installed
client to "unverified build" (which would make `+ RUNNER ATTESTED`
unreachable for pip-installed clients — the very failure this ADR
removes).

## Fail-safe direction

`_load_trusted_releases` returns `{}` on a missing, unparseable,
or malformed file, and drops any entry lacking a
`source_tree_hash`. The failure direction is always "nothing
trusted → everything honestly labeled unverified", **never**
"fail open → everything trusted". Locked by
`test_corrupt_or_missing_trusted_releases_fails_safe`.

## What this ADR does NOT change

The residual G1a explicitly does not close — a malicious binary
can lie about its own self-reported `(version, hash)` — is
**unchanged**. ADR-0018 is solely about making the trusted-set
mechanism *reachable and semantically correct*. The self-report
circularity is still closed only by reproducible-build +
third-party attestation → Foundation-key-signed manifest → TEE
(ADR-0017 §"Path forward"). This JSON-in-client design is the
clean precursor to the Foundation-signed manifest: the signature,
when it exists, signs exactly this file.

## Consequences

**Positive**
- `+ RUNNER ATTESTED` is now reachable. `cut_release.py 0.1.0
  --dry-run` proves end-to-end: hash invariant under the JSON
  write, `is_trusted_release(0.1.0, H) == (True, "")`.
- Code identity is invariant under trust-policy edits — the
  correct invariant.
- Cutting a release is one reproducible command with a built-in
  self-check that refuses to proceed if the fixed point ever
  silently returns.
- `is_trusted_release` now distinguishes three negatives —
  no-releases / unknown-version / version-known-but-tree-differs
  (the last is the "tampered or rebuilt" signal, strictly more
  informative than the old binary answer).

**Negative**
- The trusted set is no longer covered by the source-tree hash.
  This is intended (it is policy, not code) but means its
  integrity rests entirely on the "trust your own pip install"
  model until the Foundation-signed-manifest step lands. Stated
  here so it is a known, deliberate boundary, not a latent
  surprise.
- One canonical `source_tree_hash` per version: a legitimate
  rebuild producing different bytes (toolchain drift) will not
  match. Acceptable and arguably desirable — one version string
  should denote one canonical tree — but it makes reproducible
  builds a hard requirement for the eventual third-party
  attestation step, not a nice-to-have.

## References
- Flaw in: ADR-0017 (`TRUSTED_RELEASES` as a `*.py` literal).
- Code: `gyza/release.py` (`_load_trusted_releases`,
  `is_trusted_release`), `gyza/trusted_releases.json`,
  `scripts/cut_release.py`, `pyproject.toml`
  (`wheel.force-include`).
- Tests: `tests/test_release.py` —
  `…json_does_not_perturb_source_tree_hash` (the dissolution
  lock), `…fails_safe`, `…exact_version_and_hash_match`,
  `…shipped_trusted_releases_json_is_valid_and_currently_empty`
  (tripwire).
- Next: Foundation-key-signed release manifest (signs this JSON)
  → reproducible builds + third-party attestation → TEE
  (ADR-0017 path forward).
