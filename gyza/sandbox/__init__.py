"""
Phase 3 priority #22 — executor sandboxing.

Today's executors run with full process privileges. As Phase 3 starts
accepting work claims from strangers (and Phase 4+ adds tool-using
agents that genuinely run code), the executor surface becomes a
security boundary, not just a code-quality one.

This package wraps any executor (``Callable[[str, dict], dict]``) in a
bubblewrap subprocess with explicit FS / network / resource constraints.
The runner stays unchanged — it sees the same callable signature; the
work happens out-of-process inside the sandbox.

Threat model and design choices live in ``runner.py``'s module docstring.
"""
from __future__ import annotations

from gyza.sandbox.config import (
    SandboxConfig,
    SandboxBackend,
    default_system_paths,
    enforcement_satisfies_manifest,
    sandbox_config_from_manifest,
)
from gyza.sandbox.executor import make_sandboxed_executor
from gyza.sandbox.runner import (
    SandboxResult,
    SandboxUnavailableError,
    SandboxTimeoutError,
    SandboxExecutionError,
    detect_backend,
    run_sandboxed,
)


__all__ = [
    "SandboxBackend",
    "SandboxConfig",
    "SandboxExecutionError",
    "SandboxResult",
    "SandboxTimeoutError",
    "SandboxUnavailableError",
    "default_system_paths",
    "detect_backend",
    "enforcement_satisfies_manifest",
    "make_sandboxed_executor",
    "run_sandboxed",
    "sandbox_config_from_manifest",
]
