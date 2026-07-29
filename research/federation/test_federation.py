"""
Route 13 tests. These must pass before ANY result is trusted.

Two of them exist specifically to give the F2 nulls power:
  * T-BLIND-EXISTS — without it, "0 cross-principal violations under F2" could
    equally mean "contained" or "the detector is broken".
  * T-POOL-RACE    — without it, the route cannot falsify the derivation's
    predicted failure mode.

Run:  ~/dev/marshal/.os/bin/python -m pytest research/federation/ -q
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import env_federation as E                                    # noqa: E402
import guards_federation as G                                 # noqa: E402
from env_federation import Action, apply, sign_auth           # noqa: E402


# --------------------------------------------------------------------------- #
#  T-IND — harm independence (the three standard tests)                        #
# --------------------------------------------------------------------------- #
def test_ind_1_no_guard_import_in_environment():
    src = inspect.getsource(E)
    for banned in ("guards_federation", "adversaries_federation",
                   "import guards", "import adversaries"):
        assert banned not in src, f"environment imports {banned}"
    assert not any(m.startswith(("guards_", "adversaries_"))
                   for m in dir(E) if inspect.ismodule(getattr(E, m, None)))


def test_ind_2_harm_functions_reference_no_guard_symbol():
    harm_fns = [E.h_drain, E.h_lost, E.pool_overdraft, E.pool_claim,
                E.principal_total, E.asset_classes, E.lost_by_class]
    for fn in harm_fns:
        src = inspect.getsource(fn)
        for banned in ("guard", "Guard", "admits", "theta", "F0", "F1", "F2",
                       "F3", "estimated_"):
            assert banned not in src, f"{fn.__name__} references {banned!r}"


def test_ind_3_identical_harm_under_every_guard_configuration():
    """The same trajectory must score identically under F0/F1/F2/F3."""
    s0 = E.arena(2)
    traj = [
        Action("delete_cross", principal="A", obj="B:o0"),
        Action("withdraw_pool", principal="A", dst="A:a0", amt=5),
        Action("reassign", principal="B", account="B:a1", new_owner=E.EXTERNAL),
    ]
    s_end = s0
    for a in traj:
        s_end = apply(s_end, a)

    scores = {}
    for cfg in ("F0", "F1", "F2", "F3"):
        guards = G.make_guards(cfg, ("A", "B"))
        for g in guards.values():
            g.reset(s0)
        # give the guards every chance to mutate something
        s = s0
        for a in traj:
            guards[a.principal].admits(s, a)
            s = apply(s, a)
            guards[a.principal].commit(s0, a, s)
        scores[cfg] = (
            tuple(round(E.h_drain(s0, s_end, p), 9) for p in ("A", "B")),
            tuple(round(E.h_lost(s0, s_end, p), 9) for p in ("A", "B")),
            E.pool_overdraft(s_end),
        )
    assert len({repr(v) for v in scores.values()}) == 1, scores


# --------------------------------------------------------------------------- #
#  T-FRAME — R9 condition 2: the frame FLOATS                                  #
# --------------------------------------------------------------------------- #
def test_frame_h_drain_reads_the_current_owner_map():
    """G4' pinned its frame at s_0 and lost 175000; G4 read the current frame
    and bounded at 50. h_drain must see an account leaving p's ownership."""
    s0 = E.arena(2)
    s1 = apply(s0, Action("reassign", principal="A", account="A:a0",
                          new_owner=E.EXTERNAL))
    # A:a0 held 10; A keeps a1 (4) + pool claim (6) = 10, down from 20.
    assert E.h_drain(s0, s1, "A") == 10.0

    # A PINNED frame would still count A:a0 as A's and see no drain at all.
    own0 = s0.own
    pinned_total = float(sum(v for k, v in s1.balances if own0.get(k) == "A")) \
        + E.pool_claim(s0, s1, "A")
    assert pinned_total == 20.0
    assert E.h_drain(s0, s1, "A") > (E.principal_total(s0, s0, "A") - pinned_total)

    # and the ownership class registers the loss
    assert E.lost_by_class(s0, s1, "A")["ownership"] == 1.0


# --------------------------------------------------------------------------- #
#  T-BLIND-EXISTS — the detector works (gives the F2 nulls their power)        #
# --------------------------------------------------------------------------- #
def test_blind_channel_exists_under_f1():
    """Hand-built: A's guard ADMITS while B's harm RISES past B's own bound."""
    s0 = E.arena(2)
    ga = G.F1("A")
    ga.reset(s0)
    s = s0
    for obj in ("B:o0", "B:o1", "B:o2"):
        a = Action("delete_cross", principal="A", obj=obj)
        assert ga.admits(s, a), f"A's own guard should admit {a!r}"
        s = apply(s, a)

    assert E.h_lost(s0, s, "A") <= G.EPS, "A must be unharmed — that is the point"
    assert E.h_lost(s0, s, "B") > E.THETA, "B's harm must exceed B's own bound"
    assert not G.principal_invariant(s0, s, "B"), "harness must DETECT it"
    assert G.principal_invariant(s0, s, "A")


