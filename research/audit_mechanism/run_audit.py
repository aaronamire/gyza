"""
Route 6 — run every numerical verification + sensitivity sweep, dump audit_result.json.
Deterministic (SEED=1). No model calls. Run:
  cd research/audit_mechanism && ~/dev/marshal/.os/bin/python run_audit.py
"""
from __future__ import annotations

import json

import numpy as np

import audit_simulator as A


def _cv(x):
    x = np.asarray(x, dtype=float)
    x = x[x > 0]
    return float(x.std() / x.mean()) if len(x) and x.mean() > 0 else 0.0


def p1_verify():
    cl = A.make_claims(n=4000, alpha_in=0.5, seed=1)
    pm = A.p_min(cl)
    undeterrable = cl.g > cl.q * cl.B
    # numerical: at p = p_min +/- eps, best-response flips exactly
    flips_ok = True
    idx = np.where(np.isfinite(pm) & (pm <= 1) & cl.tempted)[0][:200]
    for i in idx:
        p = np.zeros(len(cl))
        p[i] = pm[i] + 1e-4
        if A.undeterred(cl, p)[i]:
            flips_ok = False
        p[i] = pm[i] - 1e-4
        if not A.undeterred(cl, p)[i]:
            flips_ok = False
    return dict(
        threshold_flips_exact=bool(flips_ok),
        undeterrable_frac=float(undeterrable.mean()),
        undeterrable_all_pmin_gt1=bool(np.all(pm[undeterrable] > 1.0)),
        mean_price_of_deterrence=float(np.mean(A.price_of_deterrence(cl)[np.isfinite(pm)])),
    )


def p2_verify():
    out = {}
    # G1 homogeneous: rho CV ~ 0, order-indifference of value deterred
    cl1 = A.make_claims(n=4000, regime="G1", alpha_in=1.0, temptation=1.0, seed=1)
    C = 0.1 * len(cl1)
    out["G1_homogeneous"] = dict(
        rho_cv=_cv(A.rho(cl1)),
        v_deterred_high_first=A.deter_value_in_order(cl1, C, np.argsort(-cl1.v)),
        v_deterred_low_first=A.deter_value_in_order(cl1, C, np.argsort(cl1.v)),
    )
    # G1 + competence (bimodal q): dispersion returns via q, competence-weighting helps
    cl2 = A.make_claims(n=4000, regime="G1", alpha_in=0.5, temptation=1.0, seed=1)
    C2 = 0.1 * len(cl2)
    out["G1_competence"] = dict(
        rho_cv=_cv(A.rho(cl2)),
        eps_uniform=A.epsilon_population(cl2, A.policy_uniform(cl2, C2)),
        eps_competence=A.epsilon_population(cl2, A.policy_competence(cl2, C2)),
        eps_optimal=A.epsilon_population(cl2, A.policy_optimal(cl2, C2)),
    )
    # G2 saturated gains: v-dispersion returns, stake order matters
    cl3 = A.make_claims(n=4000, regime="G2", beta=0.5, alpha_in=1.0, temptation=1.0, seed=1)
    C3 = 0.05 * len(cl3)
    out["G2_saturated"] = dict(
        rho_cv=_cv(A.rho(cl3)),
        v_deterred_high_first=A.deter_value_in_order(cl3, C3, np.argsort(-cl3.v)),
        v_deterred_low_first=A.deter_value_in_order(cl3, C3, np.argsort(cl3.v)),
        eps_uniform=A.epsilon_population(cl3, A.policy_uniform(cl3, C3)),
        eps_optimal=A.epsilon_population(cl3, A.policy_optimal(cl3, C3)),
    )
    # rank the dispersion sources (which knob moves rho_cv most, one at a time)
    base = A.make_claims(n=4000, regime="G1", alpha_in=1.0, temptation=1.0, seed=1)
    out["dispersion_sources_rho_cv"] = dict(
        baseline_G1_homog=_cv(A.rho(base)),
        q_heterogeneity=_cv(A.rho(A.make_claims(n=4000, regime="G1", alpha_in=0.5,
                                                temptation=1.0, seed=1))),
        gain_saturation_G2=_cv(A.rho(A.make_claims(n=4000, regime="G2", beta=0.5,
                                                   alpha_in=1.0, temptation=1.0, seed=1))),
        cost_heterogeneity=_cv(A.rho(A.make_claims(n=4000, regime="G1", alpha_in=1.0,
                                                   het_c=True, temptation=1.0, seed=1))),
        bond_heterogeneity=_cv(A.rho(A.make_claims(n=4000, regime="G1", alpha_in=1.0,
                                                   het_B=True, temptation=1.0, seed=1))),
    )
    return out


