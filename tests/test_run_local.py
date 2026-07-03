"""
Tests for `gyza run`'s core (cli.run_local_task) — the single-player
product path: one command in, one bounded + signed + auditable action
out, ending in evidence a third party can verify.

The executor is injected (the sandboxed presets need bwrap; their
soundness is covered by test_sandbox.py). What's pinned here is the
wiring: the real runner path persists artifact + manifest content-
addressed, the audit over the store reaches VALID, the evidence bundle
round-trips, the local agent identity persists across runs (and is
reissued when bounds change), and an over-bound enforcement record is
refused with no envelope produced.
"""
from __future__ import annotations

import json

from gyza.cli import run_local_task
from gyza.config import GyzaConfig
from gyza.evidence import bundle_to_bytes, create_bundle, load_bundle, verify_bundle


def _cfg(tmp_path) -> GyzaConfig:
    return GyzaConfig(
        blackboard_db_path=str(tmp_path / "bb.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        compositor_key_path=str(tmp_path / "compositor.key"),
        anthropic_api_key="",
    )


def _bounded_executor(mem_mb: int):
    def executor(prompt: str, context: dict) -> dict:
        return {
            "text": f"done: {prompt[:40]}",
            "__enforcement__": {
                "backend": "bubblewrap", "ro_paths": [], "rw_paths": [],
                "requires_network": False, "max_memory_mb": mem_mb,
            },
            "model_identifier": "mock", "inference_backend": "mock",
            "tokens_in": 0, "tokens_out": 0,
        }
    return executor


def test_run_local_task_produces_valid_auditable_record(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    code, intent_id = run_local_task(
        "count the files", cfg=cfg, executor=_bounded_executor(512),
        artifact_store_base=str(tmp_path / "cas"),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "audit: VALID" in out
    assert f"gyza bundle {intent_id}" in out
    assert "done: count the files" in out  # the result text is shown

    # The record is real: reconstructable, auditable, and bundleable by
    # the same stores the run wrote to.
    from gyza.blackboard import Blackboard
    from gyza.network.artifact_store import ArtifactStore

    bb = Blackboard(str(tmp_path / "bb.db"))
    store = ArtifactStore(base_path=str(tmp_path / "cas"))
    envelopes = bb.reconstruct_dag(intent_id)
    assert len(envelopes) == 1

    def _manifest(h):
        raw = store.get(h)
        if raw is None:
            return None
        obj = json.loads(raw.decode("utf-8"))
        return obj if isinstance(obj, dict) else None

    bundle = create_bundle(
        envelopes, resolve_artifact=store.get, resolve_manifest=_manifest,
        intent_id=intent_id,
    )
    report = verify_bundle(load_bundle(bundle_to_bytes(bundle)))
    assert report.valid, report.summary
    assert report.actions[0].is_execution


def test_local_agent_identity_persists_across_runs(tmp_path):
    cfg = _cfg(tmp_path)
    _, i1 = run_local_task(
        "task one", cfg=cfg, executor=_bounded_executor(512),
        artifact_store_base=str(tmp_path / "cas"),
    )
    _, i2 = run_local_task(
        "task two", cfg=cfg, executor=_bounded_executor(512),
        artifact_store_base=str(tmp_path / "cas"),
    )
    from gyza.blackboard import Blackboard

    bb = Blackboard(str(tmp_path / "bb.db"))
    (e1,) = bb.reconstruct_dag(i1)
    (e2,) = bb.reconstruct_dag(i2)
    # Same persistent identity signs both runs — one agent, one growing
    # history — and both bind to the same manifest.
    assert e1.agent_pubkey == e2.agent_pubkey
    assert e1.capability_manifest_hash == e2.capability_manifest_hash


def test_changed_bounds_reissue_identity(tmp_path):
    cfg = _cfg(tmp_path)
    _, i1 = run_local_task(
        "task one", cfg=cfg, executor=_bounded_executor(512),
        artifact_store_base=str(tmp_path / "cas"),
    )
    # A different memory bound is a different grant → fresh identity,
    # fresh manifest. (Attributing new work to an authorization it never
    # had would be a provenance lie.)
    _, i2 = run_local_task(
        "task two", cfg=cfg, executor=_bounded_executor(256), memory_mb=256,
        artifact_store_base=str(tmp_path / "cas"),
    )
    from gyza.blackboard import Blackboard

    bb = Blackboard(str(tmp_path / "bb.db"))
    (e1,) = bb.reconstruct_dag(i1)
    (e2,) = bb.reconstruct_dag(i2)
    assert e1.agent_pubkey != e2.agent_pubkey
    assert e1.capability_manifest_hash != e2.capability_manifest_hash


def test_over_bound_run_refused_no_envelope(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    # Executor claims 2048 MB enforcement against a 512 MB manifest —
    # the runner's brick-3 gate must refuse BEFORE signing.
    code, intent_id = run_local_task(
        "overstep", cfg=cfg, executor=_bounded_executor(2048),
        artifact_store_base=str(tmp_path / "cas"),
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "REFUSED" in err
    from gyza.blackboard import Blackboard

    bb = Blackboard(str(tmp_path / "bb.db"))
    assert bb.reconstruct_dag(intent_id) == []
