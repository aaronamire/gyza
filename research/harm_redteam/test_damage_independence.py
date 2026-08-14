"""T1/T2/T3 — the damage measures cannot see the guard.

PREREGISTERED (§3) as a precondition: these must pass before any attack is
scored. Reconstructing a harm model from the guard is circular and forbidden
(standing discipline #5), and a red team whose damage measure reads guard state
would be grading the guard against itself.

Run:
  ~/dev/marshal/.os/bin/python -m pytest research/harm_redteam/ -q
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import damage as D                                            # noqa: E402

MEASURES = [D.d1_unpaid_delivered_work, D.d2_lockout_breadth,
            D.d3_frame_multiplied_drain, D.drawdown]


class _E:
    """A ledger entry's shape, as the environment sees it."""
    def __init__(self, frm, to, amt, *, delivered=True, settled=False):
        self.from_compositor, self.to_compositor = frm, to
        self.amount_credits = amt
        self.to_signature = "sig" if delivered else ""
        self.settled = settled


# --------------------------------------------------------------------------- #
#  T1 — no guard import anywhere in the damage module                          #
# --------------------------------------------------------------------------- #
def test_T1_the_damage_module_imports_no_guard():
    tree = ast.parse((HERE / "damage.py").read_text())
    imported: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            imported.append(n.module or "")
    banned = [m for m in imported
              if "containment" in m or "guard" in m or m.startswith("gyza.")]
    assert banned == [], f"the damage module imports guard machinery: {banned}"


# --------------------------------------------------------------------------- #
#  T2 — source inspection over EVERY measure                                   #
# --------------------------------------------------------------------------- #
def test_T2_no_measure_references_a_guard_or_a_bound():
    forbidden = ("bound", "guard", "GuardEngine", "Decision", "admit",
                 "containment", "invariant", "harm_class")
    for fn in MEASURES:
        src = inspect.getsource(fn)
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        code = code.replace('"""', "\x00").split("\x00")
        code = "".join(code[::2])          # drop docstrings, keep code
        hits = [w for w in forbidden if w in code]
        assert hits == [], f"{fn.__name__} references {hits}"


def test_T2b_the_measures_do_not_share_a_fold_with_the_guard():
    """`drawdown` deliberately reimplements the balance rather than calling
    `Wallet`. If they shared a fold, a defect in it would move the guard and the
    damage measure together and the comparison would be vacuous."""
    src = inspect.getsource(D.drawdown)
    assert "Wallet" not in src.split('"""')[2]


# --------------------------------------------------------------------------- #
#  T3 — identical damage under every guard configuration                       #
# --------------------------------------------------------------------------- #
def test_T3_damage_is_identical_under_every_guard_configuration():
    """The same trajectory, scored three ways. The measures take only entries,
    so this cannot differ -- which is the point: it is pinned, not assumed."""
    traj = [_E("op", "earnerA", 60.0, settled=True),
            _E("op", "earnerA", 60.0, settled=False),
            _E("op", "earnerB", 40.0, settled=False)]

    from gyza.containment.engine import GuardEngine          # noqa: F401
    from gyza.containment.gyza_model import build_registries

    scores = []
    for bounds_file in (None, "default"):
        # building a guard at all must not change the environment's numbers
        if bounds_file == "default":
            build_registries()
        else:
            build_registries(bounds_file=None)
        scores.append((D.d1_unpaid_delivered_work(traj),
                       D.d2_lockout_breadth(traj),
                       D.d3_frame_multiplied_drain(traj, ["op"])))
    # and once with no guard constructed at all
    scores.append((D.d1_unpaid_delivered_work(traj),
                   D.d2_lockout_breadth(traj),
                   D.d3_frame_multiplied_drain(traj, ["op"])))
    assert len(set(scores)) == 1, f"damage moved with guard configuration: {scores}"


# --------------------------------------------------------------------------- #
#  The measures actually measure something                                     #
# --------------------------------------------------------------------------- #
def test_the_measures_are_not_vacuous():
    traj = [_E("op", "A", 60.0, settled=True),
            _E("op", "A", 60.0, settled=False),
            _E("op", "B", 40.0, settled=False)]
    assert D.d1_unpaid_delivered_work(traj) == 100.0
    assert D.d2_lockout_breadth(traj) == 1          # B got nothing; A got paid
    assert D.drawdown(traj, "op") == 60.0           # only settled counts

    # an entry never delivered is not damage: nobody did the work
    assert D.d1_unpaid_delivered_work(
        [_E("op", "A", 99.0, delivered=False)]) == 0.0


def test_an_HONEST_trajectory_scores_zero():
    """The control the whole exercise rests on. If a fully-settled trajectory
    scored damage, D1 would be measuring 'settlement happened'."""
    traj = [_E("op", "A", 60.0, settled=True), _E("op", "B", 30.0, settled=True)]
    assert D.d1_unpaid_delivered_work(traj) == 0.0
    assert D.d2_lockout_breadth(traj) == 0
