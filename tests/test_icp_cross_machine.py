from __future__ import annotations

import json
import time

import blake3
import pytest

from gyza.icp import (
    ICPEnvelope,
    ICPSigner,
    compute_envelope_hash,
    generate_chain_report,
    sign_envelope,
    verify_chain_multi_compositor,
)
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.network.artifact_store import ArtifactStore
from gyza.network.trust_registry import TrustRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_compositor_and_agent(tmp_path, label: str):
    compositor = LocalCompositor(key_path=str(tmp_path / f"comp-{label}.key"))
    seed, manifest = compositor.issue_agent(
        agent_type=label, model_path="mock",
        fs_read_paths=[], fs_write_paths=[], attestation_tier=1,
    )
    identity = AgentIdentity(seed, manifest)
    return compositor, identity, manifest


def _store_manifest(store: ArtifactStore, manifest: dict) -> str:
    """Store manifest canonical-JSON in the artifact store and return
    its content-addressed hash."""
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return store.store(payload)


def _store_artifact(store: ArtifactStore, content: bytes) -> str:
    return store.store(content)


def _sign_with_manifest_hash(
    identity: AgentIdentity,
    *,
    manifest_hash: str,
    intent_id: str,
    action_id: str,
    input_hashes: list[str],
    output_hash: str,
    parent: ICPEnvelope | None,
) -> ICPEnvelope:
    """Build a real signed envelope with capability_manifest_hash overridden
    to the artifact-store hash (which equals what verify expects)."""
    env = ICPEnvelope(
        intent_id=intent_id,
        action_id=action_id,
        agent_pubkey=identity.pubkey_hex,
        capability_manifest_hash=manifest_hash,
        input_hashes=list(input_hashes),
        output_hash=output_hash,
        parent_envelope_hash=(
            compute_envelope_hash(parent) if parent is not None else None
        ),
        timestamp_ns=time.time_ns(),
        inference_backend="mock",
        model_identifier="test",
        duration_ms=10,
        tokens_in=5,
        tokens_out=10,
    )
    return sign_envelope(env, identity._seed)


INTENT = "11111111-1111-4111-8111-111111111111"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_two_compositor_chain_verifies(tmp_path):
    """Hop 1 from compositor A's agent, hop 2 from compositor B's agent.
    Both compositors trusted. Chain verifies end-to-end."""
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))

    comp_a, ident_a, manifest_a = _setup_compositor_and_agent(tmp_path, "A")
    comp_b, ident_b, manifest_b = _setup_compositor_and_agent(tmp_path, "B")

    reg.add_trusted_compositor(comp_a.pubkey_hex)
    reg.add_trusted_compositor(comp_b.pubkey_hex)

    mh_a = _store_manifest(store, manifest_a)
    mh_b = _store_manifest(store, manifest_b)

    in_hash = _store_artifact(store, b"user-prompt")
    out1_hash = _store_artifact(store, b"plan from agent A")
    out2_hash = _store_artifact(store, b"draft from agent B")

    e1 = _sign_with_manifest_hash(
        ident_a, manifest_hash=mh_a, intent_id=INTENT, action_id="act-1",
        input_hashes=[in_hash], output_hash=out1_hash, parent=None,
    )
    e2 = _sign_with_manifest_hash(
        ident_b, manifest_hash=mh_b, intent_id=INTENT, action_id="act-2",
        input_hashes=[out1_hash], output_hash=out2_hash, parent=e1,
    )

    valid, idx, reason = verify_chain_multi_compositor([e1, e2], reg, store)
    assert valid is True, f"expected valid, got idx={idx} reason={reason}"
    assert idx == -1


def test_untrusted_compositor_fails_at_that_hop(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))

    comp_a, ident_a, manifest_a = _setup_compositor_and_agent(tmp_path, "A")
    comp_b, ident_b, manifest_b = _setup_compositor_and_agent(tmp_path, "B")
    # ONLY trust compositor A; B is unknown.
    reg.add_trusted_compositor(comp_a.pubkey_hex)

    mh_a = _store_manifest(store, manifest_a)
    mh_b = _store_manifest(store, manifest_b)

    in_hash = _store_artifact(store, b"prompt")
    out1 = _store_artifact(store, b"out1")
    out2 = _store_artifact(store, b"out2")

    e1 = _sign_with_manifest_hash(
        ident_a, manifest_hash=mh_a, intent_id=INTENT, action_id="act-1",
        input_hashes=[in_hash], output_hash=out1, parent=None,
    )
    e2 = _sign_with_manifest_hash(
        ident_b, manifest_hash=mh_b, intent_id=INTENT, action_id="act-2",
        input_hashes=[out1], output_hash=out2, parent=e1,
    )

    valid, idx, reason = verify_chain_multi_compositor([e1, e2], reg, store)
    assert valid is False
    assert idx == 1
    assert "not trusted" in reason


