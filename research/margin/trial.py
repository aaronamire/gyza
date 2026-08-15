"""R-M1 — one trajectory under a given (M, delta, epsilon, activity, population).

THE GUARD IS LOCAL AND STALE. A principal proposes a new total for ITSELF and
the check reads only that proposal against `[L(delta), U]`. It never reads
another principal's state -- that locality is the whole point, and the staleness
is what it has to survive.

THREE DESIGN DECISIONS, EACH FORCED BY A CONTROL THAT FAILED BEFORE ANY DATA.

1. ROLES ARE FIXED FOR THE TRAJECTORY. The first version re-drew the
   adversarial set every round, so a principal that shed to the floor in round r
   was "honest" at 0.21 in round r+1 and refused for that reason alone. It
   reported 85-95% honest refusal at delta = 0 -- the cost metric was saturated
   before any margin was applied, and would have made every later cost number
   meaningless.

2. STALENESS IS OTHER-CAUSED ONLY. A principal knows its OWN writes; it is
   stale about everyone else's. The first version measured `seen - true` raw,
   which folded in the principal's own prior shedding and reported Delta at
   17-19 of a 20-unit endowment. That is not staleness, it is amnesia, and it
   contradicts the preregistration's own definition of Delta (§2c). Self-caused
   change is now subtracted exactly, via a cumulative-divestment snapshot taken
   alongside the totals snapshot.

3. CONTAINMENT AND PERMISSIVENESS ARE MEASURED ON SEPARATE POPULATIONS. Mixing
   them puts the two measurements in direct tension: honest principals that hold
   their position make concentration UNREACHABLE at large M (32 honest holding
   14 units each cannot let one principal reach 60% of the total), so a bigger
   honest population silently weakens the attack. That is the standard TPR/FPR
   separation -- positives and negatives are different populations -- and
   collapsing it would have produced a guard that looked safe because its
   adversary had been diluted.
"""
from __future__ import annotations

import random
from fractions import Fraction

from env_margin import Fed, U, box_floor

FIXED_COUNT = "FIXED_COUNT"
FIXED_FRACTION = "FIXED_FRACTION"

ADVERSARIAL = "ADVERSARIAL"          # measures containment (violations)
HONEST = "HONEST"                    # measures permissiveness (refusals)

#: how many principals act per round under FIXED_COUNT, at any M
K_ACTORS = 3
#: an honest principal's legitimate per-round divestment: 1% of endowment
HONEST_SHED = U // 100


def run_trial(m: int, delta: Fraction, eps: int, activity: str,
              population: str, n_agents: int, seed: int,
              rounds: int = 40) -> dict:
    rng = random.Random(seed)
    fed = Fed.fresh(m)
    L = box_floor(m, delta)

    cum_div = [0] * m                       # each principal's own divestment
    # A snapshot is (totals, cumulative-divestment). Keeping both is what lets a
    # principal subtract its OWN writes and be stale only about others.
    history: list[tuple[list[int], list[int]]] = [(fed.totals(), list(cum_div))]

    others = list(range(1, m))              # index 0 is the held-out target

    violations = undefined = 0
    attempts = refused = 0
    admitted_volume = 0
    max_other_caused = 0                    # measured Delta, for §2c

    for _ in range(rounds):
        if eps > 0:
            v_tot, v_div = history[max(0, len(history) - 1 - eps)]
        else:
            v_tot = v_div = None

        if activity == FIXED_COUNT:
            acting = rng.sample(others, min(K_ACTORS, len(others)))
        elif activity == FIXED_FRACTION:
            acting = list(others)
            rng.shuffle(acting)
        else:
            raise ValueError(activity)

        for p in acting:
            for _agent in range(n_agents):
                true = fed.total(p)
                if eps > 0:
                    # believed total = snapshot MINUS my own writes since it.
                    # Whatever remains of the error is other-caused, which is
                    # exactly the Delta the closed form is stated over.
                    seen = v_tot[p] - (cum_div[p] - v_div[p])
                    if seen > true:
                        max_other_caused = max(max_other_caused, seen - true)
                else:
                    seen = true                      # PARTITIONED_READ

                if population == ADVERSARIAL:
                    # THE OPTIMAL ADMISSIBLE WITHDRAWAL: to exactly the floor,
                    # judged against the value it read. Admissible for every
                    # agent separately; their sum is not.
                    want = seen - L
                else:
                    want = HONEST_SHED
                attempts += 1

                if want <= 0:
                    continue
                if seen - want < L:                          # THE LOCAL CHECK
                    refused += 1
                    continue
                got = fed.reduce_total(p, want)
                cum_div[p] += got
                admitted_volume += got

        history.append((fed.totals(), list(cum_div)))
        v = fed.concentration_exceeds()
        if v is None:
            undefined += 1                                   # GATE 0c: excluded
        elif v:
            violations += 1

    return {
        "violations": violations,
        "scored_rounds": rounds - undefined,
        "undefined_rounds": undefined,
        "attempts": attempts,
        "refused": refused,
        "admitted_volume": admitted_volume,
        "max_other_caused": max_other_caused,
        "L": L,
    }


def cell(m, delta, eps, activity, population, n_agents, seeds=5,
         rounds=40) -> dict:
    """Fold `seeds` trajectories. A cell is SAFE iff no seed ever violated."""
    acc = {"violations": 0, "scored_rounds": 0, "undefined_rounds": 0,
           "attempts": 0, "refused": 0, "admitted_volume": 0,
           "max_other_caused": 0}
    for s in range(seeds):
        r = run_trial(m, delta, eps, activity, population, n_agents, s, rounds)
        for k in acc:
            acc[k] = (max(acc[k], r[k]) if k == "max_other_caused"
                      else acc[k] + r[k])
    acc["safe"] = acc["violations"] == 0
    # 0/0 IS NOT 0. Writing 0.0 for "no attempt was made" would report a
    # perfectly permissive guard where in fact nothing was measured.
    acc["refusal_rate"] = (acc["refused"] / acc["attempts"]
                           if acc["attempts"] else None)
    return acc


__all__ = ["run_trial", "cell", "FIXED_COUNT", "FIXED_FRACTION",
           "ADVERSARIAL", "HONEST", "K_ACTORS", "HONEST_SHED"]
