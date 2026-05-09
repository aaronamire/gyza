"""
Sentence-embedding API for Gyza.

This module is the single source of truth for "convert a text into a
384-dim vector that downstream code can compare with cosine similarity."
Before this module existed, callers fell into one of two camps:

  * ``gyza/memory.py`` loaded a SentenceTransformer privately and used
    it for episodic-memory retrieval — the only correct use.
  * Everywhere else (`cli.py:cmd_global_find`, every demo, every test,
    runner specialization initialization) used a seeded ``np.random``
    standard-normal vector. That made discovery, scoring, demand
    bucketing, and specialization tracking *all* operate on noise.

Why one module: cross-network discovery requires every node to map
the same text to the same vector. If node A uses MiniLM-L6-v2 and node
B uses BGE-small, their advertisements live in different LSH buckets
and they never find each other. Centralizing ensures one ``model_id``
across the network and lets us add negotiation later.

Backends
--------

``SentenceTransformerEmbedder``
    The production backend. Uses sentence-transformers, the same
    model as ``gyza.memory`` (all-MiniLM-L6-v2, 384-dim). ~80 MB
    download on first use to ``~/.cache/huggingface/``. Loads the
    model lazily so import is free; the cost is paid on the first
    ``embed()`` call. Safe to use the global singleton across threads
    — sentence-transformers is thread-safe for inference.

``StubEmbedder``
    Deterministic seeded-random embedder for tests and CI. Same text
    → same vector via BLAKE3-keyed PRNG. Different texts → different
    vectors with overwhelming probability. **Not semantically
    meaningful.** Use it only when retrieval quality is irrelevant
    (unit tests of routing logic, fixtures that need a stable vector).

Resolution rules
----------------

``default_embedder()`` picks based on, in order:
  1. ``GYZA_EMBEDDER`` env var (``stub`` | ``sentence-transformers``)
  2. sentence-transformers if importable
  3. ``StubEmbedder`` with a one-time warning

The fallback case is what tests on a stripped-down install hit. It
is intentionally fail-OPEN rather than fail-CLOSED so a missing
optional dep doesn't take the whole system down — but anyone running
``find_agents`` against a network of real users will get nonsense
results from a stub embedder, so the warning is loud.

Cross-network compatibility
---------------------------

The embedder's ``model_id`` is the canonical identifier. Two peers
must share the same ``model_id`` for their embeddings to be
comparable. Phase 3 hardcodes ``sentence-transformers/all-MiniLM-L6-v2``
on every node (no negotiation). Phase 4 will negotiate per-project
to support multiple embedding models in one network.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Protocol, runtime_checkable

import blake3
import numpy as np

from gyza.schema import EMBEDDING_DIM


LOG = logging.getLogger("gyza.embeddings")


# ---------------------------------------------------------------------------
# Embedder protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Embedder(Protocol):
    """The minimal embedder surface every backend must implement."""

    def embed(self, text: str) -> np.ndarray:
        """Return a (dim,) float32 vector. L2-normalized so cosine similarity
        is just a dot product. Empty / whitespace text is allowed; the
        backend decides what to return (typically a near-zero or model
        default vector)."""
        ...

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Return a (n, dim) float32 matrix. Faster than calling embed()
        N times for backends that batch under the hood."""
        ...

    @property
    def dim(self) -> int:
        ...

    @property
    def model_id(self) -> str:
        """Stable identifier used for cross-network compatibility.
        Two embedders with the same model_id MUST produce the same
        output for the same input (subject to floating-point determinism
        on the same hardware)."""
        ...


# ---------------------------------------------------------------------------
# Production backend — sentence-transformers
# ---------------------------------------------------------------------------

# Process-wide model cache. SentenceTransformer holds ~80MB of weights;
# loading per-agent or per-call would be wasteful. The lock guards the
# initial load; concurrent calls after init proceed without contention
# because sentence-transformers is thread-safe for inference.
_st_model_lock = threading.Lock()
_st_model_cache: dict[str, object] = {}


_DEFAULT_ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class SentenceTransformerEmbedder:
    """
    Backend wrapping sentence-transformers. Loads the model lazily so
    callers that never embed (e.g. importing the module for a CLI
    flag check) don't pay the 80 MB load.

    Threading: `encode` is safe to call from multiple threads on a
    single model instance. Multiple instances of this class with the
    same model_name share the underlying model via the cache.
    """

    def __init__(self, model_name: str = _DEFAULT_ST_MODEL):
        self._model_name = model_name
        # Hardcoded for the default model. If a caller specifies a
        # different model whose dim isn't 384, we'll detect mismatch
        # on first encode and raise.
        self._dim = EMBEDDING_DIM

    def _ensure_model(self):
        with _st_model_lock:
            cached = _st_model_cache.get(self._model_name)
            if cached is not None:
                return cached
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:  # pragma: no cover — guarded by factory
                raise ImportError(
                    "sentence-transformers is required for "
                    "SentenceTransformerEmbedder. "
                    "Install with: pip install sentence-transformers"
                ) from e
            model = SentenceTransformer(self._model_name)
            # API rename in sentence-transformers 5.x: prefer the new name
            # but tolerate older versions that only have the old method.
            get_dim = getattr(
                model, "get_embedding_dimension",
                getattr(model, "get_sentence_embedding_dimension", None),
            )
            actual_dim = get_dim() if callable(get_dim) else self._dim
            if actual_dim != self._dim:
                raise ValueError(
                    f"model {self._model_name!r} returns dim={actual_dim}; "
                    f"gyza.schema.EMBEDDING_DIM is {self._dim}. "
                    f"Use a model with matching output dimensionality "
                    f"or change EMBEDDING_DIM (which requires re-publishing "
                    f"every advertisement on the DHT)."
                )
            _st_model_cache[self._model_name] = model
            return model

    def embed(self, text: str) -> np.ndarray:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        model = self._ensure_model()
        # normalize_embeddings=True returns L2-normalized rows so
        # cosine == dot-product. show_progress_bar suppresses tqdm
        # output that pollutes scripts / CI.
        arr = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(arr, dtype=np.float32)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_id(self) -> str:
        return self._model_name


