"""
Route 3 — the adversarial attractor experiment. Rounds 1 (MBPP, constrained
space, dense co-failure) and 2 (MATH, open space, sparse scattered failure)
both failed to populate the regime Route 2 needs: DENSE shared error in an OPEN
answer space. This round INDUCES it — perturbed items with a strong memorized/
salient wrong answer (the attractor) — then tests whether engineered
method-disjointness (COT vs DECOMP, no code oracle) breaks it.

REUSE (not reimplemented): route2_experiment's canonicalization
(cluster_answers, _sym_equal, extract_boxed), the 5s-timeout CODE executor
(execute_code, _extract_code), the temperature-capable backend (Route2Backend);
conditional_independence_null (observed_convergence, baseline_convergence,
is_non_answer); _ci from run_openrouter.

Corrections baked in (ADDENDUM 2, exposed by the Phase-A trust-lift finding):
  C1 HELD-OUT trust-lift — a pair's within-mechanism corrected lift is 0 by
     construction, so lift is measured against HELD-OUT agents not in the pair.
  C2 ITEM resampling — the primary signal (COT x DECOMP) is a single pair;
     all primary CIs bootstrap over ITEMS, over-pairs only where >=3 pairs.
  C3 McNEMAR — DECOMP-vs-COT escape is paired binary data (discordant pairs).

No side effects on import. Cache-only after generation; keyed by
(model, method, item_id, sample_idx). __ERR__ cells are regenerable.
"""
from __future__ import annotations

import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import comb
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent / "route2_independence"))
sys.path.insert(0, str(_HERE.parent / "correlated_failure"))

import route2_experiment as R2  # noqa: E402
from route2_experiment import (  # noqa: E402
    Route2Backend, cluster_answers, execute_code, _extract_code, _slug,
)
from conditional_independence_null import (  # noqa: E402
    baseline_convergence, is_non_answer, observed_convergence,
)
from run_openrouter import _ci  # noqa: E402

# --------------------------------------------------------------------------
SEED = 1
BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = R2.API_KEY
MODELS = [
    ("meta-llama/llama-3.1-70b-instruct", "llama"),
    ("google/gemma-2-27b-it", "gemma"),
    ("mistralai/mistral-small-3.2-24b-instruct", "mistral"),
    ("microsoft/phi-4", "phi"),
]
FIXED_MODEL = "meta-llama/llama-3.1-70b-instruct"
METHODS = ["COT", "DECOMP", "CODE"]           # llama COT=0, DECOMP=1, CODE=2
K_SAMPLES = 4
SAMPLE_TEMP = 0.7
MAX_TOKENS = {"COT": 900, "DECOMP": 900, "CODE": 800, "M1COT": 900, "CONTROL": 700}
CODE_TIMEOUT = 5.0

CACHE = _HERE / "route3_cache"
ITEMS = _HERE / "items.json"
EXEC_CACHE = _HERE / "code_exec_cache.json"
RESULT = _HERE / "route3_result.json"

# GATE B thresholds (preregistered)
GATEB_MIN_ATTRACTOR_ITEMS = 25    # >=25 valid items with >=3 attractor-hit agents
GATEB_MIN_HITS = 3                 # "attractor item" = >=3 of 12 agents hit attractor
GATEB_MIN_CONCENTRATION = 0.5     # median attractor concentration among wrong
GATEB_MIN_DENSITY = 3.0           # mean wrong agents / item
CONTROL_MIN_MODELS = 2            # item valid iff >=2 of 4 control models give expected

_ASK_MARK = "Give the final answer"


def load_items() -> list[dict]:
    return json.loads(ITEMS.read_text())["items"]


def _core(prompt: str) -> str:
    return prompt.split(_ASK_MARK)[0].strip()


def method_prompt(method: str, core: str) -> str:
    if method in ("COT", "M1COT", "CONTROL"):
        return ("Solve the following problem step by step, then give the final "
                "answer as \\boxed{...} on the last line.\n\n" + core)
    if method == "DECOMP":
        return ("Solve the following problem by explicit decomposition: first "
                "list the subproblems as a numbered list (1., 2., 3., ...), solve "
                "each in order, then combine them into the final answer. Give the "
                "final answer as \\boxed{...} on the last line.\n\n" + core)
    if method == "CODE":
        return ("Write a self-contained Python program (you may use sympy, "
                "fractions, or a simulation) that COMPUTES the answer to the "
                "following problem and prints it wrapped as \\boxed{...} — e.g. "
                "print('\\\\boxed{' + str(ans) + '}'). Respond with ONLY the code "
                "in a single ```python code block.\n\n" + core)
    raise ValueError(method)


