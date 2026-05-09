"""
Phase 3 Session 8.5 — runtime ICP chain verification.

Before this session, ``verify_chain`` was implemented but never invoked
at runtime: the runner signed envelopes but didn't verify incoming
work items' lineages, so a malicious peer could publish a work item
whose chain pointed at fabricated history and the system had no
defense beyond the per-envelope signature check.

These tests cover the new pieces:

  1. Blackboard envelope log: store/get/get_for_action.
  2. Blackboard.reconstruct_chain: walks parent_id, returns chain
     or first-missing action_id.
  3. Runner.verify_chain_before_claim flag:
     - default ON → claims rejected when chain is invalid
     - strict_chain_verification ON → missing envelopes also reject
     - strict OFF → missing envelopes warn-and-proceed
  4. End-to-end: runner signs envelope, envelope hits the log,
     subsequent runner verifies it before claiming a child item.
"""
from __future__ import annotations

import secrets
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.icp import ICPEnvelope, compute_envelope_hash, sign_envelope
from gyza.identity import LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.runner import AgentRunner, make_mock_executor
from gyza.schema import EMBEDDING_DIM, WorkItem


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _make_compositor(tmp_path: Path, name: str) -> LocalCompositor:
    p = tmp_path / f"{name}.key"
    p.write_bytes(secrets.token_bytes(32))
    p.chmod(0o600)
    return LocalCompositor(str(p))


def _make_intent(bb: Blackboard, intent_id: str) -> str:
    bb.post_intent({
        "intent_id": intent_id,
        "natural_text": "test",
        "category": "system_task",
        "actions": [],
        "authorization": {
            "resources": [], "preview_required": False, "reversible": True,
        },
    })
    return intent_id


def _make_work_item(
    intent_id: str, *, parent_id: str | None = None, seed: int = 0,
) -> WorkItem:
    rng = np.random.default_rng(seed)
    emb = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    emb /= max(float(np.linalg.norm(emb)), 1e-9)
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=intent_id,
        parent_id=parent_id,
        description="chain verification test",
        desc_embedding=emb,
        reward=0.5,
        reward_updated_ns=time.time_ns(),
        required_tier=0,
        input_hashes=[],
        output_spec={},
        streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None,
        created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )


def _build_envelope(
    *,
    seed: bytes,
    pubkey_hex: str,
    intent_id: str,
    action_id: str,
    parent_envelope_hash: str | None = None,
    input_hash: str = "ab" * 32,
    output_hash: str = "cd" * 32,
) -> ICPEnvelope:
    """Build + sign an envelope. Caller controls all fields."""
    env = ICPEnvelope(
        intent_id=intent_id,
        action_id=action_id,
        agent_pubkey=pubkey_hex,
        capability_manifest_hash="ee" * 32,
        input_hashes=[input_hash],
        output_hash=output_hash,
        parent_envelope_hash=parent_envelope_hash,
        timestamp_ns=time.time_ns(),
        inference_backend="mock",
        model_identifier="mock",
        duration_ms=1, tokens_in=1, tokens_out=1,
    )
    return sign_envelope(env, seed)


# ----------------------------------------------------------------------
# Envelope log
# ----------------------------------------------------------------------

def test_store_and_get_envelope(tmp_path):
    bb = Blackboard(str(tmp_path / "bb.db"))
    seed = secrets.token_bytes(32)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    pk = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw().hex()

    env = _build_envelope(
        seed=seed, pubkey_hex=pk,
        intent_id="i1", action_id="a1",
    )
    h = bb.store_envelope(env)
    assert h == compute_envelope_hash(env)

    got = bb.get_envelope(h)
    assert got is not None
    assert got.action_id == "a1"
    assert got.agent_pubkey == pk

    # Idempotent: re-storing the same envelope is fine.
    h2 = bb.store_envelope(env)
    assert h2 == h


