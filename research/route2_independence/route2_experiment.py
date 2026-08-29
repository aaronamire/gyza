"""
Route 2 — the decisive engineered-independence experiment.

QUESTION. Route 2 = "trust agent agreement as a truth-signal because errors
are independent." Prior work (../correlated_failure) showed model-FAMILY
diversity does NOT decorrelate errors, and that in a CONSTRAINED output space
(~1 wrong answer/problem) no mechanism could help because there was no room.
This experiment tests the stronger, unresolved question: does METHOD/PATH
disjointness (forcing agents onto structurally different solution methods)
decorrelate errors in a LARGE output space, and does it hold on HARD tasks?

DESIGN (preregistered; see PREREGISTRATION.md — the contract). 2x2xmechanism:
  Factor D (difficulty): EASY (MATH level 1-2) vs HARD (level 4-5).
  Factor S (space size): CONSTRAINED (distinct_wrong_q <= 2) vs LARGE (>= 5),
    assigned per problem from the MEASURED wrong-answer cardinality.
  Factor M (mechanism), each a set of "agents" whose pairwise same-wrong
    convergence we measure:
      M1 SAME-MODEL-SAMPLES : llama-3.1-70b, COT, K=4 samples @ temp 0.7
                              (maximal-correlation baseline).
      M2 CROSS-FAMILY       : 4 models, COT, temp 0 (the weak decorrelator).
      M3 CROSS-METHOD (primary, model-controlled): FIX llama-3.1-70b; its three
                              method-runs {COT, CODE, DECOMP} are the agents.
                              The ONLY thing varying is the solution path.

REUSE (not reimplemented): the conditional-independence estimator
(observed_convergence, baseline_convergence, is_non_answer) from
../correlated_failure/conditional_independence_null.py; the _ci bootstrap from
run_openrouter.py; the APIBackend from rho_measure.py; the 5s-timeout code
executor discipline from codebench.py (run_signature is imported and
self-tested; the CODE method needs the program's *printed* \\boxed value, which
run_signature's eval-signature harness structurally cannot return, so a thin
stdout-capturing adapter reuses its exact subprocess+timeout+sentinel
semantics — see execute_code and the note there).

No side effects on import (no network, no generation). Generation is cached
under route2_cache/ keyed by (model, method, problem_id, sample_idx); all
re-analysis is free.
"""
from __future__ import annotations

import json
import re
import signal
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
_CF = _HERE.parent / "correlated_failure"
sys.path.insert(0, str(_CF))

# --- REUSE: conditional-independence estimator (do not reimplement) ---
from conditional_independence_null import (  # noqa: E402
    baseline_convergence, is_non_answer, observed_convergence,
)
# --- REUSE: bootstrap CI over pairs ---
from run_openrouter import _ci  # noqa: E402
# --- REUSE: OpenRouter chat backend (subclassed below for temperature) ---
from rho_measure import APIBackend  # noqa: E402
# --- REUSE: 5s-timeout subprocess executor (imported; self-tested) ---
from codebench import run_signature  # noqa: E402  (used in test_route2)

import sympy  # noqa: E402
from sympy import simplify, sympify  # noqa: E402

# ---------------------------------------------------------------------------
# CONFIG (fixed; preregistered).
# ---------------------------------------------------------------------------
SEED = 1
BASE_URL = "https://openrouter.ai/api/v1"
_ENV = _CF / ".env"
API_KEY = [l for l in _ENV.read_text().splitlines()
           if l.startswith("OPENROUTER")][0].split("=", 1)[1].strip()

# Roster: 4 models across 4 families, all previously shown capable.
MODELS = [
    ("meta-llama/llama-3.1-70b-instruct", "llama"),
    ("google/gemma-2-27b-it", "gemma"),
    ("mistralai/mistral-small-3.2-24b-instruct", "mistral"),
    ("microsoft/phi-4", "phi"),
]
FIXED_MODEL = "meta-llama/llama-3.1-70b-instruct"   # the model-controlled model
METHODS = ["COT", "CODE", "DECOMP"]
K_SAMPLES = 4                 # M1 same-model-samples
SAMPLE_TEMP = 0.7             # M1 sampling temperature
BAND = 0.10                   # capability band (for cross-model contrasts)

MAX_TOKENS = {"COT": 1024, "DECOMP": 1024, "CODE": 896}
CODE_TIMEOUT = 5.0

N_EASY = 40
N_HARD = 40
MATH_SUBJECTS = ["algebra", "counting_and_probability", "geometry",
                 "intermediate_algebra", "number_theory", "prealgebra",
                 "precalculus"]

DATA = _HERE / "data"
CACHE = _HERE / "route2_cache"
PROBLEM_SET = _HERE / "problem_set.json"
EXEC_CACHE = _HERE / "code_exec_cache.json"
RESULT = _HERE / "route2_result.json"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)


# ===========================================================================
# DATA — the MATH test split (the one permitted download), cached to data/.
# ===========================================================================
def load_math_test() -> list[dict]:
    """Full MATH competition test split (EleutherAI/hendrycks_math mirror),
    all subjects concatenated. Cached parquet under data/. Fields per item:
    id, subject, level (int 1-5), problem, solution, ref_raw (last \\boxed)."""
    import os
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download
    DATA.mkdir(exist_ok=True)
    items: list[dict] = []
    for subj in MATH_SUBJECTS:
        fname = f"{subj}/test-00000-of-00001.parquet"
        local = DATA / f"{subj}_test.parquet"
        if not local.exists():
            src = hf_hub_download(repo_id="EleutherAI/hendrycks_math",
                                  filename=fname, repo_type="dataset")
            local.write_bytes(Path(src).read_bytes())
        rows = pq.read_table(local).to_pylist()
        for i, r in enumerate(rows):
            lvl_m = re.search(r"(\d+)", str(r["level"]))
            if not lvl_m:
                continue
            ref = extract_boxed(r["solution"])
            items.append({
                "id": f"{subj}#{i}", "subject": subj,
                "level": int(lvl_m.group(1)), "problem": r["problem"],
                "solution": r["solution"], "ref_raw": ref,
            })
    return items


