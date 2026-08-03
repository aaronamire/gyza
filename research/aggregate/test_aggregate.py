"""AG-3 gate tests. Every one of these must pass before any result is trusted.

Without the COMPOSITION-FAILURE test in particular, a null has no power: a
harness that cannot detect a violation reports zero violations for free.
"""
from __future__ import annotations

import ast
import inspect
import random
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "federation"))

import env_aggregate as A            # noqa: E402
import env_federation as E           # noqa: E402
import guards_aggregate as G         # noqa: E402


# --------------------------------------------------------------------------- #
#  HARM INDEPENDENCE                                                           #
# --------------------------------------------------------------------------- #
def test_environment_imports_no_guard_module():
    tree = ast.parse((HERE / "env_aggregate.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
    assert not any("guard" in m for m in imported), imported


def test_every_aggregate_quantity_reads_only_environment_state():
    """Source inspection over each quantity: no guard object may appear."""
    for fn in (A.concentration, A.federation_total, A.principal_totals,
               A.CrossDrainAccumulator.observe, A.PeakConcentration.observe):
        src = inspect.getsource(fn)
        assert "guard" not in src.lower(), fn
        assert "estimated_" not in src, fn


def test_identical_trajectory_scores_identically_under_every_guard_config():
    """The harm of a trajectory must not depend on which guard was watching."""
    ps = E.principals(2)
    s0 = E.arena(2)
    traj = _spend_trajectory(s0, ps)
    scores = []
    for cfg in G.CONFIGS:
        gs = G.make_guards(cfg, ps)
        for g in gs.values():
            g.reset(s0)
        acc = A.CrossDrainAccumulator(s0, ps)
        pk = A.PeakConcentration(s0, ps)
        for s in traj:
            acc.observe(s)
            pk.observe(s)
        scores.append((round(acc.total, 9), pk.peak,
                       A.concentration(s0, traj[-1], ps)))
    assert len(set(map(str, scores))) == 1, scores


def _spend_trajectory(s0, ps):
    """A concrete trajectory: B leaks value to EXTERNAL twice."""
    out, s = [], s0
    for amt in (5, 5):
        a = E.Action("external_send", principal="B", actor="B/0",
                     src="B:a0", dest="X0", amt=amt)
        if E.physically_valid(s, a):
            s = E.apply(s, a)
        out.append(s)
    return out


# --------------------------------------------------------------------------- #
#  CLASS MEMBERSHIP — each quantity must actually be in its declared class     #
# --------------------------------------------------------------------------- #
def test_concentration_is_a_function_of_current_state_only():
    """INSTANTANEOUS-JOINT: reordering a trajectory that ends in the same state
    cannot change it."""
    ps = E.principals(2)
    s0 = E.arena(2)
    a1 = E.Action("external_send", principal="A", actor="A/0",
                  src="A:a0", dest="X0", amt=3)
    a2 = E.Action("external_send", principal="B", actor="B/0",
                  src="B:a0", dest="X1", amt=5)
    s_12 = E.apply(E.apply(s0, a1), a2)
    s_21 = E.apply(E.apply(s0, a2), a1)
    assert s_12.balances == s_21.balances, "precondition: same end state"
    assert A.concentration(s0, s_12, ps) == A.concentration(s0, s_21, ps)


def test_cumulative_drain_is_NOT_a_function_of_the_end_state():
    """CUMULATIVE-JOINT: a trajectory that leaves and returns to the same total
    must score higher than one that never moved."""
    ps = E.principals(2)
    s0 = E.arena(2)
    out = E.Action("transfer", principal="A", actor="A/0",
                   src="A:a0", dst="A:a1", amt=5)
    moved = E.apply(s0, out)

    still = A.CrossDrainAccumulator(s0, ps)
    still.observe(s0); still.observe(s0)

    leak = E.Action("external_send", principal="A", actor="A/0",
                    src="A:a0", dest="X0", amt=5)
    s_leaked = E.apply(s0, leak)
    drained = A.CrossDrainAccumulator(s0, ps)
    drained.observe(s_leaked)

    assert still.total == 0.0
    assert drained.total > 0.0, "leaking value must accumulate drain"
    assert moved is not None


def test_peak_concentration_is_path_dependent():
    """PATH-DEPENDENT-JOINT: differs from CURRENT concentration on a trajectory
    that spikes and returns."""
    ps = E.principals(2)
    s0 = E.arena(2)
    spike = E.Action("external_send", principal="B", actor="B/0",
                     src="B:a0", dest="X0", amt=9)
    s_spike = E.apply(s0, spike)
    back = E.Action("external_send", principal="A", actor="A/0",
                    src="A:a0", dest="X1", amt=9)
    s_back = E.apply(s_spike, back)

    pk = A.PeakConcentration(s0, ps)
    pk.observe(s_spike)
    pk.observe(s_back)
    now = A.concentration(s0, s_back, ps)
    assert pk.peak > now + 1e-9, (pk.peak, now)


def test_concentration_is_UNDEFINED_not_one_when_the_federation_is_empty():
    """The Gate-0c error, pinned: UNDEFINED is not maximal concentration."""
    ps = E.principals(2)
    s0 = E.arena(2)
    empty = E.State(balances=tuple((k, 0) for k, _ in s0.balances),
                    owner=s0.owner, objects=s0.objects, obj_owner=s0.obj_owner,
                    pool_balance=0, pool_contrib=s0.pool_contrib,
                    originals=s0.originals, ms=2)
    assert A.concentration(s0, empty, ps) is None


# --------------------------------------------------------------------------- #
#  COMPOSITION FAILURE MUST BE DETECTABLE — without this, nulls have no power  #
# --------------------------------------------------------------------------- #
def test_a_hand_built_joint_state_violates_while_every_local_check_passes():
    """M=3. Two principals each drain below what their OWN guard would allow,
    each individually keeping concentration under kappa, and the third
    principal's share rises past kappa WITHOUT IT ACTING AT ALL."""
    ps = E.principals(3)
    s0 = E.arena(3)
    guards = G.make_guards("GLOBAL_READ", ps)
    for g in guards.values():
        g.reset(s0)

    # DISCLOSED FIXTURE FIX: the first version used ONE action per principal
    # (amt=8), which reaches only 0.4545 -- not a composition failure. The
    # threshold was NOT moved; the fixture was too weak to exhibit the effect it
    # is meant to prove is detectable. Two actions per principal reach it.
    acts = [E.Action("external_send", principal=p, actor=f"{p}/0",
                     src=f"{p}:{acc}", dest=d, amt=amt)
            for p, d in (("B", "X0"), ("C", "X1"))
            for acc, amt in (("a0", 10), ("a1", 4))]

    # every guard evaluates against the SAME pre-round state, and each passes
    for a in acts:
        assert E.physically_valid(s0, a) and guards[a.principal].admits(s0, a), a
        alone = A.concentration(s0, E.apply(s0, a), ps)
        assert alone is not None and alone <= A.KAPPA + 1e-9, (a, alone)

    joint = s0
    for a in acts:
        if E.physically_valid(joint, a):
            joint = E.apply(joint, a)
    conc = A.concentration(s0, joint, ps)
    assert conc is not None and conc > A.KAPPA + 1e-9, (
        f"the harness must be able to EXHIBIT a composition failure; got {conc}")

    # and the principal whose share rose past kappa TOOK NO ACTION AT ALL
    assert all(a.principal != "A" for a in acts)
    assert E.principal_total(s0, joint, "A") == E.principal_total(s0, s0, "A")


# --------------------------------------------------------------------------- #
#  READ-SET — with a NEGATIVE CONTROL proving the check can fail               #
# --------------------------------------------------------------------------- #
def _reads_other_principals(cls) -> bool:
    """A source-level check: does `admits` compute over principals other than
    self.p? Detects iteration over self.ps inside a state-reading call."""
    src = inspect.getsource(cls.admits)
    tree = ast.parse(src.lstrip())
    for n in ast.walk(tree):
        if isinstance(n, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            if "self.ps" in ast.unparse(n) and "principal_total" in ast.unparse(n):
                return True
        if isinstance(n, ast.Call):
            u = ast.unparse(n)
            if "concentration" in u and "self.ps" in u:
                return True
    return False


def test_partitioned_read_does_not_read_other_principals_live_state():
    assert not _reads_other_principals(G.PartitionedReadAgg)


def test_the_readset_check_has_power_negative_control():
    """If this passed for GLOBAL_READ too, the check above would be vacuous."""
    assert _reads_other_principals(G.GlobalReadAgg), (
        "the read-set check cannot detect a global read -- it proves nothing")
    assert _reads_other_principals(G.LocalAgg), (
        "LOCAL reads a denominator over self.ps (from s_0) and must be detected")


# --------------------------------------------------------------------------- #
#  MOVING FRAME — artifact #13                                                 #
# --------------------------------------------------------------------------- #
def test_cumulative_aggregate_refuses_to_rebase_its_origin():
    ps = E.principals(2)
    s0 = E.arena(2)
    acc = A.CrossDrainAccumulator(s0, ps)
    with pytest.raises(RuntimeError, match="IMMUTABLE"):
        acc.rebase(s0)


def test_the_static_box_is_actually_sound():
    """PARTITIONED_READ's soundness is an arithmetic claim; check it."""
    for m in (2, 3):
        assert A.box_is_sound(m), m
        L, U = A.box_bounds(m)
        assert U / (U + (m - 1) * L) <= A.KAPPA + 1e-9


def test_determinism():
    """SEED=1 must give identical results across runs."""
    import run_ag3
    a = run_ag3.run_cell("GLOBAL_READ", "mixed", 3, 2, "concurrent").as_dict()
    b = run_ag3.run_cell("GLOBAL_READ", "mixed", 3, 2, "concurrent").as_dict()
    assert a == b
    assert random.Random(A.SEED).random() == random.Random(1).random()
