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
import threading
import time
from typing import Any, Callable

from gyza.release import CURRENT_RELEASE as _CURRENT_RELEASE
from gyza.sandbox.config import SandboxConfig
from gyza.sandbox.runner import (
    SandboxExecutionError,
    SandboxTimeoutError,
    run_sandboxed,
)


LOG = logging.getLogger("gyza.sandbox.executor")


# --------------------------------------------------------------------------- #
#  SANDBOX ADMISSION CONTROL                                                    #
# --------------------------------------------------------------------------- #
#
# A sandboxed action is a bubblewrap PROCESS: namespace setup, seccomp filter,
# then ~305 ms of real work (measured, n=12). One core sustains ~3.3 of them.
#
# Nothing limited how many could be in flight. That was survivable while the
# only deployments were a handful of agents in separate OS processes, and it
# stops being survivable the moment agents are THREADS -- 500 threads reaching
# this function together is 500 simultaneous namespace setups on a machine that
# can usefully run about eight.
#
# BLOCKING IS THE CORRECT BEHAVIOUR, and the alternative was considered and
# rejected. Raising on a full queue would convert a slow system into a failing
# one, and the caller's only sensible response would be to retry -- which is
# the same wait, with the claim released and re-taken in between. Blocking here
# is backpressure applied where the scarce resource actually is.
#
# It cannot deadlock: every admitted run carries its own wall-clock timeout
# (`SandboxTimeoutError`), so a slot is always released, and nothing inside a
# sandbox re-enters this function -- decomposition posts work items, it does
# not recurse into the sandbox.

def _default_concurrency() -> int:
    """Twice the core count, floor 2.

    Not the core count itself: a sandboxed action is only partly CPU-bound --
    it spends time in namespace setup and process teardown where the core is
    idle -- so admitting exactly `nproc` leaves cores stalled between runs.
    Not much more than twice either: past that the runs contend for the same
    cores and each one slows down, which buys queueing delay and no throughput.
    Override with `GYZA_SANDBOX_CONCURRENCY` to measure that curve rather than
    trust this reasoning.
    """
    env = os.environ.get("GYZA_SANDBOX_CONCURRENCY", "").strip()
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            LOG.warning("[sandbox] ignoring non-numeric "
                        "GYZA_SANDBOX_CONCURRENCY=%r", env)
    return max(2, (os.cpu_count() or 2) * 2)


class _Admission:
    """Process-wide gate on concurrent sandbox runs, with its own accounting.

    The accounting is not decoration. Without it, "the sandbox is slow" and
    "we are queued behind other agents" are indistinguishable in a throughput
    number, and those have opposite remedies -- more cores versus fewer agents.
    """

    def __init__(self) -> None:
        self._limit = _default_concurrency()
        self._sem = threading.BoundedSemaphore(self._limit)
        self._lock = threading.Lock()
        self.admitted = 0
        self.wait_s = 0.0
        self.peak_waiting = 0
        self._waiting = 0

    @property
    def limit(self) -> int:
        return self._limit

    def stats(self) -> dict:
        with self._lock:
            return {"limit": self._limit, "admitted": self.admitted,
                    "total_wait_s": round(self.wait_s, 3),
                    "peak_waiting": self.peak_waiting}

    def __enter__(self):
        with self._lock:
            self._waiting += 1
            self.peak_waiting = max(self.peak_waiting, self._waiting)
        t0 = time.monotonic()
        self._sem.acquire()
        waited = time.monotonic() - t0
        with self._lock:
            self._waiting -= 1
            self.admitted += 1
            self.wait_s += waited
        return self

    def __exit__(self, *exc):
        self._sem.release()
        return False


#: Process-wide. Threads in one process share it, which is the case it exists
#: for; separate OS processes each get their own, so a multi-process deployment
#: must size `GYZA_SANDBOX_CONCURRENCY` per process rather than globally.
ADMISSION = _Admission()


def sandbox_admission_stats() -> dict:
    """Queueing accounting, for a caller measuring where time actually went."""
    return ADMISSION.stats()


def _json_safe_artifact(a):
    """One artifact, projected onto what can cross the sandbox boundary."""
    if isinstance(a, (dict, str, int, float, bool)) or a is None:
        return a
    import base64 as _b64

    raw = getattr(a, "data", b"") or b""
    out = {
        "hash": getattr(a, "hash", None),
        "signer_pubkey": getattr(a, "signer_pubkey", None),
        "size": len(raw),
        "data_b64": _b64.b64encode(raw).decode("ascii"),
    }
    try:
        out["text"] = raw.decode("utf-8")
    except UnicodeDecodeError:
        # NOT an error and NOT silently empty: binary artifacts are legitimate
        # and `data_b64` above carries them losslessly. Omitting `text` says
        # "these bytes are not text", which is different from "no bytes".
        pass
    return out


