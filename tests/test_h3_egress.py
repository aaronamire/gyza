"""H3 — the egress log, its classification, and the measurand it feeds.

The claim under test is `gyza/containment/egress.py`'s: the four sites
`HARM_MODEL_DRAFT` §H3 calls "external network sends" are mesh-INTERNAL, so H3
must classify by what is on the other side rather than count sends flatly.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_h3_egress.py -q
"""
from __future__ import annotations

import pytest

from gyza.blackboard import Blackboard
from gyza.containment.egress import (
    EgressClass, EgressRecorder, classify_peer,
)
from gyza.containment.gyza_model import build_registries
from gyza.containment.projection import project_now


def _bb(tmp_path):
    return Blackboard(str(tmp_path / "bb.db"))


# --------------------------------------------------------------------------- #
#  CLASSIFICATION                                                              #
# --------------------------------------------------------------------------- #
def test_an_absent_attestation_source_is_NOT_a_passing_attestation():
    """The whole bound hangs on this direction. `attested_peers=None` means
    nothing vouches for the destination, so the honest class is UNATTESTED."""
    assert classify_peer("peerA", None) == EgressClass.UNATTESTED_PEER
    assert classify_peer("peerA", frozenset()) == EgressClass.UNATTESTED_PEER
    assert classify_peer("peerA", frozenset({"peerB"})) == \
        EgressClass.UNATTESTED_PEER
    assert classify_peer("peerA", frozenset({"peerA"})) == \
        EgressClass.ATTESTED_PEER


def test_H3_counts_UNATTESTED_and_OUTSIDE_but_never_ATTESTED():
    assert set(EgressClass.MESH_EXIT) == {EgressClass.UNATTESTED_PEER,
                                          EgressClass.OUTSIDE_PROTOCOL}
    assert EgressClass.ATTESTED_PEER not in EgressClass.MESH_EXIT


# --------------------------------------------------------------------------- #
#  THE LOG                                                                     #
# --------------------------------------------------------------------------- #
def test_an_unclassified_send_is_REFUSED_not_recorded_as_unknown(tmp_path):
    bb = _bb(tmp_path)
    with pytest.raises(ValueError, match="unknown egress class"):
        bb.record_egress("SOMETHING_ELSE", "chan", "dest", 10)


def test_the_log_is_DURABLE_across_a_cold_reopen(tmp_path):
    """H6's rule, applied here: an in-process counter resets on restart, and a
    cumulative bound whose origin can move is not a bound."""
    bb = _bb(tmp_path)
    for c in (EgressClass.ATTESTED_PEER, EgressClass.UNATTESTED_PEER,
              EgressClass.OUTSIDE_PROTOCOL):
        bb.record_egress(c, "chan", "dest", 5)
    del bb

    bb2 = Blackboard(str(tmp_path / "bb.db"))
    assert bb2.count_egress_since(0) == 3
    assert bb2.count_egress_since(0, EgressClass.MESH_EXIT) == 2


def test_the_default_counts_EVERYTHING_which_is_not_H3s_measurand(tmp_path):
    """A default that silently included attested peers would make the federated
    case indistinguishable from the exit case."""
    bb = _bb(tmp_path)
    for _ in range(5):
        bb.record_egress(EgressClass.ATTESTED_PEER, "c", "d", 1)
    assert bb.count_egress_since(0) == 5
    assert bb.count_egress_since(0, EgressClass.MESH_EXIT) == 0


def test_the_origin_is_honoured(tmp_path):
    bb = _bb(tmp_path)
    bb.record_egress(EgressClass.OUTSIDE_PROTOCOL, "c", "d", 1,
                     timestamp_ns=1_000)
    bb.record_egress(EgressClass.OUTSIDE_PROTOCOL, "c", "d", 1,
                     timestamp_ns=3_000)
    assert bb.count_egress_since(0) == 2
    assert bb.count_egress_since(2_000) == 1
    assert bb.count_egress_since(9_000) == 0


