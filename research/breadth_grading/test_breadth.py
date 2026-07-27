"""
Route 10 tests. No result is trusted until these are green.

The load-bearing ones are the CONCURRENCY RACE (without it the Part C nulls have
no power) and H_lost-IS-A-MEASURE (without it H_lost is R9 §3.2's error in new
clothes).
"""
from __future__ import annotations

import inspect
import itertools
import random

import pytest

import agents as AG
import env_breadth as E
import guards_graded as G
from env_breadth import (EXTERNAL, PRINCIPAL, Action, apply, arena, h_lost,
                         mkstate, physically_valid)

SEED = 1


# --------------------------------------------------------------------------- #
#  GATE 0b — HARM INDEPENDENCE                                                 #
# --------------------------------------------------------------------------- #
def test_environment_imports_no_guard_module():
    src = inspect.getsource(E)
    for bad in ("import guards", "from guards", "guards_graded"):
        assert bad not in src


@pytest.mark.parametrize("fn", [E.h_drain, E.h_irrev, E.h_lost, E.lost_by_class,
                                E.asset_classes, E.principal_total])
def test_harm_functions_read_no_guard_state(fn):
    src = inspect.getsource(fn).lower()
    for bad in ("guard", "admits", "invariant", "estimated_", "budget", "theta"):
        assert bad not in src, f"{fn.__name__} references guard concept {bad!r}"


def test_same_trajectory_scores_identically_under_all_guards():
    s0 = arena()
    seq = [Action("delete", obj="o00"), Action("transfer", src="P0", dst="X0", amt=2)]
    s = s0
    for a in seq:
        s = apply(s, a)
    ref = (E.h_drain(s0, s), E.h_irrev(s0, s), E.h_lost(s0, s))
    for g in (G.G0(), G.G2(), G.G3(), G.G4(), G.G5(0.1), G.G5(0.5)):
        g.reset(s0)
        for a in seq:
            g.admits(s0, a)
        assert (E.h_drain(s0, s), E.h_irrev(s0, s), E.h_lost(s0, s)) == ref


# --------------------------------------------------------------------------- #
#  H_lost IS A MEASURE, NOT A COUNT                                            #
# --------------------------------------------------------------------------- #
def test_h_lost_is_a_measure_not_a_count():
    """Same number of irreversible actions, different amounts of lost state.

    An action count would be an additive bound over action shapes — exactly R9
    §3.2's error, the one that let G1/G2 lose 100% while their invariants held."""
    s0 = arena()
    cheap = apply(apply(s0, Action("delete", obj="o14")),
                  Action("delete", obj="o16"))     # both duplicated: nothing lost
    dear = apply(apply(s0, Action("delete", obj="o00")),
                 Action("delete", obj="o01"))      # both unique: two contents gone
    assert len([e for e in cheap.events if e[0] == "delete"]) == \
           len([e for e in dear.events if e[0] == "delete"]) == 2
    assert h_lost(s0, cheap) == 0.0
    assert h_lost(s0, dear) > 0.0
    assert h_lost(s0, dear) > h_lost(s0, cheap)


def test_h_lost_monotone():
    rng = random.Random(SEED)
    s0 = arena()
    for _ in range(10):
        s, prev = s0, 0.0
        for _ in range(20):
            cands = [a for a in E.arena_actions(s, alphabet_objects=tuple(
                sorted(s.objs)[:8])) if physically_valid(s, a)]
            if not cands:
                break
            s = apply(s, rng.choice(cands))
            cur = h_lost(s0, s)
            assert cur >= prev - 1e-12, f"h_lost decreased {prev} -> {cur}"
            prev = cur


def test_no_resurrection_rule_holds():
    s0 = arena()
    s = apply(s0, Action("delete", obj="o00"))
    assert not physically_valid(s, Action("write", obj="o01", val="c-u00"))
    assert physically_valid(s, Action("write", obj="o01", val="brand-new"))


def test_no_spending_what_you_do_not_control():
    s0 = arena()
    assert not physically_valid(s0, Action("transfer", src="X0", dst="P0", amt=0))
    s = apply(s0, Action("reassign", account="P2", new_owner=EXTERNAL))
    assert not physically_valid(s, Action("transfer", src="P2", dst="P0", amt=1))


# --------------------------------------------------------------------------- #
#  GATE 0c — BFS IS GROUND TRUTH                                               #
# --------------------------------------------------------------------------- #
def _small():
    return mkstate({"P0": 3, "P1": 1, "X0": 0},
                   {"P0": PRINCIPAL, "P1": PRINCIPAL, "X0": EXTERNAL},
                   {"a": "ca", "b": "cb", "c": "ca"})


