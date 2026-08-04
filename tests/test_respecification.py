"""Respecification of two claim types out of the NO_VERIFIER bucket.

THE BINDING ACCEPTANCE CRITERION is the power demonstration: each verifier must
FAIL on a REAL divergence in shipped code, not on a synthetic mutant of the
verifier's own logic. A verifier that has never rejected anything real is a
verifier with no demonstrated power, and registering it would be relabeling
rather than respecification.

The divergences used here were found by reading `gyza/memory.py`, not invented:

  D1  `_LanceBackend.search` over-fetches `max(4k, 16)` candidates
      (`gyza/memory.py:317`) and `retrieve_similar` applies the
      success/threshold filter AFTER (`gyza/memory.py:438-446`), so qualifying
      episodes ranked past the cutoff are silently dropped. The SQLite path
      scans everything (`gyza/memory.py:432-437`) and does not drop them.
  D2  the Lance path scores `np.dot(query_vec, ep.task_embedding)` against the
      STORED vector (`gyza/memory.py:323`) while the SQLite path normalizes it
      first (`gyza/memory.py:434`). For non-unit-norm embeddings the two
      backends compute different similarities for the same corpus.
"""
from __future__ import annotations

import numpy as np
import pytest

from gyza.canon import values_equal
from gyza.verification.adapters import NATIVE, NO_VERIFIER, build_registries
from gyza.verification.respec import (
    FILTER_SUCCESS_ONLY, IncompleteClaim, METRIC_COSINE_UNIT, RetrievalClaim,
    SendClaim, corpus_snapshot_digest, verify_retrieval_claim,
    verify_send_claim, wire_digest,
)

DIM = 384          # gyza.memory enforces EMBEDDING_DIM; a smaller
                   # vector is rejected by Episode.__post_init__


def _vec(seed: int, scale: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=DIM).astype(np.float32)
    v /= float(np.linalg.norm(v))
    return (v * scale).astype(np.float32)


def _corpus(n_fail: int, n_succ: int, query: np.ndarray):
    """Failures crowd the top of the ranking; successes sit below them."""
    items = []
    for i in range(n_fail):                      # near the query, unsuccessful
        v = (query + 0.01 * _vec(1000 + i)).astype(np.float32)
        items.append((f"fail-{i:03d}", v / np.linalg.norm(v), False))
    for i in range(n_succ):                      # further away, successful
        v = (query + 0.9 * _vec(2000 + i)).astype(np.float32)
        items.append((f"succ-{i:03d}", v / np.linalg.norm(v), True))
    return items


# --------------------------------------------------------------------------- #
#  registration hygiene                                                        #
# --------------------------------------------------------------------------- #
def test_both_types_are_registered_PROOF_carried_with_citations():
    by = {v.claim_type: v for v in NATIVE}
    for ct in ("memory_retrieval_relevance", "external_send_content"):
        assert ct in by, f"{ct} not registered in V-1"
        assert by[ct].carrier == "PROOF", (ct, by[ct].carrier)
        assert "gyza/verification/respec.py:" in by[ct].witness


def test_they_left_the_no_verifier_bucket_and_the_survivors_are_documented():
    assert "memory_retrieval_relevance" not in NO_VERIFIER
    assert "external_send_content" not in NO_VERIFIER
    assert set(NO_VERIFIER) == {"execution_output_content", "routing_match_quality"}


def test_a_claim_missing_its_parameters_is_REJECTED_not_defaulted():
    base = dict(corpus_snapshot="d" * 64, metric=METRIC_COSINE_UNIT, k=3,
                threshold=0.5, filter_predicate=FILTER_SUCCESS_ONLY,
                returned_ids=())
    RetrievalClaim(**base)                                    # baseline is valid
    for field, bad in (("corpus_snapshot", ""), ("metric", ""),
                       ("metric", "euclidean"), ("filter_predicate", ""),
                       ("filter_predicate", "vibes"), ("k", 0), ("k", -1),
                       ("threshold", 1.5)):
        with pytest.raises(IncompleteClaim):
            RetrievalClaim(**{**base, field: bad})


def test_a_send_claim_missing_its_parameters_is_REJECTED():
    ok = dict(artifact_hash="a" * 64, policy_id="p", destination="d",
              timestamp_ns=1, n_bytes=0)
    SendClaim(**ok)
    for field, bad in (("artifact_hash", ""), ("artifact_hash", "short"),
                       ("policy_id", ""), ("destination", ""), ("n_bytes", -1)):
        with pytest.raises(IncompleteClaim):
            SendClaim(**{**ok, field: bad})


