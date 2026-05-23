"""
Regenerate the byte-parity fixtures used in gyza-capability's Rust tests.

The Rust crate `gyza-capability` ports Python's
`gyza.network.capability_protocol` and asserts byte-for-byte parity of
canonical-JSON encodings against the Python output. Run this script
WHENEVER a payload field is added / renamed / re-ordered. Paste the
emitted hex strings into the corresponding test fixtures in
`gyza-rs/gyza-capability/src/lib.rs`.

NEVER hand-construct the expected hex — silent divergence at the
serialization layer is the entire failure mode this fixture defends
against. Generate, paste, run `cargo test -p gyza-capability`.

Run:
    ~/dev/marshal/.os/bin/python gyza-rs/scripts/regenerate_capability_fixtures.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import json
from dataclasses import asdict

from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
)

from gyza.network.capability_protocol import (  # noqa: E402
    CERT_SCHEMA,
    AttestationCert,
    AttestationCertPayload,
    Challenge,
    ValidatorCosig,
    _challenge_canonical_bytes,
    _payload_canonical_bytes,
    make_seed_signer,
)


def _print_hex(label: str, data: bytes) -> None:
    print(f"\n# {label}  ({len(data)} bytes)")
    # Wrap at 64 hex chars (32 bytes) for paste-readability into a
    # Rust string literal.
    hx = data.hex()
    width = 64
    for i in range(0, len(hx), width):
        print(hx[i : i + width])


def _print_json_block(label: str, text: str) -> None:
    print(f"\n# {label}")
    width = 80
    for i in range(0, len(text), width):
        print(text[i : i + width])


def main() -> int:
    # Fixture 1: ChallengePayload (the dataclass minus signature).
    # The Rust test constructs ChallengePayload from these exact field
    # values; keep the values here aligned with `sample_challenge_payload`
    # in gyza-rs/gyza-capability/src/lib.rs.
    challenge = Challenge(
        challenge_id="chal-0001",
        eval_version="eval-v1",
        task_ids=["t1", "t2", "t3"],
        nonce="00112233445566778899aabbccddeeff",
        issued_at_ns=1_700_000_000_000_000_000,
        expires_at_ns=1_700_000_300_000_000_000,
        validator_pubkey=(
            "abcd0000000000000000000000000000"
            "000000000000000000000000000000ef"
        ),
        # signature stays empty — _challenge_canonical_bytes pops it.
    )
    chal_bytes = _challenge_canonical_bytes(challenge)
    _print_hex("challenge_canonical_bytes", chal_bytes)

    # Fixture 2: AttestationCertPayload.
    payload = AttestationCertPayload(
        schema="gyza.attestation/1",
        applicant_compositor_pubkey=(
            "11220000000000000000000000000000"
            "000000000000000000000000000000ff"
        ),
        eval_version="eval-v1",
        issued_at_ns=1_700_000_000_000_000_000,
        expires_at_ns=1_700_001_000_000_000_000,
    )
    payload_bytes = _payload_canonical_bytes(payload)
    _print_hex("attestation_payload_canonical_bytes", payload_bytes)

    # ------------------------------------------------------------------
    # Fixture 3: a fully-signed AttestationCert, for the Rust
    # cross-language interop test of `verify_attestation_cert`.
    #
    # Three deterministic validator seeds → three Ed25519 keypairs →
    # each cosigns the canonical payload bytes. Rust deserializes the
    # JSON, calls verify_attestation_cert, and must accept it.
    # ------------------------------------------------------------------
    cert_payload = AttestationCertPayload(
        schema=CERT_SCHEMA,
        applicant_compositor_pubkey=("aa" * 32),
        eval_version="eval-v1",
        issued_at_ns=1_700_000_000_000_000_000,
        expires_at_ns=1_700_000_300_000_000_000,
    )
    cp_bytes = _payload_canonical_bytes(cert_payload)

    validator_seeds = [bytes([i + 1]) * 32 for i in range(3)]
    cosigs = []
    for i, seed in enumerate(validator_seeds):
        pk_hex = (
            Ed25519PrivateKey.from_private_bytes(seed)
            .public_key()
            .public_bytes_raw()
            .hex()
        )
        signer = make_seed_signer(seed)
        sig_hex = signer(cp_bytes)
        cosigs.append(
            ValidatorCosig(
                validator_pubkey=pk_hex,
                signature=sig_hex,
                cosigned_at_ns=1_700_000_100_000_000_000 + i,
            )
        )

    cert = AttestationCert(payload=cert_payload, validator_cosigs=cosigs)
    cert_json = json.dumps(asdict(cert), sort_keys=True, separators=(",", ":"))
    _print_json_block("signed_attestation_cert (JSON)", cert_json)

    # Hand-out: validator pubkeys, applicant pubkey, time bounds — the
    # Rust test asserts against these.
    print("\n# expected_applicant_pubkey  = " + cert_payload.applicant_compositor_pubkey)
    print(f"# issued_at_ns               = {cert_payload.issued_at_ns}")
    print(f"# expires_at_ns              = {cert_payload.expires_at_ns}")
    for i, c in enumerate(cert.validator_cosigs, start=1):
        print(f"# validator_pubkey[{i}]       = {c.validator_pubkey}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
