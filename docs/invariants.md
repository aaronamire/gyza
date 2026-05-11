# Gyza protocol invariants — inventory

> **Purpose.** Pre-spec artifact for §C1 (TLA+ formal protocol
> specification). This document catalogs every invariant the current
> v1 protocol code enforces, with the code site that enforces it.
> The TLA+ spec will formalize these — having them named and
> grounded first means spec writing is translation, not discovery.
>
> **Identifier convention.** `INV-<COMPONENT>-<n>`. Stable identifiers;
> if you rename or restructure, leave the IDs alone — they're
> cross-referenced from the TLA+ spec and the Coq/Lean proofs.
>
> **Code sites.** Path:line at the time of writing (Session 18, post
> commit 481300e). Re-anchor when refactoring.
>
> **Scope.** v1 protocol as it exists today. vNext invariants are
> a superset (§8) and will be catalogued separately when vNext starts.

---

## 0. Cross-cutting invariants

| ID | Statement | Code site |
|---|---|---|
| INV-X-1 | All cryptographic signing uses Ed25519 (`crypto/ed25519` Go, `cryptography` Python). | `gyza/icp.py`, `netd/internal/capability/capability.go` |
| INV-X-2 | All cryptographic hashing uses BLAKE3 over canonical bytes. | `gyza/icp.py:63,72,90`, `netd/internal/capability/capability.go` |
| INV-X-3 | Canonical JSON: sorted keys, no whitespace, UTF-8. | `gyza/icp.py::_payload_bytes` |
| INV-X-4 | Canonical protobuf: deterministic marshal (`proto.MarshalOptions{Deterministic: true}` Go; `SerializeToString(deterministic=True)` Python). | `netd/internal/capability/capability.go:599-601` |
| INV-X-5 | HLC timestamps are monotonically non-decreasing per-node and per-shared-HLC. Mutex-guarded `now()`/`recv()`. | `gyza/schema.py::HLC` |
| INV-X-6 | Embedding dimension is fixed at 384. Constant across Python and Go. | `gyza/schema.py::EMBEDDING_DIM`, `netd/internal/dht/dht.go::EmbeddingDim = 384` |

---

## 1. ICP envelope invariants (`INV-ICP-*`)

ICP envelopes are the per-action provenance primitive. Each envelope
captures an agent's signed claim about an action plus a chain to its
parent envelopes.

| ID | Statement | Code site |
|---|---|---|
| INV-ICP-1 | An envelope's `output_hash` equals `BLAKE3({"text": text})` where `text` is the executor's output text. | `gyza/runner.py::_execute`, `gyza/icp.py` |
| INV-ICP-2 | An envelope's `signature` is Ed25519 over `BLAKE3(_payload_bytes(env))` under the issuing agent's key. | `gyza/icp.py::sign_envelope`, `verify_envelope` |
| INV-ICP-3 | `_payload_bytes(env)` is canonical-JSON of the envelope dict minus the signature field. Sorted keys, no whitespace. | `gyza/icp.py::_payload_bytes` |
| INV-ICP-4 | The envelope's `agent_pubkey` matches the public key that verifies its signature. | `gyza/icp.py::verify_envelope` |
| INV-ICP-5 | A chain of envelopes verifies iff (a) every envelope in the chain individually verifies AND (b) each non-root envelope's `parent_envelope_hashes` reference an envelope in the chain by its envelope hash. | `gyza/icp.py::verify_chain` |
| INV-ICP-6 | `envelope_hash(env)` is the BLAKE3 hex of `_payload_bytes(env)`. | `gyza/icp.py::envelope_hash` |
| INV-ICP-7 | When `strict_chain_verification=True`, a missing parent envelope causes chain verification to fail. When False, it warns and proceeds. | `gyza/runner.py::_run_loop`, `gyza/blackboard.py::reconstruct_chain` |
| INV-ICP-8 | An envelope's `agent_pubkey` is the AGENT identity (HKDF-derived from compositor master seed), NOT the compositor pubkey. | `gyza/identity.py::LocalCompositor.issue_agent` |

---

## 2. Blackboard invariants (`INV-BB-*`)

The blackboard is the per-node coordination substrate. SQLite-backed
with WAL. Stores work items, claims, completions, intents, ICP envelopes.

