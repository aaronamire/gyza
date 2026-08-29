"""The staging trio is a NON-ADOPTED execution model, and that must stay true.

`StagingArea`, `PromotionGate` and `Scheduler` have zero production
constructors. `containment/staging.py`'s header says so and explains what
covers those harm classes instead.

A CLAIM IN A DOCSTRING THAT NOTHING CHECKS IS AN ASSUMPTION. This file is the
check. If someone wires the trio into production, this test fails and the header
must be corrected -- rather than quietly becoming false, which is exactly how
"registering a checker is not evidence that it runs" (artifact #16) happened the
first time.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_staging_is_unadopted.py -q
"""
from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
GYZA = REPO / "gyza"
TRIO = {"StagingArea", "PromotionGate", "Scheduler"}

#: Modules allowed to name them: the definitions themselves plus the package
#: re-export. Anything else is a production caller.
ALLOWED = {
    GYZA / "containment" / "staging.py",
    GYZA / "containment" / "__init__.py",
    GYZA / "coordination" / "orchestrator.py",   # defines Scheduler
    GYZA / "coordination" / "__init__.py",
}


def _constructor_sites() -> list[tuple[str, int, str]]:
    """Every `Name(...)` call of the trio anywhere under gyza/.

    AST rather than grep: a string or a comment mentioning `Scheduler(` is not
    a constructor, and counting one would make the test fail for the wrong
    reason -- the same repr-vs-value confusion this corpus keeps recording.
    """
    out: list[tuple[str, int, str]] = []
    for p in sorted(GYZA.rglob("*.py")):
        if p in ALLOWED:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:                       # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in TRIO):
                out.append((str(p.relative_to(REPO)), node.lineno, node.func.id))
    return out


def test_the_staging_trio_has_NO_production_constructors():
    sites = _constructor_sites()
    assert sites == [], (
        f"the staging trio is constructed in production at {sites}. It is "
        f"labelled a non-adopted reference implementation in "
        f"gyza/containment/staging.py -- either revert the wiring, or correct "
        f"that header and this test together.")


def test_the_header_still_makes_the_claim_this_test_pins():
    """If the label is deleted, this test is guarding nothing."""
    hdr = (GYZA / "containment" / "staging.py").read_text(encoding="utf-8")
    assert "NON-ADOPTED EXECUTION MODEL" in hdr
    assert "zero\nproduction constructors" in hdr or \
           "zero production constructors" in hdr


def test_the_alternatives_named_in_the_header_actually_exist():
    """The header claims H4/H5/H6 are covered elsewhere. An excuse that cites
    machinery which does not exist is worse than no excuse."""
    from gyza.containment.gyza_model import build_registries, storage_cap_bytes
    from gyza.containment.review import check_cadence          # noqa: F401
    from gyza.network.artifact_store import ArtifactStore

    harm, _ = build_registries()
    ids = {c.id for c in harm}
    # H6 was retired as a harm class 2026-08-21 (it is a review cadence); the
    # mechanism it names still exists, which is what this test is about.
    assert {"H4_authority", "H5_storage_growth"} <= ids
    assert storage_cap_bytes() == int(harm.bound("H5_storage_growth"))
    assert hasattr(ArtifactStore, "store")