# --------------------------------------------------------------------------- #
#  A — retrieval: no false rejection, then the POWER DEMONSTRATION             #
# --------------------------------------------------------------------------- #
def _correct_claim(items, q, k, t):
    scored = sorted(
        ((eid, float(np.dot(q / np.linalg.norm(q), v / np.linalg.norm(v))))
         for eid, v, ok in items if ok),
        key=lambda p: (-p[1], p[0]))
    ids = tuple(e for e, s in scored if s >= t)[:k]
    return RetrievalClaim(corpus_snapshot=corpus_snapshot_digest(items),
                          metric=METRIC_COSINE_UNIT, k=k, threshold=t,
                          filter_predicate=FILTER_SUCCESS_ONLY,
                          returned_ids=ids)


def test_correct_retrieval_is_ACCEPTED_no_false_rejection():
    q = _vec(7)
    items = _corpus(n_fail=30, n_succ=10, query=q)
    assert verify_retrieval_claim(_correct_claim(items, q, 5, -1.0), items, q)


def test_POWER_the_verifier_catches_the_real_lance_overfetch_divergence():
    """D1, reproduced against the SHIPPED `_LanceBackend` and the SHIPPED
    `EpisodicMemory.retrieve_similar` -- not a mutant of the verifier."""
    lancedb = pytest.importorskip("lancedb")
    assert lancedb
    import tempfile

    from gyza.memory import Episode, EpisodicMemory

    q = _vec(7)
    k = 5
    # 30 near failures crowd out the successes: the over-fetch window is
    # max(4*5,16) = 20, all of which are failures, so the Lance path can return
    # nothing while 10 qualifying successful episodes exist.
    items = _corpus(n_fail=30, n_succ=10, query=q)

    with tempfile.TemporaryDirectory() as tmp:
        mem = EpisodicMemory(agent_id="a" * 16, db_path=tmp)
        if mem._backend_name != "lancedb":
            pytest.skip("lance backend unavailable in this environment")
        eps = [Episode(episode_id=eid, agent_id="a" * 16,
                       task_embedding=np.asarray(v, dtype=np.float32),
                       intent_text=eid, input_hashes=[], output_hash="h",
                       action_types=[], success=ok, duration_ms=1,
                       model_identifier="m", icp_envelope_hash="e",
                       timestamp_ns=1)
               for eid, v, ok in items]
        mem._backend.add(eps)

        ranked = mem._backend.search(q, k=k)
        got = [ep.episode_id for ep, s in ranked if ep.success][:k]

    truth = _correct_claim(items, q, k, -1.0).returned_ids
    assert not values_equal(tuple(got), truth), (
        "precondition: the lance path must actually diverge here")

    divergent = RetrievalClaim(
        corpus_snapshot=corpus_snapshot_digest(items),
        metric=METRIC_COSINE_UNIT, k=k, threshold=-1.0,
        filter_predicate=FILTER_SUCCESS_ONLY, returned_ids=tuple(got))
    assert verify_retrieval_claim(divergent, items, q) is False, (
        "the verifier must REJECT the real over-fetch divergence")


def test_POWER_the_verifier_catches_the_real_unnormalized_cosine_divergence():
    """D2: the Lance path scores against the STORED vector; the SQLite path
    normalizes first. With non-unit-norm embeddings they rank differently.

    Constructed so the NORM flips the order: `near` has the higher true cosine
    but a small magnitude, `far` the lower cosine but a large one. That is the
    shape any embedding pipeline that forgets to normalize at write time will
    produce.
    """
    from gyza.memory import _normalize

    q = _vec(11)
    near = (q * 0.05).astype(np.float32)                 # cos ~ 1.0, norm 0.05
    other = _vec(12)
    far = ((0.3 * q + 0.7 * other) * 6.0).astype(np.float32)   # lower cos, big norm
    raw = [("near", near, True), ("far", far, True)]

    lance = {e: float(np.dot(q, v)) for e, v, _ in raw}                 # :323
    sqlite = {e: float(np.dot(_normalize(q), _normalize(v)))
              for e, v, _ in raw}                                       # :434
    lance_order = tuple(sorted(lance, key=lambda e: -lance[e]))
    sqlite_order = tuple(sorted(sqlite, key=lambda e: -sqlite[e]))
    assert not values_equal(lance_order, sqlite_order), (
        f"precondition: the two shipped scorings must differ; "
        f"lance={lance} sqlite={sqlite}")

    bad = RetrievalClaim(corpus_snapshot=corpus_snapshot_digest(raw),
                         metric=METRIC_COSINE_UNIT, k=2, threshold=-1.0,
                         filter_predicate=FILTER_SUCCESS_ONLY,
                         returned_ids=lance_order)
    assert verify_retrieval_claim(bad, raw, q) is False, (
        "the verifier must REJECT the un-normalized ranking")
    good = RetrievalClaim(corpus_snapshot=corpus_snapshot_digest(raw),
                          metric=METRIC_COSINE_UNIT, k=2, threshold=-1.0,
                          filter_predicate=FILTER_SUCCESS_ONLY,
                          returned_ids=sqlite_order)
    assert verify_retrieval_claim(good, raw, q) is True


