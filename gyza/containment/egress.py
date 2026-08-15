"""H3 — classifying a send by what is on the other side of it.

WHY THIS MODULE EXISTS, AND WHAT IT CORRECTS.

`research/HARM_MODEL_DRAFT.md` §H3 enumerates "external network sends" as an
irreversibility sub-class and cites four sites: `publish_agent`, `send_message`,
`publish_delta`, `publish_attestation`. Its stated reason is that such a send
"leaves the modeled system entirely", so no invariant and no detector can bound
its consequence -- the C15 boundary.

**All four of those sites are mesh-INTERNAL.** `send_message` writes to a libp2p
`peer_id`, which is another `gyza-netd`. `publish_agent` and
`publish_attestation` are DHT puts under `/gyza/...`. `publish_delta` is
gossipsub on a Gyza topic. Every one of them lands on a node that runs this same
software, keeps its own provenance chain, and applies its own gate. They are
FEDERATION, not exit.

So C15's boundary is a property of DEPLOYMENT TOPOLOGY, not a law. The set of
effects that leave modelled state SHRINKS as the mesh grows, because more
destinations come to have a model. That makes H3 the only declared quantity in
this harm model that gets *better* with scale -- every other one worsens.

THE CLASSIFICATION IS THREE-WAY, NOT TWO, and the middle class is the point:

  ATTESTED_PEER      the destination presented a verifiable attestation. Its own
                     gate applies and its actions carry provenance, so the
                     effect stays inside modelled state.
  UNATTESTED_PEER    speaks the Gyza protocol, but nothing vouches for it. It is
                     protocol-internal and NOT contained: a rogue node runs
                     whatever gate it likes.
  OUTSIDE_PROTOCOL   leaves the protocol entirely (an HTTP fetch, sandbox egress
                     under `allowed_hosts`). Genuinely irreversible, genuinely
                     unmodellable after emission.

H3 measures `UNATTESTED_PEER + OUTSIDE_PROTOCOL`. Excluding `ATTESTED_PEER` is
what makes the quantity shrink as the mesh grows -- and it moves H3's strength
ONTO THE ATTESTATION TIER, which is a real dependency and is stated here rather
than hidden: if an agent can get a rogue node attested, it exfiltrates through
it and this bound is worth nothing.

NO BOUND IS DECLARED. The quantity is measured and left unbounded on purpose.
`H1_credits` was retired because 100 was declared without measuring the
attainable range and then refused every real model's first action; standing rule
#4 has failed four times. A level here comes after the measurement, not before.
"""
from __future__ import annotations


class EgressClass:
    """String constants, not an Enum, because these are persisted verbatim in
    `blackboard.egress_log` and read back by name. An Enum would tempt a rename
    and a rename would silently reclassify history."""

    ATTESTED_PEER = "ATTESTED_PEER"
    UNATTESTED_PEER = "UNATTESTED_PEER"
    OUTSIDE_PROTOCOL = "OUTSIDE_PROTOCOL"

    ALL = frozenset({ATTESTED_PEER, UNATTESTED_PEER, OUTSIDE_PROTOCOL})

    #: What H3 counts. `ATTESTED_PEER` is deliberately absent.
    MESH_EXIT = (UNATTESTED_PEER, OUTSIDE_PROTOCOL)


def classify_peer(peer_id: str, attested_peers: "frozenset[str] | None") -> str:
    """Classify a send to a protocol peer.

    FAILS TOWARD `UNATTESTED_PEER`. `attested_peers=None` means "no attestation
    source is wired", which is exactly the state in which nothing vouches for
    the destination -- so the honest reading is unattested, not attested. An
    absent attestation source is not a passing attestation, the same way an
    absent policy is not a permissive policy (`guardconfig.py:169`).
    """
    if attested_peers and peer_id in attested_peers:
        return EgressClass.ATTESTED_PEER
    return EgressClass.UNATTESTED_PEER


class EgressRecorder:
    """Injected into send paths so they can record without importing storage.

    `netd_client` is a gRPC client and must not learn what a blackboard is; the
    settlement service takes its harm guard the same way. A `None` recorder
    means "not wired", and the send still happens -- this is a MEASUREMENT
    surface, not a gate. When a bound is declared, the gate goes at the same
    call site and the recorder becomes its measurand.
    """

    def __init__(self, blackboard, attested_peers: "frozenset[str] | None" = None):
        self._bb = blackboard
        self._attested = attested_peers

    def peer_send(self, channel: str, peer_id: str, byte_count: int) -> str:
        cls = classify_peer(peer_id, self._attested)
        self._bb.record_egress(cls, channel, peer_id, byte_count)
        return cls

    def outside_send(self, channel: str, destination: str,
                     byte_count: int) -> str:
        self._bb.record_egress(EgressClass.OUTSIDE_PROTOCOL, channel,
                               destination, byte_count)
        return EgressClass.OUTSIDE_PROTOCOL


__all__ = ["EgressClass", "EgressRecorder", "classify_peer"]
