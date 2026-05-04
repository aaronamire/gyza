from __future__ import annotations

import time
import uuid

import numpy as np
import pytest

from gyza.memory import Episode, EpisodicMemory, build_enriched_prompt


AGENT_ID = "11" * 32  # 64-hex-char fake pubkey


def _ep(
    intent: str,
    embedding: np.ndarray,
    success: bool = True,
    actions=("QUERY",),
    duration_ms: int = 100,
    ts_ns: int | None = None,
) -> Episode:
    return Episode(
        episode_id=str(uuid.uuid7()),
        agent_id=AGENT_ID,
        task_embedding=embedding.astype(np.float32),
        intent_text=intent,
        input_hashes=["aa" * 32],
        output_hash="bb" * 32,
        action_types=list(actions),
        success=success,
        duration_ms=duration_ms,
        model_identifier="claude-opus-4-7",
        icp_envelope_hash="cc" * 32,
        timestamp_ns=ts_ns if ts_ns is not None else time.time_ns(),
    )


@pytest.fixture
def mem(tmp_path) -> EpisodicMemory:
    return EpisodicMemory(agent_id=AGENT_ID, db_path=str(tmp_path / "mem"))


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def test_retrieve_similar_returns_relevant_not_random(mem):
    file_tasks = [
        "list files in my downloads folder",
        "move the latest pdf to documents",
        "delete temporary files older than a week",
        "find duplicates in photos directory",
        "rename screenshots by date",
        "compress old logs",
        "search for unfinished drafts",
        "show disk usage of home directory",
        "archive last month's invoices",
        "split a large CSV into chunks",
    ]
    web_tasks = [
        "summarize the latest article on transformer attention",
        "fetch today's headlines from hacker news",
        "search arxiv for recent papers on RLHF",
        "translate this paragraph from french",
        "look up python's match statement docs",
        "scrape the release notes from a github repo",
        "compare prices for laptops on two retailers",
        "find a quote about resilience by stoics",
        "check the weather in Berlin tomorrow",
        "research best practices for SQLite WAL mode",
    ]

    for txt in file_tasks:
        # Synthesize a fake embedding directly so we don't need the real
        # SentenceTransformer model loaded for this test. We patch out
        # the encoder later for retrieval.
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0  # all file tasks point along axis 0
        mem.write(_ep(txt, v))
    for txt in web_tasks:
        v = np.zeros(384, dtype=np.float32)
        v[1] = 1.0  # all web tasks point along axis 1
        mem.write(_ep(txt, v))
    mem.flush()
    assert mem.episode_count() == 20

    # Inject our deterministic "encoder" so retrieval can reach the items
    # without actually downloading the sentence-transformers model.
    import gyza.memory as mem_mod
    monkey_emb = np.zeros((1, 384), dtype=np.float32)
    monkey_emb[0, 0] = 1.0  # query encodes onto file-task axis

    def fake_embed(_texts):
        return monkey_emb
    real_embed = mem_mod._embed
    mem_mod._embed = fake_embed
    try:
        results = mem.retrieve_similar(
            "show me my downloaded files",
            k=5,
            min_similarity=0.5,
            success_only=False,
        )
    finally:
        mem_mod._embed = real_embed

    assert len(results) > 0, "retrieval returned nothing"
    # Every returned result should be from the file-task cluster.
    for r in results:
        assert r.intent_text in file_tasks, (
            f"got web task {r.intent_text!r} as a 'file' result"
        )


def test_success_only_filters_failed(mem):
    # 5 successes, 5 failures, all on the same vector.
    v = np.zeros(384, dtype=np.float32)
    v[0] = 1.0
    for i in range(5):
        mem.write(_ep(f"good task {i}", v, success=True))
    for i in range(5):
        mem.write(_ep(f"bad task {i}", v, success=False))
    mem.flush()
    assert mem.episode_count() == 10
    # success_rate should be exactly 0.5.
    assert abs(mem.success_rate() - 0.5) < 1e-6

    import gyza.memory as mem_mod
    fake_q = np.zeros((1, 384), dtype=np.float32)
    fake_q[0, 0] = 1.0
    real_embed = mem_mod._embed
    mem_mod._embed = lambda _t: fake_q
    try:
        success_only = mem.retrieve_similar(
            "anything", k=10, min_similarity=0.5, success_only=True,
        )
        all_eps = mem.retrieve_similar(
            "anything", k=10, min_similarity=0.5, success_only=False,
        )
    finally:
        mem_mod._embed = real_embed

    assert len(success_only) == 5
    assert all(e.success for e in success_only)
    assert len(all_eps) == 10


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def test_format_as_few_shot_under_2000_chars(mem):
    v = np.zeros(384, dtype=np.float32)
    v[0] = 1.0
    eps: list[Episode] = []
    # Each block is ~120 chars; we generate 50 of them so the cap kicks in
    # well before all are included.
    for i in range(50):
        eps.append(_ep(
            f"task {i} — " + "x" * 80, v, success=(i % 2 == 0),
            actions=("QUERY", "WRITE"), duration_ms=42, ts_ns=10**9 + i,
        ))
    out = mem.format_as_few_shot(eps)
    assert len(out) <= 2000
    # Newest entries (highest ts) come first; the cap drops the oldest.
    assert "task 49" in out
    assert "task 0" not in out


