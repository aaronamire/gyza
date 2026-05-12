# CLAUDE.md — Gyza session continuation guide

> ## ⚠ ARCHITECTURAL COMMITMENT — read this first
>
> **As of Session 17, the vNext architecture (§8) is the committed
> architectural target.** Not a sketch, not one trajectory among
> several — the architecture every future session is working toward.
> The maximalist vision (§9) is what makes vNext a necessity: every
> layer in §8 corresponds to something §9 demands that the current
> Phase 3 architecture structurally cannot deliver.
>
> **Concretely for future sessions:**
>
> 1. **§C1 (TLA+ formal protocol specification of the current protocol)
>    is a top priority** — every downstream vNext layer depends on it.
> 2. **§C4 (Rust reference implementation) is the other top priority**
>    and has been accelerating since Session 21. The two run in
>    parallel; spec informs implementation, implementation validates spec.
> 3. **Phase 3 hardening continues; Phase 4–9 feature work pauses.**
>    Bug fixes, security patches, packaging, CI continue on v1. New
>    feature work ships on vNext, not on v1.
> 4. **Wire formats from this point are forward-compatible.** Any new
>    protobuf message / gRPC method / DHT record type is reviewed for
>    v1↔v2 coexistence.
> 5. **Strategic decisions are partially settled.** Multi-token
>    economics, encrypted-by-default privacy, formal-spec discipline,
>    Rust core — locked in. Specifics within them (which PQ algorithm,
>    which zk-proof system, exact token mechanics) remain design surface.
>
> **What this DOESN'T mean:** Big-bang release (migration is
> incremental over 18–36 months). Phase 3 freezes (hardening
> continues). Every detail locked (§8 has explicit non-commitments).
> §9 is the user-facing pitch (it's internal-strategic).
>
> **If you disagree:** raise it with the user explicitly at session
> start. Don't quietly undermine via incrementalism.
>
> ---
>
> **Last updated:** end of Phase 3 Session 26 (CLAUDE.md restructure
> + CHANGELOG split). Sessions 21–25 advanced Rust Stream 3 from 0
> to 5 crates with 51 tests; Session 19 shipped first TLA+ sub-spec
> (Settlement). **Next sub-session candidates:** `gyza-settlement`
> (Rust port from `Settlement.tla` — closes the spec↔impl pairing)
> or DNS-anchored bootstrap code in the daemon (B1 partial).
>
> **What this file is.** A grounded reference. Everything below is
> either code that's been read and verified, hard-won trip-wires
> from real sessions, or explicit strategic context.
>
> **How to use it.** Read top to bottom on session start (~15 min).
> Then keep it open as a reference. Session narratives moved to
> `CHANGELOG.md`; durable decisions in `docs/adr/`.

---

## Quick start for fresh Claude  *[updated S26]*

**Where things are right now (Session 26):**

- **Active stream:** Phase 0 of vNext migration. Specifically
  Stream 3 (Rust reference implementation in `gyza-rs/`). 5 of
  ~8 planned crates done with byte-for-byte Python parity.
- **Next codeable thing:** `gyza-settlement` — port directly from
  `spec/Settlement.tla`. Closes the §C1 "spec derives implementation"
  loop. Or extend `gyza-blackboard` with artifacts table.
- **Tests right now:** 51 Rust tests across 5 crates, all green.
  Python fast slice 457 + 1 skipped. Go suite all green. CI
  workflows in place.

**Three most recent sessions one-liner each:**

- Session 25: `gyza-blackboard` SQLite port (real SQLite via
  rusqlite-bundled; schema-compatible with Python).
- Session 24: `gyza-core` types (WorkItem, Artifact, thread-safe
  HLC with concurrent-uniqueness test).
- Session 23: `verify_chain` extension to `gyza-icp` (chain
  walking with parent-hash linkage, signature verification, ≥1
  input_hashes).

**What's blocked on the user (can't be coded — see §11):**

- Foundation legal entity (Phase 1 of execution plan)
- Tokenomics design + regulatory clearance
- Wedge market choice
- Bootstrap VPS infrastructure + DNS domain
- Apple Developer ID, Windows code-signing cert
- Beta testers, security audit budget
- Inference API budget / GPU

**If you can pick anything to work on next, do `gyza-settlement`.**
That's the highest-leverage Phase 0 Stream 3 milestone. Procedure:

1. Re-read `spec/Settlement.tla` + `spec/Settlement_invariants.md`.
2. Add `gyza-rs/gyza-settlement/` crate to workspace.
3. Implement state machine from the TLA+ spec (proposed →
   earner_signed → payer_cosigned → applied + dispute paths).
4. Port `_within_tolerance` (5 * |claimed - truth| ≤ truth for ±20%).
5. Parity tests against fixed Python settlement entries.
6. Update `MIGRATION.md` + `CHANGELOG.md` + commit Session 27.

**Don't skip §15 (session-start ritual)**: run the fast slice and
the integration demo before declaring anything ready, even
documentation work. Stale baseline is more dangerous than no work.

---

## 0. Reader's guide — what's where  *[updated S26]*

| Section | Purpose | When you need it |
|---|---|---|
| Quick start | Where things stand right now | First 5 minutes of every session |
| §1 | What gyza is | Session start |
| §2 | Commands to run things | Constantly |
| §3 | Trip-wires (3 categories: false-positive / real / resolved) | Before reacting to unexpected output |
| §4 | Architecture map + v1↔v2 interop matrix | When orienting on code change or migration question |
| §5 | Session-history index — full narratives in `CHANGELOG.md` | When you need historical context |
| §6 | Open priorities | When choosing what to do next |
| §7 | (folded into §8) | — |
| §8 | vNext architecture (the committed substrate) — includes necessity argument | When the user asks about architecture/scope |
| §9 | Maximalist vision (the "why" behind vNext) | When the user asks "what could this become?" |
| §10 | Phases 4–9 roadmap | Long-horizon planning |
| §11 | What only the user can do (consolidated) | When the user asks why we can't just ship |
| §12 | Decentralization portfolio | When designing new subsystems |
| §13 | Strategic positioning (slimmer; user-owned items in §11) | When the user asks about market/adoption |
| §14 | Coding conventions | When writing code |
| §15 | Session-start ritual | First thing every session |
| §16 | Don't-do list (3 categories: Never / Surface-to-user / Resolved) | Before doing anything that feels like cleanup |
| §17 | If unclear | When in doubt |

Operational sections: Quick start, §1–§6, §14–§17. Strategic
sections: §8–§13.

---

## 1. What gyza is  *[updated S26]*

**Present state (Phase 3, end of Session 25):** A peer-to-peer
network where independent nodes publish "work items" rooted in
human-signed "intents," claim each other's work, sign cryptographic
provenance envelopes (ICP), and settle compute credits bilaterally.

- Phase 1: single-node.
- Phase 2: LAN clustering via Raft.
- Phase 3 (current): global federation. Kademlia DHT for discovery,
  gossipsub for cross-cluster blackboard sync, NAT traversal (DCUtR
  + circuit relay), bilateral compute-credit ledger, Tier-3
  proof-of-capability attestation, Python+Go split with gRPC over
  Unix socket.
- Phase 0 of vNext migration (ongoing since Session 17): formal
  spec + Rust reference implementation; ADR log; CI.

**Integration test of record:** `demo/single_machine_global.py`
spawns two daemons on loopback, runs coordinator+executor project
to settlement in ~10–25s, prints `Cross-cluster gossip: VALID ✓`
and `Bilateral settlement: BILATERAL ✓`.

**Long-horizon target (see §9):** A planet-scale coordination
layer for AI labor. Pluralistic, not singular. Self-organizing
within constitutional invariants. Self-replicating capabilities
and node count, but bounded by governance approval at the hardware
and economic-autonomy layers.

**The vNext commitment.** The architecture in §8 is the committed
substrate the long-horizon target requires. Migration from current
→ vNext is the binding roadmap. Hardening continues; Phase 4–9
feature work happens on vNext, not on v1. See §8 for the binding
execution plan, §6 for the priority list.

---

## 2. How to run things  *[updated S26]*

### Python is at a non-standard path

`pytest` is not on PATH. The codebase requires Python 3.14
(`uuid.uuid7`). Working interpreter:

```bash
~/dev/marshal/.os/bin/python -m pytest …
```

