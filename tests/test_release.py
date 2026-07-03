"""
Release-identity tests (G1a / ADR-0017).

The whole value of runner attestation rests on
``compute_source_tree_hash`` being a *deterministic, injective*
content hash. These tests pin the determinism contract: identical
trees → identical hash; any content/path change → different hash;
build detritus → no effect. If any of these break, the
trusted-release set silently stops meaning anything.
"""
from __future__ import annotations

from pathlib import Path

import blake3

from gyza import __version__
from gyza.release import (
    CURRENT_RELEASE,
    ReleaseIdentity,
    compute_source_tree_hash,
)


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def test_hash_is_deterministic_for_identical_trees(tmp_path):
    a = _tree(tmp_path / "a", {"x.py": b"print(1)\n", "pkg/y.py": b"Y=2\n"})
    b = _tree(tmp_path / "b", {"x.py": b"print(1)\n", "pkg/y.py": b"Y=2\n"})
    assert compute_source_tree_hash(a) == compute_source_tree_hash(b)


def test_hash_changes_on_content_change(tmp_path):
    a = _tree(tmp_path / "a", {"x.py": b"print(1)\n"})
    b = _tree(tmp_path / "b", {"x.py": b"print(2)\n"})
    assert compute_source_tree_hash(a) != compute_source_tree_hash(b)


def test_hash_changes_on_rename(tmp_path):
    """The relative path is part of the hashed wire — a rename with
    identical content must change the identity."""
    a = _tree(tmp_path / "a", {"x.py": b"S=1\n"})
    b = _tree(tmp_path / "b", {"y.py": b"S=1\n"})
    assert compute_source_tree_hash(a) != compute_source_tree_hash(b)


def test_hash_ignores_pycache_and_generated_protobuf(tmp_path):
    base = {"x.py": b"print(1)\n"}
    a = _tree(tmp_path / "a", base)
    b = _tree(tmp_path / "b", {
        **base,
        "__pycache__/x.cpython-314.pyc": b"\x00garbage",
        "pkg/__pycache__/y.cpython-314.pyc": b"\x00more",
        "network/proto/netd_pb2.py": b"# generated, varies by protoc\n",
        "network/proto/netd_pb2_grpc.py": b"# generated\n",
    })
    assert compute_source_tree_hash(a) == compute_source_tree_hash(b)


def test_hash_is_injective_under_concatenation_boundary(tmp_path):
    """Length-prefixing must prevent the classic ("ab","")/("a","b")
    collision. Two trees whose naive concatenation is identical must
    still hash differently."""
    a = _tree(tmp_path / "a", {"f.py": b"ab", "g.py": b""})
    b = _tree(tmp_path / "b", {"f.py": b"a", "g.py": b"b"})
    assert compute_source_tree_hash(a) != compute_source_tree_hash(b)


def test_non_py_files_do_not_affect_hash(tmp_path):
    """Only *.py participates — a README or data file alongside the
    source must not perturb the runner identity."""
    a = _tree(tmp_path / "a", {"x.py": b"print(1)\n"})
    b = _tree(tmp_path / "b", {"x.py": b"print(1)\n", "README.md": b"hi"})
    assert compute_source_tree_hash(a) == compute_source_tree_hash(b)


def test_current_release_is_well_formed():
    assert isinstance(CURRENT_RELEASE, ReleaseIdentity)
    assert CURRENT_RELEASE.version == __version__
    # 64 hex chars — BLAKE3-256.
    assert len(CURRENT_RELEASE.source_tree_hash) == 64
    int(CURRENT_RELEASE.source_tree_hash, 16)  # raises if not hex


def test_current_release_recomputes_to_same_value():
    """Computing the live package hash twice yields the same value —
    the gyza source tree on disk has not changed under us, and the
    function is pure."""
    again = compute_source_tree_hash()
    assert again == CURRENT_RELEASE.source_tree_hash


def test_release_identity_as_dict_shape():
    rid = ReleaseIdentity(version="9.9.9", source_tree_hash="ab" * 32)
    assert rid.as_dict() == {
        "runner_version": "9.9.9",
        "runner_source_tree_hash": "ab" * 32,
    }


def test_unknown_release_is_not_trusted_with_dev_message(monkeypatch):
    """Two honest negatives, each with a message that reads correctly to a
    non-expert. Against the real (now-populated) shipped set, an unknown dev
    build is reported as outside the trusted set. With NO releases published
    (empty set), every build is honestly 'unverified' and the reason explains
    the bounds are still cryptographically checked."""
    import gyza.release as rel

    # Real shipped set is non-empty (0.1.x cut): an unknown version is
    # outside the trusted set, not trusted.
    ok, why = rel.is_trusted_release("0.0.0-dev", "ff" * 32)
    assert ok is False
    assert "not in this client's trusted-release set" in why

    # Empty set (no releases published): the dev-build wording applies.
    monkeypatch.setattr(rel, "TRUSTED_RELEASES", {})
    ok, why = rel.is_trusted_release("0.0.0-dev", "ff" * 32)
    assert ok is False
    assert "development build" in why
    assert "cryptographically" in why


