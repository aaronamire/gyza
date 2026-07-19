"""
Tests for the consensus lab — lock in the qualitative findings that the
experiments produced, so a regression in a mechanism can't silently
change the conclusions we drew from them.

These assert *directional* facts (a collapse happens, an inversion
happens, a recovery happens), not exact numbers, since the point is the
structural behaviour, not a fragile constant.
"""
from __future__ import annotations

from gyza.demo.consensus_lab import (
    exp1_monoculture,
    exp3_peer_prediction_diversity,
    exp4_market,
    exp5_trim_discards_outlier,
)


def test_detection_collapses_at_monoculture_majority():
    # E1: every detection/aggregation mechanism is ~perfect below a
    # monoculture majority and ~zero above it (the majority-following cliff).
    rows = exp1_monoculture(seed=0)
    for mech, acc in rows[0.2].items():
        assert acc > 0.9, f"{mech} should be reliable at 20% monoculture"
    for mech, acc in rows[0.7].items():
        assert acc < 0.1, f"{mech} should collapse at 70% monoculture"


def test_peer_prediction_inverts_without_diversity():
    # E3: peer-prediction separates reliable from unreliable when diverse,
    # and inverts (AUC → 0, worse than chance) under a monoculture majority.
    rows = exp3_peer_prediction_diversity(seed=0)
    assert rows[0.1]["auc_reliable_vs_unreliable"] > 0.8
    assert rows[0.7]["auc_reliable_vs_unreliable"] < 0.5


def test_market_needs_some_ground_truth_but_then_recovers():
    # E4: no resolution → chance (no free lunch); sparse resolution →
    # recovery + capital shifts to diverse-correct agents.
    rows = exp4_market(seed=0)
    assert 0.4 < rows[0.0]["accuracy"] < 0.6            # ~chance
    assert rows[0.0]["final_capital_share"]["diverse"] < 0.6
    assert rows[0.2]["accuracy"] > 0.9                  # recovered
    assert rows[0.2]["final_capital_share"]["diverse"] > 0.9


def test_trimming_can_do_worse_than_mean_by_discarding_outlier():
    # E5: in the confident-correct-minority band, the plain mean is right
    # and the trimmed mean is wrong — it discarded the correct outlier.
    rows = exp5_trim_discards_outlier(seed=0)
    assert rows[0.2]["mean_acc"] > 0.9
    assert rows[0.2]["trimmed_acc"] < 0.1
