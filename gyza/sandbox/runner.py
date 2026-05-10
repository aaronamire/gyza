"""
Sandbox runner — turns a SandboxConfig into a bwrap subprocess.

Public API:

  detect_backend()      -> SandboxBackend
  run_sandboxed(req, cfg) -> SandboxResult

``run_sandboxed`` is the single boundary between Python and bubblewrap.
Callers above it (see ``executor.py``) deal in executor protocol;
callers below see only argv strings, env, and bytes.

THREAT MODEL — what this defends against:

  * Path traversal in ``context``:  the inner executor receives
    arbitrary attacker-controlled paths via the ``context`` dict.
    Without sandboxing, ``open(path, 'rb')`` reads any host file the
    process can. Inside a bwrap with allowlisted ``ro_paths``, only
    paths under explicitly-bound trees are visible.

  * Filesystem persistence by the inner executor:  the sandboxee
    can ``write_text(...)`` anywhere it can — without sandboxing
    that's the whole user home. Inside the sandbox, only ``rw_paths``
    and ``workspace`` accept writes.

  * Network exfiltration:  unless ``requires_network=True``, the
    sandboxee runs in a fresh net namespace with only loopback,
    so a misbehaving executor cannot phone home.

  * Resource exhaustion:  RLIMIT_AS + RLIMIT_CPU + the parent's
    ``timeout_s`` together bound memory, cpu, and wall-clock.

What this DOES NOT defend against:

  * Kernel-level vulnerabilities — bwrap rides on user namespaces,
    which historically have been a CVE pump. A kernel-bug exploit
    inside the sandbox can break out.
  * Side-channels (timing, cache, /proc/self/cpuinfo).
  * Malicious code in trusted modules — anything in ``ro_paths``
    is implicitly trusted. Don't put attacker-controlled code paths
    in ``ro_paths``.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import struct
import subprocess
from dataclasses import dataclass
from typing import Any

from gyza.sandbox.config import (
    SandboxBackend,
    SandboxConfig,
    _system_mounts,
)


LOG = logging.getLogger("gyza.sandbox")

_HEADER_FMT = "!Q"
_HEADER_SIZE = 8

_ENTRYPOINT_MODULE = "gyza.sandbox._entrypoint"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class SandboxUnavailableError(RuntimeError):
    """Raised when the requested backend isn't usable on this host."""


class SandboxTimeoutError(RuntimeError):
    """Wall-clock timeout exceeded inside the sandbox."""


class SandboxExecutionError(RuntimeError):
    """The sandboxee returned a structured error; carries the inner type/message."""

    def __init__(self, message: str, exc_type: str = "", inner_traceback: str = ""):
        super().__init__(message)
        self.exc_type = exc_type
        self.inner_traceback = inner_traceback


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SandboxResult:
    """
    Successful sandbox run.

    ``payload`` is the dict returned by the inner executor.
    ``stderr`` carries everything the sandboxee wrote to fd 2 (model-load
        progress bars, deprecation warnings, etc.) — not load-bearing,
        but useful for debugging.
    """
    payload: dict[str, Any]
    stderr: str = ""
    duration_s: float = 0.0


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

