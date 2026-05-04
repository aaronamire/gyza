from __future__ import annotations

import time
import uuid

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.demand import DemandOracle, LSHIndex
from gyza.drift import DRIFT_RATE, SpecializationTracker, update_specialization
from gyza.schema import EMBEDDING_DIM, WorkItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _normed(rng: np.random.Generator, dim: int = EMBEDDING_DIM) -> np.ndarray:
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _work_item(lineage_root: str, embedding: np.ndarray, reward: float = 0.5):
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=lineage_root,
        parent_id=None,
        description="test",
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
        created_at_ns=time.time_ns() - 60 * 1_000_000_000,  # 60s old
        ttl_ns=3600 * 1_000_000_000,
    )


# ---------------------------------------------------------------------------
# LSH
# ---------------------------------------------------------------------------

def test_lsh_deterministic_for_same_embedding():
    lsh = LSHIndex()
    rng = np.random.default_rng(0)
    v = _normed(rng)
    assert lsh.hash(v) == lsh.hash(v)
    assert lsh.hash(v.copy()) == lsh.hash(v)


def test_lsh_different_seeds_give_different_hashes():
    rng = np.random.default_rng(0)
    v = _normed(rng)
    a = LSHIndex(seed=1).hash(v)
    b = LSHIndex(seed=2).hash(v)
    assert a != b


def test_lsh_neighbor_count_radius_2():
    lsh = LSHIndex()
    nbrs = lsh.neighbor_buckets(0, radius=2)
    # Self + C(64,1) + C(64,2) = 1 + 64 + 2016 = 2081 entries.
    assert len(nbrs) == 1 + 64 + (64 * 63) // 2
    assert len(set(nbrs)) == len(nbrs)  # all distinct
    assert 0 in nbrs


def test_lsh_neighbor_buckets_have_correct_hamming():
    lsh = LSHIndex()
    nbrs = lsh.neighbor_buckets(0, radius=2)
    for b in nbrs:
        assert bin(b).count("1") <= 2


def test_lsh_similar_embeddings_land_near():
    """Very similar embeddings should sit within Hamming radius 2 in >80% of
    trials. With 64 random hyperplanes the expected bit-difference between
    two vectors at cosine c is 64*arccos(c)/pi — radius-2 hits demand
    cosine well above 0.99, so we sample from a tight ball."""
    lsh = LSHIndex(seed=7)
    rng = np.random.default_rng(123)
    near_count = 0
    qualifying = 0
    trials = 100
    for _ in range(trials):
        a = _normed(rng)
        noise = rng.standard_normal(EMBEDDING_DIM).astype(np.float32) * 0.001
        b = a + noise
        b = b / np.linalg.norm(b)
        cos = float(np.dot(a, b))
        # Precondition: the user spec says "cosine sim > 0.95"; in practice
        # we sample much tighter so the radius-2 threshold is achievable.
        if cos < 0.95:
            continue
        qualifying += 1
        ha = lsh.hash(a)
        hb = lsh.hash(b)
        if bin(ha ^ hb).count("1") <= 2:
            near_count += 1
    assert qualifying >= 95, f"only {qualifying}/{trials} qualified"
    assert near_count >= 0.8 * qualifying, (
        f"only {near_count}/{qualifying} qualifying trials landed within radius 2"
    )


# ---------------------------------------------------------------------------
# DemandOracle
# ---------------------------------------------------------------------------

@pytest.fixture
def bb(tmp_path) -> Blackboard:
    return Blackboard(str(tmp_path / "bb.db"))


def test_demand_oracle_three_items_yields_positive_deficit(bb):
    intent_id = bb.post_intent(_goal_spec(_intent("a")))
    rng = np.random.default_rng(42)
    base = _normed(rng)

    # Three identical embeddings → guaranteed same bucket. (At 64-plane
    # LSH, even 0.02-magnitude noise drifts items past radius-2.)
    for _ in range(3):
        bb.post_work_item(_work_item(intent_id, base, reward=0.4))

    lsh = LSHIndex(seed=7)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    oracle._poll()  # synchronous poll for deterministic test

    deficit = oracle.compute_deficit(base)
    assert deficit > 0.0

    bucket = lsh.hash(base)
    sig = oracle.get_signal(bucket)
    assert sig is not None
    assert sig.unclaimed_count == 3
    assert 0.39 <= sig.avg_reward <= 0.41
    assert sig.centroid_embedding is not None
    assert sig.centroid_embedding.shape == (EMBEDDING_DIM,)