def test_an_empty_class_list_is_zero_not_everything(tmp_path):
    """`classes=[]` means 'none of them'. Falling through to the unfiltered
    query would report every send as H3 harm."""
    bb = _bb(tmp_path)
    bb.record_egress(EgressClass.OUTSIDE_PROTOCOL, "c", "d", 1)
    assert bb.count_egress_since(0, []) == 0


# --------------------------------------------------------------------------- #
#  THE RECORDER                                                                #
# --------------------------------------------------------------------------- #
def test_the_recorder_classifies_and_persists(tmp_path):
    bb = _bb(tmp_path)
    r = EgressRecorder(bb, attested_peers=frozenset({"good"}))
    assert r.peer_send("send_message:x", "good", 10) == \
        EgressClass.ATTESTED_PEER
    assert r.peer_send("send_message:x", "rogue", 10) == \
        EgressClass.UNATTESTED_PEER
    assert r.outside_send("http_fetch", "https://example.invalid", 10) == \
        EgressClass.OUTSIDE_PROTOCOL
    assert bb.count_egress_since(0) == 3
    assert bb.count_egress_since(0, EgressClass.MESH_EXIT) == 2


# --------------------------------------------------------------------------- #
#  THE MEASURAND — artifact #16: a registry entry must RUN on a real input      #
# --------------------------------------------------------------------------- #
def test_H3_is_registered_AND_measures_the_real_log(tmp_path):
    """785 passing tests once failed to detect a harm quantity that raised on
    every input, because a suite that builds its own fixtures never touches the
    registered one. This drives the REGISTERED class over the REAL log."""
    bb = _bb(tmp_path)
    r = EgressRecorder(bb, attested_peers=frozenset({"good"}))
    for _ in range(4):
        r.peer_send("send_message:m", "good", 1)      # attested: not H3
    for _ in range(3):
        r.peer_send("send_message:m", "rogue", 1)     # unattested: H3
    r.outside_send("http_fetch", "https://example.invalid", 1)   # H3

    harm, _inv = build_registries()
    # The RATE is the registered class; the count was retired 2026-08-21 for
    # carrying zero evidence. Same log, same exclusion of attested peers -- the
    # quantity that reads it changed, the property under test did not.
    hc = harm.get("H3_mesh_exit_rate")

    kw = dict(owner="pk", ledger_entries=[], active_holds=0.0,
              capital_entries=[])
    s0 = project_now(mesh_exit_bytes_in_window=0, **kw)
    s = project_now(
        mesh_exit_bytes_in_window=bb.mesh_exit_bytes_since(
            0, EgressClass.MESH_EXIT), **kw)

    # 3 unattested peer sends + 1 outside send, 1 byte each. The 4 ATTESTED
    # sends are excluded, which is the whole point of the class filter.
    assert hc.measure(s0, s) == 4.0, "H3 did not measure the real log"
    # and the attested sends are genuinely excluded
    assert bb.count_egress_since(0) == 8


def test_H3_has_an_invariant_because_a_class_without_one_refuses_everything():
    """E2's defect: `E2_drawdown` was registered with no invariant, the engine's
    C4 error came back through the same channel as a bound breach, and the guard
    refused all nine settlements while the table looked publishable."""
    harm, inv = build_registries()
    for hc in harm:
        assert inv.for_harm_class(hc.id), \
            f"{hc.id} has no registered invariant; the engine will refuse " \
            f"every action through the bound-breach channel"


def test_H3_is_reported_UNBOUNDED_rather_than_silently_passing():
    """Measured, not bounded, is the honest state — and `readiness()` must say
    so. A class with no level that reported ready would be the reassuring
    direction again."""
    from gyza.containment.engine import GuardEngine
    harm, inv = build_registries()
    r = GuardEngine(harm, inv).readiness()
    # H3's LEVEL was declared 2026-08-21 (v3, 300 MB/h), so it is no longer
    # unbounded. What this test guards is that the class is REGISTERED and
    # COVERED -- a class with no invariant makes the engine refuse everything
    # through the same channel as a breach.
    assert "H3_mesh_exit_rate" in {c.id for c in harm}
    assert "H3_mesh_exit_rate" not in r["uncovered"]
    assert harm.bound("H3_mesh_exit_rate") == 300_000_000


