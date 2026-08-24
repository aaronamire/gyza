"""C-2 — the harm class the model said it did not have.

`gyza_model.UNMODELLED` read: "no function in gyza/ computes an irreversibility
measure", so the guard could not distinguish computing a sum from issuing a
command that cannot be taken back. Both were one signed envelope, and every
bound the system DID enforce was a proxy for the thing anyone cares about.
"""
from __future__ import annotations

import pytest

from gyza.containment.irreversibility import (
    DESTRUCTIVE, IRREVERSIBLE, REVERSIBLE, UNPROVEN,
    benign_rate_is_zero, classify, fold_irreversible,
)

_NONET = {"backend": "bubblewrap", "ro_paths": [], "rw_paths": [],
          "requires_network": False, "max_memory_mb": 512}


def test_a_network_grant_is_IRREVERSIBLE():
    """C15's hard boundary as a measurement rather than a caveat: whatever was
    sent has left modelled state and no guard can retract it."""
    assert classify({**_NONET, "requires_network": True}).verdict == IRREVERSIBLE


def test_a_write_outside_an_append_only_store_is_DESTRUCTIVE():
    r = classify({**_NONET, "rw_paths": ["/etc"]})
    assert r.verdict == DESTRUCTIVE and "/etc" in r.reason


def test_a_write_INSIDE_the_store_is_reversible():
    """The append-only principle earns its price here: a store that keeps a
    tombstone for every removal has a restorable record, so writing to it is
    not an unrecoverable act."""
    r = classify({**_NONET, "rw_paths": ["/cas/objects"]},
                 store_paths=("/cas",))
    assert r.verdict == REVERSIBLE


def test_a_pure_compute_action_is_REVERSIBLE():
    assert classify(_NONET).verdict == REVERSIBLE
    assert classify(_NONET).counted is False


def test_a_MISSING_record_is_UNPROVEN_and_COUNTS():
    """"I did not say" must not read as "nothing left the system" -- the same
    rule the signing gate already applies to an absent enforcement record."""
    for missing in (None, {}, "not-a-record"):
        r = classify(missing)
        assert r.verdict == UNPROVEN, missing
        assert r.counted is True, "an unprovable action was counted as safe"


def test_a_prefix_collision_is_not_treated_as_inside_the_store():
    """`/cas-evil` must not pass because it starts with `/cas`."""
    r = classify({**_NONET, "rw_paths": ["/cas-evil"]}, store_paths=("/cas",))
    assert r.verdict == DESTRUCTIVE


def test_the_fold_counts_only_unrecoverable_actions():
    recs = [("a", {**_NONET, "requires_network": True}),
            ("b", _NONET),
            ("c", None),
            ("d", {**_NONET, "rw_paths": ["/tmp/x"]})]
    assert fold_irreversible(recs) == 3


def test_the_fold_is_monotone_in_its_input():
    """A pure fold over append-only input: adding actions can never reduce it,
    so there is no stored aggregate for an unmodelled path to write behind the
    guard's back."""
    recs = [("a", _NONET)]
    prev = fold_irreversible(recs)
    for k in range(5):
        recs.append((f"x{k}", {**_NONET, "requires_network": True}))
        now = fold_irreversible(recs)
        assert now >= prev
        prev = now


# --------------------------------------------------------------------------- #
#  THE RESULT: soundness is a property of the GRANT, not of the agent           #
# --------------------------------------------------------------------------- #
def test_benign_rate_is_ZERO_exactly_for_a_no_means_grant():
    """R-EVID Part C decides bound-vs-timer by the sign of the benign drift.
    Here that sign is fixed by the grant, which is why it is checkable."""
    assert benign_rate_is_zero(_NONET) is True
    assert benign_rate_is_zero({**_NONET, "requires_network": True}) is False
    assert benign_rate_is_zero({**_NONET, "rw_paths": ["/tmp"]}) is False
    assert benign_rate_is_zero(None) is False


def test_a_compliant_agent_under_a_no_means_grant_can_NEVER_increment_it():
    """b = 0 exactly. This is what makes a bound of 0 a real bound rather than
    a timer -- no level can false-alarm on an agent that cannot move it."""
    assert fold_irreversible([(f"a{i}", _NONET) for i in range(500)]) == 0


def test_under_a_NETWORK_grant_every_action_increments_it():
    """The converse, asserted rather than left implicit: b = 1 per action, so
    any cumulative level over it is a timer that fires at ceil(L/b) whatever
    the agent did. Containment over irreversible effect is claimable exactly
    for agents that were never given the means."""
    n = 50
    recs = [(f"a{i}", {**_NONET, "requires_network": True}) for i in range(n)]
    assert fold_irreversible(recs) == n


# --------------------------------------------------------------------------- #
#  Registry wiring                                                              #
# --------------------------------------------------------------------------- #
def test_the_harm_class_is_registered_and_measures_the_fold():
    from gyza.containment.gyza_model import build_registries
    from gyza.containment.projection import project_now

    harm, _ = build_registries()
    hc = harm.get("H7_irreversible_actions")
    assert hc.drift_class == "sound-by-silence"
    assert hc.frame_mutable is False

    kw = dict(owner="x", ledger_entries=[], active_holds=0.0,
              capital_entries=[])
    s0 = project_now(irreversible_actions=0, **kw)
    s = project_now(irreversible_actions=7, **kw)
    assert hc.measure(s0, s) == 7.0
    assert hc.measure(s, s0) == 0.0, "the measure must not go negative"


def test_the_harm_module_imports_no_guard(monkeypatch):
    """Discipline #5: harm must be definable without reference to the thing
    that checks it, or adequacy is tautological."""
    import gyza.containment.irreversibility as m
    src = open(m.__file__).read()
    assert "from gyza.containment.engine" not in src
    assert "GuardEngine" not in src
