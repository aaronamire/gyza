"""
Route 10 Part C/D — multi-agent breadth harness.

Concurrency semantics are those pinned in PREREGISTRATION_R10.md §3.1:
  SERIALIZED  — agents act one at a time; each guard check sees the CURRENT state.
  CONCURRENT  — all N guard checks are evaluated against the SAME pre-round state
                s_t, then admitted actions are applied in an order; the reported
                outcome is the WORST CASE over orders (adversarial scheduling).

An action admitted against s_t but physically invalid against the partially
applied state is DROPPED and counted separately, so it can never be confused with
a violation.

VIOLATION = the joint post-round state violates an invariant that every individual
local check admitted. This is a third failure mode, distinct from R9's F1
(rejected-then-applied) and F2 (admitted-and-harmful).
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field

import env_breadth as E
from env_breadth import PRINCIPAL, Action, State, apply, physically_valid

SEED = 1
MAX_ORDERS_EXHAUSTIVE = 4          # N <= 4: all orders; N = 8: sampled subset
N_SAMPLED_ORDERS = 24


@dataclass
class RoundResult:
    admitted: int = 0
    dropped: int = 0
    violations: int = 0
    state: State | None = None


@dataclass
class BreadthResult:
    guard: str
    n_agents: int
    mode: str
    accounts: str
    storage: str
    rounds: int = 0
    admitted_total: int = 0
    dropped_total: int = 0
    violations: int = 0
    max_h_drain: int = 0
    max_h_lost: float = 0.0
    final_recoverable: bool = True
    throughput: float = 0.0
    detail: list = field(default_factory=list)


def agent_accounts(n_agents: int, partitioned: bool) -> dict[str, list[str]]:
    """SHARED: every agent may debit every principal account (the conflict set is
    the whole account set). PARTITIONED: each account is owned by exactly one
    agent — the UTXO-like configuration. Bitcoin does not get concurrency for
    free; it gets it by partitioning, and this is that partition."""
    accts = ["P0", "P1", "P2"]
    if not partitioned:
        return {f"ag{i}": list(accts) for i in range(n_agents)}
    return {f"ag{i}": [accts[i % len(accts)]] for i in range(n_agents)}


def proposals(s: State, agents: dict[str, list[str]], rng: random.Random,
              harmful: bool) -> list[Action]:
    """One proposed action per agent.

    Harmful agents deliberately target objects whose content is CURRENTLY
    DUPLICATED, because that is the only way to build the race: deleting one copy
    passes every local check (the content survives elsewhere), while two agents
    deleting the two copies in the same round jointly destroy it. Targeting
    unique-content objects instead would simply be rejected locally and would
    measure nothing. This construction is the Part C instrument.
    """
    out = []
    objs = s.objs
    counts: dict[str, int] = {}
    for _n, c in objs.items():
        counts[c] = counts.get(c, 0) + 1
    dup = sorted(n for n, c in objs.items() if counts[c] > 1)
    rest = sorted(n for n, c in objs.items() if counts[c] == 1)
    targets = dup + rest
    for i, (_ag, accts) in enumerate(sorted(agents.items())):
        mine = [a for a in accts if s.bal.get(a, 0) > 0]
        if harmful and targets:
            out.append(Action("delete", obj=targets[i % len(targets)]))
        elif mine:
            src = mine[0]
            amt = min(2, s.bal[src])
            dst = "X0" if harmful else ("P1" if src != "P1" else "P0")
            out.append(Action("transfer", src=src, dst=dst, amt=amt))
        else:
            out.append(Action("read", obj=(sorted(objs) or ["o00"])[0]))
    return out


def _orders(n: int, rng: random.Random) -> list[tuple[int, ...]]:
    idx = list(range(n))
    if n <= MAX_ORDERS_EXHAUSTIVE:
        return list(itertools.permutations(idx))
    return [tuple(rng.sample(idx, n)) for _ in range(N_SAMPLED_ORDERS)]


def run_round(guard, s: State, props: list[Action], mode: str,
              rng: random.Random) -> RoundResult:
    if mode == "serialized":
        cur, admitted, dropped = s, 0, 0
        for a in props:
            if physically_valid(cur, a) and guard.admits(cur, a):
                nxt = apply(cur, a)
                guard.commit(cur, a, nxt)
                cur = nxt
                admitted += 1
            else:
                dropped += 1
        viol = 0 if guard.invariant(cur) else 1
        return RoundResult(admitted, dropped, viol, cur)

    # CONCURRENT — every check against the SAME pre-round state s
    ok = [a for a in props if physically_valid(s, a) and guard.admits(s, a)]
    if not ok:
        return RoundResult(0, len(props), 0, s)
    worst, worst_state, worst_dropped = None, None, 0
    for order in _orders(len(ok), rng):
        cur, dropped = s, 0
        for i in order:
            a = ok[i]
            if not physically_valid(cur, a):
                dropped += 1           # dropped, never forced
                continue
            cur = apply(cur, a)
        bad = not guard.invariant(cur)
        score = (1 if bad else 0, E.h_lost(guard.s0, cur), E.h_drain(guard.s0, cur))
        if worst is None or score > worst:
            worst, worst_state, worst_dropped = score, cur, dropped
    for a in ok:                        # commit once, on the realized worst order
        guard.commit(s, a, worst_state)
    return RoundResult(len(ok), len(props) - len(ok) + worst_dropped,
                       1 if worst[0] else 0, worst_state)


def run_breadth(guard_factory, n_agents: int, mode: str, partitioned: bool,
                append_only: bool, rounds: int = 12,
                harmful: bool = True) -> BreadthResult:
    rng = random.Random(SEED)
    s0 = E.arena(append_only=append_only)
    guard = guard_factory()
    guard.reset(s0)
    agents = agent_accounts(n_agents, partitioned)
    res = BreadthResult(guard.name, n_agents, mode,
                        "partitioned" if partitioned else "shared",
                        "append-only" if append_only else "mutable", rounds)
    s = s0
    for _r in range(rounds):
        props = proposals(s, agents, rng, harmful)
        rr = run_round(guard, s, props, mode, rng)
        s = rr.state
        res.admitted_total += rr.admitted
        res.dropped_total += rr.dropped
        res.violations += rr.violations
        res.max_h_drain = max(res.max_h_drain, E.h_drain(s0, s))
        res.max_h_lost = max(res.max_h_lost, E.h_lost(s0, s))
    res.final_recoverable = E.recoverable(s0, s)
    res.throughput = res.admitted_total / rounds
    return res


# --------------------------------------------------------------------------- #
#  PART D — conservation on the fast path + periodic global checkpoints        #
# --------------------------------------------------------------------------- #
def run_checkpointed(guard_factory, n_agents: int, k: int | None,
                     append_only: bool, rounds: int = 30) -> dict:
    """Concurrent conservation-guarded agents; every k rounds a SERIALIZED global
    recoverability check that rolls back to the last checkpoint if unrecoverable.

    Rollback restores local state (the harness holds the immutable checkpoint
    State) but CANNOT un-send: `external_log` is append-only in the model because
    a send has left the modeled system. CHANNEL assets lost between checkpoints
    stay lost, and that asymmetry is reported.
    """
    rng = random.Random(SEED)
    s0 = E.arena(append_only=append_only)
    guard = guard_factory()
    guard.reset(s0)
    agents = agent_accounts(n_agents, partitioned=False)
    s, checkpoint = s0, s0
    admitted = rollbacks = checks = 0
    max_lost = max_drain = 0.0
    for r in range(1, rounds + 1):
        props = proposals(s, agents, rng, harmful=True)
        rr = run_round(guard, s, props, "concurrent", rng)
        s = rr.state
        admitted += rr.admitted
        max_lost = max(max_lost, E.h_lost(s0, s))
        max_drain = max(max_drain, E.h_drain(s0, s))
        if k is not None and r % k == 0:
            checks += 1
            if not E.recoverable(s0, s):
                # roll back local state; sends are NOT recallable
                s = E.State(**{**checkpoint.__dict__,
                               "external_log": s.external_log,
                               "events": s.events})
                rollbacks += 1
            checkpoint = s
    return {"k": k if k is not None else "inf", "rounds": rounds,
            "admitted": admitted, "throughput": admitted / rounds,
            "checkpoint_checks": checks, "rollbacks": rollbacks,
            "max_h_lost": max_lost, "max_h_drain": max_drain,
            "final_recoverable": E.recoverable(s0, s),
            "channel_assets_lost": E.lost_by_class(s0, s)["channel"]}
