"""
rho_measure — the instrument for the Stage 7 measurement (reframed to
lead the project): how correlated are the *errors* of real model
collectives, within vs. across families?

This file is deliberately backend-agnostic and validated against ground
truth BEFORE any real model is touched. A ``ModelBackend`` produces, for
each multiple-choice question, a predicted answer index. The instrument
turns that into a per-model binary error vector, then measures pairwise
error correlation (the phi coefficient — Pearson on the binary error
indicators), aggregated within-family vs. cross-family, plus the
shared-wrong-answer rate (the sharp, categorical form of a shared blind
spot).

CORRECTNESS ANCHOR (Stage-2 discipline, applied here)
-----------------------------------------------------
``SyntheticBackend`` draws errors from a latent-common-factor model with
a KNOWN correlation ρ. The tests assert the instrument RECOVERS the
ordering and the null: measured error-correlation is ≈ 0 at ρ=0 (the
independent case) and increases monotonically with ρ. If the instrument
cannot recover a correlation it was handed, no real-model number it
produces can be trusted. Everything is deterministic from (seed, config)
— explicit numpy Generators, no global RNG, no wall-clock.

The strong form of H1 (aggregate worse than a single agent) is NOT
assumed anywhere here; this instrument only measures ρ̂. The reversal-of-
advantage claim and the constructive mechanism live in later stages.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


# ======================================================================
# Data + backend protocol
# ======================================================================

@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    choices: tuple[str, ...]
    answer_idx: int


class ModelBackend(Protocol):
    name: str
    family: str

    def predict(self, questions: list[Question]) -> np.ndarray:
        """Return an int array of predicted choice indices, one per question."""
        ...


# ======================================================================
# Synthetic backend — the ground-truth harness for validating the math
# ======================================================================

class SyntheticBackend:
    """
    A synthetic model whose error process is a latent-common-factor model
    with a shared bias term ``S`` (per question, shared across all models
    in the same 'world') and independent noise. Correlation is injected
    through ``rho`` and the shared draws; competence sets the base error
    rate. Used only to validate that the instrument recovers a known ρ.
    """

    def __init__(self, name: str, family: str, *, competence: float,
                 rho: float, wrong_bias_idx: int = 1):
        self.name = name
        self.family = family
        self.competence = competence
        self.rho = rho
        self._wrong_bias_idx = wrong_bias_idx

    def predict_with_shared(
        self, questions: list[Question], shared: np.ndarray,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """
        ``shared[q]`` is the per-question latent common factor (same array
        handed to every model that shares this world), so correlation is
        real, not per-model. error_latent = sqrt(rho)*shared +
        sqrt(1-rho)*eps; an error occurs when the latent exceeds a
        competence-set threshold. On an error the model returns a specific
        wrong index (a shared blind spot) so the categorical
        shared-wrong-answer signal is well-defined.
        """
        n = len(questions)
        eps = rng.standard_normal(n)
        latent = np.sqrt(self.rho) * shared + np.sqrt(1.0 - self.rho) * eps
        thresh = _competence_threshold(self.competence)
        err = latent > thresh
        preds = np.array([q.answer_idx for q in questions])
        for i, q in enumerate(questions):
            if err[i]:
                wrong = self._wrong_bias_idx % len(q.choices)
                if wrong == q.answer_idx:
                    wrong = (wrong + 1) % len(q.choices)
                preds[i] = wrong
        return preds

    def predict(self, questions: list[Question]) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError("use a SyntheticWorld to share the latent factor")


def _competence_threshold(competence: float) -> float:
    """Threshold t s.t. P(N(0,1) > t) = 1 - competence (the error rate)."""
    from scipy.stats import norm
    return float(norm.ppf(competence))


@dataclass
class SyntheticWorld:
    """Runs a set of SyntheticBackends against one shared latent factor so
    their errors carry the intended correlation structure."""
    seed: int

    def run(self, models: list[SyntheticBackend],
            questions: list[Question]) -> np.ndarray:
        rng = np.random.default_rng(self.seed)
        shared = rng.standard_normal(len(questions))
        preds = np.vstack([
            m.predict_with_shared(
                questions, shared, np.random.default_rng(self.seed + 1000 + i))
            for i, m in enumerate(models)
        ])
        return preds


# ======================================================================
# The measurement
# ======================================================================

def error_matrix(preds: np.ndarray, questions: list[Question]) -> np.ndarray:
    """Binary error indicators E[m, q] = 1 iff model m got question q wrong."""
    answers = np.array([q.answer_idx for q in questions])
    return (preds != answers[None, :]).astype(np.int8)


def error_correlation(E: np.ndarray) -> np.ndarray:
    """
    Pairwise phi coefficient (Pearson correlation of the binary error
    vectors). A model with zero error variance (never wrong / always
    wrong) has undefined correlation → reported as NaN for that pair.
    """
    m = E.shape[0]
    C = np.full((m, m), np.nan)
    for i in range(m):
        for j in range(m):
            a, b = E[i].astype(float), E[j].astype(float)
            if a.std() == 0 or b.std() == 0:
                C[i, j] = np.nan if i != j else 1.0
                continue
            C[i, j] = float(np.corrcoef(a, b)[0, 1])
    return C


@dataclass
class RhoResult:
    families: list[str]
    corr: np.ndarray                 # pairwise phi
    mean_within: float
    mean_cross: float
    shared_wrong_rate: float
    per_model_error_rate: list[float]

    def to_dict(self) -> dict:
        return {
            "families": self.families,
            "mean_within_family_rho": None if np.isnan(self.mean_within) else round(self.mean_within, 4),
            "mean_cross_family_rho": None if np.isnan(self.mean_cross) else round(self.mean_cross, 4),
            "shared_wrong_rate": round(self.shared_wrong_rate, 4),
            "per_model_error_rate": [round(x, 4) for x in self.per_model_error_rate],
        }


def within_cross(corr: np.ndarray, families: list[str]) -> tuple[float, float]:
    """Mean pairwise phi within the same family vs. across families
    (upper triangle only, NaNs ignored)."""
    within, cross = [], []
    m = len(families)
    for i in range(m):
        for j in range(i + 1, m):
            c = corr[i, j]
            if np.isnan(c):
                continue
            (within if families[i] == families[j] else cross).append(c)
    return (float(np.mean(within)) if within else float("nan"),
            float(np.mean(cross)) if cross else float("nan"))


def shared_wrong_rate(preds: np.ndarray, questions: list[Question]) -> float:
    """
    Fraction of questions on which a *majority of the models that erred*
    converged on the SAME wrong answer — the categorical shared-blind-spot
    signal that most directly threatens trimming rules.
    """
    answers = np.array([q.answer_idx for q in questions])
    n = len(questions)
    hits = 0
    for q in range(n):
        col = preds[:, q]
        wrong = col[col != answers[q]]
        if wrong.size == 0:
            continue
        vals, counts = np.unique(wrong, return_counts=True)
        # a shared blind spot: >half of the erring models agree on one wrong answer
        if counts.max() > wrong.size / 2 and counts.max() >= 2:
            hits += 1
    return hits / n if n else 0.0


def measure(preds: np.ndarray, families: list[str],
            questions: list[Question]) -> RhoResult:
    E = error_matrix(preds, questions)
    corr = error_correlation(E)
    mw, mc = within_cross(corr, families)
    return RhoResult(
        families=families,
        corr=corr,
        mean_within=mw,
        mean_cross=mc,
        shared_wrong_rate=shared_wrong_rate(preds, questions),
        per_model_error_rate=[float(E[i].mean()) for i in range(E.shape[0])],
    )


# ======================================================================
# Sharpened metrics (per Stage-0 review — the four confounds)
# ======================================================================
#
# (1) Co-failure is not correlation. We measure the SAME SPECIFIC WRONG
#     ANSWER, above what independence predicts — the Knight-Leveson move.
# (2) Distractor attractiveness confounds raw agreement. The null below
#     accounts for per-question option base rates (a leave-pair-out pool
#     attractiveness profile), so a merely-seductive distractor produces
#     ZERO excess.
# (3) Difficulty selection biases both ways. `difficulty_filter` keeps
#     intermediate-difficulty items with real outcome variance.
# (4) Capability confounds family. `within_cross` on the EXCESS matrix is
#     confound-robust to attractiveness; capability must still be matched
#     at the experiment-design level (see run configs / notes).


def difficulty_filter(preds: np.ndarray, questions: list[Question],
                      lo: float = 0.2, hi: float = 0.8,
                      reference: "np.ndarray | None" = None) -> list[int]:
    """
    Indices of questions whose pool accuracy is in [lo, hi] — items with
    real outcome variance (not all-pass, not all-fail).

    ⚠ SELECTION ARTIFACT: estimate difficulty from a pool DIFFERENT from
    the models you then correlate. Filtering on the SAME small pool
    conditions on "the models disagreed", which mechanically induces
    negative error correlation (observed in the 3-model pilot: cross-φ
    went +0.33 → −0.48 purely from this). Pass ``reference`` (a held-out
    pool's predictions) to estimate difficulty independently, or use a
    large pool so difficulty and any given pair's agreement decouple.
    """
    ref = preds if reference is None else reference
    answers = np.array([q.answer_idx for q in questions])
    acc = (ref == answers[None, :]).mean(axis=0)
    return [q for q in range(len(questions)) if lo <= acc[q] <= hi]


def same_wrong_excess(preds: np.ndarray,
                      questions: list[Question]) -> np.ndarray:
    """
    Pairwise EXCESS same-specific-wrong-answer rate over a base-rate null.

    Observed(i,j) = fraction of questions where i and j are BOTH wrong and
    picked the SAME wrong option. Null(i,j) = expected collision if both
    drew their option independently from the per-question pool
    distribution estimated from the OTHER models (leave-pair-out), so a
    question-level attractive distractor contributes equally to observed
    and null and cancels. Excess = Observed - Null: correlation in the
    *specific wrong answer* beyond distractor attractiveness.

    Needs a non-trivial pool to estimate attractiveness (leave-pair-out
    leaves m-2 models); underpowered for m<=3. NaN on the diagonal.
    """
    answers = np.array([q.answer_idx for q in questions])
    m, n = preds.shape
    E = np.full((m, m), np.nan)
    for i in range(m):
        for j in range(i + 1, m):
            others = [k for k in range(m) if k != i and k != j]
            s_obs = 0.0
            e_null = 0.0
            for q in range(n):
                ans = answers[q]
                if (preds[i, q] != ans and preds[j, q] != ans
                        and preds[i, q] == preds[j, q]):
                    s_obs += 1.0
                if others:
                    counts: dict[int, int] = {}
                    for k in others:
                        counts[int(preds[k, q])] = counts.get(int(preds[k, q]), 0) + 1
                    tot = len(others)
                    e_null += sum((c / tot) ** 2
                                  for o, c in counts.items() if o != ans)
            E[i, j] = E[j, i] = (s_obs - e_null) / n
    return E


# ======================================================================
# Free-form / verifiable-ground-truth measurement (recovers ABSOLUTE
# correlation — makes the universal blind spot visible)
# ======================================================================
#
# The identifiability trap in `same_wrong_excess` is an artifact of the
# multiple-choice FORMAT, not the phenomenon: with k options there is no
# reference class, so a blind spot shared by the whole pool is
# indistinguishable from an attractive distractor. Switch to free-form
# answers with a huge space (a specific number, a program's output) and
# chance collision → 0, so two models producing the SAME specific wrong
# answer is a strong, ABSOLUTE signal. This is the regime that matters
# most for Gyza: a UNIVERSAL blind spot that no pool diversity can fix and
# that the within−cross statistic reads as zero.


def same_wrong_convergence(preds: np.ndarray, answers: np.ndarray, *,
                           n_perms: int = 20, seed: int = 0,
                           invalid: "int | None" = None
                           ) -> tuple[np.ndarray, np.ndarray]:
    """
    Pairwise ABSOLUTE same-wrong-answer convergence for free-form answers.

    Obs(i,j) = P(pred_i == pred_j | both wrong) — among questions both got
    wrong, how often did they give the IDENTICAL wrong answer. In a large
    answer space the chance value is ~0, so Obs itself is the signal (no
    attractiveness reference class needed). Null(i,j) is a permutation
    baseline: model j's answers shuffled across questions (preserving its
    marginal + error rate), which destroys question-level alignment — it
    estimates the chance collision empirically. Report Obs and Obs−Null.

    ``invalid`` excludes a 'no answer produced' sentinel: a model that
    failed to emit a parseable answer did not converge on a wrong ANSWER,
    so counting two such failures as agreement is an artifact (it inflated
    within-family convergence to a spurious 1.0 in the tiny-model pilot).
    Questions where either model's answer is ``invalid`` are dropped.
    """
    rng = np.random.default_rng(seed)
    answers = np.asarray(answers)
    m, n = preds.shape
    wrong = preds != answers[None, :]
    ok = np.ones_like(preds, dtype=bool) if invalid is None else (preds != invalid)
    Obs = np.full((m, m), np.nan)
    Null = np.full((m, m), np.nan)
    for i in range(m):
        for j in range(i + 1, m):
            bw = wrong[i] & wrong[j] & ok[i] & ok[j]
            d = int(bw.sum())
            Obs[i, j] = Obs[j, i] = (
                float(((preds[i] == preds[j]) & bw).sum()) / d if d else np.nan)
            vals = []
            for _ in range(n_perms):
                perm = rng.permutation(n)
                pj = preds[j][perm]
                okj = ok[j][perm]
                bwp = wrong[i] & (pj != answers) & ok[i] & okj
                dp = int(bwp.sum())
                if dp:
                    vals.append(float(((preds[i] == pj) & bwp).sum()) / dp)
            Null[i, j] = Null[j, i] = float(np.mean(vals)) if vals else np.nan
    return Obs, Null


def synth_freeform(*, n_models: int, n_questions: int, answer_space: int,
                   competence: float, seductive_gamma: float, universal: bool,
                   seed: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Ground truth for the free-form regime. Errors occur INDEPENDENTLY
    across models (no shared error timing); the question is whether, WHEN
    they err, they converge on the same specific wrong answer.

    ``universal=True``: every model's blind spot points at the SAME
    seductive wrong answer (a shared miscalculation) — the dangerous
    universal case. ``universal=False``: each model has its OWN seductive
    wrong answer (they fail in different directions). ``seductive_gamma``
    is the chance an erring model takes its seductive answer vs. a random
    wrong one from the large space.
    """
    rng = np.random.default_rng(seed)
    answers = rng.integers(0, answer_space, n_questions)
    thresh = _competence_threshold(competence)
    preds = np.empty((n_models, n_questions), dtype=np.int64)
    for mi in range(n_models):
        eps = np.random.default_rng(seed + 100 + mi).standard_normal(n_questions)
        err = eps > thresh                                  # independent error timing
        seductive = ((answers + 1) if universal
                     else (answers + (mi + 2))) % answer_space
        r = np.random.default_rng(seed + 5000 + mi)
        for q in range(n_questions):
            if not err[q]:
                preds[mi, q] = answers[q]
            elif r.random() < seductive_gamma:
                preds[mi, q] = seductive[q]
            else:
                v = int(r.integers(0, answer_space))
                while v == answers[q]:
                    v = int(r.integers(0, answer_space))
                preds[mi, q] = v
    return preds, answers


