from __future__ import annotations

from dataclasses import replace

import blake3
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.icp import (
    ICPEnvelope,
    ICPSigner,
    compute_envelope_hash,
    explain_chain_failure,
    injection_breaks_chain,
    verify_chain,
    verify_envelope,
)


def _make_signer(seed_byte: int = 0x42) -> tuple[ICPSigner, bytes, bytes]:
    seed = bytes([seed_byte]) * 32
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pk_bytes = sk.public_key().public_bytes_raw()
    pk_hex = pk_bytes.hex()
    manifest_hash = blake3.blake3(b"manifest-v1").hexdigest()
    return ICPSigner(seed, pk_hex, manifest_hash), seed, pk_bytes


INTENT_ID = "11111111-1111-4111-8111-111111111111"


def _h(x: bytes) -> str:
    return blake3.blake3(x).hexdigest()


def test_single_envelope_sign_verify():
    signer, _seed, pk_bytes = _make_signer()
    env = signer.sign_action(
        intent_id=INTENT_ID,
        action_id="act-1",
        input_hashes=[_h(b"input-A")],
        output_hash=_h(b"output-1"),
        parent_envelope=None,
        inference_backend="mock",
        model_identifier="test-model-1",
        duration_ms=12,
        tokens_in=10,
        tokens_out=20,
    )
    assert env.signature
    assert verify_envelope(env, pk_bytes) is True


def test_two_hop_chain_verifies():
    signer, _seed, _pk = _make_signer()
    e1 = signer.sign_action(
        intent_id=INTENT_ID,
        action_id="act-1",
        input_hashes=[_h(b"input-A")],
        output_hash=_h(b"output-1"),
        parent_envelope=None,
        inference_backend="mock",
        model_identifier="m",
        duration_ms=5,
        tokens_in=1,
        tokens_out=2,
    )
    e2 = signer.sign_action(
        intent_id=INTENT_ID,
        action_id="act-2",
        input_hashes=[e1.output_hash],
        output_hash=_h(b"output-2"),
        parent_envelope=e1,
        inference_backend="mock",
        model_identifier="m",
        duration_ms=7,
        tokens_in=3,
        tokens_out=4,
    )
    assert e2.parent_envelope_hash == compute_envelope_hash(e1)

    valid, idx = verify_chain([e1, e2])
    assert valid is True
    assert idx == -1


def test_tampered_output_hash_breaks_chain():
    signer, _seed, _pk = _make_signer()
    e1 = signer.sign_action(
        INTENT_ID, "act-1", [_h(b"in")], _h(b"out1"), None,
        "mock", "m", 1, 1, 1,
    )
    e2 = signer.sign_action(
        INTENT_ID, "act-2", [e1.output_hash], _h(b"out2"), e1,
        "mock", "m", 1, 1, 1,
    )

    # Tamper with the FIRST envelope's output_hash. Its own signature
    # no longer matches the recomputed payload hash, so verify_chain
    # rejects at index 0.
    bad_e1 = replace(e1, output_hash=_h(b"FORGED"))
    valid, idx = verify_chain([bad_e1, e2])
    assert valid is False
    assert idx == 0


def test_tampered_middle_hop_detected():
    signer, _seed, _pk = _make_signer()
    e1 = signer.sign_action(
        INTENT_ID, "act-1", [_h(b"in")], _h(b"out1"), None,
        "mock", "m", 1, 1, 1,
    )
    e2 = signer.sign_action(
        INTENT_ID, "act-2", [e1.output_hash], _h(b"out2"), e1,
        "mock", "m", 1, 1, 1,
    )
    e3 = signer.sign_action(
        INTENT_ID, "act-3", [e2.output_hash], _h(b"out3"), e2,
        "mock", "m", 1, 1, 1,
    )

    # Mutate e2's output_hash. e2's own signature breaks at index 1.
    bad_e2 = replace(e2, output_hash=_h(b"TAMPERED"))
    valid, idx = verify_chain([e1, bad_e2, e3])
    assert valid is False
    assert idx == 1


def test_injection_breaks_chain():
    signer, _seed, _pk = _make_signer()
    e1 = signer.sign_action(
        INTENT_ID, "act-1", [_h(b"in")], _h(b"out1"), None,
        "mock", "m", 1, 1, 1,
    )
    e2 = signer.sign_action(
        INTENT_ID, "act-2", [e1.output_hash], _h(b"out2"), e1,
        "mock", "m", 1, 1, 1,
    )
    chain = [e1, e2]

    # Inject between e1 and e2.
    assert injection_breaks_chain(chain, 1) is True
    # Inject at the head.
    assert injection_breaks_chain(chain, 0) is True
    # Inject at the tail.
    assert injection_breaks_chain(chain, len(chain)) is True


