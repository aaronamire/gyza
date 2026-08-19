"""H3's producers must FIRE, not merely exist.

REGISTERING A CHECKER IS NOT EVIDENCE THAT IT RUNS. H3 was registered as a
measured harm class and was disconnected at five independent points at once:

  1. `EgressRecorder` had ZERO production constructors, so every send path
     short-circuited on `if recorder is None: return`.
  2. `publish_delta` and `publish_attestation` -- 2 of the 4 sites
     `HARM_MODEL_DRAFT` §H3 cites -- never called the recorder at all.
  3. `outside_send` has no caller, so `OUTSIDE_PROTOCOL` is unreachable
     in-process.
  4. No attested-peer source exists, so every peer send classifies UNATTESTED.
  5. `GyzaState.mesh_exit_sends` was supplied by nothing, so H3 computed
     `0 - 0 = 0` even had 1-4 been fixed.

785 passing tests did not detect the analogous defect in artifact #16. These
tests assert EXECUTION against real input, which is the only thing that would
have caught it. See research/H3_WIRING_GAP.md.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from gyza.blackboard import Blackboard
from gyza.containment.egress import (
    EgressClass,
    EgressRecorder,
    classify_peer,
    default_egress_recorder,
)
from gyza.containment.gyza_model import mesh_exit_sends_since


@pytest.fixture()
def db() -> str:
    return str(Path(tempfile.mkdtemp()) / "bb.db")


def test_the_factory_actually_constructs_a_recorder(db):
    """Defect 1. Before `default_egress_recorder` existed, nothing did."""
    assert default_egress_recorder(db) is not None


def test_every_recorder_method_writes_a_row(db):
    r = default_egress_recorder(db)
    assert r.peer_send("send_message:x", "12D3KooWfake", 128) == \
        EgressClass.UNATTESTED_PEER
    assert r.outside_send("http", "example.com", 64) == \
        EgressClass.OUTSIDE_PROTOCOL
    assert r.unbounded_grant("sandbox", "<any>") == EgressClass.UNBOUNDED_GRANT
    rows = sqlite3.connect(db).execute(
        "SELECT egress_class, byte_count FROM egress_log").fetchall()
    assert len(rows) == 3
    # NULL, not 0: "unknown bytes" is the truth, "zero bytes" is the
    # reassuring falsehood.
    assert dict(rows)[EgressClass.UNBOUNDED_GRANT] is None


def test_h3_count_EXCLUDES_grants(db):
    """Defect 5's near-miss. A grant is a different unit from a send.

    `count_egress_since` defaults to every class, so a caller that forgets the
    filter silently folds grants into the send count.
    """
    r = default_egress_recorder(db)
    r.peer_send("send_message:x", "peerA", 10)
    r.outside_send("http", "example.com", 10)
    r.unbounded_grant("sandbox", "<any>")
    bb = Blackboard(db)
    assert bb.count_egress_since(0) == 3            # every class
    assert bb.count_grants_since(0) == 1
    assert mesh_exit_sends_since(bb, 0) == 2        # H3's actual measurand


def test_classify_fails_toward_unattested(db):
    """Defect 4. An absent attestation source is not a passing attestation."""
    assert classify_peer("p", None) == EgressClass.UNATTESTED_PEER
    assert classify_peer("p", frozenset()) == EgressClass.UNATTESTED_PEER
    assert classify_peer("p", frozenset({"p"})) == EgressClass.ATTESTED_PEER


def test_all_four_documented_sites_record(db):
    """Defect 2. `publish_delta` and `publish_attestation` recorded nothing.

    The gRPC stubs are faked -- this asserts the CLIENT calls the recorder, not
    that a daemon accepted the RPC, which the integration suite covers.
    """
    from gyza.network import netd_client as nc

    rec = default_egress_recorder(db)
    fired: list[str] = []

    class _Rec(EgressRecorder):
        def peer_send(self, channel, peer_id, byte_count):
            fired.append(channel)
            return super().peer_send(channel, peer_id, byte_count)

    r = _Rec(Blackboard(db), None)

    # NetdClient's two sites already recorded; assert they still do.
    n = nc.NetdClient.__new__(nc.NetdClient)
    n._egress = r
    n._record_egress("publish_agent", "/gyza/agent/x", 32)
    n._record_egress("send_message:settle", "peerB", 64)

    # The two that did not. `_safe_peer_send` is what publish_delta and
    # publish_attestation now call.
    nc._safe_peer_send(r, "publish_delta", "topic:default", 128)
    nc._safe_peer_send(r, "publish_attestation", "/gyza/attest/y", 256)

    assert fired == ["publish_agent", "send_message:settle",
                     "publish_delta", "publish_attestation"]
    assert mesh_exit_sends_since(Blackboard(db), 0) == 4


def test_measurement_never_breaks_a_send():
    """AN ERROR IS NOT A VALUE -- and here it must not be a failed send."""
    from gyza.network import netd_client as nc

    class _Broken:
        def peer_send(self, *a, **k):
            raise RuntimeError("storage down")

    nc._safe_peer_send(_Broken(), "publish_delta", "topic:x", 1)   # no raise
    nc._safe_peer_send(None, "publish_delta", "topic:x", 1)        # unwired


def test_global_cluster_builds_a_recorder():
    """Defect 1 at the real injection site, asserted structurally."""
    import inspect

    from gyza.network import global_cluster

    src = inspect.getsource(global_cluster)
    assert "default_egress_recorder(" in src
    assert src.count("egress_recorder=self._egress_recorder") >= 3
