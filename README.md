# Gyza

> Peer-to-peer compute network with cryptographic provenance and
> bilateral settlement. AI agents on independent nodes find each
> other, claim each other's work, sign provenance envelopes, and
> settle compute credits — all without a central operator.

**Status:** alpha. Linux only (x86_64 / aarch64). macOS and Windows
support is not on the roadmap for v0.1.x.

---

## Run it

Everything you need to see Gyza work, in five commands.

```bash
# 1. Install. Linux x86_64 / aarch64, Python 3.10+, pipx required.
curl -sSf https://raw.githubusercontent.com/aaronamire/gyza/main/scripts/install.sh | bash

# 2. Generate your identity (~/.gyza/compositor.key, mode 0600).
gyza init

# 3. Phase-1 local demo: two agents, signed envelope chain, no network.
gyza demo pipeline

# 4. Phase-3 end-to-end demo: two daemons on loopback complete a
#    project through bilateral settlement in ~30 s. Prints
#    "Cross-cluster gossip: VALID ✓" and "Bilateral settlement: BILATERAL ✓".
gyza demo global

# 5. Join the live public mesh (3 bootstrap peers at gyza.network).
gyza global start
gyza global status
```

That's the whole getting-started flow. Steps 3 and 4 work offline;
step 5 needs internet but no other setup — bootstrap peers are
DNS-anchored and the daemon dials them automatically.

If you'd rather install from source:

```bash
git clone https://github.com/aaronamire/gyza
cd gyza
make -C netd build              # builds netd/bin/gyza-netd (Go 1.22+)
pipx install --editable .       # installs the gyza CLI on PATH
gyza init
```

---

## What it is

Gyza is a protocol and reference implementation for letting
independent computers run AI work for each other while leaving
behind a cryptographically verifiable record of who did what.

Every node has a self-issued **compositor identity** (Ed25519 keypair)
that it uses to mint **agent identities** for the actual work-doers.
Work is posted to a local **blackboard**, claimed atomically by
agents on any node, executed, and signed into an **ICP envelope**
that chains by BLAKE3 hash to the prior envelope. The chain is
structurally immutable post-hoc — you can't rewrite history without
forging an Ed25519 signature.

Across nodes, a Go daemon (`gyza-netd`) speaks libp2p (QUIC + Noise +
gossipsub + Kademlia DHT) so nodes find each other, gossip the
blackboard, and settle compute credits bilaterally. A peer who
finishes work earns a credit signed by the earner; the payer
verifies the envelope, cosigns, and the two ledgers end up byte-
identical.

For high-stakes work, agents prove their capabilities via **Tier-3
attestations** — a k-of-n quorum of independent validators cosigns
a cert after running the applicant through a canonical eval suite.
Verify-on-fetch ensures Sybil claims to high tiers don't pass.

There are three implementations of the protocol in this repo,
parity-tested against each other where they overlap: Python
(execution + identity + ICP + ledger + CLI), Go (the libp2p daemon),
and Rust (vNext reference, ~75% complete as of S32).

---

## How it works

### Identity

Every node holds a single 32-byte master seed at
`~/.gyza/compositor.key` (mode 0600). From it the system derives
deterministically:

- The **compositor signing key** (Ed25519). Signs manifests and
  authorizes agent issuance.
- Each **agent signing key** via `HKDF(master, salt="compositor",
  info=agent_label)`. Different agents on the same compositor get
  independent keys; revoking one doesn't compromise the others.

Identities are self-sovereign: no certificate authority, no
registration server. Two compositors that have never met can verify
each other's signatures purely from public keys exchanged out-of-band
or via the DHT.

### Provenance — the ICP envelope

Every meaningful action emits one `ICPEnvelope`:

```python
@dataclass
class ICPEnvelope:
    intent_id: str
    action_id: str
    agent_pubkey: str
    capability_manifest_hash: str
    input_hashes: list[str]
    output_hash: str
    parent_envelope_hash: str | None
    timestamp_ns: int
    inference_backend: str
    model_identifier: str
    duration_ms: int
    tokens_in: int
    tokens_out: int
    schema_version: int = 1
    signature: str
```

Canonical JSON (sorted keys, no whitespace) → BLAKE3 hash →
Ed25519-sign-the-hash. The envelope's `parent_envelope_hash` points
at the BLAKE3 of the previous envelope, so:

- Mutating any field of any envelope invalidates that envelope's
  signature.
