"""
SandboxConfig — declarative description of what an executor needs.

The config is consumed by ``runner.run_sandboxed`` to build the bwrap
argv. It is intentionally independent of bubblewrap-specific syntax —
a future macOS / WSL backend would consume the same dataclass.

Three orthogonal axes:

  * **filesystem visibility** — what's read-only, what's read-write,
    what's tmpfs (visible but ephemeral). The default is the smallest
    set of paths that lets a Python interpreter import the stdlib
    plus its installed site-packages. Callers add their executor's
    specific data paths (e.g., a model weights directory).

  * **network reachability** — boolean for now. ``True`` means
    ``--share-net`` (host network is reachable, including outbound DNS
    and any service the user reaches). ``False`` means a fresh net
    namespace with only loopback.

  * **resource limits** — RLIMIT_AS (virtual memory cap), RLIMIT_CPU
    (cpu seconds), and a wall-clock timeout enforced by the parent.
    Distinct from cgroup-based control, which would need root or
    systemd-run; rlimits are sufficient at Phase 3 scale.
"""
from __future__ import annotations

import enum
import os
import sys
import sysconfig
from dataclasses import dataclass, field


class SandboxBackend(str, enum.Enum):
    """
    Which sandbox implementation to use. Values are stable strings so
    they survive serialization across the JSON protocol boundary.

    BUBBLEWRAP — Linux ``bwrap`` subprocess (current production path).
    NONE       — direct execution in the parent process; no isolation.
                 Selectable as a fallback ONLY when callers explicitly
                 opt in. Logs a warning at construction time.
    """

    BUBBLEWRAP = "bubblewrap"
    NONE = "none"


@dataclass(frozen=True)
class _HostMount:
    """
    A single host-path entry derived from system inspection. The
    ``kind`` field selects the bwrap flag pair: ``"bind"`` → ``--ro-bind``,
    ``"symlink"`` → ``--symlink TARGET DEST`` (where TARGET is the
    relative or absolute symlink target).

    Distinguishing symlinks matters for merged-/usr distros (Arch,
    Fedora, recent Debian) where ``/lib`` and ``/lib64`` are symlinks
    to ``usr/lib``. Bind-mounting them as directories breaks the
    dynamic-linker path ``/lib64/ld-linux-x86-64.so.2`` because the
    kernel resolves the path before the bind takes effect; faithful
    symlink reproduction is the only thing that works.
    """
    kind: str
    src: str
    dest: str


def _system_mounts() -> list[_HostMount]:
    """
    Internal helper: return system mounts as ``_HostMount`` records.
    Useful for the bwrap argv builder; ``default_system_paths`` is
    a back-compat thin wrapper that returns just the destination strings.
    """
    raw: list[str] = ["/usr", "/etc"]
    for p in ("/lib", "/lib64", "/bin", "/sbin"):
        if os.path.lexists(p):
            raw.append(p)
    raw.append(sys.prefix)
    raw.append(sys.base_prefix)
    stdlib = sysconfig.get_paths().get("stdlib")
    if stdlib and os.path.lexists(stdlib):
        raw.append(stdlib)
    platlib = sysconfig.get_paths().get("platlib")
    if platlib and os.path.lexists(platlib):
        raw.append(platlib)

    # Dedup destinations while preserving order. Two paths with the
    # same realpath are NOT considered duplicates — see _HostMount
    # docstring.
    seen_dest: set[str] = set()
    out: list[_HostMount] = []
    for p in raw:
        if p in seen_dest:
            continue
        seen_dest.add(p)
        if os.path.islink(p):
            target = os.readlink(p)
            out.append(_HostMount(kind="symlink", src=target, dest=p))
        else:
            out.append(_HostMount(kind="bind", src=p, dest=p))
    return out


def default_system_paths() -> list[str]:
    """
    Smallest set of host paths that lets a Python interpreter boot,
    import stdlib, and import site-packages from the running
    interpreter.

    Returns destination paths only — the bwrap flag (``--ro-bind`` vs
    ``--symlink``) is decided by the runner via ``_system_mounts()``.

    Computed from ``sys`` and ``sysconfig`` rather than hard-coded so
    we work both inside the marshal venv and on a vanilla install.

    Notes:

      * We do NOT add ``/`` — that would expose the entire host
        filesystem read-only including ``~/.ssh`` and the user's
        compositor key. Allowlist-only is the only correct posture
        for "running stranger code."
      * ``/etc`` is included so DNS (``resolv.conf``), CA certificates
        (``ssl/certs``), and ``/etc/passwd`` (for user-id resolution by
        random C extensions) work. It IS user-controlled state — but
        on a single-user dev box it's the same trust boundary as
        ``/usr``.
      * ``/proc`` and ``/dev`` are NOT here; bwrap mounts a fresh
        ``--proc /proc`` and ``--dev /dev`` so the sandboxee sees a
        clean view, not the host's process table.
      * Symlinks like ``/lib64 → usr/lib`` are reproduced as symlinks,
        not as directory binds — see ``_HostMount`` docstring.
    """
    return [m.dest for m in _system_mounts()]


@dataclass
class SandboxConfig:
    """
    Declarative description of a sandbox session.

    Fields:

      ro_paths
        Additional host paths to bind read-only (on top of
        ``default_system_paths()``). The gyza package source goes
        here when running ``make_sandboxed_executor``.

      rw_paths
        Host paths bound read-write. Use sparingly — anything here
        survives the sandbox and is owned by whoever ran the
        sandboxee. Default empty.

      workspace
        A path on the host that is bind-mounted as the sandboxee's
        current working directory AND made read-write inside. The
        executor can drop output files here; the parent collects them
        after the call. ``None`` means a per-invocation tmpfs.

      requires_network
        ``True`` enables host networking; ``False`` (default) creates
        a fresh net namespace with loopback only. Anthropic-shaped
        executors set ``True``; mock and pure-local set ``False``.

      env_passthrough
        Names of environment variables to forward into the sandbox.
        Default forwards nothing (a fresh env). Caller-controlled —
        Anthropic executor adds ``["ANTHROPIC_API_KEY"]`` plus
        ``PATH`` ``HOME`` ``LANG`` if needed.

      env_set
        Explicit ``{name: value}`` pairs to set inside the sandbox.
        Useful for test-only fixed values (e.g., ``HOME=/tmp/sandbox``).

      max_memory_mb
        RLIMIT_AS in megabytes, set inside the sandboxee. ``None`` =
        no cap (be careful — a runaway tokenizer can OOM the host).

      max_cpu_seconds
        RLIMIT_CPU. Soft + hard set together, so the sandboxee gets
        SIGXCPU then SIGKILL.

      timeout_s
        Wall-clock cap enforced by the parent via
        ``subprocess.run(timeout=...)``. Backstop for cases where
        rlimit doesn't kick in (e.g., process is stuck in I/O).

      backend
        Which backend to use. Default ``BUBBLEWRAP``. Callers in
        controlled environments can pick ``NONE`` to bypass — the
        runner logs a warning and runs in-process.
    """

    ro_paths: list[str] = field(default_factory=list)
    rw_paths: list[str] = field(default_factory=list)
    workspace: str | None = None
    requires_network: bool = False
    env_passthrough: list[str] = field(default_factory=list)
    env_set: dict[str, str] = field(default_factory=dict)
    max_memory_mb: int | None = 2048
    max_cpu_seconds: int | None = 300
    timeout_s: float = 120.0
    backend: SandboxBackend = SandboxBackend.BUBBLEWRAP


__all__ = [
    "SandboxBackend",
    "SandboxConfig",
    "default_system_paths",
    "_system_mounts",
]