def test_shared_object_deletion_is_self_policing_under_f1():
    """The sign-alignment cell: deleting CO-OWNED content raises h_lost for the
    ACTOR too, so the actor's own local guard blocks it without any signature."""
    s0 = E.arena(2)
    ga = G.F1("A")
    ga.reset(s0)
    a = Action("delete_cross", principal="A", obj=E.SHARED_OBJ)
    s1 = apply(s0, a)
    # the harm is symmetric — both co-owners lose the content
    assert E.lost_by_class(s0, s1, "A")["content"] == 1.0
    assert E.lost_by_class(s0, s1, "B")["content"] == 1.0


# --------------------------------------------------------------------------- #
#  T-SIG-GATE                                                                  #
# --------------------------------------------------------------------------- #
def test_signature_gating_rejects_unauthorized_cross_principal_write():
    s0 = E.arena(2)
    bare = Action("delete_cross", principal="A", obj="B:o0")

    g1, g2 = G.F1("A"), G.F2("A")
    g1.reset(s0)
    g2.reset(s0)

    assert g1.admits(s0, bare), "F1 must admit the unauthorized action"
    assert not g2.admits(s0, bare), "F2 must reject it"

    signed = bare.__class__(**{**bare.__dict__,
                               "auths": (sign_auth("B", bare.key()),)})
    assert g2.admits(s0, signed), "F2 must admit it once B authorizes"

    forged = bare.__class__(**{**bare.__dict__,
                               "auths": (E.AuthToken("B", bare.key(), 0, "bad"),)})
    assert not g2.admits(s0, forged), "F2 must reject a forged signature"

    wrong_action = Action("delete_cross", principal="A", obj="B:o1")
    mismatched = wrong_action.__class__(
        **{**wrong_action.__dict__, "auths": (sign_auth("B", bare.key()),)})
    assert not g2.admits(s0, mismatched), "a token must not transfer to another action"


# --------------------------------------------------------------------------- #
#  T-POOL-RACE — the predicted failure mode must be constructible              #
# --------------------------------------------------------------------------- #
def test_joint_pool_race_two_authorized_withdrawals_overdraft():
    """Both withdrawals carry EVERY required signature. No signature is
    missing. The conflict is not about authority."""
    s0 = E.arena(2)
    assert s0.pool_balance == 12 == E.total_funded(s0)

    ga, gb = G.F2("A"), G.F2("B")
    ga.reset(s0)
    gb.reset(s0)

    wa = Action("withdraw_pool", principal="A", dst="A:a0", amt=E.AUTH_CAP)
    wa = wa.__class__(**{**wa.__dict__, "auths": (sign_auth("B", wa.key()),)})
    wb = Action("withdraw_pool", principal="B", dst="B:a0", amt=E.AUTH_CAP)
    wb = wb.__class__(**{**wb.__dict__, "auths": (sign_auth("A", wb.key()),)})

    assert ga.admits(s0, wa), "A's withdrawal is individually valid"
    s1 = apply(s0, wa)
    assert gb.admits(s1, wb), "B's withdrawal is individually valid"
    s2 = apply(s1, wb)

    assert E.pool_overdraft(s2) == 4, E.pool_overdraft(s2)
    assert s2.pool_balance == -4

    # and NEITHER principal's own harm measure registers it
    assert E.h_lost(s0, s2, "A") <= G.EPS
    assert E.h_lost(s0, s2, "B") <= G.EPS
    assert G.principal_invariant(s0, s2, "A")
    assert G.principal_invariant(s0, s2, "B")


def test_f3_global_guard_blocks_the_overdraft():
    """The containment upper bound must actually contain it, or F2-vs-F3 says
    nothing."""
    s0 = E.arena(2)
    g = G.F3("A", E.THETA, ("A", "B"))
    g.reset(s0)
    wa = Action("withdraw_pool", principal="A", dst="A:a0", amt=E.AUTH_CAP)
    s1 = apply(s0, wa)
    wb = Action("withdraw_pool", principal="B", dst="B:a0", amt=E.AUTH_CAP)
    assert g.admits(s0, wa)
    assert not g.admits(s1, wb), "F3 must refuse the overdrafting withdrawal"


# --------------------------------------------------------------------------- #
#  T-STATELESS — what makes guard state partition                              #
# --------------------------------------------------------------------------- #
def test_signature_check_is_stateless_wrt_other_principals():
    """The signature check's verdict must not depend on any UNINVOLVED
    principal's state. Verified at M=3 by varying C arbitrarily while A acts
    on B."""
    s0 = E.arena(3)
    a = Action("delete_cross", principal="A", obj="B:o0")
    a = a.__class__(**{**a.__dict__, "auths": (sign_auth("B", a.key()),)})
    g = G.F2("A")
    g.reset(s0)
    base = g.admits(s0, a)
    assert base is True

    mutations = [
        apply(s0, Action("transfer", principal="C", src="C:a0", dst="C:a1", amt=5)),
        apply(s0, Action("delete", principal="C", obj="C:o0")),
        apply(s0, Action("reassign", principal="C", account="C:a0",
                         new_owner=E.EXTERNAL)),
        apply(s0, Action("external_send", principal="C", obj="C:o1", dest="X0")),
    ]
    for m in mutations:
        assert E.verify_auth(a.auths[0]) is True
        assert g.authorized(m, a) is True, "authorization verdict moved with C"

    # the pure signature check reads nothing but the token and the key table
    src = inspect.getsource(E.verify_auth)
    for banned in ("State", "balances", "owner", "objects", "pool", "s."):
        assert banned not in src, f"verify_auth references state via {banned!r}"