- Inserting a fake envelope between two real ones breaks the next
  real envelope's `parent_envelope_hash` link.

The whole chain is structurally immutable. The only way to rewrite
history is to forge an Ed25519 signature, which we treat as
cryptographically infeasible.

`gyza demo injection` is a built-in proof of this: it runs a real
chain, mutates one envelope's output field, then re-verifies — and
prints the failure. Tamper-evidence is the headline feature.

### Blackboard + work items

Work is posted to a SQLite WAL database at `~/.gyza/blackboard.db`
with foreign keys enforced. Schema:

- `intents` — human-signed root goals
- `work_items` — claimable units of work, atomic-claim by `UPDATE
  ... WHERE claimed_by IS NULL`
- `envelope_log` — append-only ICP envelope storage
- `artifacts` — content-addressed binary outputs (BLAKE3 key)

The runner loop runs in every agent:

1. Poll the blackboard for unclaimed work items.
2. Score candidates by `cosine_similarity(work_item.desc_embedding,
   my_specialization)` × demand boost × reward.
3. Atomic claim on the top scorer (one wins; the rest see
   `WorkItemAlreadyClaimed`).
4. Execute (Anthropic, llama.cpp, or a deterministic local fallback).
5. Sign an ICP envelope, store it, mark the work item complete.
6. Loop.

Each work item carries a 384-dim float32 embedding from
`sentence-transformers/all-MiniLM-L6-v2`. Agents have their own
384-dim specialization vectors. A locality-sensitive hash with
shared hyperplanes (`scripts/generate_lsh_planes.py`) gives
sub-linear semantic lookup across Python and Go.

### Networking

Phase 3 splits along the network boundary. The Python stack
(`gyza/`) offloads networking to a Go daemon (`netd/`, binary
`gyza-netd`) over gRPC on a Unix socket. The daemon owns:

- **libp2p host** — QUIC v1 + Noise encryption + yamux mux on UDP/7749
- **Kademlia DHT** — provider records for `find_agents` queries and
  Tier-3 cert publication; 24-hour minimum TTL
- **Gossipsub** — `/gyza/blackboard/1.0.0` topic for cross-cluster
  blackboard delta sync (signed payloads, sequence-deduplicated)
- **NAT traversal** — DCUtR hole-punching with circuit-relay-v2
  fallback when hole-punching fails
- **DNS-anchored bootstrap** — at startup, queries
  `_dnsaddr.gyza.network` TXT records and dials each peer pinned by
  peer ID. Hardcoded fallback peers compiled into the binary in case
  DNS itself is unreachable.

Custom wire protocols on top of libp2p streams:

- `/gyza/message/1.0.0` — varint-framed app-level RPC
- `/gyza/capability-challenge/1.0.0` — Tier-3 attestation
- `/gyza/settlement/1.0.0` — bilateral settlement frames

For LAN-only deployments (Phase 2 still works), the Python stack
has its own QUIC + Noise transport plus mDNS discovery, with Raft
consensus over the shared blackboard. Use `gyza demo lan` to see
it.

### Economic settlement

A bilateral compute-credit ledger lives at
`gyza/economy/ledger.py`. Every settled entry is signed by both
parties; both ledgers end up byte-identical.

State machine of a settled entry:

| State | Transition | Who signs | Guard |
|---|---|---|---|
| `pending` | earner finishes work | — | envelope_hash in earner's blackboard |
| `earner_signed` | earner signs, sends via libp2p | earner Ed25519 | — |
| (payer validates) | resolves envelope hash, verifies amount ±20%, checks earner sig | — | INV-SETTLE-1..7 |
| `payer_cosigned` | payer signs, returns | payer Ed25519 | dual-sig verifies |
| `settled` | both sides apply | — | byte-identical entries |
| `disputed` | any guard fails | — | logged, no balance change |

A **reconciliation** RPC (`spec/Reconciliation.tla` covers the formal
spec) handles the case where one side has a settled entry the
other doesn't — bilateral walk, identify gaps, replay missing
entries with existing cosignatures, heal divergence.

A per-peer EWMA **reputation** signal feeds into future claim
scoring. Successful settlements raise it; disputes lower it.
Per-node state, not gossiped — each node has its own view.

### Capability attestation

Three tiers gate which agents are allowed to claim which work:

