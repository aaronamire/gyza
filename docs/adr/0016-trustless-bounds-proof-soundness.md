# ADR-0016: Trustless bounds-proof — soundness theorem, assumptions, remaining gaps

**Status:** Accepted (Session 34). Soundness-statement ADR; ships
with bricks 1–3 + manifest delivery + memory-bound predicate.

## Context

Bricks 1–3 (Sessions 31–33) and the manifest-delivery wire change
(early S34) built the system that turns a signed envelope into a
verifiable claim that an AI agent's work executed inside bounds
declared in its capability manifest. The cli now stamps
`✓ bounded (INDEPENDENTLY VERIFIED)` on `gyza submit` output when
all checks pass.

It is a structural mistake to describe this with hand-wavy
language. The system makes a precise claim, depends on precise
assumptions, and has a precise (and shrinking) set of unclosed
gaps. This ADR states all three, so future sessions can extend the
theorem rather than rediscover its shape, and so the property is
publicly defensible.

## Decision: the soundness theorem we ship

Let `e = ICPEnvelope` be a result the submitter received, `M` the
capability manifest delivered alongside `e`, and `E` the
`__enforcement__` record inside the artifact bytes `A` whose hash
appears in `e.output_hash`.

Define the predicate `verify(e, M)` as the conjunction of:

```
V1.  Ed25519_verify(sig=e.signature,
                    msg=blake3(canonical(e \ signature)),
                    pk=e.agent_pubkey)
V2.  blake3(A) == e.output_hash
V3.  blake3(canonical_json(M)) == e.capability_manifest_hash
V4.  enforcement_satisfies_manifest(E, M)
```

where `enforcement_satisfies_manifest` is the pure predicate at
`gyza/sandbox/config.py` checking:

  - `E.backend == "bubblewrap"`
  - `E.ro_paths ⊆ M.capabilities.filesystem.read`
  - `E.rw_paths ⊆ M.capabilities.filesystem.write`
  - `E.requires_network ⟹ |M.capabilities.network.allowed_hosts| > 0`
  - if `M.capabilities.spawn.resource_budget.memory_limit_mb`
    is declared (positive int):
      `E.max_memory_mb` is a positive int **and**
      `E.max_memory_mb ≤ M.capabilities.spawn.resource_budget.memory_limit_mb`

**Theorem (current state, stated precisely):**

