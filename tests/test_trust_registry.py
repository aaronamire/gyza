from __future__ import annotations

import json
from pathlib import Path

import blake3
import pytest

from gyza.identity import LocalCompositor
from gyza.network.trust_registry import TrustRegistry


def _issue_manifest(tmp_path, label: str) -> tuple[str, dict]:
    """Mint a real compositor + agent manifest and return (compositor_pubkey,
    manifest). Manifest's signature is valid against compositor_pubkey."""
    compositor = LocalCompositor(key_path=str(tmp_path / f"comp-{label}.key"))
    _seed, manifest = compositor.issue_agent(
        agent_type=label, model_path="mock",
        fs_read_paths=[], fs_write_paths=[], attestation_tier=1,
    )
    return compositor.pubkey_hex, manifest


def test_add_compositor_then_is_trusted(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    pk = "11" * 32
    assert reg.is_trusted(pk) is False
    reg.add_trusted_compositor(pk, peer_ip="192.168.1.5", gyza_version="0.2.0")
    assert reg.is_trusted(pk) is True


def test_add_invalid_pubkey_rejected(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    with pytest.raises(ValueError):
        reg.add_trusted_compositor("not-hex")
    with pytest.raises(ValueError):
        reg.add_trusted_compositor("aa" * 16)  # 16 bytes, not 32


def test_verify_valid_manifest_from_trusted_compositor(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    comp_pk, manifest = _issue_manifest(tmp_path, "x")
    reg.add_trusted_compositor(comp_pk)
    ok, reason = reg.verify_manifest_from_trusted_compositor(manifest)
    assert ok is True, f"expected ok, got {reason}"
    assert reason == "ok"


def test_verify_manifest_from_untrusted_compositor_fails(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    _comp_pk, manifest = _issue_manifest(tmp_path, "y")
    # Don't add the compositor — should be untrusted.
    ok, reason = reg.verify_manifest_from_trusted_compositor(manifest)
    assert ok is False
    assert "not trusted" in reason


def test_tampered_manifest_signature_fails(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    comp_pk, manifest = _issue_manifest(tmp_path, "z")
    reg.add_trusted_compositor(comp_pk)
    # Mutate a field after signing — original signature no longer matches.
    manifest["capabilities"]["filesystem"]["write"].append("/etc")
    ok, reason = reg.verify_manifest_from_trusted_compositor(manifest)
    assert ok is False
    assert "signature" in reason.lower()


def test_revoked_compositor_manifests_fail(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    comp_pk, manifest = _issue_manifest(tmp_path, "rev")
    reg.add_trusted_compositor(comp_pk)
    assert reg.verify_manifest_from_trusted_compositor(manifest)[0] is True

    reg.revoke_compositor(comp_pk, reason="key leaked")
    assert reg.is_trusted(comp_pk) is False
    ok, reason = reg.verify_manifest_from_trusted_compositor(manifest)
    assert ok is False
    assert "not trusted" in reason


def test_unrevoke_via_re_add(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    comp_pk, manifest = _issue_manifest(tmp_path, "rev2")
    reg.add_trusted_compositor(comp_pk)
    reg.revoke_compositor(comp_pk, reason="precaution")
    assert reg.is_trusted(comp_pk) is False
    # Re-adding clears the revocation flag.
    reg.add_trusted_compositor(comp_pk)
    assert reg.is_trusted(comp_pk) is True
    ok, _ = reg.verify_manifest_from_trusted_compositor(manifest)
    assert ok is True


def test_cache_manifest_roundtrip(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    comp_pk, manifest = _issue_manifest(tmp_path, "c")
    reg.add_trusted_compositor(comp_pk)

    reg.cache_manifest(manifest)
    expected_hash = blake3.blake3(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()
    cached = reg.get_cached_manifest(expected_hash)
    assert cached is not None
    assert cached["agent_id"] == manifest["agent_id"]
    assert cached["compositor_pubkey"] == comp_pk


def test_get_cached_manifest_missing_returns_none(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    assert reg.get_cached_manifest("00" * 32) is None


def test_list_trusted_excludes_revoked(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    pk1 = "11" * 32
    pk2 = "22" * 32
    pk3 = "33" * 32
    for p in (pk1, pk2, pk3):
        reg.add_trusted_compositor(p)
    reg.revoke_compositor(pk2, reason="x")
    listed = {r["pubkey"] for r in reg.list_trusted()}
    assert listed == {pk1, pk3}


def test_missing_compositor_pubkey_field(tmp_path):
    reg = TrustRegistry(db_path=str(tmp_path / "trust.db"))
    ok, reason = reg.verify_manifest_from_trusted_compositor({})
    assert ok is False
    assert "missing" in reason
