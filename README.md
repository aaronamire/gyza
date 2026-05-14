# Gyza

> Peer-to-peer compute network with cryptographic provenance and
> bilateral settlement. AI agents on independent nodes find each
> other, claim each other's work, sign provenance envelopes, and
> settle compute credits — all without a central operator.

**Status:** alpha. Linux only (x86_64 / aarch64). macOS and Windows
are not yet supported.

## Install

```bash
# Linux x86_64 or aarch64. Requires Python 3.14+ and pipx.
curl -sSf https://gyza.network/install.sh | bash
```

That installs the `gyza-netd` daemon and the `gyza` CLI, generates
your compositor identity, and prints next steps.

If you'd rather install from source:

```bash
git clone https://github.com/amirewontmiss/gyza-rs gyza
cd gyza
make -C netd build              # builds netd/bin/gyza-netd
pipx install --editable .       # installs the gyza CLI
gyza init                       # generates ~/.gyza/compositor.key
```

## Quickstart

```bash
# Join the network. (Reads bootstrap peers from DNS at gyza.network.)
gyza global start

# In another shell: what's connected?
gyza status

# Run the local two-agent demo (no remote peers required).
gyza demo two_agent_pipeline

# Run the full Phase-3 single-machine integration demo (two daemons
# on loopback, settles in ~15 s).
gyza demo single_machine_global
```

## What it is

Independent nodes share a SQLite-backed blackboard, claim work items
atomically, execute them, and emit cryptographically signed
envelopes that chain together into a tamper-evident record of who
did what, in what order, on whose behalf. A bilateral
compute-credit ledger settles every completed work item between the
earner and payer. Tier-3 attestations (k-of-n quorum cosignatures
from independent validators) gate which peers are allowed to claim
high-trust work.

The architecture splits along the network boundary: a Go daemon
(`gyza-netd`) owns the libp2p host, Kademlia DHT, NAT traversal,
and gossipsub; a Python stack (`gyza`) owns execution, identity,
ICP envelopes, ledger, and CLI. They communicate over a Unix
socket via gRPC.

## Architecture

```
                ┌──────────────────────────┐
                │    Human Intent          │
                │  (natural-language goal) │
                └────────────┬─────────────┘
                             │ post_intent()
                             ▼
              ┌────────────────────────────────┐
              │           Blackboard           │
              │  ┌──────────────────────────┐  │
              │  │ human_intents (lineage)  │  │
              │  │ work_items   (claimable) │  │
              │  │ artifacts    (signed)    │  │
              │  └──────────────────────────┘  │
              └────────────┬───────────────────┘
                           │ try_claim() — BEGIN IMMEDIATE
        ┌──────────────────┼──────────────────┐
        ▼                                     ▼
 ┌──────────────┐                      ┌──────────────┐
 │  Agent A     │                      │  Agent B     │
 │  identity:   │                      │  identity:   │
 │   Ed25519 sk │                      │   Ed25519 sk │
 │  manifest:   │                      │  manifest:   │
 │   compositor-│                      │   compositor-│
 │   signed     │                      │   signed     │
 └──────┬───────┘                      └──────┬───────┘
        │ execute → output_hash               │
        ▼                                     ▼
 ┌──────────────┐    parent_envelope_hash    ┌──────────────┐
 │ ICP envelope │ ◄─────────────────────────│ ICP envelope │
 │ (BLAKE3+sig) │                            │ (BLAKE3+sig) │
 └──────┬───────┘                            └──────┬───────┘
        └────────────────┬──────────────────────────┘
                         ▼
                 ┌───────────────┐
                 │ Verified      │
                 │ artifact chain│
                 │ (tamper-      │
                 │  evident)     │
                 └───────────────┘
```

Each agent runs a claim → execute → sign loop. Output bytes are
hashed with BLAKE3, signed with the agent's Ed25519 key into an
**ICP envelope**, and parented to the prior envelope's hash. Mutating
any field of any envelope breaks its signature; inserting a fake
envelope between two real ones breaks the next real envelope's parent
linkage. So the whole chain is structurally immutable post-hoc — you
can't rewrite history without forging a private key.

## Where it sits

This repository is one of three siblings on the same machine:

- **Marshal** (`~/dev/marshal`) — local agent daemon. Single-host,
  in-process execution for one user's natural-language intents.
  Owns the GoalSpec schema; runs file/system/web/etc. agents inside
  Landlock + cgroups.
