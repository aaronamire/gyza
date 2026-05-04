from __future__ import annotations

import os
from pathlib import Path

import blake3
import pytest

from gyza.network.artifact_store import ArtifactStore


def test_store_and_retrieve_roundtrip(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    data = b"hello world, this is artifact content"
    h = store.store(data)
    assert len(h) == 64
    assert h == blake3.blake3(data).hexdigest()
    got = store.get(h)
    assert got == data


def test_two_character_prefix_directory_structure(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    data = b"abc"
    h = store.store(data)
    expected_path = Path(tmp_path / "store" / h[:2] / h)
    assert expected_path.is_file()
    assert expected_path.read_bytes() == data


def test_tampered_file_detected_on_read_and_deleted(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    data = b"original content"
    h = store.store(data)
    # Mutate the on-disk content out from under the store.
    on_disk = tmp_path / "store" / h[:2] / h
    on_disk.write_bytes(b"TAMPERED!")

    got = store.get(h)
    assert got is None, "store returned tampered bytes"
    assert not on_disk.exists(), "corrupt file should have been deleted"


def test_atomic_write_no_partial_visibility(tmp_path, monkeypatch):
    """Tmp files are not visible as committed artifacts.

    Drive the failure: monkey-patch the rename step to raise, and verify
    no entry shows up in list_hashes()."""
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    data = b"never-fully-committed"
    h = blake3.blake3(data).hexdigest()

    def boom(*args, **kwargs):
        raise OSError("simulated rename failure")

    real_replace = os.replace
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.store(data)
    monkeypatch.setattr(os, "replace", real_replace)

    # The destination must not contain the artifact, and no orphan tmp
    # file should appear in list_hashes() (it's filtered by name).
    assert not store.exists(h)
    assert h not in store.list_hashes()


def test_exists_and_size(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    data = b"x" * 1234
    h = store.store(data)
    assert store.exists(h) is True
    assert store.size_bytes(h) == 1234
    assert store.exists("0" * 64) is False
    assert store.size_bytes("0" * 64) is None


def test_list_hashes_and_total_size(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    payloads = [b"alpha", b"beta", b"gamma" * 10]
    hashes = [store.store(p) for p in payloads]
    listed = set(store.list_hashes())
    assert listed == set(hashes)
    assert store.total_size_bytes() == sum(len(p) for p in payloads)


def test_duplicate_store_is_idempotent(tmp_path):
    store = ArtifactStore(base_path=str(tmp_path / "store"))
    data = b"same content twice"
    h1 = store.store(data)
    h2 = store.store(data)
    assert h1 == h2
    assert len(store.list_hashes()) == 1