def test_a_moved_corpus_is_REFUSED_the_immutable_frame():
    """Artifact #13's species in this domain: a claim whose reference set can
    move is not checkable. The digest pins the frame."""
    q = _vec(7)
    items = _corpus(4, 4, q)
    claim = _correct_claim(items, q, 3, -1.0)
    assert verify_retrieval_claim(claim, items, q)
    moved = items + [("succ-new", (q / np.linalg.norm(q)).astype(np.float32), True)]
    assert verify_retrieval_claim(claim, moved, q) is False


# --------------------------------------------------------------------------- #
#  B — send: no false rejection, then the POWER DEMONSTRATION                  #
# --------------------------------------------------------------------------- #
def test_correct_send_is_ACCEPTED():
    payload = b"the bytes that actually left"
    c = SendClaim(artifact_hash=wire_digest(payload), policy_id="P1",
                  destination="peer-1", timestamp_ns=1, n_bytes=len(payload))
    assert verify_send_claim(c, payload)


def test_POWER_a_sender_hashing_its_INTENT_rather_than_the_wire_is_caught():
    """The circularity S5 B3 records for binary hashes, at the send boundary: a
    hash computed from what the sender MEANT to send is self-report."""
    intended = b"approved artifact v2"
    actually_sent = b"approved artifact v1"          # stale buffer -- a real bug
    claim = SendClaim(artifact_hash=wire_digest(intended), policy_id="P1",
                      destination="peer-1", timestamp_ns=1,
                      n_bytes=len(intended))
    assert verify_send_claim(claim, actually_sent) is False, (
        "a hash of sender INTENT must not verify against the emitted bytes")


def test_POWER_a_truncated_send_is_caught_by_length_even_at_equal_prefix():
    payload = b"header|body-that-got-truncated"
    sent = payload[:6]
    claim = SendClaim(artifact_hash=wire_digest(payload), policy_id="P1",
                      destination="d", timestamp_ns=1, n_bytes=len(payload))
    assert verify_send_claim(claim, sent) is False


def test_policy_violation_is_caught_and_the_policy_is_CALLER_supplied():
    payload = b"x" * 10
    claim = SendClaim(artifact_hash=wire_digest(payload), policy_id="no-egress",
                      destination="external", timestamp_ns=1, n_bytes=10)
    deny_external = lambda c, b: c.destination != "external"     # noqa: E731
    assert verify_send_claim(claim, payload) is True             # hash-only
    assert verify_send_claim(claim, payload, deny_external) is False


# --------------------------------------------------------------------------- #
#  registry execution (artifact #16)                                           #
# --------------------------------------------------------------------------- #
def test_both_new_verifiers_execute_through_the_registry():
    """A registry entry no test executes is a component that does not exist."""
    verifiers, _ = build_registries()
    q = _vec(3)
    items = _corpus(2, 3, q)
    out = verifiers.get("memory_retrieval_relevance").fn(
        _correct_claim(items, q, 2, -1.0), items, q)
    assert out is True

    payload = b"registry-exercised"
    c = SendClaim(artifact_hash=wire_digest(payload), policy_id="P",
                  destination="d", timestamp_ns=1, n_bytes=len(payload))
    assert verifiers.get("external_send_content").fn(c, payload) is True


# --------------------------------------------------------------------------- #
#  THE FIX — and the verifier is its regression test                           #
# --------------------------------------------------------------------------- #
#
# The chain this demonstrates, end to end:
#   respecify the claim -> the verifier catches a REAL bug -> fix the bug ->
#   the verifier becomes the regression guard.
#
# The PRE-FIX behaviour is kept as an explicit fixture below. A regression test
# that cannot reproduce the original failure is not a regression test.

