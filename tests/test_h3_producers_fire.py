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


def test_OUTSIDE_PROTOCOL_producer_is_the_inference_boundary():
    """Defect 3, RESOLVED -- and resolved BY the check that recorded it.

    This test previously asserted `outside_send` had NO caller, with the note
    that it "FAILS THE DAY SOMEONE ADDS ONE, which is the point". On
    2026-08-19 it did exactly that, naming `runner.py`, when the Anthropic
    executor's egress was wired. The check worked as designed and is inverted
    here rather than deleted: the producer must EXIST and must be the
    inference boundary, so H3's declared measurand
    (`UNATTESTED_PEER + OUTSIDE_PROTOCOL`) is no longer broader than what it
    can observe.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "gyza"
    hits = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if p.name != "egress.py" and ".outside_send(" in p.read_text()
    ]
    assert hits == ["runner.py"], (
        f"expected the inference boundary to be OUTSIDE_PROTOCOL's only "
        f"producer; got {hits}. A new external-send site must be classified "
        "deliberately, not inherit this one's justification.")


def test_sandbox_grants_are_actually_RECORDED_end_to_end(db):
    """The hollow argument, closed.

    `run_sandboxed` accepted `egress_recorder` and NOTHING EVER PASSED IT --
    `make_sandboxed_executor` had no such parameter -- so the UNBOUNDED_GRANT
    branch never fired. The standing claim that external network "is covered
    by the grant" was therefore hollow: the grant was not recorded either, and
    a network-granted agent had unbounded unobservable egress that nothing
    counted.
    """
    from gyza.containment.gyza_model import mesh_exit_sends_since
    from gyza.sandbox.config import SandboxConfig
    from gyza.sandbox.executor import make_sandboxed_executor

    rec = default_egress_recorder(db)
    ex = make_sandboxed_executor(
        "gyza.runner:make_mock_executor", init_kwargs={"response": "hi"},
        config=SandboxConfig(requires_network=True), egress_recorder=rec)
    try:
        ex("probe", {})
    except Exception:                                        # noqa: BLE001
        pass          # bwrap may be unavailable; the GRANT is recorded first
    bb = Blackboard(db)
    assert bb.count_grants_since(0) == 1
    # A GRANT IS A DIFFERENT UNIT and must never enter the send count.
    assert mesh_exit_sends_since(bb, 0) == 0
    row = sqlite3.connect(db).execute(
        "SELECT byte_count FROM egress_log").fetchone()
    assert row[0] is None, "unknown bytes must be NULL, never 0"


def test_a_sandbox_WITHOUT_network_records_no_grant(db):
    """The counter-metric: the recorder must not fire on every sandbox run,
    or the count measures sandbox usage rather than network exposure."""
    from gyza.sandbox.config import SandboxConfig
    from gyza.sandbox.executor import make_sandboxed_executor

    rec = default_egress_recorder(db)
    ex = make_sandboxed_executor(
        "gyza.runner:make_mock_executor", init_kwargs={"response": "hi"},
        config=SandboxConfig(requires_network=False), egress_recorder=rec)
    try:
        ex("probe", {})
    except Exception:                                        # noqa: BLE001
        pass
    assert Blackboard(db).count_grants_since(0) == 0


def test_production_sandbox_paths_supply_a_recorder():
    """cli.py builds one recorder and passes it at every sandboxed site."""
    import inspect

    from gyza import cli

    src = inspect.getsource(cli)
    assert "default_egress_recorder()" in src
    assert src.count("egress_recorder=_egress") >= 3


def test_UNBOUNDED_GRANT_producer_exists_and_is_the_sandbox():
    """The counterpart: a grant IS produced, and from exactly one place.

    If a second appears, the 'different unit' argument that keeps grants out
    of the send count has to be re-checked at the new site too.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "gyza"
    hits = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if p.name != "egress.py"
        and ".unbounded_grant(" in p.read_text()
    ]
    assert hits == ["sandbox/runner.py"], hits


def test_only_peer_addressed_channels_are_ever_attestable():
    """The CEILING on H3's headline property, as a check rather than prose.

    "The only declared quantity that shrinks as the mesh grows" is true of
    `send_message` alone. DHT puts and gossip fan-out have no single
    destination to attest AT SEND TIME, so attestation coverage can never move
    them out of the exit count.
    """
    from gyza.containment.egress import is_attestable_channel

    assert is_attestable_channel("send_message:settle")
    assert is_attestable_channel("send_message")
    for fanout in ("publish_delta", "publish_agent", "publish_attestation",
                   "inference:claude-sonnet-4-5", "artifact_fetch"):
        assert not is_attestable_channel(fanout), fanout


def test_channel_split_reports_the_attestable_share(db):
    """A property that applies to part of the traffic must say which part."""
    from gyza.containment.egress import is_attestable_channel

    r = default_egress_recorder(db)
    for _ in range(20):
        r.peer_send("publish_delta", "topic:p", 8)
    for _ in range(5):
        r.peer_send("send_message:settle", "peerA", 8)
    r.outside_send("inference:m", "api.anthropic.com", 8)
    r.unbounded_grant("sandbox:share-net", "x")      # different unit

    split = Blackboard(db).egress_by_channel_since(0)
    assert split == {"publish_delta": 20, "send_message:settle": 5,
                     "inference:m": 1}, split
    total = sum(split.values())
    attestable = sum(n for c, n in split.items() if is_attestable_channel(c))
    assert total == 26 and attestable == 5
    # the grant must NOT appear -- it is a different unit
    assert "sandbox:share-net" not in split