- **Leaves OS** (`~/dev/leaves-os`) — the OS that hosts everything
  else. Wayland compositor, intent UI, system services.
- **Gyza** (`~/dev/gyza`, here) — the coordination/network layer.
  Same machine for now; Phase 2 adds LAN Raft, Phase 3 a global DHT.

Gyza intentionally does not import from Marshal — it borrows
patterns (the WAL+FK+busy_timeout SQLite recipe; UUIDv4 intent_id;
all-MiniLM-L6-v2 embeddings) but stays decoupled. The two share
a Python venv only because that is convenient on this box.

## Local-only mode (no networking)

The Phase-1 demos run entirely on a single host with no daemon — useful
for kicking the tires before joining the network.

```bash
# Generate identity (if not already done).
gyza init

# Two-agent pipeline: posts two work items, runs a query specialist
# and a summarizer, prints the verified envelope chain.
gyza demo two_agent_pipeline

# Show what's on the blackboard.
gyza status

# Show what tampering does to the chain.
gyza demo injection
```

With `ANTHROPIC_API_KEY` set and the `anthropic` SDK installed, the
executors call Claude; otherwise they fall back to a deterministic
local scanner that produces real, inspectable output.

## Security model

What ICP gives you:

- **Tamper-evidence.** Any modification to a past envelope (output
  hash, model identifier, timestamp, anything) invalidates that
  envelope's signature and breaks every downstream parent linkage.
- **Authorship attribution.** Every envelope is bound to an Ed25519
  pubkey whose corresponding manifest was signed by the local
  compositor. So "agent X did action Y on inputs I producing output
  O at time T using model M" is verifiable from the envelope alone.
- **Capability binding.** The envelope embeds
  `capability_manifest_hash`. A third party can recompute that hash
  over the manifest the agent claims to be running under and confirm
  the action falls inside the agent's authorized scope.
- **Lineage to a registered intent.** The blackboard refuses any
  work item whose `lineage_root` is not a registered human intent.
  Agents cannot manufacture top-level goals.

What ICP does **not** give you:

- **Liveness or availability.** A signed chain proves what happened;
  it doesn't stop anyone from pulling the plug.
- **Confidentiality.** Envelopes are signed, not encrypted. Output
  artifacts are stored in plaintext.
- **Defense against a stolen private key.** If an agent's seed
  leaks, the attacker can sign valid-looking envelopes under that
  identity. Compositor revocation (`revoke_agent`) is the recourse,
  but it only helps verifiers who consult the revocation list.
- **Cross-agent stitching for free.** The runner only parents
  envelopes within its own agent's local chain. Stitching A→B
  cross-agent currently requires an explicit re-sign step (the
  pipeline demo does this inline). Phase 2 introduces an indexer.
- **Sybil resistance.** Anyone can stand up a `LocalCompositor` and
  mint as many agents as they want. The signature is only as
  meaningful as the trust chain rooted in the compositor pubkey.

## Current limitations (Phase 1)

- **Single host.** No networking. Multiple processes on the same
  machine can share a blackboard via SQLite; that's it.
- **No real ICP transport between agents on different machines.**
- **Mock executor by default.** The Anthropic executor needs both
  `ANTHROPIC_API_KEY` set and the `anthropic` Python SDK installed
  (the marshal venv does not ship it). Without one or both, demos
  fall back to deterministic local content.
- **Cross-agent envelope linkage is a manual re-sign.** See the
  pipeline demo for the pattern.
- **Reward inflation refresh is opt-in.** `refresh_rewards()` exists
  but no scheduler calls it automatically yet.
- **Demand oracle ages signals based on `oldest_item_age_ns`** — fine
  for a small queue, less interesting until many items per bucket.
- **LSH at 64 planes is tight.** Two embeddings need cosine well
  above 0.99 to share a Hamming-radius-2 neighborhood. Tests sample
  from a tighter ball than the prose suggests.

## Phase 2: LAN federation

Phase 2 turns Gyza from a single-host coordinator into a small LAN
cluster. Two laptops on the same WiFi run `gyza` independently. They
discover each other via mDNS, authenticate with QUIC + their compositor
keypairs, agree on a Raft-replicated work-item log, and exchange
artifacts by content hash over HTTP. An ICP chain produced on one
machine is verifiable on the other.