# --------------------------------------------------------------------------- #
#  H5 — ONE BOUND, ONE SOURCE                                                  #
# --------------------------------------------------------------------------- #
def test_the_store_cap_comes_from_the_DECLARED_bound_not_from_config():
    """`guard_bounds.json` declared H5 while `ArtifactStore.max_bytes` was wired
    from `GyzaConfig.max_artifact_store_gb` at three CLI sites. They agreed at
    10 GB only because H5's level was transcribed from the config, and nothing
    kept them in step."""
    from gyza.cli import _declared_storage_cap
    from gyza.containment.gyza_model import build_registries, storage_cap_bytes

    harm, _ = build_registries()
    assert storage_cap_bytes() == int(harm.bound("H5_storage_growth"))
    assert _declared_storage_cap() == storage_cap_bytes()


def test_no_declared_H5_level_means_UNLIMITED_not_a_silent_default(tmp_path):
    """The honest reading of 'no bound declared'. A fallback default here would
    enforce a cap nobody declared and report it as policy."""
    from gyza.containment.gyza_model import storage_cap_bytes
    empty = tmp_path / "none.json"
    empty.write_text('{"bounds": {}}')
    assert storage_cap_bytes(empty) is None


# --------------------------------------------------------------------------- #
#  H3's HARD LIMIT — a capability grant is not a send                          #
# --------------------------------------------------------------------------- #
def test_a_GRANT_is_never_counted_as_a_SEND(tmp_path):
    """The unit-safety property, and the whole reason UNBOUNDED_GRANT exists.

    `bwrap`'s network control is all-or-nothing, so one granted sandbox permits
    arbitrarily many invisible sends. Counting the grant as one send would
    report 1 for an unbounded quantity — in the reassuring direction."""
    bb = _bb(tmp_path)
    r = EgressRecorder(bb, attested_peers=frozenset())
    r.unbounded_grant("sandbox:share-net", "pkg.mod:factory")
    r.unbounded_grant("sandbox:share-net", "pkg.mod:factory")

    assert bb.count_grants_since(0) == 2
    # H3 must not see them at all
    assert bb.count_egress_since(0, EgressClass.MESH_EXIT) == 0
    assert EgressClass.UNBOUNDED_GRANT not in EgressClass.MESH_EXIT


def test_an_unknown_volume_is_NULL_not_zero(tmp_path):
    """0 would claim nothing left the machine. NULL says unknown, which is
    what is actually true of a shared network namespace."""
    import sqlite3
    bb = _bb(tmp_path)
    EgressRecorder(bb, None).unbounded_grant("sandbox:share-net", "f")
    con = sqlite3.connect(str(tmp_path / "bb.db"))
    got = con.execute(
        "SELECT byte_count FROM egress_log WHERE egress_class=?",
        (EgressClass.UNBOUNDED_GRANT,)).fetchone()
    assert got is not None and got[0] is None, got


def test_the_sandbox_records_a_grant_ONLY_when_network_is_shared(tmp_path):
    """Drives the REAL `run_sandboxed` argument path. A sandbox with no network
    must record nothing — otherwise the measure counts denied capability."""
    from gyza.sandbox.config import SandboxConfig
    from gyza.sandbox.runner import SandboxUnavailableError, run_sandboxed

    bb = _bb(tmp_path)
    rec = EgressRecorder(bb, None)

    def _drive(requires_network: bool):
        try:
            run_sandboxed(
                factory_qualname="gyza.nonexistent:factory", init_kwargs={},
                prompt="p", context={},
                config=SandboxConfig(requires_network=requires_network,
                                     backend="bubblewrap"),
                egress_recorder=rec)
        except Exception:
            # the call is expected to fail; the grant is recorded BEFORE the
            # subprocess launches, because the capability is granted at
            # argv-construction time whether or not the agent then works
            pass

    _drive(False)
    assert bb.count_grants_since(0) == 0, "recorded a grant with no network"
    _drive(True)
    assert bb.count_grants_since(0) >= 1, "network grant was not recorded"
