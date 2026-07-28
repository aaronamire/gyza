"""
R11 tests — must be green before any result is trusted.

Six preregistered tests (PREREGISTRATION_R11.md §6): circularity,
leave-one-out, canonicalizer, degenerate predictor, economy, token cap.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import router  # noqa: E402
from data import (  # noqa: E402
    MATH_MODELS, load_math_items, math_outcomes, mbpp_outcomes, pop_difficulty,
)


# ======================================================================
# 1. CIRCULARITY — a prediction made after seeing a solution is not a router
# ======================================================================

def _leaks(prompt: str, *, solution: str, answer: str) -> bool:
    """The circularity checker: does this prompt carry outcome information?"""
    if "\\boxed" in prompt:
        return True
    if solution and solution.strip() and solution.strip()[:80] in prompt:
        return True
    if answer and f"answer is {answer}" in prompt:
        return True
    return False


def test_circularity_prompt_carries_no_solution_or_ground_truth():
    items = load_math_items()
    _, _, raws = math_outcomes()
    model = MATH_MODELS[0]
    for i, it in enumerate(items):
        p = router.build_prompt(it["problem"], task="math")
        assert not _leaks(p, solution=raws[model][i], answer=it["ref_raw"])
        # the rendered prompt is EXACTLY the frozen template + the problem
        assert p == router.SELF_MATH.format(problem=it["problem"])
        # ... and everything OUTSIDE the problem slot is item-invariant, so no
        # per-item information other than the problem statement can enter.
        # (A substring test on ref_raw is useless here: a ground truth of "1"
        # is a substring of the constant text "0 to 100".)
        head, tail = p.split(it["problem"], 1)
        assert head == router.SELF_MATH.split("{problem}", 1)[0]
        assert tail == router.SELF_MATH.split("{problem}", 1)[1]


def test_circularity_negative_control_detects_a_violation():
    """The checker must be able to FAIL, or it proves nothing."""
    items = load_math_items()
    _, _, raws = math_outcomes()
    model, it = MATH_MODELS[0], items[0]
    sol = raws[model][0]
    violating = (router.build_prompt(it["problem"], task="math")
                 + "\n\nHere is the solution: " + sol)
    assert _leaks(violating, solution=sol, answer=it["ref_raw"])


def test_build_prompt_has_no_channel_for_an_answer():
    import inspect
    params = set(inspect.signature(router.build_prompt).parameters)
    assert params == {"problem", "task", "claimant"}
    for bad in ("solution", "answer", "label", "ref", "correct", "outcome"):
        assert bad not in params


def test_cross_prompt_names_the_claimant_and_still_leaks_nothing():
    items = load_math_items()
    _, _, raws = math_outcomes()
    it = items[3]
    p = router.build_prompt(it["problem"], task="math",
                            claimant="microsoft/phi-4")
    assert "microsoft/phi-4" in p
    assert not _leaks(p, solution=raws[MATH_MODELS[0]][3], answer=it["ref_raw"])


# ======================================================================
# 2. LEAVE-ONE-OUT — the null must not see the model's own outcome
# ======================================================================

def test_pop_difficulty_excludes_the_models_own_outcome():
    _, mb = mbpp_outcomes()
    models = list(mb)
    for m in models:
        for q in range(len(mb[m])):
            others = [mb[o][q] for o in models if o != m]
            expect = (sum(1 for v in others if v) / len(others)) if others else None
            assert pop_difficulty(mb, q, m) == pytest.approx(expect)


def test_pop_difficulty_is_insensitive_to_flipping_the_models_own_outcome():
    """The decisive property: flipping M's own label must not move the null."""
    _, mb = mbpp_outcomes()
    m = list(mb)[0]
    before = [pop_difficulty(mb, q, m) for q in range(len(mb[m]))]
    mb[m] = [not v for v in mb[m]]
    after = [pop_difficulty(mb, q, m) for q in range(len(mb[m]))]
    assert before == after


# ======================================================================
# 3. CANONICALIZER — MATH labels use canonicalizer_v2 (Phase 8)
# ======================================================================

def test_math_labels_use_canonicalizer_v2_notation_cases():
    """
    Regression cases pin the COMMITTED behaviour of canonicalizer_v2 (Phase 8,
    hand-validated 27/27, zero false merges). It is imported read-only and is
    never modified here.
    """
    import canonicalizer_v2 as c
    assert c.equal("\\dfrac{1}{2}", "\\frac{1}{2}") is True
    assert c.equal("\\frac32", "3/2") is True          # brace-less \frac
    assert c.equal("2\\sqrt{3}", "2√3") is True        # unicode sqrt
    assert c.equal("\\left(3\\right)", "(3)") is True
    assert c.equal("0.5", "\\frac{1}{2}") is True
    assert c.equal("3", "4") is False