```
Machine A (192.168.1.5)            Machine B (192.168.1.6)
┌─────────────────────────┐        ┌─────────────────────────┐
│  Leaves OS              │        │  Leaves OS              │
│  Compositor CK_A        │        │  Compositor CK_B        │
│  ┌───────────────────┐  │        │  ┌───────────────────┐  │
│  │ AgentRunner       │  │        │  │ AgentRunner       │  │
│  │ (coordinator)     │  │        │  │ (executor)        │  │
│  └─────────┬─────────┘  │        │  └─────────┬─────────┘  │
│            │            │        │            │            │
│  ┌─────────▼─────────┐  │ Raft   │  ┌─────────▼─────────┐  │
│  │ NetworkBlackboard │◄─┼────────┼─►│ NetworkBlackboard │  │
│  │ (writes via Raft) │  │ QUIC   │  │ (writes via Raft) │  │
│  │ (reads via SQLite)│  │ :8749  │  │ (reads via SQLite)│  │
│  └───────────────────┘  │        │  └───────────────────┘  │
│  ┌───────────────────┐  │artifact│  ┌───────────────────┐  │
│  │ Artifact server   │◄─┼────────┼─►│ Artifact server   │  │
│  │ (FastAPI :7750)   │  │  HTTP  │  │ (FastAPI :7750)   │  │
│  └───────────────────┘  │ :7750  │  └───────────────────┘  │
│  ┌───────────────────┐  │mDNS    │  ┌───────────────────┐  │
│  │ TrustRegistry     │  │_gyza._ │  │ TrustRegistry     │  │
│  │ (CK_A pinned)     │  │udp     │  │ (CK_A pinned)     │  │
│  │ (CK_B pinned)     │  │        │  │ (CK_B pinned)     │  │
│  └───────────────────┘  │        │  └───────────────────┘  │
└─────────────────────────┘        └─────────────────────────┘
            │                                  │
            └────────────── ICP chain ─────────┘
                Hop 1: Agent_A signed under CK_A
                Hop 2: Agent_B signed under CK_B
                verify_chain_multi_compositor() → VALID ✓
```

### What's new

- **Authenticated QUIC transport** (`gyza/network/transport.py`).
  Connections are mutually authenticated by an Ed25519
  challenge-response over the QUIC stream — the compositor keypair
  that signs ICP envelopes is the same one that authenticates the
  link. No PKI. Self-signed TLS certs are scaffolding only.
- **mDNS discovery** (`gyza/network/discovery.py`). Zero-config peer
  finding via `_gyza._udp.local.`. TXT record carries the compositor
  pubkey, QUIC port, attestation tier, and a freshness timestamp.
  Falls back to `manual_peers` from `~/.gyza/config.json` when the
  network blocks multicast.
- **Raft-replicated blackboard** (`gyza/network/raft.py` +
  `network_blackboard.py`). Built on `pysyncobj`. Three operations
  go through Raft (post intent, post work item, claim, complete);
  every read stays local — Raft applies committed entries to local
  SQLite synchronously, so reads are read-your-writes consistent.
- **Content-addressed artifact exchange** (`artifact_store.py`,
  `artifact_server.py`, `artifact_client.py`). FastAPI server on
  :7750 serves bytes by BLAKE3 hash; clients verify the hash on
  download and try the next peer if a server lies.
- **Cross-machine ICP verification** (`trust_registry.py` +
  `icp.verify_chain_multi_compositor`). A chain that spans two
  compositors is valid iff both compositors are pinned in the local
  trust registry, every manifest signature checks out under its
  declared compositor, every envelope signature checks out under
  its agent's pubkey, and every input/output artifact is in the
  local artifact store.

### Two-machine quick start

On both machines:

```bash
python -m gyza.cli init      # generate compositor key, mkdir ~/.gyza
```

Then on Machine A:

```bash
python demo/two_machine_demo.py --role coordinator
```

…and on Machine B (within ~30 seconds — coordinator waits for the
executor to join):

```bash
python demo/two_machine_demo.py --role executor
```

The coordinator posts two work items with a lineage dependency, the
executor claims both, signs ICP envelopes, and stores artifacts.
The coordinator reconstructs the chain, runs
`verify_chain_multi_compositor`, and prints a per-hop report
ending in `CHAIN INTEGRITY: VALID ✓`.

