"""
Tests for the gyza.embeddings module. These exercise:

  * StubEmbedder determinism + collision behavior
  * Embedder protocol compliance
  * default_embedder() resolution rules
  * Helper wrappers (embed_intent, embed_work_description)

We do NOT test SentenceTransformerEmbedder beyond import resolution
— it requires an 80MB model download and slow first-run inference,
which would gate every CI run on HuggingFace availability. The
production backend is exercised end-to-end in the demo
(``demo/single_machine_global.py``) and in any test that opts into
``GYZA_EMBEDDER=sentence-transformers`` explicitly.
"""
from __future__ import annotations

import numpy as np
import pytest

from gyza.embeddings import (
    Embedder,
    StubEmbedder,
    default_embedder,
    embed_intent,
    embed_work_description,
    reset_default_embedder,
)
from gyza.schema import EMBEDDING_DIM


# ----------------------------------------------------------------------
# StubEmbedder
# ----------------------------------------------------------------------

def test_stub_embedder_is_deterministic():
    """Same text → same vector. This is the contract that lets two
    test runs with the same fixtures produce the same output."""
    e = StubEmbedder()
    v1 = e.embed("hello world")
    v2 = e.embed("hello world")
    assert np.array_equal(v1, v2)


def test_stub_embedder_different_text_different_vectors():
    """Different texts → vectors that aren't byte-identical. We don't
    require they be far apart (uniform-random vectors collide rarely);
    only that the BLAKE3 path actually distinguishes them."""
    e = StubEmbedder()
    v1 = e.embed("the quick brown fox")
    v2 = e.embed("jumps over the lazy dog")
    assert not np.array_equal(v1, v2)


def test_stub_embedder_l2_normalized():
    """Cosine similarity collapses to dot product when vectors are
    L2-normalized. Routing code relies on ||v|| == 1."""
    e = StubEmbedder()
    for text in ["short", "a much longer sentence with several words", ""]:
        v = e.embed(text)
        # Empty text → zero vector → norm 0 (acceptable; the empty
        # text case is the operator's responsibility to filter).
        if text == "":
            continue
        assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5


def test_stub_embedder_shape_and_dtype():
    e = StubEmbedder()
    v = e.embed("test")
    assert v.shape == (EMBEDDING_DIM,)
    assert v.dtype == np.float32


def test_stub_embedder_batch_matches_per_item():
    e = StubEmbedder()
    texts = ["alpha", "beta", "gamma"]
    batch = e.embed_batch(texts)
    assert batch.shape == (3, EMBEDDING_DIM)
    for i, t in enumerate(texts):
        assert np.array_equal(batch[i], e.embed(t))


def test_stub_embedder_empty_batch():
    e = StubEmbedder()
    out = e.embed_batch([])
    assert out.shape == (0, EMBEDDING_DIM)
    assert out.dtype == np.float32


def test_stub_embedder_custom_dim():
    e = StubEmbedder(dim=128)
    v = e.embed("test")
    assert v.shape == (128,)
    assert e.dim == 128
    # model_id encodes the dim so two stubs with different dims aren't
    # mistaken for each other across the network.
    assert "dim=128" in e.model_id
    assert e.model_id != StubEmbedder(dim=384).model_id


def test_stub_embedder_rejects_non_positive_dim():
    with pytest.raises(ValueError):
        StubEmbedder(dim=0)
    with pytest.raises(ValueError):
        StubEmbedder(dim=-1)


def test_stub_embedder_satisfies_protocol():
    """Runtime-checkable protocol: isinstance(stub, Embedder) is True
    iff the stub has the right method signatures."""
    e = StubEmbedder()
    assert isinstance(e, Embedder)


def test_stub_model_id_stable_across_instances():
    a = StubEmbedder()
    b = StubEmbedder()
    assert a.model_id == b.model_id


# ----------------------------------------------------------------------
# default_embedder() resolution
# ----------------------------------------------------------------------

def test_default_embedder_respects_env_stub(monkeypatch):
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    reset_default_embedder()
    e = default_embedder()
    assert isinstance(e, StubEmbedder)


def test_default_embedder_singleton_within_process(monkeypatch):
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    reset_default_embedder()
    a = default_embedder()
    b = default_embedder()
    assert a is b, "default_embedder must return the same instance"


def test_default_embedder_reset(monkeypatch):
    """reset_default_embedder() drops the cache so subsequent calls
    re-resolve. Used by tests that toggle env vars."""
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    reset_default_embedder()
    a = default_embedder()
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    reset_default_embedder()
    b = default_embedder()
    assert a is not b


def test_default_embedder_unknown_value_falls_through(monkeypatch):
    """An unrecognized GYZA_EMBEDDER value should not crash; it should
    fall through to auto-detection (sentence-transformers if available,
    else stub)."""
    monkeypatch.setenv("GYZA_EMBEDDER", "totally-fake")
    reset_default_embedder()
    e = default_embedder()
    # Either backend is acceptable — we just need a working embedder.
    assert isinstance(e, Embedder)
    v = e.embed("smoke test")
    assert v.shape == (EMBEDDING_DIM,)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def test_embed_intent_uses_natural_text(monkeypatch):
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    reset_default_embedder()
    spec = {
        "intent_id": "test",
        "natural_text": "build a house",
        "category": "system_task",
    }
    v1 = embed_intent(spec)
    v2 = StubEmbedder().embed("build a house")
    assert np.array_equal(v1, v2)


def test_embed_intent_falls_back_to_description(monkeypatch):
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    reset_default_embedder()
    spec = {"intent_id": "test", "description": "alt text"}
    v1 = embed_intent(spec)
    v2 = StubEmbedder().embed("alt text")
    assert np.array_equal(v1, v2)


def test_embed_intent_falls_back_to_canonical_json(monkeypatch):
    """No natural_text or description → canonical JSON. Two specs that
    differ only in dict-iteration order produce the same vector."""
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    reset_default_embedder()
    spec_a = {"intent_id": "x", "category": "system_task", "actions": []}
    spec_b = {"actions": [], "category": "system_task", "intent_id": "x"}
    assert np.array_equal(embed_intent(spec_a), embed_intent(spec_b))


def test_embed_work_description_matches_direct_embedder(monkeypatch):
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    reset_default_embedder()
    text = "summarize the codebase"
    assert np.array_equal(
        embed_work_description(text),
        default_embedder().embed(text),
    )