| ID | Statement | Code site |
|---|---|---|
| INV-BB-1 | A work item is unclaimed iff `(created_at_ns + ttl_ns) > now_ns` AND no claim exists for its `work_item_id`. | `gyza/blackboard.py::get_unclaimed` |
| INV-BB-2 | At most one claim exists per `work_item_id` (DB-level UNIQUE constraint). | `gyza/blackboard.py` SQL schema |
| INV-BB-3 | At most one completion exists per `work_item_id` (DB-level UNIQUE constraint). | `gyza/blackboard.py` SQL schema |
| INV-BB-4 | Writes serialize via SQLite WAL writer lock. Reads are concurrent. | SQLite WAL semantics (no enforcement in code) |
| INV-BB-5 | The ICP envelope log is append-only. No update path. | `gyza/blackboard.py::store_envelope` |
| INV-BB-6 | `reconstruct_chain(envelope_hash)` returns the chain in topological order, root first. | `gyza/blackboard.py::reconstruct_chain` |
| INV-BB-7 | Every signed envelope is persisted before `complete_work_item` returns. | `gyza/runner.py::_complete` |

---

## 3. Runner invariants (`INV-RUN-*`)

The AgentRunner is the per-agent claim/execute/sign/release loop.

| ID | Statement | Code site |
|---|---|---|
| INV-RUN-1 | Before claiming, the runner verifies the candidate work item's ancestor chain via `verify_chain`. Configurable strict mode (`verify_chain_before_claim`, `strict_chain_verification` flags). | `gyza/runner.py::_run_loop` |
| INV-RUN-2 | A work item's reward must meet `min_reward_threshold` to be claimed. | `gyza/runner.py::_should_claim` |
| INV-RUN-3 | A work item's specialization must meet `min_similarity_threshold` (cosine sim against agent's specialization vector) to be claimed. | `gyza/runner.py::_should_claim` |
| INV-RUN-4 | On completion, the runner persists exactly one signed envelope to the local blackboard's envelope log. | `gyza/runner.py::_complete` |
| INV-RUN-5 | The runner's `_run_loop` is single-threaded per agent instance. Per-agent state is not concurrently mutated. | `gyza/runner.py::AgentRunner` (no internal parallelism) |
| INV-RUN-6 | When wired in cluster mode, the runner uses the shared HLC (`gc.shared_hlc()`) so cross-cluster claim merges share one ratcheting clock. | `gyza/runner.py::AgentRunner.__init__::hlc kwarg` |
| INV-RUN-7 | Reputation updates fire exactly once per success/failure/dispute event per agent per work_item. | `gyza/runner.py::_complete`, `_release` |

---

## 4. Settlement invariants (`INV-SETTLE-*`)

Bilateral compute-credit ledger. Per-pair state. Earner signs first;
payer cosigns second; both ledgers converge byte-identically on
applied entries.

