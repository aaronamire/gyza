"""
Conditional-independence null for the code battery — the real H2 test.

The published headline (within=0.6027, cross=0.5602, ~13x the permutation
null) shows capable models converge on the *same specific wrong program
behavior* far above chance. But the permutation null only asks "is the
per-problem wrong-answer distribution non-degenerate?" — not "does pair or
family identity add correlation BEYOND the population's per-problem
wrong-answer structure?". A pair can look highly convergent simply because,
on the problems where both are wrong, the space of wrong behaviors is small
and *every* wrong model piles onto the same few answers.

This module adds that missing null, reusing the EXACT observed metric,
signature extraction, wrongness test, and sentinel handling from
``codebench``/``run_openrouter`` — nothing reimplemented.

LAYER 1 (pairwise excess over the leave-pair-out population baseline):
  observed(i,j) = same-bug convergence (codebench), sentinel-safe.
  baseline(i,j) = P(two OTHER wrong models agree) on the same both-wrong
                  problems (ratio-of-sums, leave-pair-out).
  excess(i,j)   = observed - baseline.
  Aggregate: mean over within-family pairs, mean over cross-family pairs,
  each with a bootstrap CI over pairs (run_openrouter._ci, 3000 resamples).

LAYER 2 (pair-independent concentration of the wrong-answer space itself):
  per problem, over all in-band wrong models: Simpson agreement, distinct
  wrong signatures, effective # of wrong answers.

SENTINEL HANDLING (artifact #4 must not reappear). A per-problem signature
is a NON-ANSWER (the program never ran / produced no per-call result) iff
every element is TIMEOUT or IMPORTERR. Two non-answers must NOT count as
agreement in observed OR baseline. Per-call ``ERR:<type>`` is a real
behavior (the program ran; that call raised) and is answer-bearing under
codebench's "behavior" definition — so the PRIMARY sentinel set is
{TIMEOUT, IMPORTERR}, which leaves observed byte-identical to the published
same_bug_convergence (there are zero TIMEOUT/IMPORTERR agreements in the
in-band data; the 90 degenerate agreements are all-ERR). Excluding all-ERR
too is reported as an ERR-sensitivity variant, applied identically to
observed and baseline so the excess stays a valid contrast.

HONESTY. Layer 1 answers "does pair/family identity add correlation beyond
problem structure." Neither layer separates "genuine universal shared
cognition" from "intrinsically small wrong-answer space"; Layer 2 only
bounds the latter. No claim beyond that.

No side effects on import. Cache-only; no API calls.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np

# Sibling-module imports (codebench, run_openrouter) — put this file's dir on
# the path so import works from anywhere (pytest, another cwd). This is the
# same pattern run_openrouter uses; it is not a runtime/network side effect.
sys.path.insert(0, str(Path(__file__).parent))

# --- REUSE (do not reimplement): signature extraction + observed metric ---
from codebench import (  # noqa: E402
    expected_signature, extract_calls, load_mbpp, same_bug_convergence,
)
# --- REUSE: model list / family map / band / CI / cache path / config ---
from run_openrouter import BAND, CACHE, MODELS, N_CODE, SEED, _ci  # noqa: E402

_HERE = Path(__file__).parent


# ----------------------------------------------------------------------
# Sentinel handling — the ONE place "what can agree" is defined.
# ----------------------------------------------------------------------

def _is_sentinel_tok(t: str) -> bool:
    return t == "TIMEOUT" or t.startswith("ERR:") or t.startswith("IMPORTERR:")


def is_non_answer(sig: list[str], *, include_err: bool = False) -> bool:
    """
    True when the signature carries no real output value on any call — the
    artifact-#4 "no answer produced" case that must not count as agreement.

    Primary (``include_err=False``): the program never ran / produced no
    per-call result — every element is TIMEOUT or IMPORTERR. ``ERR:<type>``
    is a genuine behavior and is answer-bearing.

    ERR-sensitivity (``include_err=True``): also treat an all-``ERR``
    signature (program ran but every call raised — no returned value) as a
    non-answer.
    """
    if not sig:
        return True
    if include_err:
        return all(_is_sentinel_tok(t) for t in sig)
    return all(t == "TIMEOUT" or t.startswith("IMPORTERR:") for t in sig)


def _comb2(n: int) -> int:
    return n * (n - 1) // 2


# ----------------------------------------------------------------------
# Cache loading (offline; no API calls, no network for generations).
# ----------------------------------------------------------------------

def load_from_cache() -> dict:
    """
    Load the cached OpenRouter code signatures + recompute expected /
    accuracy / band, exactly as run_openrouter did. HF dataset load is
    forced offline (uses the local MBPP parquet the original run cached).
    """
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    ids = [m for m, _ in MODELS]
    fams = {m: f for m, f in MODELS}

    missing = []
    code_sigs = {}
    for mid in ids:
        f = CACHE / f"{mid.replace('/', '__')}_code_s{SEED}.json"
        if not f.exists():
            missing.append(f.name)
            continue
        code_sigs[mid] = json.loads(f.read_text())
    if missing:
        raise FileNotFoundError(
            "GATE 0: cached code generations missing: " + ", ".join(missing))

    mbpp = load_mbpp(n=N_CODE, seed=SEED)
    calls = [extract_calls(p["test_list"]) for p in mbpp]
    expected = [expected_signature(c) for c in calls]

    acc = {m: float(np.mean([code_sigs[m][q] == expected[q]
                             for q in range(len(expected))])) for m in ids}
    hi = max(acc.values())
    band = [m for m in ids if hi - acc[m] <= BAND]
    return {"ids": ids, "fams": fams, "code_sigs": code_sigs,
            "expected": expected, "acc": acc, "band": band}


# ----------------------------------------------------------------------
# LAYER 1 — observed, leave-pair-out baseline, excess.
# ----------------------------------------------------------------------

def observed_convergence(si: list[list[str]], sj: list[list[str]],
                         expected: list[list[str]], *, include_err: bool = False):
    """
    Sentinel-safe same-bug convergence for one pair (matches codebench's
    same_bug_convergence numerically when there are no non-answer
    agreements). Among problems where BOTH are wrong, fraction with the
    identical wrong signature — a non-answer signature never counts as
    agreement. Returns (conv | nan, n_both_wrong).
    """
    d = same = 0
    for q in range(len(expected)):
        wi = si[q] != expected[q]
        wj = sj[q] != expected[q]
        if wi and wj:
            d += 1
            if si[q] == sj[q] and not is_non_answer(si[q], include_err=include_err):
                same += 1
    return (same / d, d) if d else (np.nan, 0)


def baseline_convergence(i: int, j: int, sigs: list[list[list[str]]],
                         expected: list[list[str]], ref_idx: list[int], *,
                         include_err: bool = False):
    """
    Leave-pair-out population baseline for pair (i,j): over the problems
    where BOTH i and j are wrong, how often do two OTHER wrong models (from
    ``ref_idx``, excluding i and j) agree? Ratio-of-sums:

        baseline = Σ_q agreeing_pairs_q / Σ_q total_pairs_q

    agreeing_pairs_q = Σ_s C(c_s,2) over ANSWER-BEARING distinct wrong
    signatures s (non-answers excluded — artifact #4); total_pairs_q =
    C(m,2), m = # other wrong models (any wrong, matching the both-wrong
    conditioning of observed). C(0,2)=C(1,2)=0, so m<2 contributes 0/0-safe.
    Returns (baseline | nan, n_both_wrong_with_ref).
    """
    num = den = 0
    d = 0
    for q in range(len(expected)):
        if sigs[i][q] == expected[q] or sigs[j][q] == expected[q]:
            continue  # not both-wrong
        d += 1
        others = [k for k in ref_idx if k != i and k != j
                  and sigs[k][q] != expected[q]]
        m = len(others)
        if m < 2:
            continue
        counts = Counter(
            tuple(sigs[k][q]) for k in others
            if not is_non_answer(sigs[k][q], include_err=include_err))
        num += sum(_comb2(c) for c in counts.values())
        den += _comb2(m)
    return (num / den, d) if den else (np.nan, d)


def layer1(data: dict, *, ref: str = "in_band", include_err: bool = False,
           min_distinct: "int | None" = None) -> dict:
    """
    Compute per-pair observed/baseline/excess over the in-band pairs, with
    a chosen reference pool and sentinel variant.

    ref="in_band"  : leave-pair-out reference = the OTHER in-band models.
    ref="all9"     : reference = all 9 models minus per-problem non-answers
                     (R2 — puts the band-excluded siblings back).
    min_distinct   : if set, restrict to problems whose in-band
                     distinct_wrong_q >= min_distinct before computing the
                     per-pair means (R3). Applied by masking those problems.
    """
    ids, fams = data["ids"], data["fams"]
    expected = data["expected"]
    band = data["band"]
    sigs = [data["code_sigs"][m] for m in ids]  # index-aligned to ids
    band_i = [ids.index(m) for m in band]
    ref_idx = band_i if ref == "in_band" else list(range(len(ids)))

    # Optional R3 problem mask: keep only problems with >= min_distinct
    # distinct answer-bearing wrong signatures among IN-BAND models.
    keep_q = list(range(len(expected)))
    if min_distinct is not None:
        keep_q = []
        for q in range(len(expected)):
            sigset = {tuple(sigs[k][q]) for k in band_i
                      if sigs[k][q] != expected[q]
                      and not is_non_answer(sigs[k][q], include_err=include_err)}
            if len(sigset) >= min_distinct:
                keep_q.append(q)
    keepset = set(keep_q)

    def masked(sig):
        # Re-point non-kept problems to the expected value so they read as
        # "correct" (never both-wrong) — a clean way to drop them from both
        # observed and baseline identically.
        return [sig[q] if q in keepset else expected[q] for q in range(len(expected))]

    msigs = [masked(s) for s in sigs] if min_distinct is not None else sigs

    per_pair = []
    for a in range(len(band_i)):
        for b in range(a + 1, len(band_i)):
            i, j = band_i[a], band_i[b]
            obs, nobs = observed_convergence(msigs[i], msigs[j], expected,
                                             include_err=include_err)
            base, _ = baseline_convergence(i, j, msigs, expected, ref_idx,
                                           include_err=include_err)
            same = fams[ids[i]] == fams[ids[j]]
            per_pair.append({
                "pair": [ids[i], ids[j]], "same_family": same,
                "observed": None if np.isnan(obs) else round(float(obs), 4),
                "baseline": None if np.isnan(base) else round(float(base), 4),
                "excess": (None if (np.isnan(obs) or np.isnan(base))
                           else round(float(obs - base), 4)),
                "n_both_wrong": nobs,
            })

    def grp(key, same):
        return [p[key] for p in per_pair if p["same_family"] == same
                and p[key] is not None]

    out = {"ref": ref, "include_err": include_err, "min_distinct": min_distinct,
           "n_problems_used": len(keep_q), "per_pair": per_pair}
    for name, same in (("within", True), ("cross", False)):
        seedbase = {"within": 10, "cross": 20}[name]
        out[name] = {
            "n_pairs": len(grp("observed", same)),
            "observed_mean_ci": _ci(grp("observed", same), seed=seedbase + 1),
            "baseline_mean_ci": _ci(grp("baseline", same), seed=seedbase + 2),
            "excess_mean_ci": _ci(grp("excess", same), seed=seedbase + 3),
        }
    return out


# ----------------------------------------------------------------------
# LAYER 2 — concentration of the wrong-answer space (pair-independent).
# ----------------------------------------------------------------------

def layer2(data: dict, *, include_err: bool = False) -> dict:
    """
    Per problem, over all IN-BAND models wrong on it (answer-bearing only):
    Simpson agreement (P two random wrong models agree), distinct wrong
    signatures, effective # of wrong answers (1/Simpson-index; small-m
    biased — reported, not leaned on).
    """
    ids, expected, band = data["ids"], data["expected"], data["band"]
    sigs = {m: data["code_sigs"][m] for m in band}
    rows = []
    for q in range(len(expected)):
        wrong = [tuple(sigs[m][q]) for m in band
                 if sigs[m][q] != expected[q]
                 and not is_non_answer(sigs[m][q], include_err=include_err)]
        m = len(wrong)
        counts = Counter(wrong)
        if m >= 2:
            simpson = sum(_comb2(c) for c in counts.values()) / _comb2(m)
        else:
            simpson = None
        eff = (1.0 / sum((c / m) ** 2 for c in counts.values())) if m >= 1 else None
        rows.append({"q": q, "m_wrong": m, "distinct_wrong": len(counts),
                     "simpson": None if simpson is None else round(simpson, 4),
                     "eff_wrong": None if eff is None else round(eff, 3)})

    def mstats(key, cond=lambda r: True):
        v = np.array([r[key] for r in rows if r[key] is not None and cond(r)],
                     dtype=float)
        if len(v) == 0:
            return {"median": None, "iqr": [None, None], "n": 0}
        return {"median": round(float(np.median(v)), 4),
                "iqr": [round(float(np.percentile(v, 25)), 4),
                        round(float(np.percentile(v, 75)), 4)],
                "n": int(len(v))}

    return {
        "include_err": include_err,
        "simpson": mstats("simpson"),
        "distinct_wrong": mstats("distinct_wrong"),
        "eff_wrong": mstats("eff_wrong"),
        "m_wrong": mstats("m_wrong"),
        "simpson_pairs_ge2": mstats("simpson", lambda r: r["m_wrong"] >= 2),
        "per_problem": rows,
    }


# ----------------------------------------------------------------------
# Orchestration.
# ----------------------------------------------------------------------

def _grid_case(cross_excess_ci, within_excess_ci) -> str:
    def incl0(ci):
        return ci[1] is not None and ci[1] <= 0.0 <= ci[2]
    cx0, wx0 = incl0(cross_excess_ci), incl0(within_excess_ci)
    if cx0 and wx0:
        return ("A: both excess CIs include 0 -> convergence is entirely "
                "problem-structural (constrained wrong-answer space); family "
                "irrelevant.")
    if (not wx0) and within_excess_ci[1] > 0 and cx0:
        return ("B: within-excess>0, cross-excess~0 -> family membership adds "
                "correlation beyond problem structure; diversity DOES "
                "decorrelate -> REVERSES the FINDINGS headline. FLAG.")
    if (not cx0) and cross_excess_ci[1] > 0 and (not wx0) and within_excess_ci[1] > 0:
        return ("C: within-excess ~ cross-excess, both >0 -> genuine shared "
                "blind spot beyond problem structure that family diversity "
                "does not fix -> headline SURVIVES against the right null.")
    return ("mixed/other: see per-group excess CIs (does not fall cleanly into "
            "A/B/C).")


def run_all() -> dict:
    data = load_from_cache()

    # Reproduce-first gate value: the published observed via the UNCHANGED
    # codebench metric over the in-band pairs.
    ids, fams, band = data["ids"], data["fams"], data["band"]
    band_i = [ids.index(m) for m in band]
    sigs = [data["code_sigs"][m] for m in ids]
    repro = {"within": [], "cross": [], "null_within": [], "null_cross": []}
    for a in range(len(band_i)):
        for b in range(a + 1, len(band_i)):
            i, j = band_i[a], band_i[b]
            r = same_bug_convergence([sigs[i], sigs[j]], data["expected"], seed=SEED)
            key = "within" if fams[ids[i]] == fams[ids[j]] else "cross"
            repro[key].append(r["same_bug_convergence"])
            repro["null_" + key].append(r["permutation_null"])
    reproduce = {
        "within_conv_mean_ci": _ci(repro["within"], seed=1),
        "cross_conv_mean_ci": _ci(repro["cross"], seed=2),
        "null_within": round(float(np.mean(repro["null_within"])), 4),
        "null_cross": round(float(np.mean(repro["null_cross"])), 4),
        "n_within": len(repro["within"]), "n_cross": len(repro["cross"]),
        "R": round(float(np.mean(repro["within"]) / np.mean(repro["cross"])), 3),
    }

    primary = layer1(data, ref="in_band", include_err=False)
    variants = {
        "R1_in_band_primary": primary,
        "R2_all9_minus_nonanswer": layer1(data, ref="all9", include_err=False),
        "R3_distinct_ge3": layer1(data, ref="in_band", include_err=False,
                                  min_distinct=3),
        "ERRsens_exclude_all_err": layer1(data, ref="in_band", include_err=True),
    }
    l2 = layer2(data, include_err=False)
    l2_err = layer2(data, include_err=True)

    grid = _grid_case(primary["cross"]["excess_mean_ci"],
                      primary["within"]["excess_mean_ci"])

    return {
        "config": {"seed": SEED, "n_code": N_CODE, "band": BAND,
                   "in_band_models": band, "n_within_pairs": reproduce["n_within"],
                   "n_cross_pairs": reproduce["n_cross"],
                   "sentinel_primary": "{TIMEOUT, IMPORTERR}",
                   "note": "ERR is answer-bearing (behavior) in primary; "
                           "ERRsens variant excludes all-ERR too."},
        "reproduce_gate": reproduce,
        "layer1_variants": variants,
        "layer2_concentration": l2,
        "layer2_concentration_err_excluded": l2_err,
        "grid_case": grid,
        "within_reference_caveat": (
            "Only 2 same-family models per family clear the band, so the "
            "leave-pair-out reference for a WITHIN pair is composed entirely "
            "of OTHER families. Within-excess is therefore a within-vs-cross "
            "contrast, not family-neutral. R2 (wider pool) and Layer 2 "
            "address this."),
    }


def main() -> int:
    result = run_all()
    (_HERE / "ci_null_result.json").write_text(json.dumps(result, indent=2))
    p = result["layer1_variants"]["R1_in_band_primary"]
    print("reproduce gate:", result["reproduce_gate"]["within_conv_mean_ci"],
          result["reproduce_gate"]["cross_conv_mean_ci"],
          "R", result["reproduce_gate"]["R"])
    print("PRIMARY cross-excess:", p["cross"]["excess_mean_ci"],
          " within-excess:", p["within"]["excess_mean_ci"])
    print("Layer-2 median Simpson:", result["layer2_concentration"]["simpson"]["median"])
    print("grid:", result["grid_case"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