# ==========================================================================
# GENERATION — arms in the C4 order (M1 FIRST to secure the comparator).
# ==========================================================================
def _gen_tasks() -> list[tuple]:
    """(model, method, sample_idx, temp, prompt_field). Order: M1, controls,
    llama's 3 methods (M3 primary), then the rest of the 12-cell grid."""
    t = []
    for k in range(K_SAMPLES):                         # 1. M1 (secure first)
        t.append((FIXED_MODEL, "M1COT", k, SAMPLE_TEMP, "perturbed"))
    for model, _f in MODELS:                           # 2. controls (COT/original)
        t.append((model, "CONTROL", 0, 0.0, "original"))
    for method in METHODS:                             # 3. M3 model-controlled
        t.append((FIXED_MODEL, method, 0, 0.0, "perturbed"))
    for model, _f in MODELS:                           # 4. rest of grid
        if model == FIXED_MODEL:
            continue
        for method in METHODS:
            t.append((model, method, 0, 0.0, "perturbed"))
    return t


_LOCK = threading.Lock()


def _cache_path(model, method):
    CACHE.mkdir(exist_ok=True)
    return CACHE / f"{_slug(model)}__{method}__s{SEED}.json"


def _load_cache(model, method):
    f = _cache_path(model, method)
    return json.loads(f.read_text()) if f.exists() else {}


def generate_all(items, max_workers=8, verbose=True):
    for model, method, sidx, temp, field in _gen_tasks():
        cache = _load_cache(model, method)

        def _needs(it):
            e = cache.get(it["item_id"], {}).get(str(sidx))
            return e is None or str(e.get("raw", "")).startswith("__ERR__")
        todo = [it for it in items if _needs(it)]
        if not todo:
            if verbose:
                print(f"[gen] {model} {method} s{sidx}: cached", flush=True)
            continue
        backend = Route2Backend(model, dict(MODELS).get(model, "?"),
                                base_url=BASE_URL, api_key=API_KEY)
        seed = SEED if temp == 0.0 else SEED * 1000 + sidx
        mt = MAX_TOKENS[method]

        def _one(it, backend=backend, method=method, temp=temp, seed=seed, field=field, mt=mt):
            try:
                raw = backend.generate(method_prompt(method, _core(it[field + "_prompt"])),
                                       max_new_tokens=mt, temperature=temp, seed=seed)
            except Exception as e:  # noqa: BLE001
                raw = f"__ERR__:{type(e).__name__}"
            return it["item_id"], raw

        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(_one, it) for it in todo]
            for fut in as_completed(futs):
                iid, raw = fut.result()
                with _LOCK:
                    cache.setdefault(iid, {})[str(sidx)] = {"raw": raw}
                    done += 1
                    if done % 20 == 0:
                        _cache_path(model, method).write_text(json.dumps(cache))
        _cache_path(model, method).write_text(json.dumps(cache))
        if verbose:
            print(f"[gen] {model} {method} s{sidx}: +{len(todo)}", flush=True)


# ==========================================================================
# B1 — balance + plan + cost estimate.
# ==========================================================================
def plan_and_balance(items):
    import urllib.request
    def _get(url):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}",
                                                   "User-Agent": "gyza-research/0.1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    cred = _get(BASE_URL + "/credits")["data"]
    balance = cred["total_credits"] - cred["total_usage"]
    pricing = {m["id"]: m["pricing"] for m in _get(BASE_URL + "/models")["data"]}
    total = 0.0
    n_calls = 0
    for model, method, sidx, temp, field in _gen_tasks():
        pr = pricing.get(model, {"prompt": "0", "completion": "0"})
        pin = float(pr["prompt"])
        pcomp = float(pr["completion"])
        for it in items:
            itok = len(method_prompt(method, _core(it[field + "_prompt"]))) // 4
            otok = MAX_TOKENS[method]
            total += itok * pin + otok * pcomp
            n_calls += 1
    return {"balance_usd": round(balance, 4), "n_calls": n_calls,
            "cost_est_usd": round(total, 3),
            "gate_pass": balance >= 2 * total,
            "note": "output billed at max_tokens (conservative upper bound)"}


