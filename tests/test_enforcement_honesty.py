"""
Regression: the enforcement record reflects what ACTUALLY executed.

Before this fix the demo constructed a record with ``backend=bubblewrap``
when bwrap never ran, and ``enforcement_satisfies_manifest`` then passed —
an unenforced run could produce "within bounds ✓". That is a soundness bug
in a provenance product. These tests are the proof the fabrication path is
gone: no bwrap ⇒ backend=none ⇒ the bounds gate fails closed.
"""
from __future__ import annotations

import pytest

from gyza.demo.ddil_partition import _enforcement_record, run_demo
from gyza.sandbox.config import (
    SandboxBackend,
    SandboxConfig,
    enforcement_satisfies_manifest,
)
from gyza.sandbox.runner import SandboxUnavailableError, run_sandboxed


def _bounded_manifest(mem_mb: int = 512) -> dict:
    return {"capabilities": {
        "filesystem": {"read": [], "write": []},
        "network": {"allowed_hosts": []},
        "spawn": {"resource_budget": {"memory_limit_mb": mem_mb}}}}


def test_unenforced_record_is_backend_none_and_fails_closed():
    # A record built WITHOUT running bwrap must not claim an enforcing
    # backend, and must not satisfy a bounded manifest.
    rec = _enforcement_record(SandboxConfig(max_memory_mb=512), real=False)
    assert rec["backend"] == SandboxBackend.NONE.value      # never fabricates bubblewrap
    ok, why = enforcement_satisfies_manifest(rec, _bounded_manifest())
    assert ok is False                                       # fail-closed
    assert "not an enforcing sandbox" in why


def test_no_bubblewrap_record_producible_without_bwrap(monkeypatch):
    # The production path refuses rather than silently degrading a
    # BUBBLEWRAP request to NONE — so a stamped bubblewrap record always
    # means bwrap actually ran.
    import gyza.sandbox.runner as runner_mod
    monkeypatch.setattr(runner_mod.shutil, "which", lambda _name: None)
    with pytest.raises(SandboxUnavailableError):
        run_sandboxed(
            factory_qualname="gyza.sandbox.runner:_never_reached",
            init_kwargs={}, prompt="", context={},
            config=SandboxConfig(backend=SandboxBackend.BUBBLEWRAP))


def test_no_source_fixture_fabricates_a_bubblewrap_record():
    # Category closer (not just the instance): a `backend: bubblewrap`
    # record may ONLY come from the post-run executor stamp — never a
    # hardcoded literal, which would be a latent fabrication the moment a
    # future caller checks enforcement SUCCESS instead of rejection.
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1] / "gyza"
    pat = re.compile(r'["\']backend["\']\s*:\s*["\']bubblewrap["\']')
    offenders = [
        f"{py.relative_to(root.parent)}:{i}"
        for py in root.rglob("*.py")
        for i, line in enumerate(py.read_text().splitlines(), 1)
        if pat.search(line)
    ]
    assert not offenders, (
        "hardcoded bubblewrap enforcement record(s) found — a fabrication "
        "primitive. Only the post-run executor stamp (cfg.backend.value after "
        "run_sandboxed, which raises without bwrap) may yield "
        "backend=bubblewrap: " + ", ".join(offenders)
    )


def test_demo_construct_mode_does_not_fabricate():
    # The demo runs end-to-end under disclosed no-sandbox WITHOUT
    # fabricating: every executed action's folded enforcement is
    # backend=none, and the over-bound action is still rejected.
    res = run_demo(verbose=False, sandbox_mode="construct")
    assert res.over_bound_rejected
    execed = [enf for (_t, enf, _m) in res.audit.values() if enf is not None]
    assert execed, "expected some executed (sandboxed) actions"
    assert all(e["backend"] == SandboxBackend.NONE.value for e in execed)