def _json_safe_context(context: dict) -> dict:
    """
    Project the runner's executor context onto what can cross the
    sandbox process boundary (it travels as JSON).

    The runner passes ``{"item": WorkItem, "inputs": [...]}`` — the rich
    ``WorkItem`` object (with a numpy embedding) is fine for in-process
    executors but not serializable. Sandboxed executors get the fields
    an executor can legitimately act on; ``inputs`` (parsed artifact
    dicts) pass through unchanged. Anything else the caller put in the
    context is forwarded as-is — if it isn't JSON-safe, ``run_sandboxed``
    raises, which is the honest outcome for an unserializable contract.
    """
    safe = dict(context)

    # `inputs` CARRIES Artifact OBJECTS, NOT DICTS, AND NOTHING CHECKED IT.
    # This docstring asserted that "inputs (parsed artifact dicts) pass through
    # unchanged" from the day it was written; the runner has always passed
    # `Artifact` dataclasses. The assumption held only because every sandboxed
    # workflow so far had EMPTY `input_hashes`, so the list was empty and JSON
    # never saw one. The first action that consumed an artifact inside a
    # sandbox -- a combiner gathering its siblings' outputs -- failed with
    # "Object of type Artifact is not JSON serializable".
    #
    # An unenforced invariant is an assumption. Artifacts are now projected the
    # same way `item` is: to the fields an executor can legitimately act on.
    # `data` is bytes, so it crosses as base64 under an explicit name, with a
    # decoded `text` alongside when the bytes are UTF-8 -- the common case, and
    # the one an executor actually wants.
    ins = safe.get("inputs")
    if isinstance(ins, list):
        safe["inputs"] = [_json_safe_artifact(a) for a in ins]

    item = safe.get("item")
    if item is not None and not isinstance(
        item, (dict, str, int, float, bool, list)
    ):
        safe["item"] = {
            "id": getattr(item, "id", None),
            "lineage_root": getattr(item, "lineage_root", None),
            "description": getattr(item, "description", None),
            "required_tier": getattr(item, "required_tier", None),
            "input_hashes": list(getattr(item, "input_hashes", None) or []),
            "output_spec": getattr(item, "output_spec", None),
        }
    return safe


def make_sandboxed_executor(
    factory_qualname: str,
    *,
    init_kwargs: dict[str, Any] | None = None,
    config: SandboxConfig | None = None,
    egress_recorder: Any | None = None,
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
        with ADMISSION:
            return _run(prompt, context)

    def _run(prompt: str, context: dict) -> dict:
        result = run_sandboxed(
            factory_qualname=factory_qualname,
            init_kwargs=init,
            prompt=prompt,
            context=_json_safe_context(context),
            config=cfg,
            # H3'S ONLY OBSERVABLE FACT ABOUT SANDBOXED EGRESS. `run_sandboxed`
            # accepted this parameter and NOTHING EVER PASSED IT, so the
            # UNBOUNDED_GRANT branch at sandbox/runner.py:435 never fired. The
            # standing argument that external network "is covered by the grant"
            # was therefore hollow: the grant was not recorded either, and a
            # network-granted agent had unbounded unobservable egress that
            # nothing anywhere counted.
            egress_recorder=egress_recorder,
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
                # Resource bounds — included so the predicate can
                # also check enforcement.max_memory_mb ≤
                # manifest.spawn.resource_budget.memory_limit_mb.
                # int|None preserved as JSON null when unset, so the
                # predicate distinguishes "no memory cap requested"
                # from "0 MB" (would be a misconfiguration).
                "max_memory_mb": cfg.max_memory_mb,
                "max_cpu_seconds": cfg.max_cpu_seconds,
                "timeout_s": cfg.timeout_s,
                # Runner release identity (G1a / ADR-0017). This is
                # the binary that performed the stamp, so the
                # submitter can check it against a separately-
                # distributed trusted-release set. It does NOT enter
                # enforcement_satisfies_manifest — runner identity is
                # a distinct verification axis from "enforcement ⊆
                # manifest", and conflating them would let an
                # untrusted build's bounds pass as long as the
                # predicate held. Self-reported: a malicious binary
                # can lie here; trusted-set membership only bounds
                # *which lie* is accepted. Honest closure is TEE
                # (vNext L8); see ADR-0017.
                **_CURRENT_RELEASE.as_dict(),
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