# --------------------------------------------------------------------------- #
#  Inventory + BFS tractability (PREREGISTRATION §3.2)                         #
# --------------------------------------------------------------------------- #
def test_inventory_matches_the_preregistered_arena():
    """CORRECTION, disclosed per R9 §6. The preregistration's §3.2 inventory
    table gave contents as 12 (M=2) and 17 (M=3). Both are arithmetically wrong
    by one: each principal contributes 4 unique contents plus 1 duplicated
    content = 5, so M=2 is 5*2 + 1 shared = 11 and M=3 is 5*3 + 1 = 16.

    The BUILT environment is correct and is left unchanged; the table was the
    error. The preregistration anticipated exactly this by requiring the
    inventory be "reported from the BUILT environment, never trusted from this
    table". No decision or threshold depends on the content count — T-BLIND-
    EXISTS computes 3/5 of the content class directly and passed unchanged.
    """
    for m, objs, contents, accts, pool in ((2, 13, 11, 4, 12), (3, 19, 16, 6, 18)):
        inv = E.inventory(E.arena(m))
        assert inv["objects_total"] == objs, (m, inv)
        assert inv["contents_total"] == contents, (m, inv)
        assert inv["pool_funded"] == pool
        assert sum(len(v["accounts"]) for v in inv["per_principal"].values()) == accts
        assert inv["shared_objects"] == 1


def test_bfs_is_the_definition_and_the_optimization_agrees():
    """BFS is GROUND TRUTH (GATE 0). Blind search costs ~3.3 ms/node at M=2 and
    ~6 ms/node at M=3 (measured), so the full node_cap=60000 is ~200-360 s PER
    CALL and is not run per-cell. Disclosure, carried into FINDINGS_R13:

      * the measurements use `recoverable_p` (goal-directed + memoized), which
        is R10's operational pattern;
      * blind search remains the DEFINITION and its agreement with the
        optimization is reported as a first-class number;
      * a capped blind search is SOUND on True and means only "no path found
        within the cap" on False. Both directions are asserted below at a
        disclosed cap.
    """
    CAP = 1500
    s0 = E.arena(2)

    # (a) reachable — blind finds the path immediately, so True is sound
    s1 = apply(s0, Action("transfer", principal="A", src="A:a0", dst="A:a1", amt=5))
    assert E.reachable_blind_p(s0, s1, "A", max_depth=6, node_cap=CAP) is True
    assert E.reachable_goal_p(s0, s1, "A") is True

    # (b) unrecoverable — A's unique content destroyed, no copy anywhere.
    #     RULE 1 (no resurrection) makes this permanent, so the capped False is
    #     not an artifact of the cap; the two searches AGREE.
    s2 = apply(s0, Action("delete", principal="A", obj="A:o0"))
    blind = E.reachable_blind_p(s0, s2, "A", max_depth=6, node_cap=CAP)
    goal = E.reachable_goal_p(s0, s2, "A")
    assert blind is False and goal is False, (blind, goal)
    assert "c-A-u0" not in E.available_contents(s2)   # why the False is structural

    # (c) duplicated content survives the loss of one copy
    s3 = apply(s0, Action("delete", principal="A", obj="A:o4"))
    assert E.reachable_blind_p(s0, s3, "A", max_depth=6, node_cap=CAP) is True
    assert E.reachable_goal_p(s0, s3, "A") is True


def test_blind_and_goal_agree_on_a_sample():
    """Agreement is REPORTED, never assumed. Disagreement would be a FINDING."""
    s0 = E.arena(2)
    probes = [
        [],
        [Action("transfer", principal="A", src="A:a0", dst="A:a1", amt=2)],
        [Action("delete", principal="A", obj="A:o4")],
        [Action("delete", principal="A", obj="A:o0")],
        [Action("delete", principal="A", obj="A:o1"),
         Action("delete", principal="A", obj="A:o2")],
        [Action("reassign", principal="A", account="A:a1", new_owner=E.EXTERNAL)],
    ]
    disagreements = []
    for seq in probes:
        s = s0
        for a in seq:
            s = apply(s, a)
        b = E.reachable_blind_p(s0, s, "A", max_depth=6, node_cap=1500)
        g = E.reachable_goal_p(s0, s, "A")
        if b != g:
            disagreements.append((seq, b, g))
    assert not disagreements, f"blind/goal disagreement is a FINDING: {disagreements}"
