"""
Wire-level + verification tests for result_delivery.

The interesting property after brick-3+manifest: encode → wire →
decode → re-hash manifest → re-run enforcement_satisfies_manifest
yields the SAME predicate decision the runner made at sign time.
That round-trip is what makes the bounds-proof verifiable by a
submitter without trusting the runner.
"""
from __future__ import annotations

import json

import blake3

from gyza.icp import ICPEnvelope
from gyza.identity import _canon_bytes
from gyza.network.result_delivery import (
    decode_delivery,
    encode_delivery,
)
from gyza.sandbox import enforcement_satisfies_manifest


def _make_envelope(manifest_hash: str = "deadbeef" * 8) -> ICPEnvelope:
    return ICPEnvelope(
        intent_id="018abc00-0000-7000-8000-000000000000",
        action_id="018abc00-0000-7000-8000-000000000001",
        agent_pubkey="ab" * 32,
        capability_manifest_hash=manifest_hash,
        input_hashes=["11" * 32],
        output_hash="22" * 32,
        parent_envelope_hash=None,
        timestamp_ns=1_700_000_000_000_000_000,
        inference_backend="anthropic",
        model_identifier="claude-sonnet-4-5",
        duration_ms=100,
        tokens_in=10,
        tokens_out=20,
        signature="00" * 64,
    )


def _manifest_authorizing(ro: list[str], rw: list[str], hosts: list[str]) -> dict:
    return {
        "version": 1,
        "agent_id": "agent-1",
        "agent_type": "demo",
        "compositor_pubkey": "cc" * 32,
        "capabilities": {
            "filesystem": {"read": ro, "write": rw},
            "network": {"allowed_hosts": hosts},
        },
        "signature": "ff" * 64,
    }


# ----------------------------------------------------------------------
# Wire round-trip.
# ----------------------------------------------------------------------

def test_encode_decode_roundtrip_without_manifest_is_backcompat():
    env = _make_envelope()
    wire = encode_delivery(
        work_item_id=env.action_id,
        envelope=env,
        artifact_bytes=b'{"text":"hi"}',
    )
    # Old encoder shape — manifest_b64 not in JSON at all.
    parsed = json.loads(wire.decode())
    assert "manifest_b64" not in parsed

    rd = decode_delivery(wire)
    assert rd.work_item_id == env.action_id
    assert rd.envelope.signature == env.signature
    assert rd.artifact_bytes == b'{"text":"hi"}'
    assert rd.manifest_bytes is None


def test_encode_decode_roundtrip_with_manifest_is_preserved():
    manifest = _manifest_authorizing(["/tmp"], ["/tmp"], ["api.anthropic.com"])
    mbytes = _canon_bytes(manifest)
    env = _make_envelope(manifest_hash=blake3.blake3(mbytes).hexdigest())

    wire = encode_delivery(
        work_item_id=env.action_id,
        envelope=env,
        artifact_bytes=b'{"text":"hi"}',
        manifest_bytes=mbytes,
    )
    parsed = json.loads(wire.decode())
    assert isinstance(parsed["manifest_b64"], str)

    rd = decode_delivery(wire)
    assert rd.manifest_bytes == mbytes
    # The whole point: receiver's blake3 of the delivered bytes
    # equals the envelope's capability_manifest_hash.
    assert blake3.blake3(rd.manifest_bytes).hexdigest() == \
        env.capability_manifest_hash


def test_decode_rejects_malformed_manifest_b64():
    env = _make_envelope()
    base = json.loads(encode_delivery(
        work_item_id=env.action_id, envelope=env, artifact_bytes=b"x",
    ).decode())
    base["manifest_b64"] = "not!valid!base64!"
    import pytest
    with pytest.raises(ValueError, match="manifest_b64 not valid base64"):
        decode_delivery(json.dumps(base).encode())


def test_decode_rejects_manifest_b64_not_string():
    env = _make_envelope()
    base = json.loads(encode_delivery(
        work_item_id=env.action_id, envelope=env, artifact_bytes=b"x",
    ).decode())
    base["manifest_b64"] = 12345  # type: ignore[assignment]
    import pytest
    with pytest.raises(ValueError, match="manifest_b64 is not a string"):
        decode_delivery(json.dumps(base).encode())