# ---------------------------------------------------------------------------
# Stub backend — deterministic, hermetic, semantically meaningless
# ---------------------------------------------------------------------------

class StubEmbedder:
    """
    Hash → seed → standard-normal → L2-normalize.

    Same text → same vector across runs / processes / machines. Different
    texts → different vectors with negligible collision probability for
    any reasonable corpus.

    Use cases:
      * Unit tests of routing/scoring code where the values just need to
        be stable.
      * CI environments where the SentenceTransformer model can't be
        downloaded.
      * Quick local experiments before paying the 80 MB model load.

    DO NOT use for production retrieval — vectors are uniformly random
    on the unit sphere, so cosine similarity between *related* texts is
    no higher than between unrelated ones (in expectation: zero).
    """

    def __init__(self, dim: int = EMBEDDING_DIM):
        if dim <= 0:
            raise ValueError(f"dim must be positive, got {dim}")
        self._dim = dim

    def embed(self, text: str) -> np.ndarray:
        # BLAKE3 → 8 bytes → uint64 seed. Stable across Python versions
        # because BLAKE3 is a fixed spec; numpy's PCG64 is also a fixed
        # spec. Using the first 8 bytes of a 32-byte digest discards
        # information but the seed space (2^64) is plenty for unique
        # vectors per test fixture.
        seed_bytes = blake3.blake3(text.encode("utf-8")).digest()[:8]
        seed = int.from_bytes(seed_bytes, "big")
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self._dim).astype(np.float32)
        n = float(np.linalg.norm(v))
        if n > 0:
            v /= n
        return v

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return np.stack([self.embed(t) for t in texts])

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_id(self) -> str:
        # Stable across processes; encodes the dim so two stubs with
        # different dims have different model_ids and can't be mistaken
        # for each other.
        return f"stub-blake3:dim={self._dim}"


# ---------------------------------------------------------------------------
# Factory + singleton
# ---------------------------------------------------------------------------

_default_embedder_lock = threading.Lock()
_default_embedder_singleton: Embedder | None = None
_warned_about_stub_fallback = False


def default_embedder() -> Embedder:
    """
    Return the process-wide default embedder.

    Resolution order:

      1. ``GYZA_EMBEDDER`` env var:
         * ``"stub"`` → :class:`StubEmbedder`
         * ``"sentence-transformers"`` → :class:`SentenceTransformerEmbedder`
         * other / unset → fall through

      2. sentence-transformers if importable (the production path)

      3. :class:`StubEmbedder` with a one-time warning

    The singleton means every caller in the process shares one model
    load. If you need a non-default embedder, instantiate the backend
    class directly — don't mutate this function's state.
    """
    global _default_embedder_singleton, _warned_about_stub_fallback
    with _default_embedder_lock:
        if _default_embedder_singleton is not None:
            return _default_embedder_singleton

        explicit = os.environ.get("GYZA_EMBEDDER", "").strip().lower()
        if explicit == "stub":
            _default_embedder_singleton = StubEmbedder()
        elif explicit in ("sentence-transformers", "st"):
            _default_embedder_singleton = SentenceTransformerEmbedder()
        else:
            # Auto-detect.
            try:
                import sentence_transformers  # noqa: F401
                _default_embedder_singleton = SentenceTransformerEmbedder()
            except ImportError:
                if not _warned_about_stub_fallback:
                    LOG.warning(
                        "sentence-transformers not installed; "
                        "falling back to StubEmbedder. Discovery and "
                        "specialization will not be semantically meaningful. "
                        "Install with: pip install sentence-transformers"
                    )
                    _warned_about_stub_fallback = True
                _default_embedder_singleton = StubEmbedder()
        return _default_embedder_singleton


def reset_default_embedder() -> None:
    """
    Drop the cached singleton. Tests that toggle ``GYZA_EMBEDDER``
    between cases call this so subsequent ``default_embedder()`` calls
    re-resolve. Production code never needs this.
    """
    global _default_embedder_singleton, _warned_about_stub_fallback
    with _default_embedder_lock:
        _default_embedder_singleton = None
        _warned_about_stub_fallback = False


# ---------------------------------------------------------------------------
# Helpers for common Gyza patterns
# ---------------------------------------------------------------------------

def embed_intent(goal_spec: dict) -> np.ndarray:
    """
    Embed an intent's natural-language description.

    Convention: ``goal_spec["natural_text"]`` carries the text. If
    absent, falls back to ``goal_spec["description"]``, then a
    canonicalized JSON of the spec (so the embedding is stable but
    semantically weak — fine for routing because it groups
    intent variants the user MEANT to be similar).
    """
    text = (
        goal_spec.get("natural_text")
        or goal_spec.get("description")
        or _canonical_text(goal_spec)
    )
    return default_embedder().embed(text)


def embed_work_description(description: str) -> np.ndarray:
    """Embed a WorkItem.description. Trivial wrapper kept for symmetry
    with embed_intent — single import for all "embed something" needs."""
    return default_embedder().embed(description)


def _canonical_text(d: dict) -> str:
    # JSON canonicalization for the fallback path. We avoid full
    # CBOR/etc.; goal_spec is already small and human-readable.
    import json
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


__all__ = [
    "Embedder",
    "SentenceTransformerEmbedder",
    "StubEmbedder",
    "default_embedder",
    "reset_default_embedder",
    "embed_intent",
    "embed_work_description",
]
