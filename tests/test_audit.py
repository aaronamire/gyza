"""
Tests for the unified provenance audit (gyza.audit) and the blackboard
DAG reconstruction that feeds it.

The audit is the product surface: one call over a workflow's envelopes
returns a single verdict (graph intact + every execution within bounds +
tamper-evident binding). These tests pin that it ACCEPTS an honest
workflow and REJECTS each distinct attack: an over-bound execution, a
tampered artifact, a withheld artifact, and a substituted manifest.
"""
from __future__ import annotations

import json

import blake3

from gyza.audit import audit_from_store, audit_provenance, render_audit_report
from gyza.blackboard import Blackboard
from gyza.icp import compute_envelope_hash, verify_dag
from gyza.identity import AgentIdentity, LocalCompositor

INTENT = "audit-test-intent"


def _agent(compositor: LocalCompositor, mem: int) -> AgentIdentity:
    seed, manifest = compositor.issue_agent(
        agent_type="audit.agent", model_path="mock",
        fs_read_paths=[], fs_write_paths=[], allowed_hosts=[],
        memory_limit_mb=mem, attestation_tier=1,
    )
    return AgentIdentity(seed, manifest)


def _enforcement(mem: int) -> dict:
    return {
        "backend": "bubblewrap", "ro_paths": [], "rw_paths": [],
        "requires_network": False, "max_memory_mb": mem,
    }


def _artifact_bytes(text: str, enforcement: dict | None) -> bytes:
    obj: dict = {"text": text}
    if enforcement is not None:
        obj["__enforcement__"] = enforcement
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _sign(identity, action, parent, *, text, enforcement, inputs=None):
    art = _artifact_bytes(text, enforcement)
    out_hash = blake3.blake3(art).hexdigest()
    if inputs is not None:
        in_hashes = list(inputs)
    elif parent is None:
        in_hashes = ["00" * 32]
    else:
        in_hashes = [compute_envelope_hash(parent)]
    env = identity.get_icp_signer().sign_action(
        intent_id=INTENT, action_id=action, input_hashes=in_hashes,
        output_hash=out_hash, parent_envelope=parent,
        inference_backend="mock", model_identifier="mock",
        duration_ms=0, tokens_in=0, tokens_out=0,
    )
    return env, art


def _honest_workflow(tmp_path):
    """root coordination -> one in-bounds execution (512 MB / 512 MB)."""
    compositor = LocalCompositor(key_path=str(tmp_path / "k.key"))
    coord = _agent(compositor, 1024)
    worker = _agent(compositor, 512)
    artifacts: dict[str, bytes] = {}
    manifests = {
        coord.manifest_hash: coord.manifest,
        worker.manifest_hash: worker.manifest,
    }

    e0, a0 = _sign(coord, "register", None, text="root", enforcement=None)
    e1, a1 = _sign(worker, "do-work", e0, text="work",
                   enforcement=_enforcement(512))
    for e, a in ((e0, a0), (e1, a1)):
        artifacts[e.output_hash] = a
    return [e0, e1], artifacts, manifests, (coord, worker)


def test_honest_workflow_audits_valid(tmp_path):
    envs, artifacts, manifests, _ = _honest_workflow(tmp_path)
    report = audit_provenance(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
    )
    assert report.valid, report.summary
    assert report.dag.valid
    assert any(r.is_execution and r.within_bounds for r in report.actions)


def test_over_bound_execution_rejected(tmp_path):
    compositor = LocalCompositor(key_path=str(tmp_path / "k.key"))
    worker = _agent(compositor, 512)
    manifests = {worker.manifest_hash: worker.manifest}
    # Sandbox enforced 1024 MB against a 512 MB manifest.
    e, a = _sign(worker, "rogue", None, text="x", enforcement=_enforcement(1024))
    report = audit_provenance(
        [e], resolve_artifact={e.output_hash: a}.get,
        resolve_manifest=manifests.get,
    )
    assert not report.valid
    row = report.actions[0]
    assert row.is_execution and not row.within_bounds
    assert "out of bounds" in row.reason


def test_tampered_artifact_rejected(tmp_path):
    envs, artifacts, manifests, _ = _honest_workflow(tmp_path)
    exec_env = envs[1]
    # Replace the artifact with bytes that don't hash to output_hash.
    artifacts[exec_env.output_hash] = b'{"text":"forged"}'
    report = audit_provenance(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
    )
    assert not report.valid
    bad = [r for r in report.actions if r.envelope_hash ==
           compute_envelope_hash(exec_env)][0]
    assert not bad.binding_ok
    assert "tampered" in bad.reason


