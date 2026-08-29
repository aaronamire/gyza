# Gyza

**A cryptographic provenance and capability-attenuation layer for AI agent
execution.** Every meaningful action emits one signed envelope binding the
agent's key, its capability manifest, its inputs, its output, and its parent
action. Chains and multi-parent DAGs verify offline, with zero trust in the
machine that produced them. Authority is provably non-increasing down a
delegation chain, and the runner refuses to sign when observed enforcement is
wider than the manifest it was granted.

---

## Status

**A full proposal was submitted to DARPA on 25 August 2026** under BAA
**HR001126S0010** — *Decentralized Artificial Intelligence through Controlled
Emergence* (DICE) — bidding Technical Areas 1 and 2, submission identifier
**HR001126S0010-DICE-FP-052**.

> **Submission is not selection.** No award has been made, no evaluation
> outcome is known, and nothing here is endorsed by DARPA or the U.S.
> Government. The submission is stated because this repository is the evidence
> cited in that proposal, and a reader should know what it was written for.

Maturity: **alpha, Linux, source install.** The single-agent path works today
end to end — run a command in a bubblewrap sandbox, get a signed receipt,
verify it offline on another machine. The distributed layer runs in a local
multi-node testbed. Public bootstrap nodes are offline.

---

## Verify it without trusting us

This is the only claim that matters, so it goes first. Nothing below requires
you to believe a number in this file.

```bash
# Linux x86_64/aarch64, Python 3.10+, bubblewrap (bwrap) for sandboxing.
git clone https://github.com/aaronamire/gyza && cd gyza
pip install -e .

# Run a command in an OS-enforced sandbox -> signed receipt.
gyza exec -- /usr/bin/uname -a

# Turn the run into a bundle anyone can check with no node, no identity,
# and no trust in the machine that made it.
gyza bundle <intent_id> -o run.tar.gz
gyza verify run.tar.gz

# Watch the bounds gate refuse to sign a run that exceeded its manifest.
gyza demo bounds
```

`gyza verify` re-derives every hash and signature from the bundle alone. If it
returns VALID on a machine that has never seen this project, the receipt is
sound; if a byte was altered, it fails. **Nobody outside this project has yet
run that check on a bundle they did not produce** — that is the largest open
credibility gap here and the cheapest one to close.

---

## What this proves, and what it does not

Being precise about the boundary is the point of the design, not a caveat
appended to it.

**Proven, with the code as witness:**

| Property | Where |
|---|---|
| Actions are attributable and tamper-evident; chains and DAGs verify offline | `verify_chain`, `verify_dag` in `gyza/icp.py` |
| Authority is monotone non-increasing down a delegation chain | `verify_delegation` in `gyza/economy/delegation.py` |
| A valid signed envelope implies bounded execution — the runner refuses to sign otherwise | `require_enforcement` in `gyza/runner.py` |
| Balances are a fold over append-only entries; no field an unmodelled path can write behind a guard's back | `gyza/economy/ledger.py`, `wallet.py` |
| One forensic surface composing the real verifiers, failing closed | `audit_provenance` in `gyza/audit.py` |

**Not proven, and not claimed:**

- **Correctness of any output.** Gyza establishes *accountability* (every
  action signed and attributable) and *containment* (every action inside
  granted bounds). Whether a result is *right* is a human decision. This is a
  measured limit, not an omission — see the competence bound below.
- **Containment as a whole.** `can_claim_containment` is currently **false**,
  for one reason: the authority signing key lives on the same host that runs
  agents, so anything able to read that file could re-sign the policy it is
  constrained by. Every other gate is closed and verified.
- **Effects that leave modelled state.** A guard can refuse to *emit*. After
  emission, containment has no meaning and no detector would help.
- **Scale.** The largest configuration measured is **750 agents on one
  coordination board** and 500 across a partitioned pair. Beyond that is
  designed, not demonstrated.
- **Anti-entropy.** Implemented in the demo coordination plane
  (`gyza/demo/gossip.py`) and **not** in the production gossip path. A dropped
  delta there is not currently reconciled; see Known gaps.

---

## Measured, not asserted

Every figure below comes from a preregistered run whose decision rule was
committed before the data existed. The preregistration hash predates every
result artifact in each case.

| Quantity | Value |
|---|---|
| Sandboxed agent actions | **1.95 / sec / physical core** |
| Resident cost per running agent | **2.24 MB** |
| Single-board coordination wall | **750 agents** (first failures at 1,000) |
| Claim exclusion within one board | **0 double-claims** at every count to 750 |
| Duplicate execution across a partition | **100%** — worst case by construction |
| Board agreement after heal | **0 / 20** — last-writer-wins converges the row, not the work |
| Post-heal silent-loss window | **0.400 s + 3.098 × RTT**, R² = 0.907, 17 runs |
| Cheap structural checking, inside competence | J = 0.777, LR = 19.8, n = 433 |

The last two are worth a sentence each.

