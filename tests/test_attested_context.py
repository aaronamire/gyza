"""The context that produced an output must be provable, and RECONSTRUCTIBLE.

THE GAP THIS CLOSES. `build_enriched_prompt` injects up to five retrieved
episodes into every prompt (memory.py), and the signed envelope's
`input_hashes` committed to the work item's DECLARED inputs only. So the
system could not prove what context produced an output -- an inference-time
control action was applied but not auditable.

DESIGN, and why it needs no schema change: the assembled prompt is stored
content-addressed and its hash is APPENDED to `input_hashes`. icp.py's DAG
note states the schema is "already capable" and the treatment is "deliberately
additive" -- existing signatures and the Rust byte-parity fixtures are
untouched. No spurious DAG edge forms either: a data-dependency edge requires
an input hash to match another envelope's `output_hash`, which an artifact
hash never does.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _runner_with_cas(tmp_path):
    """A runner whose blackboard has a content-addressed store attached."""
    from gyza.blackboard import Blackboard
    from gyza.network.artifact_store import ArtifactStore

    bb = Blackboard(str(tmp_path / "bb.db"))
    bb._artifact_store = ArtifactStore(base_path=str(tmp_path / "cas"))
    return bb


def test_context_is_stored_and_RECONSTRUCTIBLE(tmp_path):
    """Not 'a hash exists' -- the actual context must come back out."""
    from gyza.runner import AgentRunner

    bb = _runner_with_cas(tmp_path)
    r = AgentRunner.__new__(AgentRunner)
    r._bb = bb

    prompt = "## Relevant past experience\nepisode-A\nepisode-B\n\ndo the task"
    h = r._attest_context(prompt)
    assert h and len(h) == 64

    # an offline verifier, holding only the hash, recovers the exact bytes
    recovered = bb._artifact_store.get(h)
    assert recovered.decode("utf-8") == prompt
    assert "episode-A" in recovered.decode("utf-8"), (
        "the RETRIEVED EPISODES must be recoverable -- that is the whole point")


def test_no_CAS_means_no_claim_rather_than_a_silent_skip(tmp_path):
    """A runner without a store must make NO context claim, not a false one."""
    from gyza.blackboard import Blackboard
    from gyza.runner import AgentRunner

    r = AgentRunner.__new__(AgentRunner)
    r._bb = Blackboard(str(tmp_path / "bb.db"))      # no _artifact_store
    assert r._attest_context("anything") is None


def test_attestation_never_breaks_execution(tmp_path):
    """A measurement surface must not be why an action fails."""
    from gyza.runner import AgentRunner

    class _Broken:
        def store(self, b): raise RuntimeError("disk full")

    class _BB:
        _artifact_store = _Broken()

    r = AgentRunner.__new__(AgentRunner)
    r._bb = _BB()
    assert r._attest_context("prompt") is None      # degrades, does not raise


def test_identical_context_is_deduplicated(tmp_path):
    """Content addressing: the same context yields the same hash."""
    from gyza.runner import AgentRunner

    bb = _runner_with_cas(tmp_path)
    r = AgentRunner.__new__(AgentRunner)
    r._bb = bb
    assert r._attest_context("same") == r._attest_context("same")
    assert r._attest_context("same") != r._attest_context("different")


def test_context_hash_is_APPENDED_never_substituted():
    """A verifier must still see every declared input."""
    import inspect

    from gyza import runner

    src = inspect.getsource(runner.AgentRunner)
    assert "input_hashes.append(_ctx)" in src
    assert "if _ctx and _ctx not in input_hashes" in src, (
        "must be idempotent -- a context already declared as an input must "
        "not be added twice")


def test_the_envelope_schema_is_UNCHANGED():
    """No schema bump, so Rust byte-parity fixtures stay valid."""
    from dataclasses import fields

    from gyza.icp import ICPEnvelope

    names = [f.name for f in fields(ICPEnvelope)]
    assert "context_hash" not in names, (
        "attested context must NOT add an envelope field -- field order is "
        "load-bearing for Python/Rust canonical parity")
    assert names.index("input_hashes") >= 0
