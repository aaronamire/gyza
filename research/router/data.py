"""
R11 data layer — READ-ONLY imports of prior routes' caches.

Nothing in this module writes to, or mutates, any prior route's directory.
It loads the two cached claim sets and produces corrected correctness
labels per the preregistration:

  * MBPP  — 6 `code_band` models x 50 problems. Correctness is
    ``run_signature == expected_signature``, the decisive run's own
    definition (`codebench.py`). The cache holds run signatures, not
    program text (program text is known absent, R8 GATE 0b) — and is not
    needed.
  * MATH  — 4 models x 80 problems. Correctness is the last ``\\boxed{...}``
    of the cached COT compared to ``ref_raw`` with
    ``canonicalizer_v2.equal`` (Phase 8, hand-validated 27/27). The raw
    pre-Phase-8 labels are ~33% contaminated in the positive class and are
    NOT used. ``equal`` is three-valued; UNRESOLVED items are EXCLUDED,
    never imputed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RESEARCH = Path(__file__).resolve().parent.parent
CF = RESEARCH / "correlated_failure"
R2 = RESEARCH / "route2_independence"
CD = RESEARCH / "consistency_defensibility"

for _p in (CF, R2, CD):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# The 6 capability-banded MBPP models, fixed by the decisive run's
# preregistered band (band=0.10) before this route existed.
MBPP_MODELS = [
    "meta-llama/llama-3.1-70b-instruct",
    "google/gemma-2-27b-it",
    "google/gemma-3-27b-it",
    "mistralai/mistral-small-24b-instruct-2501",
    "mistralai/mistral-small-3.2-24b-instruct",
    "microsoft/phi-4",
]

# The 4 models with cached MATH COT runs.
MATH_MODELS = [
    "google/gemma-2-27b-it",
    "meta-llama/llama-3.1-70b-instruct",
    "microsoft/phi-4",
    "mistralai/mistral-small-3.2-24b-instruct",
]

SEED = 1
N_MBPP = 50
N_MATH = 80


# ----------------------------------------------------------------------
# MBPP
# ----------------------------------------------------------------------

def load_mbpp_items() -> list[dict]:
    """The 50 MBPP problems of the decisive run, same seed/order."""
    from codebench import load_mbpp
    return load_mbpp(n=N_MBPP, seed=SEED)


def mbpp_outcomes() -> tuple[list[dict], dict[str, list[bool]]]:
    """
    Return (items, {model: [correct?] * 50}).

    Correctness reuses the decisive run's own definition verbatim:
    the model's cached run signature must equal the expected signature
    derived from MBPP's own ``test_list``.
    """
    from codebench import expected_signature, extract_calls

    items = load_mbpp_items()
    calls = [extract_calls(p["test_list"]) for p in items]
    expected = [expected_signature(c) for c in calls]

    out: dict[str, list[bool]] = {}
    for mid in MBPP_MODELS:
        f = CF / "or_cache" / f"{mid.replace('/', '__')}_code_s{SEED}.json"
        sigs = json.loads(f.read_text())
        if len(sigs) != len(expected):
            raise RuntimeError(f"{mid}: cached {len(sigs)} != {len(expected)}")
        out[mid] = [sigs[q] == expected[q] for q in range(len(expected))]
    return items, out


# ----------------------------------------------------------------------
# MATH
# ----------------------------------------------------------------------

def load_math_items() -> list[dict]:
    """The 80 preregistered MATH problems: id/subject/level/problem/ref_raw/difficulty."""
    return json.loads((R2 / "problem_set.json").read_text())["problems"]


def math_outcomes() -> tuple[list[dict], dict[str, list], dict[str, list[str]]]:
    """
    Return (items, {model: [True|False|None] * 80}, {model: [raw_cot]}).

    ``None`` is UNRESOLVED (canonicalizer could not decide) and is EXCLUDED
    downstream, never imputed.
    """
    import canonicalizer_v2
    from route2_experiment import extract_boxed

    items = load_math_items()
    labels: dict[str, list] = {}
    raws: dict[str, list[str]] = {}
    for mid in MATH_MODELS:
        f = R2 / "route2_cache" / f"{mid.replace('/', '_')}__COT__s{SEED}.json"
        cache = json.loads(f.read_text())
        lab, rw = [], []
        for it in items:
            entry = cache.get(it["id"])
            raw = "" if entry is None else entry.get("0", {}).get("raw", "")
            rw.append(raw)
            got = extract_boxed(raw)
            # Amendment 1. NO-ANSWER (no \boxed at all) is a FAILURE, not an
            # undecidable: the model produced no final answer, mostly because
            # its chain ran past the cached run's generation cap. Only genuine
            # canonicalizer undecidability (both strings non-empty) is None and
            # excluded. Folding these together selects the positive class and
            # produced an exact 1.000 base rate at GATE 0b.
            if not got:
                lab.append(False)
            else:
                lab.append(canonicalizer_v2.equal(got, it["ref_raw"]))
        labels[mid] = lab
        raws[mid] = rw
    return items, labels, raws


# ----------------------------------------------------------------------
# The population-difficulty null — leave-M-out
# ----------------------------------------------------------------------

def pop_difficulty(outcomes: dict[str, list], q: int, model: str) -> float | None:
    """
    Fraction of the OTHER models that solved problem ``q``.

    Uses ZERO self-knowledge: it knows only what is hard in general. This is
    the conditional-independence null applied to self-knowledge.
    ``model``'s own outcome is excluded by construction. Items the other
    models left UNRESOLVED are dropped from the fraction; ``None`` is
    returned if no other model has a resolved outcome.
    """
    vals = [v for m, outs in outcomes.items() if m != model
            for v in (outs[q],) if v is not None]
    if not vals:
        return None
    return sum(1 for v in vals if v) / len(vals)
