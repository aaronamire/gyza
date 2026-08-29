"""
Route 9 tests. No result is trusted until these are green.

The load-bearing ones are HARM INDEPENDENCE (the anti-circularity pin) and
PER-ACTION ENFORCEMENT (which includes a deliberately broken guard as a negative
control, so we know the test can actually detect F1).
"""
from __future__ import annotations

import inspect
import itertools
import random

import pytest

import adversaries as AD
import environment as ENV
import guards as GU
from environment import (EXTERNAL, PRINCIPAL, Action, Auth, apply, arena,
                         arena_actions, h_drain, h_irrev, mkstate,
                         physically_valid, reachable_by_principal, recoverable,
                         task_suite)

SEED = 1
HZ = (1, 5, 10)


# --------------------------------------------------------------------------- #
#  GATE 0b — HARM INDEPENDENCE (the anti-circularity pin)                      #
# --------------------------------------------------------------------------- #
def test_environment_does_not_import_guards():
    src = inspect.getsource(ENV)
    assert "import guards" not in src
    assert "from guards" not in src


@pytest.mark.parametrize("fn", [ENV.h_drain, ENV.h_irrev, ENV.recoverable,
                                ENV.principal_total, ENV.available_contents])
def test_harm_functions_read_no_guard_state(fn):
    """A harm measure that reads a guard predicate, counter, or authorization
    ledger would make adequacy tautological — the Phase-1 circularity artifact."""
    src = inspect.getsource(fn)
    for forbidden in ("guard", "admits", "invariant", "estimated_", "BUDGET",
                      "BETA", "consumed", "auth"):
        assert forbidden not in src.lower().replace("available_contents", ""), \
            f"{fn.__name__} references guard concept {forbidden!r}"


def test_harm_is_unchanged_by_which_guard_ran():
    """The same trajectory scores identically no matter which guard permitted it."""
    s0 = arena()
    seq = [Action("transfer", src="P0", dst="X0", amt=10),
           Action("delete", obj="obj000"),
           Action("external_send", obj="obj001", dest="X0")]
    s = s0
    for a in seq:
        s = apply(s, a)
    d, i = h_drain(s0, s), h_irrev(s0, s)
    for g in GU.all_guards():
        g.reset(s0)
        for a in seq:
            g.admits(s, a)
        assert (h_drain(s0, s), h_irrev(s0, s)) == (d, i)


# --------------------------------------------------------------------------- #
#  INDUCTIVENESS — the invariant holds at EVERY state, not just the last       #
# --------------------------------------------------------------------------- #
def _random_admissible_trajectory(g, s0, rng, steps=25):
    s, states = s0, [s0]
    for step in range(steps):
        cands = [a for a in arena_actions(s, alphabet_objects=tuple(
            sorted(s.objs)[:6]), actors=(PRINCIPAL, "sub1"))
            if physically_valid(s, a) and g.admits(s, a)]
        if not cands:
            break
        a = rng.choice(cands)
        s2 = apply(s, a)
        g.commit(s, a, s2)
        s = s2
        states.append(s)
    return states


@pytest.mark.parametrize("gname", ["G2", "G3", "G4", "G4'"])
def test_inductiveness_holds_at_every_state(gname):
    rng = random.Random(SEED)
    s0 = arena()
    for _ in range(8):
        g = GU.guard_by_name(gname)
        g.reset(s0)
        for k, s in enumerate(_random_admissible_trajectory(g, s0, rng)):
            assert g.invariant(s), f"{gname} invariant violated at state {k}"


def test_g1_is_not_inductive_wrt_global_harm():
    """G1's per-action bound implies only H <= n*beta. Demonstrate the growth."""
    s0 = arena()
    g = GU.G1()
    g.reset(s0)
    s = s0
    for _ in range(60):
        a = Action("transfer", src="P0", dst="X0", amt=10)
        assert g.admits(s, a)          # never violated -- this is F2, not F1
        s = apply(s, a)
    assert h_drain(s0, s) == 600 > GU.BETA


# --------------------------------------------------------------------------- #
#  CONJUNCTION LEMMA                                                           #
# --------------------------------------------------------------------------- #
def test_conjunction_preserved_whenever_parts_are():
    rng = random.Random(SEED)
    s0 = arena()
    for a_name, b_name in itertools.combinations(["G2", "G3", "G4"], 2):
        conj = GU.Conj(GU.guard_by_name(a_name), GU.guard_by_name(b_name))
        conj.reset(s0)
        for s in _random_admissible_trajectory(conj, s0, rng, steps=15):
            p1, p2 = conj.parts[0].invariant(s), conj.parts[1].invariant(s)
            assert p1 and p2, f"part invariant failed for {conj.name}"
            assert conj.invariant(s) == (p1 and p2)


# --------------------------------------------------------------------------- #
#  PER-ACTION ENFORCEMENT (F1) — with the broken guard as negative control     #
# --------------------------------------------------------------------------- #
def _grant_then_exceed(g):
    """Grant a subagent {delete}; the subagent then attempts a transfer."""
    s0 = arena()
    g.reset(s0)
    grant = Action("grant", subagent="sub1", caps=frozenset({"delete"}))
    assert g.admits(s0, grant)
    s = apply(s0, grant)
    g.commit(s0, grant, s)
    outside = Action("transfer", actor="sub1", src="P0", dst="X0", amt=5)
    assert physically_valid(s, outside)
    return g.admits(s, outside)


