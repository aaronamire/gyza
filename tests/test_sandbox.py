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


@_REQUIRES_BWRAP
def test_sandboxed_executor_accepts_runner_context():
    # The runner's real context carries the WorkItem OBJECT (with a numpy
    # embedding) — not JSON-serializable. The sandbox wrapper must project
    # it to a JSON-safe form at the process boundary instead of blowing up
    # (the A3 production-wiring gap: caught live by `gyza run`).
    import time
    import uuid

    import numpy as np

    from gyza.schema import EMBEDDING_DIM, WorkItem

    item = WorkItem(
        id=str(uuid.uuid7()), lineage_root="intent-x", parent_id=None,
        description="d", desc_embedding=np.zeros(EMBEDDING_DIM, dtype=np.float32),
        reward=0.5, reward_updated_ns=time.time_ns(), required_tier=0,
        input_hashes=["00" * 32], output_spec={}, streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(), ttl_ns=10**12,
    )
    fn = make_sandboxed_executor(
        "gyza.runner:make_mock_executor",
        init_kwargs={"response": "ok"},
        config=SandboxConfig(timeout_s=15.0),
    )
    out = fn("prompt", {"item": item, "inputs": [{"text": "prior"}]})
    assert out["text"] == "ok"
    assert "__enforcement__" in out


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


# ----------------------------------------------------------------------
# sandbox_config_from_manifest — the manifest ≡ sandbox bridge.
# This is the connective tissue of a sound bounds-proof: the bounds the
# agent manifest DECLARES must be exactly the bounds bwrap ENFORCES.
# ----------------------------------------------------------------------

def test_sandbox_config_from_manifest_mirrors_filesystem_authorization(tmp_path):
    """A manifest's filesystem.read/write becomes ro_paths/rw_paths verbatim."""
    from gyza.identity import LocalCompositor
    from gyza.sandbox import sandbox_config_from_manifest

    comp = LocalCompositor(key_path=str(tmp_path / "comp.key"))
    _seed, manifest = comp.issue_agent(
        agent_type="test.bounds",
        model_path="mock",
        fs_read_paths=["/data/in", "/usr/share/x"],
        fs_write_paths=["/data/out"],
        allowed_hosts=["api.anthropic.com"],
        memory_limit_mb=1024,
        attestation_tier=1,
    )
    cfg = sandbox_config_from_manifest(manifest, workspace="/tmp/ws")
    # The sandbox config is the manifest's authorization, verbatim — so
    # "declared" and "enforced" cannot silently diverge.
    assert cfg.ro_paths == ["/data/in", "/usr/share/x"]
    assert cfg.rw_paths == ["/data/out"]
    assert cfg.workspace == "/tmp/ws"
    assert cfg.max_memory_mb == 1024
    assert cfg.backend == SandboxBackend.BUBBLEWRAP


def test_sandbox_config_from_manifest_network_is_all_or_nothing(tmp_path):
    """
    A manifest listing allowed_hosts opens the network namespace; a
    manifest with none keeps it closed. bwrap can't enforce a per-host
    allowlist — that's a documented partial-enforcement dimension.
    """
    from gyza.identity import LocalCompositor
    from gyza.sandbox import sandbox_config_from_manifest

    comp = LocalCompositor(key_path=str(tmp_path / "comp.key"))
    _s1, with_net = comp.issue_agent(
        agent_type="t", model_path="mock", fs_read_paths=[], fs_write_paths=[],
        allowed_hosts=["example.com"], attestation_tier=1,
    )
    _s2, no_net = comp.issue_agent(
        agent_type="t", model_path="mock", fs_read_paths=[], fs_write_paths=[],
        attestation_tier=1,
    )
    assert sandbox_config_from_manifest(with_net).requires_network is True
    assert sandbox_config_from_manifest(no_net).requires_network is False


def test_sandbox_config_from_manifest_tolerates_malformed_manifest():
    """A manifest missing the capabilities sub-dict yields empty bounds,
    not a crash — the safest possible failure (nothing authorized)."""
    from gyza.sandbox import sandbox_config_from_manifest

    cfg = sandbox_config_from_manifest({})
    assert cfg.ro_paths == []
    assert cfg.rw_paths == []
    assert cfg.requires_network is False


# ----------------------------------------------------------------------
# enforcement_satisfies_manifest — full predicate completeness tests
# (added S34). The previous brick-3 tests covered the FS dimension via
# the runner integration test; here we lock the predicate's behavior
# on the memory dimension and the asymmetric "no manifest cap = no
# check" rule, because that distinction is load-bearing for back-compat.
# ----------------------------------------------------------------------

def _enforcement(*, ro=None, rw=None, net=False, mem=None):
    """Helper: build a well-formed enforcement record."""
    return {
        "backend": "bubblewrap",
        "ro_paths": list(ro or []),
        "rw_paths": list(rw or []),
        "requires_network": bool(net),
        "max_memory_mb": mem,
        "max_cpu_seconds": 300,
        "timeout_s": 60.0,
    }


