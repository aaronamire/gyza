"""Build attestation (S5 B2/B3).

SCOPE, asserted as a test rather than left to a docstring: nothing here claims
anything about CORRECTNESS. These tests check a binding between source bytes and
binary bytes, and the module says so.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from gyza.attest import (
    ATTESTATION_SCHEMA, AttestationSet, BuildAttestation, compute_artifact_hash,
    load_attestation_set, sign_attestation, verify_attestation,
)
from gyza.canon import failed, values_equal


def _att(artifact_hash="a" * 64, version="0.1.1", src="s" * 64, who="b1"):
    return BuildAttestation(
        schema=ATTESTATION_SCHEMA, version=version, source_tree_hash=src,
        artifact_hash=artifact_hash,
        toolchain={"python": "3.14.6", "pyinstaller": "6.21.0",
                   "PYTHONHASHSEED": "0"},
        builder_id=who, builder_pubkey="")


def _signed(**kw):
    return sign_attestation(_att(**kw), secrets.token_bytes(32))


# --------------------------------------------------------------------------- #
#  the artifact hash                                                           #
# --------------------------------------------------------------------------- #
def test_artifact_hash_covers_every_file_not_a_manifest(tmp_path):
    """The only non-determinism this build had lived in a nested bundle file;
    a manifest-level digest would have missed it."""
    a = tmp_path / "a"; (a / "_internal").mkdir(parents=True)
    (a / "gyza").write_bytes(b"ELF")
    (a / "_internal" / "base_library.zip").write_bytes(b"PK\x01")
    h1 = compute_artifact_hash(a)
    (a / "_internal" / "base_library.zip").write_bytes(b"PK\x02")
    assert compute_artifact_hash(a) != h1, "a nested byte change must change it"


def test_artifact_hash_is_order_independent_but_path_sensitive(tmp_path):
    a = tmp_path / "a"; a.mkdir(); (a / "x").write_bytes(b"1"); (a / "y").write_bytes(b"2")
    b = tmp_path / "b"; b.mkdir(); (b / "y").write_bytes(b"2"); (b / "x").write_bytes(b"1")
    assert values_equal(compute_artifact_hash(a), compute_artifact_hash(b))
    c = tmp_path / "c"; c.mkdir(); (c / "x").write_bytes(b"2"); (c / "y").write_bytes(b"1")
    assert compute_artifact_hash(c) != compute_artifact_hash(a), "content↔path swap"


def test_symlinks_are_hashed_by_target_not_followed(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    (a / "real").write_bytes(b"payload")
    (a / "link").symlink_to("real")
    h1 = compute_artifact_hash(a)
    (a / "link").unlink(); (a / "link").symlink_to("elsewhere")
    assert compute_artifact_hash(a) != h1, (
        "re-pointing a symlink must change the artifact hash, or a bundle "
        "could be altered without detection")


# --------------------------------------------------------------------------- #
#  signing                                                                     #
# --------------------------------------------------------------------------- #
def test_sign_and_verify_roundtrip():
    a = _signed()
    ok, why = verify_attestation(a)
    assert ok, why


def test_signature_does_not_sign_over_itself():
    a = _signed()
    assert "signature" not in a.payload()
    tampered = BuildAttestation(**{**a.__dict__, "artifact_hash": "f" * 64})
    ok, _ = verify_attestation(tampered)
    assert not ok, "changing the attested bytes must invalidate the signature"


def test_unsigned_and_unknown_schema_are_rejected():
    assert verify_attestation(_att())[0] is False
    a = _signed()
    bad = BuildAttestation(**{**a.__dict__, "schema": "something/9"})
    assert verify_attestation(bad)[0] is False


# --------------------------------------------------------------------------- #
#  N-of-M                                                                      #
# --------------------------------------------------------------------------- #
def test_agreement_is_on_the_artifact_hash_not_on_a_signature_count():
    """The protected quantity is WHICH BYTES were attested. Counting signatures
    without checking they attest the same bytes is the monotonicity-over-a-label
    error recorded three times in this program."""
    s = AttestationSet("0.1.1", "s" * 64, threshold=2, attestations=(
        _signed(artifact_hash="a" * 64, who="b1"),
        _signed(artifact_hash="b" * 64, who="b2"),   # DIFFERENT bytes
    ))
    ah, n, why = s.independent_agreement()
    assert ah is None
    assert "DISAGREE" in why and "majority vote" in why


def test_two_independent_signers_on_the_same_bytes_agree():
    s = AttestationSet("0.1.1", "s" * 64, threshold=2, attestations=(
        _signed(artifact_hash="a" * 64, who="b1"),
        _signed(artifact_hash="a" * 64, who="b2"),
    ))
    ah, n, why = s.independent_agreement()
    assert ah == "a" * 64 and n == 2 and why == ""


def test_the_same_signer_twice_is_not_two_signers():
    """Independence is per PUBKEY, not per attestation row."""
    one = _signed(artifact_hash="a" * 64, who="b1")
    dup = BuildAttestation(**{**one.__dict__, "builder_id": "b1-again"})
    s = AttestationSet("0.1.1", "s" * 64, threshold=2, attestations=(one, dup))
    ah, n, why = s.independent_agreement()
    assert ah is None and n == 1, (ah, n, why)


def test_threshold_one_is_flagged_as_degenerate():
    """ONE SIGNER IS A TRUSTED THIRD PARTY WITH EXTRA STEPS. True here is a
    disclosure, not an error."""
    s = AttestationSet("0.1.1", "s" * 64, threshold=1,
                       attestations=(_signed(),))
    assert s.is_degenerate
    assert not AttestationSet("0.1.1", "s" * 64, threshold=2,
                              attestations=(_signed(),)).is_degenerate


def test_attestations_for_a_different_source_do_not_count():
    s = AttestationSet("0.1.1", "s" * 64, threshold=1, attestations=(
        _signed(artifact_hash="a" * 64, src="OTHER" + "s" * 59),))
    ah, n, _ = s.independent_agreement()
    assert ah is None and n == 0


# --------------------------------------------------------------------------- #
#  loading — an error is not a value                                           #
# --------------------------------------------------------------------------- #
def test_an_unreadable_trust_file_is_a_Failure_not_an_empty_trust_set(tmp_path):
    bad = tmp_path / "x.json"; bad.write_text("{not json")
    r = load_attestation_set(bad)
    assert failed(r), "a broken trust file must not read as 'nobody attested'"
    with pytest.raises(Exception):
        bool(r)


def test_a_wellformed_set_loads(tmp_path):
    a = _signed()
    f = tmp_path / "s.json"
    f.write_text(json.dumps({
        "version": "0.1.1", "source_tree_hash": "s" * 64, "threshold": 2,
        "attestations": [a.__dict__]}))
    s = load_attestation_set(f)
    assert not failed(s) and s.threshold == 2
    assert verify_attestation(s.attestations[0])[0]


# --------------------------------------------------------------------------- #
#  B3 — the verify-side check, and its circularity                             #
# --------------------------------------------------------------------------- #
def test_binary_trust_has_three_distinct_verdicts(monkeypatch):
    """Source-trusted-but-no-binary is a WEAKER verdict, not a failure of the
    source check; one signer is a disclosure; below-threshold is a refusal."""
    from gyza import release

    src = "s" * 64
    monkeypatch.setattr(release, "TRUSTED_RELEASES", {
        "9.9.9": {"source_tree_hash": src},
        "9.9.8": {"source_tree_hash": src, "attestation_threshold": 1,
                  "artifact_hashes": {"a" * 64: {"independent_signers": 1}}},
        "9.9.7": {"source_tree_hash": src, "attestation_threshold": 2,
                  "artifact_hashes": {"a" * 64: {"independent_signers": 1}}},
        "9.9.6": {"source_tree_hash": src, "attestation_threshold": 2,
                  "artifact_hashes": {"a" * 64: {"independent_signers": 3}}},
    })

    ok, why = release.is_trusted_binary("9.9.9", src, "a" * 64)
    assert not ok and "self-reported" in why, why

    ok, why = release.is_trusted_binary("9.9.8", src, "a" * 64)
    assert ok and "trusted third party with extra steps" in why.lower(), why

    ok, why = release.is_trusted_binary("9.9.7", src, "a" * 64)
    assert not ok and "below this client" in why, why

    ok, why = release.is_trusted_binary("9.9.6", src, "a" * 64)
    assert ok and "3 independent rebuilders" in why, why

    ok, why = release.is_trusted_binary("9.9.6", src, "f" * 64)
    assert not ok and "not attested" in why, why


def test_binary_trust_never_passes_when_the_source_check_fails(monkeypatch):
    """B3 is strictly downstream of the source check; it must not rescue a
    source-tree mismatch."""
    from gyza import release

    monkeypatch.setattr(release, "TRUSTED_RELEASES", {
        "9.9.6": {"source_tree_hash": "s" * 64, "attestation_threshold": 1,
                  "artifact_hashes": {"a" * 64: {"independent_signers": 9}}}})
    ok, why = release.is_trusted_binary("9.9.6", "WRONG" + "s" * 59, "a" * 64)
    assert not ok and "source-tree" in why


def test_the_module_states_its_scope_and_does_not_claim_correctness():
    """Registering a disclaimer is not evidence it is present. Assert it."""
    src = Path("gyza/attest.py").read_text()
    assert "DOES NOT ADDRESS CORRECTNESS" in src
    assert "TRUSTED THIRD PARTY WITH EXTRA STEPS" in src
    rel = Path("gyza/release.py").read_text()
    assert "SELF-REPORTING AT A FINER GRAIN" in rel, (
        "B3's circularity must be stated where the function lives")
