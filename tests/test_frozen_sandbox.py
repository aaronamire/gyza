"""
Guardrails for the frozen-binary self-re-exec sandbox launcher (Option 1).

A PyInstaller binary cannot run ``python -m gyza.sandbox._entrypoint``
inside bwrap: ``sys.executable`` is the binary (no ``-m``) and the gyza
source lives in the bundle, not a bindable tree. So ``run_sandboxed``
re-execs the binary with a sentinel argv and binds the binary read-only.
That touches the security core, so three invariants are pinned here:

  INV1  A direct ``__gyza_sandbox_entry__`` invocation, outside bwrap,
        can never produce a ``backend=bubblewrap`` record. The sentinel
        only routes to the entrypoint; the trusted PARENT stamps the
        record, never the sandboxee.
  INV2  The frozen path's bwrap argv + framed request carry the SAME
        bounds as the caller's cfg — the record the parent later stamps
        is faithful to what actually ran, not an assumed/hardcoded set.
  INV3  Every containment flag (--unshare-all, uid/gid 65534, tmpfs,
        --clearenv, --die-with-parent) survives the frozen branch.

The "an over-bound action inside the frozen enforced sandbox is still
refused" half of INV3 requires a real frozen binary + bwrap; that is the
build-time enforced smoke test, run against the onedir build.
"""
from __future__ import annotations

import io
import json
import struct

import pytest

import gyza.cli as cli
import gyza.sandbox.runner as runner
from gyza.sandbox.config import SandboxBackend, SandboxConfig

_SENTINEL = runner._SANDBOX_ENTRY_SENTINEL
_HEADER = "!Q"


def _frame(obj: dict) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    return struct.pack(_HEADER, len(body)) + body


def _unframe(buf: bytes) -> dict:
    (size,) = struct.unpack(_HEADER, buf[:8])
    return json.loads(buf[8 : 8 + size].decode("utf-8"))


# ---------------------------------------------------------------------------
# INV1 — the sentinel path never stamps an enforcement record
# ---------------------------------------------------------------------------

def test_direct_sentinel_invocation_never_yields_bubblewrap(monkeypatch):
    # Feed a framed request straight to `gyza <sentinel>` (no bwrap in the
    # loop) and read the framed reply. The sandboxee runs the factory and
    # returns its raw output with NO enforcement stamp — so a caller who
    # invokes the sentinel directly can never manufacture a bubblewrap
    # record, exactly like the Revision-1 fabrication fix one level up.
    req = _frame({
        "factory": "gyza.runner:make_mock_executor",
        "init_kwargs": {"response": "hi-from-entry"},
        "prompt": "p",
        "context": {},
    })
    monkeypatch.setattr(cli.sys, "stdin", io.TextIOWrapper(io.BytesIO(req)))
    out = io.BytesIO()
    monkeypatch.setattr(cli.sys, "stdout", io.TextIOWrapper(out))

    rc = cli.main([_SENTINEL])
    cli.sys.stdout.flush()
    assert rc == 0

    resp = _unframe(out.getvalue())
    assert resp["ok"] is True
    result = resp["result"]
    # The star of INV1: no enforcement record at all, and certainly not one
    # claiming bubblewrap. The stamp is the trusted parent's job.
    assert result.get("__enforcement__", {}).get("backend") != "bubblewrap"
    assert "__enforcement__" not in result


def test_sentinel_dispatch_precedes_argparse():
    # The sentinel must be handled before argparse — it is not a real
    # subcommand and must not be parsed as one. If dispatch works, a
    # sentinel with an empty stdin frame returns the entrypoint's read
    # failure code (2), NOT an argparse SystemExit.
    import gyza.sandbox._entrypoint as ep

    called = {}

    def _fake_entry() -> int:
        called["yes"] = True
        return 7

    # Patch where main() looks it up (imported inside the dispatch branch).
    import sys as _sys
    monkey = pytest.MonkeyPatch()
    monkey.setattr(ep, "main", _fake_entry)
    monkey.setitem(_sys.modules, "gyza.sandbox._entrypoint", ep)
    try:
        rc = cli.main([_SENTINEL, "ignored", "args"])
    finally:
        monkey.undo()
    assert called.get("yes") is True
    assert rc == 7


# ---------------------------------------------------------------------------
# Shared: capture the bwrap argv + framed request without launching bwrap
# ---------------------------------------------------------------------------

class _Captured(Exception):
    def __init__(self, argv: list[str], stdin: bytes) -> None:
        self.argv = argv
        self.stdin = stdin


