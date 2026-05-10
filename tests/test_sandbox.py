"""
Tests for the executor sandbox (Phase 3 priority #22).

Most tests require bubblewrap on the host. ``pytest.skip`` is used
when ``detect_backend()`` returns NONE; CI environments without
bwrap therefore skip the boundary tests but still run the
backend-agnostic surface (config dataclass, error mapping, NONE
backend).

The tests deliberately cover both POSITIVE outcomes (allowed paths
visible, network reachable when requested) and NEGATIVE outcomes
(disallowed paths invisible, network blocked by default). Negative
tests are the ones that actually prove the boundary; positive tests
just prevent the wrapper itself from being broken.
"""
from __future__ import annotations

import os

import pytest

from gyza.sandbox import (
    SandboxBackend,
    SandboxConfig,
    SandboxExecutionError,
    SandboxTimeoutError,
    detect_backend,
    make_sandboxed_executor,
    run_sandboxed,
)


_BACKEND = detect_backend()
_REQUIRES_BWRAP = pytest.mark.skipif(
    _BACKEND != SandboxBackend.BUBBLEWRAP,
    reason="bubblewrap not available on this host",
)


# ----------------------------------------------------------------------
# Backend detection
# ----------------------------------------------------------------------

def test_detect_backend_returns_an_enum():
    assert _BACKEND in (SandboxBackend.BUBBLEWRAP, SandboxBackend.NONE)


# ----------------------------------------------------------------------
# Roundtrip — basic protocol works
# ----------------------------------------------------------------------

@_REQUIRES_BWRAP
def test_roundtrip_mock_executor():
    r = run_sandboxed(
        factory_qualname="gyza.runner:make_mock_executor",
        init_kwargs={"response": "hi-from-sandbox"},
        prompt="prompt",
        context={},
        config=SandboxConfig(timeout_s=15.0),
    )
    assert r.payload["text"] == "hi-from-sandbox"
    assert r.payload["inference_backend"] == "mock"
    assert r.duration_s >= 0.0


@_REQUIRES_BWRAP
def test_make_sandboxed_executor_matches_runner_protocol():
    fn = make_sandboxed_executor(
        "gyza.runner:make_mock_executor",
        init_kwargs={"response": "abc"},
        config=SandboxConfig(timeout_s=15.0),
    )
    out = fn("prompt", {"context": "value"})
    assert isinstance(out, dict)
    assert out["text"] == "abc"


# ----------------------------------------------------------------------
# Filesystem isolation — POSITIVE
# ----------------------------------------------------------------------

@_REQUIRES_BWRAP
def test_allowlisted_path_is_readable(tmp_path):
    """A path explicitly added to ro_paths is readable from inside."""
    data_path = tmp_path / "data.txt"
    data_path.write_text("allowed-content")
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_path_probe",
        init_kwargs={"path": str(data_path)},
        config=SandboxConfig(
            ro_paths=[str(tmp_path)],
            timeout_s=15.0,
        ),
    )
    out = fn("", {})
    assert out["ok"] is True
    assert out["text"] == "allowed-content"