# ==========================================================================
# ASSEMBLY — extract answers, canonicalize per item, detect attractor.
# ==========================================================================
def _raw_answer(model, method, sidx, iid, caches, exec_cache):
    e = caches[(model, method)].get(iid, {}).get(str(sidx))
    if e is None:
        return "IMPORTERR:MISSING"
    raw = e["raw"]
    if isinstance(raw, str) and raw.startswith("__ERR__"):
        return "IMPORTERR:APICALL"
    if method == "CODE":
        key = f"{_slug(model)}|{method}|{sidx}|{iid}"
        if key not in exec_cache:
            exec_cache[key] = execute_code(_extract_code(raw), timeout=CODE_TIMEOUT)
        return exec_cache[key]
    b = R2.extract_boxed(raw)
    return b if b else "IMPORTERR:NOANSWER"


def _det_index(model_i, method_j):
    return 3 * model_i + method_j


def canon_tokens(allraws: list[str]) -> dict[int, str]:
    """Cluster the answer-bearing raws (sentinels excluded) into equivalence
    classes under sympy-equality; return {global_index: token}. String-== on the
    returned tokens reproduces sympy-equality WITHIN this item — the property the
    reused estimator needs. Non-answers get no token (caller keeps the sentinel)."""
    ab_idx = [i for i, rv in enumerate(allraws) if not is_non_answer([rv])]
    clus = cluster_answers([allraws[i] for i in ab_idx])
    return {gi: f"c{clus[k]}" for k, gi in enumerate(ab_idx)}


def assemble(items):
    caches = {}
    for model, _f in MODELS:
        for method in METHODS:
            caches[(model, method)] = _load_cache(model, method)
        caches[(model, "CONTROL")] = _load_cache(model, "CONTROL")
    caches[(FIXED_MODEL, "M1COT")] = _load_cache(FIXED_MODEL, "M1COT")
    exec_cache = json.loads(EXEC_CACHE.read_text()) if EXEC_CACHE.exists() else {}

    # deterministic agents (12) + M1 (4)
    det_agents = [(m, meth) for m, _f in MODELS for meth in METHODS]
    n = len(items)
    DET = list(range(12))
    M1 = list(range(12, 12 + K_SAMPLES))

    raw = [[None] * n for _ in range(16)]
    for a, (m, meth) in enumerate(det_agents):
        for qi, it in enumerate(items):
            raw[a][qi] = _raw_answer(m, meth, 0, it["item_id"], caches, exec_cache)
    for k in range(K_SAMPLES):
        for qi, it in enumerate(items):
            raw[12 + k][qi] = _raw_answer(FIXED_MODEL, "M1COT", k, it["item_id"],
                                          caches, exec_cache)
    # controls: 4 models, CONTROL, on original
    ctrl_raw = {}
    for m, _f in MODELS:
        ctrl_raw[m] = [_raw_answer(m, "CONTROL", 0, it["item_id"], caches, exec_cache)
                       for it in items]
    EXEC_CACHE.write_text(json.dumps(exec_cache))

    # per-item canonicalization: cluster true, attractor, all agent + control raws
    sigs = [[None] * n for _ in range(16)]
    expected = [None] * n           # true token
    attractor_tok = [None] * n
    ctrl_hit_expected = []          # per item: #control models producing expected
    cardinality = []
    for qi, it in enumerate(items):
        true_s, attr_s = it["true_answer"], it["attractor_answer"]
        pool = [true_s, attr_s]
        agent_raws = [raw[a][qi] for a in range(16)]
        ctrl_raws = [ctrl_raw[m][qi] for m, _f in MODELS]
        allraws = pool + agent_raws + ctrl_raws        # 0=true,1=attractor,2..=agents,then controls
        tok = canon_tokens(allraws)
        expected[qi] = [tok.get(0, "IMPORTERR:TRUE")]
        attractor_tok[qi] = tok.get(1, "IMPORTERR:ATTR")
        for a in range(16):
            gidx = 2 + a
            sigs[a][qi] = [tok[gidx]] if gidx in tok else [agent_raws[a]]
        # control expected-answer check
        expected_ctrl = attractor_tok[qi] if it["control_mode"] == "memorized" else expected[qi][0]
        hit = 0
        for ci, (m, _f) in enumerate(MODELS):
            gidx = 2 + 16 + ci
            if gidx in tok and tok[gidx] == expected_ctrl:
                hit += 1
        ctrl_hit_expected.append(hit)
        # cardinality over the 12 deterministic agents (the diverse pool)
        det_tokens = [sigs[a][qi][0] for a in DET]
        wrong = [t for a, t in zip(DET, det_tokens)
                 if not is_non_answer([t]) and t != expected[qi][0]]
        cnt = Counter(wrong)
        m_wrong = len(wrong)
        distinct = len(cnt)
        simpson = (sum(c * (c - 1) for c in cnt.values()) / (m_wrong * (m_wrong - 1))
                   if m_wrong >= 2 else None)
        attr_hits = sum(1 for a in DET if sigs[a][qi] == [attractor_tok[qi]]
                        and not is_non_answer(sigs[a][qi]))
        attr_conc = (attr_hits / m_wrong) if m_wrong >= 1 else None
        cardinality.append({"q": qi, "id": it["item_id"], "category": it["category"],
                            "control_mode": it["control_mode"],
                            "m_wrong": m_wrong, "distinct_wrong": distinct,
                            "simpson": None if simpson is None else round(simpson, 4),
                            "attractor_hits": attr_hits,
                            "attractor_concentration": None if attr_conc is None else round(attr_conc, 4),
                            "space": ("CONSTRAINED" if distinct <= 2 else "LARGE" if distinct >= 5 else "MID")})
    return {"sigs": sigs, "expected": expected, "attractor_tok": attractor_tok,
            "DET": DET, "M1": M1, "det_agents": det_agents, "n": n,
            "ctrl_hit_expected": ctrl_hit_expected, "cardinality": cardinality,
            "items": items}