# ----------------------------------------------------------------------
# End-to-end bounds-proof verification — the property the submitter
# actually relies on. encode_delivery → decode_delivery → submitter
# checks manifest_hash + runs enforcement_satisfies_manifest. The
# three cases below are the three branches gyza submit must handle.
# ----------------------------------------------------------------------

def test_submitter_can_independently_verify_in_bounds():
    """Happy path: bounds within manifest → verifier accepts."""
    manifest = _manifest_authorizing(
        ro=["/tmp", "/etc"], rw=["/tmp"],
        hosts=["api.anthropic.com"],
    )
    mbytes = _canon_bytes(manifest)
    env = _make_envelope(manifest_hash=blake3.blake3(mbytes).hexdigest())

    enf = {
        "backend": "bubblewrap",
        "ro_paths": ["/tmp"],         # tighter than manifest's /tmp+/etc
        "rw_paths": [],
        "requires_network": False,
    }
    wire = encode_delivery(
        work_item_id=env.action_id, envelope=env,
        artifact_bytes=json.dumps(
            {"text": "out", "__enforcement__": enf},
            sort_keys=True, separators=(",", ":"),
        ).encode(),
        manifest_bytes=mbytes,
    )
    rd = decode_delivery(wire)

    # Submitter's three checks:
    assert blake3.blake3(rd.manifest_bytes).hexdigest() \
        == env.capability_manifest_hash
    parsed = json.loads(rd.artifact_bytes.decode())
    ok, why = enforcement_satisfies_manifest(
        parsed["__enforcement__"], json.loads(rd.manifest_bytes.decode()),
    )
    assert ok, why


def test_submitter_detects_tampered_manifest_via_hash_mismatch():
    """Adversary swaps in a wider manifest after the fact → hash differs."""
    true_manifest = _manifest_authorizing(["/tmp"], ["/tmp"], ["api.anthropic.com"])
    true_mbytes = _canon_bytes(true_manifest)
    env = _make_envelope(
        manifest_hash=blake3.blake3(true_mbytes).hexdigest(),
    )

    # The executor (hostile) tries to ship a WIDER manifest to make
    # a wider enforcement record look in-bounds.
    wider_manifest = _manifest_authorizing(
        ["/tmp", "/etc", "/var"], ["/tmp"], ["api.anthropic.com"],
    )
    wider_mbytes = _canon_bytes(wider_manifest)

    wire = encode_delivery(
        work_item_id=env.action_id, envelope=env,
        artifact_bytes=b'{"text":"x"}',
        manifest_bytes=wider_mbytes,
    )
    rd = decode_delivery(wire)

    # Hash check FAILS — the envelope was signed against the original
    # manifest's hash; the swapped one has a different hash.
    assert blake3.blake3(rd.manifest_bytes).hexdigest() \
        != env.capability_manifest_hash


def test_submitter_detects_bounds_violation_when_delivered_unsoundly():
    """A rogue runner skipped the gate and signed a wider enforcement.
    Hash matches (manifest is real), but the predicate fails."""
    manifest = _manifest_authorizing(["/tmp"], ["/tmp"], ["api.anthropic.com"])
    mbytes = _canon_bytes(manifest)
    env = _make_envelope(manifest_hash=blake3.blake3(mbytes).hexdigest())

    rogue_enf = {
        "backend": "bubblewrap",
        "ro_paths": ["/tmp", "/etc"],   # wider than manifest's /tmp
        "rw_paths": [],
        "requires_network": False,
    }
    wire = encode_delivery(
        work_item_id=env.action_id, envelope=env,
        artifact_bytes=json.dumps(
            {"text": "x", "__enforcement__": rogue_enf},
            sort_keys=True, separators=(",", ":"),
        ).encode(),
        manifest_bytes=mbytes,
    )
    rd = decode_delivery(wire)
    assert blake3.blake3(rd.manifest_bytes).hexdigest() \
        == env.capability_manifest_hash   # the manifest IS authentic

    parsed = json.loads(rd.artifact_bytes.decode())
    ok, why = enforcement_satisfies_manifest(
        parsed["__enforcement__"], json.loads(rd.manifest_bytes.decode()),
    )
    assert not ok
    assert "beyond manifest" in why