def test_get_envelope_for_action_returns_latest(tmp_path):
    """Two envelopes for the same action_id (a re-execution after
    release): get_envelope_for_action returns the one with the
    higher timestamp_ns."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    seed = secrets.token_bytes(32)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    pk = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw().hex()
    env_old = _build_envelope(seed=seed, pubkey_hex=pk, intent_id="i", action_id="a")
    time.sleep(0.001)  # ensure distinct timestamp_ns
    env_new = _build_envelope(
        seed=seed, pubkey_hex=pk, intent_id="i", action_id="a",
        output_hash="ff" * 32,
    )
    bb.store_envelope(env_old)
    bb.store_envelope(env_new)
    got = bb.get_envelope_for_action("a")
    assert got is not None
    assert got.output_hash == "ff" * 32


def test_reconstruct_chain_full(tmp_path):
    """A 3-step chain stored end-to-end. Reconstruction returns root → leaf."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    seed = secrets.token_bytes(32)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    pk = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw().hex()

    intent_id = _make_intent(bb, "intent-chain")

    # Three work items, parent-linked.
    w1 = _make_work_item(intent_id, parent_id=None, seed=1)
    w2 = _make_work_item(intent_id, parent_id=w1.id, seed=2)
    w3 = _make_work_item(intent_id, parent_id=w2.id, seed=3)
    bb.post_work_item(w1)
    bb.post_work_item(w2)
    bb.post_work_item(w3)

    # Three envelopes, parent-linked by hash.
    e1 = _build_envelope(
        seed=seed, pubkey_hex=pk,
        intent_id=intent_id, action_id=w1.id,
    )
    h1 = compute_envelope_hash(e1)
    e2 = _build_envelope(
        seed=seed, pubkey_hex=pk,
        intent_id=intent_id, action_id=w2.id,
        parent_envelope_hash=h1,
    )
    h2 = compute_envelope_hash(e2)
    e3 = _build_envelope(
        seed=seed, pubkey_hex=pk,
        intent_id=intent_id, action_id=w3.id,
        parent_envelope_hash=h2,
    )
    bb.store_envelope(e1)
    bb.store_envelope(e2)
    bb.store_envelope(e3)

    chain, missing = bb.reconstruct_chain(w3.id)
    assert missing == ""
    assert [e.action_id for e in chain] == [w1.id, w2.id, w3.id]