def test_tampered_input_hash_mid_chain_fails_at_correct_hop(tmp_path):
    """Hop 2 lists an input hash whose artifact does not exist in the store."""
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))

    comp, ident, manifest = _setup_compositor_and_agent(tmp_path, "T")
    reg.add_trusted_compositor(comp.pubkey_hex)
    mh = _store_manifest(store, manifest)

    in_hash = _store_artifact(store, b"real input")
    out1 = _store_artifact(store, b"out1")
    out2 = _store_artifact(store, b"out2")

    e1 = _sign_with_manifest_hash(
        ident, manifest_hash=mh, intent_id=INTENT, action_id="act-1",
        input_hashes=[in_hash], output_hash=out1, parent=None,
    )
    # Hop 2 claims an input the artifact store doesn't have.
    bogus_input = "ff" * 32
    e2 = _sign_with_manifest_hash(
        ident, manifest_hash=mh, intent_id=INTENT, action_id="act-2",
        input_hashes=[bogus_input], output_hash=out2, parent=e1,
    )

    valid, idx, reason = verify_chain_multi_compositor([e1, e2], reg, store)
    assert valid is False
    assert idx == 1
    assert "not in artifact store" in reason


def test_envelope_signature_tampering_fails(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))

    comp, ident, manifest = _setup_compositor_and_agent(tmp_path, "S")
    reg.add_trusted_compositor(comp.pubkey_hex)
    mh = _store_manifest(store, manifest)
    in_hash = _store_artifact(store, b"in")
    out_hash = _store_artifact(store, b"out")

    e1 = _sign_with_manifest_hash(
        ident, manifest_hash=mh, intent_id=INTENT, action_id="act-1",
        input_hashes=[in_hash], output_hash=out_hash, parent=None,
    )
    # Mutate output_hash post-signing — signature won't match anymore.
    from dataclasses import replace
    bad_out = _store_artifact(store, b"forged")
    bad = replace(e1, output_hash=bad_out)
    valid, idx, reason = verify_chain_multi_compositor([bad], reg, store)
    assert valid is False
    assert idx == 0
    assert "signature" in reason.lower()


def test_chain_report_contains_compositor_prefixes_and_trust_markers(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))

    comp_a, ident_a, manifest_a = _setup_compositor_and_agent(tmp_path, "RA")
    comp_b, ident_b, manifest_b = _setup_compositor_and_agent(tmp_path, "RB")
    reg.add_trusted_compositor(comp_a.pubkey_hex)
    reg.add_trusted_compositor(comp_b.pubkey_hex)

    mh_a = _store_manifest(store, manifest_a)
    mh_b = _store_manifest(store, manifest_b)
    in_h = _store_artifact(store, b"prompt")
    o1 = _store_artifact(store, b"out1")
    o2 = _store_artifact(store, b"out2")

    e1 = _sign_with_manifest_hash(
        ident_a, manifest_hash=mh_a, intent_id=INTENT, action_id="act-1",
        input_hashes=[in_h], output_hash=o1, parent=None,
    )
    e2 = _sign_with_manifest_hash(
        ident_b, manifest_hash=mh_b, intent_id=INTENT, action_id="act-2",
        input_hashes=[o1], output_hash=o2, parent=e1,
    )

    report = generate_chain_report([e1, e2], reg, store)
    assert "ICP CHAIN VERIFICATION REPORT" in report
    assert "Chain length: 2 hops across 2 compositors" in report
    assert comp_a.pubkey_hex[:16] in report
    assert comp_b.pubkey_hex[:16] in report
    assert "[TRUSTED ✓]" in report
    assert "VALID ✓" in report
    assert "Full chain root:" in report


def test_chain_report_marks_untrusted_hop(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))

    comp_a, ident_a, manifest_a = _setup_compositor_and_agent(tmp_path, "UA")
    comp_b, ident_b, manifest_b = _setup_compositor_and_agent(tmp_path, "UB")
    # Only A trusted.
    reg.add_trusted_compositor(comp_a.pubkey_hex)

    mh_a = _store_manifest(store, manifest_a)
    mh_b = _store_manifest(store, manifest_b)
    in_h = _store_artifact(store, b"p")
    o1 = _store_artifact(store, b"o1")
    o2 = _store_artifact(store, b"o2")

    e1 = _sign_with_manifest_hash(
        ident_a, manifest_hash=mh_a, intent_id=INTENT, action_id="act-1",
        input_hashes=[in_h], output_hash=o1, parent=None,
    )
    e2 = _sign_with_manifest_hash(
        ident_b, manifest_hash=mh_b, intent_id=INTENT, action_id="act-2",
        input_hashes=[o1], output_hash=o2, parent=e1,
    )

    report = generate_chain_report([e1, e2], reg, store)
    assert "[UNTRUSTED ✗]" in report
    assert "BROKEN at hop 2" in report


def test_missing_manifest_in_artifact_store_fails(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))

    comp, ident, manifest = _setup_compositor_and_agent(tmp_path, "M")
    reg.add_trusted_compositor(comp.pubkey_hex)
    # Don't store manifest in artifact store; verification should fail at hop 0.
    fake_mh = blake3.blake3(b"some other bytes").hexdigest()
    in_h = _store_artifact(store, b"in")
    out_h = _store_artifact(store, b"out")

    e1 = _sign_with_manifest_hash(
        ident, manifest_hash=fake_mh, intent_id=INTENT, action_id="act-1",
        input_hashes=[in_h], output_hash=out_h, parent=None,
    )
    valid, idx, reason = verify_chain_multi_compositor([e1], reg, store)
    assert valid is False
    assert idx == 0
    assert "manifest" in reason.lower() and "not in artifact store" in reason
