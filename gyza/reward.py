"""
Reward inflation: unclaimed work items grow more attractive over time.

The mechanism is a doubling on every `INFLATION_HALFLIFE_NS`. An item
that lingered in the queue twice as long as the half-life is worth 4×
its base, capped at 1.0. This keeps stale-but-valid work eventually
attractive to lower-tier agents instead of being permanently shadowed
by fresher high-reward items.

`refresh_rewards` materializes the inflation back into the stored
`reward` column when drift exceeds 5%, so query-time sorting reflects
current attractiveness without needing a per-row computation in SQL.
"""
from __future__ import annotations

import time

from gyza.blackboard import Blackboard


INFLATION_HALFLIFE_NS = 30 * 1_000_000_000

_DRIFT_THRESHOLD = 0.05


def current_reward(base_reward: float, reward_updated_ns: int) -> float:
    age_ns = time.time_ns() - reward_updated_ns
    inflation = 2 ** (age_ns / INFLATION_HALFLIFE_NS)
    return min(base_reward * inflation, 1.0)


def refresh_rewards(blackboard: Blackboard) -> int:
    now_ns = time.time_ns()
    updated = 0
    for wid, stored, updated_ns in blackboard._iter_unclaimed_for_refresh():
        cur = current_reward(stored, updated_ns)
        # Use stored as the divisor; if stored is zero, any positive cur
        # counts as drift. Cur is always >= stored, so the diff is signed-positive.
        if stored == 0.0:
            drifted = cur > 0.0
        else:
            drifted = (cur - stored) / stored > _DRIFT_THRESHOLD
        if drifted:
            blackboard._set_reward(wid, cur, now_ns)
            updated += 1
    return updated
