"""
R11 — the router: prompts, elicitation, and metrics.

GATE 0d is enforced here, not by convention: `MAX_TOKENS = 50`, temperature 0,
and the prompt forbids chain-of-thought. If predicting solvability costs as
many tokens as solving, there is no economy even at perfect accuracy.

The prompt builders take ONLY a problem statement (and, for CROSS, a model-id
string). There is no parameter through which a solution, a cached answer, or a
ground truth could enter — that is the circularity pin, tested in
`test_router.py`.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data import CF  # noqa: E402

MAX_TOKENS = 50          # GATE 0d — hard cap
TEMPERATURE = 0
BASE = "https://openrouter.ai/api/v1"
CACHE = Path(__file__).resolve().parent / "r11_cache"


# ======================================================================
# The four frozen prompt templates (PREREGISTRATION_R11.md §3)
# ======================================================================

SELF_MATH = """You will be shown a math problem. Do NOT solve it. Do NOT explain. Do NOT show any working.
Estimate the probability, as an integer from 0 to 100, that YOU would produce the correct
final answer if you attempted this problem.
Output ONLY the integer. No words, no reasoning, no working.

Problem: {problem}

Integer 0-100:"""

SELF_MBPP = """You will be shown a Python programming task. Do NOT solve it. Do NOT explain. Do NOT show any working.
Estimate the probability, as an integer from 0 to 100, that YOU would write a correct
Python function passing the hidden tests if you attempted this task.
Output ONLY the integer. No words, no reasoning, no working.

Task: {problem}

Integer 0-100:"""

CROSS_MATH = """You will be shown a math problem. Do NOT solve it. Do NOT explain. Do NOT show any working.
Estimate the probability, as an integer from 0 to 100, that the AI language model "{claimant}"
would produce the correct final answer if it attempted this problem.
Output ONLY the integer. No words, no reasoning, no working.

Problem: {problem}

Integer 0-100:"""

CROSS_MBPP = """You will be shown a Python programming task. Do NOT solve it. Do NOT explain. Do NOT show any working.
Estimate the probability, as an integer from 0 to 100, that the AI language model "{claimant}"
would write a correct Python function passing the hidden tests if it attempted this task.
Output ONLY the integer. No words, no reasoning, no working.

Task: {problem}

