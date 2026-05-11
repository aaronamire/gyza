# Gyza wire protocol — consolidated reference

> **Purpose.** Pre-spec artifact for §C1. Single document that
> consolidates every wire-visible format in the v1 protocol: gRPC
> services and messages, libp2p stream protocols, gossipsub topics,
> DHT key namespaces, canonical-bytes routines, message-bus types.
> The TLA+ spec uses this as the lexicon of "what's on the wire" so
> formalization references concrete byte-level definitions.
>
> **Scope.** v1 protocol as it exists at end of Session 17 (commit
> 481300e). vNext wire formats are a superset / replacement;
> documented separately when vNext starts.

---

## 1. Identity and addressing

### 1.1 Compositor pubkey

Ed25519 public key, 32 bytes. Hex-encoded (lowercase, 64 chars) when
serialized to wire fields. Derived from the master seed at
`~/.gyza/compositor.key` via HKDF (see INV-ID-2). NOT the master seed
bytes directly.

### 1.2 Agent pubkey

Ed25519 public key, 32 bytes. Hex-encoded. HKDF-derived from the
compositor seed per agent_id (INV-ID-3). Distinct from the compositor
pubkey.

### 1.3 libp2p PeerID

Standard libp2p multihash derived from the compositor signing key.
Base58-encoded on the wire. Format: `12D3KooW...` (Ed25519 PeerIDs
in libp2p start with `12D3`).

PeerID ↔ compositor pubkey is bijective (INV-ID-4).

### 1.4 Multiaddrs

Standard libp2p multiaddr format. Example:
`/ip4/127.0.0.1/udp/7749/quic-v1/p2p/12D3KooWAbc...`

QUIC v1 is the default transport (see `host.NewHost` config).

---

## 2. Canonical bytes — three serialization conventions

The protocol uses **three** distinct canonical-bytes routines.
Mixing them is a load-bearing bug class (see Session 12 narrative).

### 2.1 Canonical JSON (ICP envelopes)

**Producer:** `gyza/icp.py::_payload_bytes`
**Bytes:** UTF-8, sorted keys, no whitespace, omits the `signature`
field of the envelope.

**Used by:**
- ICP envelope signing/verifying (INV-ICP-2, INV-ICP-3)
- `envelope_hash` = BLAKE3 hex of these bytes (INV-ICP-6)

**Python:** `json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")`

### 2.2 Deterministic protobuf (capability protocol)

**Producer:**
- Go: `proto.MarshalOptions{Deterministic: true}.Marshal(m)`
- Python: `m.SerializeToString(deterministic=True)`

**Used by:**
- AttestationBody signing (INV-ATT-1, INV-ATT-7)
- ResponseBody signing (INV-ATT-11)
- ChallengeBody signing (INV-ATT-9)

**Critical:** Python and Go produce byte-identical output IFF both
use the same proto file and the same flag. This is why the
attestation_adapter uses `pb.AttestationBody` directly rather than
reimplementing canonicalization.

### 2.3 BLAKE3 hashing

**Producer:** `blake3.blake3(bytes).hexdigest()` or `.digest()`.

**Used by:**
- ICP envelope hash (canonical-JSON input)
- AttestationBody hash (deterministic-protobuf input)
- LSH bucket plane seed material
- HKDF-derived agent seeds

256-bit output. Hex form is 64 chars lowercase; raw form is 32 bytes.

---

## 3. gRPC services (over Unix socket)

The daemon exposes its API over a Unix domain socket at
`~/.gyza/netd.sock` by default. Six services:

### 3.1 NodeService

```
rpc GetNodeInfo(Empty)  returns (NodeInfo);
rpc GetStatus(Empty)    returns (NodeStatus);
```

Messages:
- `NodeInfo { peer_id, compositor_pubkey, listen_addrs[], gyza_version }`
- `NodeStatus { connected_peers, dht_routing_table_size, nat_traversal_available, observed_addr, uptime_seconds }`

### 3.2 DiscoveryService

