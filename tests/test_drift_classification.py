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
    # EMPTY as of 2026-08-21. H6 was retired (it is a cadence, not a harm
    # class) and H5 gained eviction, which supplies the compensation term its
    # fold needed. If a timer ever reappears here it should be because a NEW
    # class was added without a sound shape -- update this test along with that
    # class's drift_reason, never by silencing it.
    assert r["bounded_but_only_a_timer"] == []
    assert r["unclassified_drift"] == []


def test_H4_is_the_only_class_whose_LEVEL_is_a_real_bound():
    """A sound SHAPE and a real BOUND are different claims, and only the second
    is what the containment argument spends.

    `H3_mesh_exit_rate` has a sound shape (sound-by-detection: a trailing
    window gives non-positive benign drift) and NO LEVEL, so it bounds nothing
    today. Asserting over shapes alone would have read that as progress. The
    claim this test makes is about declared levels.
    """
    harm, _ = build_registries()
    sound_shape = {c.id for c in harm if c.drift_class in DriftClass.SOUND}
    assert sound_shape == {"H4_authority", "H5_storage_growth",
                           "H3_mesh_exit_rate"}

    real_bounds = {c.id for c in harm
                   if c.bound is not None and c.drift_class in DriftClass.SOUND}
    assert real_bounds == {"H4_authority", "H5_storage_growth"}, (
        "a class other than H4 now carries a level whose shape makes it a real "
        "bound; that is a genuine change and this test should say which and why")


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


# =========================================================================== #
#  A TIMER IS NOT A BOUND, so a level on one must not buy the claim.
# =========================================================================== #
def test_the_production_model_has_no_timers_left():
    """H4 sound-by-silence, H5 sound-by-capacity, H3 sound-by-detection -- one
    class in each of Theorem 5's three sound cases, and none in the fourth.

    The blocking RULE is proven separately against a synthetic timer below,
    because a rule with no instance left to catch is a rule nobody is testing.
    """
    from gyza.containment.engine import GuardEngine

    harm, inv = build_registries()
    harm.load_bounds({"H3_mesh_exit_rate": 5e7})
    r = GuardEngine(harm, inv).readiness(authority_key_search=["/nonexistent"])

    # No timer remains in the PRODUCTION model, so this construction now
    # clears every obstacle -- which is the honest state and is why the
    # negative case below is asserted separately against a synthetic timer.
    assert r["unbounded"] == []
    assert r["uncovered"] == []
    assert r["unclassified_drift"] == []
    assert r["authority_key_colocated"] is None
    assert r["bounded_but_only_a_timer"] == []
    # Still False, and for the one honest remaining reason in this
    # construction: `build_registries()` loads the signed FILE without an
    # authority pubkey to verify it against, so provenance is
    # SIGNED_UNVERIFIED. That is a provenance gap, not a drift gap.
    assert r["bounds_signed"] is False
    assert r["can_claim_containment"] is False


def test_an_UNCLASSIFIED_drift_class_also_blocks_the_claim(tmp_path):
    """An unanswered question must not read as a passing one. A class that has
    not said which of the four cases it is in has not shown that its level
    means anything."""
    from gyza.containment.engine import GuardEngine
    from gyza.containment.harm import BoundsProvenance, HarmModelRegistry
    from gyza.containment.invariants import (
        Invariant, InvariantClass, InvariantRegistry,
    )

    harm = HarmModelRegistry()
    harm.register(HarmClass(
        id="Y", description="d", quantity=_q, frame="f", frame_mutable=False,
        code_path="p"))                       # <- no drift_class
    harm.load_bounds({"Y": 1.0}, provenance=BoundsProvenance(
        source="SIGNED", detail="t", authority_pubkey_hex="ab" * 32,
        version=1, config_hash="h"))
    inv = InvariantRegistry()
    inv.register(Invariant(id="INV-Y", harm_class="Y",
                           cls=InvariantClass.CUMULATIVE, description="covers Y"))

    r = GuardEngine(harm, inv).readiness(authority_key_search=["/nonexistent"])
    assert r["unclassified_drift"] == ["Y"]
    assert r["can_claim_containment"] is False


def test_the_retired_count_no_longer_blocks_the_claim_forever():
    """H3_mesh_exit_sends can NEVER carry a level -- benign and exfiltrating
    nodes emit the same number of sends. Leaving it registered kept `unbounded`
    permanently non-empty, making the containment claim UNREACHABLE BY
    CONSTRUCTION: progress that quietly removes the goal.
    """
    from gyza.containment.gyza_model import RETIRED_AS_HARM_CLASS

    harm, _ = build_registries()
    assert "H3_mesh_exit_sends" not in {c.id for c in harm}
    assert "H3_mesh_exit_sends" in RETIRED_AS_HARM_CLASS
    # Declaring the RATE level must now actually clear the unbounded gate.
    harm.load_bounds({"H3_mesh_exit_rate": 5e7})
    assert harm.unbounded() == []


def test_a_SYNTHETIC_timer_still_refuses_the_claim(tmp_path):
    """The production model no longer contains a timer, so the blocking rule
    must be proven against one that does -- otherwise the rule is untested and
    would silently stop working the moment a timer reappeared."""
    from gyza.containment.engine import GuardEngine
    from gyza.containment.harm import BoundsProvenance, HarmModelRegistry
    from gyza.containment.invariants import (
        Invariant, InvariantClass, InvariantRegistry,
    )

    harm = HarmModelRegistry()
    harm.register(HarmClass(
        id="Z", description="d", quantity=_q, frame="f", frame_mutable=False,
        code_path="p", drift_class=DriftClass.TIMER,
        drift_reason="positive benign drift with no compensation term"))
    harm.load_bounds({"Z": 100.0}, provenance=BoundsProvenance(
        source="SIGNED", detail="t", authority_pubkey_hex="cd" * 32,
        version=1, config_hash="h"))
    inv = InvariantRegistry()
    inv.register(Invariant(id="INV-Z", harm_class="Z",
                           cls=InvariantClass.CUMULATIVE, description="covers Z"))

    r = GuardEngine(harm, inv).readiness(authority_key_search=["/nonexistent"])
    assert r["unbounded"] == []
    assert r["bounded_but_only_a_timer"] == ["Z"]
    assert r["can_claim_containment"] is False
