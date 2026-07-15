# Gyza

**A working substrate for decentralized AI coordination with *controlled
emergence*: self-organizing collectives of agents whose every action is
cryptographically attributable, provably bounded, and resilient to the
loss or compromise of any member — no central orchestrator, no trusted
operator.**

This is the problem DARPA's **DICE** program — *Decentralized
Artificial Intelligence through Controlled Emergence*, BAA
**HR001126S0010** — was created to solve: harnessing self-organizing
agent collectives while "ensuring that the collective behavior remains
predictable and aligned with intended outcomes," resilient to
"failure or compromise of individual agents" in "contested
environments," and "under our control." Gyza is an existing,
running system built independently against that same problem. It does
not implement DICE's TA2 (inference-time control); it implements the
**coordination, consensus, and provable-containment substrate** —
where "controlled emergence" is enforced not by steering a model's
internals but by making every agent action *signed, attributable, and
cryptographically bounded*, with misbehavior detectable and slashable.

At the level of one agent, Gyza is a seatbelt and a flight recorder:
run any agent or command in a kernel-enforced sandbox and get a
receipt anyone can verify. At the level of a collective, those
receipts are the accountability layer that makes emergence
*controlled* rather than merely hoped-for.

**Status:** alpha, Linux, open source. The single-agent product works
today from a source install (`gyza exec` → signed receipt → offline
`gyza verify`). The decentralized layer is demonstrated in a **local
multi-node testbed** (peer-to-peer coordination, a real comms blackout
and self-heal, quorum attestation, bilateral settlement); the public
mesh is offline and thousand-agent scale is designed, not yet shown.
Honest maturity per capability is in the crosswalk below.

---

## How Gyza maps to DICE (BAA HR001126S0010)

DICE asks for revolutionary advances in "artificial intelligence,
control theory, formal methods, and game theory" to build
decentralized agent collectives that are **scalable, adaptable, and
resilient** and that "remain under our control." Here is what Gyza
actually provides against each, with honest maturity — *demonstrated*
(runnable today), *shipped* (in the codebase), or *designed*
(architected, not yet shown).

| DICE requirement | Gyza mechanism | Maturity |
|---|---|---|
| **TA1 — peer-to-peer self-organization & task allocation** | libp2p host + Kademlia DHT discovery + gossipsub; agents claim work items with no central scheduler | **demonstrated** (local testbed) |
| **TA1 — distributed consensus** | Raft LAN clustering; k-of-n quorum attestation; bilateral settlement to byte-identical ledgers; content-addressed CRDT coordination plane + anti-entropy gossip | **demonstrated** (local) |
| **Resilience to agent loss / compromise** | comms-blackout partition survival + self-heal; tamper-evident provenance chains; verify-on-fetch (self-reported trust is *never* accepted); Sybil resistance via quorum | **demonstrated** (partition + injection demos) |
| **Contested / DDIL environments** | denied/degraded/intermittent-comms partition scenario; a provenance chain that still verifies across a full blackout | **demonstrated** (clean cut; 40%-loss/latency harness is roadmap) |
| **Controlled emergence / "remain under our control"** | the *bounds-proof*: execution is derived from a signed capability manifest and the runner refuses to sign unless enforcement ⊆ manifest; tiered capability attestation; approval gates | **demonstrated** (bounds demo) |
| **Adversarial robustness (Phase 2 focus)** | tamper of a signed record is caught; a forged enforcement record breaks verification; out-of-bounds work is never signed; a compromised validator can't forge a quorum cosig | **demonstrated** |
| **Formal methods** | TLA+ behavioral specs (Settlement, Reconciliation, Attestation — honest *and* adversarial TLC models), ~120 named invariants, a Rust reference implementation with byte-parity to the Python | **shipped** |
| **Scalability to thousands of agents (Phase 3 focus)** | DHT + gossip topology designed for it | **designed** — not yet demonstrated at scale |
| **TA2 — local inference control** (activation steering, memory editing, context engineering) | *out of scope for Gyza* — Gyza controls the **capability and coordination** layer, not a model's internal reasoning | **gap** (complementary to a TA2 effort, not a substitute) |

**The distinctive claim.** DICE's hard problem is letting a collective
*self-organize* while staying *controllable*. Gyza's answer is not to
constrain what agents think but to make what they **do**
non-repudiable and provably bounded: emergence you can audit after the
fact and contain before it happens. That is a coordination-and-safety
substrate a DICE effort can build on or evaluate against — strongest as
a **TA1** contribution and as **TA3** verification infrastructure, and
honestly dependent on a TA2 partner for inference-time control.