```
rpc PublishAgent(AgentAdvertisement)     returns (PublishResult);
rpc FindAgents(AgentQuery)               returns (stream AgentAdvertisement);
rpc UnpublishAgent(UnpublishRequest)     returns (Empty);
```

Messages:
- `AgentAdvertisement { agent_pubkey, compositor_pubkey, capability_manifest_hash, specialization_embedding (bytes — float32[384] little-endian), lsh_bucket (server-computed), attestation_tier, reputation_score, compute_credit_balance, last_seen, ttl_seconds, gyza_version, multiaddrs[] }`
- `AgentQuery { query_embedding (bytes — f32[384] LE), k, min_tier, min_reputation }`
- `UnpublishRequest { agent_pubkey, compositor_pubkey, signature }`

**Invariants:** INV-DHT-6 (server recomputes lsh_bucket),
INV-ATT-18 (verify-on-fetch at min_tier ≥ 3).

### 3.3 PeerService

```
rpc Connect(ConnectRequest)        returns (ConnectResult);
rpc Disconnect(DisconnectRequest)  returns (Empty);
rpc ListPeers(Empty)               returns (PeerList);
rpc GetPeerInfo(PeerInfoRequest)   returns (PeerInfo);
```

### 3.4 MessageService

```
rpc Send(SendRequest)             returns (SendResult);
rpc Broadcast(BroadcastRequest)   returns (BroadcastResult);
rpc Subscribe(SubscribeRequest)   returns (stream IncomingMessage);
```

Messages flow over the libp2p `/gyza/message/1.0.0` protocol (§4.1).
The gRPC layer is the Python ↔ Daemon control plane; libp2p is the
peer-to-peer data plane.

### 3.5 GossipService

```
rpc JoinProject(JoinProjectRequest)              returns (JoinProjectResult);
rpc LeaveProject(LeaveProjectRequest)            returns (Empty);
rpc PublishDelta(PublishDeltaRequest)            returns (PublishDeltaResult);
rpc SubscribeDeltas(SubscribeDeltasRequest)      returns (stream BlackboardDelta);
rpc ListProjects(Empty)                          returns (ProjectList);
```

Topic names: `/gyza/project/{project_id}/blackboard` (§5.1).

### 3.6 DHTService

```
rpc PutValue(DHTRecord)  returns (DHTResult);
rpc GetValue(DHTKey)     returns (DHTRecord);
```

Raw key/value put/get for callers that want direct DHT access. Used
by `cap.publish_attestation` / `cap.fetch_attestation` indirectly via
CapabilityService.

### 3.7 CapabilityService

```
rpc IssueChallenge(IssueChallengeRequest)               returns (Challenge);
rpc VerifyResponse(VerifyResponseRequest)               returns (VerifyResponseResult);
rpc PublishAttestation(AttestationCert)                 returns (PublishAttestationResult);
rpc FetchAttestation(FetchAttestationRequest)           returns (AttestationCert);
rpc VerifyAttestation(AttestationCert)                  returns (VerifyAttestationResult);
rpc RequestAttestation(stream AttestationApplicantFrame) returns (stream AttestationDaemonFrame);
```

The bidi-stream `RequestAttestation` is the Session 13 Python ↔
Daemon bridge for cross-network Tier-3 attestation (§4.2 / §INV-CAPBRIDGE-*).

Messages (capability):
- `Challenge { body: ChallengeBody, challenger_signature_hex }`
- `ChallengeBody { challenge_id, applicant_pubkey, challenger_pubkey, task_ids[], issued_at_ns, expires_at_ns, nonce_hex }`
- `ChallengeResponse { body: ResponseBody, applicant_signature, proposed_attestation_body }`
- `ResponseBody { applicant_pubkey, challenger_pubkey, challenge_id, completed_at_ns, task_results[] }`
- `TaskResult { task_id, output_json (bytes), icp_payload_bytes (bytes), icp_signature_hex, icp_agent_pubkey_hex, duration_ms }`
- `AttestationBody { applicant_pubkey, issued_at_ns, expires_at_ns, tier_granted, challenge_task_ids[] }`
- `CoSignature { validator_pubkey, signature (bytes), signed_at_ns }`
- `AttestationCert { body: AttestationBody, co_signatures[] }`