# ======================================================================
# Synthetic ground truth (MC) for validating the null + a pipeline check
# ======================================================================

def synth_answers(*, n_models: int, n_questions: int, k: int,
                  competence: float, rho: float, attract_gamma: float,
                  seed: int, blind_offset: int = 1,
                  answers: "np.ndarray | None" = None
                  ) -> tuple[np.ndarray, list[Question]]:
    """
    Ground-truth generator. ``rho`` correlates *whether* models err
    (shared latent factor); ``attract_gamma`` is the chance an erring
    model picks THIS pool's blind-spot option, ``(answer+blind_offset)%k``.

    Two things this deliberately makes distinguishable:
    - rho=0 ⇒ errors independent; any same-answer collisions are pure
      attractiveness, which the base-rate null must absorb (excess ~ 0).
    - Different pools with DIFFERENT ``blind_offset`` fail toward different
      wrong answers — the ingredient that makes diversity actually help.
    Note (a real limitation, asserted in tests): a *uniform* blind spot
    shared by the whole pool is observationally identical to an attractive
    distractor; only DIFFERENTIAL correlation (a sub-pool more correlated
    than the rest) is identifiable from same-answer statistics.
    """
    if answers is None:
        answers = np.random.default_rng(seed).integers(0, k, n_questions)
    else:
        answers = np.asarray(answers, dtype=int)
        n_questions = len(answers)
    off = (blind_offset % (k - 1)) + 1               # in [1, k-1] ⇒ attract != answer
    attract = (answers + off) % k
    shared = np.random.default_rng(seed + 1).standard_normal(n_questions)  # error timing
    thresh = _competence_threshold(competence)
    preds = np.empty((n_models, n_questions), dtype=int)
    for mi in range(n_models):
        eps = np.random.default_rng(seed + 100 + mi).standard_normal(n_questions)
        latent = np.sqrt(rho) * shared + np.sqrt(1.0 - rho) * eps
        err = latent > thresh
        r = np.random.default_rng(seed + 5000 + mi)
        for q in range(n_questions):
            if not err[q]:
                preds[mi, q] = answers[q]
            elif r.random() < attract_gamma:
                preds[mi, q] = attract[q]
            else:
                o = r.integers(0, k)
                while o == answers[q]:
                    o = r.integers(0, k)
                preds[mi, q] = o
    questions = [Question(f"q{q}", "", tuple(str(x) for x in range(k)),
                          int(answers[q])) for q in range(n_questions)]
    return preds, questions


