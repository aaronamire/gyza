"""No Blackboard subclass may DROP a parameter its base accepts.

Found the hard way on 2026-08-25. `NetworkBlackboard.complete_work_item`
omitted `expected_owner`, which the runner always passes by keyword. The
resulting TypeError landed in a best-effort `except Exception: pass` inside
`_complete`, so on ANY networked deployment **every completion silently failed
to record**: envelopes were signed and stored, the board never advanced, and
items stayed claimed-but-incomplete until the lease expired and the work was
redone — forever.

It is the THIRD dropped-parameter bug in one day (`get_unclaimed`'s `limit`,
`try_claim`'s `claimant_tier`, then this), and `try_claim` even carries a
comment warning that an override dropping a parameter "would silently
reintroduce the gap". A comment two methods away did not stop it, so this is
the check instead.
"""
from __future__ import annotations

import inspect

from gyza.blackboard import Blackboard


def _subclasses(cls):
    for s in cls.__subclasses__():
        yield s
        yield from _subclasses(s)


def test_no_blackboard_override_drops_a_base_parameter():
    # import for side effect: the subclasses must be loaded to be found
    import gyza.network.network_blackboard  # noqa: F401

    offenders = []
    for sub in _subclasses(Blackboard):
        for name, fn in vars(sub).items():
            if name.startswith("__") or not callable(fn):
                continue
            base = getattr(Blackboard, name, None)
            if base is None or not callable(base):
                continue
            try:
                over_p = inspect.signature(fn).parameters
                base_p = inspect.signature(base).parameters
            except (TypeError, ValueError):
                continue
            if any(p.kind is p.VAR_KEYWORD for p in over_p.values()):
                continue                     # **kwargs forwards everything
            missing = set(base_p) - set(over_p)
            if missing:
                offenders.append(
                    f"{sub.__name__}.{name} drops {sorted(missing)}")
    assert offenders == [], offenders


def test_the_check_can_actually_FAIL():
    """Negative control. A conformance test that cannot fail is decoration —
    and this program has shipped exactly that defect before."""
    class _Dropper(Blackboard):
        def complete_work_item(self, work_item_id, output_hash,
                               icp_envelope_hash, success, hlc):
            raise NotImplementedError

    base_p = set(inspect.signature(Blackboard.complete_work_item).parameters)
    over_p = set(inspect.signature(_Dropper.complete_work_item).parameters)
    assert "expected_owner" in (base_p - over_p), (
        "the detector would not notice a dropped parameter")


def test_complete_work_item_still_ENFORCES_ownership_over_the_network():
    """The behaviour the dropped parameter silently disabled."""
    import tempfile
    import uuid
    from pathlib import Path

    import numpy as np
    import pytest

    from gyza.blackboard import ClaimLostError
    from gyza.network.network_blackboard import NetworkBlackboard
    from gyza.schema import EMBEDDING_DIM, HLC, WorkItem

    tmp = Path(tempfile.mkdtemp())
    bb = NetworkBlackboard(str(tmp / "b.db"))
    bb.post_intent({"intent_id": "own", "natural_text": "o",
                    "category": "system_task", "actions": [],
                    "authorization": {"resources": [],
                                      "preview_required": False,
                                      "reversible": True}})
    e = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    e[0] = 1.0
    import time
    w = WorkItem(
        id=str(uuid.uuid7()), lineage_root="own", parent_id=None,
        description="x", desc_embedding=e, reward=0.9,
        reward_updated_ns=time.time_ns(), required_tier=0, input_hashes=[],
        output_spec={"kind": "t"}, streaming_ok=False, claimed_by=None,
        claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(), ttl_ns=3600 * 10**9)
    bb.post_work_item(w)
    assert bb.try_claim(w.id, "owner", HLC(node_id="n"), claimant_tier=0)

    with pytest.raises(ClaimLostError):
        bb.complete_work_item(w.id, "aa" * 32, "bb" * 32, True,
                              HLC(node_id="n"), expected_owner="somebody-else")
    # and the rightful owner still succeeds
    bb.complete_work_item(w.id, "cc" * 32, "dd" * 32, True,
                          HLC(node_id="n"), expected_owner="owner")
    row = bb._conn().execute(
        "SELECT output_hash FROM work_items WHERE id=?", (w.id,)).fetchone()
    assert row["output_hash"] == "cc" * 32
