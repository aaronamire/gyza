"""Every declared level must say whether it is a BOUND or a TIMER.

R-EVID Part C (`research/evidence/THEOREMS_C.md`) proves that an accumulating
safety quantity is Lindley's recursion, and that a level on it is a real bound
only when the benign drift is non-positive and the fold reflects at zero.
Otherwise the level is a TIMER: false-alarm probability 1, firing at ceil(L/b).

THE POINT OF DECLARING IT BESIDE THE BOUND. `H6_unsupervised_actions` carried a
SIGNED level of 10,000 while its benign and adversarial rates were identical --
so no level it could ever carry would separate them. The number was checkable,
signed, and meaningless. The drift class is the part that says whether a level
means anything, so it belongs next to the level and not in a document.
"""
from __future__ import annotations

from dataclasses import fields

import pytest

from gyza.containment.gyza_model import build_registries
from gyza.containment.harm import (
    BoundsProvenance, DriftClass, HarmClass, HarmModelRegistry,
)


def _q(_s0, _s):
    return 0.0


def test_every_production_harm_class_declares_a_drift_class_and_a_reason():
    harm, _ = build_registries()
    missing = [c.id for c in harm if c.drift_class is None]
    assert not missing, (
        f"{missing} declare a quantity and no drift class. A level without one "
        f"does not say whether it is a bound or a timer.")
    for c in harm:
        assert c.drift_class in DriftClass.ALL, (
            f"{c.id} has drift class {c.drift_class!r}, not one of the four "
            f"cases -- the classification is exhaustive by Theorem 5")
        assert len(c.drift_reason) > 40, (
            f"{c.id} declares {c.drift_class!r} with no substantive reason. "
            f"The classification is a claim about production behaviour, not a "
            f"label.")


def test_the_readiness_report_names_which_bounds_are_only_timers():
    """A signed level on a timer must not read the same as one on a bound."""
    from gyza.containment.engine import GuardEngine

    harm, inv = build_registries()
    r = GuardEngine(harm, inv).readiness()
    assert "bounded_but_only_a_timer" in r
    # H5 and H6 both carry declared levels and both are timers today. If either
    # is repaired, this test should be updated ALONG WITH the drift_reason --
    # not silenced.
    assert set(r["bounded_but_only_a_timer"]) == {
        "H5_storage_growth", "H6_unsupervised_actions"}
    assert r["unclassified_drift"] == []


def test_H4_is_the_only_class_whose_level_is_a_real_bound():
    """Measured, not assumed: R-EVID Part B put H4's benign rate at exactly
    0.000. If another class ever becomes sound this test should change, and
    changing it should require saying which one and why."""
    harm, _ = build_registries()
    sound = {c.id for c in harm if c.drift_class in DriftClass.SOUND}
    assert sound == {"H4_authority"}


# --------------------------------------------------------------------------- #
#  The species, not just the instance                                          #
# --------------------------------------------------------------------------- #
def test_load_bounds_preserves_EVERY_field_not_just_the_ones_it_knew_about():
    """A field-by-field rebuild silently drops fields added later.

    `load_bounds` used to enumerate six fields, so `drift_class` and
    `drift_reason` vanished from exactly the classes that carry a level -- the
    only ones where the classification matters. It is `dataclasses.replace`
    now, and this asserts the PROPERTY rather than the two fields, so the next
    field added is covered without anyone remembering to come back here.
    """
    hc = HarmClass(
        id="X", description="d", quantity=_q, frame="f", frame_mutable=False,
        code_path="p", drift_class=DriftClass.SILENCE,
        drift_reason="benign behaviour never increments this quantity",
    )
    reg = HarmModelRegistry()
    reg.register(hc)
    reg.load_bounds({"X": 5.0}, provenance=BoundsProvenance(
        source="UNSIGNED_FILE", detail="test"))

    after = next(iter(reg))
    for f in fields(HarmClass):
        if f.name == "bound":
            continue
        assert getattr(after, f.name) == getattr(hc, f.name), (
            f"load_bounds dropped field {f.name!r}; use dataclasses.replace "
            f"rather than enumerating fields")
    assert after.bound == 5.0


def test_a_drift_class_outside_the_four_cases_is_rejected_by_the_test_not_by_luck():
    """Exhaustiveness is the claim; anything else must be visible."""
    assert DriftClass.ALL == {
        DriftClass.SILENCE, DriftClass.CAPACITY,
        DriftClass.DETECTION, DriftClass.TIMER,
    }
    assert DriftClass.TIMER not in DriftClass.SOUND
    assert DriftClass.SOUND < DriftClass.ALL