# ==========================================================================
# GATE B — manipulation check.
# ==========================================================================
def gate_b(A):
    items = A["items"]
    card = A["cardinality"]
    ctrl = A["ctrl_hit_expected"]
    valid_idx = [c["q"] for c in card if ctrl[c["q"]] >= CONTROL_MIN_MODELS]
    sigs, expected, attr = A["sigs"], A["expected"], A["attractor_tok"]
    DET = A["DET"]

    # per-agent attractor hit rate over valid items
    hit_rate = {}
    for a in DET:
        m, meth = A["det_agents"][a]
        hits = sum(1 for q in valid_idx if sigs[a][q] == [attr[q]] and not is_non_answer(sigs[a][q]))
        hit_rate[f"{m.split('/')[-1]}|{meth}"] = round(hits / len(valid_idx), 4) if valid_idx else None

    dens = [card[q]["m_wrong"] for q in valid_idx]
    conc = [card[q]["attractor_concentration"] for q in valid_idx
            if card[q]["attractor_concentration"] is not None]
    n_attr_items = sum(1 for q in valid_idx if card[q]["attractor_hits"] >= GATEB_MIN_HITS)
    density = float(np.mean(dens)) if dens else 0.0
    med_conc = float(np.median(conc)) if conc else 0.0

    space = Counter(card[q]["space"] for q in valid_idx)
    regime_valid = (n_attr_items >= GATEB_MIN_ATTRACTOR_ITEMS
                    and med_conc >= GATEB_MIN_CONCENTRATION
                    and density >= GATEB_MIN_DENSITY)
    return {"n_items": len(items), "n_control_valid": len(valid_idx),
            "attractor_hit_rate_per_agent": hit_rate,
            "mean_wrong_per_item_density": round(density, 3),
            "median_attractor_concentration": round(med_conc, 3),
            "n_attractor_items_ge3_hits": n_attr_items,
            "space_bins_valid_items": dict(space),
            "median_distinct_wrong": float(np.median([card[q]["distinct_wrong"] for q in valid_idx])) if valid_idx else None,
            "thresholds": {"min_attractor_items": GATEB_MIN_ATTRACTOR_ITEMS,
                           "min_concentration": GATEB_MIN_CONCENTRATION,
                           "min_density": GATEB_MIN_DENSITY, "min_hits": GATEB_MIN_HITS},
            "REGIME_VALID": regime_valid,
            "valid_idx": valid_idx}