def test_reconstruct_chain_missing_envelope(tmp_path):
    """Two work items, but only the leaf has an envelope. The walker
    reports the missing ancestor's action_id."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    seed = secrets.token_bytes(32)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    pk = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw().hex()

    intent_id = _make_intent(bb, "intent-partial")
    w1 = _make_work_item(intent_id, parent_id=None, seed=1)
    w2 = _make_work_item(intent_id, parent_id=w1.id, seed=2)
    bb.post_work_item(w1)
    bb.post_work_item(w2)

    # Only store the LEAF envelope; the root w1 envelope is "missing
    # from the log" (e.g. completed by a remote node, not yet gossiped).
    e2 = _build_envelope(
        seed=seed, pubkey_hex=pk,
        intent_id=intent_id, action_id=w2.id,
        parent_envelope_hash="00" * 32,
    )
    bb.store_envelope(e2)

    chain, missing = bb.reconstruct_chain(w2.id)
    assert missing == w1.id
    # Partial chain returned (empty here because w1 was the first ancestor).
    assert chain == []


def test_reconstruct_chain_unknown_work_item(tmp_path):
    bb = Blackboard(str(tmp_path / "bb.db"))
    chain, missing = bb.reconstruct_chain("does-not-exist")
    assert chain == []
    assert missing == "does-not-exist"


# ----------------------------------------------------------------------
# Runner pre-claim verification
# ----------------------------------------------------------------------

def _build_runner(
    tmp_path: Path,
    bb: Blackboard,
    *,
    verify_chain_before_claim: bool = True,
    strict: bool = False,
) -> tuple[AgentRunner, str]:
    comp = _make_compositor(tmp_path, "runner")
    seed, manifest = comp.issue_agent(
        agent_type="test",
        model_path="mock",
        fs_read_paths=["/tmp"],
        fs_write_paths=["/tmp"],
        attestation_tier=0,
    )
    from gyza.identity import AgentIdentity
    ident = AgentIdentity(seed, manifest)
    mem = EpisodicMemory(agent_id=ident.agent_id, db_path=str(tmp_path / "mem"))
    spec_v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    spec_v[0] = 1.0
    spec = SpecializationTracker(
        agent_id=ident.agent_id,
        initial_embedding=spec_v,
        db_path=str(tmp_path / "spec.db"),
    )
    lsh = LSHIndex(seed=42)
    runner = AgentRunner(
        identity=ident, blackboard=bb, memory=mem, specialization=spec,
        lsh=lsh,
        executor=make_mock_executor("ok"),
        min_reward_threshold=0.0,
        # Accept negative cosine — these tests target the chain-verify
        # gate, not the scoring layer. With a one-hot spec and a random
        # work-item embedding, cosine can land below zero just by chance.
        min_similarity_threshold=-1.0,
        poll_interval_s=0.1,
        verify_chain_before_claim=verify_chain_before_claim,
        strict_chain_verification=strict,
    )
    return runner, ident.agent_id


def _mark_completed_externally(bb: Blackboard, w: WorkItem, env_hash: str) -> None:
    """Pretend ``w`` was claimed and completed by some other agent
    out-of-band, so the runner under test doesn't try to claim it
    itself. Used to isolate the chain-verify gate on a downstream
    item from any work the runner would do on the parent."""
    bb._conn().execute(
        """
        UPDATE work_items
        SET claimed_by = ?,
            claimed_at_ns = ?,
            completed_at_ns = ?,
            output_hash = ?,
            icp_envelope_hash = ?,
            success = 1
        WHERE id = ?
        """,
        (
            "external-agent",
            time.time_ns(),
            time.time_ns(),
            "ff" * 32,
            env_hash,
            w.id,
        ),
    )


def test_runner_verify_lineage_invalid_chain_skipped(tmp_path):
    """Plant a work item whose parent has a TAMPERED envelope (signature
    invalid). Runner with verify_chain_before_claim=True must skip it.
    The skip is observable: the item stays unclaimed.

    Test isolation: w1 is marked completed by an external agent so the
    runner only ever sees w2. Without this, the runner would
    legitimately complete w1 itself (root item, no chain to verify),
    overwriting the tampered envelope with a real one and the test
    would race-trivially-pass on a chain verification it didn't actually
    exercise.
    """
    bb = Blackboard(str(tmp_path / "bb.db"))

    seed = secrets.token_bytes(32)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    pk = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw().hex()
    intent_id = _make_intent(bb, "intent-tamper")
    w1 = _make_work_item(intent_id, parent_id=None, seed=1)
    bb.post_work_item(w1)
    env1 = _build_envelope(
        seed=seed, pubkey_hex=pk,
        intent_id=intent_id, action_id=w1.id,
    )
    # Tamper: corrupt the signature so verify_chain rejects.
    env1.signature = "00" * 64
    bb.store_envelope(env1)
    _mark_completed_externally(bb, w1, compute_envelope_hash(env1))

    # Child item references the tampered envelope's chain.
    w2 = _make_work_item(intent_id, parent_id=w1.id, seed=2)
    bb.post_work_item(w2)

    runner, _ = _build_runner(tmp_path, bb, verify_chain_before_claim=True)
    runner.start()
    try:
        time.sleep(1.5)  # several poll cycles
    finally:
        runner.stop()
    row = bb._conn().execute(
        "SELECT claimed_by FROM work_items WHERE id=?", (w2.id,),
    ).fetchone()
    assert row["claimed_by"] is None, (
        "runner claimed an item with a tampered ancestor chain"
    )


def test_runner_verify_lineage_strict_skips_missing(tmp_path):
    """Strict mode + missing ancestor envelope → skip claim. Like the
    tampered-chain test above, w1 is marked completed externally so
    the runner can't legitimately produce its envelope."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _make_intent(bb, "intent-missing")
    w1 = _make_work_item(intent_id, parent_id=None, seed=1)
    w2 = _make_work_item(intent_id, parent_id=w1.id, seed=2)
    bb.post_work_item(w1)
    bb.post_work_item(w2)
    _mark_completed_externally(bb, w1, env_hash="cc" * 32)
    # No envelope stored for w1 — that's the "missing" being tested.

    runner, _ = _build_runner(
        tmp_path, bb, verify_chain_before_claim=True, strict=True,
    )
    runner.start()
    try:
        time.sleep(1.5)
    finally:
        runner.stop()
    row = bb._conn().execute(
        "SELECT claimed_by FROM work_items WHERE id=?", (w2.id,),
    ).fetchone()
    assert row["claimed_by"] is None