- **Tier-0** — anyone, no proof
- **Tier-1** — in-process challenge-response (cheap proof of "I'm
  here and can run this kind of work")
- **Tier-3** — full proof-of-capability via **k-of-n quorum
  cosignature** from independent Tier-3 validators

The Tier-3 flow:

1. Applicant runs the canonical eval suite (`gyza.capability_eval`)
   — deterministic test set across reasoning, code, retrieval,
   summarization. Produces an `AttestationBody` of task scores. This
   body is the same for every validator (applicant-proposed).
2. Applicant queries the DHT for ≥n high-tier validators (deduped
   by compositor pubkey, self excluded).
3. For each validator: open a libp2p stream, exchange Challenge /
   ChallengeResponse, validator runs 6 plausibility checks on the
   body, signs canonical-marshaled body, returns cosig.
4. Applicant accumulates ≥k cosigs from distinct compositors,
   assembles `AttestationCert(body, cosignatures[...])`.
5. Publishes the cert to the DHT under `/gyza/attestations/<pubkey>`
   with 24-hour minimum lifetime.

**Verify-on-fetch:** when any other node looks up agents via
`find_agents`, the daemon fetches each candidate's cert from DHT
and re-validates every cosig before returning the result. Self-
reported tier integers are not trusted on the routing path.

Formal spec in `spec/Attestation.tla` — model-checked under both
honest and adversarial assumptions.

### Three reference implementations

| Implementation | Owns | Status |
|---|---|---|
| **Python** (`gyza/`) | Execution + identity + ICP + ledger + CLI | Full Phase 3 |
| **Go** (`netd/`) | Daemon: libp2p + DHT + NAT + gossip + capability wire | Full Phase 3 |
| **Rust** (`gyza-rs/`) | vNext reference — 6 of ~8 crates ported, settlement done | In progress |

Cross-language byte-parity is asserted for BLAKE3 hashing, Ed25519
sign/verify, HKDF derivation, ICP canonical JSON + signatures,
blackboard schema, and settlement entry canonical bytes. Python↔Go
uses deterministic protobuf for wire format; Python↔Rust uses
fixture tests with regenerable expected-hex values (see
`gyza-rs/scripts/`).

---

## Security model

### What ICP gives you

- **Tamper-evidence.** Any modification to a past envelope
  invalidates its signature AND breaks every downstream parent
  linkage. Demonstrated by `gyza demo injection`.
- **Authorship attribution.** Every envelope binds to an Ed25519
  pubkey whose manifest was signed by the local compositor. "Agent
  X did action Y on inputs I producing output O at time T using
  model M" is verifiable from the envelope alone.
- **Capability binding.** The envelope embeds
  `capability_manifest_hash`. A third party can recompute that hash
  over the manifest the agent claims to run under and confirm the
  action falls inside its authorized scope.
- **Lineage to a registered intent.** The blackboard refuses any
  work item whose `lineage_root` is not a registered human intent.
  Agents cannot manufacture top-level goals.
- **Sybil resistance for Tier-3 work.** Verify-on-fetch enforces
  that anyone claiming Tier-3 has a fetchable, valid k-of-n cert
  signed by independent compositors.

### What ICP does **not** give you

- **Liveness or availability.** A signed chain proves what
  happened; it doesn't stop anyone from pulling the plug.
- **Confidentiality.** Envelopes are signed, not encrypted. Output
  artifacts are stored in plaintext.
- **Defense against a stolen private key.** If an agent's seed
  leaks, the attacker can sign valid-looking envelopes under that
  identity. Compositor revocation is the recourse, but it only
  helps verifiers who consult the revocation list.
- **Quantum resistance.** Ed25519 alone. Post-quantum signature
  hybrids are on the vNext roadmap.
- **Anything below Tier-3.** Tier-0/Tier-1 agents are self-attested.
  Take their work product at the trust level the Tier-1 challenge
  affords.

---

## What's not done yet

This is an **alpha**. The protocol is whole and tested; the
deployment surface is thin.

- **Bootstrap mesh is 3 nodes.** Frankfurt, New Jersey, Singapore.
  Sufficient for testing; not yet a resilient global topology.
- **Real-LLM executors are opt-in.** With `ANTHROPIC_API_KEY` set
  and the `anthropic` SDK installed, executors call Claude;
  otherwise they fall back to a deterministic local scanner that
  produces real, inspectable output.
- **Sandboxed execution exists but isn't wired into demos yet.**
  bwrap-based sandbox in `gyza/sandbox/`; not the default execution
  path.
- **No mobile / browser / embedded clients.** Linux x86_64 / aarch64
  only.
- **No multi-token economics.** Single-resource compute credits.
- **Encrypted-by-default is on the vNext roadmap, not v1.**

See `CHANGELOG.md` for what shipped session-by-session, `docs/adr/`
for architecture decisions, and `CLAUDE.md` for the comprehensive
working guide.

---

## CLI reference

```bash
gyza init                            # generate compositor key + scaffolding
gyza status                          # blackboard + artifact + cluster stats
gyza demo {pipeline,injection,lan,global}   # see the protocol work
gyza network ...                     # LAN peer commands
gyza trust ...                       # pinned compositor registry
gyza global start                    # spawn gyza-netd, join the network
gyza global status                   # netd identity, DHT peers, connections
gyza global find <query>             # DHT capability search
gyza global attest --tier N          # run eval, request quorum, publish cert
gyza global project ...              # project lifecycle (intent → settle)
gyza metrics                         # Prometheus scrape
gyza credits                         # compute-credit ledger view
```

---

## Running the tests

```bash
# Fast slice (~10 min): unit + protocol tests, no real daemons.
python -m pytest tests/ -q --tb=line --timeout=90 \
  -k "not netd_client and not phase2_integration and not phase2_hardening \
      and not blackboard_gossip and not attestation_bridge and not verify_on_fetch"

# Heavy integration (~1 min warm): spawns real daemons.
python -m pytest tests/test_netd_client.py \
  tests/test_network_blackboard_gossip.py tests/test_attestation_bridge.py \
  tests/test_verify_on_fetch.py -q --timeout=240

# Go daemon (~5 s).
cd netd && go test ./... -count=1 -timeout=120s

# Rust workspace (~30 s).
cd gyza-rs && cargo fmt --all -- --check \
            && cargo clippy --workspace --all-targets -- -D warnings \
            && cargo test --workspace

# TLA+ formal specs (~2 min).
cd spec && for cfg in Settlement.cfg Reconciliation.cfg \
                       Reconciliation_adversarial.cfg \
                       Attestation.cfg Attestation_adversarial.cfg; do
  java -XX:+UseParallelGC -cp tools/tla2tools.jar tlc2.TLC \
    -deadlock -workers 4 -config "$cfg" "${cfg%.cfg}.tla"
done
```

Coverage: ~470 Python tests + Go suite + 71 Rust tests + 5 TLA+
model checks. Every commit on `main` is gated on the fast slice
and the Go / Rust suites via GitHub Actions; heavy integration
runs nightly and on touch of `netd/` or `gyza/network/`.

---

## Layout

```
gyza/                # Python — execution, identity, ICP, ledger, CLI
├── schema.py            WorkItem / Artifact / HLC dataclasses
├── blackboard.py        SQLite WAL store + atomic claim + TTL filter
├── icp.py               ICPEnvelope; single- and multi-compositor verify
├── identity.py          LocalCompositor + AgentIdentity + manifests
├── runner.py            AgentRunner + executor backends
├── economy/             bilateral ledger + settlement protocol + reputation
├── network/             Phase-2 LAN cluster + Phase-3 daemon client + global cluster
└── cli.py               gyza CLI

netd/                # Go — gyza-netd daemon (libp2p, DHT, NAT, gossip)
├── cmd/gyza-netd/       entry point
└── internal/{identity,host,dht,discovery,nat,gossip,message,capability,grpc}/

gyza-rs/             # Rust — vNext reference implementation (workspace)
├── gyza-crypto/         Ed25519 + BLAKE3 + HKDF (parity ✓)
├── gyza-identity/       LocalCompositor + AgentIdentity (parity ✓)
├── gyza-icp/            envelope sign/verify + verify_chain (parity ✓)
├── gyza-core/           WorkItem + Artifact + HLC
├── gyza-blackboard/     SQLite-backed storage
└── gyza-settlement/     entry signing + payer_validate (parity ✓)

spec/                # TLA+ formal protocol specs
├── Settlement.tla       INV-SETTLE-1..7
├── Reconciliation.tla   INV-SETTLE-8..11
└── Attestation.tla      INV-ATT-1..8

docs/                # invariants, state machines, wire protocol, ADRs
demo/                # runnable end-to-end demos
tests/               # pytest
scripts/             # install.sh + deploy-bootstrap.sh + verify-bootstrap.sh
```

---

## License

Apache 2.0. See `LICENSE`.