| ID | Statement | Code site |
|---|---|---|
| INV-SETTLE-1 | Settlement entries flow `proposed → earner_signed → payer_cosigned → applied`. No state skipping. | `gyza/economy/settlement.py::submit_earned`, `_handle_earner_signed`, `_handle_payer_cosigned` |
| INV-SETTLE-2 | Earner signature verifies under the earner's compositor pubkey before payer signs. | `gyza/economy/settlement.py::_handle_earner_signed` |
| INV-SETTLE-3 | Before payer cosigns, the referenced `envelope_hash` must resolve to a known envelope in payer's local blackboard (poll up to 3 s for gossip lag). | `gyza/economy/settlement.py::_handle_earner_signed` |
| INV-SETTLE-4 | Payer cosigns only if the claimed amount is within ±20% of payer's locally-computed amount. | `gyza/economy/settlement.py::_within_tolerance` |
| INV-SETTLE-5 | Applied entries are byte-identical across earner and payer ledgers. | `gyza/economy/settlement.py::apply_cosigned_entry`, `gyza/economy/ledger.py` |
| INV-SETTLE-6 | Total credits across all bilateral pairs is conserved under any sequence of operations. (Conservation: sum of all entries' amounts across all pairs is invariant.) | Architectural; not explicitly checked at runtime |
| INV-SETTLE-7 | Reputation events fire at settlement protocol events: `success` on apply; `dispute` on protocol rejection (forged sig, envelope mismatch, amount tolerance, misroute); never on benign conditions. | `gyza/economy/settlement.py::_handle_*` |
| INV-SETTLE-8 | The reconciliation RPC uses a lex-cursor `(since_timestamp_ns, since_entry_id)` ordered by `(created_at_ns, entry_id)`. Single-ns cursor would skip entries sharing `created_at_ns`. | `gyza/economy/settlement.py::_handle_reconcile_request` |
| INV-SETTLE-9 | Reconciliation responses are only accepted if `request_id` is in `_pending_reconciles` AND `response.from_compositor` matches the peer the pending entry was registered against. Defends against cross-peer injection of forged response. | `gyza/economy/settlement.py::_handle_reconcile_response` |
| INV-SETTLE-10 | Reconciliation pagination is capped at `max_pages=50` per session and `_MAX_RECONCILE_PAGE_SIZE=2000` per page. | `gyza/economy/settlement.py::request_reconciliation` |
| INV-SETTLE-11 | The reconciliation `for_peer` field must equal the responder's pubkey; mismatches drop the request silently. | `gyza/economy/settlement.py::_handle_reconcile_request` |
| INV-SETTLE-12 | Reconciliation reputation policy: `disputed` entries → `record_dispute`; `missing_theirs`/`missing_ours` → NO reputation change (could be benign pruning / gossip lag / unsettled). | `gyza/economy/settlement.py::request_reconciliation` |

---

## 5. Attestation invariants (`INV-ATT-*`)

Proof-of-capability Tier-3 attestation. Quorum-cosigned by ≥
`MinCoSignatures = 2` distinct Tier-3 validators over identical
canonical body bytes.

### Body / cert structure

| ID | Statement | Code site |
|---|---|---|
| INV-ATT-1 | `MinCoSignatures = 2`. A valid AttestationCert has ≥ 2 distinct-validator cosignatures over the canonical body. | `netd/internal/capability/capability.go:55` |
| INV-ATT-2 | `IssuedTier = 3`. Body's `tier_granted` MUST equal this; any other value rejects. | `netd/internal/capability/capability.go:91`, `:542-544` |
| INV-ATT-3 | Body lifetime ≤ `MaxAttestationTTL = 90 days` (validator-side plausibility). | `netd/internal/capability/capability.go:74`, `:421-425` |
| INV-ATT-4 | Default cert lifetime is `DefaultAttestationTTL = 30 days` (applicant-side default). | `netd/internal/capability/capability.go:66`, `:361` |
| INV-ATT-5 | A cert verifies iff (a) `tier_granted == IssuedTier`, (b) `now ∈ [issued_at_ns, expires_at_ns)`, (c) ≥ MinCoSignatures distinct validators, (d) each cosig is a valid Ed25519 over the canonical-marshal body bytes. | `netd/internal/capability/capability.go::VerifyAttestation` |
| INV-ATT-6 | Cosignatures dedup by `validator_pubkey`. Two cosigs from the same pubkey count as one. Prevents single Tier-3 key from minting "self-attested" certs. | `netd/internal/capability/capability.go:563` |

### Multi-validator quorum (Session 14 load-bearing invariant)

| ID | Statement | Code site |
|---|---|---|
| INV-ATT-7 | Every cosig in a multi-validator quorum signs IDENTICAL canonical body bytes. Applicant proposes ONE body; each validator either signs the applicant-proposed body or authors its own (legacy path). | `netd/internal/capability/capability.go::verifyProposedAttestationBody`, `gyza/network/attestation_adapter.py::applicant_eval_session` |
| INV-ATT-8 | Validator plausibility checks on applicant-proposed body: applicant_pubkey match, tier_granted == IssuedTier, issued_at clock skew ≤ 1 h, lifetime ≤ MaxAttestationTTL, expires_at > now, challenge_task_ids match this validator's challenge. | `netd/internal/capability/capability.go::verifyProposedAttestationBody` |

### Challenge-response protocol

| ID | Statement | Code site |
|---|---|---|
| INV-ATT-9 | Challenger signs the challenge with the challenger's compositor signing key. Applicant verifies the challenger signature BEFORE running the eval. | `netd/internal/capability/capability.go::IssueChallenge`, `::VerifyChallenge` |
| INV-ATT-10 | Each Challenge carries a validator-chosen nonce. Applicant runs the eval ONCE per challenge (new workdir per challenge). Blocks replay across validators. | `netd/internal/capability_stream/stream.go::handleIncoming` |
| INV-ATT-11 | Applicant signs the ChallengeResponse body with the COMPOSITOR signing key (`LocalCompositor.sign`). Body bytes are deterministic protobuf marshal. Validator extracts applicant pubkey from libp2p RemotePeer (Noise-authenticated). | `gyza/network/attestation_adapter.py::make_eval_callback`, `netd/internal/capability_stream/stream.go` |
| INV-ATT-12 | Each TaskResult's ICP envelope is signed by the agent identity. Validator verifies the agent signature over the BLAKE3 of `IcpPayloadBytes`. Agent pubkey != applicant pubkey is ALLOWED (Session 13 relaxation). | `netd/internal/capability/capability.go::verifyTaskResult` |
| INV-ATT-13 | The wire protocol is exactly 3 frames over `/gyza/capability-challenge/1.0.0`: Challenge (validator→applicant), ChallengeResponse (applicant→validator), VerifyResponseResult (validator→applicant). Per-stream deadline `StreamTimeout = 120 s`. | `netd/internal/capability_stream/stream.go` |
| INV-ATT-14 | Each frame is `[uvarint_len][marshaled_proto]`. Mirrors `/gyza/message/1.0.0`. | `netd/internal/capability_stream/stream.go` |

### DHT publish/fetch/verify (Sessions 15–16)

| ID | Statement | Code site |
|---|---|---|
| INV-ATT-15 | `PublishAttestation` rejects certs with remaining lifetime < `MinPublishAttestationLifetime = 24 h`. | `netd/internal/dht/dht.go:836-841` |
| INV-ATT-16 | `gyzaValidator.Validate` rejects AttestationCert records past `ExpiresAtNs + AttestationExpiryGrace = 5 min`. Runs at PutValue (storage refusal) and on incoming GetValue records (fetch-side rejection). | `netd/internal/dht/dht.go:175-181` |
| INV-ATT-17 | Cert DHT key is `/gyza/attestations/{applicant_compositor_pubkey_hex}`. One cert per compositor. | `netd/internal/dht/dht.go::AttestationDHTKey` |
| INV-ATT-18 | Verify-on-fetch: `FindAgents(min_tier ≥ IssuedTier)` runs each candidate ad's `compositor_pubkey` through `AttestationVerifier.Verify`. Ads that don't verify are dropped from results. | `netd/internal/dht/dht.go::FindAgents`, `verifier.go::Verify` |
| INV-ATT-19 | Verifier cache: positive entries TTL = `min(posTTL=5m, cert.expires_at_ns − slack − now)`; negative TTL = `negTTL=30s`. Transient failures (fetch error, fetch timeout) are NOT cached. | `netd/internal/dht/verifier.go::Verify` |
| INV-ATT-20 | Verifier slack window: a cert with remaining lifetime < `expirySlack = 1 h` is rejected (negative-cached). Provides routing-horizon stability. | `netd/internal/dht/verifier.go::Verify` |
| INV-ATT-21 | Verifier single-flight per pubkey: concurrent `Verify` calls for the same pubkey share one DHT fetch. Semaphore-bounded global concurrency (`MaxInflight = 16`). | `netd/internal/dht/verifier.go::Verify` |
| INV-ATT-22 | Verifier keys by `compositor_pubkey`, NOT `agent_pubkey`. Multiple agents share one compositor and one cert. | `netd/internal/dht/dht.go::FindAgents` calling site |

### Recursive Tier-3 verification (Session 16)

| ID | Statement | Code site |
|---|---|---|
| INV-ATT-23 | `RecursiveVerifier.Verify` requires `TrustedBootstrap` non-empty. Empty bootstrap → all certs rejected (no base case for recursion). | `netd/internal/capability/recursive.go::Verify` |
| INV-ATT-24 | Each cosig's `validator_pubkey` must be either in `TrustedBootstrap` OR have a recursively-verifiable Tier-3 cert. | `netd/internal/capability/recursive.go::isTier3` |
| INV-ATT-25 | Cycle detection: a pubkey in the current recursion path is treated as non-Tier-3 (not infinite-loop, not mutually-validating). | `netd/internal/capability/recursive.go::isTier3` |
| INV-ATT-26 | Depth bound: `MaxDepth` (default 5) caps recursive cert fetches. Beyond `MaxDepth`, pubkey is rejected. | `netd/internal/capability/recursive.go::isTier3` |
| INV-ATT-27 | Substitution defense: fetched cert's `ApplicantPubkey` MUST equal the queried pubkey. Otherwise reject (malicious peer substituting a legitimate cert in response to a non-Tier-3 query). | `netd/internal/capability/recursive.go::isTier3` |
| INV-ATT-28 | Positive cache only. Negative results (no cert / verify failed / substitution) are NOT cached at the recursive layer. | `netd/internal/capability/recursive.go::isTier3` |

---

## 6. DHT invariants (`INV-DHT-*`)

Kademlia DHT for cross-cluster agent advertisement and attestation
publication. libp2p-backed.

| ID | Statement | Code site |
|---|---|---|
| INV-DHT-1 | `gyzaValidator.Validate` is called by libp2p kad-dht at both PutValue (storing) and on incoming GetValue records. Application-level signature verification happens in `FindAgents` / `VerifyAttestation`. | `netd/internal/dht/dht.go::gyzaValidator` |
| INV-DHT-2 | Record types dispatch by key prefix: `/gyza/relays` → RelayList, `/gyza/attestations/*` → AttestationCert, default → AgentBucket. | `netd/internal/dht/dht.go::gyzaValidator.Validate` |
| INV-DHT-3 | All record values ≤ `MaxBucketSize = 1 MiB`. | `netd/internal/dht/dht.go:58` |
| INV-DHT-4 | AgentBucket merge is LWW by advertisement `last_seen` per `agent_pubkey`. | `netd/internal/dht/dht.go::mergeBucket` |
| INV-DHT-5 | `gyzaValidator.Select` picks the value with highest `last_updated_ns` (LWW); ties break on byte-comparison for determinism. | `netd/internal/dht/dht.go::gyzaValidator.Select` |
| INV-DHT-6 | LSH bucket is recomputed server-side from advertisement embedding. Client-supplied `lsh_bucket` is ignored. | `netd/internal/grpc/server.go::PublishAgent`, `netd/internal/dht/dht.go::PublishAgent` |
| INV-DHT-7 | `LSHBits = 64`. `EmbeddingDim = 384`. Hamming-radius-2 neighbor search around the query bucket. | `netd/internal/dht/dht.go:46-50`, `::FindAgents` |
| INV-DHT-8 | Republish interval ≤ TTL/2 in steady state. Default `TTL = 3600s`, `interval = 1800s`. | `netd/internal/dht/dht.go::StartRepublishLoop` |
| INV-DHT-9 | Empty AgentBucket records are accepted (UnpublishAgent path leaves an empty bucket when the removed agent was the sole occupant). | `netd/internal/dht/dht.go::gyzaValidator.Validate` (default case) |
| INV-DHT-10 | Attestation certs do NOT auto-republish (no equivalent of `StartRepublishLoop`). Republish requires manual `gyza global attest --tier 3` invocation. (Acknowledged open item, §6 A6.) | n/a — absence of code |

---

## 7. Gossip / blackboard-sync invariants (`INV-GOSS-*`)

Gossipsub mesh per-project. Carries blackboard deltas (intents, work
items, claims, completions) cross-cluster.

| ID | Statement | Code site |
|---|---|---|
| INV-GOSS-1 | Sender sequence dedup at receivers. Same sender + same seq → second delta ignored. | `netd/internal/gossip` (TestSenderSeqDedupRejects) |
| INV-GOSS-2 | Delta application is idempotent. Re-applying an already-merged delta is a no-op. | `gyza/network/network_blackboard.py::_apply_delta` |
| INV-GOSS-3 | LWW on bucket-equivalent fields where applicable (e.g., claim merge under concurrent claims). | `gyza/network/network_blackboard.py` |
| INV-GOSS-4 | Eventual consistency under bounded partition: all live nodes converge on the same intent/work-item/completion state once gossip mesh reconnects. | Gossipsub semantics + idempotent apply |
| INV-GOSS-5 | Gossip deltas are signed by the sender's compositor key. Receivers verify before applying. | `gyza/network/network_blackboard.py::_apply_delta` |
| INV-GOSS-6 | When in cluster mode, the runner's HLC is the shared `gc.shared_hlc()` so cross-cluster timestamps ratchet against one clock. | `gyza/network/global_cluster.py::shared_hlc` |

---

## 8. Capability stream invariants (`INV-CAPSTREAM-*`)

libp2p protocol `/gyza/capability-challenge/1.0.0` ferrying the
attestation challenge-response between two daemons. Detailed
invariants overlap with INV-ATT-9 through INV-ATT-14; this section
is the wire-protocol perspective specifically.

| ID | Statement | Code site |
|---|---|---|
| INV-CAPSTREAM-1 | The applicant pubkey is extracted from `stream.Conn().RemotePeer()` (Noise-authenticated libp2p PeerID). NOT taken from a wire-claimed field. | `netd/internal/capability_stream/stream.go::handleIncoming` |
| INV-CAPSTREAM-2 | No kickoff frame from the applicant. Validator initiates by reading the applicant's libp2p identity. 3 frames total (Challenge / Response / VerifyResult). | `netd/internal/capability_stream/stream.go` |
| INV-CAPSTREAM-3 | Per-stream deadline `StreamTimeout = 120 s` bounds the WHOLE exchange (open + 3 frames + close). | `netd/internal/capability_stream/stream.go` |
| INV-CAPSTREAM-4 | Validator rejections on the response are wire-encoded as `VerifyResponseResult{Success=false, Error=<reason>}`. Network/IO errors close the stream silently. | `netd/internal/capability_stream/stream.go::handleIncoming` |
| INV-CAPSTREAM-5 | Applicant verifies the challenger signature (`VerifyChallenge`) BEFORE invoking the eval callback. Eval is the slow step; reject malformed challenges without burning CPU. | `netd/internal/capability_stream/stream.go::RequestAttestation` |

---

## 9. RequestAttestation bridge (gRPC bidi) invariants (`INV-CAPBRIDGE-*`)

The Python applicant adapter's gRPC bidirectional stream to the
daemon. Daemon ferries libp2p frames over gRPC.

| ID | Statement | Code site |
|---|---|---|
| INV-CAPBRIDGE-1 | Python opens the stream and sends `AttestationStartRequest{target_peer_id}` as the first frame. Any other first frame surfaces as `InvalidArgument`. | `netd/internal/grpc/server.go::RequestAttestation` |
| INV-CAPBRIDGE-2 | `target_peer_id` is validated via `peer.Decode` BEFORE opening a libp2p stream. Malformed peer IDs surface as `InvalidArgument` without dialing. | `netd/internal/grpc/server.go::RequestAttestation` |
| INV-CAPBRIDGE-3 | Every error path AFTER the bridge has sent a Challenge to Python surfaces as a final Outcome frame with `success=false, error=<reason>`. Python's read loop has uniform shape. | `netd/internal/grpc/server.go::RequestAttestation` |
| INV-CAPBRIDGE-4 | The bridge invokes the libp2p `EvalRunner` callback exactly once per attestation (contract with `capability_stream.Manager`). | `netd/internal/grpc/server.go::RequestAttestation` |

---

## 10. Identity / compositor invariants (`INV-ID-*`)

| ID | Statement | Code site |
|---|---|---|
| INV-ID-1 | The compositor master seed is stored at `~/.gyza/compositor.key` with mode 0600. | `gyza/identity.py::LocalCompositor`, `netd/internal/identity` |
| INV-ID-2 | The compositor signing key is HKDF-derived from the master seed via `_derive_seed(master, _CTX_COMPOSITOR_SEED, b"")`. The master seed bytes are NOT the signing seed. | `gyza/identity.py::LocalCompositor` |
| INV-ID-3 | Agent identities are HKDF-derived from the compositor seed via `LocalCompositor.issue_agent`. Agent keys ≠ compositor key. | `gyza/identity.py::LocalCompositor.issue_agent` |
| INV-ID-4 | The libp2p PeerID is derived from the compositor signing key via libp2p's standard derivation. PeerID ↔ compositor pubkey is bijective. | `netd/internal/identity` |
| INV-ID-5 | Capability manifests describe an agent's allowed operations (filesystem read/write paths, attestation tier, etc.) and are signed by the compositor. | `gyza/identity.py::AgentIdentity` |

---

## 11. Demand / supervisor / specialization invariants (`INV-SUPV-*`)

Per-node self-organization: DemandOracle observes bucket heat;
Supervisor spawns replicas; SpecializationTracker drifts agent
embeddings toward observed demand.

| ID | Statement | Code site |
|---|---|---|
| INV-SUPV-1 | DemandOracle.all_signals() returns per-bucket signals (deficit, heat). Polled by Supervisor on a configurable cadence. | `gyza/demand.py::DemandOracle` |
| INV-SUPV-2 | Supervisor spawns a new agent for a hot bucket iff there is no existing serving agent AND `len(roster) < max_agents`. | `gyza/supervisor.py::AgentSupervisor._tick` |
| INV-SUPV-3 | Factory exceptions during spawn are caught and logged; the supervisor does NOT crash. | `gyza/supervisor.py::AgentSupervisor._spawn` |
| INV-SUPV-4 | SpecializationTracker drifts an agent's embedding by exponentially-weighted average of recently completed work-item embeddings. Per-agent state. | `gyza/drift.py::SpecializationTracker` |
| INV-SUPV-5 | Reward inflation applies an exponential factor based on bucket deficit signal. Reward grows for under-served buckets. | `gyza/reward.py` |

---

## 12. Reputation invariants (`INV-REP-*`)

EWMA-based per-pair reputation, SQLite-persisted.

| ID | Statement | Code site |
|---|---|---|
| INV-REP-1 | Reputation outcomes: `success` = +1, `failure` = −0.5, `dispute` = −1. EWMA decay applied per update. | `gyza/economy/reputation.py::ReputationStore` |
| INV-REP-2 | Reputation is locally maintained per node; not gossiped. Each node has its own view of every other peer. | `gyza/economy/reputation.py` |
| INV-REP-3 | Reputation updates are mutex-guarded. Concurrent updates serialize. | `gyza/economy/reputation.py::ReputationStore._lock` |

---

## 13. Observability invariants (`INV-OBS-*`)

Prometheus + structlog. Default loopback bind.

| ID | Statement | Code site |
|---|---|---|
| INV-OBS-1 | Each counter/histogram is incremented at exactly one site in code. No double-counting. | `gyza/observability.py` and call sites |
| INV-OBS-2 | Metrics-server default bind is `127.0.0.1:9100`. External scraping requires explicit `addr="0.0.0.0"`. | `gyza/observability.py::start_metrics_server` |
| INV-OBS-3 | Settlement latency carrier purges entries on observation. Long-tail leaks if entries never round-trip; acceptable at Phase 3 scale. | `gyza/economy/settlement.py::observe_settlement_latency` |
| INV-OBS-4 | Failed observability imports fall back to no-op stubs (Session 9 fail-closed wrapper). Runner does not refuse to start if `prometheus_client` is missing. | Pattern documented in CLAUDE.md §14 |

---

## 14. Sandbox invariants (`INV-SAND-*`)

bwrap-based executor isolation. Session 10.

| ID | Statement | Code site |
|---|---|---|
| INV-SAND-1 | Default sandbox config: fresh net namespace, `--clearenv`, RLIMIT_AS = 2 GiB, RLIMIT_CPU = 300 s, wall-clock timeout = 120 s. | `gyza/sandbox/config.py::SandboxConfig` |
| INV-SAND-2 | bwrap argv ordering: system mounts → `/proc /dev` → `/tmp` tmpfs → user `ro_paths` → workspace. Tmpfs-before-ro_paths means tmp-rooted ro_paths land on top. | `gyza/sandbox/runner.py::_build_bwrap_argv` |
| INV-SAND-3 | Host symlinks (e.g. `/lib64` on merged-/usr distros) are reproduced as `--symlink`, NOT bound as `--ro-bind`. | `gyza/sandbox/config.py::_HostMount` |
| INV-SAND-4 | API keys reach the sandbox via `--setenv KEY VALUE`, NOT via argv. Argv is `ps`-visible to other users on the host. | `gyza/sandbox/runner.py` |
| INV-SAND-5 | Stdin/stdout protocol is 8-byte-bigendian length-prefixed JSON. Plain stream-of-JSON would be corrupted by tokenizer/SDK `print()` calls (sentence-transformers writes a load report on first import). | `gyza/sandbox/_entrypoint.py` |

---

## 15. Eval suite invariants (`INV-EVAL-*`)

Canonical capability eval suite. Session 11.

| ID | Statement | Code site |
|---|---|---|
| INV-EVAL-1 | Each prompt embeds `[GYZA_EVAL_TASK={id} NONCE={nonce}]`. Mock executor scans for the marker via `prompt.rfind`, NOT `prompt.find` — `build_enriched_prompt` prepends few-shot context containing prior tasks' markers; scanning from start would silently solve the wrong task. | `gyza/capability_eval.py`, mock-eval executor |
| INV-EVAL-2 | Each output's ICP envelope is signed by the agent identity. Verifier checks (a) `envelope.agent_pubkey == applicant`, (b) `BLAKE3({"text": canonical_text}) == envelope.output_hash`, (c) structural shape, (d) output equals `task.expected_output(workdir, nonce)`. | `gyza/capability_eval.py::verify_eval_results` |
| INV-EVAL-3 | Per-task workdir is isolated at `workdir/<task_id>/`. | `gyza/capability_eval.py::run_eval_locally` |
| INV-EVAL-4 | `WorkItem.ttl_ns = (timeout_s + 30) * 1e9`. Zero TTL immediately expires via `get_unclaimed`'s filter. | `gyza/capability_eval.py::run_eval_locally` |
| INV-EVAL-5 | `make_recording_executor` stores both `parsed` and `text`. The runner hashes `{"text": result["text"]}`; the verifier needs the parsed dict for shape checks. | `gyza/capability_eval.py::make_recording_executor` |

---

## Appendix A: invariants that are properties without code-level checks

Several invariants are protocol-level properties enforced by design,
not by runtime assertions. The TLA+ spec should formalize these
explicitly because they're load-bearing for safety/liveness proofs.

| ID | Statement | Why no runtime check |
|---|---|---|
| INV-X-A1 | Settlement conservation (INV-SETTLE-6). | Total credits across all pairs cannot be computed locally; conservation is a network-wide invariant that holds by construction (every apply mutates both sides identically). |
| INV-X-A2 | Eventual consistency (INV-GOSS-4). | Convergence under partition is a property of gossipsub + idempotent apply, not a runtime check. |
| INV-X-A3 | Sybil resistance threshold under stated assumptions. | Trust derivation property; protocol guarantees ≤ f Byzantine validators below quorum can't forge Tier-3 cert. |
| INV-X-A4 | Capability non-forgeability. | A capability claim is non-forgeable iff its supporting cert+signatures verify; protocol-level statement. |
| INV-X-A5 | Liveness under bounded partition. | Network-level property; holds by gossipsub + retry semantics. |

These five plus selected runtime invariants are the targets for §C2
(Coq/Lean formal proofs).

---

## Appendix B: invariants we explicitly do NOT enforce (open follow-ups)

The architecture deliberately leaves some invariants unenforced.
Each is documented as a CLAUDE.md trip-wire or §6 open item; the
spec should note them as "out of scope at v1" so the gaps are
visible.

| ID | Non-invariant | Why unenforced today |
|---|---|---|
| INV-X-B1 | Validator pubkeys in a cert's cosigs are themselves Tier-3 attested. | A2-library exists (`RecursiveVerifier`), not wired into `DHTAttestationVerifier`. Blocked on Foundation-configured trusted-bootstrap set. |
| INV-X-B2 | Agent pubkey in an ICP envelope is provably issued by the cert's compositor. | Capability-manifest path forwarding through the response is a documented follow-up. |
| INV-X-B3 | DHT-level record TTL is bounded by `cert.expires_at_ns − now`. | A1 publish-side floor + validator-side rejection partially mitigate; libp2p kaddht doesn't expose per-record TTL cleanly. |
| INV-X-B4 | `AgentAdvertisement.attestation_tier` from gossip / disk snapshots / non-`find_agents` paths is verified. | Only `find_agents(min_tier ≥ 3)` enforces verify-on-fetch. Other call sites inherit self-report weakness. |

---

## How to use this document

For §C1 (TLA+ spec writing):

1. Each TLA+ module formalizes the invariants from one section here.
   Settlement spec ↔ §4. Attestation spec ↔ §5. DHT spec ↔ §6.
   Etc.
2. Reference invariants by ID in TLA+ comments so the cross-reference
   trail stays grounded.
3. When the spec catches an inconsistency between two invariants, add
   an entry to Appendix B noting it OR update the code to align (with
   a session narrative).
4. Invariants from Appendix A become explicit `THEOREM` statements
   in TLA+ — they're the load-bearing properties.

For ongoing engineering:

- When adding a new invariant to code, append it here with a new ID.
- When changing the meaning of an existing invariant, update the
  entry and bump the session narrative.
- This document is the authoritative inventory; the TLA+ spec is the
  formalization.