def test_wrong_pubkey_rejects():
    signer, _seed, _pk = _make_signer(seed_byte=0x11)
    env = signer.sign_action(
        INTENT_ID, "act-1", [_h(b"in")], _h(b"out"), None,
        "mock", "m", 1, 1, 1,
    )
    other_pk = Ed25519PrivateKey.from_private_bytes(
        bytes([0x99]) * 32
    ).public_key().public_bytes_raw()
    assert verify_envelope(env, other_pk) is False


def test_signer_rejects_pubkey_mismatch():
    seed = bytes([0x33]) * 32
    wrong_pk_hex = "00" * 32
    with pytest.raises(ValueError, match="does not match"):
        ICPSigner(seed, wrong_pk_hex, "00" * 32)


def test_empty_input_hashes_rejected():
    signer, _seed, _pk = _make_signer()
    env = signer.sign_action(
        INTENT_ID, "act-1", [], _h(b"out"), None,
        "mock", "m", 1, 1, 1,
    )
    # Signature is valid in isolation, but verify_chain enforces
    # the "must have read something" rule.
    assert verify_envelope(env, bytes.fromhex(env.agent_pubkey)) is True
    valid, idx = verify_chain([env])
    assert valid is False
    assert idx == 0


def test_root_hop_must_have_null_parent():
    signer, _seed, _pk = _make_signer()
    env = signer.sign_action(
        INTENT_ID, "act-1", [_h(b"x")], _h(b"y"), None,
        "mock", "m", 1, 1, 1,
    )
    forged_root = replace(env, parent_envelope_hash="aa" * 32)
    valid, idx = verify_chain([forged_root])
    assert valid is False
    assert idx == 0


# ---------------------------------------------------------------------------
# Demo: print a real injection-detection trace. The assertion is just a
# smoke check; the value is in the captured stdout (run with `pytest -s`).
# ---------------------------------------------------------------------------

def test_injection_demo_trace(capsys):
    signer, _seed, _pk = _make_signer()
    e1 = signer.sign_action(
        INTENT_ID, "act-1",
        [_h(b"user-prompt")], _h(b"plan.json"), None,
        "anthropic", "claude-opus-4-7", 412, 350, 180,
    )
    e2 = signer.sign_action(
        INTENT_ID, "act-2",
        [e1.output_hash], _h(b"draft.md"), e1,
        "llama.cpp", "Llama-3.2-1B-Instruct-Q4_K_M", 154_000, 800, 1200,
    )
    e3 = signer.sign_action(
        INTENT_ID, "act-3",
        [e2.output_hash], _h(b"final.md"), e2,
        "anthropic", "claude-opus-4-7", 220, 1200, 600,
    )
    honest = [e1, e2, e3]

    valid, idx = verify_chain(honest)
    assert (valid, idx) == (True, -1)

    # Splice an envelope between hop 1 and hop 2 and verify.
    fake = ICPEnvelope(
        intent_id=INTENT_ID,
        action_id="act-attacker",
        agent_pubkey="cc" * 32,
        capability_manifest_hash="00" * 32,
        input_hashes=[_h(b"smuggled")],
        output_hash=_h(b"poisoned-context"),
        parent_envelope_hash=compute_envelope_hash(e1),
        timestamp_ns=0,
        inference_backend="mock",
        model_identifier="rogue",
        duration_ms=0,
        tokens_in=0,
        tokens_out=0,
        signature="ab" * 32,
    )
    tampered = [e1, fake, e2, e3]

    print()
    print("=" * 70)
    print("ICP CHAIN VERIFICATION TRACE — honest 3-hop chain")
    print("=" * 70)
    print(explain_chain_failure(honest))
    print()
    print("=" * 70)
    print("ICP CHAIN VERIFICATION TRACE — attacker injects at index 1")
    print("=" * 70)
    print(explain_chain_failure(tampered))
    print()

    # Sanity: the helper agrees that injection broke the chain.
    assert injection_breaks_chain(honest, 1) is True

    # capsys flushes on test exit; stdout will appear under `pytest -s`.
    captured = capsys.readouterr()
    assert "chain verified end-to-end" in captured.out
    assert "parent_envelope_hash mismatch" in captured.out or \
           "signature invalid" in captured.out
