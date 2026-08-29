"""The fleet must COMPLETE work, not merely start.

I shipped `gyza serve` having verified only that it starts: three processes,
alive, clean shutdown. Verifying the claim I had actually made -- that it does
work -- found two defects in an hour, and neither was in the supervisor.

  * `EpisodicMemory` failed every item after the first few with "Table ...
    already exists", and because `_run_loop` releases the claim and continues,
    the agents looked ALIVE while completing NOTHING. A supervisor watching
    process liveness cannot see that, which is the general hazard: liveness is
    not progress.
  * The embedder contacted huggingface.co on every load, which is unmeasured
    egress from the RUNNER process (outside the sandbox, outside every H3
    producer) and fatal on a degraded link.

Both surfaced only under a long-running agent with PERSISTENT state -- the
deployment case -- and neither is reachable from a unit test that starts in an
empty directory.
"""
from __future__ import annotations

import os
import time
import uuid

import numpy as np
import pytest

from gyza.memory import Episode, EpisodicMemory


def _episode(i: int) -> Episode:
    v = np.zeros(384, dtype=np.float32)
    v[i % 384] = 1.0
    return Episode(
        episode_id=str(uuid.uuid7()), agent_id="fleet-test",
        task_embedding=v, intent_text=f"task {i}", input_hashes=[],
        output_hash="aa" * 32, action_types=[], success=True,
        duration_ms=1, model_identifier="mock",
        icp_envelope_hash="bb" * 32, timestamp_ns=time.time_ns())


def test_memory_SURVIVES_a_restart_over_the_same_directory(tmp_path):
    """The defect, as a long-running agent meets it.

    `_connect` decides whether to open the table from a `list_tables()`
    SNAPSHOT taken at construction. A second `EpisodicMemory` over the same
    path -- which is what a restarted agent is -- must not try to CREATE a
    table that already exists.
    """
    db = str(tmp_path / "mem")
    m1 = EpisodicMemory(agent_id="fleet-test", db_path=db)
    m1.write(_episode(0))
    m1.flush()

    m2 = EpisodicMemory(agent_id="fleet-test", db_path=db)
    m2.write(_episode(1))
    m2.flush()          # raised "Table ... already exists" before the fix

    m3 = EpisodicMemory(agent_id="fleet-test", db_path=db)
    for i in range(2, 6):
        m3.write(_episode(i))
    m3.flush()


def test_many_writes_in_ONE_session_all_land(tmp_path):
    """A runner writes one episode per completed item, so a failure on the Nth
    write is a fleet that stops working after N items while still looking
    alive."""
    m = EpisodicMemory(agent_id="fleet-test", db_path=str(tmp_path / "mem"))
    for i in range(12):
        m.write(_episode(i))
        m.flush()


# --------------------------------------------------------------------------- #
#  The embedder must not reach the network                                     #
# --------------------------------------------------------------------------- #
def test_the_embedder_loads_OFFLINE_by_default():
    """Three reasons, and only one of them is speed.

    It is unmeasured egress (the runner process is outside the sandbox and
    outside every H3 producer -- `egress_log` stayed EMPTY while three agents
    made HTTP requests to huggingface.co); it breaks DDIL, which is the
    deployment environment this system is built for; and it re-validates a file
    already on disk at a measured cost of 18.9 s against 7.7 s offline.
    """
    import inspect

    from gyza.embeddings import SentenceTransformerEmbedder

    src = inspect.getsource(SentenceTransformerEmbedder._ensure_model)
    assert "local_files_only" in src, (
        "the embedder no longer pins local_files_only; agents will contact "
        "huggingface.co at startup, unmeasured and fatal on a degraded link")
    assert "GYZA_EMBEDDER_ALLOW_DOWNLOAD" in src, (
        "downloading must remain an EXPLICIT opt-in, not a silent fallback")


def test_downloading_is_opt_in_and_the_refusal_NAMES_the_remedy(monkeypatch):
    """A refusal an operator cannot act on is an outage. The message must say
    which of the two situations they are in and what to run."""
    from gyza.embeddings import SentenceTransformerEmbedder

    monkeypatch.delenv("GYZA_EMBEDDER_ALLOW_DOWNLOAD", raising=False)
    e = SentenceTransformerEmbedder(model_name="gyza/definitely-not-a-model")
    with pytest.raises(RuntimeError, match="GYZA_EMBEDDER_ALLOW_DOWNLOAD"):
        e._ensure_model()


def test_the_opt_in_is_read_from_the_environment_not_hardcoded(monkeypatch):
    """If the flag were ignored, the first install could never fetch a model
    and the refusal above would be a permanent outage rather than a gate."""
    import inspect

    from gyza.embeddings import SentenceTransformerEmbedder

    src = inspect.getsource(SentenceTransformerEmbedder._ensure_model)
    assert 'os.environ.get(' in src and 'local_files_only=not allow_download' in src