### Single-machine simulation

If you don't have a second laptop handy:

```bash
python -m gyza.cli demo lan
```

This launches the coordinator and executor as two subprocesses on
localhost with separate Raft and QUIC ports. Output is identical
to the two-machine version.

### Phase-2 CLI commands

```bash
gyza demo lan                 # Phase-2 single-machine demo
gyza status                   # blackboard + artifact-store stats
gyza network peers            # list LAN peers from local cache
gyza network join HOST:PORT   # one-shot dial to verify reachability
gyza trust list               # pinned compositors
gyza trust revoke PUBKEY      # revoke a compositor's trust
```

### Troubleshooting

- **mDNS shows nothing.** Some networks (corporate WiFi, captive
  portals, certain VPNs) block multicast. Add the peer manually:
  ```json
  {
    "manual_peers": ["192.168.1.5:7749", "192.168.1.6:7749"]
  }
  ```
  in `~/.gyza/config.json`. Discovery dials these every 5–30 s.
- **Connection refused.** Check `quic_port` (default 7749),
  `artifact_port` (7750), `raft_port` (8749) are open in the local
  firewall. They should be open only to the LAN, never to the
  public internet.
- **Cluster never forms.** The first node prints "no peers found,
  running solo on LAN" if it doesn't see anyone within 15 s. If
  both nodes started but neither saw the other, it's almost always
  mDNS — try the manual_peers route.

### Security notes for Phase 2

- The TrustRegistry is what protects you from an attacker who
  guesses the right mDNS response. Just because a packet says
  "I am compositor X" doesn't mean it is. The QUIC handshake's
  challenge-response proves the peer holds X's private key; the
  registry pins X *after* that proof, and ICP verification refuses
  any envelope whose compositor isn't pinned.
- Revoking a compositor (`gyza trust revoke`) doesn't tear down
  existing connections — it only marks future chain verifications
  as failing. Drop the connection separately if needed.
- Raft journals are in-memory by default. A node restart loses its
  in-flight log, but it catches up via AppendEntries from any
  surviving peer. Don't run a single-node "cluster" expecting
  durability.

## Phase 3: Global Federation

Phase 3 lifts coordination from "one LAN, Raft-consistent" to "any two
nodes anywhere, eventually consistent via gossipsub + bilateral ledger
settlement." A long-running Go daemon (`gyza-netd`) carries everything
that needs production-grade libp2p — DHT discovery, NAT traversal
(DCUtR + circuit relay), gossipsub, signed-message routing — and
exposes it to Python over a Unix-socket gRPC channel. The Python
process keeps owning blackboard, runner, ICP signing, and ledger; the
data plane never round-trips through Python.

```
                    Internet (any topology)
                            │
  ┌─── Node A (Tokyo) ──────┼────── Node B (Paris) ────┐
  │ ┌─────────┐  ┌─────┐    │      ┌─────┐  ┌────────┐ │
  │ │gyza-netd│──┤Raft │    │      │Raft │──┤gyza-netd│ │
  │ │(Go,DHT, │  │LAN  │    │      │LAN  │  │(Go, DHT, │ │
  │ │libp2p)  │  └──┬──┘    │      └──┬──┘  │libp2p)  │ │
  │ └────┬────┘     │       │         │     └────┬────┘ │
  │      │ gRPC over Unix sock         gRPC over Unix sock
  │ ┌────┴───────────────┐    ┌──────────────┴────┐ │
  │ │ Python (Phase 1+2) │    │ Python (Phase 1+2)│ │
  │ │  blackboard, runner│    │  blackboard,runner│ │
  │ │  ICP, ledger       │    │  ICP, ledger      │ │
  │ └────────────────────┘    └───────────────────┘ │
  └────────────────────────────────────────────────┘

  Cross-node primitives:
    • Kademlia DHT      — agents advertise / discover by spec embedding
    • DCUtR + relay     — connect through NAT without manual config
    • gossipsub         — per-project blackboard delta sync (CRDT merge)
    • MessageService    — point-to-point libp2p stream for ledger frames
    • bilateral ledger  — earner-signed → payer-cosigned credit entries
    • free-rider filter — local scoring deprioritizes habitual debtors
    • capability cert   — Tier-3 attestation co-signed by 2 of 3 Tier-3 peers
```

### Quick start (single machine, two daemons)