def majority_accuracy(preds: np.ndarray, questions: list[Question]) -> float:
    """Plurality-vote accuracy of the ensemble."""
    answers = np.array([q.answer_idx for q in questions])
    correct = 0
    for q in range(preds.shape[1]):
        vals, counts = np.unique(preds[:, q], return_counts=True)
        if vals[np.argmax(counts)] == answers[q]:
            correct += 1
    return correct / preds.shape[1]


def diverse_vs_monoculture(*, ensemble_size: int, n_groups: int,
                           n_questions: int, k: int, competence: float,
                           rho: float, seed: int) -> dict:
    """
    The intervention arm (synthetic). Same ensemble size, same per-model
    competence, same within-group correlation ρ. A MONOCULTURE draws all
    members from one correlated world; a DIVERSE ensemble splits them
    across ``n_groups`` independent worlds (low cross-group correlation).
    Returns majority-vote accuracy of each — the claim is diverse > mono
    at fixed compute.
    """
    # Monoculture: one world, one blind spot. Diverse: independent groups
    # with DIFFERENT blind spots (they fail toward different wrong answers)
    # — decorrelating the blind spot, not merely the error timing.
    answers = np.random.default_rng(seed).integers(0, k, n_questions)  # ONE shared key
    mono, qs = synth_answers(n_models=ensemble_size, n_questions=n_questions,
                             k=k, competence=competence, rho=rho, attract_gamma=0.7,
                             seed=seed, blind_offset=0, answers=answers)
    per = max(1, ensemble_size // n_groups)
    blocks = []
    for g in range(n_groups):
        p, _ = synth_answers(n_models=per, n_questions=n_questions, k=k,
                             competence=competence, rho=rho, attract_gamma=0.7,
                             seed=seed + 900 * (g + 1), blind_offset=g, answers=answers)
        blocks.append(p)
    diverse = np.vstack(blocks)[:ensemble_size]
    return {
        "monoculture_acc": round(majority_accuracy(mono, qs), 4),
        "diverse_acc": round(majority_accuracy(diverse, qs), 4),
        "ensemble_size": ensemble_size, "n_groups": n_groups, "rho": rho,
    }


# ======================================================================
# Real backend — HuggingFace causal LM, CPU, multiple-choice by logprob
# ======================================================================

class HFCausalBackend:
    """
    A real model backend. Scores each choice by the model's average
    per-token log-probability of the choice text given the prompt (one
    forward pass per choice, NO generation), returns the argmax choice.
    Deterministic: no sampling. CPU by default — viable for small models.

    Kept import-light: torch/transformers are imported on construction so
    the instrument and its tests never require them.
    """

    def __init__(self, repo: str, family: str, *, name: str | None = None,
                 device: str = "cpu", dtype: str = "float32"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.name = name or repo.split("/")[-1]
        self.family = family
        self._repo = repo
        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(repo)
        self._model = AutoModelForCausalLM.from_pretrained(
            repo, torch_dtype=getattr(torch, dtype),
        ).to(device).eval()
        self._device = device

    def _choice_logprob(self, prompt: str, choice: str) -> float:
        torch = self._torch
        p_ids = self._tok(prompt, return_tensors="pt").input_ids
        full = prompt + choice
        f_ids = self._tok(full, return_tensors="pt").input_ids.to(self._device)
        with torch.no_grad():
            logits = self._model(f_ids).logits
        logprobs = torch.log_softmax(logits[0, :-1], dim=-1)
        targets = f_ids[0, 1:]
        # only the tokens belonging to the choice continuation
        start = p_ids.shape[1] - 1
        tok_lp = logprobs[torch.arange(len(targets)), targets][start:]
        return float(tok_lp.mean()) if tok_lp.numel() else float("-inf")

    def predict(self, questions: list[Question]) -> np.ndarray:
        preds = np.empty(len(questions), dtype=int)
        for i, q in enumerate(questions):
            scores = [self._choice_logprob(q.prompt + "\nAnswer: ", " " + c)
                      for c in q.choices]
            preds[i] = int(np.argmax(scores))
        return preds

    def generate(self, prompt: str, *, max_new_tokens: int = 16,
                 chat: bool = True) -> str:
        """
        Greedy (deterministic) free-form generation. ``chat`` applies the
        model's chat template — instruct models need it to emit a clean
        answer instead of continuing the prompt (sub-1B models produced NO
        parseable integer without it in the pilot).
        """
        torch = self._torch
        if chat and getattr(self._tok, "chat_template", None):
            text = self._tok.apply_chat_template(
                [{"role": "user", "content": prompt}],
                tokenize=False, add_generation_prompt=True)
        else:
            text = prompt
        ids = self._tok(text, return_tensors="pt").to(self._device)
        with torch.no_grad():
            out = self._model.generate(
                **ids, max_new_tokens=max_new_tokens, do_sample=False,
                pad_token_id=self._tok.eos_token_id,
            )
        return self._tok.decode(out[0][ids["input_ids"].shape[1]:],
                                skip_special_tokens=True)


class APIBackend:
    """
    Free-form backend over an OpenAI-compatible chat-completions API — the
    path to capability-matched cross-family models via free tiers (Groq,
    Google AI Studio, OpenRouter, Together, Cerebras all speak this). Zero
    new deps (stdlib urllib). Deterministic (temperature 0).

    Example:
        APIBackend("llama-3.1-8b-instant", "llama",
                   base_url="https://api.groq.com/openai/v1",
                   api_key=os.environ["GROQ_API_KEY"])
    """

    def __init__(self, model: str, family: str, *, base_url: str,
                 api_key: str, name: str | None = None):
        self.name = name or model
        self.family = family
        self._model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key

    def generate(self, prompt: str, *, max_new_tokens: int = 64,
                 chat: bool = True) -> str:
        import json as _json
        import urllib.request

        body = _json.dumps({
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": max_new_tokens,
        }).encode()
        import time
        import urllib.error
        for attempt in range(6):
            req = urllib.request.Request(
                self._url, data=body, method="POST",
                headers={"Authorization": f"Bearer {self._key}",
                         "Content-Type": "application/json",
                         # some providers sit behind Cloudflare, which blocks
                         # the default urllib User-Agent (403 error 1010).
                         "User-Agent": "gyza-research/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return _json.loads(r.read())["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 5:
                    time.sleep(2 ** attempt)          # backoff on rate limit / transient
                    continue
                raise
        raise RuntimeError("API request failed after retries")


def parse_int(text: str) -> "int | None":
    """The LAST integer appearing in ``text`` (models often restate then
    answer). Returns None if there is no integer — a distinct 'no answer'
    outcome, not silently coerced."""
    import re
    matches = re.findall(r"-?\d+", text.replace(",", ""))
    return int(matches[-1]) if matches else None


__all__ = [
    "Question", "ModelBackend", "SyntheticBackend", "SyntheticWorld",
    "error_matrix", "error_correlation", "within_cross", "shared_wrong_rate",
    "measure", "RhoResult", "HFCausalBackend", "APIBackend",
    "same_wrong_excess", "difficulty_filter", "same_wrong_convergence",
    "synth_freeform", "parse_int",
]
