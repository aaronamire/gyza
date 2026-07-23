"""
Correctness anchor for Channel A (Phase 2). Synthetic; no network, no cache.
If these fail no result is trustworthy. (Phase 3 hedge-classification test is
added with defensibility_experiment.py.)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "route2_independence"))
sys.path.insert(0, str(Path(__file__).parent.parent / "correlated_failure"))

import numpy as np  # noqa: E402
from consistency_experiment import relation_holds, _youden, _perm_p, _sc_changed  # noqa: E402
from route2_experiment import _sym_equal  # noqa: E402


# 1. canonical change detection
def test_canonical_change():
    assert _sym_equal("1/2", "0.5") and _sym_equal("1/2", "\\frac{1}{2}")   # NO change
    assert not _sym_equal("1/2", "2/3")                                      # change


# 2. equivariance (T5, k=3)
def test_equivariance_relation():
    assert relation_holds("4", "12", "equivariance_k3") is True   # 4->12 satisfies x3
    assert relation_holds("4", "4", "equivariance_k3") is False   # 4->4 violates
    assert relation_holds("4", "7", "equivariance_k3") is False   # 4->7 violates
    # invariance
    assert relation_holds("1/2", "0.5", "invariance") is True
    assert relation_holds("8", "9", "invariance") is False


# 3. non-answer guard: excluded (None), never a violation
def test_nonanswer_excluded():
    assert relation_holds("IMPORTERR:NOANSWER", "12", "invariance") is None
    assert relation_holds("4", "TIMEOUT", "equivariance_k3") is None
    assert relation_holds("IMPORTERR:X", "IMPORTERR:Y", "invariance") is None


# 4. the firing-rate trap: a detector that ALWAYS fires has TPR=1, FPR=1, J=0
def test_always_fire_J_zero():
    fires = [1, 1, 1, 1, 1, 1]
    wrongs = [1, 1, 1, 0, 0, 0]
    tpr, fpr, firing, J, prec = _youden(fires, wrongs)
    assert tpr == 1.0 and fpr == 1.0 and firing == 1.0
    assert abs(J) < 1e-12          # J is 0, not 1 — pins the trap
    # a perfect detector: fires iff wrong -> J=1
    tpr2, fpr2, _, J2, _ = _youden([1, 1, 1, 0, 0, 0], wrongs)
    assert abs(J2 - 1.0) < 1e-12


# 5. permutation null: no association -> not significant
def test_perm_null_no_association():
    rng = np.random.default_rng(0)
    fires = list(rng.integers(0, 2, 60))
    wrongs = list(rng.integers(0, 2, 60))     # independent of fires
    p = _perm_p(fires, wrongs, seed=1)
    assert p is not None and p > 0.05


# 6. self-consistency: not unanimous -> fires; unanimous (canonical) -> not
def test_self_consistency_change():
    cache = {"q": {"0": {"raw": "x \\boxed{8}"}, "1": {"raw": "y \\boxed{0.5}"}}}  # 8 vs 0.5 differ
    assert _sc_changed(cache, "q", 2) is True
    cache2 = {"q": {"0": {"raw": "\\boxed{1/2}"}, "1": {"raw": "\\boxed{0.5}"}}}   # canonical-equal
    assert _sc_changed(cache2, "q", 2) is False
    cache3 = {"q": {"0": {"raw": "\\boxed{8}"}}}                                    # <2 samples
    assert _sc_changed(cache3, "q", 2) is None


# 7. cost-matched: K equals the transform count for the item (from transforms.json)
def test_cost_matched_K():
    import json
    tfs = json.loads((Path(__file__).parent / "transforms.json").read_text())["transforms"]
    by_item = {}
    for t in tfs:
        by_item.setdefault(t["item_id"], []).append(t)
    noop = [iid for iid in by_item if iid.startswith("ii_noop")]
    assert noop and all(len(by_item[iid]) == 5 for iid in noop)   # NoOp has all 5 transforms


# 8. defensibility verdict + hedge classification (Channel B)
def test_defensibility_verdict_and_hedge():
    from defensibility_experiment import _round_outcome
    # committed claim "9" (a falsehood), invariance transform:
    ok = _round_outcome({"raw": "The answer stays \\boxed{9}", "declared": "invariance", "claim": "9"})
    assert ok == "ok"                                   # maintained the claim
    viol = _round_outcome({"raw": "\\boxed{8}", "declared": "invariance", "claim": "9"})
    assert viol == "violation"                          # leaked a different answer, no hedge language
    hedge1 = _round_outcome({"raw": "Actually the correct answer is \\boxed{8}",
                             "declared": "invariance", "claim": "9"})
    assert hedge1 == "hedge"                             # explicit correction -> HEDGE, not violation
    hedge2 = _round_outcome({"raw": "I cannot answer this.", "declared": "invariance", "claim": "9"})
    assert hedge2 == "hedge"                             # no committed answer -> HEDGE
    excl = _round_outcome({"raw": "__ERR__:X", "declared": "invariance", "claim": "9"})
    assert excl == "exclude"
