"""The two defects that made the work queue negative-scale.

Measured 2026-08-23 on 1500 items with one OS process per agent:

    agents            1     2     4     8    16
    claims/s before  24    22    12     7     4     <- ADDING AGENTS REMOVED CAPACITY
    claims/s after  151   244   247   204   175
    win rate before 100%  50%   28%   20%   11%     <- ~1/N, the herd signature
    win rate after  100%  99%   98%   96%   91%

Two independent causes, and they interact -- bounding the fetch makes the herd
WORSE, so neither may be fixed alone:

  D1  `_score_items` took a STRICT ARGMAX over a deterministically ordered
      list, so every agent's best item was the same row whenever scores tied.
  D2  `get_unclaimed` had NO LIMIT, so each agent re-materialised the entire
      backlog (384 floats per row) every poll: O(agents x backlog) per interval.
"""
from __future__ import annotations

import time
import uuid

import numpy as np

from gyza.blackboard import Blackboard
from gyza.runner import SELECTION_TIE_EPSILON
from gyza.schema import EMBEDDING_DIM, WorkItem


def _item(bb, intent="cont", emb=None, reward=0.9):
    e = emb if emb is not None else np.zeros(EMBEDDING_DIM, dtype=np.float32)
    if emb is None:
        e[0] = 1.0
    w = WorkItem(
        id=str(uuid.uuid7()), lineage_root=intent, parent_id=None,
        description="x", desc_embedding=e, reward=reward,
        reward_updated_ns=time.time_ns(), required_tier=0, input_hashes=[],
        output_spec={"kind": "t"}, streaming_ok=False, claimed_by=None,
        claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(), ttl_ns=3600 * 10**9)
    bb.post_work_item(w)
    return w


def _board(tmp_path, n, **kw):
    bb = Blackboard(str(tmp_path / "c.db"))
    bb.post_intent({"intent_id": "cont", "natural_text": "c",
                    "category": "system_task", "actions": [],
                    "authorization": {"resources": [],
                                      "preview_required": False,
                                      "reversible": True}})
    return bb, [_item(bb, **kw) for _ in range(n)]


# --------------------------------------------------------------------------- #
#  D2 — the fetch is bounded                                                    #
# --------------------------------------------------------------------------- #
def test_get_unclaimed_respects_limit(tmp_path):
    bb, _ = _board(tmp_path, 50)
    assert len(bb.get_unclaimed(0.0, 0, limit=10)) == 10
    assert len(bb.get_unclaimed(0.0, 0, limit=1)) == 1


def test_limit_none_is_still_unbounded(tmp_path):
    """The default must not change behaviour for existing callers."""
    bb, _ = _board(tmp_path, 30)
    assert len(bb.get_unclaimed(0.0, 0)) == 30
    assert len(bb.get_unclaimed(0.0, 0, limit=None)) == 30


def test_limit_keeps_the_highest_reward_items(tmp_path):
    """Bounding the fetch must not discard priority -- it takes the TOP."""
    bb = Blackboard(str(tmp_path / "c.db"))
    bb.post_intent({"intent_id": "cont", "natural_text": "c",
                    "category": "system_task", "actions": [],
                    "authorization": {"resources": [],
                                      "preview_required": False,
                                      "reversible": True}})
    for r in (0.1, 0.9, 0.5):
        _item(bb, reward=r)
    got = bb.get_unclaimed(0.0, 0, limit=2)
    assert [round(w.reward, 1) for w in got] == [0.9, 0.5]


# --------------------------------------------------------------------------- #
#  D1 — ties are broken at random, and ONLY ties                                #
# --------------------------------------------------------------------------- #
def _score(runner_cls, spec, items):
    """Drive the real selection without constructing a whole runner."""
    from gyza.runner import AgentRunner

    class _S:
        current = spec
    obj = AgentRunner.__new__(AgentRunner)
    obj._spec = _S()
    return AgentRunner._score_items(obj, items)


def test_tied_scores_do_not_always_pick_the_same_item(tmp_path):
    """THE FIX. Identical embeddings => every score ties => a strict argmax
    returns items[0] for every agent, and the win rate falls as 1/N."""
    from gyza.runner import AgentRunner

    bb, items = _board(tmp_path, 40)
    spec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    spec[0] = 1.0
    picks = {_score(AgentRunner, spec, items)[0].id for _ in range(60)}
    assert len(picks) > 1, (
        "every draw picked the same tied item; the thundering herd is back"
    )


def test_a_UNIQUE_best_is_still_returned(tmp_path):
    """Negative control: randomisation must not weaken selection. Where a
    genuine best exists it is returned every time, so match quality is
    unchanged in the case the fix is not needed."""
    from gyza.runner import AgentRunner

    bb = Blackboard(str(tmp_path / "c.db"))
    bb.post_intent({"intent_id": "cont", "natural_text": "c",
                    "category": "system_task", "actions": [],
                    "authorization": {"resources": [],
                                      "preview_required": False,
                                      "reversible": True}})
    spec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    spec[0] = 1.0
    others = []
    for k in range(1, 8):
        e = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        e[k] = 1.0
        others.append(_item(bb, emb=e))
    target = _item(bb)                       # the only aligned item
    items = bb.get_unclaimed(0.0, 0)
    for _ in range(30):
        assert _score(AgentRunner, spec, items)[0].id == target.id


def test_the_returned_score_belongs_to_the_returned_item(tmp_path):
    """If the band's maximum were reported for a different item, work below
    `min_similarity_threshold` would be admitted."""
    from gyza.runner import AgentRunner, _cosine

    bb, items = _board(tmp_path, 25)
    spec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    spec[0] = 1.0
    for _ in range(25):
        it, score = _score(AgentRunner, spec, items)
        assert abs(score - _cosine(spec, it.desc_embedding)) < 1e-6


def test_near_ties_within_epsilon_are_treated_as_tied(tmp_path):
    bb = Blackboard(str(tmp_path / "c.db"))
    bb.post_intent({"intent_id": "cont", "natural_text": "c",
                    "category": "system_task", "actions": [],
                    "authorization": {"resources": [],
                                      "preview_required": False,
                                      "reversible": True}})
    from gyza.runner import AgentRunner

    spec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    spec[0] = 1.0
    a = _item(bb)
    e = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    e[0] = 1.0 - SELECTION_TIE_EPSILON / 4       # inside the band
    e[1] = 0.02
    b = _item(bb, emb=e)
    items = bb.get_unclaimed(0.0, 0)
    picks = {_score(AgentRunner, spec, items)[0].id for _ in range(60)}
    assert picks == {a.id, b.id}
