"""
Route 6 tests. A proof that fails simulation is WRONG — these tests are the
referee. Mandatory cases: deterministic top-k is exploitable; the G1 v_i
cancellation; a closed-form the simulator reproduces to tolerance.
Run: ~/dev/marshal/.os/bin/python -m pytest research/audit_mechanism/test_audit.py -q
"""
from __future__ import annotations

import numpy as np

import audit_simulator as A


def test_p1_deterrence_threshold():
    # a single tempted claim; deterred exactly when p >= g/(qB)
    cl = A.make_claims(n=1, alpha_in=1.0, temptation=1.0, seed=1)
    g, q, B = float(cl.g[0]), float(cl.q[0]), float(cl.B[0])
    pm = g / (q * B)
    assert abs(A.p_min(cl)[0] - pm) < 1e-9
    assert A.undeterred(cl, np.array([pm - 1e-3]))[0]        # just below -> lies
    assert not A.undeterred(cl, np.array([pm + 1e-3]))[0]    # just above -> deterred


def test_p1_undeterrable_set():
    # g > qB  =>  p_min > 1  => cannot deter at any feasible p
    cl = A.make_claims(n=2000, alpha_in=0.5, seed=1)
    pm = A.p_min(cl)
    undeterrable = cl.g > cl.q * cl.B
    assert np.all(pm[undeterrable] > 1.0)
    assert np.all(pm[~undeterrable & np.isfinite(pm)] <= 1.0 + 1e-9)


def test_p2_g1_cancellation():
    # G1 (g=beta v) + uniform q,B,c  =>  rho_i independent of v_i (v cancels).
    cl = A.make_claims(n=3000, dist="pareto", alpha_in=1.0, regime="G1",
                       het_c=False, het_B=False, temptation=1.0, seed=1)
    r = A.rho(cl)
    r = r[r > 0]
    assert r.std() / r.mean() < 1e-9        # perfectly uniform density (the invariant)
    # TRUE policy content: the optimal is INDIFFERENT to stake order -- deterring
    # high-stake-first vs low-stake-first deters the SAME total consequence.
    C = 0.2 * len(cl) * cl.c.mean()
    hi = np.argsort(-cl.v)
    lo = np.argsort(cl.v)
    v_hi = A.deter_value_in_order(cl, C, hi)
    v_lo = A.deter_value_in_order(cl, C, lo)
    assert abs(v_hi - v_lo) / max(v_hi, 1e-9) < 0.02   # order-indifference => v is uninformative


def test_p2_g1_competence_dispersion():
    # G1 but BIMODAL q (competence): rho disperses by q, competence-weighting helps
    cl = A.make_claims(n=3000, alpha_in=0.5, regime="G1", seed=1)
    r = A.rho(cl)
    r = r[r > 0]
    assert r.std() / r.mean() > 0.1         # dispersion returns via q
    C = 0.2 * len(cl) * cl.c.mean()
    e_uni = A.epsilon_population(cl, A.policy_uniform(cl, C))
    e_comp = A.epsilon_population(cl, A.policy_competence(cl, C))
    assert e_comp <= e_uni + 1e-9           # competence targeting weakly better


def test_p2_g2_consequence_returns():
    # G2 (capped gains): rho disperses by v, order-indifference BREAKS, and
    # targeting the high-stake claims deters strictly more consequence.
    cl = A.make_claims(n=3000, alpha_in=1.0, regime="G2", beta=0.5,
                       temptation=1.0, seed=1)
    r = A.rho(cl); r = r[r > 0]
    assert r.std() / r.mean() > 0.1         # dispersion returns under G2
    C = 0.05 * len(cl) * cl.c.mean()        # scarce, so order selects who is deterred
    v_hi = A.deter_value_in_order(cl, C, np.argsort(-cl.v))
    v_lo = A.deter_value_in_order(cl, C, np.argsort(cl.v))
    assert v_hi > v_lo * 1.05               # now stake order matters
    e_uni = A.epsilon_population(cl, A.policy_uniform(cl, C))
    e_opt = A.epsilon_population(cl, A.policy_optimal(cl, C))
    assert e_opt < e_uni                    # targeting strictly helps under G2


