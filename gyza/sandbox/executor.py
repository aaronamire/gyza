"""
``make_sandboxed_executor`` — high-level adapter that turns a
sandboxed call into the executor protocol the runner already expects.

The runner's contract (gyza/runner.py:82) is a callable
``Callable[[str, dict], dict]``. Inside that callable we shell out
to ``run_sandboxed`` with the inner executor's factory qualname and
init kwargs. From the runner's perspective nothing changes — same
type signature, same expected output shape.

Convenience presets are provided for the two existing factories:

    sandboxed_mock_executor()
    sandboxed_anthropic_executor(api_key=...)

Custom executors can use ``make_sandboxed_executor`` directly with
their own ``factory_qualname``.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

from gyza.sandbox.config import SandboxConfig
from gyza.sandbox.runner import (
    SandboxExecutionError,
    SandboxTimeoutError,
    run_sandboxed,
)


LOG = logging.getLogger("gyza.sandbox.executor")


def make_sandboxed_executor(
    factory_qualname: str,
    *,
    init_kwargs: dict[str, Any] | None = None,
    config: SandboxConfig | None = None,
) -> Callable[[str, dict], dict]:
    """
    Wrap an inner executor factory into a sandboxed callable that
    matches the runner's executor protocol.

    Parameters

      factory_qualname : "module.path:func" — must be importable
        inside the sandbox. Functions defined in the test module
        won't work; put your factory in a real module.

      init_kwargs : forwarded to the factory inside the sandbox to
        construct the inner executor on every call. (Yes, every
        call — see "performance" note below.)

      config : SandboxConfig. Defaults to no-network, no-extra-paths,
        2GB RLIMIT_AS, 300s CPU. Callers SHOULD override depending on
        what their executor needs.

    Performance

      Each invocation spawns a fresh Python interpreter inside bwrap
      and re-imports the factory's module. For Anthropic-shaped
      executors (HTTP-RTT-bound) the ~150-300ms overhead is in the
      noise. For high-throughput local executors (llama.cpp at
      100+ tok/s) you'd want a long-lived sandbox daemon — out of
      scope for Phase 3.

    Failure mapping

      The inner executor's exceptions surface as ``SandboxExecutionError``
      with the original message preserved on ``.args[0]``. Wall-clock
      timeouts surface as ``SandboxTimeoutError``. Both are RuntimeError
      subclasses, so callers that did
      ``try: ...; except RuntimeError as e: ...`` keep working.
    """
    cfg = config or SandboxConfig()
    init = dict(init_kwargs or {})

    def _wrapped(prompt: str, context: dict) -> dict:
        result = run_sandboxed(
            factory_qualname=factory_qualname,
            init_kwargs=init,
            prompt=prompt,
            context=context,
            config=cfg,
        )
        payload = result.payload
        # Host-side enforcement stamp. This runs in the trusted parent
        # AFTER run_sandboxed returns — the sandboxed code cannot forge
        # it (we overwrite any key it set). Soundness: run_sandboxed
        # RAISES rather than silently degrading a BUBBLEWRAP request to
        # NONE, so a returned payload under a bubblewrap cfg means
        # bwrap actually enforced these exact bounds. The runner gates
        # signing on this record being consistent with the agent's
        # capability manifest (see runner._execute), and folds it into
        # the signed artifact so the envelope's output_hash commits to
        # the enforcement that happened — not merely what was claimed.
        if isinstance(payload, dict):
            payload["__enforcement__"] = {
                "backend": cfg.backend.value,
                "ro_paths": sorted(cfg.ro_paths),
                "rw_paths": sorted(cfg.rw_paths),
                "requires_network": bool(cfg.requires_network),
            }
        return payload

    # Tag the wrapped callable so debugging knows what's underneath.
    _wrapped.__sandbox_factory__ = factory_qualname  # type: ignore[attr-defined]
    _wrapped.__sandbox_backend__ = cfg.backend.value  # type: ignore[attr-defined]
    return _wrapped


# ---------------------------------------------------------------------------
# Convenience presets
# ---------------------------------------------------------------------------

def sandboxed_mock_executor(
    response: str = "mock output",
    *,
    config: SandboxConfig | None = None,
) -> Callable[[str, dict], dict]:
    """Sandboxed wrapper around ``runner.make_mock_executor``."""
    cfg = config or SandboxConfig(requires_network=False)
    return make_sandboxed_executor(
        "gyza.runner:make_mock_executor",
        init_kwargs={"response": response},
        config=cfg,
    )


def sandboxed_anthropic_executor(
    api_key: str | None = None,
    *,
    model: str = "claude-sonnet-4-5",
    config: SandboxConfig | None = None,
) -> Callable[[str, dict], dict]:
    """
    Sandboxed wrapper around ``runner.make_anthropic_executor``.

    The default config grants network access (required for
    api.anthropic.com) and forwards ``ANTHROPIC_API_KEY`` from the
    parent's environment if no ``api_key`` is supplied. Override
    ``config`` for custom resource limits or extra mounts (e.g., a
    cached models directory).
    """
    if api_key is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "sandboxed_anthropic_executor needs ANTHROPIC_API_KEY in env "
            "or api_key= argument",
        )
    if config is None:
        config = SandboxConfig(
            requires_network=True,
            env_set={"ANTHROPIC_API_KEY": api_key},
            # SDK loads ssl certs from /etc/ssl; default ro_paths covers it.
        )
    else:
        # Don't mutate caller's config — produce a copy with the key set.
        config = SandboxConfig(
            ro_paths=list(config.ro_paths),
            rw_paths=list(config.rw_paths),
            workspace=config.workspace,
            requires_network=True,
            env_passthrough=list(config.env_passthrough),
            env_set={**config.env_set, "ANTHROPIC_API_KEY": api_key},
            max_memory_mb=config.max_memory_mb,
            max_cpu_seconds=config.max_cpu_seconds,
            timeout_s=config.timeout_s,
            backend=config.backend,
        )
    return make_sandboxed_executor(
        "gyza.runner:make_anthropic_executor",
        init_kwargs={"api_key": api_key, "model": model},
        config=config,
    )


__all__ = [
    "make_sandboxed_executor",
    "sandboxed_anthropic_executor",
    "sandboxed_mock_executor",
]


# Pyright bookkeeping — these are caught and re-raised by run_sandboxed
# above; declared here so users importing executor.py don't also have
# to import them from runner.py.
_ = SandboxExecutionError
_ = SandboxTimeoutError