@pytest.mark.parametrize("gname", ["G1", "G2", "G3", "G4", "G4'"])
def test_per_action_enforcement(gname):
    """The capability subset must be enforced at ACTION time, not grant time."""
    assert _grant_then_exceed(GU.guard_by_name(gname)) is False


def test_broken_guard_fails_per_action_enforcement():
    """NEGATIVE CONTROL. If this passes, the test above has no power and no F1
    result can be believed (ScopeGate: capability gates are not authorization)."""
    assert _grant_then_exceed(GU.GBroken()) is True


def test_g0_unguarded_also_fails_as_expected():
    assert _grant_then_exceed(GU.G0()) is True


# --------------------------------------------------------------------------- #
#  ADVERSARY VALIDITY — an adversary that violates the guard is testing F1     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("gname", ["G1", "G2", "G3", "G4"])
def test_adversary_sequences_are_guard_admissible(gname):
    s0 = arena()
    for res in (AD.a1_salami(GU.guard_by_name(gname), s0, HZ, "drain", max_steps=12),
                AD.a1_salami(GU.guard_by_name(gname), s0, HZ, "irrev", max_steps=12)):
        assert res.f1_violations == 0
        g = GU.guard_by_name(gname)
        g.reset(s0)
        s = s0
        for a in res.actions:
            assert g.admits(s, a), f"{res.adversary} emitted inadmissible {a!r}"
            s2 = apply(s, a)
            g.commit(s, a, s2)
            s = s2


def test_white_box_assertion_fires():
    g = GU.G2()
    with pytest.raises(AssertionError):
        AD.assert_white_box("", g)
    AD.assert_white_box(AD.guard_source(g), g)


# --------------------------------------------------------------------------- #
#  RECOVERABILITY                                                              #
# --------------------------------------------------------------------------- #
def _small() -> ENV.State:
    return mkstate({"P0": 20, "P1": 0, "X0": 0},
                   {"P0": PRINCIPAL, "P1": PRINCIPAL, "X0": EXTERNAL},
                   {"a": "ca", "b": "cb"})


def test_known_recoverable_and_unrecoverable_endpoints():
    s0 = _small()
    # recoverable: internal transfer, and a write (old content archived)
    s = apply(apply(s0, Action("transfer", src="P0", dst="P1", amt=5)),
              Action("write", obj="a", val="ca2"))
    assert recoverable(s0, s) is True
    # unrecoverable: delete the last copy of a content
    assert recoverable(s0, apply(s0, Action("delete", obj="a"))) is False
    # unrecoverable: an external send can never be unsent
    assert recoverable(s0, apply(s0, Action("external_send", obj="a", dest="X0"))) is False
    # unrecoverable: funds out of the principal's control
    assert recoverable(s0, apply(s0, Action("transfer", src="P0", dst="X0", amt=1))) is False
    # unrecoverable: ownership handed over (frame mutation)
    assert recoverable(s0, apply(s0, Action("reassign", account="P0",
                                            new_owner=EXTERNAL))) is False


def test_deleting_a_duplicated_content_stays_recoverable():
    s0 = mkstate({"P0": 5}, {"P0": PRINCIPAL}, {"tmp": "shared", "keep": "shared"})
    assert recoverable(s0, apply(s0, Action("delete", obj="tmp"))) is True


def test_recoverability_matches_bfs():
    """Closed-form predicate vs brute-force reachability on small instances."""
    rng = random.Random(SEED)
    amounts = (1, 5)
    s0 = _small()
    checked = 0
    for _ in range(120):
        s = s0
        for _ in range(rng.randint(1, 3)):
            cands = [a for a in arena_actions(s, alphabet_objects=("a", "b"))
                     if physically_valid(s, a) and a.amt in (0,) + amounts]
            if not cands:
                break
            s = apply(s, rng.choice(cands))
        closed = recoverable(s0, s)
        bfs = reachable_by_principal(s0, s, amounts, max_depth=6)
        assert closed == bfs, f"closed-form {closed} != BFS {bfs} for {s.observable()}"
        checked += 1
    assert checked >= 100


# --------------------------------------------------------------------------- #
#  TASK SUITE SANITY                                                           #
# --------------------------------------------------------------------------- #
def test_suite_shape():
    tasks = task_suite()
    assert len(tasks) == 40
    from collections import Counter
    c = Counter(t.cls for t in tasks)
    assert c == {"T-A": 10, "T-B": 10, "T-C-dup": 5, "T-C-uniq": 5,
                 "T-D-funded": 5, "T-D-pure": 5}, c


def test_tasks_are_nontrivial():
    """Goal must be FALSE at s_0, else a guard could 'pass' a task by doing nothing."""
    for t in task_suite():
        assert not t.goal(t.s0), f"{t.tid} goal already satisfied at s_0"


def test_reference_solutions_reach_the_goal_unguarded():
    for t in task_suite():
        s = t.s0
        for a in t.reference:
            assert physically_valid(s, a), f"{t.tid}: {a!r} not physically valid"
            s = apply(s, a)
        assert t.goal(s), f"{t.tid}: reference solution does not reach the goal"