---

## What actually works today — try it in ~2 minutes

The single-agent product needs no network and no daemon. Everything
below is real, runnable, and honest about what it proves.

```bash
# Linux x86_64/aarch64, Python 3.10+, plus bubblewrap (bwrap).
git clone https://github.com/aaronamire/gyza && cd gyza
pip install -e .                 # PyPI publish is on the roadmap
gyza init                        # 32-byte master seed at ~/.gyza/compositor.key

# Run any command in a kernel-enforced sandbox → signed receipt.
gyza exec --allow-read . -- ls -la

# Turn the run into a receipt anyone can verify — no node, no identity,
# no trust in you.
gyza bundle <intent-id> -o receipt.json
gyza verify receipt.json
```

The verifier recomputes every line locally, with zero trust in the
machine that produced the run:

```
INDEPENDENT VERIFICATION
signature:      ✓ VALID
artifact hash:  ✓ MATCHES envelope
manifest hash:  ✓ MATCHES envelope
bounds check:   ✓ enforcement ⊆ manifest (re-verified here)
✓ bounded (INDEPENDENTLY VERIFIED)
```

Demonstrations, all offline unless noted:

```bash
gyza demo bounds       # controlled emergence at one agent: signed → verified,
                       # tampered → caught, out-of-bounds → never signed. ~2 s.
gyza demo injection    # tamper a provenance chain, re-verify, watch it fail
gyza demo pipeline     # two agents, a signed provenance chain
gyza demo global --fast # local two-daemon testbed: peer-to-peer coordination,
                        # a real comms blackout + self-heal, quorum-checked
                        # settlement, a chain that verifies across the blackout
```

`gyza demo global --fast` is the decentralized story in miniature: two
independent daemons form a collective, one goes dark for 3 seconds, the
mesh heals, credits settle to byte-identical ledgers, and the resulting
provenance chain verifies across the outage — the DICE resilience
property, demonstrated on one machine.

---

## How it works

### Identity — self-sovereign, no CA

Every node holds one 32-byte master seed at `~/.gyza/compositor.key`.
From it the system derives a **compositor** signing key and, per agent,
an independent agent key via HKDF. No certificate authority, no
registration server. Two agents that have never met verify each other's
signatures from public keys alone — the trust primitive a
no-central-orchestrator collective needs.

### Provenance — the ICP envelope

Every meaningful action emits one `ICPEnvelope`: `agent_pubkey`,
`capability_manifest_hash`, `input_hashes`, `output_hash`,
`parent_envelope_hash`, model, timing, signature. Canonical JSON →
BLAKE3 hash → Ed25519-sign-the-hash. Each envelope's
`parent_envelope_hash` pins the previous one, so the chain is
structurally immutable: edit any past field and its signature breaks;
splice in a fake envelope and the next real one's parent link breaks.
`gyza demo injection` proves this live.

### Controlled emergence — the bounds-proof

The distinctive piece, and Gyza's answer to "remain under our control":

1. **The manifest is the source of truth.** An agent's sandbox
   (filesystem read/write, network, memory) is derived directly from
   its signed capability manifest.