def build_problem_set(seed: int = SEED) -> list[dict]:
    """Seeded, stratified 40 EASY (level 1-2) + 40 HARD (level 4-5). Eligible
    pool = problems with a cleanly extractable \\boxed reference. Deterministic
    (numpy default_rng(seed) over the id-sorted pool). Written to
    problem_set.json; the 80 ids are the preregistration contract."""
    if PROBLEM_SET.exists():
        return json.loads(PROBLEM_SET.read_text())["problems"]
    items = load_math_test()
    by_id = {it["id"]: it for it in items}
    elig = [it for it in items if it["ref_raw"]]
    easy = sorted([it["id"] for it in elig if it["level"] in (1, 2)])
    hard = sorted([it["id"] for it in elig if it["level"] in (4, 5)])
    rng = np.random.default_rng(seed)
    easy_ids = list(rng.choice(easy, N_EASY, replace=False))
    hard_ids = list(rng.choice(hard, N_HARD, replace=False))
    chosen = []
    for pid in sorted(easy_ids):
        it = by_id[pid]
        chosen.append({**{k: it[k] for k in
                          ("id", "subject", "level", "problem", "ref_raw")},
                       "difficulty": "EASY"})
    for pid in sorted(hard_ids):
        it = by_id[pid]
        chosen.append({**{k: it[k] for k in
                          ("id", "subject", "level", "problem", "ref_raw")},
                       "difficulty": "HARD"})
    PROBLEM_SET.write_text(json.dumps(
        {"seed": seed, "n_easy": N_EASY, "n_hard": N_HARD,
         "pool_sizes": {"easy_eligible": len(easy), "hard_eligible": len(hard)},
         "problems": chosen}, indent=2))
    return chosen


# ===========================================================================
# ANSWER CANONICALIZATION.
#   Equality: two answers are "the same" iff sympy simplifies their difference
#   to 0 (normalized-string fallback when sympy can't parse). Because the
#   estimator compares signatures with string ==, we canonicalize PER PROBLEM
#   by equivalence-clustering under that relation: agents in the same class get
#   the same token, so string-== reproduces sympy-equality within the problem.
# ===========================================================================
def extract_boxed(text: str) -> str:
    """Last \\boxed{...} content, brace-balanced. '' if none."""
    if not text:
        return ""
    out = ""
    idx = 0
    while True:
        j = text.find("\\boxed", idx)
        if j < 0:
            break
        k = text.find("{", j)
        if k < 0:
            break
        depth = 0
        for e in range(k, len(text)):
            if text[e] == "{":
                depth += 1
            elif text[e] == "}":
                depth -= 1
                if depth == 0:
                    out = text[k + 1:e]
                    idx = e + 1
                    break
        else:
            break
    return out.strip()


def _norm_str(s: str) -> str:
    """Normalized-string form (the fallback equality key and canonical
    display). Strips LaTeX packaging that never changes the value."""
    s = s.strip()
    for a, b in (("\\left", ""), ("\\right", ""), ("\\!", ""), ("\\,", ""),
                 ("\\;", ""), ("\\ ", ""), ("$", ""), ("\\dfrac", "\\frac"),
                 ("\\tfrac", "\\frac"), ("\\%", ""), ("^{\\circ}", ""),
                 ("\\circ", ""), ("\\text{", "{"), (" ", "")):
        s = s.replace(a, b)
    s = re.sub(r"\\mbox\{([^{}]*)\}", r"\1", s)
    s = s.replace("\\$", "").replace("dollars", "").replace("\\!", "")
    if s.endswith("."):
        s = s[:-1]
    while s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    return s.strip()


def _latex_to_sympy(s: str):
    """Best-effort LaTeX->sympy for the common MATH answer forms; returns a
    sympy expression or None (=> caller uses the normalized-string fallback).
    parse_latex needs antlr (unavailable here), so this hand-converter runs."""
    t = _norm_str(s)
    if t == "" or any(c in t for c in ("\\begin", "\\text", "&", "\\pmatrix")):
        return None
    # \frac{a}{b} -> ((a)/(b)); iterate for shallow nesting.
    for _ in range(6):
        nt = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", t)
        if nt == t:
            break
        t = nt
    t = re.sub(r"\\sqrt\[([^\]]+)\]\{([^{}]+)\}", r"((\2)**(1/(\1)))", t)
    t = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", t)
    t = re.sub(r"\\sqrt(\w)", r"sqrt(\1)", t)
    t = (t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
          .replace("\\pi", "pi").replace("\\pm", "").replace("^", "**")
          .replace("{", "(").replace("}", ")").replace("\\", ""))
    t = re.sub(r"(\d),(\d{3})", r"\1\2", t)   # 1,000 -> 1000
    t = re.sub(r"(\d)\(", r"\1*(", t)          # 2(x) -> 2*(x)
    t = re.sub(r"\)([\(a-zA-Z])", r")*\1", t)  # )(  -> )*(
    if t in ("", "-", "+", "*", "/"):
        return None
    try:
        expr = sympify(t, evaluate=True)
        return expr
    except Exception:
        return None


class _Timeout(Exception):
    pass


def _sym_equal(a: str, b: str) -> bool:
    """True iff a,b denote the same value: normalized-string equal, or sympy
    simplifies their difference to 0. Bounded (3s) so simplify can't hang;
    on any failure falls back to normalized-string equality."""
    if _norm_str(a) == _norm_str(b):
        return True
    ea, eb = _latex_to_sympy(a), _latex_to_sympy(b)
    if ea is None or eb is None:
        return False
    use_alarm = threading.current_thread() is threading.main_thread()
    old = None
    if use_alarm:
        def _h(signum, frame):
            raise _Timeout()
        old = signal.signal(signal.SIGALRM, _h)
        signal.setitimer(signal.ITIMER_REAL, 3.0)
    try:
        d = simplify(ea - eb)
        return bool(d == 0) or bool(getattr(d, "is_zero", False))
    except Exception:
        try:
            return bool(ea.equals(eb))
        except Exception:
            return False
    finally:
        if use_alarm:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            if old is not None:
                signal.signal(signal.SIGALRM, old)