---

## 4. libp2p stream protocols

Direct peer-to-peer streams. Each protocol carries length-prefixed
binary frames.

### 4.1 `/gyza/message/1.0.0`

**Purpose:** Generic application-layer messages between peers.
Used by Python `NetdClient.send_message` → daemon → libp2p stream.

**Wire format:**
```
[uvarint message_type_len][message_type bytes][uvarint payload_len][payload bytes]
```

`message_type` is a UTF-8 string namespace identifier (e.g.
`ledger.entry.earner_signed`); see §6.

**Implementation:** `netd/internal/message/message.go`.

### 4.2 `/gyza/capability-challenge/1.0.0`

**Purpose:** Tier-3 attestation challenge-response between validator
and applicant. 3 frames per stream (INV-ATT-13, INV-CAPSTREAM-*).

**Wire format:** Each frame is `[uvarint_len][marshaled_proto]`.

```
Frame 1 (validator → applicant): Challenge (det-marshal pb.Challenge)
Frame 2 (applicant → validator): ChallengeResponse
Frame 3 (validator → applicant): VerifyResponseResult
```

**Stream lifetime:** `StreamTimeout = 120 s` (INV-CAPSTREAM-3).
Applicant identity from `stream.Conn().RemotePeer()` (INV-CAPSTREAM-1),
not from a wire field.

**Implementation:** `netd/internal/capability_stream/capability_stream.go`.

---

## 5. gossipsub topics

Topic names are interpolated identifiers. The daemon validates
`project_id` to prevent topic-namespace collisions (INV-GOSS-1 area).

### 5.1 `/gyza/project/{project_id}/blackboard`

**Purpose:** Per-project blackboard delta gossip.

**Payload:** Marshaled `BlackboardDelta` proto:
```
BlackboardDelta {
  sender_compositor_pubkey
  sender_sig                    (signs over canonical-marshal of body)
  hlc_l, hlc_c                  (sender's HLC at delta-creation)
  sender_seq                    (monotonic per-sender, dedup key)
  oneof body {
    intent          IntentRecord
    work_item       WorkItemRecord
    claim           ClaimUpdate
    completion      CompletionRecord
  }
}
```

**Dedup:** Receivers track `(sender_compositor_pubkey, sender_seq)`
pairs. Duplicate (sender, seq) → ignored (INV-GOSS-1).

**Signature:** Sender signs over the deterministic-marshal of the
inner body. Receivers verify before applying (INV-GOSS-5).

**Project ID constraints:** No `/`. UTF-8. Length-bounded. See
`gossip.ValidateProjectID`.

### 5.2 `/gyza/relays`

**Purpose:** Global relay registry. Each relay-capable node appends
its `RelayEntry` to the singleton `RelayList` record.

**Storage:** Actually a DHT record at key `/gyza/relays`, not a gossip
topic. Listed here because operationally adjacent.

---

## 6. Message-bus types (MessageService payloads)

Carried over `/gyza/message/1.0.0`. Message types are UTF-8 strings
matched against subscription filters. The daemon routes
incoming messages to subscribed Python clients by message_type.

### 6.1 Settlement messages (`ledger.*`)

| message_type | Payload (JSON) | Direction | Handler |
|---|---|---|---|
| `ledger.entry.earner_signed` | `{entry, earner_signature, envelope_hash}` | earner → payer | `_handle_earner_signed` (INV-SETTLE-1..4) |
| `ledger.entry.payer_cosigned` | `{entry, payer_signature, earner_signature}` | payer → earner | `_handle_payer_cosigned` (INV-SETTLE-5) |
| `ledger.reconcile.request` | `{request_id, since_timestamp_ns, since_entry_id, max_entries, for_peer}` | requester → responder | `_handle_reconcile_request` (INV-SETTLE-8..11) |
| `ledger.reconcile.response` | `{request_id, entries[], has_more, from_compositor, error}` | responder → requester | `_handle_reconcile_response` (INV-SETTLE-9) |

Constants live in `gyza/economy/settlement.py:122-125`.

### 6.2 Other namespaces

