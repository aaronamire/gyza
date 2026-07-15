# Gyza

**Run an AI agent — or any command — inside a real sandbox, and get
back a cryptographic receipt of exactly what it did and that it
stayed inside the bounds you granted.** A seatbelt and a flight
recorder for the agents you already run. No account, no API key, no
bill.

**Status:** alpha, Linux only (x86_64 / aarch64), needs bubblewrap
(`bwrap`). It runs locally from a source checkout — no daemon, no
network, no PyPI package yet (publishing is on the roadmap; install
from source today). There is also an experimental peer-to-peer layer
for delegating a run to a machine you don't own; it's real and tested
but off by default and the public mesh is currently offline — see
[The network (experimental)](#the-network-experimental).

---

## Quickstart — local, no network, ~2 minutes

```bash
# 1. Install from source (Linux x86_64/aarch64, Python 3.10+, plus bubblewrap).
git clone https://github.com/aaronamire/gyza && cd gyza
pip install -e .              # puts the `gyza` CLI on PATH
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

---

## What you get back

Everything below is real output from `gyza demo bounds` on a source
build — every line is recomputed locally from the signed bytes, with
zero trust in the machine that produced the run:

```
  INDEPENDENT VERIFICATION
  signature:      ✓ VALID
  artifact hash:  ✓ MATCHES envelope
  manifest hash:  ✓ MATCHES envelope
  bounds check:   ✓ enforcement ⊆ manifest (re-verified here)
  runner build:   ⚠ unverified (dev tree, not a tagged release)

  ✓ bounded (INDEPENDENTLY VERIFIED)
    — manifest re-hashed and bounds predicate re-run here.
```

That verdict is the point: a valid signature *plus* an enforcement
record your machine re-checked against the agent's declared manifest
means the work **provably** ran inside those bounds — not "the
operator says so." A tagged release adds the last half,
`+ RUNNER ATTESTED`; a dev tree honestly withholds it rather than
faking it.

Handed to someone else as a receipt, the same evidence verifies
offline with no identity and no trust in you:

```
GYZA EVIDENCE VERIFY — bundle b92e0746ed9f281b…
Provenance graph: INTACT  (1 action, 1 root / 1 leaf)
  [exec ] OK   019f6621-…
VERDICT: VALID
  Accountable (every action signed + attributable),
  contained (every action within its granted bounds),
  bounds-compliant (no capability laundering).
  NOT a claim about output correctness — that needs a human on the loop.
```

---

## What it is

Handing an AI agent access to your shell, files, or network means
trusting that it did only what it should — and after the fact, the
only record of what happened is written by the same process you'd want
to audit. If it misbehaves (or a dependency, or a prompt injection
does), the log is exactly as trustworthy as the thing that produced
it.

Gyza is a **local tool that makes an agent run provable.** It executes
your command or agent inside a kernel-enforced [bubblewrap][bwrap]
sandbox derived from a signed capability manifest, and produces a
tamper-evident receipt that **anyone can re-verify** — establishing
which agent produced the result and that it ran inside a sandbox no
wider than the capabilities it declared. No central server, no
account, no API key. It runs on one machine, offline, and the receipt
it emits is portable.

There is a longer-term aim — letting you delegate a run to a machine
you *don't* own and get back the same bounded receipt — and the
peer-to-peer layer for it is built and tested. But that layer is
experimental and off by default; the product today is the local one
above. See [The network](#the-network-experimental).

[bwrap]: https://github.com/containers/bubblewrap

---

## How it works

### Identity

Every node holds one 32-byte master seed at `~/.gyza/compositor.key`.
From it the system derives a **compositor** signing key and, per
agent, an independent agent key via HKDF. Self-sovereign: no
certificate authority, no registration server. Two parties that have
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
2. **Execution runs inside the sandbox.** The command or model call
   executes inside [bubblewrap][bwrap] with exactly those bounds,
   kernel-enforced.
3. **Refuse-to-sign-if-not-enforced.** A host-side enforcement
   record (backend, paths, network, memory) is stamped onto the
   result; the runner refuses to sign unless that record is no
   wider than the manifest, and folds it into the artifact so the
   envelope's hash commits to it.
4. **Trustless verification.** The receipt carries the agent's
   manifest bytes. `gyza verify` re-hashes them, re-runs the bounds
   predicate locally, and prints one of five honest verdicts — the
   strongest being `INDEPENDENTLY VERIFIED + RUNNER ATTESTED`.

---

## The network (experimental)

> **Off by default and not part of the local product.** The public
> bootstrap mesh (`gyza.network`) is **currently offline**, and the Go
> daemon it needs (`gyza-netd`) is **not** in the pip/source install —
> build it with `make -C netd build` (Go 1.22+) or put a `gyza-netd`
> binary on PATH. Everything above works without any of this.

Gyza's larger aim is to let you delegate a bounded agent task to a
machine you don't own and get back the same signed, bounded receipt.
Two daemons on loopback already complete a project through a real
comms blackout and bilateral settlement (`gyza demo global --fast`).

You don't need the public mesh to try it — the mesh is just discovery,
and one reachable box restores it:

```bash
# A) Direct — no bootstrap at all. On node A:
gyza global start
gyza global addr                 # prints A's dialable multiaddr(s)
# On node B, dial A directly:
gyza global connect /ip4/<A-ip>/udp/7749/quic-v1/p2p/<A-peer-id>

# B) Your own bootstrap — one box everyone points at:
gyza global start                # on a box with a public IP / forwarded UDP 7749
gyza global addr                 # note its multiaddr
gyza global start --bootstrap /ip4/<box-ip>/udp/7749/quic-v1/p2p/<box-peer-id>
                                 # on every other node; they discover
                                 # each other through it via the DHT
```

Restoring the *public* `gyza.network` mesh needs a reachable host and a
DNS update — see `scripts/deploy-bootstrap.sh`.

### See the loop across two machines

A coordinator delegates a bounded task to a second machine, which runs
it in a real sandbox; the coordinator then **audits the returned work
itself and pays only if it passes**.

```bash
gyza demo loop-host          # on the host; prints an address to share
gyza demo loop-join /ip4/<host-ip>/udp/<port>/quic-v1/p2p/<peer-id>   # on the other machine
```

To see the whole thing in one process first: `gyza demo loop`.

### How the network layer is built

- **Networking.** A Go daemon (`gyza-netd`) owns a libp2p host (QUIC +
  Noise + yamux), a Kademlia DHT for discovery, gossipsub for
  cross-node sync, NAT traversal (DCUtR + circuit relay), and
  DNS-anchored bootstrap with periodic re-resolution.
- **Economic settlement.** A bilateral compute-credit ledger; each
  settled entry is signed by both parties and both ledgers end
  byte-identical, with a reconciliation exchange to heal divergence
  and an EWMA per-peer reputation signal.
- **Capability attestation.** Three tiers gate which agents may claim
  which work. Tier-3 is full proof-of-capability: a *k*-of-*n* quorum
  of independent validators runs the applicant through a canonical
  eval suite and co-signs a certificate, published to the DHT and
  re-verified on every lookup — self-reported tiers are never trusted.

---

## Three implementations

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
signatures** for the same seed and payload (RFC 8032 is deterministic;
the byte parity holds all the way through). A Rust validator and a
Python validator are interchangeable in a quorum.

---

## Security model

**What you get**

- **Tamper-evidence** — any edit to a past envelope breaks its
  signature and every downstream link.
- **Authorship** — every envelope binds to an Ed25519 identity.
- **Bounded execution, independently verifiable** — a verified
  result implies the work ran in a kernel-enforced sandbox no
  wider than the agent's declared manifest.
- **Sybil resistance** for high-tier network work via quorum
  attestation.

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

- Publish to PyPI (`pip install gyza`) with the daemon fetched
  separately.
- Per-host network enforcement (a filtering proxy in the sandbox).
- CPU-time bound checked in the verification predicate.
- Reproducible builds + a signed release manifest, tightening
  runner attestation toward hardware-backed (TEE).
- macOS / Windows signed binaries.
- Broadening the Rust reference implementation.
- Restoring the public `gyza.network` bootstrap mesh.

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