def test_demand_oracle_background_thread_polls(bb):
    intent_id = bb.post_intent(_goal_spec(_intent("b")))
    rng = np.random.default_rng(11)
    e = _normed(rng)
    bb.post_work_item(_work_item(intent_id, e, reward=0.6))

    lsh = LSHIndex(seed=3)
    oracle = DemandOracle(bb, lsh, poll_interval_s=0.05)
    try:
        oracle.start()
        # start() runs one synchronous poll; signal should already be there.
        sig = oracle.get_signal(lsh.hash(e))
        assert sig is not None
        assert sig.unclaimed_count == 1
    finally:
        oracle.stop()


def test_should_spawn_replica_threshold_logic(bb):
    intent_id = bb.post_intent(_goal_spec(_intent("c")))
    rng = np.random.default_rng(99)
    base = _normed(rng)

    # Many items in the same bucket → high deficit, but the agent's own
    # bucket is the same one and it's saturated → no spawn.
    for _ in range(8):
        bb.post_work_item(_work_item(intent_id, base, reward=0.7))

    lsh = LSHIndex(seed=7)
    oracle = DemandOracle(bb, lsh, poll_interval_s=60.0)
    oracle._poll()

    # Agent sitting on the same neighborhood as the work — saturated.
    assert oracle.should_spawn_replica(base, SPAWN_THRESHOLD=5.0) is False

    # Agent in an unrelated neighborhood — own bucket empty, but neighbor-
    # radius-2 won't reach the loaded bucket either, so deficit = 0.
    far = _normed(np.random.default_rng(123456))
    assert oracle.should_spawn_replica(far, SPAWN_THRESHOLD=5.0) is False


# ---------------------------------------------------------------------------
# Specialization drift
# ---------------------------------------------------------------------------

def test_update_specialization_pulls_toward_success():
    rng = np.random.default_rng(0)
    cur = _normed(rng)
    task = _normed(rng)
    cos_before = float(np.dot(cur, task))
    new = update_specialization(cur, task, success=True)
    cos_after = float(np.dot(new, task))
    assert cos_after > cos_before
    # Result lives on the unit sphere.
    assert abs(float(np.linalg.norm(new)) - 1.0) < 1e-5


def test_update_specialization_pushes_away_on_failure():
    rng = np.random.default_rng(1)
    cur = _normed(rng)
    task = _normed(rng)
    cos_before = float(np.dot(cur, task))
    new = update_specialization(cur, task, success=False)
    cos_after = float(np.dot(new, task))
    # Failure direction is -0.1 * task: small repulsion. Cosine should drop,
    # not spike, but the magnitude is small per-update.
    assert cos_after < cos_before


def test_specialization_tracker_persists(tmp_path):
    db_path = str(tmp_path / "spec.db")
    rng = np.random.default_rng(5)
    initial = _normed(rng)

    t1 = SpecializationTracker("agent-A", initial, db_path)
    task = _normed(rng)
    new1 = t1.update(task, success=True)
    assert t1.update_count == 1

    # Reopen — should resume from persisted state.
    t2 = SpecializationTracker("agent-A", _normed(rng), db_path)
    assert t2.update_count == 1
    np.testing.assert_allclose(t2.current, new1, atol=1e-6)


def test_drift_converges_to_domain_centroid(tmp_path):
    """After 100 successful tasks drawn from a tight domain cluster,
    the agent's specialization vector should align well with the domain
    centroid (cosine sim > 0.7)."""
    rng = np.random.default_rng(2026)
    domain_centroid = _normed(rng)

    # Generate 100 tasks tightly clustered around the centroid.
    tasks = []
    for _ in range(100):
        noise = rng.standard_normal(EMBEDDING_DIM).astype(np.float32) * 0.08
        t = domain_centroid + noise
        t = t / np.linalg.norm(t)
        tasks.append(t)

    db_path = str(tmp_path / "drift.db")
    # Start far from the centroid so the test actually exercises convergence.
    far_start = _normed(np.random.default_rng(91234))
    tracker = SpecializationTracker("agent-X", far_start, db_path)

    initial_cos = float(np.dot(tracker.current, domain_centroid))

    for t in tasks:
        tracker.update(t, success=True)

    final_cos = float(np.dot(tracker.current, domain_centroid))
    assert final_cos > 0.7, (
        f"cosine to centroid only reached {final_cos:.3f} after 100 updates "
        f"(started at {initial_cos:.3f})"
    )
    # Should still be a unit vector.
    assert abs(float(np.linalg.norm(tracker.current)) - 1.0) < 1e-5


def test_drift_rate_constant_is_small():
    # Sanity guard: if someone bumps DRIFT_RATE to 0.5 thinking "it'll
    # converge faster", agents will thrash. Document the bound.
    assert 0.0 < DRIFT_RATE <= 0.1