def _run_frozen_captured(monkeypatch, cfg: SandboxConfig):
    # Pretend we are a frozen onedir binary and capture the bwrap argv.
    monkeypatch.setattr(runner.shutil, "which", lambda _n: "/usr/bin/bwrap")
    monkeypatch.setattr(runner.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runner.sys, "executable", "/opt/gyza/gyza")
    monkeypatch.setattr(runner.sys, "_MEIPASS", "/opt/gyza/_internal",
                        raising=False)

    def _capture(argv, **kw):
        raise _Captured(argv, kw.get("input", b""))

    monkeypatch.setattr(runner.subprocess, "run", _capture)
    with pytest.raises(_Captured) as ei:
        runner.run_sandboxed(
            factory_qualname="gyza.runner:make_mock_executor",
            init_kwargs={"response": "x"},
            prompt="p", context={}, config=cfg,
        )
    return ei.value.argv, ei.value.stdin


# ---------------------------------------------------------------------------
# INV2 — frozen argv is self-re-exec + binary-bound, bounds faithful to cfg
# ---------------------------------------------------------------------------

def test_frozen_path_self_reexecs_and_binds_binary_not_source(monkeypatch):
    cfg = SandboxConfig(backend=SandboxBackend.BUBBLEWRAP, max_memory_mb=512)
    argv, stdin = _run_frozen_captured(monkeypatch, cfg)

    # Self-re-exec: the last two argv tokens are the binary + the sentinel.
    assert argv[-2:] == ["/opt/gyza/gyza", _SENTINEL]
    # No `-m` / _entrypoint module invocation (that shape can't run frozen).
    assert "-m" not in argv
    assert runner._ENTRYPOINT_MODULE not in argv

    # The binary and its bundle are bound read-only so the re-exec resolves.
    def _ro_dests(a):
        return {a[i + 2] for i in range(len(a) - 2) if a[i] == "--ro-bind"}
    ro = _ro_dests(argv)
    assert "/opt/gyza/gyza" in ro
    assert "/opt/gyza/_internal" in ro
    # NO gyza source tree bind and NO PYTHONPATH leak — source is in-bundle.
    assert "--setenv" not in argv or "PYTHONPATH" not in argv


def test_frozen_request_bounds_match_cfg_not_assumed(monkeypatch):
    # INV2 core: the framed request the sandboxee receives (which drives
    # the rlimits it applies) carries the SAME bounds as cfg, so the record
    # the parent later stamps from that same cfg is faithful — the frozen
    # branch changed only which binary runs, never the bounds.
    cfg = SandboxConfig(backend=SandboxBackend.BUBBLEWRAP,
                        max_memory_mb=512, max_cpu_seconds=17)
    _argv, stdin = _run_frozen_captured(monkeypatch, cfg)
    req = _unframe(stdin)
    assert req["max_memory_mb"] == 512
    assert req["max_cpu_seconds"] == 17


# ---------------------------------------------------------------------------
# INV3 — every containment flag survives the frozen branch
# ---------------------------------------------------------------------------

def test_frozen_argv_preserves_all_containment_flags(monkeypatch):
    cfg = SandboxConfig(backend=SandboxBackend.BUBBLEWRAP, max_memory_mb=512)
    argv, _stdin = _run_frozen_captured(monkeypatch, cfg)

    assert "--unshare-all" in argv
    assert "--clearenv" in argv
    assert "--die-with-parent" in argv
    assert "--new-session" in argv
    # uid/gid dropped to nobody.
    assert argv[argv.index("--uid") + 1] == "65534"
    assert argv[argv.index("--gid") + 1] == "65534"
    # /tmp is a fresh tmpfs (host /tmp never exposed).
    assert any(argv[i] == "--tmpfs" and argv[i + 1] == "/tmp"
               for i in range(len(argv) - 1))
    # Network stays unshared unless the cfg asked for it.
    assert "--share-net" not in argv


def test_source_path_unchanged_by_the_frozen_branch(monkeypatch):
    # Regression guard: when NOT frozen, the argv is still the source shape
    # (python -m gyza.sandbox._entrypoint) — Option 1 must not perturb the
    # source path that every existing enforced run depends on.
    monkeypatch.setattr(runner.shutil, "which", lambda _n: "/usr/bin/bwrap")
    monkeypatch.setattr(runner.sys, "frozen", False, raising=False)

    def _capture(argv, **kw):
        raise _Captured(argv, kw.get("input", b""))

    monkeypatch.setattr(runner.subprocess, "run", _capture)
    cfg = SandboxConfig(backend=SandboxBackend.BUBBLEWRAP, max_memory_mb=512)
    with pytest.raises(_Captured) as ei:
        runner.run_sandboxed(
            factory_qualname="gyza.runner:make_mock_executor",
            init_kwargs={"response": "x"}, prompt="p", context={}, config=cfg,
        )
    argv = ei.value.argv
    assert "-m" in argv
    assert runner._ENTRYPOINT_MODULE in argv
    assert _SENTINEL not in argv
