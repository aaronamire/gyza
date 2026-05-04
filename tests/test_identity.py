from __future__ import annotations

import json
import os
import time
from pathlib import Path

import blake3
import pytest

from gyza.icp import verify_envelope
from gyza.identity import AgentIdentity, LocalCompositor


@pytest.fixture
def compositor(tmp_path) -> LocalCompositor:
    return LocalCompositor(key_path=str(tmp_path / "compositor.key"))


def _model_path(tmp_path: Path) -> str:
    p = tmp_path / "fake-model.gguf"
    p.write_bytes(b"FAKE-MODEL-WEIGHTS-FOR-TESTING")
    return str(p)


def test_master_seed_persists_and_pubkey_stable(tmp_path):
    key_path = str(tmp_path / "compositor.key")
    c1 = LocalCompositor(key_path=key_path)
    pk1 = c1.pubkey_hex

    # File created with 0600 perms.
    st = os.stat(key_path)
    assert st.st_size == 32
    assert (st.st_mode & 0o777) == 0o600

    # Re-instantiating reads the same seed → same pubkey.
    c2 = LocalCompositor(key_path=key_path)
    assert c2.pubkey_hex == pk1


def test_issue_agent_manifest_signature_valid(compositor, tmp_path):
    seed, manifest = compositor.issue_agent(
        agent_type="planner",
        model_path=_model_path(tmp_path),
        fs_read_paths=["/home/user/docs"],
        fs_write_paths=["/tmp/planner"],
        allowed_hosts=["api.anthropic.com"],
        spawn_permitted=[],
        attestation_tier=2,
    )
    assert len(seed) == 32
    assert compositor.verify_manifest(manifest) is True

    # Schema-shaped fields present.
    assert manifest["agent_id"] == manifest["agent_id"].lower()
    assert len(manifest["agent_id"]) == 64
    assert manifest["compositor_pubkey"] == compositor.pubkey_hex
    caps = manifest["capabilities"]
    assert caps["filesystem"]["read"] == ["/home/user/docs"]
    assert caps["filesystem"]["landlock_enforced"] is True
    assert caps["network"]["allowed_hosts"] == ["api.anthropic.com"]
    assert caps["spawn"]["resource_budget"]["memory_limit_mb"] == 512
    assert manifest["attestation_tier"] == 2
    assert manifest["parent_agent_id"] is None


def test_two_agents_different_pubkeys_both_verify(compositor, tmp_path):
    mp = _model_path(tmp_path)
    s1, m1 = compositor.issue_agent("planner", mp, ["/a"], ["/b"])
    s2, m2 = compositor.issue_agent("worker", mp, ["/c"], ["/d"])

    assert m1["agent_id"] != m2["agent_id"]
    assert s1 != s2
    assert m1["spawn_counter"] != m2["spawn_counter"]

    assert compositor.verify_manifest(m1) is True
    assert compositor.verify_manifest(m2) is True


def test_tampered_manifest_fails_verification(compositor, tmp_path):
    _seed, manifest = compositor.issue_agent(
        "planner", _model_path(tmp_path), ["/a"], ["/b"],
    )
    assert compositor.verify_manifest(manifest) is True

    # Mutating any field invalidates the compositor signature.
    manifest["capabilities"]["filesystem"]["write"].append("/etc")
    assert compositor.verify_manifest(manifest) is False


def test_revoke_agent_writes_signed_record(compositor, tmp_path):
    _seed, manifest = compositor.issue_agent(
        "planner", _model_path(tmp_path), ["/a"], ["/b"],
    )
    agent_id = manifest["agent_id"]

    record = compositor.revoke_agent(agent_id, reason="manifest leaked")
    assert record["agent_id"] == agent_id
    assert record["reason"] == "manifest leaked"
    assert record["compositor_pubkey"] == compositor.pubkey_hex
    assert compositor.verify_revocation(record) is True

    # File materialized at the documented path with restrictive perms.
    revoke_dir = Path(compositor._key_path.parent) / "revocations"
    out = revoke_dir / f"{agent_id}.json"
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk == record
    assert (os.stat(out).st_mode & 0o777) == 0o600

    # Tampering with the on-disk record breaks the signature.
    on_disk["reason"] = "tampered"
    assert compositor.verify_revocation(on_disk) is False