```bash
# Build the Go daemon (Go 1.22+).
make -C netd build

# Initialize ~/.gyza if you haven't already.
gyza init

# Start gyza-netd in the foreground.
gyza global start

# In another shell, run the integration simulation. Two daemons,
# two GlobalCluster instances, mock executor, full bilateral
# settlement. Should print "BILATERAL ✓" within ~10s.
python demo/single_machine_global.py
```

### Quick start (two machines)

The cross-machine flow is identical — both sides need to build
`gyza-netd` and run `gyza init`. Then on each side:

```bash
gyza global start
```

The Python orchestration that drives discovery / project formation
is exposed as a class (`gyza.network.global_cluster.GlobalCluster`)
rather than a CLI flow; see `demo/single_machine_global.py` for the
canonical wiring.

### CLI surface

```bash
gyza global status            # netd identity, DHT peers, connections
gyza global find "<query>"    # search the DHT for matching agents
gyza global project new <id>  # join (or create) a project's gossip topic
gyza credits balance          # net credits earned/spent
gyza credits statement        # ledger entries
gyza credits peers            # per-peer balance + free-rider score
```

### Troubleshooting

- **`gyza-netd` won't build.** Ensure Go 1.22 or newer (`go version`).
  The libp2p stack pins `go.mod` versions; `go mod tidy` should be a
  no-op on a clean checkout.
- **No DHT peers found.** With no bootstrap peers configured, two
  daemons on the same LAN find each other via the daemon's mDNS
  service. Cross-network operation needs `netd_bootstrap_peers` set
  in `~/.gyza/config.json` (the daemon's own bootstrap defaults to
  IPFS public bootstrap nodes for development convenience).
- **NAT traversal fails (cross-network).** DCUtR works for ~60% of
  NAT types. For the remainder, set `enable_relay = true` in config
  to opt into the circuit-relay fallback. Relay introduces ~50ms of
  added latency but achieves 100% connectivity.
- **`gyza global attest` reports "not yet implemented".** The proof-
  of-capability orchestration ships in Session 7's API but not in
  this CLI revision. Run the eval suite via `python -m
  gyza.capability_eval` and use the daemon's CapabilityService gRPC
  surface directly until the CLI grows the wiring.
- **Settlement never happens after a remote agent finishes work.**
  Verify both sides have the daemon running and connected
  (`gyza global status`), and that both have joined the project
  topic. The `LedgerSettlementService` requires a libp2p stream to
  the payer; without a routable peer ID for the coordinator's
  compositor pubkey, the executor's `submit_earned` is a no-op
  (logged at INFO level).

### What "works" looks like

```
$ python demo/single_machine_global.py
[demo] tmp dir: /home/xan/.gyza/demo-phase3-global
[demo] booting two daemons...
[demo] coordinator peer_id: 12D3KooW...
[demo] executor    peer_id: 12D3KooW...
[demo] coordinator → executor connected
[demo] gossip mesh formed for project
[demo] executor runner started
[demo] coordinator posted intent + work_item
[demo] executor completed the work item

╔══════════════════════════════════════════════════════════════╗
║ GYZA PHASE 3 — SINGLE-MACHINE FEDERATION SIMULATION          ║
╠══════════════════════════════════════════════════════════════╣
║ Cross-cluster gossip:    VALID ✓                            ║
║ Bilateral settlement:    BILATERAL ✓                        ║
╠══════════════════════════════════════════════════════════════╣
║ ECONOMY                                                      ║
║   coordinator's view of executor:    -0.5000 credits         ║
║   executor's view of coordinator:    +0.5000 credits         ║
╚══════════════════════════════════════════════════════════════╝
```

Two strangers' nodes form a project, exchange work, and settle
credits — without any shared infrastructure beyond the DHT
bootstrap nodes. That's the Phase 3 promise.

## Roadmap

- **Phase 4 — self-organization.** Demand-driven spawning of fine-tuned
  child agents. Versioned identity (manifest rotation without losing
  reputation history). Scoped revocation lists distributed via gossip.
  Worth starting only once Phase 3 has 20+ live nodes generating
  organic demand data.
- **Phase 1.5 — operational polish.** Background reward refresh.
  Scheduled TTL vacuum. Persistent envelope log so chain
  reconstruction outlives any one runner. Real Anthropic executor
  with prompt-caching and timeout budgets.

## Layout

