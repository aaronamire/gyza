# Gyza

Gyza is an agentic coordination layer: multiple AI agents share a
SQLite-backed blackboard, claim work items atomically, execute them,
and emit cryptographically signed envelopes that chain together into
a tamper-evident record of who did what, in what order, on whose
behalf. Phase 1 runs entirely on a single host. Networking comes
later.

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

## Quick start

Gyza Phase 1 reuses Marshal's venv (`~/dev/marshal/.os`) since it
already has numpy, lancedb, sentence-transformers, blake3,
cryptography, and pytest. If you don't have that, create your own:

```bash
python3.14 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Then:

```bash
# One-time: generate the compositor key under ~/.gyza
python -m gyza.cli init

# Run the two-agent pipeline demo (works without an API key)
python -m gyza.cli demo

# Show what's on the blackboard
python -m gyza.cli status

# Show what tampering looks like
python -m gyza.cli demo injection
```

The demo posts two work items, runs a query specialist + summarizer
specialist as `AgentRunner` threads, and prints a verification report
including the BLAKE3 chain hash. With `ANTHROPIC_API_KEY` set and the
`anthropic` SDK installed, the executors call Claude; otherwise they
fall back to a deterministic local scanner that produces real,
inspectable output.

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

## Roadmap

- **Phase 2 — LAN Raft.** Replace single-host SQLite with a Raft-
  replicated work-item log across a small cluster. Cross-agent
  envelope stitching becomes automatic via a chain indexer that
  walks parent_envelope_hash links across agents. Capability
  manifests get distributed via a gossip layer.
- **Phase 3 — Global DHT.** Long-lived agents discover and join
  task neighborhoods through a Kademlia-style overlay. Compositor
  trust roots federate; revocation lists become CRDTs.
- **Phase 1.5 — operational polish.** Background reward refresh.
  Scheduled TTL vacuum. Persistent envelope log so chain
  reconstruction outlives any one runner. Real Anthropic executor
  with prompt-caching and timeout budgets.

## Layout

```
gyza/                package root
├── schema.py        WorkItem / Artifact / HLC dataclasses
├── blackboard.py    SQLite WAL store + atomic claim + TTL filter
├── reward.py        Exponential reward inflation
├── icp.py           ICPEnvelope, sign / verify / chain helpers
├── identity.py      LocalCompositor, AgentIdentity, manifests, revocation
├── memory.py        EpisodicMemory (LanceDB primary, SQLite fallback)
├── demand.py        LSHIndex + DemandOracle (background polling)
├── drift.py         Specialization drift + persisted tracker
├── runner.py        AgentRunner + mock/anthropic executors
├── config.py        GyzaConfig (~/.gyza/config.json)
└── cli.py           init / demo / status

demo/                end-to-end demos
├── two_agent_pipeline.py
└── injection_demo.py

tests/               pytest, all passing
```

## Running the tests

```bash
~/dev/marshal/.os/bin/python -m pytest tests/ -v
```

64 tests covering the data layer, ICP cryptography, identity
issuance, episodic memory (with LanceDB unavailability path), demand
oracle / LSH locality / specialization convergence, the runner's
race / completion / executor-failure semantics, TTL filtering,
config loading, and CLI argument parsing.
