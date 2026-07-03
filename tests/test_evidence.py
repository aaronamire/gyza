"""
Tests for evidence bundles (gyza.evidence) — the portable form of the
unified audit.

The bundle is a carrier, not a trust boundary: everything inside is
judged by the same verifiers as a local audit. These tests pin (1) the
honest round-trip (create → bytes → load → verify VALID), (2) byte
determinism (same workflow → same bundle hash), (3) that every attack
the audit rejects locally is also rejected when it arrives by bundle
(tampered artifact, withheld artifact, tampered envelope), and (4) that
malformed files fail loudly as BundleError, never as a silent pass.
"""
from __future__ import annotations

import base64

import pytest

from gyza.evidence import (
    BUNDLE_FORMAT,
    BUNDLE_VERSION,
    BundleError,
    bundle_hash,
    bundle_to_bytes,
    create_bundle,
    load_bundle,
    verify_bundle,
)
from tests.test_audit import _honest_workflow

INTENT = "audit-test-intent"


def _bundle_of(tmp_path):
    envs, artifacts, manifests, _ = _honest_workflow(tmp_path)
    bundle = create_bundle(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
        intent_id=INTENT,
    )
    return bundle, envs


def test_honest_round_trip_verifies_valid(tmp_path):
    bundle, envs = _bundle_of(tmp_path)
    loaded = load_bundle(bundle_to_bytes(bundle))
    report = verify_bundle(loaded)
    assert report.valid, report.summary
    assert len(report.actions) == len(envs)
    assert any(r.is_execution for r in report.actions)


def test_bundle_bytes_are_deterministic(tmp_path):
    # The same stored workflow exported twice → byte-identical bundles,
    # same hash. This is what makes a bundle hash a stable citation.
    # (Two separate *signings* legitimately differ — timestamp_ns — so
    # determinism is over the evidence, not over re-execution.)
    envs, artifacts, manifests, _ = _honest_workflow(tmp_path)
    b1 = create_bundle(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
        intent_id=INTENT,
    )
    b2 = create_bundle(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
        intent_id=INTENT,
    )
    assert bundle_to_bytes(b1) == bundle_to_bytes(b2)
    assert bundle_hash(b1) == bundle_hash(b2)


def test_bundle_shape_and_metadata(tmp_path):
    bundle, envs = _bundle_of(tmp_path)
    assert bundle["format"] == BUNDLE_FORMAT
    assert bundle["version"] == BUNDLE_VERSION
    assert bundle["intent_id"] == INTENT
    assert "runner_version" in bundle["runner"]
    assert len(bundle["envelopes"]) == len(envs)
    # Every output artifact of the honest workflow was resolvable.
    assert set(bundle["artifacts"]) == {e.output_hash for e in envs}


def test_tampered_artifact_in_bundle_rejected(tmp_path):
    bundle, envs = _bundle_of(tmp_path)
    exec_env = envs[1]
    bundle["artifacts"][exec_env.output_hash] = base64.b64encode(
        b'{"text":"forged"}'
    ).decode("ascii")
    report = verify_bundle(load_bundle(bundle_to_bytes(bundle)))
    assert not report.valid
    bad = [r for r in report.actions if not r.ok][0]
    assert "tampered" in bad.reason


def test_withheld_artifact_in_bundle_fails_closed(tmp_path):
    bundle, envs = _bundle_of(tmp_path)
    del bundle["artifacts"][envs[1].output_hash]
    report = verify_bundle(load_bundle(bundle_to_bytes(bundle)))
    assert not report.valid
    bad = [r for r in report.actions if not r.ok][0]
    assert "not resolvable" in bad.reason


def test_tampered_envelope_field_breaks_signature(tmp_path):
    bundle, _ = _bundle_of(tmp_path)
    bundle["envelopes"][1]["tokens_out"] = 999_999
    report = verify_bundle(load_bundle(bundle_to_bytes(bundle)))
    assert not report.valid
    assert "signature invalid" in report.dag.reason


