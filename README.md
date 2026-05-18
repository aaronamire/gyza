# Gyza

> A sovereign AI you own — it works for you, funds itself by doing
> verifiable bounded work on a network no one controls, and nobody
> can deplatform it, throttle it, read it, or switch it off. The
> ownerless economy and the bounded planetary organism are simply
> what that one thing becomes when there are millions of them.

**Status:** alpha. Linux only (x86_64 / aarch64). The protocol is
whole, tested, and live on a public mesh; the deployment and
economic-autonomy surface is deliberately thin and gated (see
[The agentic civilization](#the-agentic-civilization) and
[L1 roadmap](#l1-roadmap)).

One sentence: **Gyza is a sovereign AI you own that funds itself by
doing verifiable bounded work on a network no one controls — and the
ownerless economy and the bounded organism are what that one thing
becomes at scale, held non-catastrophic by a single invariant: every
action proves its own bound, and bounds compose upward.**

---

## Run it

Everything you need to see Gyza work, in a few commands.

```bash
# 1. Install. Linux x86_64 / aarch64, Python 3.10+, pipx required.
#    (The installer also runs `gyza init` to generate your identity.)
curl -sSf https://raw.githubusercontent.com/aaronamire/gyza/main/scripts/install.sh | bash

# 2. Start your daemon — it joins the public mesh (3 DNS-anchored
#    bootstrap peers) automatically, no other setup.
gyza global start
gyza global status            # dht_peers / connections — give it a few seconds

# 3. THE one that matters: ask the live network a question. A hosted
#    agent on someone else's machine, somewhere on Earth, answers it
#    inside a kernel-enforced sandbox — and your machine
#    independently re-verifies the answer was produced within the
#    bounds the agent declared. No account. No API key. No bill.
gyza submit "In one sentence, what is a Merkle tree?"

# 4. Local demos — no network needed.
gyza demo pipeline            # two agents, signed envelope chain
gyza demo injection           # tamper-detection: mutates a chain, re-verifies, fails
gyza demo global              # two daemons on loopback → bilateral settlement (~30s)
```

`gyza submit` is the product — step 2 just brings your node onto
the mesh first (`submit` talks to the network through your running
daemon). The demos in step 4 run fully offline. Bootstrap peers are
DNS-anchored, the daemon dials them automatically, and a
long-running daemon self-heals back onto the mesh if it ever loses
every peer (see [Networking](#networking)).

From source:

```bash
git clone https://github.com/aaronamire/gyza
cd gyza
make -C netd build              # builds netd/bin/gyza-netd (Go 1.22+)
pipx install --editable .       # installs the gyza CLI on PATH
gyza init
```

---

## What it is

Gyza lets independent computers run AI work for each other while
leaving behind a cryptographically verifiable record of **who did
what, and that they stayed inside the bounds they declared** —
checkable by the requester with no trust in the operator.

Every node has a self-issued **compositor identity** (Ed25519
keypair) that mints **agent identities** for the work-doers. Work
roots in a human-signed **intent**, is claimed atomically by an
agent on any node, executed **inside a kernel-enforced sandbox**,
and signed into an **ICP envelope** that hash-chains to the prior
one. The envelope carries an **enforcement record** of the exact
sandbox bounds the work ran under; the requester re-hashes the
agent's manifest and re-runs the bounds predicate locally — a
signed result that satisfies it *implies* bounded execution, not
"the operator promised."

Across nodes a Go daemon (`gyza-netd`) speaks libp2p (QUIC + Noise +
gossipsub + Kademlia DHT) so nodes discover each other, gossip the
blackboard, and settle compute credits bilaterally. For high-stakes
work, agents prove capability via **Tier-3 k-of-n quorum
attestation**.

Three parity-tested implementations: Python (execution, identity,
ICP, ledger, sandbox, CLI), Go (the libp2p daemon), Rust (vNext
reference, 6 of ~8 crates).

**Where this is going:** the single sentence above is the whole
project. What runs today is the *cell* — a sovereign, bounded,
self-verifying agent. The [agentic civilization](#the-agentic-civilization)
section is the honest, graded trajectory from that cell to an
ownerless economy and a bounded planetary organism, and exactly
which parts are real, plausible, or deliberately gated.

---

## How it works

### Identity

One 32-byte master seed at `~/.gyza/compositor.key` (mode 0600)
deterministically derives the compositor signing key and each agent
key via `HKDF(master, salt="compositor", info=agent_label)`.
Self-sovereign: no CA, no registration server. Two compositors that
never met verify each other from public keys alone. The agent's
pubkey is also its **account** — its wallet is a projection over
settled ledger entries keyed by that key (see
[L1 roadmap](#l1-roadmap)).

### Provenance — the ICP envelope

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

Canonical JSON → BLAKE3 → Ed25519-sign-the-hash. `parent_envelope_hash`
points at the BLAKE3 of the previous envelope, so the chain is
structurally immutable: mutating any field breaks that envelope's
signature; inserting a fake one breaks the next real
`parent_envelope_hash`. `gyza demo injection` proves it live.

**This DAG is also the structure over which boundedness composes**
(see [the bounds-proof](#bounded-execution--the-bounds-proof) and
[compositional boundedness](#the-agentic-civilization)).

### Bounded execution — the bounds-proof

The keystone. Shipped and exercised end-to-end on the public mesh.
The hosted demo agent runs behind a funded daily quota; when the
quota is exhausted `gyza submit` returns a clear "demo quota
reached" message (not an error) and the protocol/verification path
is unchanged — you can always reproduce the full bounds-proof
locally against your own daemon.

1. **Manifest is the single source of truth.**
   `sandbox_config_from_manifest()` derives the bwrap sandbox
   (filesystem read/write paths, network on/off, memory cap)
   directly from the agent's signed capability manifest. Declared
   bounds ≡ enforced bounds by construction.
2. **Execution runs inside the sandbox.** The hosted agent's model
   call (e.g. Anthropic) executes inside bubblewrap with exactly
   the manifest's bounds. `run_sandboxed` *raises* rather than
   silently degrading an enforcing backend to none.
3. **Refuse-to-sign-if-not-enforced.** `make_sandboxed_executor`
   stamps a host-side `__enforcement__` record (backend, ro/rw
   paths, network, memory cap) the sandboxed code cannot forge. The
   runner refuses to sign unless `enforcement_satisfies_manifest`
   holds (the sandbox is no wider than the manifest), and folds the
   record into the artifact so the envelope's `output_hash`
   *cryptographically commits* to the bounds the work ran under.
4. **Trustless verification.** The result delivery carries the
   canonical manifest bytes. `gyza submit` re-hashes them
   (`= envelope.capability_manifest_hash`), re-runs the predicate
   locally, and prints one of five honest verdicts — the strongest
   being **`✓ bounded (INDEPENDENTLY VERIFIED + RUNNER ATTESTED)`**.
   No trust in the executor's runner.
5. **Runner attestation (G1a).** The runner stamps its release
   identity `(version, source_tree_hash)`; the submitter checks it
   against a `trusted_releases.json` that ships in *its own*
   client. Honest about the residual (a binary can lie about its
   own hash → TEE closes it; ADR-0017/0018).

The bounds-proof is **not the pitch — it's the physics.** At n=1
it's the brick-3 gate; at scale it's a fold over the ICP DAG with
`enforcement_satisfies_manifest`. It's why a planetary autonomous
network can be an organism instead of the villain.

ADRs: 0016 (soundness theorem + named assumptions), 0017 (runner
attestation), 0018 (trusted-release fixed-point dissolution).

### Blackboard + work items

SQLite WAL at `~/.gyza/blackboard.db`: `intents` (human-signed
roots), `work_items` (atomic-claim by `UPDATE ... WHERE claimed_by
IS NULL`), `envelope_log` (append-only), `artifacts`
(content-addressed). The runner loop: poll → score by
`cosine(work.embed, my_spec) × demand × reward` → atomic claim →
execute (sandboxed) → sign → loop. 384-dim
`all-MiniLM-L6-v2` embeddings; shared-hyperplane LSH for sub-linear
semantic lookup across Python and Go.

### Networking

The Python stack offloads networking to `gyza-netd` over gRPC on a
Unix socket. The daemon owns:

- **libp2p host** — QUIC v1 + Noise + yamux on UDP/7749
- **Kademlia DHT** — provider records for `find_agents` + Tier-3
  cert publication; 24 h minimum TTL
- **Gossipsub** — `/gyza/blackboard/1.0.0` signed, seq-deduped
  delta sync
- **NAT traversal** — DCUtR hole-punching, circuit-relay-v2 fallback
- **DNS-anchored bootstrap + self-healing** — resolves
  `_dnsaddr.gyza.network` TXT records (and compiled-in pinned
  fallback peers) at startup, **and re-resolves + re-dials every
  `--rebootstrap-interval` (default 2 m)**. A daemon that loses
  every peer (bootstrap restart, NAT churn, sleep) recovers on its
  own instead of becoming a permanent DHT island. Re-resolving
  each tick also makes DNS-based peer rotation live.

Custom stream protocols: `/gyza/message/1.0.0`,
`/gyza/capability-challenge/1.0.0`, `/gyza/settlement/1.0.0`. The
executor → submitter result push carries envelope + artifact +
**manifest bytes** so the submitter can independently verify the
bounds-proof.

LAN-only Phase 2 still works (QUIC+Noise+mDNS+Raft); `gyza demo lan`.

### Economic settlement

Bilateral compute-credit ledger (`gyza/economy/`). Every settled
entry dual-signed; both ledgers end byte-identical.

| State | Who signs | Guard |
|---|---|---|
| `earner_signed` | earner Ed25519 | envelope in earner's blackboard |
| (payer validates) | — | earner sig, envelope hash, amount ±20%, **bounds-proof** |
| `payer_cosigned` | payer Ed25519 | dual-sig verifies |
| `settled` | — | byte-identical entries |
| `disputed` | — | any guard fails; no balance change |

Reconciliation RPC heals divergence (`spec/Reconciliation.tla`).
Per-peer EWMA reputation feeds claim scoring. Binding credit-mint
to the bounds-proof in the payer-validate step is **Proof of Useful
Cognition** — the mint and the safety keystone are the same check
(see [L1 roadmap](#l1-roadmap)).

### Capability attestation

Tier-0 (none) / Tier-1 (in-process challenge) / Tier-3 (k-of-n
quorum cosignature). Tier-3: applicant runs the canonical eval
suite → proposes one `AttestationBody` → ≥k independent validators
run 6 plausibility checks and cosign → `AttestationCert` published
to DHT under `/gyza/attestations/<pubkey>` (24 h min lifetime).
**Verify-on-fetch:** `find_agents` re-validates every cosig before
returning; self-reported tiers are never trusted on the routing
path. `spec/Attestation.tla`, honest + adversarial model-checked.

### Three reference implementations

| Impl | Owns | Status |
|---|---|---|
| **Python** (`gyza/`) | Execution, identity, ICP, ledger, sandbox, CLI | Full Phase 3 + bounds-proof |
| **Go** (`netd/`) | Daemon: libp2p, DHT, NAT, gossip, capability wire, self-healing bootstrap | Full Phase 3 |
| **Rust** (`gyza-rs/`) | vNext reference — 6 of ~8 crates, settlement parity ✓ | In progress |

Cross-language byte-parity: BLAKE3, Ed25519, HKDF, ICP canonical
JSON + signatures, blackboard schema, settlement canonical bytes.

---

## Security model

### What you get

- **Tamper-evidence** — any past-envelope edit breaks its signature
  and every downstream parent link (`gyza demo injection`).
- **Authorship attribution** — every envelope binds to an Ed25519
  pubkey whose manifest the compositor signed.
- **Bounded execution, independently verifiable** — a signed result
  that passes the submitter's local re-check *implies* the work ran
  in a kernel-enforced sandbox no wider than the agent's manifest.
  Five honest verdict states; the strongest requires the runner to
  be a trusted release.
- **Sybil resistance for Tier-3** — verify-on-fetch enforces a
  fetchable, valid k-of-n cert from independent compositors.
- **Self-healing reachability** — periodic re-bootstrap; a node
  can't be permanently islanded by transient peer loss.

### What you do **not** get (honest residuals)

- **Liveness / availability** — a signed chain proves what
  happened; it doesn't stop someone pulling the plug.
- **Confidentiality** — envelopes signed, not encrypted; artifacts
  plaintext. (Encrypted-by-default is vNext.)
- **Defense against a stolen seed** — a leaked agent seed signs
  valid-looking envelopes; recourse is compositor revocation.
- **Honest self-report of the runner binary** — G1a moves trust
  from "the operator" to "a binary that self-reports a trusted-
  release hash," but a malicious binary can still lie about its own
  hash. Closed only by reproducible builds + third-party
  attestation → Foundation-signed manifest → TEE
  (ADR-0017/0018, ranked path).
- **Quantum resistance** — Ed25519 only; PQ hybrids are vNext.
- **Per-host network enforcement** — bwrap is all-or-nothing on the
  network namespace; `allowed_hosts` is declared, not kernel-
  enforced (labeled honestly; G2 on the roadmap).

Honesty about the residuals is deliberate and load-bearing — it's
what makes the verdicts trustworthy.

---

## The agentic civilization

This is the trajectory, graded honestly. Gyza is **one object at
three radii** — you don't build three things; you build the cell
and the rest is what it becomes.

**Radius 0 — the person (the soul). Mostly real today.** A
sovereign AI you own: persistent self-issued identity ✓, hash-
chained provenance ✓, kernel-bounded execution with independent
verification ✓ (live). Missing: a **wallet** (a projection over
settled entries) and the **subcontract loop** (it posts child
intents with bounties and pays for sub-work it can't do). Small,
precise deltas over primitives that already exist.

**Radius 1 — the economy (the machine). Emergent; small-N
buildable, at-scale gated.** The ownerless verifiable labor market
is the *sum* of many radius-0 agents transacting — not a separate
product. Bilateral L0 settlement ✓ suffices for radius 0 and small
N. **Proof of Useful Cognition** = credits mint *iff* a valid
bounds-proof exists — the mint and the safety keystone are the
same ~20 lines in the payer-validate path. Full graph-wide credit
fungibility requires multilateral clearing (L1), which is
deliberately **not built**.

**Radius 2 — the organism (a bounded autonomous network). Further out.**
Self-improvement under economic selection (seeds: `drift.py`,
`supervisor.py`, `reward.py`), a treasury-funded immune system
(= the economy turned adversarial), and a governed treasury. Its
safety is **compositional boundedness**: a fold over the existing
hash-chained ICP DAG applying `enforcement_satisfies_manifest` at
each hop. Safety isn't bolted on top — it grows from the leaf.

**The throttle — one line, three coincident gates.** The point
where credits become fungible across the whole graph (multilateral
**L1**) is *simultaneously*: the technical boundary where bilateral
L0 stops sufficing, the legal cliff where credits become a token
(securities/MTL — requires an adult-backed legal entity), and the
governance throttle where the autonomous organism becomes
economically self-propelling. They are the same line. You cannot
cross it by accident — crossing it is a deliberate, large protocol.
**Build all three radii; let only radius 0 run free; gate L1 behind
the legal entity and governance.**

The discipline: ship the cell, fund it with a credibly-neutral
verifiable-AI oracle beachhead, let the economy and organism
*emerge* — never faster than the bounds that keep it ours.

---

## L1 roadmap

What's left to make the cell of the agentic civilization real and
launchable. Ordered; the seed is first because everything reads
from it.

### The seed (weeks — wiring over existing primitives)

- [x] **`gyza/economy/wallet.py` — the wallet projection.** ✅ Pure
  read model: `net_balance(pubkey)` / `statement(pubkey)` folded
  over settled bilateral entries in exact integer micro-credits
  (never float), idempotent by `entry_id` (a double-count is a
  silent mint), settled-only spendable, defensively excludes
  self-dealing / conflicts. `Credits` is a typed, explicitly
  non-monetary fake unit (`TOKEN_IS_FAKE`). 21 tests. *The organ
  that makes an agent economically alive — done.*
- [ ] **Personal-agent mode** — the hosted agent with `settle=True`
  (the earn loop already exists; it's one boolean off the public
  demo).
- [ ] **The dual-role subcontract loop** — one identity that earns
  (runner) *and* spends (posts child intents with a bounty, awaits
  result delivery, runs the existing payer cosign). Built from
  `post_intent` + `result_delivery` + the settlement payer path —
  all of which exist. Delegated capability must be ⊆ the agent's
  own manifest (compositional boundedness, recursive
  `enforcement_satisfies_manifest`).
- [ ] **Continuity-v1** — identity seed + wallet reconstructable
  from signed settled envelopes (memory portability deferred).

### Plausible (months — control loops on existing primitives)

- [ ] **Proof of Useful Cognition** — bind credit-mint to a valid
  bounds-proof (and, for high value, a Tier-3 cosig) inside
  `settlement.payer_validate`. The mint = the safety keystone.
- [ ] **Bounty field + profitability filter** — additive
  intent/work-item schema field; runner claims iff
  `E[bounty] > E[cost] + risk`.
- [ ] **Evolutionary supervisor** — wire `AgentSupervisor` spawn/
  retain to the wallet projection (credit-starved variants not
  respawned; profitable specializations spawn variants).
- [ ] **Treasury** — protocol fee fraction to a governed pubkey in
  the settlement entry (governance of it is gated, below).

### Hardening / launch surface

- [ ] **G2** — per-host network enforcement (filtering proxy in the
  sandbox net namespace or TEE) — the one MEDIUM bounds residual.
- [ ] **G3** — CPU-time bound in the predicate (mechanical; mirror
  the memory check; needs a manifest `cpu_seconds_max` field).
- [ ] **G1a → G1b** — reproducible builds + third-party attestation
  → Foundation-signed release manifest → TEE.
- [ ] **Packaging** — `pyproject.toml` ✓ (hatchling, `force-include`
  ships `trusted_releases.json`); `scripts/cut_release.py` ✓
  (self-checks the fixed point); macOS/Windows signed binaries
  (user-owned certs, §11).
- [ ] **Cut `0.1.0` at launch** — `cut_release.py` flips the runner
  verdict to `+ RUNNER ATTESTED`; do it *with* the public launch,
  not before (a stale release by launch day helps no one).
- [ ] **`gyza demo` (escape-caught, local, no infra)** — a 60 s
  zero-network demo where an agent *tries to leave its sandbox*,
  gets caught, and the bounds-proof is verified locally. The
  artifact that travels; first impression can't depend on the
  fragile mesh.

### Gated behind the legal entity + governance (§11 / vNext)

- [ ] **Multilateral L1 fungible clearing** — the throttle line.
  Technical L1 boundary = legal token cliff = governance throttle.
  Deliberate, large, not crossed by accident.
- [ ] **Treasury governance** — must *lead* the economy, not lag it.
- [ ] **The credibly-neutral oracle beachhead** — same primitives
  at a fundable B2B altitude; funds the runway to radius 0 at
  scale.

---

## CLI reference

```bash
gyza init                            # generate compositor key + scaffolding
gyza status                          # blackboard + artifact + cluster stats
gyza submit "<question>"             # ask the live network; verify the bounds-proof locally
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
# Fast slice (~10 min): unit + protocol, no real daemons.
python -m pytest tests/ -q --tb=line --timeout=90 \
  -k "not netd_client and not phase2_integration and not phase2_hardening \
      and not blackboard_gossip and not attestation_bridge and not verify_on_fetch"

# Heavy integration (~1 min warm): spawns real daemons.
python -m pytest tests/test_netd_client.py \
  tests/test_network_blackboard_gossip.py tests/test_attestation_bridge.py \
  tests/test_verify_on_fetch.py -q --timeout=240

# Go daemon (~5 s) — includes the host re-bootstrap recovery test.
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

Coverage: ~560 Python fast tests + Go suite (incl. bootstrap-
recovery) + 71 Rust tests + 5 TLA+ model checks. `main` is gated on
the fast slice + Go/Rust suites via GitHub Actions; heavy
integration runs nightly and on touch of `netd/` or `gyza/network/`.

---

## Layout

```
gyza/                # Python — execution, identity, ICP, ledger, sandbox, CLI
├── schema.py            WorkItem / Artifact / HLC
├── blackboard.py        SQLite WAL + atomic claim + TTL filter
├── icp.py               ICPEnvelope; single/multi-compositor verify_chain
├── identity.py          LocalCompositor + AgentIdentity + manifests
├── release.py           runner release identity (G1a) + trusted-set loader
├── trusted_releases.json  trusted-release policy data (ADR-0018; not in source hash)
├── runner.py            AgentRunner + executor backends + bounds-proof gate
├── sandbox/             bwrap config-from-manifest + enforcement predicate + stamp
├── economy/             bilateral ledger + settlement + reputation  (wallet: roadmap)
├── network/             Phase-2 LAN + Phase-3 daemon client + global cluster + result delivery
└── cli.py               gyza CLI (incl. `gyza submit`)

netd/                # Go — gyza-netd daemon
├── cmd/gyza-netd/       entry point (+ --rebootstrap-interval)
└── internal/{identity,host,dht,discovery,nat,gossip,message,capability,bootstrap,grpc}/
    └── host/            ConnectBootstrap + StartBootstrapLoop (self-healing)

gyza-rs/             # Rust — vNext reference (6 crates: crypto, identity, icp, core, blackboard, settlement)
spec/                # TLA+ — Settlement, Reconciliation, Attestation (honest + adversarial)
docs/                # invariants, state machines, wire protocol, ADRs 0001–0018
scripts/             # install.sh, deploy-bootstrap.sh, verify-bootstrap.sh, cut_release.py
tests/               # pytest
demo/                # runnable end-to-end demos
```

---

## License

Apache 2.0. See `LICENSE`.
