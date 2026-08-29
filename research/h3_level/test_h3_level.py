"""R-H3L's measured facts, pinned so a code change that invalidates them fails.

A findings document is prose. These are the three claims it rests on, asserted
against the production code path rather than against measurements.json -- a
test that reads the results file would only confirm the file still says what it
said.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Sibling import, matching the other routes' convention -- `research/` is
# deliberately not a package, and making it one here would change collection
# semantics for every route in the tree.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from run_h3_level import (                            # noqa: E402
    install_anthropic_stub, lifetime_tradeoff, run_inference_workload,
)


@pytest.fixture(scope="module", autouse=True)
def _stub():
    install_anthropic_stub()


def test_C1_exactly_one_mesh_exit_per_action(tmp_path):
    """C1, the ceiling the whole route turns on.

    Q-COUNT rises by exactly 1 per executed action, so any level on it is a
    lifetime action budget consumed at the same rate by a benign node and an
    exfiltrating one. If this ever reads anything but 1.0, either the inference
    site stopped firing (H3 silently measures less than it should) or a second
    producer appeared on the path -- both are findings, not noise.
    """
    r = run_inference_workload("c1", 50, 1024, tmp_path)
    assert r.q_count == 50, (
        f"expected exactly one MESH_EXIT event per action, got {r.q_count}/50")
    assert r.q_rate == 1.0


def test_truncation_is_per_artifact_not_per_send(tmp_path):
    """The defect that made this route's first adversary too weak.

    `_executor` slices each artifact at 4000 bytes, which looks like a cap on
    disclosure and is not: every artifact contributes its own block, so
    per-send bytes scale with the artifact COUNT. The first harness handed over
    one huge artifact, measured a number sitting exactly on the constant, and
    would have reported that a byte bound cannot separate an adversary.
    """
    one = run_inference_workload("t1", 20, 4096, tmp_path, n_artifacts=1)
    ten = run_inference_workload("t10", 20, 4096, tmp_path, n_artifacts=10)
    assert one.bytes_per_action < 5000, (
        "a single 4096-byte artifact should be truncated near 4000")
    assert ten.bytes_per_action > 8 * one.bytes_per_action, (
        f"disclosure must scale with artifact count: {one.bytes_per_action} "
        f"-> {ten.bytes_per_action} is not roughly 10x")


def test_cumulative_bound_degrades_linearly_with_demanded_lifetime():
    """The durable result, stated as arithmetic so it cannot drift.

    A separating level exists iff b_adv/b_benign > N/K. K is fixed by how fast
    the adversary must be caught, so the required adversary strength grows
    linearly with the benign lifetime N -- and for unbounded lifetime, no
    cumulative bound binds on any adversary of bounded per-send strength.
    """
    t = lifetime_tradeoff(1000.0, [1_000, 10_000, 100_000])
    ratios = [t[n]["required_adversary_ratio"] for n in (1_000, 10_000, 100_000)]
    assert ratios == [10.0, 100.0, 1000.0]
    # Linear, not sublinear: a 10x longer life costs exactly 10x the strength.
    assert ratios[1] / ratios[0] == 10.0
    assert ratios[2] / ratios[1] == 10.0
