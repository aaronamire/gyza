# Gyza

**Run an AI task on a machine you don't own — and get back a
cryptographic proof of who ran it and that it stayed inside safe,
declared bounds.** No account, no API key, no bill.

**Status:** alpha. Linux only (x86_64 / aarch64). The protocol is
whole, tested, and live on a public mesh; treat it as early
software.

---

## Quickstart

Four steps from nothing to a verified answer.

```bash
# 1. Install (Linux x86_64/aarch64, Python 3.10+, pipx).
#    Also generates your identity key (~/.gyza/compositor.key).
curl -sSf https://raw.githubusercontent.com/aaronamire/gyza/main/scripts/install.sh | bash

# 2. Start your node — it joins the public mesh automatically
#    (3 DNS-anchored bootstrap peers, no other setup).
gyza global start
gyza global status        # give it a few seconds: dht_peers / connections

# 3. Ask the network a question. A hosted agent somewhere on Earth
#    runs it in a sandbox and pushes back a signed result; your
#    machine verifies it locally.
gyza submit "In one sentence, what is a Merkle tree?"

# 4. Local demos — no network needed.
gyza demo pipeline        # two agents, a signed provenance chain
gyza demo injection       # tamper a chain, re-verify — watch it fail
gyza demo global          # two nodes settle a job end-to-end (~30s)
```

`gyza submit` is the product; step 2 just brings your node onto the
mesh first. If the public demo agent's daily quota is exhausted you
get a clear "demo quota reached" message — the protocol path is
identical, and you can always reproduce the full result against
your own node.

Install from source instead:

```bash
git clone https://github.com/aaronamire/gyza && cd gyza
make -C netd build            # builds netd/bin/gyza-netd (Go 1.22+)
pipx install --editable .     # puts the `gyza` CLI on PATH
gyza init
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
| **Rust** (`gyza-rs/`) | Reference implementation, 6 of ~8 crates | in progress |

Byte-parity is asserted across implementations for hashing,
signatures, key derivation, canonical encodings, and settlement.

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

~560 Python fast tests + the Go suite + the Rust workspace. CI
runs the fast slice and the Go/Rust suites on every push.

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