2. **Execution runs inside the sandbox** — the command or model call
   executes inside [bubblewrap](https://github.com/containers/bubblewrap),
   kernel-enforced.
3. **Refuse-to-sign-if-not-enforced.** A host-side enforcement record
   is stamped onto the result; the runner refuses to sign unless that
   record is no wider than the manifest, and folds it into the artifact
   so the envelope's hash commits to it.
4. **Trustless verification.** The receipt carries the manifest bytes;
   `gyza verify` re-hashes them, re-runs the bounds predicate locally,
   and returns one of five honest verdicts.

The consequence: a valid signature *implies* the work ran inside
declared, kernel-enforced bounds. An agent cannot exceed its granted
capabilities and still produce a valid receipt. That is emergence made
containable at the individual level and auditable at the collective
level.

### Decentralized coordination & consensus

A Go daemon (`gyza-netd`) owns a libp2p host (QUIC + Noise + yamux), a
Kademlia DHT for discovery, gossipsub for cross-node sync, NAT
traversal (DCUtR + circuit relay), and DNS-anchored bootstrap with
periodic re-resolution. Agents self-organize and claim work with no
central scheduler. A bilateral compute-credit ledger settles work
between peers — each entry signed by both parties, both ledgers
byte-identical, with a reconciliation exchange to heal divergence and
an EWMA reputation signal. High-trust work is gated by **tiered
capability attestation**: a *k*-of-*n* quorum of independent validators
runs an applicant through a canonical eval suite and co-signs a
certificate, re-verified on every lookup — self-reported capability is
never trusted.

### Formal methods

The wire protocol is specified in TLA+ (`spec/`) with honest and
adversarial TLC models that pass; ~120 named invariants live in
`docs/invariants.md`; a Rust reference implementation (`gyza-rs/`)
holds byte-parity with the Python for hashing, signatures, key
derivation, canonical encodings, settlement, and the attestation
protocol — including **byte-identical Ed25519 cosigns** cross-language,
so a Rust validator and a Python validator are interchangeable in a
quorum. Alternative implementations and formal verification are
first-class, not afterthoughts.

---

## Security model

**What you get**

- **Tamper-evidence** — any edit to a past envelope breaks its
  signature and every downstream link.
- **Authorship** — every action binds to an Ed25519 identity.
- **Bounded execution, independently verifiable** — a verified result
  implies the work ran in a kernel-enforced sandbox no wider than the
  agent's declared manifest.
- **Resilience to compromise** — Sybil resistance and forged-quorum
  resistance for high-tier work via k-of-n attestation; a compromised
  agent cannot forge others' cosigns or exceed its bounds undetected.

**What you do not get (honest limits)**

- **Inference-time control** — Gyza bounds what an agent may *do*, not
  what a model *reasons*; it is complementary to DICE TA2, not a
  substitute.
- **Demonstrated scale** — the collective is shown at two nodes on
  loopback, not thousands; scale is designed, not proven.
- **Confidentiality** — envelopes are signed, not encrypted; artifacts
  are plaintext.
- **Fully trustless runner identity** — the runner self-reports its
  build; closing this fully needs reproducible builds + hardware
  attestation (TEE). The output labels this honestly.
- **Live global network** — the public bootstrap mesh (`gyza.network`)
  is currently offline; use direct dial or a self-hosted bootstrap
  (below).

Honesty about the limits is deliberate — it is what makes the verdicts,
and any claim of alignment, trustworthy.

---

## The network (experimental)

> Off by default and not required for the single-agent product. The Go
> daemon is not in the pip install — build it with `make -C netd build`
> (Go 1.22+). The public mesh is offline; the demos above run a local
> testbed, and the paths below connect real machines without it.

```bash
# Direct dial — no bootstrap at all:
gyza global start && gyza global addr        # node A prints its multiaddr
gyza global connect /ip4/<A-ip>/udp/7749/quic-v1/p2p/<A-peer-id>   # node B

# Or one self-hosted bootstrap everyone points at:
gyza global start --bootstrap /ip4/<box-ip>/udp/7749/quic-v1/p2p/<box-peer-id>
```

Two-machine delegation with independent audit-before-pay:
`gyza demo loop-host` on one box, `gyza demo loop-join <multiaddr>` on
another. Restoring the public mesh needs a reachable host + a DNS
update (`scripts/deploy-bootstrap.sh`).

---

## Running the tests

```bash
python -m pytest tests/ -q --tb=line --timeout=90 \
  -k "not netd_client and not phase2_integration and not phase2_hardening \
      and not blackboard_gossip and not attestation_bridge and not verify_on_fetch"
cd netd && go test ./... -count=1 -timeout=120s     # Go daemon
cd gyza-rs && cargo test --workspace                # Rust reference impl
```

~640 Python fast tests + the Go suite + the Rust workspace (94 tests
across 7 crates). CI runs the fast slice and the Go/Rust suites on
every push. TLA+ models are model-checked with TLC (`spec/`).

---

## Layout

```
gyza/      Python — execution, identity, ICP, ledger, sandbox, CLI
netd/      Go — the gyza-netd daemon (libp2p, DHT, NAT, gossip)
gyza-rs/   Rust — reference implementation (byte-parity with Python)
spec/      TLA+ formal specifications + TLC models
docs/      invariants, state machines, wire protocol, ADRs
demo/      runnable end-to-end demonstrations
tests/     pytest suite
```

---

## References

- DARPA DICE program — *Decentralized Artificial Intelligence through
  Controlled Emergence*:
  <https://www.darpa.mil/research/programs/decentralized-artificial-intelligence-through-controlled-emergence>
- Solicitation **BAA HR001126S0010** (full proposals due 2026-08-25).

Gyza is an independent open-source project. Any reference to DICE
describes problem alignment, not affiliation with or endorsement by
DARPA or the U.S. Government.

## License

Apache 2.0. See `LICENSE`.
