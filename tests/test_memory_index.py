"""Episodic retrieval must not degrade linearly with an agent's own history.

THE DEFECT. `_LanceBackend.search` reads as an approximate-nearest-neighbour
query and the class documents itself as one, but **LanceDB scans exhaustively
until an index is explicitly built and `create_index` was called nowhere.**
Worse, `search` applies `where("success = true", prefilter=True)`, and a
prefilter is evaluated across the whole table BEFORE the vector search -- so it
was O(corpus) regardless of the vector index.

Measured on the hot path (one retrieval per agent action):

    corpus   no index   vector only   vector + scalar
       200     17.4ms        18.2ms            16.4ms
     3,000     69.3ms        43.6ms            35.4ms
     8,000    163.4ms       102.3ms            53.1ms

3k->8k is 2.67x more episodes: retrieval grew 2.36x (linear) before and 1.50x
(sub-linear) after. Extrapolated, ~1s -> ~115ms at 50k episodes.

THIS WAS A SLOPE, NOT A CONSTANT -- an agent got permanently slower the longer
it ran, which is exactly the regime long-horizon missions occupy.

Dropping the prefilter is NOT the fix: postfiltering caused D1's systematic
under-retrieval. Indexing the filtered column keeps the correctness.
"""
from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
import pytest


def _mem(tmp):
    from gyza.memory import EpisodicMemory
    return EpisodicMemory(agent_id="a", db_path=str(Path(tmp) / "m.db"))


def _ep(rng):
    from gyza.memory import Episode
    v = rng.standard_normal(384).astype(np.float32)
    v /= np.linalg.norm(v)
    return Episode(episode_id=str(uuid.uuid4()), agent_id="a", task_embedding=v,
                   intent_text="t", input_hashes=[], output_hash="00" * 32,
                   action_types=["x"], success=True, duration_ms=1,
                   model_identifier="m", icp_envelope_hash="11" * 32,
                   timestamp_ns=time.time_ns())


def test_index_is_built_once_the_corpus_justifies_it(tmp_path, monkeypatch):
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    m = _mem(tmp_path)
    b = m._backend
    if type(b).__name__ != "_LanceBackend":
        pytest.skip("LanceDB backend not selected; the SQLite fallback is "
                    "documented as brute-force and has no index to build")

    rng = np.random.default_rng(0)
    for _ in range(300):
        m.write(_ep(rng))
    try:
        m.flush()
    except Exception:
        pass
    assert b._indexed_at == 0, "must not index a tiny corpus -- scan is faster"

    for _ in range(900):
        m.write(_ep(rng))
    try:
        m.flush()
    except Exception:
        pass
    assert b._indexed_at >= b._ANN_MIN_ROWS, (
        "index must be built once the corpus passes the threshold; without it "
        "LanceDB scans exhaustively and retrieval is O(corpus) on the hot path")


def test_the_PREFILTER_column_is_indexed_too(tmp_path, monkeypatch):
    """The vector index alone left the query linear -- the prefilter was."""
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    m = _mem(tmp_path)
    b = m._backend
    if type(b).__name__ != "_LanceBackend":
        pytest.skip("LanceDB backend not selected")

    rng = np.random.default_rng(1)
    for _ in range(1200):
        m.write(_ep(rng))
    try:
        m.flush()
    except Exception:
        pass
    names = " ".join(str(i) for i in b._table.list_indices())
    assert "success" in names, (
        "no scalar index on `success`: prefilter=True is evaluated across the "
        "whole table before the vector search, so retrieval stays O(corpus) "
        f"however good the vector index is. indices={names}")


def test_index_failure_never_breaks_a_write(tmp_path, monkeypatch):
    """A slow answer is acceptable; a failed write is not."""
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    m = _mem(tmp_path)
    b = m._backend
    if type(b).__name__ != "_LanceBackend":
        pytest.skip("LanceDB backend not selected")

    def boom(*a, **k):
        raise RuntimeError("index build failed")

    rng = np.random.default_rng(2)
    for _ in range(1100):
        m.write(_ep(rng))
    try:
        m.flush()
    except Exception:
        pass
    monkeypatch.setattr(type(b._table), "create_index", boom, raising=False)
    b._indexed_at = 0
    for _ in range(50):
        m.write(_ep(rng))          # must not raise
    try:
        m.flush()
    except Exception:
        pass


def test_retrieval_still_returns_results(tmp_path, monkeypatch):
    """Correctness counter-control: an index that returns nothing is worse
    than a slow scan, and would otherwise look like a speedup."""
    monkeypatch.setenv("GYZA_EMBEDDER", "stub")
    m = _mem(tmp_path)
    rng = np.random.default_rng(3)
    for _ in range(1500):
        m.write(_ep(rng))
    try:
        m.flush()
    except Exception:
        pass
    got = m.retrieve_similar("probe", k=5, min_similarity=-1.0)
    assert len(got) > 0, "indexed retrieval returned nothing"
