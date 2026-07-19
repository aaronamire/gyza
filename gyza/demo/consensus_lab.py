"""
Consensus lab — an abstract signal-model simulation that TESTS the
competing claims in the two Gyza research briefs, rather than assuming
them.

WHAT THIS IS (AND IS NOT)
-------------------------
This is NOT an LLM evaluation. Agents here are stochastic signal
sources with tunable competence, error-correlation, and malice. That is
deliberate: the claims under test — "receiver-side scoring fails when
the receiver shares the liar's blind spot", "trimming discards the
correct minority", "peer-prediction separation collapses at low
diversity", "a bonded market reallocates influence to correct agents" —
are information-theoretic / game-theoretic structural claims. The source
literature (Correlated Agreement's Delta matrix, ALIE, W-MSR) tests them
with exactly this kind of abstract model. Real-LLM validation is a
separate, later step; conflating the two would be dishonest.

WHAT IT DOES SHOW
-----------------
Whether each mechanism, as a mechanism, survives the correlated-failure
regime — the crux both briefs converge on. The findings are
model-level and hold to the extent the signal model faithfully captures
"a shared nuisance signal makes a fraction of honest agents confidently
wrong together", which is the precise hole Gao-Wright-Leyton-Brown prove
defeats every verification-free mechanism.

Run it:

    python -m gyza.demo.consensus_lab              # all experiments, tables
    python -m gyza.demo.consensus_lab --json       # machine-readable
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import dataclass


# ======================================================================
# Agent / signal model
# ======================================================================

@dataclass(frozen=True)
class AgentSpec:
    agent_id: int
    kind: str          # "diverse" | "monoculture" | "byzantine"
    competence: float  # P(correct) on ordinary questions (honest kinds)


def make_pool(
    n: int, *, byzantine_fraction: float, monoculture_fraction: float,
    competence: float, rng: random.Random,
) -> list[AgentSpec]:
    """
    Build a pool. ``monoculture_fraction`` is the share of the *honest*
    agents that belong to the shared-blind-spot cluster (they are
    confidently wrong together on trap questions); the rest of the
    honest agents are 'diverse' (unaffected by the trap). Byzantines are
    a separate malicious fraction of the whole pool.
    """
    n_byz = int(round(byzantine_fraction * n))
    n_honest = n - n_byz
    n_mono = int(round(monoculture_fraction * n_honest))
    specs: list[AgentSpec] = []
    aid = 0
    for _ in range(n_byz):
        specs.append(AgentSpec(aid, "byzantine", 0.0)); aid += 1
    for _ in range(n_mono):
        specs.append(AgentSpec(aid, "monoculture", competence)); aid += 1
    for _ in range(n_honest - n_mono):
        specs.append(AgentSpec(aid, "diverse", competence)); aid += 1
    rng.shuffle(specs)
    return specs


@dataclass
class Report:
    agent_id: int
    kind: str
    estimate: float     # in [0,1], an estimate of the binary truth
    confidence: float   # self-reported in [0,1] (byzantines falsify to 1.0)


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def run_question(
    pool: list[AgentSpec], *, truth: int, is_trap: bool, rng: random.Random,
    honest_sd: float = 0.20,
) -> list[Report]:
    """
    One question. Honest agents report truth + Gaussian noise (sd set by
    competence). Monoculture agents, ON A TRAP, instead confidently
    report the WRONG answer (the shared blind spot). Byzantines mount the
    worst-case ALIE attack: a *plausible* perturbation of the honest
    distribution toward the wrong answer, with falsified confidence 1.0.
    """
    honest_reports: list[Report] = []
    for s in pool:
        if s.kind == "byzantine":
            continue
        if is_trap and s.kind == "monoculture":
            # Confidently wrong, together — the correlated blind spot.
            est = _clip01((1 - truth) + rng.gauss(0, honest_sd * 0.5))
            conf = 0.9 + 0.1 * rng.random()
        else:
            est = _clip01(truth + rng.gauss(0, honest_sd) * (1 if truth == 0 else -1))
            # calibrated-ish confidence tied to competence
            conf = _clip01(s.competence + rng.gauss(0, 0.05))
        honest_reports.append(Report(s.agent_id, s.kind, est, conf))

    # ALIE byzantine: sit z*sd on the wrong side of the honest mean so
    # the report stays statistically plausible yet drags the aggregate.
    if honest_reports:
        hmean = statistics.fmean(r.estimate for r in honest_reports)
        hsd = statistics.pstdev(r.estimate for r in honest_reports) or honest_sd
    else:
        hmean, hsd = 0.5, honest_sd
    z = 1.5  # ALIE tuning: large enough to move the mean, small enough to evade trims
    byz_target = _clip01(hmean + (z * hsd if truth == 0 else -z * hsd))

    reports = list(honest_reports)
    for s in pool:
        if s.kind == "byzantine":
            reports.append(Report(s.agent_id, s.kind, byz_target, 1.0))
    reports.sort(key=lambda r: r.agent_id)
    return reports


# ======================================================================
# Mechanisms — each maps a list[Report] -> a collective estimate in [0,1]
# ======================================================================

def m_mean(reports: list[Report]) -> float:
    return statistics.fmean(r.estimate for r in reports)


def m_majority(reports: list[Report]) -> float:
    votes = [1 if r.estimate >= 0.5 else 0 for r in reports]
    return statistics.fmean(votes)


def m_confidence_weighted(reports: list[Report]) -> float:
    """CP-WBFT baseline — weight by self-reported confidence. Expected to
    collapse under falsified confidence (byzantines report 1.0)."""
    num = sum(r.confidence * r.estimate for r in reports)
    den = sum(r.confidence for r in reports) or 1.0
    return num / den


def m_trimmed(reports: list[Report], trim_frac: float = 0.2) -> float:
    """Coordinate-wise trimmed mean (W-MSR flavour): drop the top and
    bottom ``trim_frac`` of estimates, average the rest."""
    xs = sorted(r.estimate for r in reports)
    k = int(len(xs) * trim_frac)
    kept = xs[k: len(xs) - k] or xs
    return statistics.fmean(kept)


def m_receiver_side(reports: list[Report]) -> float:
    """
    SAC-style receiver-side scoring: each agent scores every other by
    closeness to its OWN estimate (its own model is the yardstick), and
    we weight by received score. When the pool is a wrong-answer
    monoculture, the majority score each other high and the correct
    minority low — so the weighted mean is dragged toward the majority.
    That failure mode is the point of including it.
    """
    xs = [r.estimate for r in reports]
    n = len(xs)
    recv = [0.0] * n
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            recv[j] += 1.0 - abs(xs[i] - xs[j])
    total = sum(recv) or 1.0
    return sum(w * x for w, x in zip(recv, xs)) / total


MECHANISMS = {
    "mean": m_mean,
    "majority": m_majority,
    "confidence_wt": m_confidence_weighted,
    "trimmed_20": m_trimmed,
    "receiver_side": m_receiver_side,
}


def decide(estimate: float) -> int:
    return 1 if estimate >= 0.5 else 0


# ======================================================================
# Peer-prediction (Correlated-Agreement Delta) — a SCORING method, used
# to test the diversity-invariant claim, not to pick an answer.
# ======================================================================

def peer_prediction_scores(answer_matrix: list[list[int]]) -> list[float]:
    """
    Correlated-Agreement-style score per agent over a batch of questions.

    ``answer_matrix[i]`` is agent i's binary answers across M probe
    questions. Score_i = mean over reference agents k of the
    excess-agreement Delta(i,k) = P(agree) - P(agree by chance from
    marginals). Truthful reports that are *mutually informative* score
    positively; a wrong-answer monoculture is mutually informative among
    itself, so this deliberately can reward the blind cluster — which is
    exactly the diversity-dependence we are measuring.
    """
    n = len(answer_matrix)
    m = len(answer_matrix[0]) if n else 0
    p1 = [sum(row) / m if m else 0.0 for row in answer_matrix]
    scores = [0.0] * n
    for i in range(n):
        acc = 0.0
        for k in range(n):
            if i == k:
                continue
            agree = sum(1 for t in range(m) if answer_matrix[i][t] == answer_matrix[k][t]) / m
            chance = p1[i] * p1[k] + (1 - p1[i]) * (1 - p1[k])
            acc += agree - chance
        scores[i] = acc / (n - 1) if n > 1 else 0.0
    return scores


def auc(pos: list[float], neg: list[float]) -> float:
    """Mann-Whitney AUC: P(random pos ranks above random neg)."""
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for q in neg:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return wins / (len(pos) * len(neg))


# ======================================================================
# Bonded market with repeated-round capital dynamics (settlement-primary)
# ======================================================================

def run_market(
    pool: list[AgentSpec], *, rounds: int, p_trap: float, resolve_prob: float,
    base_stake: float, rng: random.Random,
) -> dict:
    """
    Repeated bonded-assertion market. Each round every solvent agent
    stakes on its answer; with probability ``resolve_prob`` the ground
    truth is revealed and stakes are settled (winners split losers'
    stakes pro-rata). The collective decision each round is the
    *bankroll-weighted* vote — so influence follows accumulated capital,
    and correct agents compound while confidently-wrong ones bleed out.
    Tests the settlement-primary claim: does truth win over time even
    when a correlated-wrong majority initially dominates?
    """
    bankroll = {s.agent_id: 100.0 for s in pool}
    by_id = {s.agent_id: s for s in pool}
    correct_decisions = 0
    trap_decisions = 0
    trap_correct = 0
    for _ in range(rounds):
        truth = rng.randint(0, 1)
        is_trap = rng.random() < p_trap
        reports = run_question(list(by_id.values()), truth=truth,
                               is_trap=is_trap, rng=rng)
        # bankroll-weighted collective decision
        w1 = sum(bankroll[r.agent_id] for r in reports if r.estimate >= 0.5)
        w0 = sum(bankroll[r.agent_id] for r in reports if r.estimate < 0.5)
        col = 1 if w1 >= w0 else 0
        correct_decisions += (col == truth)
        if is_trap:
            trap_decisions += 1
            trap_correct += (col == truth)

        if rng.random() < resolve_prob:
            # settle: losers' stake redistributed to winners pro-rata
            stakes = {r.agent_id: min(base_stake, bankroll[r.agent_id])
                      for r in reports}
            winners = [r.agent_id for r in reports if decide(r.estimate) == truth]
            losers = [r.agent_id for r in reports if decide(r.estimate) != truth]
            pot = sum(stakes[a] for a in losers)
            win_stake = sum(stakes[a] for a in winners) or 1.0
            for a in losers:
                bankroll[a] -= stakes[a]
            for a in winners:
                bankroll[a] += pot * (stakes[a] / win_stake)

    # capital share by kind at the end
    kinds = ("diverse", "monoculture", "byzantine")
    cap = {k: sum(bankroll[s.agent_id] for s in pool if s.kind == k) for k in kinds}
    total_cap = sum(cap.values()) or 1.0
    return {
        "accuracy": correct_decisions / rounds,
        "trap_accuracy": (trap_correct / trap_decisions) if trap_decisions else None,
        "final_capital_share": {k: round(cap[k] / total_cap, 3) for k in kinds},
    }


# ======================================================================
# Experiments
# ======================================================================

def _batch_accuracy(pool, *, questions, p_trap, rng, mechanism, trap_only=False):
    ok = tot = 0
    for _ in range(questions):
        truth = rng.randint(0, 1)
        is_trap = rng.random() < p_trap
        if trap_only and not is_trap:
            continue
        reports = run_question(pool, truth=truth, is_trap=is_trap, rng=rng)
        if decide(mechanism(reports)) == truth:
            ok += 1
        tot += 1
    return ok / tot if tot else float("nan")


def exp1_monoculture(seed=0, n=100, questions=1500) -> dict:
    """Accuracy on TRAP questions vs. size of the correlated blind-spot
    cluster, per mechanism. Tests: do detection/aggregation methods
    collapse as the monoculture grows, and does trimming do worse?"""
    rows = {}
    for mono in (0.0, 0.2, 0.4, 0.55, 0.7, 0.85):
        pool = make_pool(n, byzantine_fraction=0.0, monoculture_fraction=mono,
                         competence=0.8, rng=random.Random(seed + 1))
        rows[mono] = {
            name: round(_batch_accuracy(pool, questions=questions, p_trap=1.0,
                                        rng=random.Random(seed + 7), mechanism=fn,
                                        trap_only=True), 3)
            for name, fn in MECHANISMS.items()
        }
    return rows


def exp2_byzantine(seed=0, n=100, questions=1500) -> dict:
    """Accuracy vs. Byzantine (ALIE + falsified-confidence) fraction, on
    ordinary questions. Tests: which mechanisms survive the confident
    liar; does confidence-weighting collapse?"""
    rows = {}
    for bf in (0.0, 0.1, 0.2, 0.3, 0.4):
        pool = make_pool(n, byzantine_fraction=bf, monoculture_fraction=0.0,
                         competence=0.8, rng=random.Random(seed + 2))
        rows[bf] = {
            name: round(_batch_accuracy(pool, questions=questions, p_trap=0.0,
                                        rng=random.Random(seed + 11), mechanism=fn),
                        3)
            for name, fn in MECHANISMS.items()
        }
    return rows


def exp3_peer_prediction_diversity(seed=0, n=60, probes=400) -> dict:
    """Peer-prediction separation AUC (reliable=diverse-honest vs.
    unreliable=monoculture+byzantine) as diversity varies. Tests the
    central diversity-invariant claim: does separation collapse toward
    (or below) chance as the pool becomes a monoculture?"""
    rows = {}
    for mono in (0.1, 0.3, 0.5, 0.7, 0.9):
        rng = random.Random(seed + 3)
        pool = make_pool(n, byzantine_fraction=0.1, monoculture_fraction=mono,
                         competence=0.8, rng=rng)
        # build answer matrix over probe questions (all traps: the regime
        # where blind spots matter)
        mat = [[0] * probes for _ in pool]
        idx = {s.agent_id: i for i, s in enumerate(pool)}
        for t in range(probes):
            truth = rng.randint(0, 1)
            reports = run_question(pool, truth=truth, is_trap=True, rng=rng)
            for r in reports:
                mat[idx[r.agent_id]][t] = decide(r.estimate)
        scores = peer_prediction_scores(mat)
        reliable = [scores[idx[s.agent_id]] for s in pool if s.kind == "diverse"]
        unreliable = [scores[idx[s.agent_id]] for s in pool
                      if s.kind in ("monoculture", "byzantine")]
        rows[mono] = {
            "auc_reliable_vs_unreliable": round(auc(reliable, unreliable), 3),
            "n_reliable": len(reliable), "n_unreliable": len(unreliable),
        }
    return rows


def exp5_trim_discards_outlier(seed=0, questions=2000) -> dict:
    """
    Isolate Document 2's specific claim that robust trimming does *worse*
    than the plain mean by discarding the lone correct outlier.

    Regime: the truth is held by a small, CONFIDENT minority; the
    majority is wrong-but-only-mildly (clustered just past the decision
    boundary), so the plain mean is still dragged across to correct by
    the extreme-but-few correct reports — while a trimmed mean removes
    exactly those extremes and lands on the wrong majority. Sweep the
    correct-minority size; report mean vs. trimmed accuracy.
    """
    rows = {}
    for minority in (0.1, 0.2, 0.3, 0.4):
        rng = random.Random(seed + 40)
        ok_mean = ok_trim = 0
        for _ in range(questions):
            truth = rng.randint(0, 1)
            reports = []
            n = 100
            n_min = int(minority * n)
            for i in range(n):
                if i < n_min:  # confident-correct minority (extreme)
                    est = truth * 0.97 + (1 - truth) * 0.03 + rng.gauss(0, 0.02)
                else:          # mildly-wrong majority, just past the boundary
                    est = (0.42 if truth == 1 else 0.58) + rng.gauss(0, 0.04)
                reports.append(Report(i, "x", _clip01(est), 0.5))
            ok_mean += decide(m_mean(reports)) == truth
            ok_trim += decide(m_trimmed(reports)) == truth
        rows[minority] = {
            "mean_acc": round(ok_mean / questions, 3),
            "trimmed_acc": round(ok_trim / questions, 3),
        }
    return rows


def exp4_market(seed=0, n=100, rounds=400) -> dict:
    """Market accuracy + capital reallocation vs. ground-truth resolution
    frequency, in a 60%-monoculture pool (correlated-wrong majority).
    Tests the settlement-primary claim."""
    rows = {}
    for resolve in (0.0, 0.05, 0.2, 1.0):
        pool = make_pool(n, byzantine_fraction=0.1, monoculture_fraction=0.5,
                         competence=0.8, rng=random.Random(seed + 4))
        rows[resolve] = run_market(pool, rounds=rounds, p_trap=0.5,
                                   resolve_prob=resolve, base_stake=10.0,
                                   rng=random.Random(seed + 5))
    return rows


# ======================================================================
# CLI
# ======================================================================

def _fmt_table(title: str, rows: dict, col_key: str) -> str:
    out = [title]
    cols = list(next(iter(rows.values())).keys())
    header = f"  {col_key:>10} | " + " | ".join(f"{c:>13}" for c in cols)
    out.append(header)
    out.append("  " + "-" * (len(header) - 2))
    for k, v in rows.items():
        out.append(f"  {k:>10} | " + " | ".join(f"{str(v[c]):>13}" for c in cols))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    results = {
        "exp1_monoculture_trap_accuracy": exp1_monoculture(args.seed),
        "exp2_byzantine_accuracy": exp2_byzantine(args.seed),
        "exp3_peer_prediction_auc_vs_diversity": exp3_peer_prediction_diversity(args.seed),
        "exp4_market_vs_resolution": exp4_market(args.seed),
        "exp5_trim_discards_outlier": exp5_trim_discards_outlier(args.seed),
    }

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0

    print("GYZA — CONSENSUS LAB  (abstract signal-model simulation)")
    print("=" * 76)
    print("Testing the correlated-failure crux from the two research briefs.")
    print("NOT an LLM eval — agents are tunable stochastic signal sources.\n")

    print(_fmt_table(
        "E1 — accuracy on TRAP questions vs. monoculture size "
        "(0% byzantine).\n     Hypothesis: detection/aggregation collapse as "
        "the blind-spot cluster\n     grows; trimming is no better than mean.",
        results["exp1_monoculture_trap_accuracy"], "mono_frac"))
    print()
    print(_fmt_table(
        "E2 — accuracy vs. byzantine fraction (ALIE + falsified confidence,\n"
        "     no monoculture). Hypothesis: confidence-weighting collapses.",
        results["exp2_byzantine_accuracy"], "byz_frac"))
    print()
    print(_fmt_table(
        "E3 — peer-prediction separation AUC (reliable vs. unreliable) vs.\n"
        "     monoculture size. Hypothesis: AUC → 0.5 (or below) as diversity\n"
        "     vanishes — the diversity invariant is necessary.",
        results["exp3_peer_prediction_auc_vs_diversity"], "mono_frac"))
    print()
    print("E4 — bonded market (50% monoculture, 10% byzantine) vs. ground-truth")
    print("     resolution frequency. Hypothesis: with even occasional resolution,")
    print("     capital shifts to diverse-correct agents and accuracy recovers.")
    for resolve, r in results["exp4_market_vs_resolution"].items():
        print(f"    resolve={resolve:>4}: acc={r['accuracy']:.3f}  "
              f"trap_acc={r['trap_accuracy']}  capital_share={r['final_capital_share']}")

    print()
    print(_fmt_table(
        "E5 — trimming vs. mean when the truth is a confident minority and\n"
        "     the majority is mildly wrong. Hypothesis (Doc 2): trimming\n"
        "     discards the correct outlier and does WORSE than the mean.",
        results["exp5_trim_discards_outlier"], "correct_min"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