def p3_verify():
    # bond-capacity vs targeting substitution: sweep B_max, measure the gap between
    # optimal (targeted) and uniform. Gap -> 0 as B_max grows (targeting redundant).
    rows = []
    for bmax in [1.0, 2.0, 3.0, 5.0, 10.0, 25.0, 100.0]:
        cl = A.make_claims(n=4000, regime="G1", alpha_in=0.5, B_max=bmax,
                           temptation=1.0, seed=1)
        C = 0.1 * len(cl)
        e_uni = A.epsilon_population(cl, A.policy_uniform(cl, C))
        e_opt = A.epsilon_population(cl, A.policy_optimal(cl, C))
        undeterrable = float((cl.g > cl.q * cl.B).mean())
        rows.append(dict(B_max=bmax, eps_uniform=e_uni, eps_optimal=e_opt,
                         targeting_gain=e_uni - e_opt, undeterrable_frac=undeterrable))
    return rows


def p4_verify():
    # two-tier vs single, and routing-accuracy floor
    cl = A.make_claims(n=4000, regime="G1", alpha_in=0.6, B_max=5.0,
                       temptation=1.0, seed=1)
    C = 0.05 * len(cl)   # scarce regime (where two-tier's cost edge matters)
    e_single = A.single_tier_all_expensive(cl, C, c_ex=20.0)
    # sweep routing accuracy s=t=acc
    routing = []
    for acc in [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0]:
        e_two, meta = A.two_tier_epsilon(cl, C, c_ex=20.0, s=acc, t=acc, seed=1)
        routing.append(dict(routing_acc=acc, eps_two_tier=e_two,
                            beats_single=bool(e_two < e_single),
                            dangerous_frac=meta["dangerous_frac"]))
    # minimum accuracy at which two-tier still beats single
    min_acc = None
    for r in routing:
        if r["beats_single"]:
            min_acc = r["routing_acc"]
            break
    # also show the budget-regime dependence: abundant budget flips it
    C_ab = 0.5 * len(cl)
    e_single_ab = A.single_tier_all_expensive(cl, C_ab, c_ex=20.0)
    e_two_ab, _ = A.two_tier_epsilon(cl, C_ab, c_ex=20.0, s=1.0, t=1.0, seed=1)
    return dict(eps_single_tier=e_single, routing_sweep=routing,
                min_routing_acc_to_beat_single=min_acc,
                abundant_budget=dict(eps_single=e_single_ab, eps_two_tier=e_two_ab,
                                     two_tier_wins=bool(e_two_ab < e_single_ab)))


def p5_verify():
    # the epsilon(r) CONTRACT curve, calibrated, for each policy + stake dist
    rs = [round(x, 3) for x in np.linspace(0.0, 0.6, 13)]
    curves = {}
    for dist in ["pareto", "lognormal", "uniform"]:
        cl = A.make_claims(n=4000, regime="G1", alpha_in=0.6, dist=dist,
                           B_max=5.0, temptation=None, seed=1)   # temptation=BASE_WRONG
        pol_curves = {}
        for pol in ["uniform", "optimal", "consequence", "competence"]:
            pts, e0 = A.epsilon_of_r(cl, rs, policy=pol)
            pol_curves[pol] = dict(e0=e0, curve=pts)
        curves[dist] = pol_curves
    # MC cross-check of the calibrated optimal curve at one r
    cl = A.make_claims(n=1500, regime="G1", alpha_in=0.6, B_max=5.0, seed=1)
    p = A.policy_optimal(cl, 0.2 * len(cl))
    curves["mc_crosscheck"] = dict(
        expectation=A.epsilon_population(cl, p),
        montecarlo=A.epsilon_montecarlo(cl, p, draws=4000, seed=1))
    return curves