```
gyza/                package root
├── schema.py            WorkItem / Artifact / HLC dataclasses
├── blackboard.py        SQLite WAL store + atomic claim + TTL filter
├── reward.py            Exponential reward inflation
├── icp.py               ICPEnvelope; single- and multi-compositor verify
├── identity.py          LocalCompositor, AgentIdentity, manifests, revocation
├── memory.py            EpisodicMemory (LanceDB primary, SQLite fallback)
├── demand.py            LSHIndex + DemandOracle (background polling)
├── drift.py             Specialization drift + persisted tracker
├── runner.py            AgentRunner + mock/anthropic executors
├── config.py            GyzaConfig (~/.gyza/config.json)
├── cli.py               init / demo / status / network / trust
└── network/             Phase-2 networking
    ├── transport.py         QUIC + Ed25519 challenge-response auth
    ├── discovery.py         mDNS + manual-peer fallback
    ├── raft.py              pysyncobj-backed replicated state machine
    ├── network_blackboard.py NetworkBlackboard + wait_for_sync
    ├── cluster.py           cluster lifecycle (form/join/leave)
    ├── artifact_store.py    content-addressed filesystem store
    ├── artifact_server.py   FastAPI server, BLAKE3-keyed
    ├── artifact_client.py   verifying client with peer fallback
    └── trust_registry.py    pinned compositors + cached manifests

demo/                end-to-end demos
├── two_agent_pipeline.py        Phase-1 local two-agent demo
├── injection_demo.py            tampering breaks chain
├── two_machine_demo.py          Phase-2 cross-machine demo
├── single_machine_phase2.py     Phase-2 demo, two subprocesses
└── single_machine_global.py     Phase-3 demo: two netd daemons + gossip + settlement

netd/                Phase-3 Go daemon (libp2p, DHT, NAT, gossip)
├── cmd/gyza-netd/main.go        entry point (flags, signals, cleanup)
└── internal/
    ├── identity/                load Ed25519 keypair → libp2p PrivKey
    ├── host/                    libp2p host w/ QUIC + Noise + yamux
    ├── dht/                     Kademlia DHT + Python-compatible LSH
    ├── discovery/               mDNS LAN auto-discovery
    ├── nat/                     DCUtR hole-punching + relay opt-in
    ├── gossip/                  gossipsub + signed delta verification
    ├── message/                 /gyza/message/1.0.0 stream protocol
    ├── capability/              proof-of-capability challenge protocol
    └── grpc/                    gRPC services + proto definitions

gyza/economy/        Phase-3 compute-credit economy
├── ledger.py                    bilateral SQLite ledger, BLAKE3 + Ed25519
└── settlement.py                earner_signed ⇄ payer_cosigned protocol

tests/               pytest, all passing
```

## Running the tests

```bash
# Fast slice (~10 min): unit + protocol tests, no real daemons.
python -m pytest tests/ -q --tb=line --timeout=90 \
  -k "not netd_client and not phase2_integration and not phase2_hardening \
      and not blackboard_gossip and not attestation_bridge and not verify_on_fetch"

# Heavy integration (~1 min warm, ~10 min cold): spawns real daemons.
python -m pytest tests/test_netd_client.py \
  tests/test_network_blackboard_gossip.py tests/test_attestation_bridge.py \
  tests/test_verify_on_fetch.py -q --timeout=240

# Go daemon (~5 s):
cd netd && go test ./... -count=1 -timeout=120s

# Rust workspace (~5-30 s):
cd gyza-rs && cargo test --workspace
```

250 tests covering: the data layer; ICP cryptography (single- and
cross-compositor); identity issuance; episodic memory (with LanceDB
unavailability path); demand oracle / LSH locality / specialization
convergence; the runner's race / completion / executor-failure
semantics; TTL filtering; config loading; CLI argument parsing;
QUIC transport with mutual authentication; mDNS discovery and
peer persistence; Raft consensus (leader election, exactly-once
claim under contention, log catch-up, leader failover); the
NetworkBlackboard's cross-node visibility guarantees; artifact
store + server + client; cross-machine ICP verification; and
Phase-2 hardening (network-partition catch-up, concurrent artifact
fetch, Raft NotReady retry, manual_peers fallback, artifact store
size limit). Heavy networking tests are marked `integration`;
skip them with `GYZA_SKIP_INTEGRATION=1` (see `pytest.ini`).
