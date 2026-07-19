"""
Correctness anchor for the rho-measurement instrument.

The instrument must RECOVER a correlation it was handed: ~0 at rho=0 (the
independent case that must match known results) and monotonically
increasing with rho. If these fail, no real-model number the instrument
produces is trustworthy. Everything deterministic from a seed.

Run:  ~/dev/marshal/.os/bin/python -m pytest research/correlated_failure/ -q
"""
from __future__ import annotations

import numpy as np

from rho_measure import (
    Question,
    SyntheticBackend,
    SyntheticWorld,
    error_correlation,
    measure,
    shared_wrong_rate,
    within_cross,
)


def _questions(n: int, k: int = 4) -> list[Question]:
    # answer index cycles deterministically; content is irrelevant to the math
    return [Question(f"q{i}", f"p{i}", tuple(f"c{j}" for j in range(k)), i % k)
            for i in range(n)]


# ----------------------------------------------------------------------
# Pure math
# ----------------------------------------------------------------------

def test_error_correlation_identical_and_anti():
    E = np.array([[1, 0, 1, 0, 1], [1, 0, 1, 0, 1], [0, 1, 0, 1, 0]])
    C = error_correlation(E)
    assert C[0, 1] == 1.0        # identical error vectors
    assert C[0, 2] == -1.0       # anti-correlated


def test_within_cross_aggregation():
    fams = ["A", "A", "B"]
    corr = np.array([[1.0, 0.8, 0.1],
                     [0.8, 1.0, 0.2],
                     [0.1, 0.2, 1.0]])
    w, c = within_cross(corr, fams)
    assert w == 0.8                       # the A-A pair
    assert abs(c - 0.15) < 1e-9           # mean of A-B pairs (0.1, 0.2)


def test_shared_wrong_rate_detects_agreement():
    q = _questions(2)
    # q0: three models, two agree on the same wrong answer -> shared blind spot
    # q1: erring models disagree -> not shared
    ans = [q[0].answer_idx, q[1].answer_idx]
    w0 = (ans[0] + 1) % 4
    preds = np.array([
        [w0, (ans[1] + 1) % 4],
        [w0, (ans[1] + 2) % 4],
        [ans[0], (ans[1] + 3) % 4],
    ])
    # q0: 2/2 erring models agree on w0 -> shared; q1: 3 erring, all differ -> not
    assert shared_wrong_rate(preds, q) == 0.5


# ----------------------------------------------------------------------
# The anchor: recover a known rho
# ----------------------------------------------------------------------

def _mean_cross_corr(rho: float, seed: int, n_models: int = 8,
                     n_q: int = 3000) -> float:
    qs = _questions(n_q)
    models = [SyntheticBackend(f"m{i}", "fam", competence=0.7, rho=rho)
              for i in range(n_models)]
    preds = SyntheticWorld(seed).run(models, qs)
    C = error_correlation(preds != np.array([q.answer_idx for q in qs])[None, :])
    # mean off-diagonal
    m = C.shape[0]
    vals = [C[i, j] for i in range(m) for j in range(i + 1, m)]
    return float(np.mean(vals))


def test_null_at_rho_zero():
    # Independent errors -> measured cross-correlation ~ 0.
    assert abs(_mean_cross_corr(0.0, seed=1)) < 0.05


def test_monotonic_in_rho():
    seeds = [1, 2, 3]
    curve = {r: np.mean([_mean_cross_corr(r, s) for s in seeds])
             for r in (0.0, 0.3, 0.6, 0.9)}
    vals = [curve[r] for r in (0.0, 0.3, 0.6, 0.9)]
    # strictly increasing and clearly separated from the null
    assert vals[0] < vals[1] < vals[2] < vals[3]
    assert vals[0] < 0.05 and vals[3] > 0.4


def test_determinism_same_seed():
    a = _mean_cross_corr(0.6, seed=42)
    b = _mean_cross_corr(0.6, seed=42)
    assert a == b


def test_within_beats_cross_under_family_structure():
    # Two families, each with its OWN shared latent world (high within-ρ),
    # composed into one measurement (low cross-ρ because the worlds differ).
    qs = _questions(3000)
    fam_a = [SyntheticBackend(f"a{i}", "A", competence=0.7, rho=0.8)
             for i in range(4)]
    fam_b = [SyntheticBackend(f"b{i}", "B", competence=0.7, rho=0.8)
             for i in range(4)]
    pa = SyntheticWorld(seed=10).run(fam_a, qs)   # world A
    pb = SyntheticWorld(seed=20).run(fam_b, qs)   # independent world B
    preds = np.vstack([pa, pb])
    res = measure(preds, ["A"] * 4 + ["B"] * 4, qs)
    assert res.mean_within > res.mean_cross + 0.2   # within clearly higher