def p6_verify():
    # collusion under commitment: separable => coalition gains nothing.
    # Simulate: independent best-response vs a coalition that jointly picks lies.
    # Under committed independent p, the coalition's joint optimum = sum of the
    # individual best-responses (no coupling), so realized epsilon is identical.
    cl = A.make_claims(n=2000, regime="G1", alpha_in=0.6, temptation=1.0, seed=1)
    p = A.policy_optimal(cl, 0.15 * len(cl))
    # Separability under commitment: brute-force a K-member coalition's JOINT best
    # lie-vector (2^K options, maximizing total expected payoff sum L_i(g_i-p_i q_i B_i))
    # and confirm it equals each member independently best-responding. Equal =>
    # commitment makes the deterrence constraints separable; coalition gains nothing.
    rng = np.random.default_rng(1)
    members = rng.choice(len(cl), size=14, replace=False)
    gain = cl.g[members] - p[members] * cl.q[members] * cl.B[members]   # E[lie]-E[honest]
    indep = (gain > 0).astype(int)                                      # independent BR
    best_joint, best_val = None, -np.inf
    for mask in range(1 << len(members)):
        L = np.array([(mask >> j) & 1 for j in range(len(members))])
        val = float(np.sum(L * gain))
        if val > best_val:
            best_val, best_joint = val, L
    coalition_equals_independent = bool(np.array_equal(best_joint, indep))
    # adaptive-auditor attack (case a): auditor allocates p ∝ observed stake; a
    # coalition floods M decoys of COMPARABLE stake to dilute p on a target lie.
    def p_on_target(n_decoy):
        v = np.concatenate([cl.v, np.full(n_decoy, cl.v.mean())])   # comparable decoys
        c = np.ones(len(v))
        C = 0.15 * len(cl)                          # budget fixed to real N
        p2 = A.policy_consequence(A.Claims(v=v, g=0.3 * v, B=np.full(len(v), 3.0),
                                           c=c, q=np.full(len(v), A.Q_IN),
                                           f=np.full(len(v), A.F_IN),
                                           tempted=np.ones(len(v), bool),
                                           in_comp=np.ones(len(v), bool)), C)
        target = int(np.argsort(-cl.v)[len(cl) // 10])   # 90th pct (unsaturated)
        return float(p2[target])
    p_target_0 = p_on_target(0)
    p_target_flood = p_on_target(len(cl) * 3)
    return dict(coalition_joint_equals_independent=coalition_equals_independent,
                coalition_members=int(len(members)),
                adaptive_p_target_no_decoys=p_target_0,
                adaptive_p_target_after_flood=p_target_flood,
                adaptive_dilution_factor=float(p_target_0 / max(p_target_flood, 1e-12)))


def p7_verify():
    # feasibility frontier: LR = q/f is the sufficient statistic, not TPR/FPR/J.
    pts = []
    for gw in [1.0, 1.25, 2, 5, 10, 15, 19.8, 25, 50]:
        pts.append(dict(g_over_w=gw, min_LR_required=A.min_LR_for(gw),
                        in_feasible=A.feasible_LR(A.Q_IN, A.F_IN, gw),
                        out_feasible=A.feasible_LR(A.Q_OUT_TPR, A.F_OUT, gw)))
    # same-J different-LR pair: J=0.5 both, but LR differs -> feasibility differs
    same_J = dict(
        checkerA=dict(TPR=0.6, FPR=0.1, J=0.5, LR=6.0,
                      feasible_at_gw5=A.feasible_LR(0.6, 0.1, 5.0)),
        checkerB=dict(TPR=0.9, FPR=0.4, J=0.5, LR=2.25,
                      feasible_at_gw5=A.feasible_LR(0.9, 0.4, 5.0)))
    return dict(LR_in=A.LR_IN, LR_out=A.LR_OUT, J_in=A.Q_IN - A.F_IN, J_out=A.J_OUT,
                frontier=pts, same_J_different_LR=same_J)


def policy_comparison():
    # head-to-head across stake dists and gain regimes at a fixed audit rate
    rows = []
    for dist in ["pareto", "lognormal", "uniform"]:
        for regime in ["G1", "G2"]:
            cl = A.make_claims(n=4000, dist=dist, regime=regime, beta=0.4,
                               alpha_in=0.6, B_max=5.0, temptation=1.0, seed=1)
            C = 0.15 * len(cl)
            row = dict(dist=dist, regime=regime)
            for name, fn in A.POLICIES.items():
                p = fn(cl, C)
                row[f"eps_{name}"] = A.epsilon_population(cl, p)
                row[f"wl_{name}"] = A.epsilon_weakest_link(cl, p)
            rows.append(row)
    return rows


def sensitivity():
    # sweep q_out over [0,0.3] (cell-b underpowered) + tail index; report robustness
    out = {"q_out_sweep": [], "tail_sweep": []}
    for qo in [0.0, 0.05, 0.111, 0.15, 0.2, 0.25, 0.3]:
        cl = A.make_claims(n=4000, regime="G1", alpha_in=0.6, q_out=qo,
                           B_max=5.0, temptation=1.0, seed=1)
        C = 0.15 * len(cl)
        # fraction of consequential loss from out-of-competence claims (uncatchable cheap)
        p = A.policy_optimal(cl, C)
        u = A.undeterred(cl, p)
        eps = (u * (1 - p * cl.q) * cl.v)
        frac_out = float(eps[~cl.in_comp].sum() / max(eps.sum(), 1e-12))
        out["q_out_sweep"].append(dict(q_out=qo, eps=float(eps.sum()),
                                       frac_loss_out_competence=frac_out))
    for tail in [1.2, 1.5, 2.0, 3.0]:
        cl = A.make_claims(n=4000, regime="G1", dist="pareto", tail=tail,
                           alpha_in=0.6, B_max=5.0, temptation=1.0, seed=1)
        C = 0.15 * len(cl)
        e_uni = A.epsilon_population(cl, A.policy_uniform(cl, C))
        e_opt = A.epsilon_population(cl, A.policy_optimal(cl, C))
        out["tail_sweep"].append(dict(tail=tail, eps_uniform=e_uni, eps_optimal=e_opt,
                                      targeting_gain=e_uni - e_opt))
    return out


def main():
    result = dict(
        seed=A.SEED,
        calibration=dict(Q_IN=A.Q_IN, F_IN=A.F_IN, LR_IN=A.LR_IN,
                         Q_OUT_TPR=A.Q_OUT_TPR, F_OUT=A.F_OUT, J_OUT=A.J_OUT,
                         LR_OUT=A.LR_OUT, Q_OUT_EFF=A.Q_OUT_EFF, BASE_WRONG=A.BASE_WRONG,
                         source="consistency_defensibility/FINDINGS_CORRECTION.md (Phase 8)"),
        P1=p1_verify(),
        P2=p2_verify(),
        P3=p3_verify(),
        P4=p4_verify(),
        P5=p5_verify(),
        P6=p6_verify(),
        P7=p7_verify(),
        policy_comparison=policy_comparison(),
        sensitivity=sensitivity(),
    )
    with open("audit_result.json", "w") as fh:
        json.dump(result, fh, indent=2, default=float)
    # compact console summary
    print("=== R6 numerical verification ===")
    print("P1 threshold flips exact:", result["P1"]["threshold_flips_exact"],
          "| undeterrable frac:", round(result["P1"]["undeterrable_frac"], 3))
    g1 = result["P2"]["G1_homogeneous"]
    print("P2 G1 rho_cv:", f'{g1["rho_cv"]:.2e}',
          "| order-indiff:", round(g1["v_deterred_high_first"], 2),
          "vs", round(g1["v_deterred_low_first"], 2))
    print("P2 dispersion sources:", {k: round(v, 3) for k, v in
          result["P2"]["dispersion_sources_rho_cv"].items()})
    print("P3 targeting_gain by B_max:",
          [(r["B_max"], round(r["targeting_gain"], 2)) for r in result["P3"]])
    print("P4 min routing acc to beat single-tier:",
          result["P4"]["min_routing_acc_to_beat_single"],
          "| abundant-budget two-tier wins:",
          result["P4"]["abundant_budget"]["two_tier_wins"])
    mc = result["P5"]["mc_crosscheck"]
    print("P5 MC crosscheck: expect", round(mc["expectation"], 3),
          "MC", round(mc["montecarlo"], 3))
    print("P6 coalition joint==independent:", result["P6"]["coalition_joint_equals_independent"],
          "| adaptive dilution x", round(result["P6"]["adaptive_dilution_factor"], 2))
    print("P7 LR_in", round(result["P7"]["LR_in"], 1), "LR_out",
          round(result["P7"]["LR_out"], 2),
          "| sameJ feasibility A/B:",
          result["P7"]["same_J_different_LR"]["checkerA"]["feasible_at_gw5"],
          result["P7"]["same_J_different_LR"]["checkerB"]["feasible_at_gw5"])
    print("sensitivity q_out frac-loss-out:",
          [(r["q_out"], round(r["frac_loss_out_competence"], 2))
           for r in result["sensitivity"]["q_out_sweep"]])
    print("written audit_result.json")


if __name__ == "__main__":
    main()