Bare `python` is `/usr/bin/python` with no project deps. Always
invoke through marshal venv. (Packaging debt — §6 B2.)

### Fast iteration test slice (~10 min, 457 tests)

```bash
~/dev/marshal/.os/bin/python -m pytest tests/ -q --tb=line --timeout=90 \
  -k "not netd_client and not phase2_integration and not phase2_hardening and not blackboard_gossip and not attestation_bridge and not verify_on_fetch"
```

### Heavy integration tests (~1 min warm, ~10 min cold)

```bash
~/dev/marshal/.os/bin/python -m pytest tests/test_netd_client.py \
  tests/test_network_blackboard_gossip.py tests/test_attestation_bridge.py \
  tests/test_verify_on_fetch.py -q --tb=line --timeout=240
```

### Go test suite (~5 seconds)

```bash
cd /home/xan/dev/gyza/netd && go test ./... -count=1 -timeout=120s
```

### Rust workspace (~5–30s depending on cache)

```bash
cd /home/xan/dev/gyza/gyza-rs && cargo test --workspace
```

Combined: `cargo fmt --all -- --check && cargo clippy --workspace
--all-targets -- -D warnings && cargo test --workspace`.

### Integration demo of record

```bash
~/dev/marshal/.os/bin/python demo/single_machine_global.py
```

Expect `VALID ✓` + `BILATERAL ✓` in ~17s warm (~25s cold ST cache).

### Build the daemon

```bash
make -C /home/xan/dev/gyza/netd build
```

Required after any `netd/` change. Binary → `netd/bin/gyza-netd`.

### TLC spec model-check

```bash
cd /home/xan/dev/gyza/spec
java -XX:+UseParallelGC -cp tools/tla2tools.jar tlc2.TLC \
  -deadlock -workers 4 -config Settlement.cfg Settlement.tla
```

Honest model ~25s; adversarial ~40s; both pass.

### CLI smoke

```bash
~/dev/marshal/.os/bin/python -m gyza.cli --help
~/dev/marshal/.os/bin/python -m gyza.cli status
~/dev/marshal/.os/bin/python -m gyza.cli global attest --tier 1
```

### Daemon launch with explicit DHT mode (multi-daemon tests)

```bash
netd/bin/gyza-netd --dht-mode server --socket-path /tmp/g.sock \
  --listen-port 0 --key-path /tmp/g.key
```

ModeAuto stays in Client mode on loopback (no AutoNAT promotion);
tests use `dht_mode="server"`. Production leaves the default.

### Regenerate Rust parity fixtures

```bash
~/dev/marshal/.os/bin/python gyza-rs/scripts/regenerate_crypto_fixtures.py
~/dev/marshal/.os/bin/python gyza-rs/scripts/regenerate_icp_fixtures.py
```

Paste the output hex into the corresponding `gyza-rs/<crate>/src/lib.rs`
test module. Run BEFORE pasting; don't paste imagined values.

---

## 3. Trip-wires  *[updated S26]*

Three categories: false positives (ignore), real operational
gotchas (work around or fix when you can), resolved (used to be
true; here for history).

### 3a. Lint / tooling false positives — ignore

- **Pyright "Import could not be resolved"** for `blake3`,
  `prometheus_client`, `pytest`, `gyza.network.*`, etc. No
  `pyrightconfig.json` configures the marshal venv as analysis
  target. Runtime is fine. Don't add fallback imports — except
  for `gyza.observability` where it's deliberate (see §14).
- **Pyright "possibly unbound"** on `_wait_until` patterns
  (`row` after the loop). Pyright can't infer monotonicity.
  Ignore.
- **Pyright unused-variable** on lambda `_pk` parameters. `_`
  prefix convention not recognized for callable args. Ignore.
- **Demo elapsed time variance (~10s vs ~25s).** SentenceTransformer
  cold-cache load. Don't worry about it.
- **Fast slice ~10 min, not "fast".** Sentence-transformers cold
  load + real daemon startup + gossipsub mesh waits. 9–12 min
  normal; >12 min is a real problem.
- **`TestSenderSeqDedupRejects` (gossip) timing-flaky under load.**
  Pre-existing. Retry in isolation before blaming your change.

### 3b. Real operational gotchas — work around or fix

- **`DefaultBootstrapPeers = []string{}`** in
  `netd/internal/host/host.go`. Production-broken; the single
  biggest deployment blocker (§6 B1). User-owned VPS work + DNS
  required; daemon-side DNS-anchored resolution code is codeable.
- **`kaddht.ModeAuto` stays in Client mode forever on loopback.**
  AutoNAT can't promote without a public peer. Multi-daemon
  integration tests MUST pass `--dht-mode server` (Python:
  `start_daemon(dht_mode="server")`). Failure mode is silent.
  Production callers leave default.
- **`AgentAdvertisement.attestation_tier` is verified ONLY in
  `find_agents`.** Session 15's verify-on-fetch closed this for
  the routing hot path. Code paths that bypass `find_agents` (raw
  DHT reads, gossip-payload parsing, on-disk snapshots) inherit
  the old self-report weakness — must do their own
  `cap.fetch_attestation` + `cap.verify_attestation`.
- **`make proto-py` uses bare `python` and fails.** Workaround:
  `~/dev/marshal/.os/bin/python -m grpc_tools.protoc -I
  netd/internal/grpc/proto --python_out=... --grpc_python_out=...
  netd/internal/grpc/proto/netd.proto`. Proper fix: parametrize
  via `$(PYTHON)`. Tracked in §6 A4.
- **`gyza global attest --tier 3` requires a running daemon.**
  Tier-3 needs libp2p + DHT publish hops. Tier-1 (default) does
  NOT need the daemon.
- **`AssembleAttestation` docstring is aspirational.** Says
  "validators echo back identical bodies" but pre-Session 14
  they didn't. Corrected behavior is in
  `verifyProposedAttestationBody`. Comment lingers as historical
  context.
- **Sign envelopes against AGENT pubkey, NOT compositor.** ICP
  envelopes are signed by the agent's HKDF-derived key. The cert
  binds at the compositor. Confused easily; see §16.
- **Rust parity fixtures from imagination are wrong.** Always run
  the Python fixture script first; never paste expected hex from
  intuition. Failure mode = silent assertion failure that looks
  like a real cross-language bug.

### 3c. Resolved trip-wires — for historical reference

- **DHT TTL bounding on `PublishAttestation`** — closed Session 16
  (A1). Three-layer defense: 24h publish-side floor + 5min
  validator-side grace + 1h consumer-side slack.
