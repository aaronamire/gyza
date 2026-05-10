"""
Test-only probe executors that exercise specific sandbox properties.

These live in the package (not under ``tests/``) because the sandbox
imports inner executors by qualified name from a long-lived module
path. Closures and test-local helpers can't cross the
subprocess/JSON boundary; a real module can.

The probes are intentionally minimal — each one tests ONE property
of the sandbox boundary. None of them are useful in production.
"""
from __future__ import annotations

import os
import socket
import time
from typing import Callable


def make_path_probe(path: str) -> Callable[[str, dict], dict]:
    """
    Read ``path`` and return the first 500 bytes (or the OSError).
    Used to assert which paths are visible inside the sandbox.
    """
    def _exec(_prompt: str, _ctx: dict) -> dict:
        try:
            with open(path, "rb") as f:
                data = f.read(500)
            return {"text": data.decode("utf-8", "replace"), "ok": True}
        except OSError as e:
            return {"text": "", "ok": False, "errno": e.errno, "msg": str(e)}
    return _exec


def make_listdir_probe(path: str) -> Callable[[str, dict], dict]:
    """List ``path`` and return entries (or the OSError)."""
    def _exec(_prompt: str, _ctx: dict) -> dict:
        try:
            entries = sorted(os.listdir(path))
            return {"text": "\n".join(entries[:50]), "ok": True}
        except OSError as e:
            return {"text": "", "ok": False, "errno": e.errno, "msg": str(e)}
    return _exec


def make_write_probe(path: str, content: str = "x") -> Callable[[str, dict], dict]:
    """Try to write to ``path``; return ok on success."""
    def _exec(_prompt: str, _ctx: dict) -> dict:
        try:
            with open(path, "w") as f:
                f.write(content)
            return {"text": "wrote", "ok": True}
        except OSError as e:
            return {"text": "", "ok": False, "errno": e.errno, "msg": str(e)}
    return _exec


def make_socket_probe(
    host: str = "1.1.1.1",
    port: int = 53,
    timeout_s: float = 2.0,
) -> Callable[[str, dict], dict]:
    """
    Try a TCP connect to ``host:port``. Used to assert the network
    namespace is or is not isolated. Default 1.1.1.1:53 is a public
    DNS resolver — unreachable from a netns-isolated sandbox; reachable
    from one with --share-net.
    """
    def _exec(_prompt: str, _ctx: dict) -> dict:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout_s)
        try:
            s.connect((host, port))
            return {"text": f"connected to {host}:{port}", "ok": True}
        except OSError as e:
            return {"text": "", "ok": False, "errno": e.errno, "msg": str(e)}
        finally:
            s.close()
    return _exec


def make_env_probe(name: str) -> Callable[[str, dict], dict]:
    """Return the value of env var ``name`` (or empty if absent)."""
    def _exec(_prompt: str, _ctx: dict) -> dict:
        return {"text": os.environ.get(name, ""), "ok": True}
    return _exec


def make_sleep_probe(seconds: float) -> Callable[[str, dict], dict]:
    """Sleep ``seconds`` then return. Used for timeout testing."""
    def _exec(_prompt: str, _ctx: dict) -> dict:
        time.sleep(seconds)
        return {"text": f"slept {seconds}", "ok": True}
    return _exec


def make_raising_probe(message: str = "boom") -> Callable[[str, dict], dict]:
    """Raise ValueError with the given message. Tests error surfacing."""
    def _exec(_prompt: str, _ctx: dict) -> dict:
        raise ValueError(message)
    return _exec


def make_oom_probe(target_mb: int = 4096) -> Callable[[str, dict], dict]:
    """
    Allocate ``target_mb`` of memory in 64MB chunks. With a sufficiently
    low RLIMIT_AS the allocation should fail (MemoryError).
    """
    def _exec(_prompt: str, _ctx: dict) -> dict:
        chunks: list[bytes] = []
        chunk_size = 64 * 1024 * 1024
        try:
            for _ in range(target_mb // 64):
                chunks.append(b"\x00" * chunk_size)
            return {"text": f"allocated {len(chunks) * 64} MB", "ok": True}
        except MemoryError as e:
            return {"text": "", "ok": False, "msg": str(e)}
    return _exec


def make_uid_probe() -> Callable[[str, dict], dict]:
    """Return the uid/gid the sandboxee is running as. Tests --uid mapping."""
    def _exec(_prompt: str, _ctx: dict) -> dict:
        return {"text": f"uid={os.getuid()} gid={os.getgid()}", "ok": True}
    return _exec
