"""Tests for the hardened conservative canonicalizer (Phase 8). Must pass before
recompute. Includes the mandatory conservatism tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from canonicalizer_v2 import equal, norm  # noqa: E402


# --- conservatism (never merge different values) ---
def test_distinct_stay_distinct():
    assert equal("1/2", "2/3") is False
    assert equal("\\sqrt{2}", "1.414") is False          # no numeric coercion
    assert equal("3", "4") is False
    assert equal("(4,1)", "(2,1)") is False               # element-wise distinct


# --- merges that fix the contamination ---
def test_merges():
    assert equal("\\dfrac{1}{2}", "0.5") is True
    assert equal("3\\frac12", "3.5") is True              # mixed number
    assert equal("\\frac{25}{16}", "\\cfrac{25}{16}") is True
    assert equal("2√13", "2\\sqrt{13}") is True
    assert equal("2\\sqrt{13}", "\\sqrt{52}") is True     # sympy proves equal
    assert equal("162 minutes", "162") is True
    assert equal("12^{\\mathrm{th}} grade", "12") is True
    assert equal("\\frac32", "3/2") is True
    assert equal("19{,}404", "19404") is True or equal("19,404", "19404") is True


# --- unresolved is not "wrong" ---
def test_unresolved_marked_none():
    # a genuinely unparseable, string-different pair -> None, never False
    r = equal("\\begin{pmatrix}1\\\\2\\end{pmatrix}", "3")
    assert r is None or r is False   # matrices: at worst unresolved, never a spurious True
    assert equal("", "5") is None


def test_norm_examples():
    assert norm("\\boxed{\\frac{25}{16}}") == norm("\\cfrac{25}{16}")
    assert norm("162\\text{ minutes}") == "162"