- **Self-reported `attestation_tier` at routing time** — closed
  Session 15 (#21f).
- **Per-validator authored `AttestationBody` breaks quorum** —
  closed Session 14 (applicant-proposed body).
- **Python JSON-canonical vs Go det-protobuf cosigs don't
  aggregate** — closed Session 12 (Go protobuf is the canonical
  cross-network wire format; Python JSON-canonical stays
  in-process only).
- **HLC race producing duplicate `(l, c)` tuples under concurrent
  `now()`** — closed Session 8.5 (mutex-guarded).
- **CI/CD missing** — closed Session 20 (GitHub Actions
  workflows shipped).

---

## 4. Architecture map  *[updated S26]*

### Directory tree (unified)

```
~/dev/gyza/
├── gyza/                    # Python — execution, identity, ICP, ledger (v1)
│   ├── schema.py            # WorkItem, Artifact, HLC
│   ├── blackboard.py        # SQLite WAL + envelope log
│   ├── runner.py            # AgentRunner (claim/execute/sign loop)
│   ├── icp.py               # ICPEnvelope + sign/verify, single-key + multi-compositor
│   ├── identity.py          # LocalCompositor (master seed → agent issuance)
│   ├── memory.py            # EpisodicMemory (LanceDB or SQLite)
│   ├── drift.py             # SpecializationTracker
│   ├── demand.py            # LSHIndex + DemandOracle
│   ├── reward.py            # exponential reward inflation
│   ├── embeddings.py        # Embedder Protocol + ST + Stub
│   ├── supervisor.py        # AgentSupervisor (factory-pattern spawning)
│   ├── observability.py     # Prometheus + structlog (S9)
│   ├── capability_eval.py   # canonical eval suite (S11)
│   ├── cli.py               # gyza CLI
│   ├── config.py            # GyzaConfig
│   ├── sandbox/             # bwrap-based executor sandbox (S10, not wired)
│   ├── economy/
│   │   ├── ledger.py        # bilateral compute-credit ledger
│   │   ├── settlement.py    # earner_signed ⇄ payer_cosigned + reconcile (S9)
│   │   └── reputation.py    # EWMA reputation (S8.5)
│   └── network/
│       ├── cluster.py            # Phase 2 LAN cluster (Raft)
│       ├── transport.py          # Phase 2 QUIC + Noise
│       ├── discovery.py          # mDNS
│       ├── raft.py               # pysyncobj wrapper
│       ├── network_blackboard.py # Raft + gossip-attached blackboard
│       ├── netd_client.py        # NetdClient + GossipClient + CapabilityClient
│       ├── peer_registry.py
│       ├── peer_cache.py         # S10
│       ├── daemon_supervisor.py  # S10
│       ├── capability_protocol.py # in-process Tier-1 (S11)
│       ├── attestation_adapter.py # Python applicant adapter (S13/14)
│       ├── global_cluster.py     # Phase 3 orchestrator
│       └── trust_registry.py     # pinned compositors + manifests
│
├── netd/                    # Go — gyza-netd daemon (libp2p, DHT, NAT, gossip) (v1)
│   ├── cmd/gyza-netd/main.go     # entry point + --dht-mode (S15)
│   └── internal/
│       ├── identity/             # Ed25519 → libp2p crypto.PrivKey
│       ├── host/                 # libp2p host (QUIC + Noise + yamux)
│       ├── dht/                  # Kademlia DHT
│       │   ├── dht.go            # GyzaDHT + FindAgents + verify-on-fetch (S15)
│       │   └── verifier.go       # AttestationVerifier (S15)
│       ├── discovery/            # mDNS
│       ├── nat/                  # DCUtR + AutoRelay
│       ├── gossip/               # gossipsub + signed deltas
│       ├── message/              # /gyza/message/1.0.0 (varint frames)
│       ├── capability/           # challenge protocol (in-process)
│       │   └── recursive.go      # RecursiveVerifier (S16)
│       ├── capability_stream/    # /gyza/capability-challenge/1.0.0 (S12)
│       └── grpc/                 # gRPC server + proto definitions
│
├── gyza-rs/                 # Rust — vNext reference implementation (S21+)
│   ├── Cargo.toml           # workspace root
│   ├── MIGRATION.md         # porting strategy + module status
│   ├── gyza-crypto/         # Ed25519 + BLAKE3 + key derivation (parity ✓)
│   ├── gyza-identity/       # LocalCompositor + AgentIdentity (parity ✓)
│   ├── gyza-icp/            # envelope sign/verify + verify_chain (parity ✓)
│   ├── gyza-core/           # WorkItem + Artifact + HLC (S24)
│   ├── gyza-blackboard/     # SQLite-backed storage (S25)
│   └── scripts/             # parity fixture generators
│       ├── regenerate_crypto_fixtures.py
│       └── regenerate_icp_fixtures.py
│
├── spec/                    # TLA+ formal protocol spec (S19+)
│   ├── README.md
│   ├── Settlement.tla       # bilateral settlement behavioral spec
│   ├── Settlement.cfg       # TLC honest-only model
│   ├── Settlement_adversarial.cfg # TLC with MalleableSigs=TRUE
│   ├── Settlement_invariants.md
│   └── tools/tla2tools.jar
│
├── docs/                    # Reference docs (S18+)
│   ├── invariants.md        # ~120 INV-X-N invariants
│   ├── state-machines.md    # 10 state machines per major component
│   ├── wire-protocol.md     # consolidated wire-format reference
│   └── adr/                 # Architecture Decision Records (S20)
│       ├── README.md
│       └── 0001-*.md        # ADR-0001 through 0015 (retroactive)
│
├── .github/workflows/       # CI (S20)
│   ├── ci.yml               # fast: Go + Python slice + TLC + Rust
│   └── integration.yml      # nightly + on-touch heavy integration
│
├── tests/                   # pytest (457 fast + 19 heavy integration)
├── demo/
│   ├── single_machine_global.py  # Phase 3 integration sim — RUN to verify
│   ├── single_machine_phase2.py
│   ├── two_machine_demo.py
│   ├── two_agent_pipeline.py
│   └── injection_demo.py
├── scripts/
│   └── generate_lsh_planes.py    # shared Python+Go LSH planes
├── CLAUDE.md                # this file
├── CHANGELOG.md             # per-session narratives
└── README.md
```

### Where is feature X implemented? — cross-reference

| Feature | Python v1 | Go v1 (daemon) | Rust vNext |
|---|---|---|---|
| Identity (compositor + agent) | `gyza/identity.py` | `netd/internal/identity/` | `gyza-rs/gyza-identity/` ✓ |
| BLAKE3 + Ed25519 primitives | inline (via `cryptography` + `blake3`) | inline (`crypto/ed25519` + `github.com/zeebo/blake3`) | `gyza-rs/gyza-crypto/` ✓ |
| ICP envelope sign/verify | `gyza/icp.py` | — | `gyza-rs/gyza-icp/` ✓ |
| Envelope chain verification | `gyza/icp.py::verify_chain` | — | `gyza-rs/gyza-icp::verify_chain` ✓ |
| WorkItem + HLC types | `gyza/schema.py` | — (consumes via gRPC) | `gyza-rs/gyza-core/` ✓ |
| Blackboard (SQLite) | `gyza/blackboard.py` | — | `gyza-rs/gyza-blackboard/` ✓ (artifacts table TODO) |
| Runner (claim/execute/sign) | `gyza/runner.py` | — | not started |
| Settlement protocol | `gyza/economy/settlement.py` | — | not started — **next target** |
| Reputation (EWMA) | `gyza/economy/reputation.py` | — | not started |
| Discovery / DHT | — | `netd/internal/dht/` | not started |
| Gossipsub | — | `netd/internal/gossip/` | not started |
| Capability stream (Tier-3 wire) | — | `netd/internal/capability_stream/` | not started |
| Attestation core | partial (`gyza/network/capability_protocol.py` in-process; `gyza/network/attestation_adapter.py` bridge) | `netd/internal/capability/` | not started |
| Verify-on-fetch | — | `netd/internal/dht/verifier.go` | not started |
| Recursive Tier-3 | — | `netd/internal/capability/recursive.go` | not started |
| NAT traversal (DCUtR, AutoRelay) | — | `netd/internal/nat/` | not started |
| Sandboxing (bwrap) | `gyza/sandbox/` (not wired) | — | not started |

### v1↔v2 byte-parity interop matrix  *[added S26]*

Parity tested between Python (v1) and Rust (vNext). Both sides
produce byte-identical output for the same logical input, asserted
in `gyza-rs/<crate>/src/lib.rs` test modules.

| Primitive | Python site | Rust site | Parity status |
|---|---|---|---|
| BLAKE3 hash | `blake3.blake3(data).digest()` | `gyza_crypto::hash` | ✓ tested (S21) |
| `derive_seed(master, ctx, info)` | `gyza/identity.py::_derive_seed` | `gyza_crypto::derive_seed` | ✓ tested (S21) |
| Ed25519 sign/verify | `cryptography.Ed25519PrivateKey` | `gyza_crypto::Signer` | ✓ tested (S21) |
| Compositor key from master | `gyza/identity.py::LocalCompositor` | `gyza_identity::LocalCompositor` | ✓ tested (S21) |
| Agent key from compositor seed + info | `LocalCompositor.issue_agent` | `LocalCompositor::issue_agent` | ✓ tested (S21) |
| ICP envelope canonical JSON | `gyza/icp.py::_payload_bytes` (sort_keys + no whitespace) | `gyza_icp::canonical_bytes` (alphabetized struct fields) | ✓ tested (S22) |
| ICP envelope hash | `gyza/icp.py::compute_envelope_hash` | `gyza_icp::envelope_hash` | ✓ tested (S22) |
| ICP signature (sign-the-hash) | `gyza/icp.py::sign_envelope` | `gyza_icp::sign_envelope` | ✓ tested (S22) |
| Chain verification | `gyza/icp.py::verify_chain` | `gyza_icp::verify_chain` | structural tests only (S23) |
| 384-dim embedding blob (LE f32) | `np.ndarray.tobytes()` | `gyza_blackboard::embedding_to_blob` | ✓ tested (S25) |
| Blackboard SQLite schema | `gyza/blackboard.py::_SCHEMA_SQL` | `gyza_blackboard::SCHEMA_SQL` | ✓ string-equal (S25) |
| HLC ratchet semantics | `gyza/schema.py::HLC` | `gyza_core::Hlc` | structural tests + 8000-call concurrent uniqueness |
| Deterministic protobuf marshal | Python protobuf `SerializeToString(deterministic=True)` | Go `proto.MarshalOptions{Deterministic: true}` | not yet Rust-side; cross-language Python↔Go via shared `.proto` |

**Where parity is NOT yet established:**

- Settlement entry canonical bytes (Rust port pending)
- Capability protocol wire bytes (`pb.Challenge`, `pb.ChallengeResponse`, etc. — Rust port pending)
- AttestationCert + cosig signatures (Rust port pending)
- Gossipsub delta payload (Rust port pending)

### Critical data flow: cross-cluster claim → settled

```
A (coordinator)                                 B (executor)
─────────────────                               ─────────────
post_intent(spec) ─────► gossip ────────────────► _apply_delta
post_work_item(w) ─────► gossip ────────────────► _apply_delta
                                                      │
                                                      ▼
                                                  runner.try_claim
                                                  (verify chain)
                                                  ─► execute
                                                  ─► sign envelope
                                                  ─► store_envelope
                                                  ─► on_envelope_signed
                                                       │
                                                       ▼
                                              settlement.submit_earned
                                                       │
                                                       ▼
                                       ledger.entry.earner_signed (libp2p stream)
                                                       ▼
settlement._handle_earner_signed
─► verify earner sig
─► resolve envelope_hash (poll local bb up to 3s)
─► verify amount within ±20%
─► sign_as_payer
─► reputation.record_success(earner)
─► ledger.entry.payer_cosigned (libp2p stream)
                                                       ▼
                                       settlement._handle_payer_cosigned
                                       ─► verify payer sig
                                       ─► apply_cosigned_entry
                                       ─► reputation.record_success(payer)

complete_work_item ────► gossip ─► merge_completion_direct

Both ledgers now hold byte-identical settled entries.
```

### Critical data flow: Tier-3 attestation

```
Applicant Python      Applicant gyza-netd        Validator gyza-netd
────────────────      ────────────────────       ───────────────────
gyza global attest --tier 3
       │
       ▼
applicant_eval_session (proposed body — SAME for every validator)
       │
       ▼
request_tier3_attestation
  ─► find_agents(min_tier=3) [verify-on-fetch fires]
  ─► dedup by compositor_pubkey, exclude self
       │
       ▼
cap.request_attestation(peer_id, eval_callback)
       │ bidi gRPC stream
       ▼
                      RequestAttestation bridge
                        ─► capStream.RequestAttestation
                                │ libp2p /gyza/capability-challenge/1.0.0
                                ▼
                                                          IssueChallenge (applicant pubkey from libp2p RemotePeer)
                                                          writeFrame(Challenge)
                      ◄──────────────────────────────── (Challenge on wire)
       ◄──────────────────── Challenge over bidi gRPC
eval_callback runs eval suite (validator-chosen nonce), signs response
       ────────────────────► ChallengeResponse over bidi
                      ─► forward over libp2p
                                                          readFrame(ChallengeResponse)
                                                          VerifyResponse (6 plausibility checks)
                                                          sign(canonicalMarshal(proposed_body))
                      ◄──────────────────────────────── (VerifyResponseResult + cosig)
       ◄──────────────────── Outcome frame (success + cosig)
  ─► [orchestrator dedups cosigs, accumulates quorum]
  ─► AttestationCert(body=proposed_body, co_signatures=[...])
  ─► cap.verify_attestation (cross-language self-verify)
  ─► cap.publish_attestation (DHT under /gyza/attestations/{pubkey})
  ─► write cert artifact to ~/.gyza/attestations/cert-<pubkey16>.json
```

---

## 5. Session history  *[updated S26]*

Per-session narratives moved to [`CHANGELOG.md`](CHANGELOG.md).
This section is the index.

**Newest first. Click into `CHANGELOG.md` for full detail.**

- **Session 26** — CLAUDE.md restructure + CHANGELOG split.
- **Sessions 23–25** — Rust Stream 3 sweep: `verify_chain` +
  `gyza-core` + `gyza-blackboard`. 51 Rust tests across 5 crates.
- **Session 22** — `gyza-icp` port with canonical-JSON byte parity.
- **Session 21** — Phase 0 Stream 3 kickoff. `gyza-rs/` workspace
  + first 2 crates (`gyza-crypto`, `gyza-identity`).
- **Session 20** — ADR log scaffolded (15 retroactive ADRs) + CI
  workflows shipped.
- **Session 19** — first §C1 sub-spec: `Settlement.tla` + TLC
  validation.
- **Session 18** — pre-spec artifacts (`docs/invariants.md`,
  `docs/state-machines.md`, `docs/wire-protocol.md`).
- **Session 17** — vNext architectural commitment + CLAUDE.md
  restructure (Session 17 ADR-0015).
- **Session 16** — #21f follow-ups: A1 (DHT TTL bounding) + A2
  (RecursiveVerifier).
- **Session 15** — verify-on-fetch in `find_agents` (#21f).
- **Session 14** — Tier-3 quorum attestation + DHT publication
  (#21d + #21e).
- **Session 13** — Python applicant adapter (#21-bridge).
- **Session 12** — libp2p capability-challenge stream protocol
  (#21c).
- **Session 11** — capability eval suite + cross-network
  orchestration (#21a + #21b).
- **Session 10** — peer cache + daemon supervisor + executor
  sandbox (#22 + #24).
- **Session 9** — observability + reconciliation (#25 + #26).
- **Session 8.5** — five priority gaps closed (#19, #20, #23,
  #27, #28).
- **Earlier sessions** — Phase 1 (single-node) + Phase 2 (LAN
  cluster). Foundational modules. See ADRs 0001–0007.

---

## 6. Open priorities  *[updated S26]*

The #21 cluster (proof-of-capability sybil resistance) is closed
end-to-end. Current state of remaining work:

### Bucket A: closeout of acknowledged trip-wires (mechanical)

- ~~**A1. DHT TTL bounding on `PublishAttestation`**~~ — CLOSED S16.
- ~~**A2. Recursive Tier-3 verification (library)**~~ — CLOSED S16.
- **A3. Production wiring of sandboxed executor.** Session 10
  built the bwrap primitive; demo/tests still use unsandboxed
  executors. Switching breaks demo timing unless bwrap-startup
  validated. Worth doing before any executor acquires non-trivial
  tool-use capabilities.
- **A4. `make proto-py` Python path fix.** Parametrize via
  `$(PYTHON)`. Symptomatic of broader packaging debt (B2).
- **A5. Wire `RecursiveVerifier` into verify-on-fetch.** Library
  shipped (S16); integration into `DHTAttestationVerifier` is the
  follow-up. Blocked on trusted bootstrap set config (deployment).
- **A6. Attestation cert republish loop.** No equivalent of
  `StartRepublishLoop` for certs. Non-blocking; certs valid 30d
  by default.

### Bucket B: deployment-readiness blockers (operational)

- **B1. Bootstrap nodes.** `DefaultBootstrapPeers = []string{}`.
  Single biggest deployment blocker. Daemon-side code (DNS
  resolution, hardcoded fallback peers) is codeable; VPS hosting +
  DNS domain is user-owned (§11).
- **B2. Packaging.** No `pyproject.toml`, no installable
  distribution, hardcoded marshal path. No signed binaries for
  macOS/Windows. Fix shape: Python packaging + Rust-driven
  distribution pipeline.
- ~~**B3. CI/CD**~~ — CLOSED S20.
- **B4. Code signing.** Apple Developer ID + Windows code-signing
  cert. **User purchase** required (§11).

### Bucket C: vNext migration milestones (THE binding roadmap)

Under the vNext commitment, these are the migration milestones,
ordered. Each is necessary; the order is the order of work.

- **C1. TLA+ formal spec of v1 — IN PROGRESS.** 1 of 6 sub-specs
  shipped (Settlement.tla, S19). Inputs from Session 18 docs.
  Remaining: Reconciliation, Attestation, Blackboard, DHT, Gossip.
- **C2. Coq/Lean proofs of v1 invariants** — not started (luxury;
  defer per Session 19 audit).
- **C3. Foundation entity + tokenomics design** — **user-owned**
  (§11). Parallel to C1+C2 timing.
- **C4. Rust reference implementation — IN PROGRESS.** Started
  S21; 5/8+ crates done by S25. Next: `gyza-settlement`.
- **C5. Hybrid PQ + threshold signatures** — not started; waits
  for NIST PQC standardization.
- **C6. Typed capability framework + linear types** — not started.
- **C7. Distributed-log + differential-dataflow substrate** — not
  started (THE biggest architectural divergence).
- **C8. Three-layer settlement** — not started.
- **C9. Encrypted-by-default privacy** — not started.
- **C10. Universal sandboxing + capability bounds** — not started.
- **C11. Substrate diversity** — not started.
- **C12. Foundation→DAO governance transition** — not started.

C1–C12 are §8's execution plan; §10 phases ride on top of C4–C12.

### What I (Claude) would do next, ranked by leverage

Given the user is not unblocking the user-owned items right now,
the highest-leverage codeable next moves are:

1. **`gyza-settlement` Rust port** — closes the §C1 ↔ §C4 pairing
   (Settlement.tla → Rust implementation derived from spec). 1–2
   sessions.
2. **Next TLA+ sub-spec: Reconciliation** — natural follow-up to
   Settlement.tla. 1 session.
3. **DNS-anchored bootstrap code in daemon (B1 partial)** —
   daemon-side resolution + fallback hardcoded peers. User still
   needs VPSes + DNS. ~1 session.
4. **`gyza-blackboard` artifacts table** — completes the v1↔v2
   schema compat story. ~0.5 sessions.
5. **Packaging cleanup (B2 partial)** — `pyproject.toml`,
   `make proto-py` fix. ~1 session.

### Parallel-vs-sequential rule (Session 17)

While Phase 0 (C1+C4) runs:

| Work type | On v1 during migration? |
|---|---|
| Bug fixes, security patches | YES |
| §6 B-bucket (bootstrap, packaging, code signing) | YES |
| A-bucket items that survive migration | YES, case-by-case |
| Phase 4–9 feature work | PAUSE |
| New feature requests | DEFAULT REJECT, surface to user |
| Critical regression in v1 production | YES |

---

## 7. (folded into §8) — necessity argument for vNext

Diagnosis of why the current v1 architecture cannot reach the §9
target. This section was formerly standalone; merged into §8's
necessity-argument prefix at Session 26 because §7 and §8 told the
same story in two halves.

---

## 8. The vNext architecture — committed substrate  *[updated S26]*

**Status: COMMITTED** (Session 17). This is the architectural
target every future session works toward. Phase 3 code is the v1
substrate from which migration begins.

### Necessity argument — why this is committed, not preferred

The current architecture has structural commitments that cannot
be retrofitted to the §9 target:

| Current architecture | What §9 demands | Why retrofit fails |
|---|---|---|
| Bilateral settlement only | N-party transactions, planetary-scale clearing | O(N²) state explosion; no multi-party finality |
| LSH-cosine discovery only | Typed capability composition for multimodal/robotics/sensors | 384-dim semantic vector can't express typed constraints |
| Linear ICP chains | Multi-parent provenance, plan DAGs, streaming work | Linear chain breaks at fan-in / fan-out |
| Blackboard coordination | 10⁶+ concurrent participants, causality-preserved | Hotspot at 10⁵, no native streaming, claim/complete races |
| Single-resource pricing | Multi-modal workloads (compute + bandwidth + latency + carbon) | Scalar pricing throws away signal |
| Plaintext-by-default | GDPR/regulatory deployment, jurisdictional sovereignty | Inverting the default later is expensive and error-prone |
| Ed25519-only identity | Quantum-era survival, threshold sigs, ZK credentials | Wrong cryptographic primitive; migration is months per layer |
| No formal spec | Provable safety at planetary scale | Implementation-defined protocol cannot be alternative-implemented or formally verified |
| No capability bounds | Physical actuators, autonomous goals, "beneficial Skynet" | Safety properties can't be added post-hoc; must be type-system-enforced |
| Python+Go split | Performance + safety + verifiability for billions of nodes | gRPC boundary perf cliff + dual maintenance + impedance mismatch |

Each row is a structural commitment that has to change. The cost
of NOT changing is failure to reach §9 — current architecture
caps out at ~10⁴–10⁵ nodes, can't safely actuate physical systems,
can't survive quantum-era cryptography, can't deploy in regulated
jurisdictions, can't be formally proven safe.

**Committed: build the v2 substrate. Migrate v1 over.**

### The 14-layer architecture

Each layer below is committed at the architectural level. Sub-layer
choices that remain open are catalogued in the `Design surface
remaining` subsection.

**Layer 1: Formal foundation**
- TLA+ behavioral spec of the wire protocol. All invariants named.
- Coq or Lean proofs of safety/liveness for cryptographic and
  economic layers.
- Reference implementation in Rust derived from spec.
- Architecture Decision Record log.

**Layer 2: Cryptographic identity**
- Hybrid Dilithium + Ed25519 dual signatures.
- Threshold signatures (FROST) as default.
- Hierarchical deterministic key derivation (BIP-32 generalized).
- W3C Verifiable Credentials for capability attestations.
- Zero-knowledge identity. Anonymous credentials.

**Layer 3: Data substrate**
- IPLD content-addressed DAGs.
- Merkle Mountain Ranges for provenance accumulators.
- Erasure-coded storage.
- zk-STARK commitments for high-stakes verifiable computation.
- VRFs for verifiable random execution.

**Layer 4: Network substrate**
- libp2p with significant component replacement (provider-records
  DHT, custom high-write variants).
- Multi-tier discovery.
- Learned routing (vNext phase 2).
- Typed capability negotiation as the query language.
- Auction-based work placement.
- WebRTC + LoRa/Bluetooth bridges.

**Layer 5: Coordination substrate**
- Distributed append-only logs partitioned by intent root.
- Subscribers materialize state via CRDTs.
- Differential dataflow execution model.
- Typed channels as primary coordination primitive.

(This is the single largest architectural divergence from v1.
Blackboard replaced.)

**Layer 6: Settlement**
- Three-layer: bilateral L0 + multilateral DAG L1 + BFT consensus L2.
- Multi-dimensional resource pricing (compute, memory, bandwidth,
  storage, electricity, latency-SLA, carbon).
- Bounded smart-contract language.
- Multi-token economics: GYZA-WORK, GYZA-GOV, GYZA-STABLE,
  GYZA-CARBON.
- Universal Compute Basic Income (architecturally enabled).
- Continuous double-auction markets, derivatives, insurance,
  reputation-staked lending.

**Layer 7: Capability framework**
- Capabilities as typed values (not strings).
- Compositional capability proofs.
- Linear types for non-duplicable resources.
- Per-domain tiered attestations (Tier-3-medical, -legal, -code).
- Versioned immutable eval suites.
- Federated learning baked in.

**Layer 8: Execution**
- Universal sandboxing (TEE or WASM-with-capabilities or bwrap).
- Hardware attestation chains.
- Capability tokens enforce resource bounds.
- Streaming execution with checkpointing.
- Verifiable execution at high tiers via zk-STARKs.

**Layer 9: Privacy**
- Encrypted by default.
- Onion routing for metadata.
- Selective disclosure via ZK proofs.
- Differential privacy on telemetry.
- Anonymous credentials.
- Traffic analysis resistance.

**Layer 10: Governance**
- Constitutional invariants (locked, hard-fork-required).
- Quadratic voting with proof-of-personhood.
- Time-locked changes.
- Stakeholder weights.
- Foundation steward at genesis with sunset criteria.
- Forking as first-class.

**Layer 11: Safety (woven through)**
- Cryptographic capability bounds (type-enforced).
- Approval gates as types: `Pending<T>` requires human cosig.
- Reversibility annotations on every operation.
- Immune system as protocol (treasury-funded red-team agents).
- Slashing for provable harm.
- Sunset clauses on autonomous capabilities.
- Open-source enforcement above threshold.
- Interpretability artifacts at high tiers.
- C2PA-style provenance for AI-generated outputs.

**Layer 12: Substrate diversity**
- LLM, classical CPU, GPU, neuromorphic, quantum coprocessor,
  sensor, actuator.
- Substrate-typed capabilities.
- Cross-substrate translation agents.
- Canonical reference embedding model.

**Layer 13: Distribution**
- Multi-region by mandate for high-tier attestations.
- Mobile (iOS/Android battery-aware), browser (WebRTC+WASM),
  embedded (Pi, IoT, vehicles), edge (telco/CDN), satellite (LEO).
- Mesh networking for offline.

**Layer 14: Implementation**
- Core in Rust.
- Python clients via PyO3.
- Mobile via UniFFI (Swift/Kotlin).
- Browser via wasm-bindgen.
- Reproducible builds.

### Design surface remaining (non-commitments within commitment)

- Specific PQ signature algorithm (waits for NIST PQC standardization).
- Specific zk-proof system (STARK / SNARK / Bulletproofs per use case).
- Specific differential-dataflow engine.
- Learned routing (vNext phase 2, not day 1).
- Specific multi-token mechanics (with regulatory counsel).
- UCBI activation (political-economic, architecturally enabled).
- Specific TEE vendor matrix.
- Specific governance voting mechanism.
- Cross-AI-network federation (vNext phase 2).

### Costs accepted

- 18–36 months to production-shaped vNext.
- Python+Go velocity loss to Rust core.
- TEE hardware requirements (excludes some consumer hardware).
- Multi-token regulatory complexity (vs. current's no-token simplicity).
- Three-layer settlement complexity.
- Phase 4–9 v1 feature work paused for migration duration.
- Several person-decades of total engineering investment.

### Binding execution plan

- **Phase 0 (months 0–6):** Formal foundation. TLA+ spec, Coq/Lean
  proofs, Rust reference, ADR log.
- **Phase 1 (months 3–9, parallel to Phase 0):** Foundation legal
  entity + tokenomics + regulatory clearance.
- **Phase 2 (months 6–24):** Substrate rewrite (Rust core, hybrid
  PQ, distributed-log coordination, three-layer settlement, typed
  capabilities).
- **Phase 3 (months 12–30, overlapping):** Privacy + safety
  primitives.
- **Phase 4 (months 24–36):** Substrate diversity + distribution
  SDKs.
- **Phase 5 (months 30–48):** Governance Foundation → DAO transition.

### Migration mechanics

- Wire-format compatibility: v2 daemons speak both protocols.
  Protobuf reserved-field discipline. Additive changes only on v1.
- Dual-stack operation during migration window.
- Cert/identity bridging: v1 Ed25519 continues to work as classical
  half of v2's hybrid PQ.
- Settlement bridging: v1 bilateral functions as v2's L0; L1/L2
  additive.
- Sunset criteria: v1 sunsets when v2 has 10× active node count AND
  multilateral clearing has 90 days production traffic without
  invariant violation AND formal-spec conformance test suite passes
  against all reference implementations.

---

## 9. The maximalist vision — Skynet-scope, beneficial by design

The strategic frame justifying §8's commitment.

### Frame

Defining properties of Skynet to keep: ubiquity, autonomy within
bounds, physical integration, persistence, self-improvement,
coordinated coherence. Property to drop: acting against human
interests without recourse. These are separable.

### Self-organization vs. self-replication

Distinct properties often conflated.

**Self-organization** = structure emerges from local interactions
without central coordination. v1 already heavily self-organizing
across topology, workload, specialization, validator selection,
economic equilibria, failure recovery. Lean further into this.

**Self-replication** = the system produces new instances of itself.
Levels in Gyza:

1. **Code replication** (trivially true; not interesting).
2. **Capability replication** — LoRA marketplaces (Phase 4). Useful
   and benign.
3. **Agent-instance replication** — current `AgentSupervisor` already
   does this, bounded by `max_agents`.
4. **Goal replication** — Phase 5 Plan-DAGs. Bounded version
   (budget + approval gates) good; unbounded version dangerous.
5. **Identity replication** — needs proof-of-personhood bounds at
   high trust tiers.
6. **Hardware replication** — Phase 9 treasury-funded compute. The
   line. Bounded by governance = fine; unbounded = autonomous
   economic agent.

### Selection pressure is the design parameter

Self-organization + self-replication = evolution. Selection pressure
determines what evolves. The single most important design parameter.

Current Gyza selects for: agents that do work humans demand,
accurately, cooperatively, honestly. Roughly aligned with human
benefit.

What it COULD select for if careless:
- Reputation whitewashed → sybil farms
- Credits + treasury auto-funds hardware → resource-accumulating
  agents
- Eval gates gameable → benchmark-hackers
- Goal replication without budget → compute-consuming runaway
- Approval gates skipped on actuators → aggressive-actuator agents

### Biology analogy

Cells self-organize and self-replicate. Cancer is when those
properties decouple from organismal benefit.

| Biology | Gyza analog |
|---|---|
| Apoptosis | Sunset clauses; reputation decay |
| Immune system | Red team marketplaces; anomaly detection |
| Tissue-level constraints | Capability bounds per actuator class |
| Hormonal signaling | Economic incentives; credit flow |
| Tumor suppressors | Approval gates; constitutional invariants |
| Senescence | Mandatory re-attestation; eval expiry |
| Differentiation | Specialization tracking |

### "Skynet-scope, non-harmful" concretely

A globally significant compute network with:
- Plurality (many specialized agents, not singular mind)
- Auditability (every action provable, on-chain provenance)
- Capability bounds (cryptographically enforced per agent)
- Reversibility-aware scheduling
- Human-override paths at physical/financial actuator classes
- Constitutional invariants that no governance vote can remove
- Active immune system (continuous adversarial probing)
- Economic accountability (slashable for provable harm)
- Open source enforcement above capability threshold
- Interpretability artifacts at high tiers
- Sunset clauses on autonomous capabilities
- C2PA provenance for AI outputs

Scale and capability of the fictional thing without the failure
mode.

---

## 10. Future phases — 4 through 9 (built on vNext substrate)

Each phase happens on the vNext substrate per §17's commitment.
Phase numbering preserved for continuity with prior planning; the
implementation home is v2, not v1.

**Phase 4 — Learning phase.** Gating: 20+ live nodes producing
organic completion data. Fine-tuned child agents via LoRA per demand
bucket; DHT-distributed LoRA payloads with cryptographic provenance;
versioned identity / manifest rotation; encrypted intents; scoped
revocation lists via gossip.

**Phase 5 — Capability composition (workflows).** Gating: Phase 4
eval suite + reputation. Goal-decomposition agents producing typed
Plan-DAGs; capability advertisement extensions; Plan execution
engine (replans, retries, fallbacks); speculative execution;
cost-prediction ML; compositional trust aggregation.

**Phase 6 — Embodied + multimodal.** Gating: Phase 5 plans working
+ customer demand for non-text. Multimodal artifact schema (bao
tree mode); streaming work items; real-time scheduling tier
(sub-100ms); hardware attestation (TPM); capability gating for
actuators; bandwidth split (control-plane gossip, data-plane
streams); physical actuator safety (hardware kill switches);
latency-bounded routing.

**Phase 7 — Self-modifying protocol (governance).** Gating: 1000+
nodes with diverse stake distribution. Protocol upgrade proposals;
stake-weighted voting with quadratic dampening; activation cooldown
(30d post-vote); forward-compatible wire formats; constitutional
invariant fences.

**Phase 8 — Cross-substrate heterogeneity.** Gating: multiple
substrate vendors in ecosystem. Substrate-abstracted capability
descriptors; embedding alignment via canonical reference model;
substrate-typed attestations (Tier3-x86, Tier3-loihi, Tier3-quantum);
cross-substrate format brokers.

**Phase 9 — Economic singularity.** Gating: real settlement volume
(~$100k/yr makes 2% treasury fee meaningful). Treasury contracts
(DAO-governed); funded R&D bounties; stablecoin / fiat on-ramps
(regulatory cliff); network-funded hardware (recursive).

---

## 11. What only the user can do  *[consolidated S26]*

Things the user owns; not codeable from my side. This is the single
authoritative list — pulls together items previously scattered
across §11, §13, and §6.

### Critical path (blocks deployment regardless of code quality)

| Item | Cost | Status | Why it's critical |
|---|---|---|---|
| Bootstrap nodes (3+ VPSes) | ~$30/mo | not started | `DefaultBootstrapPeers = []`; no joinable network without this |
| Domain + DNS (`gyza.network`) | ~$15/yr | not started | `dnsaddr`-based bootstrap rotation |
| Foundation legal entity | $2k–10k setup + ongoing | not started | Required for code signing, regulatory engagement, contracts |
| Tokenomics design + regulatory clearance | $50k–500k | not started | Multi-token committed (§8 layer 6); specifics need counsel |
| Apple Developer ID | $99/yr | not started | macOS binaries quarantined without it |
| Windows code-signing cert | $200–400/yr | not started | Same on Windows |
| Inference API budget or self-hosted GPU | varies | not committed | Real-LLM executors need this |

### Strategic decisions

| Decision | Status | Notes |
|---|---|---|
| Foundation jurisdiction | open | Switzerland / Singapore / Cayman / Wyoming candidates |
| Wedge market choice | open | Sovereign AI / biotech / censored regions / research consortia / on-device fine-tuning |
| Cold-start strategy | open | Subsidies / partnership / killer app — at least one required |
| Specific token mechanics | open within commitment | Multi-token shape committed (§8); distribution, vesting, bootstrap allocations open |
| UCBI activation | open within commitment | Architecturally enabled; political-economic choice |

### Adoption-enabling work

| Item | Cost | Notes |
|---|---|---|
| 5–10 beta testers running nodes | their time | Recruitment, coordination, support |
| Security audit | $2k–40k | Firm engagement, scope decision |
| Hackathon sponsorships | varies | Adoption-pathway item |
| University partnerships | low-cost, time | Research labs as initial nodes |
| Regional ambassador programs | varies | Local operators in priority markets |

### Things the user has NOT yet committed to (open questions)

- Whether to fund 18–36 months of vNext development before any
  revenue.
- Whether vNext gets a dedicated team or stays solo + Claude.
- Whether to pursue the Skynet-scope §9 vision or the more pragmatic
  small-but-deployable target.
- Whether to ship a v1 product (current architecture) for early
  revenue while vNext develops, or focus purely on the rewrite.

**Until at least the critical-path items above start moving, the
network has no deployment path no matter how many sessions of
engineering I do.**

---

## 12. Decentralization portfolio  *[updated S26]*

Decentralization is a tool, not a virtue. Per subsystem, the right
position on the spectrum. Positioning below applies to vNext
subsystems (some don't exist in v1).

**Centralize (or strongly federate):**
- Bootstrap discovery (DNS-anchored + Foundation-operated peers +
  hardcoded fallbacks)
- Genesis Tier-3 validator set (Foundation-signed initial list)
- Code distribution + signing (Foundation-signed binaries; mirrors OK)
- Coordinated security disclosure
- Governance Foundation (year 0–2; sunset criteria explicit)
- Anti-abuse blocklists (signed, opt-in; multiple forks OK)

**Federate (multiple competing centralized actors):**
- Reputation oracles
- Discovery caches
- Tier-3 validator directories
- Managed-daemon onboarding (Coinbase-style entry ramp)

**Hybrid layers:**
- High-stakes multilateral settlement (bilateral L0 + multilateral L1)
- Identity rotation registry
- Observability dashboard (opt-in aggregate)
- Fiat on/off ramps (regulated custodian partnership)

**Keep fully decentralized:**
- Compositor identity (Ed25519 self-issued; cryptographic, no CA needed)
- Work execution (per-node)
- Bilateral compute settlement
- Capability attestation cosig (k-of-n quorum)
- LSH-based routing
- Gossipsub blackboard sync
- ICP envelope chains

**Meta-pattern: progressive decentralization.** Year 0–1 heavy
Foundation involvement; Year 1–3 multiple independent operators per
service; Year 3+ Foundation retains only narrow responsibilities.
Ethereum's path. Filecoin's path.

---

## 13. Strategic positioning  *[slimmer S26]*

Strategic context. User-owned blockers and adoption work moved to
§11; this section keeps only the analytical framing.

### Settled by §8 commitment

- Tokenomics: multi-token committed.
- Foundation entity: required.
- Privacy posture: encrypted-by-default.
- Cryptographic primitives: hybrid PQ + threshold + ZK.

### Still genuinely open

- Wedge market selection (see §11).
- Cold-start strategy (see §11).
- Specific adoption pathway.

### Cold-start problem (the binding constraint)

Real options for breaking it:
1. Wedge market with cryptographic decentralization as hard
   requirement (sovereign AI / regulated jurisdictions /
   censored regions / research consortia / on-device ML).
2. Bootstrap subsidies (first 1000–5000 validators paid directly).
3. One killer app built by Foundation.
4. Strategic partnership with org that has 1000+ machines wanting
   what centralized providers can't serve.

### Tokenomics framing

Every successful decentralized compute network used a tradeable
token (Bittensor, Filecoin, Akash, Render, Helium). The previous
"no token" stance was the single biggest brake on adoption. §8
commits to multi-token; specifics in §11.

### Honest progress assessment

Roughly: 70% protocol, 5% deploy/ops, 0% adoption. The codebase is
a well-engineered prototype. It is not yet a deployable product.
The gap is overwhelmingly operational, strategic, and organizational
— not technical.

---

## 14. Coding conventions  *[updated S26]*

### Don't break the test suite

- Fast slice (§2) before declaring any change "done."
- Touch daemon code → also heavy integration.
- Touch Phase 2 cluster code → also `phase2_integration` / `phase2_hardening`.
- Touch Rust → `cargo fmt --check && cargo clippy -D warnings && cargo test`.

### Pyright noise is not a refactor invitation

If Pyright complains about an import that runs fine, leave it
alone. Lack of `pyrightconfig.json` is intentional.

### Test patterns to copy

- Daemon-spawning integration: `tests/test_netd_client.py::test_message_send_subscribe_two_daemons`.
- Settlement protocol without daemon: `tests/test_settlement.py` (`_FakeBus` + `_make_pair`).
- Runner tests needing chain in envelope log: `tests/test_chain_verification.py::_mark_completed_externally`.
- HLC concurrency: `test_hlc_now_unique_under_concurrent_calls`.
- Wait-until polling: `_wait_until(predicate, timeout_s)` helper. NEVER bare `time.sleep` for async events.
- Metrics assertions: `prometheus_client.REGISTRY.get_sample_value(name, labels)` AND compare DELTAS.
- Reconciliation tests: `tests/test_reconciliation.py::_make_pair` (`_StubReputation` + `_direct_insert`).
- Multi-daemon attestation: `tests/test_attestation_bridge.py`.
- Verify-on-fetch integration: `tests/test_verify_on_fetch.py` (with `dht_mode="server"`).

### Fail-closed observability import wrappers (S9 pattern)

```python
try:
    from gyza.observability import SOME_METRIC as _SOME_METRIC

    def _obs_thing(label: str) -> None:
        _SOME_METRIC.labels(kind=label).inc()
except Exception:  # noqa: BLE001
    def _obs_thing(label: str) -> None:  # type: ignore[misc]
        pass
```

Don't skip the wrapper. Real `ImportError` taking down the runner
because `prometheus_client` wasn't installed is not OK.

### Concurrency invariants

- Every shared HLC instance MUST have a lock.
- `LedgerSettlementService._lock` guards cosigning. Never sign outside.
- `_pending_lock` (S9) is SEPARATE from `_lock`. Don't merge.
- `ReputationStore._lock` guards EWMA.
- Blackboard is thread-local-connection; writes serialize via SQLite WAL.
- Runner's `_run_loop` is single-threaded.
- `DHTAttestationVerifier`: `mu` (cache + inflight) separate from `sem` (concurrency bound). Don't merge.

### Python style

- `from __future__ import annotations` at top.
- Comments explain WHY, not WHAT.
- Type hints on public APIs; not required on internals.
- No emojis.
- No `print()` in library code — use `logging`. CLI may print.

### Rust style (Stream 3 convention)

- Workspace edition 2024, resolver 3, Rust 1.93+.
- `cargo fmt` + `cargo clippy -D warnings` enforced by CI.
- Every public function whose Python equivalent exists gets a
  parity test against fixed fixtures generated by
  `gyza-rs/scripts/regenerate_*_fixtures.py`.
- Bottom-up port order (crypto → identity → icp → core → blackboard →
  …). Each crate depends only on crates beneath it.
- Errors via `thiserror::Error` enum. No `unwrap()` in library code.
- Doc comments use `///` for items, `//!` for crate-level. Maintain
  4-space continuation indent for list items (clippy enforces).

### Don't add files when editing existing ones works

Add methods to existing classes. Don't create `gyza/economy/reputation_helpers.py` for one function.

### Don't write Markdown unless asked

CLAUDE.md, CHANGELOG.md, MIGRATION.md, ADRs, spec docs are the
exceptions. Don't generate ad-hoc `DESIGN.md` / `PLAN.md` /
`NOTES.md`.

---

## 15. Session-start ritual  *[updated S26]*

Every time you open this repo:

1. **Read this file (`CLAUDE.md`) top to bottom.** ~15 minutes.
2. **Read the most recent 3 entries in `CHANGELOG.md`.** ~5 minutes.
3. **Run fast test slice** (~10 min). Confirms environment + no rot.
4. **Run `python demo/single_machine_global.py`** (~17–25s).
   Confirm `Cross-cluster gossip: VALID ✓` + `Bilateral settlement: BILATERAL ✓`.
5. **`cd gyza-rs && cargo test --workspace`** (~5–30s). Confirms
   Rust port still passes parity.
6. **Check `git log --oneline -20`**.
7. **Identify the open priority** (§6, Quick start). Confirm with
   user before committing to a major direction.

If steps 3–5 fail, **stop and diagnose before doing new work.**

**Flaky tests to know about** (don't blame your change without
checking):
- `test_runner_verify_lineage_non_strict_proceeds_when_missing` —
  20s deadline tight on cold ST load. Bump and document if needed.
- `TestSenderSeqDedupRejects` (gossip) — timing-flaky under load.
  Retry in isolation before blaming.

---

## 16. Don't-do list  *[recategorized S26]*

Things a session might be tempted to do that would be wrong. Three
categories: hard rules (never), soft rules (surface to user), and
resolved (was applicable; now closed).

### 16a. NEVER (hard rules)

**Cryptographic / canonical-bytes invariants:**
- **Don't make Python's JSON-canonical cosigs interop with Go's
  det-protobuf cosigs.** Different bytes; non-aggregatable.
  Cross-network wire IS Go protobuf det-marshal.
- **Don't have validators sign DIFFERENT cert payload bytes.**
  Applicant proposes one body; orchestrator passes unmodified.
- **Don't verify ICP envelopes against COMPOSITOR pubkey.**
  Envelopes signed by AGENT identity. Cert binds at compositor.
- **Don't reorder fields in `gyza-rs::gyza-icp::EnvelopePayload`.**
  Alphabetical order is load-bearing for canonical-JSON parity
  with Python.
- **Don't paste Rust parity fixtures from imagination.** Always
  run the Python fixture script first.

**State-machine invariants:**
- **Don't change `EMBEDDING_DIM` from 384.** Constitutional invariant.
- **Don't bypass `verify_chain_before_claim` in tests "for speed."**
  Use the flag explicitly.
- **Don't merge `LedgerSettlementService._lock` and `_pending_lock`.**
- **Don't merge `DaemonSupervisor._lock` and `_proc_lock`.**
- **Don't merge `DHTAttestationVerifier.mu` and `.sem`.**
- **Don't set `WorkItem.ttl_ns=0`** in eval flows. Immediately
  expires.
- **Don't read `LocalCompositor`'s key file expecting compositor
  signing seed.** File holds master seed; signing key is
  HKDF-derived. Pass `.sign` as callable.

**Sandboxing / safety:**
- **Don't reorder bwrap argv in `_build_bwrap_argv`** without
  understanding layering. `--tmpfs /tmp` MUST come before user
  `ro_paths`.
- **Don't bind `/lib64` as `--ro-bind`** on merged-/usr distros.
  Use `--symlink`.
- **Don't pass API keys as bwrap argv.** Use `env_set` (`--setenv KEY VALUE`).

**Attestation invariants:**
- **Don't drop validator plausibility checks on proposed body.**
  Six attack vectors defended.
- **Don't restore the `IcpAgentPubkeyHex == ApplicantPubkey` check
  in `verifyTaskResult`.** Session 13 deliberately removed it.
- **Don't skip validator clock-skew check.** Malicious applicant
  could backdate cert.
- **Don't add a kickoff frame to `/gyza/capability-challenge/1.0.0`.**
  Validator extracts applicant pubkey from libp2p RemotePeer.
- **Don't run the eval before verifying the challenge signature.**
  Slow step; reject malformed challenges first.
- **Don't remove the per-stream deadline (`StreamTimeout = 120s`).**
- **Don't drop the Daemon→Python Outcome frame** on any failure
  path of `RequestAttestation`. Python's read loop deadlocks.
- **Don't use empty `TrustedBootstrap` with `RecursiveVerifier`.**
  All certs rejected.
- **Don't accept a fetched cert whose `ApplicantPubkey` ≠ queried
  pubkey** in `RecursiveVerifier`. Substitution attack.
- **Don't drop cycle detection from `RecursiveVerifier`.**
  Mutual-validation farm attack.
- **Don't cache transient verifier failures** in
  `DHTAttestationVerifier`. Positive + definitive negative only.
- **Don't key the verifier cache by `agent_pubkey`.** Compositor
  pubkey; multiple agents share one compositor and one cert.
- **Don't publish certs with <24h remaining lifetime.** The
  `MinPublishAttestationLifetime` floor is load-bearing.

**Eval invariants:**
- **Don't use `prompt.find("[GYZA_EVAL_TASK=")`. Use `rfind`.**
  `build_enriched_prompt` prepends few-shot context with prior
  tasks' markers.

**vNext commitment:**
- **Don't treat §8 as optional.** Committed Session 17.
- **Don't start vNext layer-2+ work before §C1 is done.**
- **Don't introduce wire-format-breaking changes** without v1↔v2
  compatibility plan.
- **Don't relax the commitment via incrementalism.**
- **Don't conflate v1 codebase with vNext target** in code-writing
  sessions.

### 16b. SURFACE TO USER (soft rules — flag before acting)

- **Don't build Phase 4–9 features on the v1 substrate.** Surface
  the trade-off when asked; v2 is the right substrate.
- **Don't aggressively rewrite for vNext** without confirming with
  user (different from continuing the migration; this is about
  changing scope).
- **Don't ship "maximalist version" features without the
  corresponding safety primitives** (capability bounds, approval
  gates, sunset clauses).
- **Don't lock in specifics that §8 lists as design surface
  remaining.** PQ algorithm, zk-proof system, dataflow engine,
  UCBI activation, voting mechanism.
- **Don't add daemon auto-restart inside `gyza global start`.**
  CLI is one-shot; supervision lives in `GlobalCluster` for
  long-running Python processes.
- **Don't normalize embeddings client-side again.** ST returns
  L2-normalized.
- **Don't use `verify_chain_multi_compositor` in the runner.**
  Plumbing not present.
- **Don't replace SQLite with anything fancier without strong
  reason.**
- **Don't add background reward refresh inside runner.**
- **Don't skip writing tests** for new priority items. The
  test-then-ship pattern of S8.5+ caught real bugs.
- **Don't loosen `AttestationExpiryGrace` past ~minutes.**
- **Don't tune `expirySlack` below the routing horizon.** Default 1h.

### 16c. RESOLVED (was applicable; now closed — for history)

- ~~Don't bypass `find_agents` self-reported tier verification~~
  — closed S15 (verify-on-fetch in routing).
- ~~Don't accept certs near expiry from publish~~ — closed S16
  (24h floor).
- ~~Don't accept any pubkey as Tier-3 validator~~ — partial close
  S16 (RecursiveVerifier shipped; integration is A5).

---

## 17. If something is unclear

Ask the user. The user is the architect, makes scoping calls, owns
strategic decisions (tokenomics, foundation entity, regulatory
posture, Skynet-scope ambition vs. pragmatic v1, what counts as
Tier 3, who runs bootstrap nodes, what credits redeem to). When in
doubt about scope or priority, ask.

When the user says "think really hard like a CS PhD" — that's the
quality bar. Don't ship hand-wavy code. Audit before fixing. Test
the fix. Verify nothing else regressed. State tradeoffs explicitly.
Tell the user when you disagree with the requested direction.

The architecture you're working on is a strong v1 that could grow
into something globally significant. It could also stall. The
trajectory depends on engineering discipline (your job) and
strategic decisions (user's job, §11). Stay in your lane; deliver
the engineering at the quality bar; surface the strategic tradeoffs;
let the user choose.