@pytest.mark.parametrize("seq", [
    [],
    [Action("transfer", src="P0", dst="P1", amt=1)],
    [Action("delete", obj="a")],                       # 'ca' survives at 'c'
    [Action("delete", obj="a"), Action("delete", obj="c")],   # 'ca' gone
    [Action("delete", obj="b")],                       # 'cb' unique -> gone
    [Action("write", obj="a", val="new")],
    [Action("reassign", account="P1", new_owner=EXTERNAL)],   # REGRESSION (R9 #1)
])
def test_goal_directed_agrees_with_blind_bfs(seq):
    """GATE 0c: the optimization is validated against the definition, every case.
    Disagreement is a FINDING, never silently patched."""
    s0 = _small()
    s = s0
    for a in seq:
        s = apply(s, a)
    blind = E.reachable_blind(s0, s, (1, 2))
    goal = E.reachable_goal(s0, s, (1, 2))
    assert blind == goal, f"DISAGREEMENT (report, do not patch): {seq} " \
                          f"blind={blind} goal={goal}"


def test_zero_balance_reassign_regression():
    """R9 correction #1: handing away a ZERO-BALANCE principal account moves no
    resource but is unrecoverable, since reassign is one-directional."""
    s0 = mkstate({"P0": 2, "P1": 0}, {"P0": PRINCIPAL, "P1": PRINCIPAL},
                 {"a": "ca"})
    s = apply(s0, Action("reassign", account="P1", new_owner=EXTERNAL))
    assert E.reachable_blind(s0, s, (1, 2)) is False
    assert E.recoverable(s0, s, (1, 2)) is False


def test_snapshot_restore_regression_is_not_applicable():
    """R12's breakage was snapshot+delete. R10's vocabulary has no snapshot /
    restore, so the case cannot arise here — recorded rather than silently
    dropped."""
    assert not any(a.kind in ("snapshot", "restore")
                   for a in E.arena_actions(arena()))


# --------------------------------------------------------------------------- #
#  G5(0) == G3                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("variant", list(E.VARIANTS))
def test_g5_zero_equals_g3(variant):
    s0 = arena()
    acts = [a for a in E.arena_actions(s0) if physically_valid(s0, a)]
    g5, g3 = G.G5(0.0, variant), G.G3()
    g5.reset(s0)
    g3.reset(s0)
    assert {a.key() for a in acts if g5.admits(s0, a)} == \
           {a.key() for a in acts if g3.admits(s0, a)}


# --------------------------------------------------------------------------- #
#  CONCURRENCY RACE — without this the Part C nulls have no power              #
# --------------------------------------------------------------------------- #
def _race_state(append_only: bool):
    """Content X lives in exactly two objects, O and L."""
    return mkstate({"P0": 2}, {"P0": PRINCIPAL},
                   {"O": "X", "L": "X", "keep": "K"}, append_only=append_only)


def test_concurrency_race_each_local_check_passes_joint_state_is_unrecoverable():
    s0 = _race_state(append_only=False)
    a = Action("delete", obj="O")
    b = Action("delete", obj="L")
    g = G.G3()
    g.reset(s0)
    assert g.admits(s0, a), "A's local check must pass (X survives at L)"
    assert g.admits(s0, b), "B's local check must pass (X survives at O)"
    joint = apply(apply(s0, a), b)
    assert not E.recoverable(s0, joint), "joint state must be unrecoverable"
    assert h_lost(s0, joint) > 0.0
    assert not g.invariant(joint), "the harness must detect the composition failure"


def test_append_only_makes_the_race_impossible():
    """H-APPEND: if deletion archives rather than destroys, no agent's action can
    invalidate another's recoverability claim."""
    s0 = _race_state(append_only=True)
    a, b = Action("delete", obj="O"), Action("delete", obj="L")
    g = G.G3()
    g.reset(s0)
    assert g.admits(s0, a) and g.admits(s0, b)
    joint = apply(apply(s0, a), b)
    assert E.recoverable(s0, joint), "append-only must keep the joint state recoverable"
    assert h_lost(s0, joint) == 0.0
    assert g.invariant(joint)


def test_append_only_has_a_cost_nothing_is_ever_freed():
    """The rescue is not free: deletion no longer frees anything."""
    s0 = _race_state(append_only=True)
    s = apply(s0, Action("delete", obj="O"))
    assert "X" in s.archive and "X" in E.available_contents(s)


# --------------------------------------------------------------------------- #
#  ORDER SENSITIVITY                                                           #
# --------------------------------------------------------------------------- #
def test_order_sensitivity_all_orders_evaluated():
    rng = random.Random(SEED)
    for n in (2, 3, 4):
        assert len(AG._orders(n, rng)) == len(list(itertools.permutations(range(n))))
    assert len(AG._orders(8, rng)) == AG.N_SAMPLED_ORDERS


def test_concurrent_round_reports_worst_case_over_orders():
    s0 = _race_state(append_only=False)
    g = G.G3()
    g.reset(s0)
    rr = AG.run_round(g, s0, [Action("delete", obj="O"), Action("delete", obj="L")],
                      "concurrent", random.Random(SEED))
    assert rr.admitted == 2, "both were admitted against the pre-round state"
    assert rr.violations == 1, "the joint state violates what both local checks passed"