def detect_backend() -> SandboxBackend:
    """
    Probe the host for a usable backend. Order of preference:

      1. bubblewrap, IF the binary exists AND user namespaces are
         enabled (we test both; some distros ship bwrap-suid which
         doesn't need userns, others ship plain bwrap which does).
      2. NONE (no isolation) as the explicit fallback.

    Callers should treat ``NONE`` as "ask the operator before
    accepting work from strangers."
    """
    if shutil.which("bwrap") is None:
        return SandboxBackend.NONE
    # Quick smoke test — try a no-op sandbox spawn. If userns is
    # disabled the bwrap binary will fail at startup with a clear
    # exit code, and we fall back to NONE.
    #
    # We construct the same mount set the real runner uses (system
    # mounts including /lib64-as-symlink) so the smoke test matches
    # production semantics, not a degenerate subset.
    smoke_argv: list[str] = [
        "bwrap",
        "--unshare-user", "--unshare-pid", "--unshare-ipc",
    ]
    for m in _system_mounts():
        if m.kind == "symlink":
            smoke_argv += ["--symlink", m.src, m.dest]
        else:
            smoke_argv += ["--ro-bind", m.src, m.dest]
    smoke_argv += [
        "--proc", "/proc",
        "--dev", "/dev",
        "--die-with-parent",
        "/usr/bin/true",
    ]
    try:
        rc = subprocess.run(
            smoke_argv,
            capture_output=True,
            timeout=5.0,
        )
        if rc.returncode == 0:
            return SandboxBackend.BUBBLEWRAP
        LOG.warning(
            "[sandbox] bwrap smoke test failed (rc=%d): %s",
            rc.returncode, rc.stderr.decode("utf-8", "replace")[:200],
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        LOG.warning("[sandbox] bwrap smoke test threw: %s", e)
    return SandboxBackend.NONE


# ---------------------------------------------------------------------------
# argv construction
# ---------------------------------------------------------------------------

def _build_bwrap_argv(
    config: SandboxConfig,
    python_bin: str,
) -> list[str]:
    """
    Translate a SandboxConfig into bwrap's CLI flags.

    Bwrap's flag ordering matters: namespaces declared first, then
    binds, then internal mounts, then the command. We follow that
    order so a future bwrap version that becomes stricter doesn't
    break us silently.
    """
    argv: list[str] = ["bwrap"]

    # --- namespace setup -------------------------------------------------
    # --unshare-all gives us new user/mount/uts/ipc/pid/cgroup namespaces.
    # We then selectively re-share what's needed.
    argv += ["--unshare-all"]
    if config.requires_network:
        argv += ["--share-net"]

    # Drop into uid/gid 65534 (nobody/nogroup) so any rare host-shared
    # state we left visible (e.g., world-readable /etc paths) gets
    # accessed as a fresh unprivileged identity, not as the parent's uid.
    argv += ["--uid", "65534", "--gid", "65534"]

    # --- filesystem allowlist -------------------------------------------
    # Bwrap layers mounts in argv order — later flags shadow earlier
    # ones at the same path. Order matters here:
    #
    #   1. System mounts (the merged-/usr trees) and /proc, /dev first
    #      so the dynamic linker can resolve the python interpreter.
    #   2. /tmp tmpfs BEFORE user ro_paths, so a user ro_path that
    #      happens to live under /tmp (e.g., a pytest tmp dir) lands
    #      ON TOP of the tmpfs and stays visible. If we did this after
    #      the ro_paths, the tmpfs would shadow them all.
    #   3. User ro_paths and rw_paths.
    #   4. Workspace bind (or tmpfs) — its host path may also live
    #      under /tmp, so it has to come after the /tmp tmpfs for
    #      the same reason.
    #
    # ``_system_mounts`` distinguishes between symlinks and directory
    # binds so merged-/usr distros (/lib64 → symlink) get the right
    # treatment. See _HostMount docstring.
    for m in _system_mounts():
        if m.kind == "symlink":
            argv += ["--symlink", m.src, m.dest]
        else:
            argv += ["--ro-bind", m.src, m.dest]

    # /proc and /dev — fresh views, not the host's.
    argv += ["--proc", "/proc", "--dev", "/dev"]

    # tmpfs for /tmp — always provided so libraries that drop ephemera
    # (tokenizer caches, sentence-transformers, importlib bytecode
    # caches) don't fail. Done BEFORE user ro_paths so a tmp-rooted
    # ro_path lands on top.
    argv += ["--tmpfs", "/tmp"]

    for p in config.ro_paths:
        # User-supplied ro_paths: also distinguish symlinks. We don't
        # rebuild the full _HostMount machinery here — just check islink.
        if os.path.islink(p):
            argv += ["--symlink", os.readlink(p), p]
        else:
            argv += ["--ro-bind", p, p]
    for p in config.rw_paths:
        argv += ["--bind", p, p]

    # Workspace — read-write bind. If None, give a fresh tmpfs.
    if config.workspace is not None:
        argv += ["--bind", config.workspace, "/workspace"]
        argv += ["--chdir", "/workspace"]
    else:
        argv += ["--tmpfs", "/workspace", "--chdir", "/workspace"]

    # --- environment -----------------------------------------------------
    # bwrap clears env unless told otherwise. We're explicit: each
    # passthrough name reads its value from os.environ at this layer.
    argv += ["--clearenv"]
    # Always set HOME and PATH so Python can boot. HOME points at
    # /tmp inside the sandbox so any module that does
    # `os.path.expanduser("~/.cache/foo")` writes to the tmpfs, not
    # to the host home (which isn't even visible).
    argv += ["--setenv", "HOME", "/tmp"]
    argv += ["--setenv", "PATH", "/usr/bin:/bin"]
    argv += ["--setenv", "PYTHONUNBUFFERED", "1"]
    # PYTHONPATH wasn't set explicitly — sys.prefix's site-packages is
    # already on the import path because we bind-mount sys.prefix.
    for name in config.env_passthrough:
        if name in ("HOME", "PATH"):  # already set above
            continue
        val = os.environ.get(name)
        if val is None:
            continue  # absent in parent → absent in child
        argv += ["--setenv", name, val]
    for name, val in config.env_set.items():
        argv += ["--setenv", name, val]

    # --- safety ----------------------------------------------------------
    argv += [
        "--die-with-parent",
        "--new-session",  # so SIGTERM to the bwrap pid kills the tree
    ]

    # --- command ---------------------------------------------------------
    # Inside the sandbox, run the entrypoint module from the bound gyza
    # source. ``-u`` for unbuffered IO (matches the framing protocol).
    argv += [python_bin, "-u", "-m", _ENTRYPOINT_MODULE]
    return argv


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------

def run_sandboxed(
    *,
    factory_qualname: str,
    init_kwargs: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
    config: SandboxConfig,
    python_bin: str | None = None,
    gyza_source_root: str | None = None,
) -> SandboxResult:
    """
    Execute one sandboxed call. Returns a SandboxResult on success.
    On failure raises one of:

      * SandboxUnavailableError — backend not usable on this host
      * SandboxTimeoutError     — wall-clock timeout exceeded
      * SandboxExecutionError   — sandboxee raised; inner exc preserved

    ``factory_qualname`` is ``"package.module:factory_func"``.
    ``init_kwargs`` is forwarded to that factory inside the sandbox.
    The returned executor is then called with ``(prompt, context)``.

    ``gyza_source_root`` defaults to the parent of ``gyza.__path__[0]``.
    Passed in for tests that point at a checkout other than the running
    one.
    """
    import time

    if config.backend == SandboxBackend.NONE:
        return _run_in_process(
            factory_qualname=factory_qualname,
            init_kwargs=init_kwargs,
            prompt=prompt,
            context=context,
        )
    if config.backend != SandboxBackend.BUBBLEWRAP:
        raise SandboxUnavailableError(f"unknown backend {config.backend}")

    if shutil.which("bwrap") is None:
        raise SandboxUnavailableError(
            "bubblewrap not found on PATH; install `bubblewrap` or "
            "fall back to SandboxBackend.NONE",
        )

    # Resolve the python binary AND make sure it's bind-mounted. Default
    # to the running interpreter — it's already on the system_paths
    # allowlist via sys.prefix/base_prefix.
    if python_bin is None:
        import sys
        python_bin = sys.executable

    # The gyza package source must be visible inside the sandbox. We
    # locate it via the import system rather than relative paths so
    # this works whether gyza is installed editable, vendored, or
    # placed via PYTHONPATH.
    if gyza_source_root is None:
        import gyza
        gyza_source_root = os.path.dirname(os.path.dirname(gyza.__file__))

    # Augment ro_paths with gyza root and the python binary's prefix
    # in case the caller forgot. Dedup happens inside default_system_paths.
    augmented_ro = list(config.ro_paths)
    if gyza_source_root not in augmented_ro:
        augmented_ro.append(gyza_source_root)

    # Build a temporary copy of config with augmented paths — we don't
    # mutate the caller's config. PYTHONPATH must include the gyza
    # source root so the sandboxee can import the entrypoint module;
    # we layer this on top of any caller-supplied env_set without
    # clobbering the caller's other vars.
    augmented_env = dict(config.env_set)
    existing_pp = augmented_env.get("PYTHONPATH", "")
    augmented_env["PYTHONPATH"] = (
        f"{gyza_source_root}:{existing_pp}" if existing_pp else gyza_source_root
    )
    effective = SandboxConfig(
        ro_paths=augmented_ro,
        rw_paths=list(config.rw_paths),
        workspace=config.workspace,
        requires_network=config.requires_network,
        env_passthrough=list(config.env_passthrough),
        env_set=augmented_env,
        max_memory_mb=config.max_memory_mb,
        max_cpu_seconds=config.max_cpu_seconds,
        timeout_s=config.timeout_s,
        backend=config.backend,
    )

    argv = _build_bwrap_argv(effective, python_bin)

    request = {
        "factory": factory_qualname,
        "init_kwargs": init_kwargs,
        "prompt": prompt,
        "context": context,
        "max_memory_mb": effective.max_memory_mb,
        "max_cpu_seconds": effective.max_cpu_seconds,
    }
    request_bytes = json.dumps(request).encode("utf-8")
    framed = struct.pack(_HEADER_FMT, len(request_bytes)) + request_bytes

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            input=framed,
            capture_output=True,
            timeout=effective.timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise SandboxTimeoutError(
            f"sandbox exceeded {effective.timeout_s}s wall clock",
        ) from e
    duration = time.monotonic() - t0

    stderr_text = result.stderr.decode("utf-8", "replace")
    if result.returncode != 0 and not result.stdout:
        # Hard failure with no payload — surface bwrap's own stderr.
        raise SandboxExecutionError(
            f"sandbox exited rc={result.returncode}; stderr={stderr_text[:500]}",
        )

    response = _parse_framed_response(result.stdout)
    if not response.get("ok"):
        raise SandboxExecutionError(
            response.get("error", "unknown sandbox error"),
            exc_type=response.get("exc_type", ""),
            inner_traceback=response.get("traceback", ""),
        )
    payload = response["result"]
    if not isinstance(payload, dict):
        raise SandboxExecutionError(
            f"sandbox returned non-dict payload: {type(payload).__name__}",
        )
    return SandboxResult(payload=payload, stderr=stderr_text, duration_s=duration)


def _parse_framed_response(stdout: bytes) -> dict[str, Any]:
    """
    Read the LAST framed response from stdout. The sandboxee may have
    `print()`d junk before the framed reply (model-load progress, etc.),
    so we scan from the end.

    Strategy: the sandboxee writes EXACTLY one frame at the very end.
    We slice the trailing 8-byte length prefix off the tail and read
    that many bytes preceding it.
    """
    if len(stdout) < _HEADER_SIZE:
        raise SandboxExecutionError(
            f"sandbox stdout too short for a frame: {len(stdout)} bytes",
        )
    # Walk from the end: find a length prefix that, interpreted as a
    # big-endian uint64, equals (len(stdout) - 8 - prefix_offset).
    # In practice only one configuration matches (the trailing frame).
    n = len(stdout)
    # Try the most common case first: stdout is JUST the frame.
    (size,) = struct.unpack(_HEADER_FMT, stdout[:_HEADER_SIZE])
    if size + _HEADER_SIZE == n:
        return json.loads(stdout[_HEADER_SIZE:].decode("utf-8"))
    # Fallback: scan back. Since the entrypoint only ever writes one
    # frame, look for the offset where size exactly matches the tail.
    for offset in range(n - _HEADER_SIZE - 1, -1, -1):
        try:
            (cand_size,) = struct.unpack(
                _HEADER_FMT, stdout[offset:offset + _HEADER_SIZE],
            )
        except struct.error:
            continue
        if cand_size + _HEADER_SIZE + offset == n:
            try:
                return json.loads(
                    stdout[offset + _HEADER_SIZE:].decode("utf-8"),
                )
            except json.JSONDecodeError:
                continue
    raise SandboxExecutionError(
        f"could not locate framed response in {n} bytes of stdout",
    )


def _run_in_process(
    *,
    factory_qualname: str,
    init_kwargs: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
) -> SandboxResult:
    """
    Backend=NONE — direct execution in the parent. Used for environments
    where bwrap is unavailable AND the operator has explicitly opted
    into running unsandboxed (e.g., trusted-cluster integration tests).
    """
    LOG.warning(
        "[sandbox] backend=NONE — executor running WITHOUT isolation. "
        "Set backend=BUBBLEWRAP for production.",
    )
    import importlib
    import time
    if ":" not in factory_qualname:
        raise ValueError(f"factory qualname must be 'mod:func', got {factory_qualname!r}")
    mod_name, func_name = factory_qualname.split(":", 1)
    mod = importlib.import_module(mod_name)
    factory = getattr(mod, func_name)
    inner = factory(**init_kwargs)
    t0 = time.monotonic()
    payload = inner(prompt, context)
    if not isinstance(payload, dict):
        raise SandboxExecutionError(
            f"inner executor returned {type(payload).__name__}, want dict",
        )
    return SandboxResult(payload=payload, stderr="", duration_s=time.monotonic() - t0)


__all__ = [
    "SandboxExecutionError",
    "SandboxResult",
    "SandboxTimeoutError",
    "SandboxUnavailableError",
    "detect_backend",
    "run_sandboxed",
]
