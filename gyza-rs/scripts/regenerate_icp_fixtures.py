#!/usr/bin/env python3
"""
Regenerate Rust parity-test fixtures for gyza-rs/gyza-icp.

Run after any change to ICPEnvelope semantics or _payload_bytes
canonicalization.

Usage:
    ~/dev/marshal/.os/bin/python gyza-rs/scripts/regenerate_icp_fixtures.py

Output: canonical bytes string + BLAKE3 hash + signature hex.
Paste into `gyza-rs/gyza-icp/src/lib.rs` test module.

The fixture envelope is a fixed-input envelope that mirrors what the
Rust test constructs. The Python `_payload_bytes(env)` output IS the
canonical-JSON byte string the Rust port must produce byte-identically.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import blake3
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.icp import ICPEnvelope, _payload_bytes, compute_envelope_hash, sign_envelope


# Same TEST_MASTER as the crypto fixtures.
TEST_MASTER = bytes.fromhex(
    "0102030405060708090a0b0c0d0e0f10"
    "1112131415161718191a1b1c1d1e1f20"
)


def _derive_seed(master: bytes, context: bytes, info: bytes) -> bytes:
    return blake3.blake3(context + b"|" + info, key=master).digest()


def fixture_envelope() -> ICPEnvelope:
    """Mirror of `fixture_payload()` in gyza-icp/src/lib.rs tests."""
    return ICPEnvelope(
        intent_id="int-0001",
        action_id="act-0001",
        agent_pubkey=(
            "08ed03d0cb5efe9152a79430ddd86a97286d760bdb5955fea3688e8bb9a13ab9"
        ),
        capability_manifest_hash=(
            "cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1cmh1"
        ),
        input_hashes=["i1", "i2"],
        output_hash=(
            "out1out1out1out1out1out1out1out1out1out1out1out1out1out1out1out1"
        ),
        parent_envelope_hash=None,
        timestamp_ns=1_700_000_000_000_000_000,
        inference_backend="local",
        model_identifier="mock-eval",
        duration_ms=42,
        tokens_in=10,
        tokens_out=20,
        schema_version=1,
    )


def fixture_envelope_hostile() -> ICPEnvelope:
    """The fixture the ASCII-only ones could never be.

    Every existing parity fixture uses ASCII-only, finite payloads, so it
    agreed under BOTH the pre-fix and post-fix Rust encoders and had no power
    to detect the ensure_ascii divergence (FINDINGS_SURVEY.md). This one
    carries, in a single envelope:

      * BMP non-ASCII        -- e-acute, escaped \u00e9
      * a combining mark     -- so NFC and NFD forms differ on the wire
      * an astral codepoint  -- escaped as a UTF-16 SURROGATE PAIR
      * DEL (U+007F)         -- ASCII, and escaped by Python; the case a
                                spec-derived "escape non-ASCII" misses
      * CJK, NBSP, an RTL mark
      * a solidus and a quote, which must NOT gain an escape
    """
    e = fixture_envelope()
    e.intent_id = "caf\u00e9/x\U0001F510y"          # BMP + solidus + astral
    e.action_id = "cafe\u0301"                       # NFD: e + combining acute
    e.model_identifier = "a\x7fb"                    # DEL
    e.inference_backend = "\u4e2d\u6587\u00a0\u200f"  # CJK + NBSP + RTL
    e.input_hashes = ["\u00e9", 'q"q', "plain"]      # non-ASCII + quote in a list
    return e


def main() -> None:
    env = fixture_envelope()

    print("# Paste these into gyza-rs/gyza-icp/src/lib.rs::tests")
    print()

    payload_bytes = _payload_bytes(env)
    print("canonical_bytes (UTF-8 decoded for readability):")
    print(f"  {payload_bytes.decode('utf-8')!r}")
    print()

    env_hash = compute_envelope_hash(env)
    print(f"envelope_hash = {env_hash}")
    print()

    # Sign with the compositor key derived from TEST_MASTER. This
    # matches the Rust test's `derive_seed(TEST_MASTER, ...)` path.
    compositor_seed = _derive_seed(
        TEST_MASTER, b"gyza.compositor.ed25519.v1", b"",
    )
    signed = sign_envelope(env, compositor_seed)
    print(f"signature = {signed.signature}")
    print()

    # Sanity: round-trip verification.
    from gyza.icp import verify_envelope
    sk = Ed25519PrivateKey.from_private_bytes(compositor_seed)
    pk = sk.public_key().public_bytes_raw()
    assert verify_envelope(signed, pk), "Python self-verify must succeed"
    print("[ok] Python self-verify passed")


if __name__ == "__main__":
    main()

    # ---- the hostile fixture (commit 3) -------------------------------
    h = fixture_envelope_hostile()
    hb = _payload_bytes(h)
    print()
    print("# ---- HOSTILE fixture: non-ASCII, astral, DEL, combining ----")
    print("# paste into gyza-icp/src/lib.rs::tests::fixture_payload_hostile")
    print(f"# canonical bytes ({len(hb)} bytes):")
    print(f'let expected = {json.dumps(hb.decode("ascii"))};')
    print(f'# envelope hash: {compute_envelope_hash(h)}')