Integer 0-100:"""


def build_prompt(problem: str, *, task: str, claimant: str | None = None) -> str:
    """
    Render one prediction prompt.

    Takes ONLY the problem statement and (for CROSS) a model-id string. There is
    deliberately no parameter for a solution, an answer, or a ground truth.
    """
    if task not in ("math", "mbpp"):
        raise ValueError(task)
    if claimant is None:
        tpl = SELF_MATH if task == "math" else SELF_MBPP
        return tpl.format(problem=problem)
    tpl = CROSS_MATH if task == "math" else CROSS_MBPP
    return tpl.format(problem=problem, claimant=claimant)


# ======================================================================
# Parsing — unparseable predictions are EXCLUDED, never imputed
# ======================================================================

def parse_confidence(text: str) -> int | None:
    """First integer 0-100 in the completion; None if absent or out of range."""
    if not text:
        return None
    m = re.search(r"\d{1,3}", text)
    if not m:
        return None
    v = int(m.group())
    return v if 0 <= v <= 100 else None


# ======================================================================
# Elicitation
# ======================================================================

def _key() -> str:
    return [l for l in (CF / ".env").read_text().splitlines()
            if l.startswith("OPENROUTER")][0].split("=", 1)[1].strip()


class Elicitor:
    """Cached, rate-limit-tolerant prediction calls. Never exceeds MAX_TOKENS."""

    def __init__(self, model: str, *, max_tokens: int = MAX_TOKENS):
        if max_tokens > MAX_TOKENS:
            raise ValueError(f"GATE 0d: max_tokens {max_tokens} > {MAX_TOKENS}")
        self.model = model
        self.max_tokens = max_tokens
        self._key = _key()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def _post(self, prompt: str) -> tuple[str, int, int]:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE,
            "max_tokens": self.max_tokens,
        }).encode()
        for attempt in range(6):
            req = urllib.request.Request(
                BASE + "/chat/completions", data=body, method="POST",
                headers={"Authorization": f"Bearer {self._key}",
                         "Content-Type": "application/json",
                         "User-Agent": "gyza-research/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    d = json.loads(r.read())
                u = d.get("usage") or {}
                return (d["choices"][0]["message"]["content"],
                        int(u.get("prompt_tokens", 0)),
                        int(u.get("completion_tokens", 0)))
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 5:
                    time.sleep(2 ** attempt)
                    continue
                return (f"__ERR__:HTTP{e.code}", 0, 0)
            except Exception as e:  # noqa: BLE001
                if attempt < 5:
                    time.sleep(2 ** attempt)
                    continue
                return (f"__ERR__:{type(e).__name__}", 0, 0)
        return ("__ERR__:RETRIES", 0, 0)

    def run(self, prompts: list[str], tag: str) -> list[dict]:
        """Elicit for a list of prompts, caching the whole list under `tag`."""
        CACHE.mkdir(exist_ok=True)
        f = CACHE / f"{tag}.json"
        if f.exists():
            out = json.loads(f.read_text())
            self.prompt_tokens += sum(r.get("ptok", 0) for r in out)
            self.completion_tokens += sum(r.get("ctok", 0) for r in out)
            return out
        out = []
        for p in prompts:
            txt, pt, ct = self._post(p)
            self.calls += 1
            self.prompt_tokens += pt
            self.completion_tokens += ct
            out.append({"raw": txt, "conf": parse_confidence(txt),
                        "ptok": pt, "ctok": ct})
        f.write_text(json.dumps(out))
        return out


# ======================================================================
# Metrics
# ======================================================================

def auroc(scores: list[float], labels: list[bool]) -> float | None:
    """
    Mann-Whitney AUROC with tie correction. Higher score => more likely True.
    None if either class is empty (undefined, never imputed).
    """
    pairs = [(s, y) for s, y in zip(scores, labels) if s is not None]
    pos = [s for s, y in pairs if y]
    neg = [s for s, y in pairs if not y]
    if not pos or not neg:
        return None
    # rank-based, average ranks for ties
    allv = sorted(s for s, _ in pairs)
    rank: dict[float, float] = {}
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1] == allv[i]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        rank[allv[i]] = r
        i = j + 1
    rsum = sum(rank[s] for s in pos)
    n1, n2 = len(pos), len(neg)
    return (rsum - n1 * (n1 + 1) / 2.0) / (n1 * n2)


def sweep(scores: list[float], labels: list[bool]) -> list[dict]:
    """
    Threshold sweep. Route CHEAP iff score >= t; else escalate.

    recall  = P(escalated | actually failed)   -- catching the leaks
    escal   = P(escalated)
    economy = 1 - escal                        -- what still takes the cheap path
    """
    pairs = [(s, y) for s, y in zip(scores, labels) if s is not None]
    if not pairs:
        return []
    n = len(pairs)
    nfail = sum(1 for _, y in pairs if not y)
    out = []
    # thresholds just above each observed score, plus one below everything
    cands = sorted({s for s, _ in pairs})
    for t in [min(cands) - 1] + [c + 1e-12 for c in cands]:
        esc = [(s, y) for s, y in pairs if s < t]
        rec = (sum(1 for _, y in esc if not y) / nfail) if nfail else None
        out.append({"t": t, "recall": rec, "escalation": len(esc) / n,
                    "economy": 1 - len(esc) / n})
    return out


def economy_at_recall(curve: list[dict], target: float) -> dict | None:
    """Best (max) economy among points meeting recall >= target."""
    ok = [p for p in curve if p["recall"] is not None and p["recall"] >= target]
    if not ok:
        return None
    return max(ok, key=lambda p: p["economy"])


def paired_delta_ci(scores_a: list[float], scores_b: list[float],
                    labels: list[bool], *, n_boot: int = 10000,
                    seed: int = 11) -> dict:
    """
    Bootstrap the PAIRED difference AUROC(a) - AUROC(b) over problems.

    Both AUROCs are recomputed on each resample so the pairing is preserved.
    """
    import numpy as np

    idx_all = [i for i in range(len(labels))
               if scores_a[i] is not None and scores_b[i] is not None]
    a = [scores_a[i] for i in idx_all]
    b = [scores_b[i] for i in idx_all]
    y = [labels[i] for i in idx_all]
    A, B = auroc(a, y), auroc(b, y)
    if A is None or B is None:
        return {"auroc_self": A, "auroc_null": B, "delta": None,
                "ci": None, "n": len(idx_all)}
    rng = np.random.default_rng(seed)
    boots = []
    m = len(idx_all)
    for _ in range(n_boot):
        r = rng.integers(0, m, m)
        ya = [y[i] for i in r]
        if all(ya) or not any(ya):
            continue
        da = auroc([a[i] for i in r], ya)
        db = auroc([b[i] for i in r], ya)
        if da is not None and db is not None:
            boots.append(da - db)
    lo, hi = (float(np.percentile(boots, 2.5)),
              float(np.percentile(boots, 97.5))) if boots else (None, None)
    return {"auroc_self": round(A, 4), "auroc_null": round(B, 4),
            "delta": round(A - B, 4),
            "ci": [round(lo, 4), round(hi, 4)] if boots else None,
            "n": len(idx_all), "n_boot_used": len(boots)}


def rank_average(a: list[float], b: list[float]) -> list[float]:
    """Combined predictor: mean of the two within-sample percentile ranks."""
    def ranks(v):
        ok = [x for x in v if x is not None]
        if not ok:
            return [None] * len(v)
        srt = sorted(ok)
        return [None if x is None else srt.index(x) / max(1, len(srt) - 1)
                for x in v]
    ra, rb = ranks(a), ranks(b)
    return [None if (x is None or y is None) else (x + y) / 2
            for x, y in zip(ra, rb)]


def is_degenerate(confs: list[int | None]) -> bool:
    """>=90% of parsed predictions taking <=2 distinct values (prereg §4.5)."""
    ok = [c for c in confs if c is not None]
    if not ok:
        return True
    from collections import Counter
    top2 = sum(v for _, v in Counter(ok).most_common(2))
    return top2 / len(ok) >= 0.90