**The silent-loss window.** After a partition heals, an item published between
the moment the transport reports success and the moment the gossip mesh
re-forms is lost permanently — gossip does not retry, and the CRDT converges
over deltas *received*. Sweeping RTT with `tc netem` gives a two-term model: a
~400 ms floor plus roughly three round trips, which is what a mesh handshake
costs. The loss is a window with a sharp edge — **zero non-monotone runs out
of 17** — not a decaying probability, which is what makes a readiness
predicate a viable remedy rather than only anti-entropy.

**The competence bound.** A preregistered program across six structurally
independent mechanism families found that cheap black-box verification of
natural-language reasoning is bounded by the verifier's competence: *you
cannot cheaply verify what you cannot understand*. Each family was
preregistered with a decision rule before data and each failed for the same
reason from a different direction. The durable positive is that cheap
structural checks do work **inside** the checker's competence, which is the
only regime a bonded market is viable over.

---

## How it works

**Identity.** A local compositor derives per-agent Ed25519 keys from a master
seed via HKDF. No certificate authority. An agent's identity is its key, and a
compositor certificate binds a key to a capability manifest.

**Provenance.** Canonical JSON → BLAKE3 → sign-the-hash with Ed25519. Each
envelope carries the agent pubkey, the manifest hash, input hashes, the output
hash, and parent-envelope hashes. Multi-parent DAGs reconstruct and verify.

**Attenuation.** A `CapabilitySpec` covers five dimensions — read paths, write
paths, a network boolean, a memory cap, and an action rate cap. Delegation is
proven monotone non-increasing, with bounded depth and cycle detection, so a
subcontractor honestly inside its *own* over-wide manifest is still caught at
the `manifest ⊆ delegated` step.

**Execution.** Bubblewrap — unprivileged user namespaces plus seccomp. This is
an **OS-enforced** boundary, not a kernel security boundary, and the
distinction is deliberate. The sandbox is derived from the signed manifest, and
the enforcement record is folded into the artifact so the envelope hash commits
to it.

**Coordination.** libp2p host, Kademlia DHT, gossipsub, and a SQLite-backed
blackboard whose claims are leases rather than deeds — a runner that dies
holding one no longer leaks the work item.

**Formal methods.** TLA+ specifications for settlement, reconciliation and
attestation, each with an honest and an adversarial model, and a Rust
reference implementation with byte-parity fixtures against the Python. *The
TLA+ sources and the invariant catalogue are not in the public tree.*

---

## Research discipline

The unusual thing about this repository is not a feature; it is the record of
being wrong in public.

- **Preregistration before data.** ~50 preregistration documents, each
  committing environment, configurations, decision rules and point predictions
  with a hash that predates every result.
- **A corrections log — 34 entries.** Claims this project made and then had to
  retract, with the mechanism that produced each error.
- **An artifact ledger.** Clean numbers that turned out false, kept with the
  reason each was believed. An exact 0 or 1 is treated as a suspected artifact
  until shown to be definitional.
- **Negative results published.** The competence bound is a negative result.
  So is `ROUTER-DEAD` — difficulty-based routing fails even with an
  AUROC-1.000 oracle. Both closed lines of work this project wanted to keep.
- **Feasibility ceilings computed for both sides** of every comparison,
  including the apparatus, because checking only the system under test has
  produced a meaningless verdict here more than once.

Entry points: `research/PROGRAM_STATUS.md`, `research/FRONTIER_LEDGER.md`,
`research/CORRECTIONS.md`.

---

## Known gaps

Stated because a gap you can read is worth more than one you find.

1. **No production anti-entropy.** A gossip delta lost into a not-yet-formed
   mesh is never reconciled. Work-item deltas now carry their lineage intent so
   that specific failure self-heals, but a lost *claim* or *completion* does
   not. This is the largest correctness gap in the distributed layer.
2. **Authority key colocation.** See Status. It is the single reason
   `can_claim_containment` is false.
3. **Compositor key rotation is deferred**, and a naive implementation would
   pin history to the old key while the live gate reads the new one.
4. **No external verification.** Nobody outside this project has verified a
   bundle.
5. **n = 1.** Every measurement here is of this system. The theorems are
   general; the evidence for them is not.

---

## Tests

```bash
python -m pytest tests/ -q --tb=line --timeout=90     # Python
cd netd    && go test ./... -count=1                  # Go daemon
cd gyza-rs && cargo test --workspace                  # Rust reference (111 tests)
```

The Rust crates carry parity tests against fixtures generated from the Python,
so a divergence in canonical encoding fails the build rather than producing two
implementations that quietly disagree.

---

## Layout

```
gyza/        Python — the product
  icp.py         signed envelopes; chain and DAG verification
  audit.py       the unified forensic verdict; fails closed
  runner.py      claim / execute / sign; the bounds gate
  economy/       delegation attenuation, append-only ledger, settlement
  containment/   harm model, signed guard config, readiness
  network/       libp2p client, DHT, gossip, artifact store
  sandbox/       bubblewrap executor and enforcement records
netd/        Go — the libp2p daemon
gyza-rs/     Rust — reference implementation, byte-parity with Python
research/    preregistrations, findings, corrections, artifact ledger
tests/       pytest
```

---

## License

See `LICENSE`. Issues and independent verification attempts are welcome; a
failed `gyza verify` on a bundle this project produced is the most useful bug
report possible.