def _prefix_lance_scoring(ranked_rows, query_vec):
    """The PRE-FIX D2 scoring, preserved verbatim: dot against the STORED
    vector. `gyza/memory.py:323` before the fix."""
    return [(ep, float(np.dot(query_vec, ep.task_embedding)))
            for ep in ranked_rows]


def _lance_store(items, tmp):
    from gyza.memory import Episode, EpisodicMemory

    mem = EpisodicMemory(agent_id="b" * 16, db_path=tmp)
    if mem._backend_name != "lancedb":
        pytest.skip("lance backend unavailable in this environment")
    mem._backend.add([
        Episode(episode_id=eid, agent_id="b" * 16,
                task_embedding=np.asarray(v, dtype=np.float32),
                intent_text=eid, input_hashes=[], output_hash="h",
                action_types=[], success=ok, duration_ms=1,
                model_identifier="m", icp_envelope_hash="e", timestamp_ns=1)
        for eid, v, ok in items])
    return mem


def test_D1_FIXED_lance_and_sqlite_agree_on_the_divergence_case():
    """A3: proven against the REAL backend (lancedb), not a stub."""
    import tempfile

    pytest.importorskip("lancedb")
    q = _vec(7)
    k = 5
    items = _corpus(n_fail=30, n_succ=10, query=q)     # the case that broke it

    with tempfile.TemporaryDirectory() as tmp:
        mem = _lance_store(items, tmp)
        lance = [ep.episode_id
                 for ep, _ in mem._backend.search(q, k=k, success_only=True)][:k]

    truth = _correct_claim(items, q, k, -1.0).returned_ids
    assert len(lance) == k, (
        f"pre-fix this returned 0 of {k} qualifying results; got {len(lance)}")
    assert values_equal(tuple(lance), truth), (lance, truth)


def test_D1_the_prefix_behaviour_is_STILL_rejected_regression_fixture():
    """The original failure must remain reproducible, or this proves nothing."""
    q = _vec(7)
    items = _corpus(n_fail=30, n_succ=10, query=q)
    # pre-fix: rank everything, THEN drop failures, window = max(4k,16) = 20
    scored = sorted(
        ((eid, float(np.dot(q / np.linalg.norm(q), v / np.linalg.norm(v))), ok)
         for eid, v, ok in items), key=lambda p: (-p[1], p[0]))
    window = scored[:20]
    prefix_result = tuple(e for e, _s, ok in window if ok)[:5]
    assert prefix_result == (), "the pre-fix window must contain no successes"

    claim = RetrievalClaim(
        corpus_snapshot=corpus_snapshot_digest(items),
        metric=METRIC_COSINE_UNIT, k=5, threshold=-1.0,
        filter_predicate=FILTER_SUCCESS_ONLY, returned_ids=prefix_result)
    assert verify_retrieval_claim(claim, items, q) is False, (
        "the verifier must still reject the pre-fix behaviour")


def test_D2_FIXED_ranking_follows_the_declared_metric_not_magnitude():
    """The claim declares metric = cosine_unit; that definition is the arbiter."""
    import tempfile

    from gyza.memory import _normalize

    pytest.importorskip("lancedb")
    q = _vec(11)
    near = (q * 0.05).astype(np.float32)
    other = _vec(12)
    far = ((0.3 * q + 0.7 * other) * 6.0).astype(np.float32)
    items = [("near", near, True), ("far", far, True)]

    with tempfile.TemporaryDirectory() as tmp:
        mem = _lance_store(items, tmp)
        got = [ep.episode_id
               for ep, _ in mem._backend.search(q, k=2, success_only=True)]

    by_cosine = tuple(sorted(
        (e for e, _v, _o in items),
        key=lambda e: -float(np.dot(_normalize(q),
                                    _normalize(dict((i, v) for i, v, _ in items)[e])))))
    assert values_equal(tuple(got), by_cosine), (got, by_cosine)
    assert got[0] == "near", "magnitude must not outrank direction"

    prefix = _prefix_lance_scoring(
        [type("E", (), {"episode_id": e, "task_embedding": v})()
         for e, v, _ in items], q)
    prefix_order = tuple(e.episode_id for e, _ in
                         sorted(prefix, key=lambda t: -t[1]))
    assert prefix_order != tuple(got), (
        "the pre-fix scoring must still differ, or the fixture is inert")
