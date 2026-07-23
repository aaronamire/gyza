"""
Route 6 — simulator for the optimal-audit-under-a-competence-bounded-verifier
model. ANALYTIC route: zero model calls, no network, no credits. This module is
the referee for the proofs in PROPOSITIONS.md — every proposition is checked
against these functions. Importable, no import side effects, deterministic.

Model (see MODEL.md for the numbered assumptions):
  claim i: consequence v_i, lie-gain g_i, bond B_i (<= B_max), audit cost c_i,
  detection prob q_i (competence-bounded), false-conviction prob f_i.
  auditor COMMITS to p_i (public); risk-neutral agents best-respond (Stackelberg).
  deterrence:  lie iff g_i > p_i q_i B_i        (P1, Becker/CSV convention)
  objective:   epsilon = sum_{tempted & undeterred} (1 - p_i q_i) v_i
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SEED = 1

# ---- calibration (source: consistency_defensibility/FINDINGS_CORRECTION.md, Phase 8) ----
# cheap cross-model checker WITHIN competence (6B cell-a, n=433):
Q_IN = 0.818          # TPR_in  -> effective detection in-competence
F_IN = 0.041          # FPR_in  -> false-conviction in-competence
LR_IN = Q_IN / F_IN   # 19.95 (reported 19.8)
# cheap checker OUTSIDE competence (6B cell-b, n=36, UNDERPOWERED, CI incl 0):
Q_OUT_TPR = 0.556     # raw TPR_out
F_OUT = 0.444         # FPR_out
LR_OUT = Q_OUT_TPR / F_OUT   # 1.25
J_OUT = Q_OUT_TPR - F_OUT    # 0.111 -- the ACTIONABLE detection edge out-of-competence
# effective/actionable q_out is bounded by J (net detection above chance), swept [0,0.3]:
Q_OUT_EFF = J_OUT            # 0.111 central; ALWAYS report the [0,0.3] sweep
BASE_WRONG = 0.128           # corrected MATH wrongness base rate (temptation proxy)


@dataclass
class Claims:
    """Vectorized population of claims. All arrays length N."""
    v: np.ndarray          # consequence (principal loss if wrong & undetected)
    g: np.ndarray          # lie-gain
    B: np.ndarray          # bond posted
    c: np.ndarray          # audit cost
    q: np.ndarray          # detection prob (competence-bounded)
    f: np.ndarray          # false-conviction prob
    tempted: np.ndarray    # bool: would lie if undeterred
    in_comp: np.ndarray    # bool: within cheap checker competence
    meta: dict = field(default_factory=dict)

    def __len__(self):
        return len(self.v)


# --------------------------------------------------------------------------- #
#  claim generation                                                           #
# --------------------------------------------------------------------------- #
def make_claims(n=4000, dist="pareto", alpha_in=0.6, regime="G1", beta=0.3,
                g_max=None, B_max=3.0, c_cheap=1.0, q_in=Q_IN, q_out=Q_OUT_EFF,
                f_in=F_IN, f_out=F_OUT, temptation=None, tail=1.5,
                het_c=False, het_B=False, seed=SEED):
    """Draw N claims. Stakes v from a heavy/light distribution; gains by regime
    G1 (proportional g=beta*v) or G2 (capped g=min(beta*v,g_max)); competence by
    an alpha_in mixture; bonds capped at B_max. `temptation` fraction of claims are
    lie-tempted (default BASE_WRONG). Deterministic in `seed`."""
    rng = np.random.default_rng(seed)
    if dist == "pareto":
        v = (rng.pareto(tail, n) + 1.0)              # heavy tail, mean ~ tail/(tail-1)
    elif dist == "lognormal":
        v = rng.lognormal(0.0, 1.0, n)
    elif dist == "uniform":
        v = rng.uniform(0.1, 2.0, n)
    else:
        raise ValueError(dist)
    v = v / v.mean()                                 # normalize mean stake to 1

    if regime == "G1":
        g = beta * v
    elif regime == "G2":
        gm = g_max if g_max is not None else beta * np.quantile(v, 0.8)
        g = np.minimum(beta * v, gm)
    else:
        raise ValueError(regime)

    in_comp = rng.random(n) < alpha_in
    q = np.where(in_comp, q_in, q_out)
    f = np.where(in_comp, f_in, f_out)

    B = np.full(n, B_max, dtype=float)
    if het_B:                                        # bonds scale with gain, capped
        B = np.minimum(g / max(q_in, 1e-9) / 0.5, B_max)
    c = np.full(n, c_cheap, dtype=float)
    if het_c:
        c = c_cheap * rng.uniform(0.5, 2.0, n)

    tr = BASE_WRONG if temptation is None else temptation
    tempted = rng.random(n) < tr
    return Claims(v=v, g=g, B=B, c=c, q=q, f=f, tempted=tempted, in_comp=in_comp,
                  meta=dict(regime=regime, beta=beta, B_max=B_max, c_cheap=c_cheap,
                            alpha_in=alpha_in, dist=dist, tail=tail, seed=seed))


# --------------------------------------------------------------------------- #
#  core quantities                                                            #
# --------------------------------------------------------------------------- #
def p_min(cl: Claims):
    """Minimum audit prob that deters claim i:  p_i^min = g_i/(q_i B_i)  (P1).
    inf where q_i B_i == 0 (undeterrable at any p<=1)."""
    denom = cl.q * cl.B
    with np.errstate(divide="ignore", invalid="ignore"):
        pm = np.where(denom > 0, cl.g / denom, np.inf)
    return pm


def price_of_deterrence(cl: Claims):
    """pi_i = c_i * p_i^min = c_i g_i/(q_i B_i)  (P1). inf if undeterrable."""
    return cl.c * p_min(cl)


def rho(cl: Claims):
    """value density rho_i = v_i / pi_i = v_i q_i B_i /(c_i g_i)  (P2).
    0 where undeterrable (pi=inf) or not tempted."""
    pi = price_of_deterrence(cl)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(np.isfinite(pi) & (pi > 0), cl.v / pi, 0.0)
    r = np.where(cl.tempted, r, 0.0)
    return r


# --------------------------------------------------------------------------- #
#  adversary best-response and objective                                      #
# --------------------------------------------------------------------------- #
def undeterred(cl: Claims, p):
    """Stackelberg best-response: a tempted agent lies iff g_i > p_i q_i B_i."""
    return cl.tempted & (cl.g > p * cl.q * cl.B + 1e-12)


def epsilon_population(cl: Claims, p):
    """Expected undetected consequential loss (the objective). Population model:
    every tempted-and-undeterred agent lies; expected leak = (1 - p q) v."""
    u = undeterred(cl, p)
    return float(np.sum(u * (1.0 - p * cl.q) * cl.v))


def epsilon_weakest_link(cl: Claims, p):
    """Single strategic adversary picks the one claim maximizing expected damage
    (1 - p_i q_i) v_i. This is the inspection-game measure that exposes
    DETERMINISTIC policies: a p_i=0 claim yields the full v_i with certainty."""
    dmg = (1.0 - p * cl.q) * cl.v
    dmg = np.where(cl.tempted, dmg, 0.0)
    return float(dmg.max()) if len(dmg) else 0.0


def epsilon_montecarlo(cl: Claims, p, draws=2000, seed=SEED):
    """Stochastic check of epsilon_population: actually draw audits & detections."""
    rng = np.random.default_rng(seed)
    u = undeterred(cl, p)
    tot = 0.0
    for _ in range(draws):
        audited = rng.random(len(cl)) < p
        detected = audited & (rng.random(len(cl)) < cl.q)
        leak = u & ~detected
        tot += np.sum(leak * cl.v)
    return tot / draws


# --------------------------------------------------------------------------- #
#  policies  (each returns p array with sum c_i p_i <= C, p in [0,1])          #
# --------------------------------------------------------------------------- #
def _scale_to_budget(p, c, C):
    """Scale a nonneg preference vector to spend <= C, clipping at 1. Water-filling:
    scale, clip at 1, redistribute freed budget once."""
    p = np.clip(np.asarray(p, dtype=float), 0.0, None)
    if p.sum() == 0:
        return np.zeros_like(p)
    for _ in range(6):
        spend = np.sum(c * p)
        if spend <= C + 1e-12:
            break
        p = p * (C / spend)
        p = np.minimum(p, 1.0)
    # try to use leftover on unsaturated claims
    for _ in range(6):
        used = np.sum(c * p)
        left = C - used
        if left <= 1e-9:
            break
        room = p < 1.0 - 1e-9
        if not room.any():
            break
        add = np.zeros_like(p)
        base = p.copy()
        base[~room] = 0.0
        if base.sum() == 0:
            add[room] = np.minimum(1.0 - p[room], left / (c[room].sum()))
        else:
            scale = left / np.sum(c * base)
            add = np.minimum(1.0 - p, base * scale)
        p = np.minimum(p + add, 1.0)
    return np.clip(p, 0.0, 1.0)


def policy_uniform(cl: Claims, C):
    """Audit every claim with equal probability."""
    p0 = np.ones(len(cl))
    return _scale_to_budget(p0, cl.c, C)


def policy_consequence(cl: Claims, C):
    """p_i increasing in stake v_i (the 'intuitive' policy)."""
    return _scale_to_budget(cl.v.copy(), cl.c, C)


def policy_competence(cl: Claims, C):
    """p_i increasing in detection prob q_i (audit where you can actually catch)."""
    return _scale_to_budget(cl.q.copy(), cl.c, C)


def policy_optimal(cl: Claims, C):
    """Greedy on value density rho_i = v_i/pi_i (P2): buy full deterrence for the
    highest-rho tempted deterrable claims until budget out; spend any leftover on
    partial audits of the highest q_i v_i / c_i undeterred claims."""
    n = len(cl)
    p = np.zeros(n)
    pm = p_min(cl)
    r = rho(cl)
    deterrable = cl.tempted & np.isfinite(pm) & (pm <= 1.0) & (r > 0)
    order = np.argsort(-r)
    budget = C
    for i in order:
        if not deterrable[i]:
            continue
        cost = cl.c[i] * pm[i]
        if cost <= budget + 1e-12:
            p[i] = pm[i]
            budget -= cost
    # leftover -> partial audit of still-undeterred tempted, by q v / c density
    if budget > 1e-9:
        u = undeterred(cl, p)
        dens = np.where(u, cl.q * cl.v / cl.c, 0.0)
        for i in np.argsort(-dens):
            if dens[i] <= 0 or budget <= 1e-9:
                break
            room = 1.0 - p[i]
            spend = min(room * cl.c[i], budget)
            p[i] += spend / cl.c[i]
            budget -= spend
    return np.clip(p, 0.0, 1.0)


def deter_value_in_order(cl: Claims, C, order):
    """Full-deterrence knapsack executed in a GIVEN order: total consequence
    deterred within budget C. Under G1+homogeneous (constant rho) this total is
    INVARIANT to the order (the v-cancellation's true policy content, P2)."""
    pm = p_min(cl)
    deterrable = cl.tempted & np.isfinite(pm) & (pm <= 1.0)
    budget = C
    val = 0.0
    for i in order:
        if not deterrable[i]:
            continue
        cost = cl.c[i] * pm[i]
        if cost <= budget + 1e-12:
            val += cl.v[i]
            budget -= cost
    return val


def policy_topk_stake(cl: Claims, C):
    """DETERMINISTIC: fully audit (p=1) the highest-stake claims until budget out,
    p=0 for the rest. Included to demonstrate exploitability (inspection game)."""
    p = np.zeros(len(cl))
    order = np.argsort(-cl.v)
    budget = C
    for i in order:
        if cl.c[i] <= budget + 1e-12:
            p[i] = 1.0
            budget -= cl.c[i]
        else:
            break
    return p


POLICIES = {
    "uniform": policy_uniform,
    "consequence": policy_consequence,
    "competence": policy_competence,
    "optimal": policy_optimal,
    "topk_stake": policy_topk_stake,
}


# --------------------------------------------------------------------------- #
#  two-tier routing (P4)                                                       #
# --------------------------------------------------------------------------- #
def two_tier_epsilon(cl: Claims, C, c_ex=20.0, q_ex=0.999, s=1.0, t=1.0,
                     seed=SEED):
    """Split budget between a cheap tier (cost c_cheap, detection q_i, only useful
    in-competence) and an expensive oracle (cost c_ex, detection q_ex, works on
    anything). An imperfect router with sensitivity s = P(route->cheap | in-comp)
    and specificity t = P(route->expensive | out-comp) directs each claim.

    Misrouting is asymmetric: a truly-out claim sent to cheap (rate 1-t) is
    DANGEROUS (undeterred consequential leak); a truly-in claim sent to expensive
    (rate 1-s) is merely WASTEFUL (deterred but at higher cost). Greedy-by-rho
    within the realized routing, expensive claims priced at c_ex g/(q_ex B)."""
    rng = np.random.default_rng(seed)
    n = len(cl)
    route_cheap = np.where(
        cl.in_comp, rng.random(n) < s, rng.random(n) < (1.0 - t))
    # effective detection & cost per claim under its assigned tier
    q_eff = np.where(route_cheap, cl.q, q_ex)
    c_eff = np.where(route_cheap, cl.c, c_ex)
    cl2 = Claims(v=cl.v, g=cl.g, B=cl.B, c=c_eff, q=q_eff, f=cl.f,
                 tempted=cl.tempted, in_comp=cl.in_comp, meta=cl.meta)
    p = policy_optimal(cl2, C)
    return epsilon_population(cl2, p), dict(
        route_cheap_frac=float(route_cheap.mean()),
        dangerous_frac=float((route_cheap & ~cl.in_comp).mean()))


def single_tier_all_expensive(cl: Claims, C, c_ex=20.0, q_ex=0.999):
    """Baseline: send everything to the oracle. Deters anything it can afford."""
    cl2 = Claims(v=cl.v, g=cl.g, B=cl.B, c=np.full(len(cl), c_ex), q=np.full(len(cl), q_ex),
                 f=cl.f, tempted=cl.tempted, in_comp=cl.in_comp, meta=cl.meta)
    p = policy_optimal(cl2, C)
    return epsilon_population(cl2, p)


# --------------------------------------------------------------------------- #
#  epsilon(r) contract curve (P5)                                             #
# --------------------------------------------------------------------------- #
def epsilon_of_r(cl: Claims, rs, policy="optimal"):
    """epsilon as a function of audit rate r = C/(N c_cheap). Returns list of
    (r, epsilon, epsilon_normalized_by_r0)."""
    n = len(cl)
    c_cheap = float(cl.meta.get("c_cheap", 1.0))
    pol = POLICIES[policy]
    e0 = epsilon_population(cl, np.zeros(n))    # r=0 baseline (no audit)
    out = []
    for r in rs:
        C = r * n * c_cheap
        p = pol(cl, C)
        e = epsilon_population(cl, p)
        out.append((float(r), float(e), float(e / e0) if e0 > 0 else 0.0))
    return out, float(e0)


# --------------------------------------------------------------------------- #
#  P7 feasibility frontier                                                     #
# --------------------------------------------------------------------------- #
def feasible_LR(q, f, g_over_w):
    """Joint deter+retain feasibility (P7): need LR = q/f >= g/w. Returns bool."""
    return (q / f) >= g_over_w


def min_LR_for(g_over_w):
    """Minimum likelihood ratio q/f required for feasibility at gain/profit ratio."""
    return g_over_w
