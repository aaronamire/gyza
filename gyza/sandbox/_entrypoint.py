"""
In-sandbox bootstrap. Invoked as ``python -m gyza.sandbox._entrypoint``
inside the bubblewrap subprocess.

Protocol on stdin / stdout: 8-byte big-endian length prefix followed by
a UTF-8 JSON document.

  parent → child  : {"factory": "module:func",
                     "init_kwargs": {...},
                     "prompt": "...",
                     "context": {...}}

  child → parent  : {"ok": true,  "result": {...}}                  on success
                   {"ok": false, "error": "...", "exc_type": "..."} on failure

Why framed: the inner executor (or any C extension it loads) might
``print()`` to stdout — sentence-transformers does on first model load.
A pure stream-of-JSON channel would be corrupted by that. Length-prefix
gives the parent a clean way to read exactly the response and ignore
the rest of stdout.

Why not pickle: untrusted code path. Pickle in either direction would
let a malicious sandboxee execute arbitrary code in the parent on
deserialize. JSON is safe.
"""
from __future__ import annotations

import importlib
import json
import resource
import struct
import sys
import traceback
from typing import Any


_HEADER_FMT = "!Q"   # 8-byte big-endian uint64 length prefix
_HEADER_SIZE = 8


def _read_framed() -> bytes:
    """Read one length-prefixed frame from stdin."""
    header = b""
    while len(header) < _HEADER_SIZE:
        chunk = sys.stdin.buffer.read(_HEADER_SIZE - len(header))
        if not chunk:
            raise EOFError("stdin closed before frame header complete")
        header += chunk
    (size,) = struct.unpack(_HEADER_FMT, header)
    body = b""
    while len(body) < size:
        chunk = sys.stdin.buffer.read(size - len(body))
        if not chunk:
            raise EOFError("stdin closed mid-frame")
        body += chunk
    return body


def _write_framed(payload: bytes) -> None:
    sys.stdout.buffer.write(struct.pack(_HEADER_FMT, len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _apply_rlimits(
    max_memory_mb: int | None,
    max_cpu_seconds: int | None,
) -> None:
    """
    Apply soft = hard rlimits for memory and CPU. Setting both equal
    means the sandboxee can't use ``setrlimit`` to raise its own caps
    later (ulimit -u behavior).
    """
    if max_memory_mb is not None:
        bytes_cap = max_memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (bytes_cap, bytes_cap))
        except (ValueError, OSError):
            # Some kernels reject very low caps for the running process
            # (the heap already in use exceeds the proposed cap). Surface
            # to the parent rather than silently continuing without limits.
            raise
    if max_cpu_seconds is not None:
        try:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (max_cpu_seconds, max_cpu_seconds),
            )
        except (ValueError, OSError):
            raise


def _resolve_factory(qualname: str) -> Any:
    """
    Resolve ``"module.path:func_name"`` to a callable. We split on
    ``:`` rather than ``.`` so a submodule and a top-level function
    are unambiguous.
    """
    if ":" not in qualname:
        raise ValueError(
            f"factory qualname must be 'module:func', got {qualname!r}",
        )
    mod_name, func_name = qualname.split(":", 1)
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, func_name, None)
    if fn is None:
        raise ImportError(f"{mod_name} has no attribute {func_name!r}")
    return fn


def main() -> int:
    try:
        request = json.loads(_read_framed().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        # We may not even have a working frame writer at this point —
        # exit non-zero and dump diagnostic info on stderr.
        sys.stderr.write(f"sandbox entrypoint: failed reading request: {e}\n")
        return 2

    try:
        factory_q = request["factory"]
        init_kwargs = request.get("init_kwargs", {}) or {}
        prompt = request["prompt"]
        context = request.get("context", {}) or {}
        max_mem = request.get("max_memory_mb")
        max_cpu = request.get("max_cpu_seconds")

        _apply_rlimits(max_mem, max_cpu)

        factory = _resolve_factory(factory_q)
        executor = factory(**init_kwargs)
        result = executor(prompt, context)
        if not isinstance(result, dict):
            raise TypeError(
                f"inner executor returned {type(result).__name__}, want dict",
            )
        _write_framed(json.dumps({"ok": True, "result": result}).encode("utf-8"))
        return 0
    except Exception as e:  # noqa: BLE001
        # Wrap the exception so the parent can surface it without
        # eval'ing the type. ``exc_type`` is informational only.
        try:
            _write_framed(json.dumps({
                "ok": False,
                "error": str(e),
                "exc_type": type(e).__name__,
                "traceback": traceback.format_exc(limit=20),
            }).encode("utf-8"))
        except Exception:  # noqa: BLE001
            sys.stderr.write(f"sandbox entrypoint: {type(e).__name__}: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
