"""Pins R-D's claims. Run: ~/dev/marshal/.os/bin/python -m pytest research/disperse/ -q"""
from __future__ import annotations

import pathlib
import sys
from fractions import Fraction as F

HERE = pathlib.Path(__file__).resolve().parent
for d in ("", "../churn", "../hierarchy", "../margin"):
    sys.path.insert(0, str((HERE / d).resolve()))

from disperse import COLLIDE, DISPERSE, cell, critical_k        # noqa: E402


def test_collide_reproduces_R_C():
    """P-D0. Without this the routing comparison is not attributable."""
    assert critical_k(3, 8, F(0), 1, COLLIDE, seeds=3) == 511


def test_dispersal_NEVER_breaches():
    """The result: the smarter routing is strictly worse for the attacker."""
    assert critical_k(3, 8, F(0), 1, DISPERSE, seeds=3) is None


def test_dispersal_destroys_more_and_achieves_less():
    """Reach and damage are both anti-correlated with success; only asymmetry
    predicts it."""
    d = cell(3, 8, F(0), 1, 103, DISPERSE, seeds=3)
    c = cell(3, 8, F(0), 1, 103, COLLIDE, seeds=3)
    assert d["pools_touched"] > c["pools_touched"]      # reaches more
    assert d["violations"] == 0 and c["violations"] == 0
    # ...and the stationary attack, reaching ONE cluster, is the one that works
    from churn_tree import ADVERSARIAL, CLAIM_TRAVELS
    from churn_tree import cell as ccell
    assert ccell(3, 8, F(0), 1, 103, F(0), CLAIM_TRAVELS, ADVERSARIAL,
                 seeds=3)["violations"] > 0


def test_a_ratio_bound_survives_96_percent_value_destruction():
    """Scale invariance, measured. The mechanism behind the whole result."""
    import random

    from churn_tree import CLAIM_TRAVELS, ChurnTree
    from env_margin import SCALE
    from tree import KAPPA, box_floor_at, kappa_level, level_endowment

    d, f, k = 3, 8, 103
    kl = kappa_level(d)
    floors = {l: box_floor_at(f, kl, F(0), level_endowment(f, l - 1))
              for l in range(1, d + 1)}
    rng = random.Random(0)
    t = ChurnTree(d, f)
    order = list(range(1, t.n))
    rng.shuffle(order)
    defs = set(order[:k])
    start = sum(t.leaves)
    cum = [0] * t.n
    hd = [list(cum)]
    for _ in range(41):
        for p in defs:
            unseen = [c for c in range(t.n_clusters) if c not in t.touched[p]]
            pool = unseen or list(range(t.n_clusters))
            t.migrate(p, max(pool, key=lambda c: t.pool[c]), CLAIM_TRAVELS)
        vd = hd[max(0, len(hd) - 2)]
        for leaf in order:
            b = t.seen(0, leaf, 1) - (cum[leaf] - vd[leaf])
            w = b - (0 if leaf in defs else floors[1])
            if w > 0:
                cum[leaf] += t.divest(leaf, w)
        t.commit()
        hd.append(list(cum))
    end = sum(t.leaves)
    assert end < start * 0.1, (start / SCALE, end / SCALE)   # >90% destroyed
    assert t.concentration() < KAPPA, "a ratio must survive uniform destruction"
