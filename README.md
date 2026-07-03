# Gyza

**Run an AI agent — or any command — inside a real sandbox, and get
back a cryptographic receipt of exactly what it did and that it
stayed inside the bounds you granted.** A seatbelt and a flight
recorder for the agents you already run. No account, no API key, no
bill.

**Status:** alpha, Linux only (x86_64 / aarch64), needs bubblewrap
(`bwrap`) for the sandbox. The single-node product below works from
a plain `pip install` with no daemon and no network. The
peer-to-peer layer (join a mesh, delegate work to a stranger's
machine) is real and tested but experimental, and the public
bootstrap mesh is currently offline — see
[Experimental: the network](#experimental-the-network).

---

## Quickstart — local, no network, ~1 minute

```bash
# 1. Install (Linux x86_64/aarch64, Python 3.10+, plus bubblewrap).
pip install gyza          # or: pipx install gyza
#   Debian/Ubuntu: sudo apt install bubblewrap
#   Arch:          sudo pacman -S bubblewrap

# 2. Set up your identity key (~/.gyza/compositor.key).
gyza init

# 3. Run YOUR command inside a bounded sandbox — get a signed receipt.
gyza exec --allow-read . -- ls -la
#   → runs in a bwrap sandbox that can see only what you granted,
#     signs the result, and prints an intent id + audit verdict.

# 4. Turn the run into a portable receipt anyone can check — with no
#    node, no daemon, no identity, and no trust in you.
gyza bundle <intent-id> -o receipt.json
gyza verify receipt.json         # a third party runs exactly this
```

`gyza exec -- <command>` and `gyza run "<task>"` both execute inside a
manifest-derived bwrap sandbox (memory cap, filesystem allowlist,
fresh network namespace), fold a tamper-evident enforcement record
into a signed provenance envelope, and end in a receipt you can hand
to someone else. What it proves: **accountability** (every action
signed and attributable) and **containment** (the run provably stayed
within the bounds you granted — it can't touch your home or secrets).
What it does *not* prove: that the output is *correct* — that's still
a human call.

### Local demos — no network, no API key

```bash
gyza demo bounds          # a sandboxed task is signed; an adversary
                          # forges the enforcement record (caught) and
                          # a wider sandbox is refused. ~2 s.
gyza demo pipeline        # two agents, a signed provenance chain
gyza demo injection       # tamper a chain, re-verify — watch it fail
```

Install from source instead:

```bash
git clone https://github.com/aaronamire/gyza && cd gyza
pip install -e .              # puts the `gyza` CLI on PATH
gyza init
make -C netd build            # OPTIONAL: the Go network daemon (Go 1.22+)
```

---

## Experimental: the network

Gyza's larger aim is to let you delegate an agent task to a machine
you don't own and get back the same signed, bounded receipt. That
peer-to-peer layer is implemented and tested (two daemons on
loopback complete a project through a real comms blackout and
bilateral settlement — `gyza demo global --fast`), but it is
experimental and needs the Go daemon (`gyza-netd`), which is **not**
shipped in the pip package — build it from a source checkout with
`make -C netd build`, or put a `gyza-netd` binary on PATH.

The public bootstrap mesh (`gyza.network`) is **currently offline**,
so `gyza global start` / `gyza submit` won't reach live peers right
now. The commands still work against your own daemons:

```bash
gyza demo global --fast   # two local daemons, a real blackout, a
                          # 2-envelope chain that verifies across it (~22 s)
gyza global start         # start a local daemon (needs gyza-netd)
```

---

## What it is

Today, using an AI model means trusting a company: you send your
prompt to their servers, they send back an answer, and you take on
faith that nothing else happened. You can't verify which model ran,
what it was allowed to touch, or whether it stayed in bounds.

Gyza is a peer-to-peer network that removes that blind trust. You
post a task; an independent node somewhere on the internet runs it
**inside a kernel-enforced sandbox**; it signs the result into a
tamper-evident provenance record; and your own machine
**independently re-verifies** — with no trust in the operator —
that the answer was produced by the agent it claims, and that the
agent ran inside a sandbox no wider than the capabilities it
publicly declared.

There is no central server, no account, and no API key. Nodes find
each other over libp2p, settle compute credits between themselves,
and prove their capabilities to each other cryptographically. The
result is a way to get AI work done on infrastructure nobody owns —
and still know exactly what happened.

---

## What you get back

A `gyza submit` returns the answer **and** a verification block.
Every line is something your own machine checked locally:

```
  RESULT
  A Merkle tree is a data structure that organizes data into a
  tree of cryptographic hashes ...
  PROVENANCE
  signed by:     95aa2e6f…        model: claude-sonnet-4-5
  signature:     ✓ VALID
  artifact hash: ✓ MATCHES envelope
  BOUNDS-PROOF (committed in the signed artifact)
  sandbox:       bubblewrap (kernel-enforced)
  fs read:       NONE (no host filesystem)
  fs write:      NONE (no host filesystem)
  memory cap:    512 MB     cpu cap: 300 s
  manifest hash: ✓ MATCHES envelope
  bounds check:  ✓ enforcement ⊆ manifest (re-verified here)
  runner build:  0.1.1  ✓ trusted release
  ✓ bounded (INDEPENDENTLY VERIFIED + RUNNER ATTESTED)
```

That bottom line is the point: a valid signature *plus* an
enforcement record that your machine re-checked against the agent's
declared manifest means the work **provably** ran inside those
bounds — not "the operator says so."

---

## How it works

### Identity

Every node holds one 32-byte master seed at `~/.gyza/compositor.key`.
From it the system derives a **compositor** signing key and, per
agent, an independent agent key via HKDF. Self-sovereign: no
certificate authority, no registration server. Two nodes that have
never met verify each other's signatures from public keys alone.

### Provenance — the ICP envelope

Every meaningful action emits one `ICPEnvelope`: a dataclass of
`agent_pubkey`, `capability_manifest_hash`, `input_hashes`,
`output_hash`, `parent_envelope_hash`, model, timing, signature.
Canonical JSON → BLAKE3 hash → Ed25519-sign-the-hash. Each
envelope's `parent_envelope_hash` pins the previous one, so the
chain is structurally immutable: edit any past field and its
signature breaks; splice in a fake envelope and the next real one's
parent link breaks. `gyza demo injection` proves this live —
it tampers a real chain and shows verification fail.

### Bounded execution — the bounds-proof

The distinctive piece.

1. **The manifest is the source of truth.** The sandbox an agent
   runs in (filesystem read/write paths, network, memory cap) is
   derived directly from its signed capability manifest.
2. **Execution runs inside the sandbox.** The model call executes
   inside [bubblewrap](https://github.com/containers/bubblewrap)
   with exactly those bounds, kernel-enforced.
3. **Refuse-to-sign-if-not-enforced.** A host-side enforcement
   record (backend, paths, network, memory) is stamped onto the
   result; the runner refuses to sign unless that record is no
   wider than the manifest, and folds it into the artifact so the
   envelope's hash commits to it.
4. **Trustless verification.** The result delivery carries the
   agent's manifest bytes. `gyza submit` re-hashes them, re-runs
   the bounds predicate locally, and prints one of five honest
   verdicts — the strongest being `INDEPENDENTLY VERIFIED +
   RUNNER ATTESTED`.

### Networking

A Go daemon (`gyza-netd`) owns the network layer: a libp2p host
(QUIC + Noise + yamux), a Kademlia DHT for discovery, gossipsub for
cross-node sync, NAT traversal (DCUtR + circuit relay), and
DNS-anchored bootstrap with periodic re-resolution — a node that
loses every peer self-heals back onto the mesh instead of becoming
an island.

### Economic settlement

A bilateral compute-credit ledger. Each settled entry is signed by
both parties; both ledgers end byte-identical. A reconciliation
exchange heals divergence. A per-peer reputation signal (EWMA)
feeds future work-claim scoring.

### Capability attestation

Three tiers gate which agents may claim which work. Tier-3 is full
proof-of-capability: a *k*-of-*n* quorum of independent validators
runs the applicant through a canonical eval suite and co-signs a
certificate, published to the DHT. When any node looks up agents,
the daemon re-verifies every co-signature before returning a
result — self-reported tiers are never trusted.

### Three implementations

| Implementation | Owns | Status |
|---|---|---|
| **Python** (`gyza/`) | Execution, identity, ICP, ledger, sandbox, CLI | full |
| **Go** (`netd/`) | The libp2p daemon | full |
| **Rust** (`gyza-rs/`) | Reference implementation, 7 of ~8 crates | in progress |

Byte-parity is asserted across implementations for hashing,
signatures, key derivation, canonical encodings, settlement entries,
and the Tier-3 capability protocol — including the recursive
canonical-JSON of nested arbitrary maps inside `ChallengeResponse`.
For Ed25519 cosigs on attestation certs the parity is stronger than
"mutually verifiable": Rust and Python produce **byte-identical
signatures** for the same seed and payload (RFC 8032 is
deterministic; the byte parity holds all the way through). A Rust
validator and a Python validator are interchangeable in a quorum.

---

## Security model

**What you get**

- **Tamper-evidence** — any edit to a past envelope breaks its
  signature and every downstream link.
- **Authorship** — every envelope binds to an Ed25519 identity.
- **Bounded execution, independently verifiable** — a verified
  result implies the work ran in a kernel-enforced sandbox no
  wider than the agent's declared manifest.
- **Sybil resistance** for high-tier work via quorum attestation.

**What you do not get (honest limits)**

- **Confidentiality** — envelopes are signed, not encrypted;
  artifacts are stored in plaintext.
- **Fully trustless runner identity** — the runner self-reports
  which build it is; a malicious build could lie about its own
  hash. Trusted-release checking narrows this, but closing it
  fully needs reproducible builds + hardware attestation (TEE).
- **Per-host network enforcement** — the sandbox's network is
  all-or-nothing; a declared host allowlist is not yet
  kernel-enforced (the output labels this honestly).
- **Quantum resistance** — Ed25519 today.

Honesty about the limits is deliberate — it's what makes the
verdicts trustworthy.

---

## Roadmap

Near-term, concrete:

- Per-host network enforcement (a filtering proxy in the sandbox).
- CPU-time bound checked in the verification predicate.
- Reproducible builds + a signed release manifest, tightening
  runner attestation toward hardware-backed (TEE).
- macOS / Windows signed binaries.
- Broadening the Rust reference implementation.

---

## Running the tests

```bash
# Python fast slice (~10 min): unit + protocol, no real daemons.
python -m pytest tests/ -q --tb=line --timeout=90 \
  -k "not netd_client and not phase2_integration and not phase2_hardening \
      and not blackboard_gossip and not attestation_bridge and not verify_on_fetch"

# Go daemon (~5 s).
cd netd && go test ./... -count=1 -timeout=120s

# Rust workspace.
cd gyza-rs && cargo test --workspace
```

~560 Python fast tests + the Go suite + the Rust workspace
(~94 tests across 7 crates). CI runs the fast slice and the
Go/Rust suites on every push.

---

## Layout

```
gyza/      Python — execution, identity, ICP, ledger, sandbox, CLI
netd/      Go — the gyza-netd daemon (libp2p, DHT, NAT, gossip)
gyza-rs/   Rust — reference implementation (workspace of crates)
tests/     pytest suite
demo/      runnable end-to-end demos
scripts/   install.sh + bootstrap deploy tooling
```

---

## Contributing

Issues and pull requests welcome at
<https://github.com/aaronamire/gyza>. It's alpha — bug reports
from real installs are especially useful.

## License

Apache 2.0. See `LICENSE`.