def test_malformed_bundles_raise_bundle_error(tmp_path):
    bundle, _ = _bundle_of(tmp_path)
    good = bundle_to_bytes(bundle)

    with pytest.raises(BundleError, match="not valid JSON"):
        load_bundle(b"{ not json")
    with pytest.raises(BundleError, match="JSON object"):
        load_bundle(b"[1,2,3]")
    with pytest.raises(BundleError, match="format"):
        load_bundle(good.replace(BUNDLE_FORMAT.encode(), b"something-else"))

    wrong_version = dict(bundle, version=999)
    with pytest.raises(BundleError, match="version"):
        load_bundle(bundle_to_bytes(wrong_version))

    extra_key = dict(bundle, sneaky="payload")
    with pytest.raises(BundleError, match="unexpected bundle shape"):
        load_bundle(bundle_to_bytes(extra_key))

    no_envs = dict(bundle, envelopes=[])
    with pytest.raises(BundleError, match="no envelopes"):
        load_bundle(bundle_to_bytes(no_envs))


def test_envelope_with_wrong_fields_raises(tmp_path):
    bundle, _ = _bundle_of(tmp_path)
    bundle["envelopes"][0]["not_a_field"] = 1
    with pytest.raises(BundleError, match="wrong fields"):
        verify_bundle(load_bundle(bundle_to_bytes(bundle)))


def test_bad_base64_artifact_raises(tmp_path):
    bundle, envs = _bundle_of(tmp_path)
    bundle["artifacts"][envs[0].output_hash] = "!!not-base64!!"
    with pytest.raises(BundleError, match="base64"):
        verify_bundle(load_bundle(bundle_to_bytes(bundle)))


def test_full_stack_store_to_valid_bundle(tmp_path):
    # The exact path `gyza bundle` takes: real Blackboard (envelope log)
    # + real ArtifactStore (content-addressed bytes, manifests stored as
    # canonical JSON) → reconstruct_dag → create_bundle → bytes → load →
    # verify VALID. A forked fan-in workflow, so the DAG is non-linear.
    import json

    from gyza.blackboard import Blackboard
    from gyza.network.artifact_store import ArtifactStore
    from tests.test_audit import _agent, _enforcement, _sign
    from gyza.identity import LocalCompositor

    compositor = LocalCompositor(key_path=str(tmp_path / "k.key"))
    coord = _agent(compositor, 1024)
    worker = _agent(compositor, 512)

    e0, a0 = _sign(coord, "root", None, text="root", enforcement=None)
    eA, aA = _sign(worker, "branch-a", e0, text="A", enforcement=_enforcement(512))
    eB, aB = _sign(worker, "branch-b", e0, text="B", enforcement=_enforcement(512))
    e_sink, a_sink = _sign(
        coord, "synthesize", eA, text="sink", enforcement=_enforcement(1024),
        inputs=[eA.output_hash, eB.output_hash],
    )

    bb = Blackboard(str(tmp_path / "bb.db"))
    store = ArtifactStore(base_path=str(tmp_path / "artifacts"))
    for e, a in ((e0, a0), (eA, aA), (eB, aB), (e_sink, a_sink)):
        bb.store_envelope(e)
        store.store(a)
    for identity in (coord, worker):
        store.store(json.dumps(
            identity.manifest, sort_keys=True, separators=(",", ":")
        ).encode())

    def _manifest(h: str) -> "dict | None":
        raw = store.get(h)
        if raw is None:
            return None
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return obj if isinstance(obj, dict) else None

    recovered = bb.reconstruct_dag(INTENT)
    assert len(recovered) == 4
    bundle = create_bundle(
        recovered, resolve_artifact=store.get, resolve_manifest=_manifest,
        intent_id=INTENT,
    )
    report = verify_bundle(load_bundle(bundle_to_bytes(bundle)))
    assert report.valid, report.summary
    assert report.dag.valid
    assert len(report.dag.roots) == 1 and len(report.dag.leaves) == 1
    assert sum(1 for r in report.actions if r.is_execution) == 3


def test_create_bundle_is_permissive_verify_is_not(tmp_path):
    # Exporting a workflow with missing evidence must SUCCEED (shipping
    # proof of a violation is legitimate); verification must then fail
    # closed. Judgment lives in verify, not create.
    envs, artifacts, manifests, _ = _honest_workflow(tmp_path)
    del artifacts[envs[1].output_hash]
    bundle = create_bundle(
        envs, resolve_artifact=artifacts.get, resolve_manifest=manifests.get,
        intent_id=INTENT,
    )
    assert envs[1].output_hash not in bundle["artifacts"]
    report = verify_bundle(load_bundle(bundle_to_bytes(bundle)))
    assert not report.valid
