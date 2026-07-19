"""
Validation of the sharpened metrics against ground truth — the four
confounds from the Stage-0 review. The load-bearing test is
`test_null_distinguishes_attractiveness_from_correlation`: if the
base-rate null cannot tell a seductive distractor from a shared blind
spot, every real-model number is worthless.
"""
from __future__ import annotations

import numpy as np

from rho_measure import (
    difficulty_filter,
    diverse_vs_monoculture,
    same_wrong_excess,
    synth_answers,
    within_cross,
)


# ----------------------------------------------------------------------
# (1)+(2) The base-rate null: attractiveness vs. genuine correlation
# ----------------------------------------------------------------------

def _mean_excess(rho: float, attract_gamma: float, seed: int) -> float:
    preds, qs = synth_answers(n_models=24, n_questions=2500, k=4,
                              competence=0.6, rho=rho,
                              attract_gamma=attract_gamma, seed=seed)
    E = same_wrong_excess(preds, qs)
    m = E.shape[0]
    vals = [E[i, j] for i in range(m) for j in range(i + 1, m)]
    return float(np.nanmean(vals))


def test_pure_attractiveness_gives_zero_excess():
    # A STRONG attractive distractor (gamma=0.9) with INDEPENDENT errors
    # (rho=0): many same-wrong collisions, fully explained by
    # attractiveness -> the base-rate null absorbs them -> excess ~ 0.
    assert abs(_mean_excess(rho=0.0, attract_gamma=0.9, seed=1)) < 0.02


def test_uniform_correlation_is_absorbed_by_the_null():
    # THE KEY LIMITATION, asserted honestly: a blind spot shared UNIFORMLY
    # by the whole pool is observationally identical to an attractive
    # distractor. A per-question base-rate null cannot (and must not)
    # separate them -> excess stays ~ 0 even at high uniform rho. Only
    # DIFFERENTIAL correlation is identifiable (next test).
    assert abs(_mean_excess(rho=0.6, attract_gamma=0.9, seed=1)) < 0.03


# ----------------------------------------------------------------------
# (3) Difficulty filtering keeps intermediate-variance items
# ----------------------------------------------------------------------

def test_difficulty_filter_drops_trivial_and_impossible():
    preds, qs = synth_answers(n_models=20, n_questions=1500, k=4,
                              competence=0.6, rho=0.3, attract_gamma=0.7, seed=3)
    keep = difficulty_filter(preds, qs, lo=0.2, hi=0.8)
    answers = np.array([q.answer_idx for q in qs])
    acc = (preds == answers[None, :]).mean(axis=0)
    assert all(0.2 <= acc[q] <= 0.8 for q in keep)
    # some items are excluded (the distribution has tails)
    assert 0 < len(keep) < len(qs)


# ----------------------------------------------------------------------
# within-vs-cross of the EXCESS matrix is attractiveness-robust
# ----------------------------------------------------------------------

def test_within_beats_cross_on_excess_under_family_structure():
    # Two families = two independent correlated worlds, same attractive
    # distractor structure. Attractiveness is shared across BOTH families,
    # so only genuine within-family correlation should separate them.
    a, qa = synth_answers(n_models=6, n_questions=2500, k=4, competence=0.6,
                          rho=0.7, attract_gamma=0.8, seed=10)
    b, _ = synth_answers(n_models=6, n_questions=2500, k=4, competence=0.6,
                         rho=0.7, attract_gamma=0.8, seed=20)
    preds = np.vstack([a, b])
    E = same_wrong_excess(preds, qa)
    w, c = within_cross(E, ["A"] * 6 + ["B"] * 6)
    assert w > c + 0.03          # within-family excess clearly higher


# ----------------------------------------------------------------------
# The intervention arm: reducing correlation improves collective accuracy
# ----------------------------------------------------------------------

def test_diversity_intervention_improves_accuracy_at_fixed_size():
    r = diverse_vs_monoculture(ensemble_size=15, n_groups=5, n_questions=2000,
                               k=4, competence=0.55, rho=0.8, seed=7)
    # Same size, same competence, same within-group rho: splitting across
    # independent groups beats the monoculture.
    assert r["diverse_acc"] > r["monoculture_acc"] + 0.03
