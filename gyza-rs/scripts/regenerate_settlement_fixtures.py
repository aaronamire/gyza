#!/usr/bin/env python3
"""
Regenerate Rust parity-test fixtures for gyza-rs/gyza-settlement.

Mirrors the Rust `fixture_entry()` exactly so canonical-bytes
output is byte-comparable.

Usage:
    ~/dev/marshal/.os/bin/python gyza-rs/scripts/regenerate_settlement_fixtures.py

Paste the output hex strings into
`gyza-rs/gyza-settlement/src/lib.rs` test module's
`canonical_sign_bytes_parity_with_python` test.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import blake3
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.economy.ledger import LedgerEntry, canonical_sign_bytes


# Same TEST_MASTER as crypto + icp fixtures.
TEST_MASTER = bytes.fromhex(
    "0102030405060708090a0b0c0d0e0f10"
    "1112131415161718191a1b1c1d1e1f20"
)

# Different master seed for the payer side. Matches the Rust test's
# PAYER_MASTER constant.
PAYER_MASTER = bytes.fromhex(
    "feedfaceabad1deadeadbeef0badc0de"
    "cafef00d8badf00ddeadbeef13371337"
)


def _derive_seed(master: bytes, context: bytes, info: bytes) -> bytes:
    return blake3.blake3(context + b"|" + info, key=master).digest()


def _compositor_pubkey_hex(master: bytes) -> str:
    seed = _derive_seed(master, b"gyza.compositor.ed25519.v1", b"")
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    return sk.public_key().public_bytes_raw().hex()


def main() -> None:
    earner_pk_hex = _compositor_pubkey_hex(TEST_MASTER)
    payer_pk_hex = _compositor_pubkey_hex(PAYER_MASTER)

    entry = LedgerEntry(
        entry_id="entry-0001",
        from_compositor=payer_pk_hex,
        to_compositor=earner_pk_hex,
        amount_credits=0.5,
        work_item_id="work-0001",
        icp_envelope_hash="envhash-0001",
        model_identifier="mock-eval",
        tokens_out=100,
        duration_ms=500,
        created_at_ns=1_700_000_000_000_000_000,
    )

    print("# Paste these into gyza-rs/gyza-settlement/src/lib.rs::tests")
    print()
    print(f"earner_pubkey_hex = {earner_pk_hex}")
    print(f"payer_pubkey_hex  = {payer_pk_hex}")
    print()

    earner_digest = canonical_sign_bytes(entry, "earner")
    print(f"canonical_sign_bytes(entry, 'earner') = {earner_digest.hex()}")

    payer_digest = canonical_sign_bytes(entry, "payer")
    print(f"canonical_sign_bytes(entry, 'payer')  = {payer_digest.hex()}")


if __name__ == "__main__":
    main()