def test_format_as_few_shot_shape():
    mem = None  # unused
    _ = mem  # noqa
    v = np.zeros(384, dtype=np.float32)
    v[0] = 1.0
    eps = [_ep("alpha task", v, success=True, actions=("QUERY",), duration_ms=10)]
    em = EpisodicMemory.__new__(EpisodicMemory)  # don't actually init
    out = EpisodicMemory.format_as_few_shot(em, eps)
    assert "# Past experience #1" in out
    assert "Task: alpha task" in out
    assert "Actions: QUERY" in out
    assert "Outcome: success" in out
    assert "Duration: 10ms" in out


# ---------------------------------------------------------------------------
# build_enriched_prompt
# ---------------------------------------------------------------------------

def test_build_enriched_prompt_includes_few_shot(mem):
    v = np.zeros(384, dtype=np.float32)
    v[0] = 1.0
    for i in range(3):
        mem.write(_ep(f"file task {i}", v, success=True))
    mem.flush()

    import gyza.memory as mem_mod
    fake_q = np.zeros((1, 384), dtype=np.float32)
    fake_q[0, 0] = 1.0
    real_embed = mem_mod._embed
    mem_mod._embed = lambda _t: fake_q
    try:
        enriched = build_enriched_prompt(
            base_prompt="Help me organize my files.",
            memory=mem,
            current_task="organize files",
            max_episodes=3,
        )
    finally:
        mem_mod._embed = real_embed

    assert "## Relevant past experience" in enriched
    assert "## Current task" in enriched
    assert "Help me organize my files." in enriched
    assert "# Past experience #1" in enriched


def test_build_enriched_prompt_no_episodes_returns_base(mem):
    import gyza.memory as mem_mod
    real_embed = mem_mod._embed
    mem_mod._embed = lambda _t: np.zeros((1, 384), dtype=np.float32)
    try:
        out = build_enriched_prompt("base prompt", mem, "anything")
    finally:
        mem_mod._embed = real_embed
    assert out == "base prompt"


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

def test_performance_100_writes_10_retrievals(mem):
    rng = np.random.default_rng(0)

    import gyza.memory as mem_mod
    real_embed = mem_mod._embed

    # Patch encoder to a deterministic, fast stub. The real all-MiniLM
    # model would dominate this microbench; the test is about storage +
    # retrieval throughput, not model cost.
    def fake_embed(texts):
        out = np.zeros((len(texts), 384), dtype=np.float32)
        for i, _ in enumerate(texts):
            out[i] = rng.standard_normal(384).astype(np.float32)
            out[i] /= np.linalg.norm(out[i])
        return out

    mem_mod._embed = fake_embed
    try:
        t0 = time.monotonic()
        for i in range(100):
            v = rng.standard_normal(384).astype(np.float32)
            v /= np.linalg.norm(v)
            mem.write(_ep(f"task {i}", v, success=(i % 3 != 0)))
        mem.flush()

        for _ in range(10):
            mem.retrieve_similar(
                "query", k=5, min_similarity=0.0, success_only=False,
            )
        elapsed = time.monotonic() - t0
    finally:
        mem_mod._embed = real_embed

    assert mem.episode_count() == 100
    assert elapsed < 5.0, f"100 writes + 10 retrievals took {elapsed:.2f}s"


def test_buffered_writes_flush_at_batch(mem):
    v = np.zeros(384, dtype=np.float32)
    v[0] = 1.0
    # 9 writes — buffered, not yet on disk
    for i in range(9):
        mem.write(_ep(f"t{i}", v))
    # 10th write triggers a flush
    mem.write(_ep("t9", v))
    assert mem.episode_count() == 10
