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
    is_trusted_release,
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


def test_unknown_release_is_not_trusted_with_dev_message():
    """No tagged releases yet → every build is honestly 'unverified',
    and the reason explains the bounds are still cryptographically
    checked (so the message reads correctly to a non-expert)."""
    ok, why = is_trusted_release("0.0.0-dev", "ff" * 32)
    assert ok is False
    assert "development build" in why
    assert "cryptographically" in why


def test_trusted_release_lookup_is_exact_tuple_match(monkeypatch):
    """When the trusted set is populated, membership is by the EXACT
    (version, hash) tuple — a matching version with a different tree
    hash (i.e. a tampered build claiming to be a release) is NOT
    trusted."""
    import gyza.release as rel

    good_hash = "a" * 64
    monkeypatch.setattr(
        rel, "TRUSTED_RELEASES",
        {("0.1.0", good_hash): {"released": "2026-06-01"}},
    )
    assert rel.is_trusted_release("0.1.0", good_hash)[0] is True
    # Same version, tampered tree.
    assert rel.is_trusted_release("0.1.0", "b" * 64)[0] is False
    # Right tree hash, wrong version label.
    assert rel.is_trusted_release("0.1.0-evil", good_hash)[0] is False


def test_injectivity_against_real_blake3_shape(tmp_path):
    """Sanity: the function actually produces a BLAKE3-shaped digest
    and is not accidentally returning a constant."""
    a = _tree(tmp_path / "a", {"x.py": b"A\n"})
    h = compute_source_tree_hash(a)
    assert h != blake3.blake3(b"").hexdigest()
    assert len(h) == 64