> Under the assumptions A1–A5 below, `verify(e, M) ⟹ E faithfully
> describes the bwrap sandbox configuration under which the
> execution that produced `e` ran, **and** that configuration is
> consistent with — i.e. no wider than — what `M` authorizes along
> the dimensions `enforcement_satisfies_manifest` checks (FS read,
> FS write, network on/off, memory bound).

This is what makes it correct to print `INDEPENDENTLY VERIFIED`.

## Assumptions on which V1–V4 ⟹ bounded execution

**A1. Cryptographic primitives.** Ed25519 unforgeability and
BLAKE3 collision-resistance. Universal in this codebase; same
assumption as every signed envelope.

**A2. Bwrap correctness.** Linux user namespaces, mount
namespaces, and network namespaces enforce exactly what the bwrap
manual page says they do. A kernel CVE in namespace isolation
voids this. Considered a fixed assumption; not codeable around.

**A3. Bwrap namespace coverage (audit owed).** The codebase
invokes bwrap with `--unshare-all` (or equivalent) by default,
which unshares pid/ipc/uts/cgroup/user/mount/network. The audit
of `gyza/sandbox/runner.py`'s argv construction is required to
keep this assumption tight — any change that drops an `unshare`
flag silently breaks the theorem. Tracked: keep a single grep
target (`--unshare-` in `gyza/sandbox/runner.py`) inspected on
every change to sandbox code.

**A4. Host integrity for the stamp.** `make_sandboxed_executor.
_wrapped` runs in the **parent**, after `run_sandboxed` returns,
and overwrites any key the sandboxed code may have set. Therefore
the sandboxed process **cannot forge `E`**. **However:** whoever
controls the parent's binary controls what `E` is stamped to be.
A hostile daemon operator could patch the wrapper to stamp `E` =
`{ro_paths: ["/tmp"], ...}` while invoking bwrap with `ro_paths
= ["/tmp", "/etc", "/var", ...]`.

The current theorem therefore **presumes an honest parent
binary**. This is the largest unclosed assumption. See "Path to
closing A4" below.

**A5. The runner gate is in the path the executor's result
takes.** That is: every envelope this submitter accepts as
`INDEPENDENTLY VERIFIED` came through `runner._execute`'s gate at
sign time. The gate refuses to sign when `E ⊄ M`, so this is
self-consistent — *if* the runner is the v1 code. A subverted
runner (e.g., a fork that removes the gate, signs anyway) would
ship a wider `E` than the manifest authorizes, which V4 catches
at submission time. Hence: **A5 is not actually an assumption;
V4 is what makes the runner gate trustless to the submitter.**
Documented here to head off confusion.

## Remaining gaps (honest scope)

### G1. Host integrity (the residual of A4) — MEDIUM-HIGH

Closes via:

- **G1a (cheap, partial):** Include `runner_binary_hash` (sha256
  of the daemon binary at startup) in the envelope. Foundation
  publishes a signed manifest of trusted release hashes; submitter
  rejects envelopes from unknown releases. Raises the bar
  (attacker must publish a fork as a trusted release) but does
  not eliminate trust in the binary itself.
- **G1b (real):** TEE remote attestation (Intel TDX, AMD
  SEV-SNP, ARM CCA). The remote attestation report covers the
  bwrap-invoking binary's code + initial memory; verifier knows
  it's the exact code claimed. This is vNext layer 8.
- **G1c (alternative):** Threshold attestation of the
  enforcement record — K independent hosts execute the same
  work, agree on `E`, sign as a quorum. Expensive (K× compute)
  but uses existing Tier-3 machinery.

G1a is shippable in ~1 session; G1b is part of the layer-8
TEE work; G1c is a research direction.

### G2. Network bounds are coarse — MEDIUM

`E.requires_network` is binary; `M.capabilities.network.
allowed_hosts` declares specific hosts but bwrap cannot enforce
per-host firewall rules at the namespace level. The predicate
labels this dimension as "declared, not enforced" — the bounds
shown say "network: open" with no host allowlist verified.

Closes via:

- A filtering proxy (mitmproxy-shaped) inside the sandbox net
  namespace, with an allowlist derived from the manifest. The
  enforcement record would include the proxy's allowlist; the
  predicate would check `E.allowed_hosts ⊆ M.allowed_hosts`.
- Or a TEE-attested userspace network stack.

### G3. CPU-time bound — LOW

`SandboxConfig.max_cpu_seconds` is enforced (RLIMIT_CPU) but the
manifest has only `cpu_quota_percent` (a fraction, not an
absolute bound), so no compare predicate exists. To close: add
`manifest.capabilities.spawn.resource_budget.cpu_seconds_max:
int | None` and extend the predicate symmetrically with the
memory check.

### G4. Wall-clock bound — LOW

`E.timeout_s` is stamped for transparency but the manifest has
no wall-clock field. Same shape as G3.

### G5. Output correctness vs. operational bounds — RESEARCH

The bounds-proof says nothing about whether the OUTPUT is what
was asked. An agent perfectly bounded operationally can still
produce misinformation, jailbroken responses, or just be wrong.
Tier-3 covers a slice (proof-of-capability is per-agent, not
per-output). Per-output correctness via zk-ML, verifiable
inference, or multi-validator consensus is genuinely open
research; orthogonal to the operational-bounds story.

## Path to closing A4 (host integrity)

Priority order, all on the vNext substrate:

1. **G1a** — runner_binary_hash + Foundation release manifest.
   Cheapest; raises the bar to "must publish a fork as a trusted
   release." Ship before TEE work begins, as the staging step.
2. **G1b** — TDX/SEV-SNP attestation. The "real" close. Aligns
   with §8 layer 8 (Execution).
3. **G1c** — Quorum-attested execution. Parallel research path;
   doesn't require TEE hardware, but K× the compute. Useful
   where TEE is not available (consumer, mobile, embedded).

## Consequences

**Positive:**

- The system makes a stated cryptographic claim and we can defend
  it under attack. Independent re-verification by `gyza submit`
  is not lipstick: it runs the predicate locally on the submitter
  machine using only open-source code + Ed25519/BLAKE3, and the
  predicate's failure modes are exactly the ones an attacker
  would try.
- The remaining assumption (A4) is named and bounded; the
  closure plan is concrete.
- Future sessions extending the predicate (G3, G4) have a clean
  template: extend `enforcement_satisfies_manifest`, extend the
  stamp, extend the cli display, write predicate tests, write
  ADR delta. The pattern is mechanical.

**Negative:**

- The honest labeling — "✓ bounded (INDEPENDENTLY VERIFIED)" vs.
  "claimed but not independently verifiable" vs. "BOUNDS-PROOF
  FAILED" vs. "no bounds-proof" — is a four-state output where
  many products would just say "verified." Marketing surface is
  smaller; technical surface is correct. We pay clarity tax
  willingly.
- The predicate code is a security-critical surface. Bugs in
  `enforcement_satisfies_manifest` invalidate the theorem
  silently. Mitigation: every branch has a focused predicate
  test in `tests/test_sandbox.py`; CI fails on a missing branch.

## References

- Soundness keystone: bricks 1–3 commits S31–S33.
- Trustless verification: S34 commit `4759245`.
- Resource bound + manifest cleanup: this ADR's session.
- Predicate code: `gyza/sandbox/config.py::
  enforcement_satisfies_manifest`.
- Stamp code: `gyza/sandbox/executor.py::
  make_sandboxed_executor._wrapped`.
- Runner gate: `gyza/runner.py::_execute`.
- Wire: `gyza/network/result_delivery.py`.
- Submitter checks: `gyza/cli.py::cmd_submit` display block.
- Tests: `tests/test_sandbox.py` (predicate),
  `tests/test_runner.py` (gate), `tests/test_result_delivery.py`
  (wire + submitter checks).