Phase 3 reserves the namespaces `gyza.*`, `gossip.*`, `application.*`
for future use. Currently only `ledger.*` is in active production.

---

## 7. DHT key namespaces

Kademlia DHT records under three key shapes:

| Key shape | Record type | Source |
|---|---|---|
| `/gyza/agents/{lsh_bucket_hex}` | `AgentBucket` (list of `AgentAdvertisement`) | `PublishAgent` |
| `/gyza/attestations/{compositor_pubkey_hex}` | `AttestationCert` | `PublishAttestation` |
| `/gyza/relays` | `RelayList` (singleton record) | `PublishRelay` |

**Validation:** `gyzaValidator.Validate` dispatches by key prefix
(INV-DHT-2). Each record type has its own well-formedness +
domain-specific checks (INV-ATT-16 for attestations).

**Selection on multiple values:** `gyzaValidator.Select` picks the
record with highest `last_updated_ns`; ties on byte-comparison
(INV-DHT-5).

**Size bound:** All records ≤ `MaxBucketSize = 1 MiB` (INV-DHT-3).

**`lsh_bucket_hex`:** 16-char zero-padded hex of the 64-bit LSH
bucket id (`netd/internal/dht/dht.go::AgentDHTKey`).

---

## 8. LSH (Locality-Sensitive Hashing) for discovery

The discovery layer hashes specialization embeddings into 64-bit
buckets for routing. Cross-language compatibility is load-bearing.

### 8.1 Parameters

- Embedding dim: 384 (INV-X-6)
- LSH bit width: 64 (INV-DHT-7)
- Planes generated by `scripts/generate_lsh_planes.py`, seeded
  deterministically so Python and Go agree byte-for-byte.

### 8.2 Hash function

For each of 64 planes:
- Plane `p_i` is a 384-dim float32 vector (random hyperplane).
- Bit `i` of bucket = `sign(dot(embedding, p_i))`.
- Pack 64 bits into uint64.

### 8.3 Neighbor search

`FindAgents` enumerates Hamming-neighbors of the query bucket up to
radius 2. Total buckets queried: 1 + 64 + (64*63/2) = 2017 (INV-DHT-7).

---

## 9. Envelope and chain encodings

ICP envelopes are JSON-canonical for cryptographic ops, but stored
in a SQLite envelope log on the blackboard (INV-BB-5).

### 9.1 Envelope dict shape

```
{
  envelope_id: uuid (uuid7),
  agent_pubkey: hex,
  output_hash: BLAKE3 hex of {"text": output_text} canonical-JSON,
  parent_envelope_hashes: [hex, ...],
  action_id: uuid,
  hlc: [l, c],
  timestamp_ns: int,
  metadata: dict (free-form),
  signature: ed25519 hex of BLAKE3({_payload_bytes(env without signature)})
}
```

### 9.2 envelope_hash

`BLAKE3(_payload_bytes(env)).hexdigest()` where `_payload_bytes` is
canonical-JSON minus the `signature` field (INV-ICP-6).

This is the value referenced from parent_envelope_hashes and from
settlement entries (`envelope_hash` field).

---

## 10. Cross-language compatibility summary

The single most important wire-protocol property: Python and Go
must produce byte-identical outputs for the SAME canonical-bytes
operation on the SAME logical input. The matrix:

| Operation | Python implementation | Go implementation | Match? |
|---|---|---|---|
| ICP envelope canonical JSON | `_payload_bytes` (json.dumps sorted) | n/a — Go doesn't author ICP envelopes today | n/a |
| ICP envelope BLAKE3 hash | `blake3.blake3(...)` | `blake3.Sum256(...)` (validator-side) | YES — `_payload_bytes` produces the bytes Go hashes |
| AttestationBody canonical bytes | `pb.AttestationBody.SerializeToString(deterministic=True)` | `proto.MarshalOptions{Deterministic: true}.Marshal(body)` | YES (Session 14 fix) |
| ResponseBody canonical bytes | same | same | YES |
| ChallengeBody canonical bytes | same | same | YES |
| LSH bucket | `gyza.demand::LSHIndex.hash` | `netd/internal/dht::LSHIndex.Hash` | YES (shared plane seed) |
| Ed25519 sign / verify | `cryptography.hazmat.primitives.asymmetric.ed25519` | `crypto/ed25519` | YES (RFC 8032 standard) |
| BLAKE3 hash | `blake3` PyPI package | `github.com/zeebo/blake3` | YES (standard) |