def test_deterministic_topk_exploitable():
    # Inspection game: a deterministic policy leaves a certain-safe claim the
    # strategic adversary takes. Clean under LIGHT-tailed stakes (the marginal
    # uncovered claim is nearly as damaging as the covered ones). Under a heavy
    # tail top-k covers the whale and the effect is masked -- a regime caveat.
    cl = A.make_claims(n=2000, dist="uniform", alpha_in=1.0, regime="G1",
                       temptation=1.0, seed=1)
    C = 0.2 * len(cl) * cl.c.mean()
    # realized (population) epsilon: deterministic top-k leaves EVERY uncovered
    # claim lying with certainty (p=0); randomized uniform deters all claims below
    # a stake threshold. This is the classic inspection-game gap.
    e_topk = A.epsilon_population(cl, A.policy_topk_stake(cl, C))
    e_uni = A.epsilon_population(cl, A.policy_uniform(cl, C))
    assert e_topk > e_uni                   # deterministic leaves an exploitable hole
    # and the weakest-link measure exposes the certain-safe hole under top-k
    assert A.epsilon_weakest_link(cl, A.policy_topk_stake(cl, C)) > 0


def test_montecarlo_matches_expectation():
    # closed form: epsilon_population is the expectation; MC must reproduce it.
    cl = A.make_claims(n=800, alpha_in=0.6, seed=1)
    p = A.policy_optimal(cl, 0.2 * len(cl) * cl.c.mean())
    e_expect = A.epsilon_population(cl, p)
    e_mc = A.epsilon_montecarlo(cl, p, draws=4000, seed=1)
    assert abs(e_mc - e_expect) / max(e_expect, 1e-9) < 0.05


def test_closed_form_homogeneous():
    # Fully homogeneous in-competence population, G1, uniform policy below the
    # deterrence threshold: NO claim deterred, so epsilon = sum (1-p q) v exactly.
    n = 1000
    v = np.ones(n)
    g = 0.9 * np.ones(n)          # g close to qB so p_min>budgeted p (undeterred)
    B = np.ones(n)
    q = 0.818 * np.ones(n)
    cl = A.Claims(v=v, g=g, B=B, c=np.ones(n), q=q, f=0.041 * np.ones(n),
                  tempted=np.ones(n, bool), in_comp=np.ones(n, bool),
                  meta=dict(c_cheap=1.0))
    r = 0.1
    p = A.policy_uniform(cl, r * n)         # p = 0.1 everywhere < p_min = 0.9/0.818
    assert np.all(A.undeterred(cl, p))      # nobody deterred
    closed = np.sum((1 - p * q) * v)
    assert abs(A.epsilon_population(cl, p) - closed) < 1e-9


def test_p7_LR_feasibility():
    # feasibility depends on LR = q/f, not TPR/FPR/J individually.
    assert A.feasible_LR(A.Q_IN, A.F_IN, g_over_w=10.0)      # LR 19.8 >= 10 ok
    assert not A.feasible_LR(A.Q_IN, A.F_IN, g_over_w=25.0)  # 19.8 < 25 infeasible
    assert not A.feasible_LR(A.Q_OUT_TPR, A.F_OUT, g_over_w=2.0)  # LR 1.25 < 2
    # two checkers with same J but different LR -> different feasibility
    # A: TPR .6 FPR .1 (J .5, LR 6);  Bb: TPR .9 FPR .4 (J .5, LR 2.25)
    assert A.feasible_LR(0.6, 0.1, 5.0) and not A.feasible_LR(0.9, 0.4, 5.0)


def test_two_tier_beats_single_when_routing_good():
    # Two-tier's advantage is a BUDGET-SCARCITY effect: the cheap tier audits many
    # more in-competence claims per dollar. At scarce budget with good routing it
    # wins; at abundant budget the higher-detection single expensive tier can win
    # given a bond cap (a regime caveat, reported in FINDINGS).
    cl = A.make_claims(n=3000, dist="uniform", alpha_in=0.6, regime="G1",
                       B_max=5.0, seed=1)
    C = 0.05 * len(cl)                       # scarce
    e_single = A.single_tier_all_expensive(cl, C, c_ex=20.0)
    e_two, _ = A.two_tier_epsilon(cl, C, c_ex=20.0, s=1.0, t=1.0)
    assert e_two < e_single                 # scarce budget + good routing -> two-tier wins