@_REQUIRES_BWRAP
def test_workspace_is_writable(tmp_path):
    """A path bound as workspace is writable from inside, and the
    write is visible on the host."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_write_probe",
        init_kwargs={"path": "/workspace/output.txt", "content": "from-sandbox"},
        config=SandboxConfig(
            workspace=str(workspace),
            timeout_s=15.0,
        ),
    )
    out = fn("", {})
    assert out["ok"] is True
    # The file appears on the host because /workspace is bind-mounted rw.
    assert (workspace / "output.txt").read_text() == "from-sandbox"


# ----------------------------------------------------------------------
# Filesystem isolation — NEGATIVE (the actual boundary)
# ----------------------------------------------------------------------

@_REQUIRES_BWRAP
def test_user_home_is_not_visible(tmp_path):
    """
    The sandboxee cannot read paths under the user's home that aren't
    explicitly mounted. This is the property that lets us safely
    accept stranger work.
    """
    # Use a path we know is on the host but not in default mounts.
    secret = tmp_path / "secret.key"
    secret.write_text("PRIVATE")
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_path_probe",
        init_kwargs={"path": str(secret)},
        # Notice: tmp_path NOT in ro_paths.
        config=SandboxConfig(timeout_s=15.0),
    )
    out = fn("", {})
    assert out["ok"] is False, (
        f"expected sandbox to deny access to {secret}, got {out!r}"
    )


@_REQUIRES_BWRAP
def test_workspace_is_not_writable_outside_bind(tmp_path):
    """
    Writes to /tmp survive only as tmpfs; writes to absolute host paths
    not in rw_paths fail.
    """
    target = tmp_path / "should_not_appear.txt"
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_write_probe",
        init_kwargs={"path": str(target), "content": "x"},
        config=SandboxConfig(timeout_s=15.0),
    )
    out = fn("", {})
    assert out["ok"] is False
    assert not target.exists()


# ----------------------------------------------------------------------
# Network isolation
# ----------------------------------------------------------------------

@_REQUIRES_BWRAP
def test_network_isolated_by_default():
    """
    Without ``requires_network=True``, TCP to a public address fails
    immediately — a fresh net namespace has only loopback.
    """
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_socket_probe",
        # 1.1.1.1:53 — public DNS, would succeed if net were shared.
        init_kwargs={"host": "1.1.1.1", "port": 53, "timeout_s": 1.5},
        config=SandboxConfig(timeout_s=15.0, requires_network=False),
    )
    out = fn("", {})
    assert out["ok"] is False, (
        "sandbox without --share-net must not reach external network"
    )


@_REQUIRES_BWRAP
@pytest.mark.skipif(
    os.environ.get("GYZA_TEST_NETWORK") != "1",
    reason="network-positive test gated on GYZA_TEST_NETWORK=1",
)
def test_network_reachable_when_requested():
    """
    With ``requires_network=True``, the sandbox can reach the host's
    network. Gated behind an env flag because this test depends on
    real internet connectivity (1.1.1.1:53 must be reachable from
    the host running the suite).
    """
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_socket_probe",
        init_kwargs={"host": "1.1.1.1", "port": 53, "timeout_s": 3.0},
        config=SandboxConfig(timeout_s=15.0, requires_network=True),
    )
    out = fn("", {})
    assert out["ok"] is True


# ----------------------------------------------------------------------
# Resource limits
# ----------------------------------------------------------------------

@_REQUIRES_BWRAP
def test_wall_clock_timeout_raises():
    """
    Exceeding ``timeout_s`` raises SandboxTimeoutError (not
    SandboxExecutionError).
    """
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_sleep_probe",
        init_kwargs={"seconds": 5.0},
        config=SandboxConfig(timeout_s=1.0),
    )
    with pytest.raises(SandboxTimeoutError):
        fn("", {})


# ----------------------------------------------------------------------
# Environment passthrough
# ----------------------------------------------------------------------

@_REQUIRES_BWRAP
def test_env_set_reaches_sandbox():
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_env_probe",
        init_kwargs={"name": "GYZA_SANDBOX_TEST"},
        config=SandboxConfig(
            timeout_s=15.0,
            env_set={"GYZA_SANDBOX_TEST": "from-test"},
        ),
    )
    out = fn("", {})
    assert out["text"] == "from-test"


@_REQUIRES_BWRAP
def test_unset_env_is_empty(monkeypatch):
    """
    Without explicit passthrough, env vars from the parent are NOT
    visible inside the sandbox. Defends against accidental leakage of
    secrets via env.
    """
    monkeypatch.setenv("GYZA_SANDBOX_LEAK_PROBE", "should-not-leak")
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_env_probe",
        init_kwargs={"name": "GYZA_SANDBOX_LEAK_PROBE"},
        config=SandboxConfig(timeout_s=15.0),
    )
    out = fn("", {})
    assert out["text"] == ""


@_REQUIRES_BWRAP
def test_env_passthrough_forwards_named_var(monkeypatch):
    """
    An env var listed in ``env_passthrough`` is forwarded with its
    parent value.
    """
    monkeypatch.setenv("GYZA_SANDBOX_PASSTHRU_PROBE", "hello-via-passthrough")
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_env_probe",
        init_kwargs={"name": "GYZA_SANDBOX_PASSTHRU_PROBE"},
        config=SandboxConfig(
            timeout_s=15.0,
            env_passthrough=["GYZA_SANDBOX_PASSTHRU_PROBE"],
        ),
    )
    out = fn("", {})
    assert out["text"] == "hello-via-passthrough"


# ----------------------------------------------------------------------
# Error surfacing
# ----------------------------------------------------------------------

@_REQUIRES_BWRAP
def test_inner_exception_surfaces_as_execution_error():
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_raising_probe",
        init_kwargs={"message": "synthetic failure"},
        config=SandboxConfig(timeout_s=15.0),
    )
    with pytest.raises(SandboxExecutionError) as excinfo:
        fn("", {})
    assert "synthetic failure" in str(excinfo.value)
    assert excinfo.value.exc_type == "ValueError"


@_REQUIRES_BWRAP
def test_bad_factory_qualname_raises():
    fn = make_sandboxed_executor(
        "gyza.runner:does_not_exist_executor_factory",
        init_kwargs={},
        config=SandboxConfig(timeout_s=15.0),
    )
    with pytest.raises(SandboxExecutionError) as excinfo:
        fn("", {})
    # Could be ImportError or AttributeError; either is acceptable.
    assert excinfo.value.exc_type in ("ImportError", "AttributeError")


# ----------------------------------------------------------------------
# UID mapping — runs as nobody (65534) inside, regardless of host uid
# ----------------------------------------------------------------------

@_REQUIRES_BWRAP
def test_runs_as_unprivileged_uid():
    fn = make_sandboxed_executor(
        "gyza.sandbox._probes:make_uid_probe",
        config=SandboxConfig(timeout_s=15.0),
    )
    out = fn("", {})
    # The sandbox sets uid 65534 / gid 65534.
    assert "uid=65534" in out["text"]
    assert "gid=65534" in out["text"]


# ----------------------------------------------------------------------
# NONE backend — direct execution path
# ----------------------------------------------------------------------

def test_none_backend_runs_in_process():
    """
    SandboxBackend.NONE bypasses the subprocess and runs the inner
    executor directly. Used as fallback when bwrap is unavailable.
    """
    r = run_sandboxed(
        factory_qualname="gyza.runner:make_mock_executor",
        init_kwargs={"response": "in-process"},
        prompt="",
        context={},
        config=SandboxConfig(backend=SandboxBackend.NONE),
    )
    assert r.payload["text"] == "in-process"


# ----------------------------------------------------------------------
# Config surface
# ----------------------------------------------------------------------

def test_default_system_paths_includes_python_prefix():
    """
    The autodiscovered path set must cover the running interpreter's
    prefix; otherwise the entrypoint can't even be invoked.
    """
    import sys
    from gyza.sandbox import default_system_paths
    paths = default_system_paths()
    assert sys.prefix in paths
    # /usr is always there (system tools).
    assert "/usr" in paths


def test_config_defaults_are_safe():
    """
    Defaults: no network, 2GB RLIMIT_AS, 300s CPU, 120s wall clock.
    Locking these in so a casual edit doesn't widen the boundary.
    """
    cfg = SandboxConfig()
    assert cfg.requires_network is False
    assert cfg.max_memory_mb == 2048
    assert cfg.max_cpu_seconds == 300
    assert cfg.timeout_s == 120.0
    assert cfg.backend == SandboxBackend.BUBBLEWRAP
    assert cfg.ro_paths == []
    assert cfg.rw_paths == []
