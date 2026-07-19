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


__all__ = [
    "Question", "ModelBackend", "SyntheticBackend", "SyntheticWorld",
    "error_matrix", "error_correlation", "within_cross", "shared_wrong_rate",
    "measure", "RhoResult", "HFCausalBackend",
]
