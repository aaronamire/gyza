"""
End-to-end: the REAL producer path must be auditable.

This is the proof for "#0" — the gap between "demoable" and "usable".
A live ``AgentRunner`` executes a work item, stores its output artifact
AND its manifest content-addressed, signs the ICP envelope; then the
unified audit, resolving everything from the same artifact store the
runner wrote to, must reach VALID. Before the manifest was persisted
content-addressed, the bounds half of the audit could only succeed on
the demo's in-memory store, never on real on-disk work.

The executor returns a within-bounds ``__enforcement__`` record
directly (no bubblewrap needed), so this exercises the full
producer->store->audit path deterministically on any machine.
"""
from __future__ import annotations

import json
import time
import uuid

import blake3
import numpy as np
import pytest

from gyza.audit import audit_from_store
from gyza.blackboard import Blackboard
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.icp import verify_dag
from gyza.identity import AgentIdentity, LocalCompositor, manifest_canonical_bytes
from gyza.memory import EpisodicMemory
from gyza.network.artifact_store import ArtifactStore
from gyza.runner import AgentRunner
from gyza.schema import EMBEDDING_DIM, WorkItem


def _within_bounds_executor(mem_mb: int):
    def executor(prompt: str, context: dict) -> dict:
        return {
            "text": "computed result",
            "__enforcement__": {
                "backend": "bubblewrap", "ro_paths": [], "rw_paths": [],
                "requires_network": False, "max_memory_mb": mem_mb,
            },
            "model_identifier": "mock", "inference_backend": "mock",
            "tokens_in": 0, "tokens_out": 0,
        }
    return executor


def _runner(tmp_path, bb, executor):
    comp = LocalCompositor(key_path=str(tmp_path / "k.key"))
    seed, manifest = comp.issue_agent(
        agent_type="audit.worker", model_path="mock",
        fs_read_paths=[], fs_write_paths=[], allowed_hosts=[],
        memory_limit_mb=512, attestation_tier=0,
    )
    ident = AgentIdentity(seed, manifest)
    mem = EpisodicMemory(agent_id=ident.agent_id, db_path=str(tmp_path / "mem"))
    spec_v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    spec_v[0] = 1.0
    spec = SpecializationTracker(
        agent_id=ident.agent_id, initial_embedding=spec_v,
        db_path=str(tmp_path / "spec.db"),
    )
    runner = AgentRunner(
        identity=ident, blackboard=bb, memory=mem, specialization=spec,
        lsh=LSHIndex(seed=42), executor=executor,
        min_reward_threshold=0.0, min_similarity_threshold=-1.0,
        verify_chain_before_claim=False,
    )
    return runner, ident, manifest


def _intent(bb: Blackboard, intent_id: str) -> None:
    bb.post_intent({
        "intent_id": intent_id, "natural_text": "audit it",
        "category": "system_task", "actions": [],
        "authorization": {"resources": [], "preview_required": False,
                          "reversible": True},
    })


def _work_item(intent_id: str) -> WorkItem:
    emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    emb[0] = 1.0
    return WorkItem(
        id=str(uuid.uuid7()), lineage_root=intent_id, parent_id=None,
        description="audit me", desc_embedding=emb, reward=0.5,
        reward_updated_ns=time.time_ns(), required_tier=0,
        input_hashes=["00" * 32], output_spec={}, streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )


def test_real_runner_output_audits_valid(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "cas"))
    bb = Blackboard(str(tmp_path / "bb.db"))
    bb.attach_artifact_store(store)

    runner, ident, manifest = _runner(
        tmp_path, bb, _within_bounds_executor(512),
    )
    intent_id = "runner-audit-intent"
    _intent(bb, intent_id)
    w = _work_item(intent_id)
    bb.post_work_item(w)

    # Drive one execute+complete cycle exactly as _run_loop does.
    result = runner._execute(w)
    runner._complete(w, result, success=True)

    # The runner must have persisted the manifest content-addressed under
    # its capability_manifest_hash — the heart of the fix.
    assert store.get(ident.manifest_hash) == manifest_canonical_bytes(manifest)

    # Reconstruct the workflow's DAG from the envelope log and audit it
    # against the same store the runner wrote to.
    envelopes = bb.reconstruct_dag(intent_id)
    assert len(envelopes) == 1
    dag = verify_dag(envelopes, require_closed=True)
    assert dag.valid, dag.reason

    report = audit_from_store(envelopes, store, require_closed=True)
    assert report.valid, report.summary
    row = report.actions[0]
    assert row.is_execution and row.within_bounds and row.binding_ok
    assert row.manifest_bound_ok


def test_over_bound_runner_output_audits_invalid(tmp_path):
    # If a (hypothetical) runner stamped an over-bound enforcement record,
    # the audit must catch it. (The runner's own brick-3 gate would refuse
    # to sign first; this proves the audit is an independent backstop.)
    store = ArtifactStore(base_path=str(tmp_path / "cas"))
    bb = Blackboard(str(tmp_path / "bb.db"))
    bb.attach_artifact_store(store)

    # Manifest authorizes 512 MB; executor claims 2048 MB enforcement.
    runner, ident, manifest = _runner(
        tmp_path, bb, _within_bounds_executor(2048),
    )
    intent_id = "runner-overbound-intent"
    _intent(bb, intent_id)
    w = _work_item(intent_id)
    bb.post_work_item(w)

    # The runner's own gate raises before signing — that's the producer
    # backstop. We assert it refuses, then prove the audit would also
    # reject the same record independently.
    with pytest.raises(Exception):
        runner._execute(w)

    # Build the artifact the over-bound run WOULD have produced and audit
    # it directly against the real manifest.
    over = {"text": "x", "__enforcement__": {
        "backend": "bubblewrap", "ro_paths": [], "rw_paths": [],
        "requires_network": False, "max_memory_mb": 2048}}
    art = json.dumps(over, sort_keys=True, separators=(",", ":")).encode()
    out_hash = blake3.blake3(art).hexdigest()
    env = ident.get_icp_signer().sign_action(
        intent_id=intent_id, action_id=w.id, input_hashes=["00" * 32],
        output_hash=out_hash, parent_envelope=None,
        inference_backend="mock", model_identifier="mock",
        duration_ms=0, tokens_in=0, tokens_out=0,
    )
    store.store(art)
    store.store(manifest_canonical_bytes(manifest))
    report = audit_from_store([env], store, require_closed=True)
    assert not report.valid
    assert not report.actions[0].within_bounds