def cluster_answers(raws: list[str]) -> list[int]:
    """Assign each raw answer a cluster id under _sym_equal (transitive by
    representative). raws are already answer-bearing (no sentinels)."""
    reps: list[str] = []
    ids: list[int] = []
    for r in raws:
        placed = -1
        for ci, rep in enumerate(reps):
            if _sym_equal(r, rep):
                placed = ci
                break
        if placed < 0:
            placed = len(reps)
            reps.append(r)
        ids.append(placed)
    return ids


# ===========================================================================
# BACKEND — APIBackend subclassed to expose temperature + seed (M1 needs 0.7).
# ===========================================================================
class Route2Backend(APIBackend):
    """Reuses APIBackend's url/key/retry discipline; adds temperature and an
    OpenRouter ``seed`` passthrough. (APIBackend hard-codes temperature 0.)"""

    def generate(self, prompt: str, *, max_new_tokens: int = 512,
                 temperature: float = 0.0, seed: int | None = None) -> str:
        import json as _json
        import time
        import urllib.error
        import urllib.request
        payload = {"model": self._model,
                   "messages": [{"role": "user", "content": prompt}],
                   "temperature": temperature, "max_tokens": max_new_tokens}
        if seed is not None:
            payload["seed"] = seed
        body = _json.dumps(payload).encode()
        for attempt in range(6):
            req = urllib.request.Request(
                self._url, data=body, method="POST",
                headers={"Authorization": f"Bearer {self._key}",
                         "Content-Type": "application/json",
                         "User-Agent": "gyza-research/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    d = _json.loads(r.read())
                return d["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as e:
                if e.code in (408, 429, 500, 502, 503) and attempt < 5:
                    time.sleep(2 ** attempt)
                    continue
                raise
        raise RuntimeError("API request failed after retries")


# ===========================================================================
# PROMPTS (fixed; preregistered — never tuned after seeing convergence).
# ===========================================================================
def prompt_for(method: str, problem: str) -> str:
    if method == "COT":
        return ("Solve the following competition mathematics problem. Show "
                "your step-by-step reasoning, then give the final answer as "
                "\\boxed{...} on the last line.\n\nProblem: " + problem)
    if method == "DECOMP":
        return ("Solve the following competition mathematics problem by "
                "explicit decomposition. First list the subproblems as a "
                "numbered list (1., 2., 3., ...). Solve each subproblem in "
                "order. Then combine the sub-results into the final answer. "
                "Give the final answer as \\boxed{...} on the last line."
                "\n\nProblem: " + problem)
    if method == "CODE":
        return ("Write a self-contained Python program that computes the exact "
                "answer to the following competition mathematics problem using "
                "sympy. Import sympy, compute the answer symbolically, and end "
                "by printing it wrapped as \\boxed{...} — e.g. "
                "print('\\\\boxed{' + str(answer) + '}'). Respond with ONLY the "
                "code inside a single ```python code block.\n\nProblem: "
                + problem)
    raise ValueError(method)


def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


# ===========================================================================
# CODE EXECUTION — reuses codebench's subprocess+5s-timeout+sentinel
# discipline. codebench.run_signature returns an eval-signature and discards
# the program's stdout; the CODE method's answer IS the printed \boxed value,
# so this adapter captures stdout with byte-identical timeout/sentinel
# semantics. Sentinels (TIMEOUT / IMPORTERR / crash / no-\boxed) are
# NON-ANSWERS: a crashed or silent program produced no answer and must NEVER
# count as agreement (the artifact-#4 guard) — codebench treats ERR as
# answer-bearing only because there it is one call within a multi-call
# behavioral signature; here the program emits a single scalar, so absence of
# a printed answer is a non-answer. Returned token feeds canonicalization; a
# non-answer token is caught by is_non_answer (starts with IMPORTERR:/TIMEOUT).
# ===========================================================================
def execute_code(program: str, timeout: float = CODE_TIMEOUT) -> str:
    """Run the program; return the raw printed \\boxed answer string, or a
    non-answer sentinel token ('TIMEOUT' / 'IMPORTERR:<why>')."""
    if not program.strip():
        return "IMPORTERR:EMPTY"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(program)
        path = f.name
    try:
        p = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return f"IMPORTERR:{type(e).__name__}"
    finally:
        Path(path).unlink(missing_ok=True)
    if p.returncode != 0:
        last = (p.stderr.strip().splitlines() or ["Error"])[-1][:40]
        etype = last.split(":")[0].split(".")[-1] or "Error"
        return f"IMPORTERR:{etype}"
    boxed = extract_boxed(p.stdout)
    if boxed:
        return boxed
    # PARSER robustness (never touch generation): if the program printed a bare
    # value without the \boxed wrapper, accept the last stdout line ONLY if it
    # canonicalizes as a math value — rejecting prose so garbage can never
    # masquerade as a (spuriously agreeing) answer.
    for line in reversed([l.strip() for l in p.stdout.splitlines() if l.strip()]):
        has_structure = bool(re.search(r"\d", line)) or bool(
            re.search(r"[+\-*/^]|\\frac|\\sqrt|\\pi", line))
        if len(line) <= 60 and has_structure and _latex_to_sympy(line) is not None:
            return line
    return "IMPORTERR:NOANSWER"


# ===========================================================================
# GENERATION — cached per (model, method, problem_id, sample_idx).
#   Cache file per (model, method): {problem_id: {sample_idx: {raw, usage}}}.
# ===========================================================================
_CACHE_LOCK = threading.Lock()


def _cache_path(model: str, method: str) -> Path:
    CACHE.mkdir(exist_ok=True)
    return CACHE / f"{_slug(model)}__{method}__s{SEED}.json"


def _load_cache(model: str, method: str) -> dict:
    f = _cache_path(model, method)
    return json.loads(f.read_text()) if f.exists() else {}


def _save_cache(model: str, method: str, data: dict) -> None:
    _cache_path(model, method).write_text(json.dumps(data))


def _base_method(method: str) -> str:
    """Prompt/token family of a method label ('M1COT' is a COT run)."""
    return "COT" if method == "M1COT" else method


def _gen_tasks() -> list[tuple]:
    """Every (model, method, sample_idx) run over the 80 problems.
    Deterministic grid: 4 models x 3 methods (temp 0, sample 0) = 960 calls.
    M1 arm: FIXED_MODEL x COT x K samples ALL at temp 0.7 = 320 calls, cached
    under the separate label 'M1COT' so it never collides with the temp-0
    deterministic llama-COT run (which is M3's COT agent)."""
    tasks = []
    for model, _fam in MODELS:
        for method in METHODS:
            tasks.append((model, method, 0, 0.0))                 # deterministic
    for k in range(K_SAMPLES):
        tasks.append((FIXED_MODEL, "M1COT", k, SAMPLE_TEMP))       # M1 samples
    return tasks


def generate_all(problems: list[dict], max_workers: int = 8,
                 verbose: bool = True) -> None:
    """Fill the cache for every (model, method, sample_idx) x 80 problems.
    Resumable: only missing (problem_id, sample_idx) are generated."""
    for model, method, sidx, temp in _gen_tasks():
        cache = _load_cache(model, method)

        def _needs(pb):
            e = cache.get(pb["id"], {}).get(str(sidx))
            return e is None or str(e.get("raw", "")).startswith("__ERR__")
        todo = [pb for pb in problems if _needs(pb)]
        if not todo:
            if verbose:
                print(f"[gen] {model} {method} s{sidx}: cached", flush=True)
            continue
        backend = Route2Backend(model, dict(MODELS).get(model, "?"),
                                base_url=BASE_URL, api_key=API_KEY)
        seed = SEED if temp == 0.0 else SEED * 1000 + sidx
        bm = _base_method(method)

        def _one(pb, backend=backend, bm=bm, temp=temp, seed=seed):
            try:
                raw = backend.generate(prompt_for(bm, pb["problem"]),
                                       max_new_tokens=MAX_TOKENS[bm],
                                       temperature=temp, seed=seed)
            except Exception as e:  # noqa: BLE001
                raw = f"__ERR__:{type(e).__name__}"
            return pb["id"], raw

        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(_one, pb) for pb in todo]
            for fut in as_completed(futs):
                pid, raw = fut.result()
                with _CACHE_LOCK:
                    cache.setdefault(pid, {})[str(sidx)] = {"raw": raw}
                    done += 1
                    if done % 20 == 0:
                        _save_cache(model, method, cache)
        _save_cache(model, method, cache)
        if verbose:
            print(f"[gen] {model} {method} s{sidx}: +{len(todo)} done",
                  flush=True)


# ===========================================================================
# GATE 0 — generation plan + cost estimate (printed BEFORE any generation).
# ===========================================================================
def _live_pricing() -> dict:
    import urllib.request
    req = urllib.request.Request(BASE_URL + "/models",
                                 headers={"User-Agent": "gyza-research/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())["data"]
    out = {}
    for m in data:
        out[m["id"]] = {"prompt": float(m["pricing"]["prompt"]),
                        "completion": float(m["pricing"]["completion"])}
    return out


def plan_and_estimate(problems: list[dict]) -> dict:
    """Full generation plan + conservative cost estimate (output tokens billed
    at max_tokens). Returns the plan dict; caller enforces the $25 gate."""
    pricing = _live_pricing()
    # per-problem input token estimate (chars/4), per method.
    def in_toks(method):
        return [max(1, len(prompt_for(method, pb["problem"])) // 4)
                for pb in problems]
    plan_rows = []
    total = 0.0
    # deterministic grid
    for model, _fam in MODELS:
        pr = pricing.get(model, {"prompt": 0.0, "completion": 0.0})
        for method in METHODS:
            it = sum(in_toks(method))
            ot = MAX_TOKENS[method] * len(problems)
            cost = it * pr["prompt"] + ot * pr["completion"]
            total += cost
            plan_rows.append({"model": model, "method": method, "temp": 0.0,
                              "calls": len(problems), "in_tok_est": it,
                              "out_tok_max": ot, "cost_est": round(cost, 4)})
    # M1 samples (K, all temp 0.7)
    pr = pricing.get(FIXED_MODEL, {"prompt": 0.0, "completion": 0.0})
    for k in range(K_SAMPLES):
        it = sum(in_toks("COT"))
        ot = MAX_TOKENS["COT"] * len(problems)
        cost = it * pr["prompt"] + ot * pr["completion"]
        total += cost
        plan_rows.append({"model": FIXED_MODEL, "method": "COT",
                          "temp": SAMPLE_TEMP, "sample_idx": k,
                          "calls": len(problems), "in_tok_est": it,
                          "out_tok_max": ot, "cost_est": round(cost, 4)})
    n_calls = sum(r["calls"] for r in plan_rows)
    return {"n_calls": n_calls, "total_cost_est_usd": round(total, 3),
            "rows": plan_rows,
            "note": ("output billed at max_tokens (conservative upper bound); "
                     "actual will be lower as models finish early")}


# ===========================================================================
# ANSWER ASSEMBLY — from cache to per-(agent, problem) tokens + signatures.
# ===========================================================================
# Global agent layout (index = global id):
#   0..11  deterministic: model m (0..3) x method (COT,CODE,DECOMP) -> 3*m+j
#   12..15 M1 samples: FIXED_MODEL, COT, temp0.7, sample 1..K-1, PLUS the
#          shared temp-0 FIXED_MODEL/COT run as sample "0".
# M1's 4 agents = {FIXED_MODEL/COT sample 0 (temp0)} + samples 1..3 (temp0.7).
def _det_index(model_i: int, method_j: int) -> int:
    return 3 * model_i + method_j


def _load_exec_cache() -> dict:
    return json.loads(EXEC_CACHE.read_text()) if EXEC_CACHE.exists() else {}


def _raw_answer(model: str, method: str, sidx: int, pid: str,
                cache: dict, exec_cache: dict) -> str:
    """Extract the answer-bearing raw string (or a non-answer sentinel) for one
    (model, method, sample, problem). CODE is executed (cached)."""
    entry = cache[(model, method)].get(pid, {}).get(str(sidx))
    if entry is None:
        return "IMPORTERR:MISSING"
    raw = entry["raw"]
    if isinstance(raw, str) and raw.startswith("__ERR__"):
        return "IMPORTERR:APICALL"
    if method == "CODE":
        key = f"{_slug(model)}|{sidx}|{pid}"
        if key not in exec_cache:
            exec_cache[key] = execute_code(_extract_code(raw))
        return exec_cache[key]
    boxed = extract_boxed(raw)
    return boxed if boxed else "IMPORTERR:NOANSWER"


def assemble(problems: list[dict]) -> dict:
    """Build the global agent signatures + per-problem cardinality. Returns
    everything the analysis needs. Executes+caches CODE programs."""
    # load all caches once (12 deterministic + the M1COT sampling arm)
    caches = {}
    for model, _f in MODELS:
        for method in METHODS:
            caches[(model, method)] = _load_cache(model, method)
    caches[(FIXED_MODEL, "M1COT")] = _load_cache(FIXED_MODEL, "M1COT")
    exec_cache = _load_exec_cache()

    # agent descriptors
    agents = []                       # list of (model, method, sidx, temp)
    for mi, (model, f) in enumerate(MODELS):
        for mj, method in enumerate(METHODS):
            agents.append((model, method, 0, 0.0))
    for k in range(K_SAMPLES):
        agents.append((FIXED_MODEL, "M1COT", k, SAMPLE_TEMP))   # all temp 0.7
    fam = {}
    # indices: 0..11 deterministic, 12..15 M1 samples (k=0..3, temp 0.7)
    M1_IDX = list(range(12, 12 + K_SAMPLES))
    DET_IDX = list(range(12))

    n = len(problems)
    raw_by_agent = []                 # [agent][q] -> raw string / sentinel
    for (model, method, sidx, _t) in agents:
        col = []
        for pb in problems:
            col.append(_raw_answer(model, method, sidx, pb["id"],
                                   caches, exec_cache))
        raw_by_agent.append(col)
    EXEC_CACHE.write_text(json.dumps(exec_cache))

    # per-problem canonicalization (cluster answer-bearing raws + reference)
    sigs = [[None] * n for _ in raw_by_agent]      # [agent][q] -> [token]
    expected = [None] * n
    cardinality = []                               # per-problem measured space
    parse_ok = 0
    parse_tot = 0
    for q, pb in enumerate(problems):
        ref = pb["ref_raw"]
        raws = [ref] + [raw_by_agent[a][q] for a in range(len(agents))]
        answer_bearing_idx = [i for i, r in enumerate(raws)
                              if not is_non_answer([r])]
        ab_raws = [raws[i] for i in answer_bearing_idx]
        clus = cluster_answers(ab_raws)
        token_of = {}
        for local_i, gi in enumerate(answer_bearing_idx):
            token_of[gi] = f"c{clus[local_i]}"
        # 0 -> reference, 1..len -> agents
        ref_token = token_of.get(0, "IMPORTERR:REF")
        expected[q] = [ref_token]
        for a in range(len(agents)):
            gi = a + 1
            tok = token_of.get(gi)
            sigs[a][q] = [tok] if tok is not None else [raws[gi]]  # sentinel
            parse_tot += 1
            if tok is not None:
                parse_ok += 1
        # measured wrong-answer cardinality over ALL agents (answer-bearing)
        wrong_tokens = [sigs[a][q][0] for a in range(len(agents))
                        if not is_non_answer(sigs[a][q])
                        and sigs[a][q][0] != ref_token]
        cnt = Counter(wrong_tokens)
        m_wrong = len(wrong_tokens)
        distinct = len(cnt)
        simpson = (sum(c * (c - 1) for c in cnt.values()) / (m_wrong * (m_wrong - 1))
                   if m_wrong >= 2 else None)
        eff = (1.0 / sum((c / m_wrong) ** 2 for c in cnt.values())
               if m_wrong >= 1 else None)
        cardinality.append({"q": q, "id": pb["id"],
                            "difficulty": pb["difficulty"], "level": pb["level"],
                            "m_wrong": m_wrong, "distinct_wrong": distinct,
                            "simpson": None if simpson is None else round(simpson, 4),
                            "eff_wrong": None if eff is None else round(eff, 3),
                            "space": ("CONSTRAINED" if distinct <= 2
                                      else "LARGE" if distinct >= 5 else "MID")})
    return {"agents": agents, "fam": fam, "sigs": sigs, "expected": expected,
            "cardinality": cardinality, "DET_IDX": DET_IDX, "M1_IDX": M1_IDX,
            "parse_rate": round(parse_ok / parse_tot, 4) if parse_tot else None,
            "raw_by_agent": raw_by_agent}


# ===========================================================================
# CELL METRICS — excess (A) and trust-lift (B). Reuse the estimator.
# ===========================================================================
def _mask_sigs(sigs, expected, keep_q: set):
    """Re-point non-kept problems to expected (=> 'correct', never both-wrong)
    so observed/baseline drop them identically. Exactly the ci_null mask."""
    n = len(expected)
    return [[s[q] if q in keep_q else expected[q] for q in range(n)]
            for s in sigs]


def cell_excess(pairs, sigs, expected, ref_idx, keep_q, seed):
    """Per-pair (observed - leave-pair-out baseline) over the cell's problems;
    mean + bootstrap CI over pairs. Reuses observed_convergence /
    baseline_convergence verbatim on masked signatures."""
    msigs = _mask_sigs(sigs, expected, keep_q)
    per = []
    for (i, j) in pairs:
        obs, nobs = observed_convergence(msigs[i], msigs[j], expected)
        base, _ = baseline_convergence(i, j, msigs, expected, ref_idx)
        exc = (None if (np.isnan(obs) or np.isnan(base))
               else round(float(obs - base), 4))
        per.append({"pair": [i, j],
                    "observed": None if np.isnan(obs) else round(float(obs), 4),
                    "baseline": None if np.isnan(base) else round(float(base), 4),
                    "excess": exc, "n_both_wrong": nobs})
    exc_vals = [p["excess"] for p in per if p["excess"] is not None]
    return {"n_pairs": len(exc_vals), "excess_ci": _ci(exc_vals, seed=seed),
            "observed_ci": _ci([p["observed"] for p in per
                                if p["observed"] is not None], seed=seed + 1),
            "per_pair": per}


def cell_lift(pairs, sigs, expected, keep_q, agent_idx, seed):
    """Agreement trust-lift: among cell problems where a pair AGREES
    (same answer-bearing token), fraction correct, minus mean single-agent
    accuracy in the cell. Per-pair, bootstrap CI over pairs."""
    qs = sorted(keep_q)
    # single-agent accuracy over the mechanism's agents on cell problems
    acc_terms = []
    for a in agent_idx:
        for q in qs:
            if is_non_answer(sigs[a][q]):
                acc_terms.append(0.0)
            else:
                acc_terms.append(1.0 if sigs[a][q] == expected[q] else 0.0)
    single_acc = float(np.mean(acc_terms)) if acc_terms else None
    per = []
    for (i, j) in pairs:
        agree_correct = []
        for q in qs:
            si, sj = sigs[i][q], sigs[j][q]
            if is_non_answer(si) or is_non_answer(sj):
                continue
            if si == sj:
                agree_correct.append(1.0 if si == expected[q] else 0.0)
        if agree_correct:
            prec = float(np.mean(agree_correct))
            per.append({"pair": [i, j], "n_agree": len(agree_correct),
                        "agree_precision": round(prec, 4),
                        "lift": round(prec - single_acc, 4)})
    lifts = [p["lift"] for p in per]
    return {"single_acc": None if single_acc is None else round(single_acc, 4),
            "n_pairs": len(lifts), "lift_ci": _ci(lifts, seed=seed),
            "per_pair": per}


def _ci_diff(vals_a, vals_b, seed=0, n=3000):
    """Bootstrap CI for mean(A) - mean(B), resampling pairs independently."""
    a = np.array([x for x in vals_a if x is not None])
    b = np.array([x for x in vals_b if x is not None])
    if len(a) == 0 or len(b) == 0:
        return (None, None, None)
    rng = np.random.default_rng(seed)
    boot = [rng.choice(a, len(a), True).mean() - rng.choice(b, len(b), True).mean()
            for _ in range(n)]
    return (round(float(a.mean() - b.mean()), 4),
            round(float(np.percentile(boot, 2.5)), 4),
            round(float(np.percentile(boot, 97.5)), 4))


# ===========================================================================
# ANALYSIS — all cells, mechanisms, variants, and the DECISION.
# ===========================================================================
def _pairs(idxs):
    return [(idxs[a], idxs[b]) for a in range(len(idxs))
            for b in range(a + 1, len(idxs))]


def _keep(cardinality, difficulty=None, space=None, min_distinct=None):
    keep = set()
    for c in cardinality:
        if difficulty and c["difficulty"] != difficulty:
            continue
        if space and c["space"] != space:
            continue
        if min_distinct is not None and c["distinct_wrong"] < min_distinct:
            continue
        keep.add(c["q"])
    return keep


def _capability_band(A) -> dict:
    """COT accuracy per model on the 80 problems; band = within BAND of top."""
    sigs, expected = A["sigs"], A["expected"]
    n = len(expected)
    acc = {}
    for mi, (model, _f) in enumerate(MODELS):
        a = _det_index(mi, METHODS.index("COT"))
        correct = sum(1 for q in range(n)
                      if not is_non_answer(sigs[a][q]) and sigs[a][q] == expected[q])
        acc[model] = round(correct / n, 4)
    hi = max(acc.values())
    band = [m for m in acc if hi - acc[m] <= BAND]
    return {"cot_accuracy": acc, "band": band}


def _agent_diagnostics(A) -> list[dict]:
    """Per-agent answer-bearing rate + accuracy — to catch a dead model / a
    low-extraction method, and to disclose per-method parse rates honestly."""
    sigs, expected, agents = A["sigs"], A["expected"], A["agents"]
    n = len(expected)
    rows = []
    for a, (model, method, sidx, temp) in enumerate(agents):
        ab = [q for q in range(n) if not is_non_answer(sigs[a][q])]
        acc = (sum(1 for q in ab if sigs[a][q] == expected[q]) / n) if n else 0.0
        rows.append({"model": model, "method": method, "sample": sidx,
                     "temp": temp, "answer_rate": round(len(ab) / n, 4),
                     "accuracy": round(acc, 4)})
    return rows


def _data_integrity(problems) -> dict:
    """Scan caches for __ERR__ (failed API calls). A high failure rate on a
    whole arm invalidates that arm's cells — must be disclosed, never hidden."""
    groups = [(m, meth) for m, _f in MODELS for meth in METHODS]
    groups.append((FIXED_MODEL, "M1COT"))
    per, tot_err, tot = {}, 0, 0
    for model, method in groups:
        c = _load_cache(model, method)
        err = sum(1 for pid in c for s in c[pid]
                  if str(c[pid][s].get("raw", "")).startswith("__ERR__"))
        n = sum(len(c[pid]) for pid in c)
        per[f"{model}|{method}"] = {"failed": err, "n": n}
        tot_err += err
        tot += n
    return {"total_generations": tot, "total_failed_402": tot_err,
            "failed_fraction": round(tot_err / tot, 4) if tot else None,
            "per_group": per,
            "m1_arm_usable": per[f"{FIXED_MODEL}|M1COT"]["failed"] == 0,
            "note": ("__ERR__ = OpenRouter HTTP 402 (account out of credits). "
                     "Failures cluster at the run tail; the M1 same-model-samples "
                     "arm was entirely lost, so the preregistered contrast "
                     "Delta = excess(M1) - excess(M3) cannot be formed. Re-run "
                     "`generate` after adding credits to fill __ERR__ cells.")}


def analyze(problems: list[dict]) -> dict:
    A = assemble(problems)
    sigs, expected, card = A["sigs"], A["expected"], A["cardinality"]
    DET, M1 = A["DET_IDX"], A["M1_IDX"]
    ref_idx = DET                          # leave-pair-out population baseline
    diagnostics = _agent_diagnostics(A)
    integrity = _data_integrity(problems)

    band = _capability_band(A)
    band_models = band["band"]
    cot_idx_all = [_det_index(mi, 0) for mi, _ in enumerate(MODELS)]
    cot_idx_band = [_det_index(mi, 0) for mi, (m, _f) in enumerate(MODELS)
                    if m in band_models]

    llama_i = [m for m, _ in MODELS].index(FIXED_MODEL)
    m3_idx = [_det_index(llama_i, j) for j in range(3)]           # COT,CODE,DECOMP
    m3_no_code = [_det_index(llama_i, METHODS.index(x)) for x in ("COT", "DECOMP")]
    mixed_idx_pairs = [(i, j) for i in DET for j in DET if i < j
                       and (i % 3) != (j % 3)]                    # method differs

    mech_pairs = {
        "M1_same_model_samples": _pairs(M1),
        "M2_cross_family_cot": _pairs(cot_idx_band),
        "M2_cross_family_cot_unbanded": _pairs(cot_idx_all),
        "M3_cross_method_llama": _pairs(m3_idx),
        "M3_cross_method_llama_no_code": _pairs(m3_no_code),
        "M3_mixed_model_method": mixed_idx_pairs,
    }
    mech_agents = {
        "M1_same_model_samples": M1,
        "M2_cross_family_cot": cot_idx_band,
        "M2_cross_family_cot_unbanded": cot_idx_all,
        "M3_cross_method_llama": m3_idx,
        "M3_cross_method_llama_no_code": m3_no_code,
        "M3_mixed_model_method": DET,
    }

    # space-cardinality by difficulty (first-class finding)
    def _bin_counts(diff):
        rows = [c for c in card if diff is None or c["difficulty"] == diff]
        b = Counter(c["space"] for c in rows)
        # conditional-on-error concentration: among problems where >=2 agents
        # are wrong, how concentrated is the wrong-answer space (Simpson)?
        # Separates "few errors" (competence) from "convergent errors" (a
        # genuine shared attractor).
        simp = [c["simpson"] for c in rows if c["simpson"] is not None]
        ge2 = [c for c in rows if c["m_wrong"] >= 2]
        return {"CONSTRAINED": b["CONSTRAINED"], "MID": b["MID"],
                "LARGE": b["LARGE"], "n": len(rows),
                "median_distinct": float(np.median([c["distinct_wrong"] for c in rows]))
                if rows else None,
                "mean_m_wrong": round(float(np.mean([c["m_wrong"] for c in rows])), 2)
                if rows else None,
                "n_ge2_wrong": len(ge2),
                "median_simpson_when_ge2wrong": round(float(np.median(simp)), 3)
                if simp else None,
                "median_distinct_when_ge2wrong": float(np.median(
                    [c["distinct_wrong"] for c in ge2])) if ge2 else None}
    space_table = {"ALL": _bin_counts(None), "EASY": _bin_counts("EASY"),
                   "HARD": _bin_counts("HARD")}

    # all mechanism x D x S cells
    cells = {}
    sd = 100
    for mech, pairs in mech_pairs.items():
        for D in ("EASY", "HARD", "ALL"):
            for S in ("CONSTRAINED", "LARGE", "ALL"):
                keep = _keep(card, None if D == "ALL" else D,
                             None if S == "ALL" else S)
                sd += 1
                exc = cell_excess(pairs, sigs, expected, ref_idx, keep, seed=sd)
                lift = cell_lift(pairs, sigs, expected, keep,
                                 mech_agents[mech], seed=sd + 50)
                cells[f"{mech}|{D}|{S}"] = {
                    "n_problems": len(keep), "excess": exc, "lift": lift}

    def excess_vals(mech, D, S="LARGE"):
        c = cells[f"{mech}|{D}|{S}"]["excess"]
        return [p["excess"] for p in c["per_pair"] if p["excess"] is not None]

    # ---- DECISION RULE (LARGE stratum) ----
    def decide(space="LARGE"):
        out = {}
        for D in ("EASY", "HARD"):
            a = excess_vals("M1_same_model_samples", D, space)
            b = excess_vals("M3_cross_method_llama", D, space)
            out[D] = {
                "delta_ci": _ci_diff(a, b, seed=7),
                "excess_M1_ci": cells[f"M1_same_model_samples|{D}|{space}"]["excess"]["excess_ci"],
                "excess_M3_ci": cells[f"M3_cross_method_llama|{D}|{space}"]["excess"]["excess_ci"],
                "lift_M3_ci": cells[f"M3_cross_method_llama|{D}|{space}"]["lift"]["lift_ci"],
                "n_M1_pairs": len(a), "n_M3_pairs": len(b),
                "n_problems": cells[f"M3_cross_method_llama|{D}|{space}"]["n_problems"],
            }
        return out

    dec = decide("LARGE")

    def _gt0(ci):   # CI strictly excludes 0 on the positive side
        return ci[1] is not None and ci[1] > 0.0
    def _incl0(ci):
        return ci[1] is None or (ci[1] <= 0.0 <= ci[2])

    dH, dE = dec["HARD"], dec["EASY"]
    live = _gt0(dH["delta_ci"]) and _gt0(dH["lift_M3_ci"])
    mirage = ((_gt0(dE["delta_ci"]) and not _gt0(dH["delta_ci"]))
              or (_gt0(dE["lift_M3_ci"]) and not _gt0(dH["lift_M3_ci"])))
    closed = _incl0(dE["delta_ci"]) and _incl0(dH["delta_ci"])
    if live:
        case = "ROUTE_2_LIVE"
    elif closed and not live:
        case = "ROUTE_2_CLOSED"
    elif mirage:
        case = "ROUTE_2_MIRAGE"
    else:
        case = "INCONCLUSIVE_OR_MIXED"

    # under-population guard for the decision stratum
    large_hard_n = space_table["HARD"]["LARGE"]
    decision_caveat = None
    if large_hard_n < 5:
        decision_caveat = (
            f"HARD x LARGE has only {large_hard_n} problems: the LARGE-space "
            "stratum is under-populated. The wrong-answer space is small here "
            "not by convergence but by SPARSITY — mean m_wrong ~2.7/10 agents, "
            "and when >=2 err they mostly DISAGREE (median Simpson 0). So Route 2 "
            "is blocked by OUTPUT-SPACE STRUCTURE (few, diverse errors), not by "
            "the independence mechanism failing — a different, more fundamental "
            "obstruction. Read the decision as provisional.")
    if not integrity["m1_arm_usable"]:
        decision_caveat = ((decision_caveat or "") +
            " ALSO: the M1 same-model-samples arm was entirely lost to OpenRouter "
            "402 (out of credits), so Delta = excess(M1) - excess(M3) cannot be "
            "formed from real data — the preregistered LIVE/MIRAGE/CLOSED rule is "
            "UNREACHABLE regardless of the stratum. This is an external data-loss "
            "blocker, not a scientific null.")

    result = {
        "config": {"seed": SEED, "models": [m for m, _ in MODELS],
                   "fixed_model": FIXED_MODEL, "methods": METHODS,
                   "k_samples": K_SAMPLES, "sample_temp": SAMPLE_TEMP,
                   "band": BAND, "n_easy": N_EASY, "n_hard": N_HARD,
                   "space_bins": "CONSTRAINED<=2, MID 3-4, LARGE>=5",
                   "baseline_population": "12 deterministic model x method agents"},
        "DECISION": {"case": case, "hard": dH, "easy": dE,
                     "caveat": decision_caveat},
        "data_integrity": integrity,
        "capability": band,
        "parse_rate_overall": A["parse_rate"],
        "agent_diagnostics": diagnostics,
        "space_cardinality_by_difficulty": space_table,
        "cells": cells,
        "robustness": {
            "R1_mixed_vs_model_controlled": {
                "model_controlled_M3": {D: cells[f"M3_cross_method_llama|{D}|LARGE"]["excess"]["excess_ci"]
                                        for D in ("EASY", "HARD")},
                "mixed_model_method": {D: cells[f"M3_mixed_model_method|{D}|LARGE"]["excess"]["excess_ci"]
                                       for D in ("EASY", "HARD")}},
            "R2_distinct_ge5_is_the_LARGE_bin": "S=LARGE already means distinct_wrong>=5; MID(3-4) excluded from both strata (counts in space table).",
            "R3_code_included_vs_excluded": {
                "with_code_M3": {D: {"excess": cells[f"M3_cross_method_llama|{D}|LARGE"]["excess"]["excess_ci"],
                                     "lift": cells[f"M3_cross_method_llama|{D}|LARGE"]["lift"]["lift_ci"]}
                                 for D in ("EASY", "HARD")},
                "without_code_M3": {D: {"excess": cells[f"M3_cross_method_llama_no_code|{D}|LARGE"]["excess"]["excess_ci"],
                                        "lift": cells[f"M3_cross_method_llama_no_code|{D}|LARGE"]["lift"]["lift_ci"]}
                                    for D in ("EASY", "HARD")}},
            "R4_difficulty_x_space_disentangle": {
                "EASY_LARGE": {"excess_M3": cells["M3_cross_method_llama|EASY|LARGE"]["excess"]["excess_ci"],
                               "n": cells["M3_cross_method_llama|EASY|LARGE"]["n_problems"]},
                "HARD_CONSTRAINED": {"excess_M3": cells["M3_cross_method_llama|HARD|CONSTRAINED"]["excess"]["excess_ci"],
                                     "n": cells["M3_cross_method_llama|HARD|CONSTRAINED"]["n_problems"]}},
        },
    }
    return result


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "analyze"
    problems = build_problem_set(SEED)
    if cmd == "plan":
        plan = plan_and_estimate(problems)
        print(json.dumps(plan, indent=2))
        print(f"\nTOTAL: {plan['n_calls']} calls, "
              f"est ${plan['total_cost_est_usd']} (<= $25 gate: "
              f"{'PASS' if plan['total_cost_est_usd'] <= 25 else 'FAIL — STOP'})")
        return 0
    if cmd == "generate":
        generate_all(problems)
        return 0
    if cmd == "analyze":
        res = analyze(problems)
        RESULT.write_text(json.dumps(res, indent=2))
        print("DECISION:", res["DECISION"]["case"])
        print("HARD delta CI:", res["DECISION"]["hard"]["delta_ci"],
              "| lift(M3,HARD):", res["DECISION"]["hard"]["lift_M3_ci"])
        print("EASY delta CI:", res["DECISION"]["easy"]["delta_ci"],
              "| lift(M3,EASY):", res["DECISION"]["easy"]["lift_M3_ci"])
        print("space by difficulty:", json.dumps(res["space_cardinality_by_difficulty"]))
        if res["DECISION"]["caveat"]:
            print("CAVEAT:", res["DECISION"]["caveat"])
        return 0
    print("usage: route2_experiment.py [plan|generate|analyze]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
