# ADR-0008: bwrap-based executor sandboxing

**Status:** Accepted (Session 10). Production wiring still pending
(CLAUDE.md §6 A3). Superseded by universal sandboxing in vNext
(ADR-0015 layer 8).

## Context

Phase 3 accepts work from strangers via cross-cluster discovery.
The executor surface is therefore a security boundary. Today's
Anthropic executor is HTTP-bound (no local code execution), but
Phase 4+ introduces tool-using and code-running executors where the
boundary becomes load-bearing.

Sandboxing primitives evaluated: Docker (heavyweight, requires
daemon), bwrap (lightweight, no daemon, Linux-native), gVisor
(performant but Linux-x86_64-only), Firecracker (VM-level isolation,
heavy).

## Decision

- **`bwrap` (bubblewrap)** as the sandbox primitive on Linux.
- New `gyza/sandbox/` module: `SandboxConfig`, `_HostMount`,
  `run_sandboxed`, `_entrypoint` (in-sandbox bootstrap), `executor`
  (sandboxed executor wrapper).
- **Defaults:** fresh net namespace, `--clearenv`, RLIMIT_AS = 2 GiB,
  RLIMIT_CPU = 300 s, wall-clock timeout = 120 s.
- **Argv ordering load-bearing:** system mounts → `/proc /dev` →
  `/tmp` tmpfs → user `ro_paths` → workspace. Tmpfs-before-ro_paths
  is essential (CLAUDE.md §16 trip-wire).
- **Symlink-vs-bind distinction:** `_HostMount(kind="symlink"|"bind")`
  emits `--symlink` for host symlinks (e.g., `/lib64` on merged-/usr
  distros). Binding a symlink as `--ro-bind` breaks the dynamic
  linker.
- **stdin/stdout protocol:** 8-byte-bigendian length-prefixed JSON.
  Required because sentence-transformers writes a load report to
  stdout on first import; stream-of-JSON would be corrupted.

## Consequences

**Intended:**
- Lightweight isolation suitable for inner-loop executor calls.
- Linux-native; no extra daemon to manage.
- Capability bounds: per-call FS allowlist, optional network,
  RLIMIT/timeout enforcement.
- Defends against: path traversal, FS persistence, network
  exfiltration, resource exhaustion, env leakage.

**Accepted costs:**
- Linux-only. macOS/Windows execution paths are unsandboxed today.
  (vNext layer 8 addresses with universal sandbox matrix
  TEE/WASM/bwrap.)
- Does NOT defend against: kernel CVEs in user namespaces,
  side-channels, malicious code in the trusted tree (anything in
  `ro_paths` is implicitly trusted).
- **Production wiring not yet done.** Demo/tests still use
  unsandboxed executors. Switching breaks the integration demo's
  timing unless bwrap-startup-time is validated. Acknowledged
  open item in CLAUDE.md §6 A3.

## Alternatives considered

- **Docker.** Rejected: heavyweight, requires daemon, slower
  startup, less ergonomic for per-call isolation.
- **gVisor.** Rejected: x86_64-Linux-only, performance overhead.
- **Firecracker / VMs.** Rejected: minutes-of-startup; overkill for
  per-call isolation.
- **No sandbox.** Rejected: cross-cluster work claim opens executor
  to adversarial input; need defense in depth.

## References

- `gyza/sandbox/` — sandbox module
- `gyza/sandbox/runner.py::_build_bwrap_argv` — argv builder
- CLAUDE.md §5c (Session 10 narrative)
- CLAUDE.md §16 (don't-do entries on bwrap argv ordering)
- ADR-0015 (vNext layer 8 — universal sandboxing matrix)