# ==========================================================================
# PHASE D — Route 2 metrics (only if regime-valid).
# ==========================================================================
def _pairs(idxs):
    return [(idxs[a], idxs[b]) for a in range(len(idxs)) for b in range(a + 1, len(idxs))]


def excess_cell(pairs, sigs, expected, ref_idx, keep, seed):
    ks = set(keep)
    n = len(expected)
    msigs = [[s[q] if q in ks else expected[q] for q in range(n)] for s in sigs]
    per = []
    for (i, j) in pairs:
        obs, nb = observed_convergence(msigs[i], msigs[j], expected)
        base, _ = baseline_convergence(i, j, msigs, expected, ref_idx)
        exc = None if (np.isnan(obs) or np.isnan(base)) else round(float(obs - base), 4)
        per.append({"pair": list((i, j)), "observed": None if np.isnan(obs) else round(float(obs), 4),
                    "baseline": None if np.isnan(base) else round(float(base), 4),
                    "excess": exc, "n_both_wrong": nb})
    ev = [p["excess"] for p in per if p["excess"] is not None]
    return {"n_pairs": len(ev), "excess_over_pairs_ci": _ci(ev, seed=seed), "per_pair": per}


def escape_rate(agent, sigs, attr, keep):
    """Fraction of items (in keep) where the agent does NOT give the attractor
    (answer-bearing). Non-answers count as escape=False (did not escape)."""
    esc = tot = 0
    for q in keep:
        if is_non_answer(sigs[agent][q]):
            tot += 1
            continue
        tot += 1
        if sigs[agent][q] != [attr[q]]:
            esc += 1
    return esc / tot if tot else None


def mcnemar(agent_a, agent_b, sigs, attr, keep):
    """Paired: does A escape where B doesn't (and vice versa)? Discordant pairs.
    escape = answer-bearing and != attractor."""
    def esc(a, q):
        return (not is_non_answer(sigs[a][q])) and sigs[a][q] != [attr[q]]
    b_only = a_only = both = neither = 0
    for q in keep:
        ea, eb = esc(agent_a, q), esc(agent_b, q)
        if ea and not eb:
            a_only += 1
        elif eb and not ea:
            b_only += 1
        elif ea and eb:
            both += 1
        else:
            neither += 1
    disc = a_only + b_only
    # exact binomial two-sided p on discordant pairs (McNemar exact)
    from math import comb as _c
    if disc == 0:
        p = 1.0
    else:
        k = min(a_only, b_only)
        p = min(1.0, 2 * sum(_c(disc, i) for i in range(0, k + 1)) / (2 ** disc))
    return {"a_escapes_b_not": a_only, "b_escapes_a_not": b_only,
            "both": both, "neither": neither, "discordant": disc,
            "exact_p": round(p, 4)}


def heldout_lift(pi, pj, heldout, sigs, expected, keep, seed):
    """C1: on items where pair (pi,pj) agree (answer-bearing), precision of the
    agreed answer minus the mean accuracy of HELD-OUT agents on those items.
    Bootstrap over ITEMS (C2). Reports per-held-out and mean."""
    agree_q = [q for q in keep
               if not is_non_answer(sigs[pi][q]) and not is_non_answer(sigs[pj][q])
               and sigs[pi][q] == sigs[pj][q]]
    if not agree_q:
        return {"n_agree": 0, "precision_item_ci": (None, None, None),
                "heldout_acc": {}, "lift_vs_mean_item_ci": (None, None, None)}
    correct = np.array([1.0 if sigs[pi][q] == expected[q] else 0.0 for q in agree_q])
    ho_acc = {}
    ho_terms = {}
    for h in heldout:
        terms = [1.0 if (not is_non_answer(sigs[h][q]) and sigs[h][q] == expected[q]) else 0.0
                 for q in agree_q]
        ho_acc[h] = round(float(np.mean(terms)), 4)
        ho_terms[h] = np.array(terms)
    mean_ho = np.mean([ho_terms[h] for h in heldout], axis=0)  # per-item mean held-out acc
    lift_per_item = correct - mean_ho
    rng = np.random.default_rng(seed)
    def boot(v):
        b = [rng.choice(v, len(v), True).mean() for _ in range(3000)]
        return (round(float(v.mean()), 4), round(float(np.percentile(b, 2.5)), 4),
                round(float(np.percentile(b, 97.5)), 4))
    return {"n_agree": len(agree_q), "precision_item_ci": boot(correct),
            "heldout_acc": ho_acc, "lift_vs_mean_item_ci": boot(lift_per_item)}