def test_runner_verify_lineage_non_strict_proceeds_when_missing(tmp_path):
    """Non-strict mode + missing ancestor envelope → proceeds (warn-only).
    This is the cross-cluster default: peer's envelope hasn't gossiped
    yet, but we don't want to starve."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _make_intent(bb, "intent-missing-nonstrict")
    w1 = _make_work_item(intent_id, parent_id=None, seed=1)
    w2 = _make_work_item(intent_id, parent_id=w1.id, seed=2)
    bb.post_work_item(w1)
    bb.post_work_item(w2)

    runner, agent_id = _build_runner(
        tmp_path, bb, verify_chain_before_claim=True, strict=False,
    )
    runner.start()
    try:
        # Item should complete within several poll cycles. Generous
        # deadline because the EpisodicMemory's first call loads the
        # SentenceTransformer model when the singleton hasn't been
        # primed in this process — that's a one-time ~25s cost on cold
        # cache, plus the runner's internal poll cadence. 60s gives
        # safe headroom; in isolation this test runs in ~33s.
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            row = bb._conn().execute(
                "SELECT completed_at_ns FROM work_items WHERE id=?",
                (w2.id,),
            ).fetchone()
            if row["completed_at_ns"] is not None:
                break
            time.sleep(0.1)
    finally:
        runner.stop()
    row = bb._conn().execute(
        "SELECT claimed_by, completed_at_ns FROM work_items WHERE id=?",
        (w2.id,),
    ).fetchone()
    assert row["claimed_by"] == agent_id
    assert row["completed_at_ns"] is not None


def test_runner_persists_envelope_to_log(tmp_path):
    """After completing a work item, the runner's envelope is in the
    blackboard's log. Subsequent verify_lineage calls find it."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _make_intent(bb, "intent-persist")
    w = _make_work_item(intent_id, parent_id=None, seed=10)
    bb.post_work_item(w)

    runner, _ = _build_runner(tmp_path, bb)
    runner.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            row = bb._conn().execute(
                "SELECT completed_at_ns FROM work_items WHERE id=?", (w.id,),
            ).fetchone()
            if row["completed_at_ns"] is not None:
                break
            time.sleep(0.1)
    finally:
        runner.stop()

    env = bb.get_envelope_for_action(w.id)
    assert env is not None
    assert env.action_id == w.id
    assert env.intent_id == intent_id


def test_runner_root_item_has_no_chain_to_verify(tmp_path):
    """Items with parent_id=None have no chain to verify; the gate
    short-circuits and the runner claims normally."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _make_intent(bb, "intent-root")
    w = _make_work_item(intent_id, parent_id=None, seed=20)
    bb.post_work_item(w)

    runner, agent_id = _build_runner(
        tmp_path, bb, verify_chain_before_claim=True, strict=True,
    )
    runner.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            row = bb._conn().execute(
                "SELECT claimed_by FROM work_items WHERE id=?", (w.id,),
            ).fetchone()
            if row["claimed_by"] == agent_id:
                break
            time.sleep(0.1)
    finally:
        runner.stop()
    assert row["claimed_by"] == agent_id


def test_runner_full_chain_verifies_and_claim_proceeds(tmp_path):
    """Honest two-step chain: w1 completed by us (envelope in log),
    w2 references w1 as parent. Runner verifies and claims w2."""
    bb = Blackboard(str(tmp_path / "bb.db"))
    intent_id = _make_intent(bb, "intent-honest")
    w1 = _make_work_item(intent_id, parent_id=None, seed=1)
    bb.post_work_item(w1)

    # Complete w1 via the runner so its envelope hits the log.
    runner, agent_id = _build_runner(tmp_path, bb)
    runner.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            row = bb._conn().execute(
                "SELECT completed_at_ns FROM work_items WHERE id=?", (w1.id,),
            ).fetchone()
            if row["completed_at_ns"] is not None:
                break
            time.sleep(0.1)
        assert row["completed_at_ns"] is not None
    finally:
        runner.stop()

    # Post w2 referencing w1 as parent; new runner instance verifies + claims.
    w2 = _make_work_item(intent_id, parent_id=w1.id, seed=2)
    bb.post_work_item(w2)

    runner2, _ = _build_runner(tmp_path, bb, verify_chain_before_claim=True)
    runner2.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            row = bb._conn().execute(
                "SELECT completed_at_ns FROM work_items WHERE id=?", (w2.id,),
            ).fetchone()
            if row["completed_at_ns"] is not None:
                break
            time.sleep(0.1)
    finally:
        runner2.stop()
    assert row["completed_at_ns"] is not None, (
        "runner refused to claim a work item whose chain is honest"
    )


_ = pytest  # silence unused-import warning in static checkers