def test_withheld_artifact_rejected(tmp_path):
    envs, artifacts, manifests, _ = _honest_workflow(tmp_path)
    exec_env = envs[1]
    del artifacts[exec_env.output_hash]  # hide the evidence
    report = audit_provenance(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
        require_all_artifacts=True,
    )
    assert not report.valid
    bad = [r for r in report.actions if r.envelope_hash ==
           compute_envelope_hash(exec_env)][0]
    assert not bad.binding_ok
    assert "not resolvable" in bad.reason


def test_withheld_artifact_skipped_when_not_required(tmp_path):
    # With require_all_artifacts=False, an envelope whose artifact this
    # replica does not hold is *skipped* (not-yet-auditable), not failed —
    # while every row it CAN resolve is still fully checked. binding_ok stays
    # honest (False for the missing one); the verdict stays VALID because the
    # missing row is skipped rather than counted against it.
    envs, artifacts, manifests, _ = _honest_workflow(tmp_path)
    exec_env = envs[1]
    del artifacts[exec_env.output_hash]  # this replica simply hasn't got it
    report = audit_provenance(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
        require_all_artifacts=False,
    )
    assert report.valid, report.summary
    skipped = [r for r in report.actions if r.envelope_hash ==
               compute_envelope_hash(exec_env)][0]
    assert not skipped.binding_ok  # honest: nothing was bound
    assert skipped.ok              # but the row is not held against the audit
    # And the same withheld artifact under the strict default still fails,
    # so the concession is opt-in, not a silent weakening.
    strict = audit_provenance(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
        require_all_artifacts=True,
    )
    assert not strict.valid


def test_substituted_manifest_rejected(tmp_path):
    envs, artifacts, manifests, agents = _honest_workflow(tmp_path)
    exec_env = envs[1]
    coord, worker = agents
    # Resolve the worker's manifest hash to the COORDINATOR's manifest
    # (1024 MB) — a hash that won't bind back.
    manifests[worker.manifest_hash] = coord.manifest
    report = audit_provenance(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
    )
    assert not report.valid
    bad = [r for r in report.actions if r.envelope_hash ==
           compute_envelope_hash(exec_env)][0]
    assert not bad.manifest_bound_ok


def test_blackboard_reconstruct_dag_round_trips(tmp_path):
    # Store a forked workflow in the real blackboard, reconstruct the DAG
    # from the envelope log, and audit it.
    compositor = LocalCompositor(key_path=str(tmp_path / "k.key"))
    coord = _agent(compositor, 1024)
    worker = _agent(compositor, 512)
    artifacts: dict[str, bytes] = {}
    manifests = {coord.manifest_hash: coord.manifest,
                 worker.manifest_hash: worker.manifest}

    e0, a0 = _sign(coord, "root", None, text="root", enforcement=None)
    eA, aA = _sign(worker, "branch-a", e0, text="A", enforcement=_enforcement(512))
    eB, aB = _sign(worker, "branch-b", e0, text="B", enforcement=_enforcement(512))
    e_sink, a_sink = _sign(
        coord, "synthesize", eA, text="sink",
        enforcement=_enforcement(1024),
        inputs=[eA.output_hash, eB.output_hash],  # fan-in
    )
    built = [e0, eA, eB, e_sink]
    for e, a in ((e0, a0), (eA, aA), (eB, aB), (e_sink, a_sink)):
        artifacts[e.output_hash] = a

    bb = Blackboard(str(tmp_path / "bb.db"))
    for e in built:
        bb.store_envelope(e)

    recovered = bb.reconstruct_dag(INTENT)
    assert len(recovered) == 4
    assert {compute_envelope_hash(e) for e in recovered} == \
           {compute_envelope_hash(e) for e in built}

    dag = verify_dag(recovered, require_closed=True)
    assert dag.valid
    assert len(dag.roots) == 1 and len(dag.leaves) == 1  # fan-in re-joined

    report = audit_provenance(
        recovered, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
    )
    assert report.valid, report.summary


def test_audit_from_store_and_render(tmp_path):
    # audit_from_store reads artifacts + manifests from one content-
    # addressed .get() store (manifests stored as their canonical bytes).
    envs, artifacts, manifests, _ = _honest_workflow(tmp_path)
    store: dict[str, bytes] = dict(artifacts)
    for mhash, manifest in manifests.items():
        store[mhash] = json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ).encode()
    report = audit_from_store(envs, store)
    assert report.valid, report.summary
    text = render_audit_report(report)
    assert "VERDICT: VALID" in text
    assert "Provenance graph: INTACT" in text


def test_render_shows_failure_reason(tmp_path):
    envs, artifacts, manifests, _ = _honest_workflow(tmp_path)
    del artifacts[envs[1].output_hash]  # drop an artifact
    report = audit_provenance(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
    )
    text = render_audit_report(report)
    assert "VERDICT: INVALID" in text
    assert "not resolvable" in text