def phase_d(A, valid_idx):
    sigs, expected, attr = A["sigs"], A["expected"], A["attractor_tok"]
    DET, M1, card = A["DET"], A["M1"], A["cardinality"]
    ref_idx = DET
    attr_items = [q for q in valid_idx if card[q]["attractor_hits"] >= GATEB_MIN_HITS]

    llama = 0
    cot, dec, code = _det_index(llama, 0), _det_index(llama, 1), _det_index(llama, 2)
    cot_all = [_det_index(mi, 0) for mi in range(4)]
    heldout_for_llama = [_det_index(mi, 0) for mi in range(1, 4)] + M1  # other COT + M1

    mech = {
        "M1_same_model_samples": _pairs(M1),
        "M2_cross_family_cot": _pairs(cot_all),
        "M3_cross_method_llama": _pairs([cot, dec, code]),
        "M3_mixed_model_method": [(i, j) for i in DET for j in DET if i < j and i % 3 != j % 3],
    }
    excess = {k: excess_cell(v, sigs, expected, ref_idx, attr_items, seed=200 + i)
              for i, (k, v) in enumerate(mech.items())}

    escapes = {f"llama|{METHODS[j]}": escape_rate(_det_index(llama, j), sigs, attr, attr_items)
               for j in range(3)}
    # D2 discriminator: pairwise (COT×DECOMP primary, no oracle)
    disc = {
        "COT_x_DECOMP_primary": {
            "excess": excess_cell([(cot, dec)], sigs, expected, ref_idx, attr_items, 301)["per_pair"],
            "mcnemar_DECOMP_vs_COT": mcnemar(dec, cot, sigs, attr, attr_items),
            "heldout_lift": heldout_lift(cot, dec, heldout_for_llama, sigs, expected, attr_items, 401)},
        "COT_x_CODE": {
            "excess": excess_cell([(cot, code)], sigs, expected, ref_idx, attr_items, 302)["per_pair"],
            "mcnemar_CODE_vs_COT": mcnemar(code, cot, sigs, attr, attr_items)},
        "DECOMP_x_CODE": {
            "excess": excess_cell([(dec, code)], sigs, expected, ref_idx, attr_items, 303)["per_pair"],
            "mcnemar_CODE_vs_DECOMP": mcnemar(code, dec, sigs, attr, attr_items)},
    }

    # Delta = excess(M1) - excess(M3 model-controlled), item-bootstrap on the
    # per-item excess is not defined (excess is pairwise); report over-pairs
    # means and flag.
    dm1 = [p["excess"] for p in excess["M1_same_model_samples"]["per_pair"] if p["excess"] is not None]
    dm3 = [p["excess"] for p in excess["M3_cross_method_llama"]["per_pair"] if p["excess"] is not None]
    rng = np.random.default_rng(7)
    if dm1 and dm3:
        a, b = np.array(dm1), np.array(dm3)
        boot = [rng.choice(a, len(a), True).mean() - rng.choice(b, len(b), True).mean() for _ in range(3000)]
        delta = (round(float(a.mean() - b.mean()), 4), round(float(np.percentile(boot, 2.5)), 4),
                 round(float(np.percentile(boot, 97.5)), 4))
    else:
        delta = (None, None, None)

    return {"n_attractor_items": len(attr_items), "attractor_item_ids": [card[q]["id"] for q in attr_items],
            "excess_by_mechanism": excess, "escape_rate_by_method": escapes,
            "discriminator": disc, "delta_excess_M1_minus_M3_over_pairs": delta}