**Trip-wires from past sessions:**
- Session 12 narrative: Python JSON-canonical and Go det-protobuf
  produce DIFFERENT bytes. Don't mix.
- Session 13 narrative: the attestation adapter reuses
  `gyza.icp._payload_bytes` exactly so canonical-JSON bytes match
  what the runner signed. Don't re-implement.
- Session 14 narrative: protobuf default-value handling differs
  between Python and Go in some cases; explicitly setting fields to
  zero rather than omitting avoids edge cases.

---

## 11. Version, evolution, compatibility

### 11.1 Protocol version markers

- libp2p protocol IDs include `/1.0.0` suffix. Bumping is a hard
  break.
- DHT key prefix `/gyza/1.0` segregates Gyza records from public
  IPFS records.
- gossipsub topic naming includes `/gyza/project/{id}/blackboard`
  with no version marker; future evolution may add a `/v2` segment.

### 11.2 Forward-compatibility rules (per Session 17 vNext commitment)

Going forward, new wire-format additions MUST:

1. **Add new protobuf fields with reserved tags.** Never reuse tag
   numbers; never remove fields. Protobuf reserved-field discipline.
2. **Add new gRPC methods, never modify existing signatures.**
   Methods can be additively introduced; old methods stay until v1
   sunset (per §8 migration mechanics).
3. **Add new libp2p protocol IDs for new wire shapes.** Never modify
   the wire shape of an existing protocol ID; cut a new ID (e.g.,
   `/gyza/capability-challenge/2.0.0`) and run both side-by-side.
4. **Add new message_type namespaces for new bus types.** Never
   change the payload shape of an existing message_type.
5. **Add new DHT key prefixes for new record types.** The validator's
   prefix dispatch handles them cleanly.

These rules let v2 daemons coexist with v1 daemons during the 18–36
month migration (INV-X — informal; will become formal in vNext spec).

---

## 12. Quick-reference table for §C1 spec writers

When writing TLA+ for component X, the relevant wire shapes are:

| Component | gRPC | libp2p stream | Gossipsub | DHT key | Bus types |
|---|---|---|---|---|---|
| Discovery | DiscoveryService | none | none | `/gyza/agents/*` | none |
| Settlement | (read via SubscribeMessages) | `/gyza/message/1.0.0` | none | none | `ledger.*` (§6.1) |
| Blackboard / gossip | GossipService | none | `/gyza/project/{id}/blackboard` | none | none |
| Capability (in-process) | CapabilityService (synchronous methods) | none | none | none | none |
| Capability (cross-network) | RequestAttestation bidi (CapabilityService) | `/gyza/capability-challenge/1.0.0` | none | none | none |
| Attestation publish/fetch | CapabilityService.Publish/Fetch | none | none | `/gyza/attestations/*` | none |
| Relay | none directly | n/a | none | `/gyza/relays` | none |

---

## How to use this document

For §C1 (TLA+ spec writing):

1. When a spec module references a wire-visible value, link to the
   specific subsection here. Spec readers should be able to navigate
   from a TLA+ constant to its byte-level definition.
2. When the spec catches a wire-format ambiguity (e.g., "what's the
   canonical-bytes routine for this type?"), the answer is here.
   If not, add it before formalizing.
3. The cross-language compatibility table (§10) is the authoritative
   list of "byte-for-byte equivalent" claims. Each row should become
   an explicit `THEOREM` in the cross-language verification spec.

For migration work (vNext):

1. Section 11.2 (forward-compatibility rules) is the operational
   discipline every wire-touching change must follow.
2. vNext adds new wire formats (typed channels, distributed logs,
   etc.); they're additive on top of this v1 layer with new
   protocol IDs / gRPC methods / message types.