def test_trusted_release_lookup_is_exact_version_and_hash_match(monkeypatch):
    """Membership is keyed by version with exactly one canonical hash
    per version: a matching version with a different tree hash (a
    tampered build claiming to be a release) is NOT trusted, and the
    reason distinguishes 'unknown version' from 'tampered'."""
    import gyza.release as rel

    good_hash = "a" * 64
    monkeypatch.setattr(
        rel, "TRUSTED_RELEASES",
        {"0.1.0": {"source_tree_hash": good_hash, "released": "2026-06-01"}},
    )
    assert rel.is_trusted_release("0.1.0", good_hash) == (True, "")

    ok, why = rel.is_trusted_release("0.1.0", "b" * 64)
    assert ok is False
    assert "tampered or rebuilt" in why  # strongest negative

    ok, why = rel.is_trusted_release("0.9.9", good_hash)
    assert ok is False
    assert "not in this client's trusted-release set" in why


def test_trusted_releases_json_does_not_perturb_source_tree_hash(tmp_path):
    """THE fixed-point-dissolution property (ADR-0018). The trusted
    set lives in a non-.py file precisely so that writing a release's
    own hash into it cannot change the hash. A tree with an arbitrary
    trusted_releases.json must hash identically to one without it —
    otherwise pinning a release would be a non-convergent fixed point
    and `+ RUNNER ATTESTED` would be unreachable in principle."""
    base = {"release.py": b"# logic lives here\n", "pkg/x.py": b"X=1\n"}
    a = _tree(tmp_path / "a", base)
    b = _tree(tmp_path / "b", {
        **base,
        "trusted_releases.json": b'{"releases":{"0.1.0":{"source_tree_hash":"deadbeef"}}}',
    })
    # Mutating the JSON to a totally different policy must STILL not
    # move the hash.
    c = _tree(tmp_path / "c", {
        **base,
        "trusted_releases.json": b'{"releases":{"9.9.9":{"source_tree_hash":"ffff"}}}',
    })
    assert compute_source_tree_hash(a) == compute_source_tree_hash(b)
    assert compute_source_tree_hash(a) == compute_source_tree_hash(c)


def test_corrupt_or_missing_trusted_releases_fails_safe(tmp_path, monkeypatch):
    """Fail-safe direction: a missing / unparseable / malformed file
    yields an empty trust set (everything 'unverified'), NEVER
    fail-open (everything trusted)."""
    import gyza.release as rel

    # Missing file.
    monkeypatch.setattr(rel, "_trusted_releases_path",
                         lambda: tmp_path / "nope.json")
    assert rel._load_trusted_releases() == {}

    # Corrupt JSON.
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(rel, "_trusted_releases_path", lambda: bad)
    assert rel._load_trusted_releases() == {}

    # Well-formed JSON, wrong shape (releases not a dict).
    weird = tmp_path / "weird.json"
    weird.write_text('{"releases": [1,2,3]}', encoding="utf-8")
    monkeypatch.setattr(rel, "_trusted_releases_path", lambda: weird)
    assert rel._load_trusted_releases() == {}

    # Entry missing source_tree_hash is dropped (not trusted-by-omission).
    partial = tmp_path / "partial.json"
    partial.write_text('{"releases": {"0.1.0": {"notes": "no hash"}}}',
                        encoding="utf-8")
    monkeypatch.setattr(rel, "_trusted_releases_path", lambda: partial)
    assert rel._load_trusted_releases() == {}


def test_shipped_trusted_releases_json_pins_the_cut_releases():
    """The file that actually ships in the package must parse, and it pins
    exactly the releases cut so far (scripts/cut_release.py). This is a
    deliberate tripwire: when a release is added or removed, update the
    expected set below so the pin stays an honest record of what shipped."""
    import gyza.release as rel
    loaded = rel._load_trusted_releases()
    assert isinstance(loaded, dict)
    assert set(loaded) == {"0.1.0", "0.1.1"}, (
        "trusted_releases.json membership changed — a release was cut or "
        "removed. Update this tripwire to assert the new pinned set."
    )
    assert loaded["0.1.0"]["source_tree_hash"] == (
        "f307afe7dfc6f345cf2cffdba2774ae979bb8fa075a8a545bfa00f0ead004193"
    )
    assert loaded["0.1.1"]["source_tree_hash"] == (
        "328f7f0d8c1ead1c9d65039c477a4232d3cf7800c9945c82e90b63e5226d5bd4"
    )
    # Every pinned entry carries a 64-hex BLAKE3 tree hash.
    for entry in loaded.values():
        assert len(entry["source_tree_hash"]) == 64
        int(entry["source_tree_hash"], 16)  # raises if not hex


def test_injectivity_against_real_blake3_shape(tmp_path):
    """Sanity: the function actually produces a BLAKE3-shaped digest
    and is not accidentally returning a constant."""
    a = _tree(tmp_path / "a", {"x.py": b"A\n"})
    h = compute_source_tree_hash(a)
    assert h != blake3.blake3(b"").hexdigest()
    assert len(h) == 64