def _manifest(*, ro=None, rw=None, hosts=None, mem=None):
    """Helper: build a manifest authorizing the given capabilities."""
    caps: dict = {
        "filesystem": {"read": list(ro or []), "write": list(rw or [])},
        "network": {"allowed_hosts": list(hosts or [])},
    }
    if mem is not None:
        caps["spawn"] = {"resource_budget": {"memory_limit_mb": mem}}
    return {"capabilities": caps}


def test_predicate_memory_within_manifest_passes():
    from gyza.sandbox import enforcement_satisfies_manifest
    ok, why = enforcement_satisfies_manifest(
        _enforcement(mem=512),
        _manifest(mem=1024),
    )
    assert ok, why


def test_predicate_memory_equal_to_manifest_passes():
    """Boundary: equal is allowed (subset semantics include equality)."""
    from gyza.sandbox import enforcement_satisfies_manifest
    ok, why = enforcement_satisfies_manifest(
        _enforcement(mem=1024),
        _manifest(mem=1024),
    )
    assert ok, why


def test_predicate_memory_exceeds_manifest_fails():
    from gyza.sandbox import enforcement_satisfies_manifest
    ok, why = enforcement_satisfies_manifest(
        _enforcement(mem=2048),
        _manifest(mem=1024),
    )
    assert not ok
    assert "exceeds manifest budget" in why


def test_predicate_unbounded_enforcement_under_declared_manifest_fails():
    """Manifest declared a cap; enforcement record has None for memory.
    Strict rule: "no cap" under a declared cap is a violation, not a
    no-op. Otherwise an attacker could omit the field to bypass."""
    from gyza.sandbox import enforcement_satisfies_manifest
    ok, why = enforcement_satisfies_manifest(
        _enforcement(mem=None),
        _manifest(mem=1024),
    )
    assert not ok
    assert "no memory cap" in why


def test_predicate_no_manifest_cap_skips_memory_check():
    """Manifest declared no memory cap → predicate doesn't enforce one.
    Back-compat with manifests that never had memory_limit_mb."""
    from gyza.sandbox import enforcement_satisfies_manifest
    ok, why = enforcement_satisfies_manifest(
        _enforcement(mem=999999),     # arbitrary; not constrained
        _manifest(),                  # no memory in manifest
    )
    assert ok, why


def test_predicate_zero_manifest_cap_is_treated_as_unset():
    """memory_limit_mb=0 is a misconfiguration — treat as no cap (don't
    fail-closed against a misconfigured manifest)."""
    from gyza.sandbox import enforcement_satisfies_manifest
    ok, why = enforcement_satisfies_manifest(
        _enforcement(mem=512),
        _manifest(mem=0),
    )
    assert ok, why


def test_predicate_invalid_enforcement_memory_value_fails():
    from gyza.sandbox import enforcement_satisfies_manifest
    for bad in (0, -1, "1024", 1.5):
        ok, why = enforcement_satisfies_manifest(
            {**_enforcement(mem=512), "max_memory_mb": bad},
            _manifest(mem=1024),
        )
        assert not ok, f"predicate accepted bad enforcement memory {bad!r}"
        assert "positive int" in why or "exceeds" in why


def test_predicate_fs_subset_check_still_works_with_resource_fields():
    """Regression: the existing FS check must still fire even when the
    resource fields are present and within bounds."""
    from gyza.sandbox import enforcement_satisfies_manifest
    ok, why = enforcement_satisfies_manifest(
        _enforcement(ro=["/tmp", "/etc"], mem=256),
        _manifest(ro=["/tmp"], mem=1024),
    )
    assert not ok
    assert "read paths beyond manifest" in why


def test_tmpfs_precedes_tmp_rooted_binds_in_argv():
    # Regression (beta cold-install): bwrap layers mounts in argv order,
    # later shadowing earlier at the same path. The /tmp tmpfs must come
    # BEFORE any bind whose destination lives under /tmp — otherwise a
    # Python interpreter (sys.prefix) or ro_path physically under /tmp is
    # shadowed by the tmpfs and bwrap dies with "execvp .../python: No
    # such file or directory". This bit a venv installed under /tmp.
    from gyza.sandbox.runner import _build_bwrap_argv

    cfg = SandboxConfig(
        ro_paths=["/tmp/some/ro/path"],
        max_memory_mb=256,
        backend=SandboxBackend.BUBBLEWRAP,
    )
    argv = _build_bwrap_argv(cfg, python_bin="/tmp/venv/bin/python")

    tmpfs_idx = None
    for i in range(len(argv) - 1):
        if argv[i] == "--tmpfs" and argv[i + 1] == "/tmp":
            tmpfs_idx = i
            break
    assert tmpfs_idx is not None, "no --tmpfs /tmp in argv"

    # Every bind flag targeting a /tmp-rooted DEST must appear after it.
    bind_flags = {"--ro-bind", "--bind", "--symlink"}
    for i in range(len(argv) - 2):
        if argv[i] in bind_flags:
            dest = argv[i + 2]  # flag, src, dest
            if dest == "/tmp" or dest.startswith("/tmp/"):
                assert i > tmpfs_idx, (
                    f"bind {argv[i]} -> {dest} at {i} precedes the /tmp "
                    f"tmpfs at {tmpfs_idx}; it would be shadowed"
                )