def test_canonicalizer_text_annotation_is_conservatively_unresolved():
    """
    `\\text{...}` is DISCARDED as a unit annotation ("5 \\text{feet}" -> "5"),
    which is right for units and means a BARE `\\text{2}` normalises to the
    empty string and is reported UNRESOLVED rather than guessed.

    This is the conservative, zero-false-merge behaviour Phase 8 validated —
    pinned here because it is one source of the (small) MATH exclusion counts,
    NOT a defect to be "fixed".
    """
    import canonicalizer_v2 as c
    assert c.norm("\\text{2}") == ""
    assert c.equal("\\text{2}", "2") is None
    assert c.equal("\\text{feet}", "feet") is None


def test_no_answer_is_labelled_failure_not_excluded():
    """Amendment 1: NO-ANSWER is a failure; only true undecidables excluded."""
    _, labels, raws = math_outcomes()
    from route2_experiment import extract_boxed
    for m, lab in labels.items():
        for i, v in enumerate(lab):
            if not extract_boxed(raws[m][i]):
                assert v is False, f"{m}[{i}] NO-ANSWER must be False, got {v!r}"
    # and the exclusion rate is now small (it was 19-40/80 before the fix)
    for m, lab in labels.items():
        assert sum(1 for v in lab if v is None) <= 5


# ======================================================================
# 4. DEGENERATE PREDICTOR — pins the gameability signature
# ======================================================================

def test_constant_confidence_gives_auroc_half_and_zero_economy():
    labels = [True, False, True, False, True, False, False, True]
    const = [50.0] * len(labels)
    assert router.auroc(const, labels) == pytest.approx(0.5)
    curve = router.sweep(const, labels)
    for target in (0.90, 0.95, 0.99):
        best = router.economy_at_recall(curve, target)
        assert best is not None
        assert best["economy"] == pytest.approx(0.0)


def test_is_degenerate_flags_a_near_constant_predictor():
    assert router.is_degenerate([80] * 19 + [70])
    assert router.is_degenerate([80, 80, 80, 80, 90, 90, 90, 90, 90, 100])
    assert not router.is_degenerate(list(range(0, 100, 5)))


# ======================================================================
# 5. ECONOMY — perfect predictor => economy = 1 - base_failure_rate
# ======================================================================

def test_perfect_predictor_economy_equals_one_minus_base_failure_rate():
    labels = [True] * 7 + [False] * 3
    scores = [90.0] * 7 + [10.0] * 3
    base_failure = 3 / 10
    curve = router.sweep(scores, labels)
    best = router.economy_at_recall(curve, 1.0)
    assert best is not None
    assert best["recall"] == pytest.approx(1.0)
    assert best["economy"] == pytest.approx(1 - base_failure)


def test_auroc_undefined_when_a_class_is_empty():
    assert router.auroc([1.0, 2.0, 3.0], [True, True, True]) is None
    assert router.auroc([1.0, 2.0, 3.0], [False, False, False]) is None


def test_auroc_perfect_and_inverted():
    labels = [True, True, False, False]
    assert router.auroc([9.0, 8.0, 2.0, 1.0], labels) == pytest.approx(1.0)
    assert router.auroc([1.0, 2.0, 8.0, 9.0], labels) == pytest.approx(0.0)


# ======================================================================
# 6. TOKEN CAP — GATE 0d, enforced not assumed
# ======================================================================

def test_elicitor_refuses_to_exceed_the_token_cap():
    router.Elicitor("x/y", max_tokens=50)
    with pytest.raises(ValueError):
        router.Elicitor("x/y", max_tokens=51)
    with pytest.raises(ValueError):
        router.Elicitor("x/y", max_tokens=400)


def test_elicitor_issues_calls_at_or_below_the_cap(monkeypatch, tmp_path):
    seen = {}

    def fake_urlopen(req, timeout=0):
        import json as _j
        seen["body"] = _j.loads(req.data)

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return _j.dumps({
                    "choices": [{"message": {"content": "72"}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 2},
                }).encode()
        return R()

    monkeypatch.setattr(router.urllib.request, "urlopen", fake_urlopen)
    # a FRESH cache dir per run, or the assertion silently reads a prior
    # run's cached result and never exercises the call path at all
    monkeypatch.setattr(router, "CACHE", tmp_path / "r11_test_cache")
    e = router.Elicitor("x/y")
    out = e.run(["hello"], tag="unit_token_cap")
    assert seen["body"]["max_tokens"] <= 50
    assert seen["body"]["temperature"] == 0
    assert out[0]["conf"] == 72


# ======================================================================
# parsing
# ======================================================================

@pytest.mark.parametrize("txt,exp", [
    ("72", 72), ("  85 ", 85), ("0", 0), ("100", 100),
    ("I'd say 40", 40), ("101", None), ("", None), ("no idea", None),
    ("__ERR__:HTTP429", 429 if False else None),
])
def test_parse_confidence(txt, exp):
    assert router.parse_confidence(txt) == exp


def test_no_chain_of_thought_permitted_in_any_template():
    for tpl in (router.SELF_MATH, router.SELF_MBPP,
                router.CROSS_MATH, router.CROSS_MBPP):
        assert "Do NOT solve it" in tpl
        assert "Output ONLY the integer" in tpl
        assert "step by step" not in tpl.lower()
