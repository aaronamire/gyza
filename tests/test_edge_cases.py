"""
Phase 1 edge-case coverage.

Each of these maps to a concrete operational concern that the README
makes promises about — TTL expiry, executor-failure release semantics,
ICP chain shape rules, and graceful memory degradation when LanceDB
isn't available.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path

import blake3
import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.icp import (
    ICPEnvelope,
    compute_envelope_hash,
    sign_envelope,
    verify_chain,
)
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.runner import AgentRunner
from gyza.schema import EMBEDDING_DIM, WorkItem


def _intent(suffix: str) -> str:
    d = suffix
    return f"{d*8}-{d*4}-4{d*3}-8{d*3}-{d*12}"


def _goal_spec(intent_id: str) -> dict:
    return {
        "intent_id": intent_id,
        "natural_text": "test",
        "category": "system_task",
        "actions": [],
        "authorization": {
            "resources": [], "preview_required": False, "reversible": True,
        },
    }


def _normed(rng: np.random.Generator) -> np.ndarray:
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _work_item(
    lineage_root: str,
    embedding: np.ndarray,
    *,
    reward: float = 0.5,
    ttl_ns: int = 3600 * 1_000_000_000,
    created_at_ns: int | None = None,
) -> WorkItem:
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=lineage_root,
        parent_id=None,
        description="edge-case work",
        desc_embedding=embedding.astype(np.float32),
        reward=reward,
        reward_updated_ns=time.time_ns(),
        required_tier=0,
        input_hashes=[],
        output_spec={},
        streaming_ok=False,
        claimed_by=None,
        claimed_at_ns=None,
        claim_hlc_l=0,
        claim_hlc_c=0,
        claim_hlc_node="",
        completed_at_ns=None,
        output_hash=None,
        icp_envelope_hash=None,
        success=None,
        created_at_ns=created_at_ns if created_at_ns is not None else time.time_ns(),
        ttl_ns=ttl_ns,
    )


# ---------------------------------------------------------------------------
# Blackboard TTL
# ---------------------------------------------------------------------------

def test_get_unclaimed_excludes_expired_ttl(tmp_path):
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = bb.post_intent(_goal_spec(_intent("a")))
    rng = np.random.default_rng(0)

    fresh = _work_item(intent_id, _normed(rng), reward=0.6)
    # Created 10s ago with a 5s TTL → expired by 5s.
    expired = _work_item(
        intent_id, _normed(rng), reward=0.9,
        created_at_ns=time.time_ns() - 10 * 1_000_000_000,
        ttl_ns=5 * 1_000_000_000,
    )
    bb.post_work_item(fresh)
    bb.post_work_item(expired)

    rows = bb.get_unclaimed(min_reward=0.0, tier=3)
    ids = {w.id for w in rows}
    assert fresh.id in ids
    assert expired.id not in ids, "expired work item leaked into get_unclaimed"


def test_release_claim_restores_unclaimed_state(tmp_path):
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = bb.post_intent(_goal_spec(_intent("b")))
    w = _work_item(intent_id, _normed(np.random.default_rng(0)))
    bb.post_work_item(w)

    from gyza.schema import HLC
    hlc = HLC(node_id="test")
    assert bb.try_claim(w.id, "agent-X", hlc) is True

    # Item is now claimed.
    item = bb.get_by_lineage(intent_id)[0]
    assert item.claimed_by == "agent-X"

    # Release it.
    assert bb.release_claim(w.id) is True
    item = bb.get_by_lineage(intent_id)[0]
    assert item.claimed_by is None
    assert item.claimed_at_ns is None

    # Now it should be returned by get_unclaimed again.
    assert any(x.id == w.id for x in bb.get_unclaimed(0.0, 3))

    # Releasing an unclaimed item is a no-op (returns False).
    assert bb.release_claim(w.id) is False


# ---------------------------------------------------------------------------
# Runner: executor exception → claim released
# ---------------------------------------------------------------------------

def test_runner_executor_exception_releases_claim(tmp_path):
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = bb.post_intent(_goal_spec(_intent("c")))
    rng = np.random.default_rng(2)
    target = _normed(rng)
    w = _work_item(intent_id, target, reward=0.8)
    bb.post_work_item(w)

    compositor = LocalCompositor(key_path=str(tmp_path / "comp.key"))
    seed, manifest = compositor.issue_agent(
        "failing", "mock", [], [], attestation_tier=2,
    )
    ident = AgentIdentity(seed, manifest)
    mem = EpisodicMemory(ident.agent_id, db_path=str(tmp_path / "mem"))
    spec = SpecializationTracker(
        ident.agent_id, _normed(np.random.default_rng(99)),
        str(tmp_path / "spec.db"),
    )

    def boom(_p, _c):
        raise RuntimeError("inference exploded")

    runner = AgentRunner(
        identity=ident,
        blackboard=bb,
        memory=mem,
        specialization=spec,
        lsh=LSHIndex(seed=7),
        executor=boom,
        min_reward_threshold=0.0,
        min_similarity_threshold=-1.0,
        poll_interval_s=0.05,
    )
    runner.start()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if runner.completed_count >= 1:
            break
        time.sleep(0.05)
    runner.stop()

    item = bb.get_by_lineage(intent_id)[0]
    # Released, not completed:
    assert item.claimed_by is None
    assert item.completed_at_ns is None
    assert item.success is None

    # Episode written with success=False, drift updated.
    mem.flush()
    assert mem.episode_count() == 1
    assert spec.update_count == 1
    assert mem.success_rate() == 0.0


# ---------------------------------------------------------------------------
# ICP: empty input_hashes on non-first hop
# ---------------------------------------------------------------------------

def test_verify_chain_rejects_empty_input_hashes_on_non_first_hop():
    compositor = LocalCompositor(key_path=str(Path("/tmp") / f"icp-edge-{uuid.uuid4().hex}.key"))
    seed1, m1 = compositor.issue_agent("a1", "mock", [], [])
    seed2, m2 = compositor.issue_agent("a2", "mock", [], [])
    id1 = AgentIdentity(seed1, m1)
    id2 = AgentIdentity(seed2, m2)
    s1 = id1.get_icp_signer()
    s2 = id2.get_icp_signer()

    h = blake3.blake3(b"x").hexdigest()
    e1 = s1.sign_action(
        "11111111-1111-4111-8111-111111111111", "act-1",
        [h], h, None, "mock", "m", 1, 1, 1,
    )
    # Non-first hop with EMPTY input_hashes — should fail at index 1.
    e2_unsigned = ICPEnvelope(
        intent_id="11111111-1111-4111-8111-111111111111",
        action_id="act-2",
        agent_pubkey=id2.pubkey_hex,
        capability_manifest_hash=id2.manifest_hash,
        input_hashes=[],  # ← the violation
        output_hash=h,
        parent_envelope_hash=compute_envelope_hash(e1),
        timestamp_ns=time.time_ns(),
        inference_backend="mock",
        model_identifier="m",
        duration_ms=1,
        tokens_in=1,
        tokens_out=1,
    )
    e2 = sign_envelope(e2_unsigned, seed2)

    valid, idx = verify_chain([e1, e2])
    assert valid is False
    assert idx == 1


# ---------------------------------------------------------------------------
# Memory: LanceDB unavailable → graceful fallback
# ---------------------------------------------------------------------------

def test_memory_falls_back_to_sqlite_when_lance_unavailable(tmp_path, monkeypatch, capsys):
    """If LanceDB import (or initialization) blows up, EpisodicMemory must
    still construct and the runner must still be usable. We force the
    failure by patching the LanceDB backend to raise on construction."""
    import gyza.memory as mem_mod

    class _Boom:
        def __init__(self, *_a, **_kw):
            raise RuntimeError("lancedb wheel missing")

    monkeypatch.setattr(mem_mod, "_LanceBackend", _Boom)

    mem = mem_mod.EpisodicMemory(
        agent_id="fa" * 32, db_path=str(tmp_path / "mem"),
    )
    assert mem.backend == "sqlite"

    # Round-trip an episode through the fallback.
    from gyza.memory import Episode

    ep = Episode(
        episode_id=str(uuid.uuid7()),
        agent_id="fa" * 32,
        task_embedding=np.zeros(EMBEDDING_DIM, dtype=np.float32),
        intent_text="fallback test",
        input_hashes=[],
        output_hash="00" * 32,
        action_types=[],
        success=True,
        duration_ms=1,
        model_identifier="mock",
        icp_envelope_hash="00" * 32,
        timestamp_ns=time.time_ns(),
    )
    mem.write(ep)
    mem.flush()
    assert mem.episode_count() == 1


def test_runner_works_when_memory_is_sqlite_only(tmp_path, monkeypatch):
    """Smoke test: runner runs to completion with the SQLite-only
    memory backend (no episodic retrieval available)."""
    import gyza.memory as mem_mod

    class _Boom:
        def __init__(self, *_a, **_kw):
            raise RuntimeError("forced fallback")

    monkeypatch.setattr(mem_mod, "_LanceBackend", _Boom)

    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = bb.post_intent(_goal_spec(_intent("d")))
    rng = np.random.default_rng(7)
    target = _normed(rng)
    bb.post_work_item(_work_item(intent_id, target))

    compositor = LocalCompositor(key_path=str(tmp_path / "comp.key"))
    seed, manifest = compositor.issue_agent(
        "fb-runner", "mock", [], [], attestation_tier=2,
    )
    ident = AgentIdentity(seed, manifest)
    mem = mem_mod.EpisodicMemory(ident.agent_id, db_path=str(tmp_path / "mem"))
    assert mem.backend == "sqlite"
    spec = SpecializationTracker(
        ident.agent_id, _normed(np.random.default_rng(11)),
        str(tmp_path / "spec.db"),
    )

    def ok(_p, _c):
        return {"text": "fine", "tokens_in": 1, "tokens_out": 1,
                "model_identifier": "mock", "inference_backend": "mock"}

    runner = AgentRunner(
        identity=ident, blackboard=bb, memory=mem, specialization=spec,
        lsh=LSHIndex(seed=7), executor=ok,
        min_reward_threshold=0.0, min_similarity_threshold=-1.0,
        poll_interval_s=0.05,
    )
    runner.start()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        items = bb.get_by_lineage(intent_id)
        if items and items[0].completed_at_ns is not None:
            break
        time.sleep(0.05)
    runner.stop()

    item = bb.get_by_lineage(intent_id)[0]
    assert item.completed_at_ns is not None
    assert item.success is True


# ---------------------------------------------------------------------------
# Config & CLI smoke
# ---------------------------------------------------------------------------

def test_load_config_defaults_when_missing(tmp_path):
    from gyza.config import load_config

    cfg = load_config(str(tmp_path / "doesnt-exist.json"))
    assert cfg.default_model == "claude-sonnet-4-5"
    assert cfg.lsh_planes == 64


def test_load_config_overrides_from_json(tmp_path):
    import json as _json
    from gyza.config import load_config

    p = tmp_path / "cfg.json"
    p.write_text(_json.dumps({
        "default_model": "claude-opus-4-7",
        "poll_interval_s": 0.5,
        "lsh_planes": 64,  # honor the spec; just smoke-test override
    }))
    cfg = load_config(str(p))
    assert cfg.default_model == "claude-opus-4-7"
    assert cfg.poll_interval_s == 0.5


def test_cli_parser_builds():
    from gyza.cli import build_parser

    p = build_parser()
    args = p.parse_args(["init"])
    assert args.command == "init"
    args = p.parse_args(["demo", "injection"])
    assert args.command == "demo"
    assert args.scenario == "injection"
    args = p.parse_args(["demo", "global"])
    assert args.scenario == "global"
    args = p.parse_args(["status"])
    assert args.command == "status"