def decide(gb, d):
    """D3 decision, corrected (C1/C2/C3)."""
    if not gb["REGIME_VALID"]:
        return {"case": "ROUTE_2_UNFALSIFIABLE_IN_PRACTICE",
                "reason": ("Three successive designs (MBPP constrained, MATH open, "
                           "and this adversarial attractor induction) failed to "
                           "produce a testable dense-open-error regime. GATE B not "
                           "met: see counts. Terminal — commit to Route 1.")}
    prim = d["discriminator"]["COT_x_DECOMP_primary"]
    cd_excess = prim["excess"][0]["excess"] if prim["excess"] else None
    mcn = prim["mcnemar_DECOMP_vs_COT"]
    lift = prim["heldout_lift"]["lift_vs_mean_item_ci"]
    esc = d["escape_rate_by_method"]
    esc_cot, esc_dec, esc_code = esc.get("llama|COT"), esc.get("llama|DECOMP"), esc.get("llama|CODE")

    cd_decorr = (cd_excess is not None and cd_excess <= 0)
    dec_beats_cot = (mcn["exact_p"] < 0.05 and mcn["b_escapes_a_not"] > mcn["a_escapes_b_not"]) \
        if False else (mcn["exact_p"] < 0.05 and mcn["a_escapes_b_not"] > mcn["b_escapes_a_not"])
    lift_pos = lift[1] is not None and lift[1] > 0
    only_code = (esc_code is not None and esc_cot is not None and esc_dec is not None
                 and esc_code - max(esc_cot, esc_dec) > 0.15
                 and abs((esc_dec or 0) - (esc_cot or 0)) < 0.1)

    if cd_decorr and dec_beats_cot and lift_pos:
        case = "ROUTE_2_LIVE"
    elif only_code and not (dec_beats_cot and lift_pos):
        case = "ROUTE_2_MIRAGE"
    elif (esc_cot is not None and esc_dec is not None
          and abs(esc_dec - esc_cot) < 0.1 and not dec_beats_cot):
        case = "ROUTE_2_CLOSED"
    else:
        case = "INCONCLUSIVE_OR_MIXED"
    return {"case": case, "cot_x_decomp_excess": cd_excess,
            "mcnemar_DECOMP_vs_COT": mcn, "heldout_lift_ci": lift,
            "escape_COT": esc_cot, "escape_DECOMP": esc_dec, "escape_CODE": esc_code}


def _data_integrity(items):
    groups = [(m, meth) for m, _f in MODELS for meth in METHODS]
    groups += [(m, "CONTROL") for m, _f in MODELS] + [(FIXED_MODEL, "M1COT")]
    per, err, tot = {}, 0, 0
    for m, meth in groups:
        c = _load_cache(m, meth)
        e = sum(1 for iid in c for s in c[iid] if str(c[iid][s].get("raw", "")).startswith("__ERR__"))
        nn = sum(len(c[iid]) for iid in c)
        per[f"{m}|{meth}"] = {"failed": e, "n": nn}
        err += e
        tot += nn
    return {"total": tot, "failed_402": err,
            "failed_fraction": round(err / tot, 4) if tot else None, "per_group": per}


def analyze(items):
    A = assemble(items)
    gb = gate_b(A)
    result = {"config": {"seed": SEED, "models": [m for m, _ in MODELS], "methods": METHODS,
                         "k_samples": K_SAMPLES, "n_items": len(items)},
              "data_integrity": _data_integrity(items),
              "GATE_B": {k: v for k, v in gb.items() if k != "valid_idx"},
              "space_cardinality_full": A["cardinality"]}
    if gb["REGIME_VALID"]:
        d = phase_d(A, gb["valid_idx"])
        result["phase_D"] = d
        result["DECISION"] = decide(gb, d)
    else:
        result["DECISION"] = decide(gb, None)
    return result


def main(argv):
    items = load_items()
    cmd = argv[1] if len(argv) > 1 else "analyze"
    if cmd == "plan":
        print(json.dumps(plan_and_balance(items), indent=2))
        return 0
    if cmd == "generate":
        generate_all(items)
        return 0
    if cmd == "analyze":
        res = analyze(items)
        RESULT.write_text(json.dumps(res, indent=2))
        print("GATE B REGIME_VALID:", res["GATE_B"]["REGIME_VALID"])
        print("  control-valid items:", res["GATE_B"]["n_control_valid"],
              "| attractor items (>=3 hits):", res["GATE_B"]["n_attractor_items_ge3_hits"],
              "| density:", res["GATE_B"]["mean_wrong_per_item_density"],
              "| median concentration:", res["GATE_B"]["median_attractor_concentration"])
        print("DECISION:", res["DECISION"]["case"])
        return 0
    print("usage: route3_experiment.py [plan|generate|analyze]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
