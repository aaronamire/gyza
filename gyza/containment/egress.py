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

    #: A CAPABILITY GRANT, NOT A SEND, and the distinction is the point.
    #: `bwrap`'s network control is all-or-nothing (`sandbox/config.py:231-238`:
    #: a per-host allowlist is "DECLARED, not enforced"), so granting network to
    #: a sandboxed agent permits an UNBOUNDED number of sends to arbitrary
    #: destinations, in a subprocess with no per-send visibility.
    UNBOUNDED_GRANT = "UNBOUNDED_GRANT"

    ALL = frozenset({ATTESTED_PEER, UNATTESTED_PEER, OUTSIDE_PROTOCOL,
                     UNBOUNDED_GRANT})

    #: What H3 counts. TWO deliberate exclusions.
    #:
    #: `ATTESTED_PEER` is excluded because the effect stays in modelled state.
    #:
    #: `UNBOUNDED_GRANT` is excluded because IT IS A DIFFERENT UNIT. Folding
    #: grants into a send count would report "1" for a capability that permits
    #: arbitrarily many sends -- a category error of exactly the species this
    #: program keeps recording, and one that would fail in the reassuring
    #: direction. Grants are counted separately by `count_grants_since`.
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

    def unbounded_grant(self, channel: str, destination: str) -> str:
        """Record that a capability permitting UNCOUNTABLE egress was granted.

        `byte_count` is None, stored as SQL NULL, and that is load-bearing: 0
        would read as "zero bytes left the machine", which is false and is the
        reassuring reading. NULL says UNKNOWN, which is the truth -- nothing in
        this process can see what a sandboxed subprocess sends once its network
        namespace is shared.
        """
        self._bb.record_egress(EgressClass.UNBOUNDED_GRANT, channel,
                               destination, None)
        return EgressClass.UNBOUNDED_GRANT


def default_egress_recorder(blackboard_path: "str | None" = None,
                            attested_peers: "frozenset[str] | None" = None
                            ) -> "EgressRecorder | None":
    """Build the recorder production send paths inject.

    THIS FUNCTION EXISTS BECAUSE NOTHING BUILT ONE. `EgressRecorder` had zero
    production constructors: the parameter was threaded through `NetdClient`,
    `GossipClient`, `CapabilityClient`, `ArtifactClient` and the sandbox runner,
    and was supplied at none of the 12+ construction sites -- so every call site
    short-circuited on `if recorder is None: return` and H3 measured 0 in every
    production evaluation while being registered as a measured class. That is
    the exact condition H2_market_capital was RETIRED for, found by reading
    rather than by a failing test (research/H3_WIRING_GAP.md).

    Returns None -- meaning "unwired", the pre-existing behaviour -- when the
    blackboard cannot be opened. A measurement surface must never be the reason
    a node fails to start.

    `attested_peers` STAYS A PARAMETER AND HAS NO PRODUCTION SOURCE YET. Passing
    None makes `classify_peer` fail toward UNATTESTED_PEER, so every peer send
    counts toward H3 and the "H3 shrinks as the mesh grows" property in this
    module's header is UNREALISED until an attestation source is wired. That is
    a deliberate, documented over-count: it errs toward reporting more exit than
    there is, which is the safe direction for a bound.
    """
    try:
        from gyza.blackboard import Blackboard
        from gyza.config import load_config

        if blackboard_path is None:
            rp = load_config().resolved_paths()
            blackboard_path = rp["blackboard_db_path"]
        return EgressRecorder(Blackboard(blackboard_path), attested_peers)
    except Exception:                                        # noqa: BLE001
        import logging
        logging.getLogger("gyza.containment.egress").warning(
            "[egress] recorder not wired; H3 will measure 0", exc_info=True)
        return None


__all__ = ["EgressClass", "EgressRecorder", "classify_peer",
           "default_egress_recorder"]
