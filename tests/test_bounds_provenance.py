"""The bytes in force must be the bytes that were signed.

THE DEFECT. `DEFAULT_BOUNDS_FILE` pointed at `guard_bounds.json` while
`guard_bounds.signed.json` sat beside it carrying a valid signature over
identical values. So the levels actually loaded came from a document the
signature DID NOT COVER, and editing the unsigned file was undetectable BY
CONSTRUCTION -- the signature protected something nothing read.

Switching the default was not a one-line change: `load_bounds_file` did
`data.get("bounds", data)`, which on a signed envelope returns the whole
wrapper, so it would have loaded NO BOUNDS while reporting success. Every class
would read UNDECLARED -- failing closed, but for the wrong reason.

`SIGNED_UNVERIFIED` is the fourth provenance state: signed bytes, no key
configured to check them. Untrusted, but a different condition from
UNSIGNED_FILE with a different remedy, and collapsing them would send an
operator to re-sign a document that is already signed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gyza.containment.engine import GuardEngine
from gyza.containment.gyza_model import (
    DEFAULT_BOUNDS_FILE,
    PLAIN_BOUNDS_FILE,
    build_registries,
)


def test_the_default_is_the_SIGNED_configuration():
    assert DEFAULT_BOUNDS_FILE.name == "guard_bounds.signed.json"
    assert DEFAULT_BOUNDS_FILE.exists()


def test_signed_and_plain_files_declare_IDENTICAL_levels():
    """The switch must change provenance only. If the values differed, this
    would silently alter what is enforced."""
    signed = json.loads(DEFAULT_BOUNDS_FILE.read_text())["config"]["bounds"]
    plain = json.loads(PLAIN_BOUNDS_FILE.read_text())["bounds"]
    assert signed == plain


def test_default_load_yields_SIGNED_UNVERIFIED_and_is_NOT_trusted():
    harm, inv = build_registries()
    r = GuardEngine(harm, inv).readiness()
    assert r["bounds_provenance"]["source"] == "SIGNED_UNVERIFIED"
    assert r["bounds_signed"] is False, "unverified must never read as signed"
    assert r["can_claim_containment"] is False


def test_the_envelope_actually_yields_BOUNDS_not_an_empty_model():
    """The trap in switching the default: a silently empty bounds set."""
    harm, _ = build_registries()
    assert harm.bound("H5_storage_growth") == 10_000_000_000.0
    assert harm.bound("H6_unsupervised_actions") == 10_000
    assert harm.bound("H4_authority") == 0.0


def test_a_plain_file_still_reports_UNSIGNED_FILE():
    """The two untrusted states stay DISTINCT -- different remedies."""
    harm, inv = build_registries(bounds_file=PLAIN_BOUNDS_FILE)
    r = GuardEngine(harm, inv).readiness()
    assert r["bounds_provenance"]["source"] == "UNSIGNED_FILE"
    assert r["bounds_signed"] is False


def test_TAMPERING_WITH_THE_SIGNED_FILE_IS_DETECTABLE(tmp_path):
    """THE POINT OF THE WHOLE CHANGE.

    Before, the signature covered a file nothing loaded, so editing the loaded
    file broke nothing checkable. Now the loaded bytes ARE the signed bytes, so
    a verifier holding the pubkey rejects a tampered configuration.
    """
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from gyza.containment.guardconfig import GuardConfigError, GuardConfigStore

    raw = Path.home().joinpath(".gyza/authority.key")
    if not raw.exists():
        pytest.skip("no local authority key to verify against")
    sk = Ed25519PrivateKey.from_private_bytes(raw.read_bytes()[:32])
    pub = sk.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)

    # untampered: verifies, and is TRUSTED
    harm, inv = build_registries(bounds_file=DEFAULT_BOUNDS_FILE,
                                 authority_pubkey=pub)
    r = GuardEngine(harm, inv).readiness()
    assert r["bounds_provenance"]["source"] == "SIGNED"
    assert r["bounds_signed"] is True

    # tampered: a raised bound with the ORIGINAL signature must be refused
    doc = json.loads(DEFAULT_BOUNDS_FILE.read_text())
    doc["config"]["bounds"]["H6_unsupervised_actions"] = 10_000_000
    bad = tmp_path / "tampered.signed.json"
    bad.write_text(json.dumps(doc))
    with pytest.raises((GuardConfigError, Exception)):
        GuardConfigStore(pub).load_file(bad)