def test_agent_identity_constructs_and_signs(compositor, tmp_path):
    seed, manifest = compositor.issue_agent(
        "planner", _model_path(tmp_path), ["/a"], ["/b"],
    )
    ident = AgentIdentity(seed, manifest)

    assert ident.agent_id == manifest["agent_id"]
    assert ident.pubkey_hex == manifest["agent_id"]
    assert len(ident.manifest_hash) == 64

    msg = b"the quick brown fox"
    sig = ident.sign_bytes(msg)
    assert ident.verify_signature(msg, sig) is True
    assert ident.verify_signature(b"different bytes", sig) is False


def test_agent_identity_rejects_seed_manifest_mismatch(compositor, tmp_path):
    seed1, manifest1 = compositor.issue_agent(
        "planner", _model_path(tmp_path), ["/a"], ["/b"],
    )
    seed2, _manifest2 = compositor.issue_agent(
        "worker", _model_path(tmp_path), ["/c"], ["/d"],
    )
    with pytest.raises(ValueError, match="agent_id"):
        AgentIdentity(seed2, manifest1)


def test_get_icp_signer_round_trip(compositor, tmp_path):
    """Cross-test with icp.py: signer from identity produces verifiable envelopes."""
    seed, manifest = compositor.issue_agent(
        "planner", _model_path(tmp_path), ["/a"], ["/b"],
    )
    ident = AgentIdentity(seed, manifest)
    signer = ident.get_icp_signer()

    intent_id = "11111111-1111-4111-8111-111111111111"
    in_hash = blake3.blake3(b"input").hexdigest()
    out_hash = blake3.blake3(b"output").hexdigest()

    env = signer.sign_action(
        intent_id=intent_id,
        action_id="act-1",
        input_hashes=[in_hash],
        output_hash=out_hash,
        parent_envelope=None,
        inference_backend="mock",
        model_identifier="test",
        duration_ms=10,
        tokens_in=5,
        tokens_out=10,
    )

    # The envelope embeds the agent's identity and the manifest hash...
    assert env.agent_pubkey == ident.pubkey_hex
    assert env.capability_manifest_hash == ident.manifest_hash

    # ...and verifies under that same pubkey.
    assert verify_envelope(env, bytes.fromhex(env.agent_pubkey)) is True


def test_spawn_counter_persists_across_instances(tmp_path):
    key_path = str(tmp_path / "compositor.key")
    mp = _model_path(tmp_path)

    c1 = LocalCompositor(key_path=key_path)
    _, m1 = c1.issue_agent("planner", mp, ["/a"], ["/b"])
    _, m2 = c1.issue_agent("planner", mp, ["/a"], ["/b"])
    assert m1["spawn_counter"] == 0
    assert m2["spawn_counter"] == 1

    # Re-load: counter should resume where it left off.
    c2 = LocalCompositor(key_path=key_path)
    _, m3 = c2.issue_agent("planner", mp, ["/a"], ["/b"])
    assert m3["spawn_counter"] == 2


def test_api_model_hash_uses_identifier(compositor):
    """Non-existent path → hash of the identifier string itself."""
    _, manifest = compositor.issue_agent(
        "planner",
        model_path="claude-opus-4-7",
        fs_read_paths=[],
        fs_write_paths=[],
    )
    expected = blake3.blake3(b"claude-opus-4-7").hexdigest()
    assert manifest["model_hash"] == expected


def test_invalid_attestation_tier_rejected(compositor, tmp_path):
    with pytest.raises(ValueError, match="attestation_tier"):
        compositor.issue_agent(
            "planner", _model_path(tmp_path), [], [], attestation_tier=7,
        )


# Smoke check: spawn_time monotonically increases (even with the same
# counter logic, ns timestamps shouldn't go backwards within a process).
def test_spawn_time_monotonic(compositor, tmp_path):
    mp = _model_path(tmp_path)
    times = []
    for _ in range(3):
        _, m = compositor.issue_agent("planner", mp, [], [])
        times.append(m["spawn_time"])
        time.sleep(0.001)
    assert times == sorted(times)
